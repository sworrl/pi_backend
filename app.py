# ==============================================================================
# Pi Backend Main Application
# Version: 2.1.2 (Definitive Startup Fix)
# ==============================================================================
# This is the core Flask application file for the pi_backend. It initializes
# the Flask app, configures it, and registers all the necessary API routes
# and services.
#
# Changelog:
# - v2.1.2:
#   - FIX: CRITICAL: Reworked the application factory (`create_app`) to
#     ensure all manager classes are initialized and dependencies are injected
#     in the correct, logical order within the application context.
#   - FIX: This version definitively solves the silent startup crash by
#     correctly calling `location_services.set_hardware_manager(hw_manager)`.
#
# Author: Gemini
# ==============================================================================

import os
import logging
from logging.handlers import RotatingFileHandler
from flask import Flask
from flask_cors import CORS

from api_routes import api_blueprint
from db_config_manager import DBConfigManager
from database import DatabaseManager
from security_manager import SecurityManager
from hardware_manager import HardwareManager
import location_services # Import the module to inject dependencies

def create_app():
    """
    Factory function to create and configure the Flask application.
    """
    app = Flask(__name__)
    
    # --- Load Configuration and Initialize Managers ---
    # This sequence is critical to prevent "Working outside of application context" errors.
    with app.app_context():
        # 1. Initialize DatabaseManager first, as it's the foundation for config.
        db_path = '/var/lib/pi_backend/pi_backend.db'
        app.config['DB_MANAGER'] = DatabaseManager(database_path=db_path)

        # 2. Initialize the DB-backed ConfigManager.
        app.config['CONFIG_MANAGER'] = DBConfigManager(db_manager=app.config['DB_MANAGER'])
        config_manager = app.config['CONFIG_MANAGER']

        # 3. Setup Logging using the loaded configuration.
        setup_logging(config_manager)
        logging.info("--- Starting pi_backend Application ---")

        # 4. Initialize HardwareManager, which can now use the config.
        app.config['HW_MANAGER'] = HardwareManager(app_config=config_manager)
        hw_manager = app.config['HW_MANAGER']
        
        # 5. CRITICAL: Inject the HardwareManager instance into the location_services module.
        location_services.set_hardware_manager(hw_manager)
        logging.info("HardwareManager instance injected into Location Services.")

        # 6. Initialize SecurityManager.
        app.config['SECURITY_MANAGER'] = SecurityManager(db_manager=app.config['DB_MANAGER'])

        # 7. Enable CORS.
        cors_origins = config_manager.get('CORS', 'Origins', fallback='*')
        CORS(app, resources={r"/api/*": {"origins": cors_origins}})
        logging.info(f"CORS enabled for origins: {cors_origins}")

        # 8. Register API routes.
        app.register_blueprint(api_blueprint)
        logging.info("API routes registered.")

    logging.info("Flask application created and configured successfully.")
    return app

def setup_logging(config_manager):
    """
    Configures application-wide logging using settings from DBConfigManager.
    """
    log_file = config_manager.get('Logging', 'App_Log_File', fallback='/var/log/pi_backend/app.log')
    log_level_str = config_manager.get('Logging', 'Log_Level', fallback='INFO').upper()
    
    log_dir = os.path.dirname(log_file)
    if not os.path.exists(log_dir):
        try:
            os.makedirs(log_dir, exist_ok=True)
            # After creating, set permissions for www-data
            os.chown(log_dir, 33, 33) # 33 is the UID/GID for www-data on Debian-based systems
        except PermissionError:
            print(f"WARNING: Could not create or set permissions on log directory {log_dir}. Please create it manually and set ownership to 'www-data'.", file=sys.stderr)
        except Exception as e:
            print(f"An unexpected error occurred creating log directory {log_dir}: {e}", file=sys.stderr)

    log_level = getattr(logging, log_level_str, logging.INFO)
    
    # Configure root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(log_level)
    
    # Clear existing handlers to avoid duplicates
    if root_logger.hasHandlers():
        root_logger.handlers.clear()

    # File Handler
    try:
        handler = RotatingFileHandler(log_file, maxBytes=10000000, backupCount=5)
        formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
        handler.setFormatter(formatter)
        root_logger.addHandler(handler)
    except PermissionError:
        print(f"WARNING: Could not write to log file {log_file}. Please check permissions.", file=sys.stderr)
    except Exception as e:
        print(f"An unexpected error occurred setting up file logging: {e}", file=sys.stderr)

    # Stream Handler (for console output)
    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))
    root_logger.addHandler(stream_handler)


# --- Main Execution ---
app = create_app()

if __name__ == '__main__':
    # This block runs when the script is executed directly (e.g., `python3 app.py`)
    # It is intended for development and debugging.
    # For production, Gunicorn is started by the systemd service and points to the `app` object.
    app.run(host='0.0.0.0', port=5000, debug=True)
