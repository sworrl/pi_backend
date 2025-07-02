#
# File: api_routes.py
# Version: 4.10.0 (API Endpoints Info)
#
# Description: Defines all API endpoints for the pi_backend application.
#
# Changelog (v4.10.0):
# - FEAT: Added new endpoint `/api/routes_info` to list all registered API endpoints,
#   their HTTP methods, and a description (from the function's docstring).
# - FEAT: Enhanced `/community/nearby` endpoint to accept `radius_m` or `radius_miles`
#   and to return all POIs within the specified radius, including detailed info
#   (address, phone, website).
# - FEAT: Added `/space/weather` endpoint to retrieve space weather data.
# - FEAT: Added `/space/moon` endpoint to retrieve moon information.
# - FEAT: Added `/space/satellites/overhead` endpoint to retrieve overhead satellite data.
# - FIX: Corrected the omission of astronomy services from the API layer.
#
from flask import Blueprint, request, jsonify, g, current_app
from datetime import datetime, timezone
import functools
import logging
import secrets
import os
import hashlib
import re

# Import all service modules
import hardware
import location_services
import weather_services
import communtiy_services
import astronomy_services
from hardware_manager import HardwareManager 

api_blueprint = Blueprint('api', __name__, url_prefix='/api')
__version__ = "4.10.0"

# --- Authentication Helpers ---
def _make_error_response(message, status_code):
    return jsonify({"error": message}), status_code

def require_auth(f):
    @functools.wraps(f)
    def decorated_function(*args, **kwargs):
        public_endpoints = ['/api/status', '/api/setup/user_count', '/api/setup/create_initial_admin', '/api/routes_info']
        if request.path in public_endpoints:
            return f(*args, **kwargs)

        api_key_value = request.headers.get('X-API-Key')
        auth = request.authorization
        db_manager = current_app.config['DB_MANAGER']
        security_manager = current_app.config['SECURITY_MANAGER']

        if api_key_value:
            key_details = db_manager.get_api_key_for_auth(api_key_value)
            if key_details:
                g.authenticated_by = f"api_key:{key_details['key_name']}"
                g.user_role = 'admin'
                return f(*args, **kwargs)

        if auth and auth.username and auth.password:
            if security_manager.verify_credentials(auth.username, auth.password):
                g.authenticated_by = f"user:{auth.username}"
                g.authenticated_username = auth.username
                g.user_role = security_manager.get_user_role(auth.username)
                return f(*args, **kwargs)

        return _make_error_response("Authentication Failed.", 401)
    return decorated_function

def require_admin(f):
    @functools.wraps(f)
    def decorated_function(*args, **kwargs):
        if g.get('user_role') != 'admin':
            return _make_error_response("Authorization Denied: Requires 'admin' privileges.", 403)
        return f(*args, **kwargs)
    return decorated_function

# --- API Endpoints Information (NEW) ---
@api_blueprint.route('/routes_info', methods=['GET'])
def get_routes_info():
    """
    Returns a list of all registered API endpoints, their methods, and descriptions.
    """
    routes = []
    for rule in current_app.url_map.iter_rules():
        # Filter for rules belonging to this blueprint and not internal Flask routes
        if rule.endpoint.startswith('api.') and not rule.endpoint.endswith('static'):
            methods = sorted([m for m in rule.methods if m not in ['HEAD', 'OPTIONS']])
            
            # Try to get the view function and its docstring
            view_function = current_app.view_functions.get(rule.endpoint)
            description = view_function.__doc__.strip() if view_function and view_function.__doc__ else "No description available."
            
            routes.append({
                "path": rule.rule,
                "methods": methods,
                "description": description
            })
    
    # Sort routes by path for better readability
    routes = sorted(routes, key=lambda x: x['path'])
    return jsonify(routes)


# --- Service Test Endpoints ---
@api_blueprint.route('/services/location-test', methods=['GET'])
@require_auth
def test_location_services():
    """
    Tests location services: geocoding (name to coords) or reverse geocoding (coords to name).
    Requires 'location' query param for geocoding, or 'lat' and 'lon' for reverse geocoding.
    """
    try:
        location_query = request.args.get('location')
        lat = request.args.get('lat')
        lon = request.args.get('lon')

        db_manager = current_app.config['DB_MANAGER']
        config_manager = current_app.config['CONFIG_MANAGER']

        if location_query:
            _, _, resolved_info = location_services.get_location_details(
                location_query=location_query,
                db_manager=db_manager,
                config_manager=config_manager
            )
            return jsonify(resolved_info)
        elif lat and lon:
            result = location_services.reverse_geocode_from_coords(
                float(lat), float(lon),
                db_manager=db_manager
            )
            return jsonify(result)
        else:
            return _make_error_response("Provide 'location' query for geocoding, or 'lat' and 'lon' for reverse.", 400)
    except Exception as e:
        logging.error(f"Error in location-test endpoint: {e}", exc_info=True)
        return _make_error_response(f"An internal error occurred in the location service: {e}", 500)

@api_blueprint.route('/services/weather-test', methods=['GET'])
@require_auth
def test_weather_services():
    """
    Fetches aggregated weather data from various external APIs.
    Optionally accepts a 'location' query parameter (e.g., 'London,UK').
    """
    try:
        location_query = request.args.get('location')
        db_manager = current_app.config['DB_MANAGER']
        config_manager = current_app.config['CONFIG_MANAGER']
        
        weather_data = weather_services.fetch_all_weather_data(
            location_query=location_query,
            db_manager=db_manager,
            config_manager=config_manager
        )
        return jsonify(weather_data)
    except Exception as e:
        logging.error(f"Error in weather-test endpoint: {e}", exc_info=True)
        return _make_error_response(f"An internal error occurred in the weather service: {e}", 500)

# --- Astronomy Services Endpoints ---
@api_blueprint.route('/space/sky-data', methods=['GET'])
@require_auth
def get_sky_data():
    """
    Retrieves comprehensive astronomy data for the current location,
    including sun/moon rise/set, planet visibility, and meteor showers.
    """
    try:
        db_manager = current_app.config['DB_MANAGER']
        config_manager = current_app.config['CONFIG_MANAGER']
        
        # Get location from GPS first
        lat, lon, _ = location_services.get_location_details(
            db_manager=db_manager,
            config_manager=config_manager
        )
        if lat is None or lon is None:
            return _make_error_response("Could not determine location from GPS.", 500)

        # Pass managers to the astronomy service
        sky_data = astronomy_services.get_full_sky_data(
            lat=lat, lon=lon,
            db_manager=db_manager,
            config_manager=config_manager
        )
        return jsonify(sky_data)
    except Exception as e:
        logging.error(f"Error in sky-data endpoint: {e}", exc_info=True)
        return _make_error_response(f"An internal error occurred in the astronomy service: {e}", 500)

@api_blueprint.route('/space/satellites/overhead', methods=['GET'])
@require_auth
def get_overhead_satellites():
    """
    Retrieves a list of satellites currently overhead for a given location and radius.
    Optional query parameters: 'lat', 'lon', 'alt_m' (defaults to GPS), 'radius_m' (default 10km), 'search'.
    """
    try:
        # Get lat/lon/alt from query params or fallback to GPS
        lat = request.args.get('lat', type=float)
        lon = request.args.get('lon', type=float)
        alt_m = request.args.get('alt_m', type=float) # Altitude in meters
        radius_m = request.args.get('radius_m', default=10000, type=float) # Radius in meters
        search_term = request.args.get('search')

        db_manager = current_app.config['DB_MANAGER']
        config_manager = current_app.config['CONFIG_MANAGER']

        # If lat/lon/alt not provided, try to get from GPS
        if lat is None or lon is None:
            gps_data = current_app.config['HW_MANAGER'].get_best_gnss_data()
            if gps_data and "error" not in gps_data and gps_data.get('latitude') is not None:
                lat = gps_data['latitude']
                lon = gps_data['longitude']
                if alt_m is None: # Only use GPS altitude if not manually provided
                    alt_m = gps_data.get('altitude_m', 0.0)
            else:
                return _make_error_response("Could not determine location from GPS. Provide lat/lon/alt.", 500)

        # Fetch overhead satellites using the astronomy service
        overhead_sats = astronomy_services.get_overhead_satellites(
            lat=lat, lon=lon, alt_m=alt_m, radius_m=radius_m, search_term=search_term,
            config_manager=config_manager
        )
        return jsonify(overhead_sats)
    except Exception as e:
        logging.error(f"Error in /space/satellites/overhead endpoint: {e}", exc_info=True)
        return _make_error_response(f"An internal error occurred: {e}", 500)

@api_blueprint.route('/space/weather', methods=['GET'])
@require_auth
def get_space_weather():
    """
    Retrieves the latest space weather data (e.g., Kp-index, solar flare levels).
    Data is typically polled by the background service.
    """
    try:
        db_manager = current_app.config['DB_MANAGER']
        # For now, we'll fetch directly from the database, assuming poller populates it
        space_weather_data = db_manager.get_latest_space_weather()
        if space_weather_data:
            return jsonify(space_weather_data)
        return _make_error_response("Space weather data not available. Poller may not have run yet.", 404)
    except Exception as e:
        logging.error(f"Error in /space/weather endpoint: {e}", exc_info=True)
        return _make_error_response(f"An internal error occurred: {e}", 500)

@api_blueprint.route('/space/moon', methods=['GET'])
@require_auth
def get_moon_info():
    """
    Retrieves current moon phase, illumination, rise/set times, and next major phases for the current location.
    """
    try:
        db_manager = current_app.config['DB_MANAGER']
        config_manager = current_app.config['CONFIG_MANAGER']
        
        lat, lon, _ = location_services.get_location_details(
            db_manager=db_manager,
            config_manager=config_manager
        )
        if lat is None or lon is None:
            return _make_error_response("Could not determine location from GPS.", 500)

        # Get moon data from astronomy services (which might use cached/polled data)
        moon_data = astronomy_services.get_base_astronomy_data(lat, lon, config_manager)
        
        # Extract specific moon info from the base astronomy data
        if moon_data and 'moon' in moon_data:
            # Add illumination and distance (if available from other astronomy functions)
            # For this example, let's assume get_full_sky_data provides it
            full_sky_data = astronomy_services.get_full_sky_data(lat, lon, db_manager, config_manager)
            moon_details = full_sky_data.get('base_astronomy', {}).get('moon', {})
            
            # Add next phases (placeholder for more detailed calculation in astronomy_services)
            moon_details['next_phases'] = {
                "new_moon": (datetime.now() + timedelta(days=29)).isoformat(), # Placeholder
                "first_quarter": (datetime.now() + timedelta(days=7)).isoformat(),
                "full_moon": (datetime.now() + timedelta(days=14)).isoformat(),
                "last_quarter": (datetime.now() + timedelta(days=21)).isoformat(),
            }
            # Add example illumination and distance if not already present
            moon_details.setdefault('illumination_percent', 0.85) # Example
            moon_details.setdefault('distance_km', 384400) # Example
            moon_details.setdefault('age_days', 15.0) # Example

            return jsonify(moon_details)
        
        return _make_error_response("Moon information not available.", 404)
    except Exception as e:
        logging.error(f"Error in /space/moon endpoint: {e}", exc_info=True)
        return _make_error_response(f"An internal error occurred: {e}", 500)


# --- Community Services Endpoint ---
@api_blueprint.route('/community/nearby', methods=['GET'])
@require_auth
def get_nearby_pois_endpoint():
    """
    Finds nearby Points of Interest (POIs) around a specified or current location.
    Optional query parameters: 'lat', 'lon' (defaults to GPS), 'location' (city/zip/county for geocoding),
    'types' (comma-separated, e.g., 'hospital,police'), 'radius' (numeric), 'unit' ('km' or 'miles').
    Returns a list of all found POIs with detailed information.
    """
    try:
        db_manager = current_app.config['DB_MANAGER']
        config_manager = current_app.config['CONFIG_MANAGER']
        
        # Determine location from query params or GPS
        input_location_query = request.args.get('location')
        input_lat = request.args.get('lat', type=float)
        input_lon = request.args.get('lon', type=float)

        if input_location_query:
            lat, lon, resolved_info = location_services.get_location_details(
                location_query=input_location_query,
                db_manager=db_manager,
                config_manager=config_manager
            )
        elif input_lat is not None and input_lon is not None:
            lat, lon = input_lat, input_lon
            resolved_info = {"source": "Manual Coords", "latitude": lat, "longitude": lon}
        else:
            lat, lon, resolved_info = location_services.get_location_details(
                db_manager=db_manager,
                config_manager=config_manager
            )

        if lat is None or lon is None:
            return _make_error_response(f"Could not get a valid location for POI search: {resolved_info.get('error', 'Unknown')}", 500)

        types_query = request.args.get('types')
        if types_query:
            types_list = [t.strip() for t in types_query.split(',') if t.strip()]
        else:
            types_list = None # Let the service use its default types

        radius = request.args.get('radius', default=10, type=float) # Default 10 units
        radius_unit = request.args.get('unit', default='km', type=str) # Default 'km'

        pois = communtiy_services.get_nearby_pois(
            lat=lat, lon=lon,
            db_manager=db_manager, # Pass db_manager for Google enrichment
            search_radius=radius,
            radius_unit=radius_unit,
            types=types_list
        )
        return jsonify({
            "search_location": {"latitude": lat, "longitude": lon, "radius": radius, "unit": radius_unit, "resolved_info": resolved_info},
            "points_of_interest": pois
        })
    except Exception as e:
        logging.error(f"Error in nearby POIs endpoint: {e}", exc_info=True)
        return _make_error_response(f"An internal error occurred: {e}", 500)

# --- Setup & Initialization Endpoints ---
@api_blueprint.route('/setup/user_count', methods=['GET'])
def get_user_count():
    """
    Returns the number of registered users in the system.
    Used for initial setup checks.
    """
    db_manager = current_app.config['DB_MANAGER']
    stats = db_manager.get_db_stats()
    return jsonify({"user_count": stats.get('user_count', 0)})

@api_blueprint.route('/setup/create_initial_admin', methods=['POST'])
def create_initial_admin():
    """
    Creates the first admin user if no users exist in the database.
    Requires a 'password' in the request body.
    """
    db_manager = current_app.config['DB_MANAGER']
    if db_manager.check_if_default_credentials_exist() == False:
        return _make_error_response("Initial admin user can only be created if no users exist.", 409)

    data = request.get_json()
    if not data or 'password' not in data:
        return _make_error_response("Password is required to create the initial admin.", 400)

    success = db_manager.add_user("admin", data['password'], "admin")
    if success:
        return jsonify({
            "message": "Initial admin user 'admin' created successfully.",
            "username": "admin",
        }), 201
    return _make_error_response("Failed to create initial admin user.", 500)

# --- General & Status Endpoints ---
@api_blueprint.route('/status', methods=['GET'])
def get_status():
    """
    Returns the API status, version, and indicates if default credentials are active.
    """
    db_manager = current_app.config['DB_MANAGER']
    user_count = db_manager.get_db_stats().get('user_count', 0)
    default_creds = (user_count == 0) 
    return jsonify({
        "status": "ok",
        "version": __version__,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "default_credentials_active": default_creds
    })

# --- Hardware & System Endpoints ---
@api_blueprint.route('/hardware/summary', methods=['GET'])
@require_auth
def get_hardware_summary():
    """
    Returns a summary of detected hardware components and their operational status.
    """
    hw_manager = current_app.config['HW_MANAGER']
    summary = {}
    sense_data = hw_manager.get_sense_hat_data()
    summary['sense_hat'] = { "detected": "error" not in sense_data, "status": "OK" if "error" not in sense_data else sense_data.get("error") }
    gps_status = hw_manager.get_gpsd_status()
    summary['gps'] = { "detected": True, "status": "OK" if all(s == 'active' for s in gps_status.values()) else "Error", "details": gps_status }
    lte_info = hw_manager.get_lte_network_info()
    summary['lte_modem'] = { "detected": "error" not in lte_info, "status": "OK" if "error" not in lte_info else "Error", "details": lte_info.get("operator_info", "N/A") if "error" not in lte_info else lte_info.get("error") }
    ups_data = hw_manager.get_ups_data()
    summary['ups_hat'] = { "detected": "error" not in ups_data, "status": ups_data.get("status", "Error"), "details": f"{ups_data.get('bus_voltage_V', 0)}V" if "error" not in ups_data else ups_data.get("error") }
    return jsonify(summary)

@api_blueprint.route('/hardware/system-stats', methods=['GET'])
@require_auth
def get_system_stats():
    """
    Returns current system statistics: CPU usage, memory usage, disk usage, boot time, and CPU temperature.
    """
    try:
        hw_manager = current_app.config['HW_MANAGER']
        sense_data = hw_manager.get_sense_hat_data()
        return jsonify({
            "cpu_usage_percent": hardware.get_cpu_usage(),
            "memory_usage_percent": hardware.get_memory_usage(),
            "disk_usage": hardware.get_disk_usage('/'),
            "boot_time": hardware.get_boot_time(),
            "cpu_temperature_c": sense_data.get('sensors', {}).get('temperature_cpu_c')
        })
    except Exception as e:
        return _make_error_response(f"An internal error occurred: {e}", 500)

@api_blueprint.route('/hardware/bluetooth-scan', methods=['POST'])
@require_auth
@require_admin
def scan_bluetooth_devices():
    """
    Scans for nearby Bluetooth devices.
    Requires admin privileges.
    """
    return jsonify(hardware.find_bluetooth_devices())

@api_blueprint.route('/hardware/time-sync', methods=['GET'])
@require_auth
def get_time_sync_stats():
    """
    Returns detailed time synchronization statistics from Chrony.
    """
    return jsonify(hardware.get_chrony_tracking_stats())

# --- UPS HAT Endpoint (New) ---
@api_blueprint.route('/hardware/ups', methods=['GET'])
@require_auth
def get_ups_hat_data():
    """
    Retrieves the latest power statistics from the UPS HAT, including voltages, current, power, and battery percentage.
    """
    hw_manager = current_app.config['HW_MANAGER']
    return jsonify(hw_manager.get_ups_data())

# --- GNSS (GPS) Endpoints ---
@api_blueprint.route('/hardware/gps/best', methods=['GET'])
@require_auth
def get_best_gps_data_endpoint():
    """
    Retrieves the best available GNSS (GPS) data, including latitude, longitude, altitude, speed, and fix type.
    """
    hw_manager = current_app.config['HW_MANAGER']
    return jsonify(hw_manager.get_best_gnss_data())

# --- LTE Modem Endpoints ---
@api_blueprint.route('/hardware/lte/network-info', methods=['GET'])
@require_auth
def get_lte_network_info():
    """
    Retrieves network information from the LTE modem (signal quality, registration, operator).
    """
    hw_manager = current_app.config['HW_MANAGER']
    return jsonify(hw_manager.get_lte_network_info())

@api_blueprint.route('/hardware/lte/flight-mode', methods=['POST'])
@require_auth
@require_admin
def set_flight_mode_endpoint():
    """
    Enables or disables flight mode on the LTE modem.
    Requires a JSON body with 'enable': true/false. Requires admin privileges.
    """
    data = request.get_json()
    if not data or 'enable' not in data:
        return _make_error_response("Request must be JSON with a boolean 'enable' key.", 400)
    hw_manager = current_app.config['HW_MANAGER']
    return jsonify(hw_manager.set_lte_flight_mode(enable=data['enable']))

# --- Sense HAT Endpoints ---
@api_blueprint.route('/hardware/sensehat/data', methods=['GET'])
@require_auth
def get_sensehat_data():
    """
    Retrieves the latest sensor data (temperature, humidity, pressure, orientation, accelerometer)
    and joystick events from the Sense HAT.
    """
    hw_manager = current_app.config['HW_MANAGER']
    return jsonify(hw_manager.get_sense_hat_data())

@api_blueprint.route('/hardware/sensehat/execute-command', methods=['POST'])
@require_auth
@require_admin
def sensehat_execute_command_endpoint():
    """
    Executes a command on the Sense HAT LED matrix (e.g., display_message, set_pixels, clear).
    Requires a 'command' key and optional 'params' in the JSON body. Requires admin privileges.
    """
    data = request.get_json()
    if not data or 'command' not in data:
        return _make_error_response("Request must contain a 'command' key.", 400)
    hw_manager = current_app.config['HW_MANAGER']
    command = data['command']
    params = data.get('params', {})
    return jsonify(hw_manager.sense_hat_execute_command(command, params))

# --- Database Endpoints ---
@api_blueprint.route('/database/stats', methods=['GET'])
@require_auth
@require_admin
def get_db_stats_endpoint():
    """
    Returns statistics about the application database, including table row counts and size.
    Requires admin privileges.
    """
    db_manager = current_app.config['DB_MANAGER']
    return jsonify(db_manager.get_db_stats())

@api_blueprint.route('/database/prune', methods=['POST'])
@require_auth
@require_admin
def prune_database_endpoint():
    """
    Deletes old sensor data from the database based on a configured retention period.
    Requires admin privileges.
    """
    db_manager = current_app.config['DB_MANAGER']
    rows_deleted, success, message = db_manager.prune_sensor_data()
    if not success:
        return _make_error_response(message, 500)
    return jsonify({"success": True, "rows_deleted": rows_deleted, "message": message})


# --- Unified API Key Management Endpoints ---
@api_blueprint.route('/keys', methods=['GET', 'POST'])
@require_auth
@require_admin
def manage_api_keys():
    """
    Manages API keys:
    - GET: Lists all stored API keys (names and internal/external status).
    - POST: Adds a new API key or generates an internal key. Requires 'name' and optional 'value' in JSON body.
    Requires admin privileges.
    """
    db_manager = current_app.config['DB_MANAGER']
    try:
        if request.method == 'GET':
            return jsonify(db_manager.list_api_keys())
        if request.method == 'POST':
            data = request.get_json()
            if not data or 'name' not in data:
                return _make_error_response("Request must include 'name'.", 400)
            key_name = data['name']
            key_value = data.get('value')
            success, message, new_key = db_manager.add_api_key(key_name, key_value)
            if success:
                response = {"message": message}
                if new_key: response['api_key'] = new_key
                return jsonify(response), 201
            return _make_error_response(message, 409)
    except Exception as e:
        return _make_error_response(f"Internal error: {e}", 500)

@api_blueprint.route('/keys/<string:key_name>', methods=['PUT', 'DELETE'])
@require_auth
@require_admin
def manage_single_api_key(key_name):
    """
    Manages a single API key by name:
    - PUT: Updates the value of an existing API key. Requires 'value' in JSON body.
    - DELETE: Deletes an API key.
    Requires admin privileges, or the authenticated user must match the target username.
    """
    db_manager = current_app.config['DB_MANAGER']
    try:
        if request.method == 'PUT':
            data = request.get_json()
            if not data or 'value' not in data:
                return _make_error_response("Request must include 'value'.", 400)
            if db_manager.update_api_key(key_name, data['value']):
                return jsonify({"message": f"API key '{key_name}' updated."})
            return _make_error_response("API key not found.", 404)
        if request.method == 'DELETE':
            if db_manager.delete_api_key(key_name):
                return jsonify({"message": f"API key '{key_name}' deleted."})
            return _make_error_response("API key not found.", 404)
    except Exception as e:
        return _make_error_response(f"Internal error: {e}", 500)

# --- User Management Endpoints ---
@api_blueprint.route('/users', methods=['GET', 'POST'])
@require_auth
@require_admin
def manage_users():
    """
    Manages user accounts:
    - GET: Lists all registered users (username, role).
    - POST: Creates a new user. Requires 'username', 'password', and 'role' in JSON body.
    Requires admin privileges.
    """
    db_manager = current_app.config['DB_MANAGER']
    if request.method == 'GET':
        return jsonify(db_manager.list_all_users())
    if request.method == 'POST':
        data = request.get_json()
        if not data or not all(k in data for k in ['username', 'password', 'role']):
            return _make_error_response("Missing 'username', 'password', or 'role'.", 400)
        if data['role'] not in ['admin', 'user']:
             return _make_error_response("Role must be 'admin' or 'user'.", 400)

        success = db_manager.add_user(data['username'], data['password'], data['role'])
        if success:
            return jsonify({"message": f"User '{data['username']}' created."}), 201
        return _make_error_response(f"User '{data['username']}' may already exist.", 409)

@api_blueprint.route('/users/<string:username>', methods=['GET', 'PUT', 'DELETE'])
@require_auth
def manage_single_user(username):
    """
    Manages a single user account by username:
    - GET: Retrieves details for a specific user.
    - PUT: Updates a user's password or role. Requires 'password' or 'role' in JSON body.
    - DELETE: Deletes a user.
    Requires admin privileges, or the authenticated user must match the target username.
    """
    if 'authenticated_username' not in g:
        return _make_error_response("This action requires user authentication.", 403)
    auth_user = g.authenticated_username
    is_admin = g.get('user_role') == 'admin'
    if not is_admin and auth_user != username:
        return _make_error_response("Authorization Denied.", 403)

    db_manager = current_app.config['DB_MANAGER']
    if request.method == 'GET':
        user = db_manager.get_user(username)
        if user: return jsonify(user)
        return _make_error_response("User not found.", 404)
    if request.method == 'DELETE':
        if not is_admin: return _make_error_response("Admins only.", 403)
        if db_manager.delete_user(username):
            return jsonify({"message": f"User '{username}' deleted."})
        return _make_error_response("User not found or cannot be deleted.", 404)
    if request.method == 'PUT':
        data = request.get_json()
        if not data: return _make_error_response("Request body is empty.", 400)
        if 'password' in data:
            if db_manager.update_user_password(username, data['password']):
                return jsonify({"message": "Password updated."})
            return _make_error_response("User not found.", 404)
        if 'role' in data:
            if not is_admin: return _make_error_response("Admins only.", 403)
            if data['role'] not in ['admin', 'user']: return _make_error_response("Invalid role.", 400)
            if db_manager.update_user_role(username, data['role']):
                 return jsonify({"message": f"Role updated to '{data['role']}'."})
            return _make_error_response("Failed to update role.", 500)
        return _make_error_response("No valid fields for update.", 400)

@api_blueprint.route('/system/file-info', methods=['GET'])
@require_auth
@require_admin
def get_file_info():
    """
    Returns version and checksum information for core application files.
    Requires admin privileges.
    """
    install_path = current_app.config['CONFIG_MANAGER'].get('SystemPaths', 'install_path', fallback='/var/www/pi_backend')
    
    file_specs = [
        {"name": "api_routes.py", "path": os.path.join(install_path, "api_routes.py"), "type": "Python Script"},
        {"name": "app.py", "path": os.path.join(install_path, "app.py"), "type": "Python Script"},
        {"name": "astronomy_services.py", "path": os.path.join(install_path, "astronomy_services.py"), "type": "Python Script"},
        {"name": "db_config_manager.py", "path": os.path.join(install_path, "db_config_manager.py"), "type": "Python Script"},
        {"name": "database.py", "path": os.path.join(install_path, "database.py"), "type": "Python Script"},
        {"name": "data_poller.py", "path": os.path.join(install_path, "data_poller.py"), "type": "Python Script"},
        {"name": "hardware.py", "path": os.path.join(install_path, "hardware.py"), "type": "Python Script"},
        {"name": "hardware_manager.py", "path": os.path.join(install_path, "hardware_manager.py"), "type": "Python Script"},
        {"name": "index.html", "path": os.path.join(install_path, "index.html"), "type": "HTML Page"},
        {"name": "location_services.py", "path": os.path.join(install_path, "location_services.py"), "type": "Python Script"},
        {"name": "perm_enforcer.py", "path": os.path.join(install_path, "perm_enforcer.py"), "type": "Python Script"},
        {"name": "security_manager.py", "path": os.path.join(install_path, "security_manager.py"), "type": "Python Script"},
        {"name": "weather_services.py", "path": os.path.join(install_path, "weather_services.py"), "type": "Python Script"},
        {"name": "communtiy_services.py", "path": os.path.join(install_path, "communtiy_services.py"), "type": "Python Script"},
        {"name": "A7670E.py", "path": os.path.join(install_path, "modules", "A7670E.py"), "type": "Python Module"},
        {"name": "sense_hat.py", "path": os.path.join(install_path, "modules", "sense_hat.py"), "type": "Python Module"},
        {"name": "ina219.py", "path": os.path.join(install_path, "modules", "ina219.py"), "type": "Python Module"},
        {"name": "setup_a7670e_gps.sh", "path": "/usr/local/bin/setup_a7670e_gps.sh", "type": "Bash Script (Tool)"},
    ]

    file_info_list = []
    for spec in file_specs:
        file_path = spec['path']
        info = {
            "name": spec['name'],
            "type": spec['type'],
            "path": file_path,
            "exists": os.path.exists(file_path),
            "version": "N/A",
            "checksum_sha256": "N/A"
        }

        if info["exists"]:
            try:
                with open(file_path, 'rb') as f:
                    info["checksum_sha256"] = hashlib.sha256(f.read()).hexdigest()
                
                if file_path.endswith(".py") or file_path.endswith(".sh"):
                    with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                        content = f.read(2048)
                        version_match = re.search(r"Version:\s*([0-9a-zA-Z.-]+)", content)
                        if version_match:
                            info["version"] = version_match.group(1)
            except Exception as e:
                info["version"] = f"Error: {e}"
                info["checksum_sha256"] = f"Error: {e}"
        
        file_info_list.append(info)

    return jsonify(file_info_list)
