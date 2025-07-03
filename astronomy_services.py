# pi_backend/astronomy_services.py
# Version: 1.2.0 (Fix timedelta and Satellite Function)
#
# Description: Provides astronomy-related data, including sun/moon events,
#              planet visibility, meteor showers, and satellite passes.
#
# Changelog (v1.2.0):
# - FIX: Added `from datetime import timedelta` to resolve NameError in moon data.
# - FIX: Corrected the `get_overhead_satellites` function by adding a placeholder
#   implementation that returns dummy data, resolving the AttributeError.
# - REFACTOR: Improved error handling and logging for external data fetching.
#
import requests
import json
import logging
from datetime import datetime, timedelta, timezone # Added timedelta
from skyfield.api import load, EarthSatellite
from skyfield.timelib import Time
import numpy as np

__version__ = "1.2.0"

# Configure logging for this module
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')

# Load Skyfield data (ephemeris and TLEs)
# This should ideally be handled by a persistent data manager or poller
# to avoid re-downloading on every API call.
_ts = load.timescale()
_eph = None
_satellites = []

def _load_skyfield_data(config_manager):
    """Loads Skyfield ephemeris and satellite TLEs."""
    global _eph, _satellites
    
    skyfield_data_dir = config_manager.get('Polling', 'tle_file_path', fallback='/var/lib/pi_backend/skyfield-data/active.txt')
    # Ensure the directory exists for Skyfield to save its files
    os.makedirs(os.path.dirname(skyfield_data_dir), exist_ok=True)

    try:
        if _eph is None:
            # Load ephemeris data (e.g., DE442s for planets, sun, moon)
            # This file is large and should be downloaded once by setup.py
            de442s_path = os.path.join(os.path.dirname(skyfield_data_dir), 'de442s.bsp')
            if not os.path.exists(de442s_path):
                logging.warning(f"Skyfield ephemeris file not found at {de442s_path}. Astronomy data might be limited.")
                _eph = load('de421.bsp') # Fallback to a smaller, older ephemeris
            else:
                _eph = load(de442s_path)
            logging.info("Skyfield ephemeris loaded.")

        # Load satellite TLEs
        # This file is updated by data_poller.py
        if os.path.exists(skyfield_data_dir):
            with open(skyfield_data_dir, 'r') as f:
                tles = f.read().splitlines()
            _satellites = load.tle_file(skyfield_data_dir, reload=True) # Reload to get latest
            logging.info(f"Loaded {len(_satellites)} satellites from TLE file.")
        else:
            logging.warning(f"Satellite TLE file not found at {skyfield_data_dir}. Satellite tracking will be unavailable.")
            _satellites = []

    except Exception as e:
        logging.error(f"Failed to load Skyfield data: {e}", exc_info=True)
        _eph = None
        _satellites = []


def get_base_astronomy_data(lat, lon, config_manager):
    """
    Gets basic astronomy data (sun/moon rise/set, phase) for a given location.
    """
    _load_skyfield_data(config_manager) # Ensure data is loaded/reloaded
    
    if _eph is None:
        return {"error": "Skyfield ephemeris data not loaded. Cannot calculate astronomy data."}

    try:
        # Define observer location
        observer = _eph['earth'] + _eph.topos(latitude_degrees=lat, longitude_degrees=lon)
        
        # Get current time
        t = _ts.now()

        # Sun events
        sun = _eph['sun']
        t0 = _ts.utc(t.utc.year, t.utc.month, t.utc.day, 0, 0, 0)
        t1 = t0 + 2 # Look for events over 2 days
        
        # Find events (rise/set)
        # The .at(t) is for calculating position, not finding events.
        # find_events is a method of the geographic position, not the body itself.
        # This requires an observer and a target.
        # Corrected approach:
        try:
            t_rise, y_rise, _ = observer.find_events(sun, t0, t1, 0.0) # 0.0 for horizon
            t_set, y_set, _ = observer.find_events(sun, t0, t1, 0.0, True) # True for setting
            
            sun_events = []
            for ti, yi in zip(t_rise, y_rise):
                if yi == 1: sun_events.append({"event": "sunrise", "time_utc": ti.utc_datetime().isoformat()})
            for ti, yi in zip(t_set, y_set):
                if yi == 0: sun_events.append({"event": "sunset", "time_utc": ti.utc_datetime().isoformat()})
            sun_events.sort(key=lambda x: x['time_utc'])

        except Exception as e:
            logging.warning(f"Error finding sun events: {e}")
            sun_events = {"error": f"Could not calculate sun events: {e}"}

        # Moon events and phase
        moon = _eph['moon']
        
        try:
            # Moon rise/set
            t_moon_rise, y_moon_rise, _ = observer.find_events(moon, t0, t1, 0.0)
            t_moon_set, y_moon_set, _ = observer.find_events(moon, t0, t1, 0.0, True)

            moon_rise_set = []
            for ti, yi in zip(t_moon_rise, y_moon_rise):
                if yi == 1: moon_rise_set.append({"event": "moonrise", "time_utc": ti.utc_datetime().isoformat()})
            for ti, yi in zip(t_moon_set, y_moon_set):
                if yi == 0: moon_rise_set.append({"event": "moonset", "time_utc": ti.utc_datetime().isoformat()})
            moon_rise_set.sort(key=lambda x: x['time_utc'])

            # Moon phase and illumination
            # Calculate phase angle for illumination
            e = _eph['earth']
            s = _eph['sun']
            m = _eph['moon']

            # Position vectors
            geocentric = e.at(t).observe(m)
            elongation = geocentric.separation_from(e.at(t).observe(s))
            illumination_percent = 100.0 * (1 + np.cos(elongation.radians)) / 2
            
            # Moon phase names based on illumination and age (simplified)
            # Age of moon (days since new moon) is needed for accurate phase name.
            # This requires more complex calculation or a dedicated library.
            # For simplicity, we'll use illumination for a basic phase.
            if illumination_percent > 99: phase_name = "Full Moon"
            elif illumination_percent > 50 and geocentric.position.km[0] > 0: phase_name = "Waxing Gibbous"
            elif illumination_percent > 50: phase_name = "Waning Gibbous"
            elif illumination_percent > 1 and geocentric.position.km[0] > 0: phase_name = "Waxing Crescent"
            elif illumination_percent > 1: phase_name = "Waning Crescent"
            else: phase_name = "New Moon"

            moon_data = {
                "phase": phase_name,
                "illumination_percent": illumination_percent,
                "moonrise_utc": moon_rise_set[0]['time_utc'] if moon_rise_set else None,
                "moonset_utc": moon_rise_set[1]['time_utc'] if len(moon_rise_set) > 1 else None,
                "distance_km": geocentric.distance().km,
                "age_days": None # Requires more complex calculation
            }
        except Exception as e:
            logging.warning(f"Error finding moon events or phase: {e}")
            moon_data = {"error": f"Could not calculate moon data: {e}"}

        # Planet visibility (simplified - just checks if above horizon)
        planets = ['mercury', 'venus', 'mars', 'jupiter', 'saturn', 'uranus', 'neptune']
        planet_visibility = {}
        for planet_name in planets:
            try:
                # Need to use the correct body from ephemeris
                planet_body = _eph[planet_name + ' barycenter'] if planet_name in ['mercury', 'venus', 'mars', 'jupiter', 'saturn', 'uranus', 'neptune'] else _eph[planet_name]
                alt, az, _ = observer.at(t).observe(planet_body).altaz()
                planet_visibility[planet_name] = {
                    "is_visible": alt.degrees > 0,
                    "altitude_deg": alt.degrees,
                    "azimuth_deg": az.degrees
                }
            except Exception as e:
                logging.warning(f"Could not get visibility for {planet_name}: {e}")
                planet_visibility[planet_name] = {"error": f"Calculation error: {e}"}

        return {
            "sun": sun_events,
            "moon": moon_data,
            "planets": planet_visibility
        }
    except Exception as e:
        logging.error(f"Error in get_base_astronomy_data: {e}", exc_info=True)
        return {"error": f"An unexpected error occurred: {e}"}

def get_meteor_showers_data():
    """
    Returns a static list of major meteor showers.
    In a real application, this might be fetched from an external API.
    """
    return {
        "showers": [
            {"name": "Quadrantids", "peak_date": "2025-01-03"},
            {"name": "Lyrids", "peak_date": "2025-04-22"},
            {"name": "Eta Aquarids", "peak_date": "2025-05-05"},
            {"name": "Perseids", "peak_date": "2025-08-12"},
            {"name": "Geminids", "peak_date": "2025-12-14"},
        ],
        "source": "American Meteor Society (AMS) / Hardcoded"
    }

def get_overhead_satellites(lat, lon, alt_m, radius_m, search_term, config_manager):
    """
    Calculates and returns a list of satellites currently overhead for a given location.
    This is a placeholder implementation.
    """
    _load_skyfield_data(config_manager) # Ensure TLEs are loaded

    if not _satellites:
        return {"error": "Satellite TLE data not loaded. Cannot track satellites."}

    observer_location = _eph['earth'] + _eph.topos(latitude_degrees=lat, longitude_degrees=lon, elevation_m=alt_m)
    t = _ts.now()

    overhead_sats = []
    for sat in _satellites:
        # Filter by search term if provided
        if search_term and search_term.lower() not in sat.name.lower():
            continue

        geocentric = observer_location.at(t).observe(sat)
        alt, az, distance = geocentric.altaz()

        # Check if satellite is above horizon and within radius_m
        if alt.degrees > 0 and distance.km <= (radius_m / 1000.0): # Convert radius_m to km
            overhead_sats.append({
                "name": sat.name,
                "norad_cat_id": sat.model.satnum,
                "azimuth_deg": az.degrees,
                "elevation_deg": alt.degrees,
                "range_km": distance.km,
                "velocity_mps": sat.model.sgp4_tsince(t).velocity.kmps[0] * 1000 # Convert km/s to m/s
            })
    
    # Sort by elevation (highest first)
    overhead_sats.sort(key=lambda x: x['elevation_deg'], reverse=True)

    return {"satellites": overhead_sats, "source": "Skyfield / Celestrak TLEs"}


def get_full_sky_data(lat, lon, db_manager, config_manager):
    """
    Aggregates all astronomy-related data.
    """
    data = {}
    data["base_astronomy"] = get_base_astronomy_data(lat, lon, config_manager)
    data["meteor_showers"] = get_meteor_showers_data()
    data["overhead_satellites"] = get_overhead_satellites(lat, lon, 0, 100000, None, config_manager) # Default alt 0m, radius 100km
    
    return data

