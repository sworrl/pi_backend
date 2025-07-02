#
# File: hardware_manager.py
# Version: 2.6.0 (UPS Data from DB)
#
# Description: This module acts as a central abstraction layer for hardware.
#
# Changelog (v2.6.0):
# - FEAT: `get_ups_data` now reads the latest UPS metrics directly from the
#   main application database (`pi_backend.db`) via `DatabaseManager`.
# - REFACTOR: Removed all direct dependencies and references to `ups_daemon.py`
#   and its state file, as UPS data logging is now handled by `ups_status.py`
#   logging directly to the main database.
# - FIX: Ensured INA219.py is no longer loaded or used by HardwareManager,
#   as its readings are obtained from the database.
#
import sys
import os
import logging
import importlib.util
import subprocess
import threading
import json
import time

# Import DatabaseManager to fetch UPS data from the main database
# Adjust path if necessary based on your project structure
script_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.abspath(os.path.join(script_dir, '..')))
from database import DatabaseManager

__version__ = "2.6.0"

# Configure logging for this module
logging.basicConfig(level=logging.INFO, stream=sys.stdout, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')

# Define the path to the main pi_backend database
DEFAULT_PI_BACKEND_DB_PATH = "/var/lib/pi_backend/pi_backend.db"


class HardwareManager:
    """
    Manages and abstracts interactions with various hardware components.
    Includes a real-time GPS streaming thread.
    """
    _instance = None
    _gps_lock = threading.Lock()

    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            cls._instance = super(HardwareManager, cls).__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self, app_config=None):
        if self._initialized:
            return

        self.app_config = app_config
        self._loaded_modules = {}
        
        # Initialize DatabaseManager for accessing UPS data
        self.db_manager = DatabaseManager(database_path=DEFAULT_PI_BACKEND_DB_PATH)
        if self.db_manager.connection is None:
            logging.critical("HardwareManager: Failed to connect to main database. UPS data will be unavailable.")

        self._latest_gps_data = {
            "TPV": {"class": "TPV", "mode": 0},
            "SKY": {"class": "SKY", "satellites": []},
            "last_update": 0
        }
        self._stop_gps_thread = threading.Event()
        self._gps_thread = threading.Thread(target=self._gps_reader_thread, daemon=True)

        logging.info(f"HardwareManager: Initializing (Version {__version__})")

        if os.path.join(script_dir, 'modules') not in sys.path:
            sys.path.insert(0, os.path.join(script_dir, 'modules'))

        # Load all hardware modules
        self._load_module_by_path("A7670E", "A7670E", "LTE Modem (A7670E)", os.path.join(script_dir, 'modules', 'A7670E.py'))
        self._load_module_by_path("sense_hat", "SenseHatManager", "Sense HAT", os.path.join(script_dir, 'modules', 'sense_hat.py'))
        # NOTE: INA219 is no longer loaded here. Its readings are handled by ups_status.py logging to DB.


        self._gps_thread.start()
        logging.info("HardwareManager: Real-time GPS streaming thread started.")

        self._initialized = True
        logging.info("HardwareManager: Initialization complete.")

    def _gps_reader_thread(self):
        """A background thread that continuously reads JSON data from gpsd using gpspipe."""
        logging.info("GPS Reader Thread: Starting up...")
        process = None
        while not self._stop_gps_thread.is_set():
            try:
                # Use 'gpspipe -w' for a clean JSON stream of TPV and SKY reports.
                process = subprocess.Popen(['gpspipe', '-w'], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, bufsize=1)
                for line in iter(process.stdout.readline, ''):
                    if self._stop_gps_thread.is_set():
                        break
                    try:
                        data = json.loads(line.strip())
                        if 'class' in data:
                            with self._gps_lock:
                                # We only care about TPV (Time-Position-Velocity) and SKY (Satellite) reports
                                if data['class'] in ['TPV', 'SKY']:
                                    self._latest_gps_data[data['class']] = data
                                    self._latest_gps_data["last_update"] = time.time()
                    except json.JSONDecodeError:
                        logging.debug(f"GPS Reader Thread: Skipping non-JSON line: {line.strip()}")

                if self._stop_gps_thread.is_set():
                    break

                logging.warning("GPS Reader Thread: `gpspipe -w` stream ended. Restarting in 5s.")
                time.sleep(5)

            except FileNotFoundError:
                logging.critical("GPS Reader Thread: `gpspipe` command not found. GPS streaming is disabled. Please ensure 'gpsd-clients' is installed.")
                return
            except Exception as e:
                logging.error(f"GPS Reader Thread: Error occurred: {e}. Restarting in 10s.", exc_info=True)
                time.sleep(10)
            finally:
                if process:
                    process.kill()

    def _load_module_by_path(self, module_name, class_name, friendly_name, file_path):
        """Dynamically loads a module from a file path with robust error handling."""
        try:
            if not os.path.exists(file_path):
                logging.warning(f"HardwareManager: Module file '{file_path}' not found. {friendly_name} unavailable.")
                return

            spec = importlib.util.spec_from_file_location(module_name, file_path)
            if spec is None:
                logging.error(f"Could not create module spec for {friendly_name} at {file_path}")
                return
                
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            manager_class = getattr(module, class_name)
            
            # Special handling for SenseHatManager and A7670E which need to be instantiated without args or with implicit args
            if friendly_name == "Sense HAT":
                self._loaded_modules[friendly_name] = manager_class() # SenseHatManager initializes itself
            elif friendly_name == "LTE Modem (A7670E)":
                self._loaded_modules[friendly_name] = manager_class() # A7670E initializes without direct serial port connection
            else:
                self._loaded_modules[friendly_name] = manager_class() # Generic instantiation

            logging.info(f"HardwareManager: Successfully loaded and initialized {friendly_name}.")
        except Exception as e:
            logging.error(f"HardwareManager: CRITICAL FAILURE loading module '{friendly_name}'. The hardware will be disabled. Error: {e}", exc_info=True)
            if friendly_name in self._loaded_modules:
                del self._loaded_modules[friendly_name]


    def get_manager(self, friendly_name):
        return self._loaded_modules.get(friendly_name)

    # --- UPS HAT Methods (Modified to read from main DB) ---
    def get_ups_data(self):
        """
        Retrieves UPS data from the main database.
        Returns a dictionary with current UPS status, including SoC and raw values.
        """
        if self.db_manager.connection is None:
            return {"error": "Database not connected. Cannot retrieve UPS data.", "status": "error"}
        
        try:
            latest_metric = self.db_manager.get_latest_ups_metric()
            
            if latest_metric:
                # The ups_metrics table stores battery_percentage and remaining_mah directly
                battery_percentage = latest_metric.get("battery_percentage")
                remaining_mah = latest_metric.get("remaining_mah") # Can be None if ups_status.py doesn't track it

                return {
                    "bus_voltage_V": latest_metric.get("bus_voltage_V"),
                    "current_mA": latest_metric.get("current_mA"),
                    "power_W": latest_metric.get("power_mW"), 
                    "shunt_voltage_mV": latest_metric.get("shunt_voltage_mV"),
                    "battery_voltage_V": latest_metric.get("battery_voltage_V"),
                    "remaining_mah": round(remaining_mah, 2) if remaining_mah is not None else "N/A",
                    "battery_percentage": round(battery_percentage, 2) if battery_percentage is not None else "N/A",
                    "status_text": latest_metric.get("status_text"),
                    # These timestamps are from the metric entry itself, not separate event logs
                    "last_full_charge": None, # This would require querying ups_events table
                    "last_update": latest_metric.get("timestamp"),
                    "total_charge_seconds": None, # This would require more complex aggregation
                    "total_discharge_seconds": None, # This would require more complex aggregation
                    "status": "ok"
                }
            else:
                return {"error": "No UPS data found in database. Is ups_status.py running and logging?", "status": "no_data"}
        except Exception as e:
            logging.error(f"An unexpected error occurred in get_ups_data: {e}", exc_info=True)
            return {"error": f"Unexpected error: {e}", "status": "error"}


    # --- GNSS (GPS) Methods ---
    def get_best_gnss_data(self):
        """Retrieves the latest GNSS data directly from the real-time cache."""
        with self._gps_lock:
            # Check for stale data if last_update is older than 10 seconds
            if time.time() - self._latest_gps_data.get("last_update", 0) > 10:
                return {"error": "Stale GPS data. `gpspipe` stream may be down or no fix.", "fix_type": "No Fix"}
            tpv_data = self._latest_gps_data.get("TPV", {})
            sky_data = self._latest_gps_data.get("SKY", {})

        fix_mode = tpv_data.get('mode', 0)
        fix_type_map = {0: 'No Fix', 1: 'No Fix', 2: '2D Fix', 3: '3D Fix'}

        altitude = tpv_data.get('altHAE')
        if altitude is None:
            altitude = tpv_data.get('altMSL')
        if altitude is None:
            altitude = tpv_data.get('alt')

        return {
            "source": "Realtime gpspipe Stream",
            "fix_type": fix_type_map.get(fix_mode, "Unknown"),
            "latitude": tpv_data.get('lat'),
            "longitude": tpv_data.get('lon'),
            "altitude_m": altitude,
            "speed_mps": tpv_data.get('speed'),
            "track_deg": tpv_data.get('track'),
            "climb_mps": tpv_data.get('climb'),
            "time_utc": tpv_data.get('time'),
            "satellites_used": sky_data.get('uSat', 0),
            "satellites_in_view": sky_data.get('nSat', 0),
            "error_horizontal_m": tpv_data.get('epx'),
            "error_vertical_m": tpv_data.get('epv'),
        }

    def get_raw_gps_cache(self):
        """Returns a copy of the internal raw GPS data cache for debugging."""
        with self._gps_lock:
            return self._latest_gps_data.copy()

    def get_gpsd_status(self):
        """Checks the status of core GPS-related services."""
        services = ["gpsd.service", "a7670e-gps-init.service"]
        status_report = {}
        for service in services:
            try:
                result = subprocess.run(['systemctl', 'is-active', service], capture_output=True, text=True)
                status_report[service] = result.stdout.strip()
            except Exception as e:
                 status_report[service] = f"error: {e}"
        return status_report

    # --- LTE Methods ---
    def get_lte_network_info(self):
        """Gets detailed network information from the LTE modem."""
        lte_manager = self.get_manager("LTE Modem (A7670E)")
        if not lte_manager: return {"error": "LTE Modem module not loaded or failed to initialize."}
        return {
            "signal_quality": lte_manager.send_at_command("AT+CSQ", "+CSQ:"),
            "network_registration": lte_manager.send_at_command("AT+CREG?", "+CREG:"),
            "operator_info": lte_manager.send_at_command("AT+COPS?", "+COPS:")
        }

    def set_lte_flight_mode(self, enable: bool):
        """Enables or disables the LTE modem's flight mode."""
        lte_manager = self.get_manager("LTE Modem (A7670E)")
        if not lte_manager: return {"error": "LTE Modem module not loaded."}
        command = 'AT+CFUN=4' if enable else 'AT+CFUN=1'
        response = lte_manager.send_at_command(command, "OK")
        if response:
            return {"success": True, "message": f"Flight mode set to {enable}."}
        return {"error": "Failed to set flight mode."}

    # --- Sense HAT Methods ---
    def get_sense_hat_data(self):
        """Gets the latest sensor and joystick data from Sense HAT."""
        sense_hat_manager = self.get_manager("Sense HAT")
        if sense_hat_manager:
            return sense_hat_manager.get_current_state()
        return {"error": "Sense HAT module not loaded or available."}

    def sense_hat_execute_command(self, command, params=None):
        """Executes a generic command on the Sense HAT."""
        sense_hat_manager = self.get_manager("Sense HAT")
        if sense_hat_manager:
            return sense_hat_manager.execute_command(command, params or {})
        return {"error": "Sense HAT module not loaded."}

    # --- General Methods ---
    def close_all(self):
        """Stops threads and closes connections for all loaded hardware modules."""
        logging.info("HardwareManager: Closing all hardware and stopping threads.")
        self._stop_gps_thread.set()
        if self._gps_thread.is_alive():
            self._gps_thread.join(timeout=2)

        for name, manager_instance in self._loaded_modules.items():
            if hasattr(manager_instance, 'close'):
                try:
                    manager_instance.close()
                    logging.info(f"Closed connection for {name}.")
                except Exception as e:
                    logging.error(f"Error closing {name}: {e}")

