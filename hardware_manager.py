#
# File: hardware_manager.py
# Version: 2.4.0 (Waveshare UPS HAT Integration)
#
# Description: This module acts as a central abstraction layer for hardware.
#
# Changelog (v2.4.0):
# - FEAT: Added full integration for Waveshare UPS HAT (INA219).
#   - It now loads the 'ina219.py' module on initialization.
#   - Added a `get_ups_data` method to read and return UPS voltage and current.
#   - Note: Requires 'python3-smbus' and i2c group permissions.
#
import sys
import os
import logging
import importlib.util
import subprocess
import threading
import json
import time

__version__ = "2.4.0"

# Configure logging for this module
logging.basicConfig(level=logging.INFO, stream=sys.stdout, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')

# Determine the base directory of the project
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
MODULES_DIR = os.path.join(SCRIPT_DIR, 'modules')

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

        self._latest_gps_data = {
            "TPV": {"class": "TPV", "mode": 0},
            "SKY": {"class": "SKY", "satellites": []},
            "last_update": 0
        }
        self._stop_gps_thread = threading.Event()
        self._gps_thread = threading.Thread(target=self._gps_reader_thread, daemon=True)

        logging.info(f"HardwareManager: Initializing (Version {__version__})")

        if MODULES_DIR not in sys.path:
            sys.path.insert(0, MODULES_DIR)

        # Load all hardware modules
        self._load_module_by_path("A7670E", "A7670E", "LTE Modem (A7670E)", os.path.join(MODULES_DIR, 'A7670E.py'))
        self._load_module_by_path("sense_hat", "SenseHatManager", "Sense HAT", os.path.join(MODULES_DIR, 'sense_hat.py'))
        self._load_module_by_path("ina219", "INA219", "Waveshare UPS HAT", os.path.join(MODULES_DIR, 'ina219.py'))


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
            
            self._loaded_modules[friendly_name] = manager_class()
            
            logging.info(f"HardwareManager: Successfully loaded and initialized {friendly_name}.")
        except Exception as e:
            logging.error(f"HardwareManager: CRITICAL FAILURE loading module '{friendly_name}'. The hardware will be disabled. Error: {e}", exc_info=True)
            if friendly_name in self._loaded_modules:
                del self._loaded_modules[friendly_name]


    def get_manager(self, friendly_name):
        return self._loaded_modules.get(friendly_name)

    # --- UPS HAT Methods (New) ---
    def get_ups_data(self):
        """Gets voltage and current from the Waveshare UPS HAT."""
        ups_manager = self.get_manager("Waveshare UPS HAT")
        if not ups_manager:
            return {"error": "Waveshare UPS HAT module not loaded or failed to initialize."}
        
        try:
            bus_voltage = ups_manager.get_bus_voltage_V()
            current_mA = ups_manager.get_current_mA()
            
            # The power (in watts) can be calculated. P = V * I
            # Convert current from mA to A for the calculation.
            power_W = bus_voltage * (current_mA / 1000.0)

            return {
                "bus_voltage_V": round(bus_voltage, 2),
                "current_mA": round(current_mA, 2),
                "power_W": round(power_W, 2),
                "status": "ok"
            }
        except Exception as e:
            # This can happen if there's an I2C communication error
            logging.error(f"Error reading from UPS HAT (INA219): {e}", exc_info=True)
            return {"error": f"Failed to read from UPS HAT. Check I2C connection. Error: {e}"}

    # --- GNSS (GPS) Methods ---
    def get_best_gnss_data(self):
        """Retrieves the latest GNSS data directly from the real-time cache."""
        with self._gps_lock:
            if time.time() - self._latest_gps_data.get("last_update", 0) > 10:
                return {"error": "Stale GPS data. `gpspipe` stream may be down."}
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
            "source": "Realtime gpspipe Stream", "fix_type": fix_type_map.get(fix_mode, "Unknown"),
            "latitude": tpv_data.get('lat'), "longitude": tpv_data.get('lon'),
            "altitude_m": altitude, "speed_mps": tpv_data.get('speed'),
            "track_deg": tpv_data.get('track'), "climb_mps": tpv_data.get('climb'),
            "time_utc": tpv_data.get('time'), "satellites_used": sky_data.get('uSat', 0),
            "satellites_in_view": sky_data.get('nSat', 0),
            "error_horizontal_m": tpv_data.get('epx'), "error_vertical_m": tpv_data.get('epv'),
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
