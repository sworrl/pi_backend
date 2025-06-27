# ==============================================================================
# pi_backend - Astronomy Services
# Version: 3.3.7 (Fix Application Context)
# ==============================================================================
# This script provides a comprehensive suite of astronomical data by aggregating
# data from multiple sources.
#
# Changelog (v3.3.7):
# - FIX: Modified `get_full_sky_data` to accept `db_manager` and `config_manager`
#   explicitly, ensuring internal calls (like for TLE file paths) can access
#   configuration from the database.
# - REFACTOR: Updated `eph` and `ts` initialization to ensure `load` is correctly
#   configured with `config_manager` when retrieving paths from DB.
#
# Changelog (v3.3.6):
# - ROBUSTNESS: Wrapped the loading of the ephemeris data file (eph) in a
#   try...except block. If the file is empty or corrupt (causing a ValueError),
#   the script will now log a warning and continue, rather than crashing the
#   entire API worker. This makes the system resilient to download failures.
#
# Changelog (v3.3.5):
# - CRITICAL FIX: Corrected the Skyfield initialization logic.
# ==============================================================================

import requests
import sys
import time
from datetime import datetime, timedelta
import concurrent.futures
import os
import logging

try:
    from skyfield.api import Loader, Topos
    SKYFIELD_AVAILABLE = True
except ImportError:
    SKYFIELD_AVAILABLE = False
    logging.critical("Skyfield library not found. Please run 'pip install skyfield'. Satellite and planet calculations will fail.")

__version__ = "3.3.7"

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

# Global instances (will be initialized on first access or by explicit function call)
eph = None
ts = None
_skyfield_loader_instance = None # To hold the Loader instance

def _initialize_skyfield(config_manager):
    """Initializes Skyfield components, reading paths from config_manager."""
    global eph, ts, _skyfield_loader_instance

    if not SKYFIELD_AVAILABLE:
        logging.error("Skyfield is not available. Cannot initialize for astronomy services.")
        return

    if eph is not None and ts is not None and _skyfield_loader_instance is not None:
        logging.debug("Skyfield already initialized.")
        return # Already initialized

    try:
        # Paths from config_manager
        skyfield_data_dir = config_manager.get('SystemPaths', 'skyfield_data_dir', fallback="/var/lib/pi_backend/skyfield-data")
        ephemeris_file = os.path.join(skyfield_data_dir, 'de442s.bsp') # Note: using de442s.bsp
        
        # 1. Instantiate the Loader class.
        _skyfield_loader_instance = Loader(skyfield_data_dir)
        
        # 2. Use the loader instance to get the timescale.
        ts = _skyfield_loader_instance.timescale()

        # 3. **Resiliently** load the ephemeris file.
        if os.path.exists(ephemeris_file):
            try:
                eph = _skyfield_loader_instance(ephemeris_file)
                logging.info(f"Successfully loaded Skyfield ephemeris data ({ephemeris_file}).")
            except ValueError as e:
                logging.error(f"!!! Ephemeris file '{ephemeris_file}' is corrupt or empty: {e}")
                logging.error("!!! Planet visibility calculations will be disabled until the file is redownloaded.")
                eph = None # Ensure eph is None so dependent functions fail gracefully
        else:
            logging.warning(f"Ephemeris file not found at '{ephemeris_file}'. Planet visibility will be disabled.")
            eph = None

    except Exception as e:
        logging.critical(f"A critical error occurred during Skyfield initialization: {e}", exc_info=True)
        # Reset to ensure dependent functions know Skyfield is not ready
        eph = None
        ts = None
        _skyfield_loader_instance = None

# --- Individual Data Fetching Functions ---

# Modified to accept config_manager for TLE file path
def get_satellite_passes(lat, lon, search_term=None, satellite_id=None, days=2, config_manager=None):
    if not SKYFIELD_AVAILABLE or config_manager is None: 
        return {"error": "Skyfield library not installed or config_manager is missing."}
    
    # Ensure Skyfield is initialized before using it
    _initialize_skyfield(config_manager)
    if ts is None or _skyfield_loader_instance is None:
        return {"error": "Skyfield initialization failed. Cannot calculate satellite passes."}

    satellite_tle_file = config_manager.get('Polling', 'tle_file_path', fallback="/var/lib/pi_backend/skyfield-data/active.txt")
    if not os.path.exists(satellite_tle_file):
        return {"error": f"Satellite TLE file missing at {satellite_tle_file}. Cannot calculate passes."}

    try:
        # Use the already initialized _skyfield_loader_instance
        all_satellites = _skyfield_loader_instance.tle_file(satellite_tle_file)
        found_satellites = []

        if satellite_id:
            satellite = next((s for s in all_satellites if s.model.satnum == int(satellite_id)), None)
            if satellite:
                found_satellites.append(satellite)
        elif search_term:
            found_satellites = [s for s in all_satellites if search_term.lower() in s.name.lower()]
        
        if not found_satellites:
            return {"error": f"No satellites found matching the criteria.", "search_term": search_term, "id": satellite_id}

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
                if event_name == 'rise':
                    current_pass = {'start': {}}
                    alt, az, _ = (satellite - location).at(ti).altaz()
                    current_pass['start']['time_utc'] = ti.utc_iso()
                    current_pass['start']['azimuth'] = round(az.degrees, 2)
                    current_pass['start']['altitude'] = round(alt.degrees, 2)
                
                elif event_name == 'culminate' and 'start' in current_pass:
                    current_pass['peak'] = {}
                    alt, az, _ = (satellite - location).at(ti).altaz()
                    current_pass['peak']['time_utc'] = ti.utc_iso()
                    current_pass['peak']['azimuth'] = round(az.degrees, 2)
                    current_pass['peak']['altitude'] = round(alt.degrees, 2)

                elif event_name == 'set' and 'start' in current_pass:
                    current_pass['end'] = {}
                    alt, az, _ = (satellite - location).at(ti).altaz()
                    current_pass['end']['time_utc'] = ti.utc_iso()
                    current_pass['end']['azimuth'] = round(az.degrees, 2)
                    current_pass['end']['altitude'] = round(alt.degrees, 2)
                    
                    start_dt = datetime.fromisoformat(current_pass['start']['time_utc'].replace('Z', '+00:00'))
                    end_dt = datetime.fromisoformat(current_pass['end']['time_utc'].replace('Z', '+00:00'))
                    current_pass['duration_minutes'] = round((end_dt - start_dt).total_seconds() / 60, 2)

                    passes.append(current_pass)
                    current_pass = {}
            
            if passes:
                 results[f"{satellite.name} ({satellite.model.satnum})"] = passes

        return {"search_results": results}
    except Exception as e:
        logging.error(f"Error calculating satellite passes: {e}", exc_info=True)
        return {"error": str(e)}

# Modified to accept config_manager for ephemeris initialization
def get_planet_visibility(lat, lon, config_manager=None):
    if not SKYFIELD_AVAILABLE or config_manager is None: 
        return {"error": "Skyfield library not installed or config_manager is missing."}
    
    _initialize_skyfield(config_manager) # Ensure eph and ts are initialized with current config
    if not eph: 
        return {"error": "Planet visibility calculations disabled: Ephemeris data file (de442s.bsp) is unavailable or corrupt."}

    try:
        location = Topos(latitude_degrees=lat, longitude_degrees=lon)
        t0 = ts.now()
        t1 = ts.utc(t0.utc_datetime() + timedelta(days=1))
        
        planets = {"mercury": eph['mercury'], "venus": eph['venus'], "mars": eph['mars'], 
                   "jupiter": eph['jupiter barycenter'], "saturn": eph['saturn barycenter']}
        
        visibility_data = {}
        for name, body in planets.items():
            t, y = body.find_events(location, t0, t1, altitude_degrees=0.0)
            event_names = ['rise', 'transit', 'set']
            events = {}
            for ti, event in zip(t, y):
                events[event_names[event]] = ti.utc_iso()
            visibility_data[name] = events

        return visibility_data
    except Exception as e:
        logging.error(f"Error calculating planet visibility: {e}", exc_info=True)
        return {"error": str(e)}
        
def get_major_meteor_showers():
    """Returns a static list of major meteor showers for the year."""
    year = datetime.now().year
    return {
        "source": "American Meteor Society (AMS) / Hardcoded",
        "showers": [
            {"name": "Quadrantids", "peak_date": f"{year}-01-03", "radiant": "Boötes", "zhr": 120},
            {"name": "Lyrids", "peak_date": f"{year}-04-22", "radiant": "Lyra", "zhr": 18},
            {"name": "Eta Aquarids", "peak_date": f"{year}-05-05", "radiant": "Aquarius", "zhr": 55},
            {"name": "Delta Aquarids", "peak_date": f"{year}-07-28", "radiant": "Aquarius", "zhr": 20},
            {"name": "Perseids", "peak_date": f"{year}-08-12", "radiant": "Perseus", "zhr": 100},
            {"name": "Orionids", "peak_date": f"{year}-10-21", "radiant": "Orion", "zhr": 20},
            {"name": "Leonids", "peak_date": f"{year}-11-17", "radiant": "Leo", "zhr": 15},
            {"name": "Geminids", "peak_date": f"{year}-12-14", "radiant": "Gemini", "zhr": 120},
            {"name": "Ursids", "peak_date": f"{year}-12-22", "radiant": "Ursa Minor", "zhr": 10},
        ]
    }

# --- Main Orchestration Function ---
def get_full_sky_data(lat, lon, db_manager=None, config_manager=None):
    """
    Orchestrates fetching core astronomical data (sun, moon, planets, space weather).
    Requires db_manager and config_manager for dependency injection.
    """
    if db_manager is None or config_manager is None:
        return {"error": "Database/Config Manager not provided for astronomy services."}

    # Ensure Skyfield is initialized first for all dependent functions
    _initialize_skyfield(config_manager) 
    
    cache_key = f"full_{lat:.2f}_{lon:.2f}"
    cached_data = _get_from_cache(cache_key)
    if cached_data:
        return cached_data

    results = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
        future_map = {
            executor.submit(get_base_astronomy_data, lat, lon): "base_astronomy",
            executor.submit(get_space_weather_data): "space_weather",
            executor.submit(get_planet_visibility, lat, lon, config_manager): "planet_visibility", # Pass config_manager
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
