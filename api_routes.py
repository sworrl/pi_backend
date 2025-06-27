#
# File: api_routes.py
# Version: 4.6.0 (Add File Info Endpoint)
#
# Description: Defines all API endpoints for the pi_backend application.
#
# Changelog (v4.6.0):
# - FEATURE: Added new `/api/system/file-info` endpoint. This endpoint
#   dynamically scans application scripts, extracts their versions,
#   calculates SHA256 checksums, and returns this information. It helps
#   in verifying deployed file integrity from the UI.
#
# Changelog (v4.5.5):
# - FIX: Modified API routes that call `location_services` and `weather_services`
#   to explicitly pass `db_manager` and `config_manager` from `current_app.config`.
#   This ensures these services receive necessary dependencies and resolves
#   "Working outside of application context" errors.
#
# Changelog (v4.5.4):
# - FIX: Corrected the import statement for `communtiy_services` to explicitly
#   match the filename `communtiy_services.py` provided by the user,
#   resolving `ModuleNotFoundError`.
#
from flask import Blueprint, request, jsonify, g, current_app
from datetime import datetime, timezone
import functools
import logging
import secrets
import os
import hashlib # For checksum calculation
import re      # For version extraction using regex

# Import all service modules
import hardware
import location_services
import weather_services
import communtiy_services 
from hardware_manager import HardwareManager 

api_blueprint = Blueprint('api', __name__, url_prefix='/api')
__version__ = "4.6.0"

# --- Authentication Helpers ---
def _make_error_response(message, status_code):
    return jsonify({"error": message}), status_code

def require_auth(f):
    @functools.wraps(f)
    def decorated_function(*args, **kwargs):
        public_endpoints = ['/api/status', '/api/setup/user_count', '/api/setup/create_initial_admin']
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

# --- Service Test Endpoints ---
@api_blueprint.route('/services/location-test', methods=['GET'])
@require_auth
def test_location_services():
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

# --- Community Services Endpoint ---
@api_blueprint.route('/community/nearby', methods=['GET'])
@require_auth
def get_nearby_pois_endpoint():
    try:
        db_manager = current_app.config['DB_MANAGER']
        config_manager = current_app.config['CONFIG_MANAGER']
        
        lat, lon, resolved_info = location_services.get_location_details(
            db_manager=db_manager,
            config_manager=config_manager
        )
        if lat is None or lon is None:
            return _make_error_response(f"Could not get a valid GPS location: {resolved_info.get('error', 'Unknown')}", 500)

        types_query = request.args.get('types')
        if types_query:
            types_list = [t.strip() for t in types_query.split(',') if t.strip()]
        else:
            types_list = None

        # community_services should now get its data paths from config_manager
        # Assuming community_services needs db_manager/config_manager (e.g., for PFAS_DATA_FILE path),
        # these need to be passed into its functions similar to location/weather.
        pois = communtiy_services.get_nearby_pois(lat, lon, types=types_list) # Corrected import name
        return jsonify({
            "search_location": {"latitude": lat, "longitude": lon},
            "points_of_interest": pois
        })
    except Exception as e:
        logging.error(f"Error in nearby POIs endpoint: {e}", exc_info=True)
        return _make_error_response(f"An internal error occurred: {e}", 500)

# --- Setup & Initialization Endpoints ---
@api_blueprint.route('/setup/user_count', methods=['GET'])
def get_user_count():
    db_manager = current_app.config['DB_MANAGER']
    stats = db_manager.get_db_stats()
    return jsonify({"user_count": stats.get('user_count', 0)})

@api_blueprint.route('/setup/create_initial_admin', methods=['POST'])
def create_initial_admin():
    db_manager = current_app.config['DB_MANAGER']
    if db_manager.check_if_default_credentials_exist() == False: # True means no users, False means users exist
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
    db_manager = current_app.config['DB_MANAGER']
    user_count = db_manager.get_db_stats().get('user_count', 0)
    # default_credentials_active is true if user_count is 0 (meaning no users set up yet)
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
    hw_manager = current_app.config['HW_MANAGER']
    summary = {}
    sense_data = hw_manager.get_sense_hat_data()
    summary['sense_hat'] = { "detected": "error" not in sense_data, "status": "OK" if "error" not in sense_data else sense_data.get("error") }
    gps_status = hw_manager.get_gpsd_status()
    summary['gps'] = { "detected": True, "status": "OK" if all(s == 'active' for s in gps_status.values()) else "Error", "details": gps_status }
    lte_info = hw_manager.get_lte_network_info()
    summary['lte_modem'] = { "detected": "error" not in lte_info, "status": "OK" if "error" not in lte_info else "Error", "details": lte_info.get("operator_info", "N/A") if "error" not in lte_info else lte_info.get("error") }
    return jsonify(summary)

@api_blueprint.route('/hardware/system-stats', methods=['GET'])
@require_auth
def get_system_stats():
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
    return jsonify(hardware.find_bluetooth_devices())

@api_blueprint.route('/hardware/time-sync', methods=['GET'])
@require_auth
def get_time_sync_stats():
    return jsonify(hardware.get_chrony_tracking_stats())

# --- GNSS (GPS) Endpoints ---
@api_blueprint.route('/hardware/gps/best', methods=['GET'])
@require_auth
def get_best_gps_data_endpoint():
    hw_manager = current_app.config['HW_MANAGER']
    return jsonify(hw_manager.get_best_gnss_data())

# --- LTE Modem Endpoints ---
@api_blueprint.route('/hardware/lte/network-info', methods=['GET'])
@require_auth
def get_lte_network_info():
    hw_manager = current_app.config['HW_MANAGER']
    return jsonify(hw_manager.get_lte_network_info())

@api_blueprint.route('/hardware/lte/flight-mode', methods=['POST'])
@require_auth
@require_admin
def set_flight_mode_endpoint():
    data = request.get_json()
    if not data or 'enable' not in data:
        return _make_error_response("Request must be JSON with a boolean 'enable' key.", 400)
    hw_manager = current_app.config['HW_MANAGER']
    return jsonify(hw_manager.set_lte_flight_mode(enable=data['enable']))

# --- Sense HAT Endpoints ---
@api_blueprint.route('/hardware/sensehat/data', methods=['GET'])
@require_auth
def get_sensehat_data():
    hw_manager = current_app.config['HW_MANAGER']
    return jsonify(hw_manager.get_sense_hat_data())

@api_blueprint.route('/hardware/sensehat/execute-command', methods=['POST'])
@require_auth
@require_admin
def sensehat_execute_command_endpoint():
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
    db_manager = current_app.config['DB_MANAGER']
    return jsonify(db_manager.get_db_stats())

@api_blueprint.route('/database/prune', methods=['POST'])
@require_auth
@require_admin
def prune_database_endpoint():
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
    install_path = current_app.config['CONFIG_MANAGER'].get('SystemPaths', 'install_path', fallback='/var/www/pi_backend')
    
    # Define files we want to inspect and where they typically reside
    # Note: We check current_app's path and also the /usr/local/bin for external tools
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
        {"name": "communtiy_services.py", "path": os.path.join(install_path, "communtiy_services.py"), "type": "Python Script"}, # Note the typo in filename
        {"name": "A7670E.py", "path": os.path.join(install_path, "modules", "A7670E.py"), "type": "Python Module"},
        {"name": "sense_hat.py", "path": os.path.join(install_path, "modules", "sense_hat.py"), "type": "Python Module"},
        {"name": "setup_a7670e_gps.sh", "path": "/usr/local/bin/setup_a7670e_gps.sh", "type": "Bash Script (Tool)"}, # External tool
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
                # Calculate SHA256 checksum
                with open(file_path, 'rb') as f:
                    info["checksum_sha256"] = hashlib.sha256(f.read()).hexdigest()
                
                # Extract version for Python scripts if applicable
                if file_path.endswith(".py") or file_path.endswith(".sh"):
                    with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                        content = f.read(2048) # Read first 2KB for efficiency
                        version_match = re.search(r"Version:\s*([0-9a-zA-Z.-]+)", content)
                        if version_match:
                            info["version"] = version_match.group(1)
            except Exception as e:
                info["version"] = f"Error: {e}"
                info["checksum_sha256"] = f"Error: {e}"
        
        file_info_list.append(info)

    return jsonify(file_info_list)
