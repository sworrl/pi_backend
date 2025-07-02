# ==============================================================================
# Pi Backend Data Poller
# Version: 3.5.0 (UPS Polling Removed)
# ==============================================================================
# This script runs as a persistent background service (systemd). It is
# responsible for periodically polling various API endpoints (both internal
# and external) and storing the collected data in the database.
#
# Changelog:
# - v3.4.0: POI Google Enrichment.
# - v3.5.0: Removed UPS polling from this service. UPS data is now logged
#           directly to the main database by `ups_status.py` when run in
#           continuous mode (`-c`). This simplifies data flow and avoids redundancy.
#
import schedule
import time
import requests
import logging
import json
import sys
import os
from datetime import datetime, timedelta

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
import communtiy_services # Added for POI polling

__version__ = "3.5.0"

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

def poll_astronomy_data():
    """Polls astronomy data (sun/moon, planets, meteor showers) and saves it."""
    logging.info("Polling astronomy data...")
    if not db_manager or not config_manager:
        logging.error("Managers not initialized. Skipping astronomy poll.")
        return
    
    try:
        lat, lon, resolved_info = location_services.get_location_details(
            db_manager=db_manager,
            config_manager=config_manager
        )
        if lat is None or lon is None:
            logging.error(f"Could not get location for astronomy data: {resolved_info.get('error', 'Unknown')}")
            return

        # Fetch all astronomy data
        sky_data = astronomy_services.get_full_sky_data(
            lat=lat, lon=lon,
            db_manager=db_manager,
            config_manager=config_manager
        )
        
        if sky_data and "error" not in sky_data:
            # Store each type of astronomy data separately for easier querying
            for data_type, data_content in sky_data.items():
                if "error" not in data_content: # Only store if no error for that specific type
                    db_manager.add_astronomy_data(
                        data_type=data_type,
                        location_lat=lat,
                        location_lon=lon,
                        data_json=data_content
                    )
                    logging.info(f"Successfully polled and stored astronomy data for type: {data_type}")
                else:
                    logging.warning(f"Error in astronomy data for type {data_type}: {data_content['error']}")
        else:
            logging.error(f"Failed to poll astronomy data: {sky_data.get('error', 'Unknown reason')}")

    except Exception as e:
        logging.error(f"Error polling astronomy data: {e}", exc_info=True)

def poll_space_weather_data():
    """Polls space weather data and saves it."""
    logging.info("Polling space weather data...")
    if not db_manager or not config_manager:
        logging.error("Managers not initialized. Skipping space weather poll.")
        return
    
    try:
        # Assuming astronomy_services also handles space weather (or a new module is created)
        # For now, let's assume get_full_sky_data might return it or we need a new service call
        # In a real scenario, you'd likely have a dedicated space_weather_service.py
        
        # Placeholder for actual space weather API call
        # For now, let's mock some data or call a simple endpoint if available
        response = requests.get("https://services.swpc.noaa.gov/json/goes/primary/xrays-6-hour.json", timeout=10)
        response.raise_for_status()
        raw_data = response.json()

        # Extract relevant fields (this will depend on the actual API response structure)
        # Example: Kp index from a different NOAA endpoint
        kp_response = requests.get("https://services.swpc.noaa.gov/json/planetary_k_index.json", timeout=10)
        kp_response.raise_for_status()
        kp_data = kp_response.json()
        
        latest_kp = None
        if kp_data and isinstance(kp_data, list):
            latest_kp_entry = kp_data[-1] if kp_data else None
            if latest_kp_entry:
                latest_kp = latest_kp_entry.get('kp')

        # Dummy data for solar flare and geomagnetic storm levels if not in API
        solar_flare_level = "C-class" # Example
        geomagnetic_storm_level = "G1" # Example

        # Use the latest timestamp from the data or current time
        report_time_utc = datetime.now().isoformat() # Fallback

        db_manager.add_space_weather_data(
            report_time_utc=report_time_utc,
            kp_index=latest_kp,
            solar_flare_level=solar_flare_level,
            geomagnetic_storm_level=geomagnetic_storm_level,
            data_json={"kp_index": latest_kp, "solar_flare_level": solar_flare_level, "geomagnetic_storm_level": geomagnetic_storm_level, "raw_xrays": raw_data, "raw_kp": kp_data}
        )
        logging.info("Successfully polled and stored space weather data.")

    except requests.RequestException as e:
        logging.error(f"Error fetching space weather data from external API: {e}", exc_info=True)
    except Exception as e:
        logging.error(f"Error polling space weather data: {e}", exc_info=True)

def poll_community_pois():
    """Polls nearby community POIs and saves them, with Google enrichment."""
    logging.info("Polling community POIs...")
    if not db_manager or not config_manager:
        logging.error("Managers not initialized. Skipping POI poll.")
        return
    
    try:
        lat, lon, resolved_info = location_services.get_location_details(
            db_manager=db_manager,
            config_manager=config_manager
        )
        if lat is None or lon is None:
            logging.error(f"Could not get location for POI data: {resolved_info.get('error', 'Unknown')}")
            return

        # Get POI types and radius from config, or use sensible defaults
        poi_types_str = config_manager.get('Polling', 'poi_types', fallback='hospital,police,fire_station,water_tower,water_works,sewage_plant,sewage_pump,substation,landfill')
        poi_types = [t.strip() for t in poi_types_str.split(',') if t.strip()]
        
        poi_radius = config_manager.getint('Polling', 'poi_radius', fallback=10) # Default 10 km
        poi_radius_unit = config_manager.get('Polling', 'poi_radius_unit', fallback='km')

        # Pass db_manager to get_nearby_pois for Google enrichment
        pois_data = communtiy_services.get_nearby_pois(
            lat=lat, lon=lon,
            db_manager=db_manager, # Pass db_manager for Google enrichment
            search_radius=poi_radius,
            radius_unit=poi_radius_unit,
            types=poi_types
        )

        if pois_data:
            for poi_type, pois_list in pois_data.items():
                if isinstance(pois_list, list):
                    for poi in pois_list:
                        # Ensure OSM ID is an integer for the database schema
                        # Use a combination of OSM ID and type for a robust unique key if OSM ID is missing
                        osm_id = int(poi['osm_id']) if 'osm_id' in poi and str(poi['osm_id']).isdigit() else None
                        
                        if osm_id:
                            db_manager.add_community_poi(
                                osm_id=osm_id,
                                poi_type=poi_type,
                                name=poi.get('name'),
                                latitude=poi.get('latitude'),
                                longitude=poi.get('longitude'),
                                address=poi.get('address'),
                                phone=poi.get('phone'),
                                website=poi.get('website'),
                                details_json=poi.get('full_tags', {}) # Store full raw data from Overpass/Google
                            )
                            logging.info(f"Stored POI: {poi.get('name')} ({poi_type})")
                        else:
                            logging.warning(f"Skipping POI due to missing/invalid OSM ID: {poi.get('name')} (Type: {poi_type})")
                elif isinstance(pois_list, dict) and "error" in pois_list:
                    logging.error(f"Error fetching POIs for type {poi_type}: {pois_list['error']}")
            logging.info("Finished polling community POIs.")
        else:
            logging.info("No community POIs found for the current location/criteria.")

    except Exception as e:
        logging.error(f"Error polling community POIs: {e}", exc_info=True)


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
        
        # New polling jobs
        schedule.every(config_manager.getint("Polling", "astronomy_days", 1)).days.do(poll_astronomy_data)
        schedule.every(config_manager.getint("Polling", "space_weather_hours", 1)).hours.do(poll_space_weather_data)
        schedule.every(config_manager.getint("Polling", "community_pois_days", 7)).days.do(poll_community_pois)
        
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

