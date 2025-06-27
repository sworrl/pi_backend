#
# File: location_services.py
# Version: 2.1.2 (Fix Application Context)
#
# Description: Handles geocoding from location strings to coordinates.
#
# Changelog (v2.1.2):
# - FIX: Modified `get_location_details` and `reverse_geocode_from_coords`
#   to explicitly accept `db_manager` and `config_manager` instances instead
#   of relying on `current_app`. This resolves "Working outside of application context"
#   errors when called from contexts like the data poller service.
# - REFACTOR: Updated `set_hardware_manager` to allow the Flask app to inject
#   the `HardwareManager` instance, ensuring consistency.
#
# DEV_NOTES:
# - v2.1.1:
#   - CRITICAL FIX: Solved "Working outside of application context" error.
#     The database manager is now correctly accessed from `current_app`
#     inside the functions, ensuring it's only called during a request.
# - v2.0.0:
#   - REFACTOR: Switched to fetching API keys from the database.
#
import sys
import time
# Removed flask's current_app import as it will be passed explicitly
from hardware_manager import HardwareManager # Keep import for type hinting/dependency understanding

try:
    from geopy.geocoders import GoogleV3
    from geopy.exc import GeocoderTimedOut, GeocoderServiceError
    GEOPY_AVAILABLE = True
except ImportError:
    GEOPY_AVAILABLE = False
    print("[WARN] geopy library not found. Geocoding features will be disabled.", file=sys.stderr)

__version__ = "2.1.2"

_location_cache = {}
CACHE_EXPIRY_SECONDS = 3600

_hw_manager_instance = None 

def set_hardware_manager(hw_manager_instance):
    """Allows external injection of HardwareManager instance into this module."""
    global _hw_manager_instance
    _hw_manager_instance = hw_manager_instance

def _get_from_cache(key):
    if key in _location_cache and (time.time() - _location_cache[key][0]) < CACHE_EXPIRY_SECONDS:
        return _location_cache[key][1]
    return None

def _set_in_cache(key, data):
    _location_cache[key] = (time.time(), data)

# Updated to accept db_manager and config_manager explicitly
def get_location_details(location_query=None, db_manager=None, config_manager=None):
    if db_manager is None or config_manager is None:
        return (None, None, {"error": "Database/Config Manager not provided to location_services.get_location_details."})

    # Use the globally injected HardwareManager instance
    hw_manager_to_use = _hw_manager_instance 
    if hw_manager_to_use is None:
        # Fallback if not injected, but this indicates a setup issue in calling code
        # Attempt to create a new one, though this might lead to multiple instances
        # and not ideal for long-running processes like data_poller.
        logging.warning("location_services: HardwareManager not injected. Attempting to create new instance.")
        hw_manager_to_use = HardwareManager(app_config=config_manager) # Pass config_manager to new instance

    if location_query:
        cached_location = _get_from_cache(location_query)
        if cached_location:
            return cached_location

        if GEOPY_AVAILABLE:
            api_key = db_manager.get_key_value_by_name('GOOGLE_GEOCODING_API_KEY')

            if api_key:
                try:
                    geolocator = GoogleV3(api_key=api_key)
                    location = geolocator.geocode(location_query, timeout=10)
                    if location:
                        result = (location.latitude, location.longitude, {
                            "source": "Google Geocoding", "query": location_query,
                            "address": location.address, "latitude": location.latitude,
                            "longitude": location.longitude
                        })
                        _set_in_cache(location_query, result)
                        return result
                except Exception as e:
                    print(f"[ERROR] Geocoding service error: {e}. Falling back.", file=sys.stderr)
            else:
                print("[WARN] GOOGLE_GEOCODING_API_KEY not found in database. Geocoding disabled.", file=sys.stderr)

    # Fallback to GNSS
    if hw_manager_to_use:
        gps_data = hw_manager_to_use.get_best_gnss_data()
        if gps_data and "error" not in gps_data and gps_data.get('latitude') is not None:
            lat, lon = gps_data['latitude'], gps_data['longitude']
            return (float(lat), float(lon), {"source": "Onboard GNSS", "latitude": float(lat), "longitude": float(lon)})

    return (None, None, {"error": "Failed to resolve location from any source."})

# Updated to accept db_manager explicitly
def reverse_geocode_from_coords(lat, lon, db_manager):
    if not GEOPY_AVAILABLE:
        return {"error": "geopy library not available."}
    if db_manager is None:
        return {"error": "Database Manager not provided for reverse geocoding."}

    api_key = db_manager.get_key_value_by_name('GOOGLE_GEOCODING_API_KEY')

    if not api_key:
        return {"error": "GOOGLE_GEOCODING_API_KEY not found in database."}

    try:
        geolocator = GoogleV3(api_key=api_key)
        location = geolocator.reverse((lat, lon), exactly_one=True, timeout=10)
        return {"address": location.address, "raw": location.raw} if location else {"error": "No address found."}
    except Exception as e:
        return {"error": f"Reverse geocoding error: {e}"}
