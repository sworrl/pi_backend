# ==============================================================================
# Pi Backend Data Poller
# Version: 3.0.0 (Standalone Service)
# ==============================================================================
# This script runs as a persistent background service (systemd). It is
# responsible for periodically polling various API endpoints (both internal
# and external) and storing the collected data in the database.
#
# The polling frequencies are determined by the settings in the database,
# which are initially migrated from setup_config.ini.
# ==============================================================================

import schedule
import time
import requests
import logging
import json
import sys
import os

# Ensure the app's root directory is in the Python path
# This allows us to import other modules from the application
APP_ROOT = os.path.dirname(os.path.abspath(__file__))
if APP_ROOT not in sys.path:
    sys.path.append(APP_ROOT)

from database import DatabaseManager
from db_config_manager import DBConfigManager
from hardware_manager import HardwareManager
import location_services
import weather_services
import astronomy_services

__version__ = "3.0.0"

# --- Global Instances ---
db_manager = None
config_manager = None
hw_manager = None

# --- Logging Setup ---
# Basic logging to stdout for systemd journal
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    stream=sys.stdout
)

# --- Polling Functions ---

def poll_system_stats():
    """Polls basic system stats (CPU, Memory, Disk) and saves them."""
    logging.info("Polling system stats...")
    if not db_manager:
        logging.error("Database manager not initialized. Skipping poll.")
        return

    try:
        # For system stats, we can call the hardware module directly
        # as it doesn't rely on the full Flask app context.
        import hardware
        cpu_usage = hardware.get_cpu_usage()
        mem_usage = hardware.get_memory_usage()
        disk_usage = hardware.get_disk_usage('/')

        db_manager.add_data("system", cpu_usage, "percent", source="psutil", metadata={"metric": "cpu_usage"})
        db_manager.add_data("system", mem_usage, "percent", source="psutil", metadata={"metric": "memory_usage"})
        db_manager.add_data("system", disk_usage['percent'], "percent", source="psutil", metadata={"metric": "disk_usage", "path": "/"})
        
        logging.info(f"Logged System Stats: CPU {cpu_usage}%, Mem {mem_usage}%, Disk {disk_usage['percent']}%")

    except Exception as e:
        logging.error(f"Error polling system stats: {e}", exc_info=True)

def poll_weather_data():
    """Polls external weather data and saves it."""
    logging.info("Polling weather data...")
    if not db_manager or not config_manager or not hw_manager:
        logging.error("Managers not initialized. Skipping poll.")
        return
        
    try:
        # The location can be hardcoded in config or based on live GPS
        location_query = config_manager.get('Polling', 'location', fallback=None)
        
        # We pass the managers directly to the service function
        weather_data = weather_services.fetch_all_weather_data(
            location_query=location_query,
            db_manager=db_manager,
            config_manager=config_manager
        )

        if weather_data and "error" not in weather_data:
            # Save the full aggregated response as a JSON string
            db_manager.add_data(
                data_type="weather_forecast",
                value=None, # The main value is the JSON blob in metadata
                source="weather_services",
                metadata=weather_data
            )
            logging.info("Successfully polled and stored weather data.")
        else:
            logging.error(f"Failed to poll weather data: {weather_data.get('error', 'Unknown reason')}")
            
    except Exception as e:
        logging.error(f"Error polling weather data: {e}", exc_info=True)

def poll_gnss_data():
    """Polls internal GNSS data and saves it."""
    logging.info("Polling GNSS data...")
    if not db_manager or not hw_manager:
        logging.error("Managers not initialized. Skipping poll.")
        return
        
    try:
        # Call the hardware manager directly for the latest data
        gps_data = hw_manager.get_best_gnss_data()

        if gps_data and "error" not in gps_data and gps_data.get('latitude') is not None:
             # Save the location data to the location-specific table
            db_manager.execute_query(
                "INSERT INTO location_data (latitude, longitude, altitude, source, metadata) VALUES (?, ?, ?, ?, ?)",
                (
                    gps_data.get('latitude'),
                    gps_data.get('longitude'),
                    gps_data.get('altitude_m'),
                    gps_data.get('source', 'Onboard GNSS'),
                    json.dumps(gps_data)
                )
            )
            logging.info(f"Successfully polled and stored GNSS data: Lat {gps_data['latitude']}, Lon {gps_data['longitude']}")
        else:
            logging.warning(f"Could not poll valid GNSS data: {gps_data.get('error', 'No fix')}")

    except Exception as e:
        logging.error(f"Error polling GNSS data: {e}", exc_info=True)


# --- Main Execution ---
def main():
    """
    The main function that initializes managers and starts the scheduler loop.
    """
    global db_manager, config_manager, hw_manager

    logging.info(f"--- Starting Data Poller Service v{__version__} ---")

    try:
        # Initialize managers needed for polling tasks
        db_path = os.environ.get('DB_PATH', '/var/lib/pi_backend/pi_backend.db')
        db_manager = DatabaseManager(database_path=db_path)
        config_manager = DBConfigManager(db_manager=db_manager)
        hw_manager = HardwareManager(app_config=config_manager)
        
        # Inject hardware manager into services that need it
        location_services.set_hardware_manager(hw_manager)

        logging.info("Managers initialized successfully.")
    except Exception as e:
        logging.critical(f"CRITICAL: Failed to initialize managers. Poller cannot start. Error: {e}", exc_info=True)
        sys.exit(1)

    # --- Schedule Jobs ---
    # Read intervals from the database-backed configuration
    try:
        schedule.every(config_manager.getint("Polling", "system_stats_seconds", 60)).seconds.do(poll_system_stats)
        schedule.every(config_manager.getint("Polling", "weather_minutes", 15)).minutes.do(poll_weather_data)
        schedule.every(config_manager.getint("Polling", "gps_seconds", 10)).seconds.do(poll_gnss_data)
        
        logging.info("Polling jobs scheduled:")
        for job in schedule.get_jobs():
            logging.info(f"  -> {job}")

    except Exception as e:
        logging.critical(f"CRITICAL: Could not schedule jobs. Error: {e}", exc_info=True)
        sys.exit(1)

    # --- Run Scheduler Loop ---
    logging.info("Starting scheduler loop. Poller is now active.")
    while True:
        try:
            schedule.run_pending()
            time.sleep(1)
        except KeyboardInterrupt:
            logging.info("Keyboard interrupt received. Shutting down poller.")
            break
        except Exception as e:
            logging.error(f"An unexpected error occurred in the scheduler loop: {e}", exc_info=True)
            # Sleep longer on error to prevent rapid-fire failures
            time.sleep(60)

if __name__ == "__main__":
    main()
