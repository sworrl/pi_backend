# ==============================================================================
# Pi Backend Main Application
# Version: 2.1.0 (Database-Backed Configuration)
# ==============================================================================
# This is the core Flask application file for the pi_backend. It initializes
# the Flask app, configures it, and registers all the necessary API routes
# and services.
#
# Changelog:
# - v2.0.3: Initial stable release with multi-service architecture.
# - v2.0.4: CRITICAL FIX: Removed the obsolete import of 'PermissionEnforcer'.
# - v2.0.5: CRITICAL FIX: Updated SecurityManager instantiation.
# - v2.1.0: REFACTOR: Switched from file-based configuration (`ConfigLoader`)
#           to database-backed configuration (`DBConfigManager`). All settings
#           are now pulled from the database after initial setup.
# ==============================================================================

# --- Standard Library Imports ---
import os
import logging
from logging.handlers import RotatingFileHandler

# --- Third-Party Imports ---
from flask import Flask
from flask_cors import CORS

# --- Local Application Imports ---
from api_routes import api_blueprint
# Renamed and refactored config_loader to db_config_manager
from db_config_manager import DBConfigManager
from database import DatabaseManager
from security_manager import SecurityManager
from hardware_manager import HardwareManager

# --- Constants ---
APP_ROOT = os.path.dirname(os.path.abspath(__file__))
# The config file path is now primarily for setup.sh to load initial settings into DB
# The app itself will largely ignore this for runtime config, pulling from DB.
# Keeping it for potential initial DB_Path resolution if DBConfigManager isn't ready.
APP_CONFIG_PATH_FOR_SETUP = '/etc/pi_backend/setup_config.ini'


# --- Initialization Functions ---

def create_app():
    """
    Factory function to create and configure the Flask application.
    """
    app = Flask(__name__)
    
    # --- Initialize Database Manager FIRST ---
    # Database path must be loaded initially for DBManager instance
    # For robust startup, we might still need to get this from an INI file initially
    # before DBConfigManager is fully operational (e.g., if DB path itself is needed before DB is init'd)
    # This assumes setup.sh ensures DB_Path is either in environment or hardcoded fallback.
    # A more robust solution might pass this via environment variables or a very minimal static config.
    
    # Temporarily load DB_Path from an INI for DBManager initialization if not already set.
    # In a production setup, this path should be reliably known or passed.
    # For now, we'll try to read it directly from the setup_config.ini.
    # This is a temporary measure during transition.
    
    # To handle the chicken-and-egg problem:
    # 1. setup.sh ensures the DB_Path is available (e.g. by setting env var or by passing it)
    # 2. DatabaseManager uses this path.
    # 3. DBConfigManager is initialized with DatabaseManager.
    # 4. All other services then use DBConfigManager.
    
    # For now, let's assume `app_config.ini` or `setup_config.ini` is parsed once for DB_Path
    # or that the DB_Path is a known constant for the DatabaseManager constructor.
    # Since setup.sh will put it in /var/lib/pi_backend/pi_backend.db, we can use that.
    
    # A cleaner approach would be:
    # from configparser import ConfigParser
    # ini_parser = ConfigParser()
    # ini_parser.read(APP_CONFIG_PATH_FOR_SETUP)
    # db_path = ini_parser.get('Database', 'DB_Path', fallback='/var/lib/pi_backend/pi_backend.db')

    # Given that `setup.sh` ensures the DB_Path is written to `/etc/pi_backend/setup_config.ini`
    # and that the DatabaseManager needs it, we'll create a temporary parser here.
    # In a perfectly refactored system, DB_Path could be a static constant if known.
    
    import configparser
    temp_config_parser = configparser.ConfigParser()
    # Read the canonical setup config for the DB_Path
    temp_config_parser.read(APP_CONFIG_PATH_FOR_SETUP)
    db_path = temp_config_parser.get('SystemPaths', 'database_path', fallback='/var/lib/pi_backend/pi_backend.db')

    app.config['DB_MANAGER'] = DatabaseManager(database_path=db_path)

    # --- Initialize DBConfigManager (replaces ConfigLoader) ---
    # Now, all configuration for the app comes from the database
    app.config['CONFIG_MANAGER'] = DBConfigManager(db_manager=app.config['DB_MANAGER'])
    
    # --- Enable CORS ---
    # CORS origins might now come from DB_ConfigManager
    cors_origins = app.config['CONFIG_MANAGER'].get('CORS', 'Origins', fallback='*')
    CORS(app, resources={r"/api/*": {"origins": cors_origins}})

    # --- Initialize Hardware Manager ---
    install_path = os.path.dirname(os.path.abspath(__file__))
    # HardwareManager now gets the new CONFIG_MANAGER
    app.config['HW_MANAGER'] = HardwareManager(app_config=app.config['CONFIG_MANAGER'])

    # --- Initialize Security Manager ---
    db_manager = app.config['DB_MANAGER']
    app.config['SECURITY_MANAGER'] = SecurityManager(db_manager)

    # --- Register Blueprints ---
    app.register_blueprint(api_blueprint, url_prefix='/api')
    
    return app

def setup_logging(config_manager):
    """
    Configures application-wide logging using settings from DBConfigManager.
    """
    log_file = config_manager.get('Logging', 'App_Log_File', fallback='/var/log/pi_backend/app.log')
    log_level_str = config_manager.get('Logging', 'Log_Level', fallback='INFO').upper()
    
    log_dir = os.path.dirname(log_file)
    if not os.path.exists(log_dir):
        os.makedirs(log_dir)

    log_level = getattr(logging, log_level_str, logging.INFO)
    handler = RotatingFileHandler(log_file, maxBytes=10000000, backupCount=5)
    handler.setLevel(log_level)
    formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    handler.setFormatter(formatter)
    
    logging.getLogger().addHandler(handler)
    logging.getLogger().setLevel(log_level)
    
    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(formatter)
    logging.getLogger().addHandler(stream_handler)


# --- Main Execution ---
if __name__ == '__main__':
    app = create_app()
    # Configure logging using the DB-backed config manager
    setup_logging(app.config['CONFIG_MANAGER']) 
    app.run(host='0.0.0.0', port=5000, debug=True)
else:
    app = create_app()
    # Configure logging using the DB-backed config manager
    setup_logging(app.config['CONFIG_MANAGER'])
    logging.info("Pi Backend application created and configured for production.")
