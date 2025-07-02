#
# File: app.py
# Version: 1.2.0 (Service Manager Integration)
#
# Description: Main Flask application for the pi_backend.
#              Initializes the Flask app, loads configuration, sets up database
#              and security managers, and registers API routes.
#
# Changelog (v1.2.0):
# - REFACTOR: Integrated `DBConfigManager` for database-backed configuration.
# - REFACTOR: Integrated `SecurityManager` for user authentication and authorization.
# - FEAT: Added initialization of `HardwareManager` and injected `app_config` into it.
# - FEAT: Added a setup endpoint `/setup/create_initial_admin` to create the first admin user.
# - FEAT: Added a `/status` endpoint to check API health and version.
# - FIX: Ensured `location_services` is initialized with `HardwareManager`.
#
from flask import Flask, jsonify, request, g, current_app
from flask_cors import CORS
import os
import sys
import logging
from datetime import datetime, timezone

# Ensure the app's root directory is in the Python path
APP_ROOT = os.path.dirname(os.path.abspath(__file__))
if APP_ROOT not in sys.path:
    sys.path.append(APP_ROOT)

# Import managers and services
from database import DatabaseManager
from db_config_manager import DBConfigManager
from security_manager import SecurityManager
from hardware_manager import HardwareManager
import location_services # Import location_services to set its hardware manager

# Import API routes blueprint
from api_routes import api_blueprint

__version__ = "1.2.0"

# --- Flask App Initialization ---
app = Flask(__name__)

# --- Logging Setup ---
# Configure logging to stdout for systemd journal
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(filename)s:%(lineno)d - %(message)s',
    stream=sys.stdout
)

# --- CORS Configuration ---
# Allow CORS for all origins by default, can be restricted via config
CORS(app, resources={r"/api/*": {"origins": "*"}}) # Default to allow all for development

# --- Global Managers Initialization (happens once per Gunicorn worker) ---
@app.before_request
def initialize_managers():
    # Use g (Flask's global object) to store managers, so they are initialized
    # once per request context, but effectively once per Gunicorn worker process.
    if 'db_manager' not in g:
        try:
            # Get DB path from environment variable (set by systemd service)
            db_path = os.environ.get('DB_PATH', '/var/lib/pi_backend/pi_backend.db')
            g.db_manager = DatabaseManager(database_path=db_path)
            if g.db_manager.connection is None:
                logging.error("Failed to connect to database on app startup.")
                # Depending on severity, you might want to abort here or return an error
                # For now, let's allow it to continue but log the error.
        except Exception as e:
            logging.critical(f"CRITICAL: Failed to initialize DatabaseManager: {e}", exc_info=True)
            g.db_manager = None # Mark as failed

    if 'config_manager' not in g:
        if g.db_manager:
            g.config_manager = DBConfigManager(db_manager=g.db_manager)
            # Update CORS origins from DB config
            cors_origins = g.config_manager.get('CORS', 'Origins', fallback='*')
            if cors_origins != '*':
                # This requires re-initializing CORS, which is tricky after app.run()
                # For simplicity, we'll assume a restart is needed for CORS changes.
                # Or, for dynamic origins, use a more advanced Flask-CORS setup.
                pass # CORS is already initialized globally, dynamic change is complex.
        else:
            g.config_manager = None
            logging.error("ConfigManager not initialized due to missing DBManager.")

    if 'security_manager' not in g:
        if g.db_manager:
            g.security_manager = SecurityManager(db_manager=g.db_manager)
        else:
            g.security_manager = None
            logging.error("SecurityManager not initialized due to missing DBManager.")
            
    if 'hw_manager' not in g:
        if g.config_manager:
            g.hw_manager = HardwareManager(app_config=g.config_manager)
            # Inject hardware manager into services that need it
            location_services.set_hardware_manager(g.hw_manager)
        else:
            g.hw_manager = None
            logging.error("HardwareManager not initialized due to missing ConfigManager.")


    # Make managers available to current_app.config for blueprints/routes
    current_app.config['DB_MANAGER'] = g.db_manager
    current_app.config['CONFIG_MANAGER'] = g.config_manager
    current_app.config['SECURITY_MANAGER'] = g.security_manager
    current_app.config['HW_MANAGER'] = g.hw_manager # Make HardwareManager accessible


# --- Register Blueprints ---
app.register_blueprint(api_blueprint)

# --- Error Handlers ---
@app.errorhandler(404)
def not_found_error(error):
    return jsonify({"error": "Not Found", "message": "The requested URL was not found on the server."}), 404

@app.errorhandler(500)
def internal_error(error):
    app.logger.exception("An internal server error occurred.")
    return jsonify({"error": "Internal Server Error", "message": "Something went wrong on the server."}), 500

# --- Main Entry Point for Development (not used by Gunicorn directly) ---
if __name__ == '__main__':
    # This block is for direct Python execution (e.g., `python3 app.py`)
    # Gunicorn will call `app` directly from the `ExecStart` in the service file.
    # For development, you can run `python3 app.py` and it will start a dev server.
    app.run(debug=True, host='0.0.0.0', port=5000)

