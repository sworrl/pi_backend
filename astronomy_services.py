# ==============================================================================
# pi_backend - Astronomy Services
# Version: 3.3.8 (Implement Base Astronomy & Fix NameError)
# ==============================================================================
# This script provides a comprehensive suite of astronomical data.
#
# Changelog (v3.3.8):
# - FIX: Implemented the missing `get_base_astronomy_data` function to calculate
#   Sun and Moon rise/set times, resolving a NameError.
# - REFACTOR: Consolidated all astronomy data fetching under the existing
#   `get_full_sky_data` to ensure a consistent data structure.
# ==============================================================================

import requests
import sys
import time
from datetime import datetime, timedelta
import concurrent.futures
import os
import logging

try:
    from skyfield.api import Loader, Topos, Star
    from skyfield.framelib import ecliptic_frame
    SKYFIELD_AVAILABLE = True
except ImportError:
    SKYFIELD_AVAILABLE = False
    logging.critical("Skyfield library not found. Please run 'pip install skyfield'. Satellite and planet calculations will fail.")

__version__ = "3.3.8"

# --- Caching ---
_astro_cache = {}
CACHE_EXPIRY_SECONDS = 3 * 3600

def _get_from_cache(key):
    if key in _astro_cache:
        entry_time, data = _astro_cache[key]
        if (time.time() - entry_time) < CACHE_EXPIRY_SECONDS:
            return data
    return None

def _set_in_cache(key, data):
    _astro_cache[key] = (time.time(), data)

# Global instances
eph = None
ts = None
_skyfield_loader_instance = None

def _initialize_skyfield(config_manager):
    """Initializes Skyfield components, reading paths from config_manager."""
    global eph, ts, _skyfield_loader_instance
    if not SKYFIELD_AVAILABLE: return
    if eph is not None and ts is not None: return

    try:
        skyfield_data_dir = config_manager.get('SystemPaths', 'skyfield_data_dir', fallback="/var/lib/pi_backend/skyfield-data")
        ephemeris_file = os.path.join(skyfield_data_dir, 'de442s.bsp')
        
        _skyfield_loader_instance = Loader(skyfield_data_dir)
        ts = _skyfield_loader_instance.timescale()

        if os.path.exists(ephemeris_file):
            eph = _skyfield_loader_instance(ephemeris_file)
            logging.info(f"Successfully loaded Skyfield ephemeris data ({ephemeris_file}).")
        else:
            logging.warning(f"Ephemeris file not found at '{ephemeris_file}'. Planet/Sun/Moon visibility will be disabled.")
            eph = None
    except Exception as e:
        logging.critical(f"A critical error occurred during Skyfield initialization: {e}", exc_info=True)
        eph = ts = _skyfield_loader_instance = None

# *** FIX: Implemented the missing function to calculate Sun and Moon events. ***
def get_base_astronomy_data(lat, lon, config_manager=None):
    """
    Calculates rise and set times for the Sun and Moon.
    """
    if not SKYFIELD_AVAILABLE or config_manager is None: 
        return {"error": "Skyfield library not installed or config_manager is missing."}
    
    _initialize_skyfield(config_manager)
    if not eph or not ts: 
        return {"error": "Base astronomy calculations disabled: Ephemeris data unavailable."}

    location = Topos(latitude_degrees=lat, longitude_degrees=lon)
    t0 = ts.now()
    t1 = ts.utc(t0.utc_datetime() + timedelta(days=1))
    
    results = {}
    
    # Sun Events
    try:
        t_sun, y_sun = eph['sun'].find_events(location, t0, t1, altitude_degrees=0.0)
        sun_events = {['rise', 'transit', 'set'][event]: time.utc_iso() for time, event in zip(t_sun, y_sun)}
        results['sun'] = sun_events
    except Exception as e:
        results['sun'] = {'error': str(e)}

    # Moon Events & Phase
    try:
        t_moon, y_moon = eph['moon'].find_events(location, t0, t1, altitude_degrees=0.0)
        moon_events = {['rise', 'transit', 'set'][event]: time.utc_iso() for time, event in zip(t_moon, y_moon)}
        
        # Calculate moon phase
        sun = eph['sun']
        moon = eph['moon']
        earth = eph['earth']
        e = earth.at(t0)
        _, slon, _ = e.observe(sun).apparent().frame_latlon(ecliptic_frame)
        _, mlon, _ = e.observe(moon).apparent().frame_latlon(ecliptic_frame)
        moon_phase_angle = (mlon.degrees - slon.degrees) % 360.0
        moon_events['phase_degrees'] = round(moon_phase_angle, 2)
        moon_events['phase_description'] = ["New Moon", "Waxing Crescent", "First Quarter", "Waxing Gibbous", "Full Moon", "Waning Gibbous", "Last Quarter", "Waning Crescent"][int(moon_phase_angle / 45)]

        results['moon'] = moon_events
    except Exception as e:
        results['moon'] = {'error': str(e)}
        
    return results

def get_satellite_passes(lat, lon, search_term=None, satellite_id=None, days=2, config_manager=None):
    if not SKYFIELD_AVAILABLE or config_manager is None: 
        return {"error": "Skyfield library not installed or config_manager is missing."}
    _initialize_skyfield(config_manager)
    if ts is None or _skyfield_loader_instance is None:
        return {"error": "Skyfield initialization failed."}

    satellite_tle_file = config_manager.get('Polling', 'tle_file_path', fallback="/var/lib/pi_backend/skyfield-data/active.txt")
    if not os.path.exists(satellite_tle_file):
        return {"error": f"Satellite TLE file missing at {satellite_tle_file}."}

    try:
        all_satellites = _skyfield_loader_instance.tle_file(satellite_tle_file)
        found_satellites = []

        if satellite_id:
            satellite = next((s for s in all_satellites if s.model.satnum == int(satellite_id)), None)
            if satellite: found_satellites.append(satellite)
        elif search_term:
            found_satellites = [s for s in all_satellites if search_term.lower() in s.name.lower()]
        
        if not found_satellites:
            return {"error": "No satellites found."}

        location = Topos(latitude_degrees=lat, longitude_degrees=lon)
        t0 = ts.now()
        t1 = ts.utc(t0.utc_datetime() + timedelta(days=days))

        results = {}
        for satellite in found_satellites:
            times, events = satellite.find_events(location, t0, t1, altitude_degrees=10.0)
            event_names = ['rise', 'culminate', 'set']
            passes = []
            current_pass = {}
            for ti, event in zip(times, events):
                event_name = event_names[event]
                alt, az, _ = (satellite - location).at(ti).altaz()
                if event_name == 'rise':
                    current_pass = {'start': {'time_utc': ti.utc_iso(), 'azimuth': round(az.degrees, 2)}}
                elif event_name == 'peak' and 'start' in current_pass:
                     current_pass['peak'] = {'time_utc': ti.utc_iso(), 'azimuth': round(az.degrees, 2), 'altitude': round(alt.degrees, 2)}
                elif event_name == 'set' and 'start' in current_pass:
                    current_pass['end'] = {'time_utc': ti.utc_iso(), 'azimuth': round(az.degrees, 2)}
                    start_dt = datetime.fromisoformat(current_pass['start']['time_utc'].replace('Z', '+00:00'))
                    end_dt = datetime.fromisoformat(current_pass['end']['time_utc'].replace('Z', '+00:00'))
                    current_pass['duration_minutes'] = round((end_dt - start_dt).total_seconds() / 60, 2)
                    passes.append(current_pass)
                    current_pass = {}
            if passes:
                 results[f"{satellite.name} ({satellite.model.satnum})"] = passes
        return {"search_results": results}
    except Exception as e:
        return {"error": str(e)}

def get_planet_visibility(lat, lon, config_manager=None):
    if not SKYFIELD_AVAILABLE or config_manager is None: return {"error": "Skyfield not available."}
    _initialize_skyfield(config_manager)
    if not eph: return {"error": "Ephemeris data unavailable."}

    location = Topos(latitude_degrees=lat, longitude_degrees=lon)
    t0 = ts.now()
    t1 = ts.utc(t0.utc_datetime() + timedelta(days=1))
    planets = {"mercury": eph['mercury'], "venus": eph['venus'], "mars": eph['mars'], "jupiter": eph['jupiter barycenter'], "saturn": eph['saturn barycenter']}
    visibility_data = {}
    for name, body in planets.items():
        t, y = body.find_events(location, t0, t1, altitude_degrees=0.0)
        visibility_data[name] = {['rise', 'transit', 'set'][event]: ti.utc_iso() for ti, event in zip(t, y)}
    return visibility_data
        
def get_major_meteor_showers():
    year = datetime.now().year
    return { "source": "American Meteor Society (AMS) / Hardcoded", "showers": [{"name": "Quadrantids", "peak_date": f"{year}-01-03"}, {"name": "Lyrids", "peak_date": f"{year}-04-22"}, {"name": "Eta Aquarids", "peak_date": f"{year}-05-05"}, {"name": "Perseids", "peak_date": f"{year}-08-12"}, {"name": "Geminids", "peak_date": f"{year}-12-14"}] }

# --- Main Orchestration Function ---
def get_full_sky_data(lat, lon, db_manager=None, config_manager=None):
    if db_manager is None or config_manager is None:
        return {"error": "Database/Config Manager not provided."}
    _initialize_skyfield(config_manager)
    
    cache_key = f"full_{lat:.2f}_{lon:.2f}"
    cached_data = _get_from_cache(cache_key)
    if cached_data: return cached_data

    results = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
        future_map = {
            executor.submit(get_base_astronomy_data, lat, lon, config_manager): "base_astronomy",
            executor.submit(get_planet_visibility, lat, lon, config_manager): "planet_visibility",
            executor.submit(get_major_meteor_showers): "meteor_showers",
        }
        for future in concurrent.futures.as_completed(future_map):
            key = future_map[future]
            try:
                results[key] = future.result()
            except Exception as e:
                results[key] = {"error": str(e)}
    
    _set_in_cache(cache_key, results)
    return results
