#
# File: sense_hat.py
# Version: 1.1.0 (Resilient Initialization)
#
# Description: This module provides a consolidated driver for the Raspberry Pi
#              Sense HAT.
#
# Changelog (v1.1.0):
# - FIX: Implemented a resilient initialization pattern. The module now attempts
#   to re-initialize the SenseHat connection on each command/data request if
#   it failed on the initial application startup. This resolves race conditions
#   where the app starts before the OS hardware drivers are ready.
#
import sys
import os
import time
import json
import logging
from threading import Thread, Event

# --- Module-level state ---
_sense_instance = None
_sense_hat_initialized = False
SENSE_HAT_AVAILABLE = False

# Configure logging for this module
logging.basicConfig(level=logging.INFO, stream=sys.stdout, format='%(asctime)s - %(levelname)s - %(message)s')

def _initialize_sense_hat():
    """
    Tries to initialize the Sense HAT connection.
    This can be called multiple times if the first attempt fails.
    """
    global _sense_instance, _sense_hat_initialized, SENSE_HAT_AVAILABLE

    if _sense_hat_initialized:
        return

    try:
        from sense_hat import SenseHat, SenseHatEmulator
        SENSE_HAT_AVAILABLE = True
        try:
            _sense_instance = SenseHat()
            logging.info("Successfully initialized real Sense HAT hardware.")
            _sense_hat_initialized = True
        except Exception as e:
            logging.warning(f"Failed to initialize real Sense HAT: {e}. Falling back to emulator for now.")
            try:
                _sense_instance = SenseHatEmulator()
                logging.info("Successfully initialized SenseHatEmulator as a fallback.")
                _sense_hat_initialized = True
            except Exception as emu_e:
                 logging.error(f"SenseHatEmulator also failed to initialize: {emu_e}. Sense HAT features disabled.")
                 SENSE_HAT_AVAILABLE = False
                 _sense_instance = None

    except ImportError:
        SENSE_HAT_AVAILABLE = False
        _sense_instance = None
        logging.critical("[CRITICAL] Sense HAT library not found. Sense HAT features will be disabled.")
    except Exception as e:
        SENSE_HAT_AVAILABLE = False
        _sense_instance = None
        logging.critical(f"[CRITICAL] Unhandled error during Sense HAT import/initialization: {e}. Features disabled.")

# Attempt initialization on module load
_initialize_sense_hat()

__version__ = "1.1.0"

# --- Polling Configuration ---
POLLING_INTERVAL_SECONDS = 0.2

class SenseHatManager:
    """
    Manages direct interactions with the Sense HAT hardware.
    Polls data in a background thread and provides methods for LED control.
    """
    def __init__(self, config=None):
        """
        Initializes the Sense HAT manager.
        """
        self.sense = None # Will be set on-demand
        self._check_and_set_sense_instance()

        self._current_state = {
            "sensors": {},
            "joystick_events": [],
            "last_update": 0
        }
        self._polling_stop_event = Event()
        self.polling_thread = Thread(target=self._polling_loop, daemon=True)

        if self.sense:
            self.polling_thread.start()
            logging.info("Sense HAT polling thread started.")
        else:
             logging.error("SenseHatManager initialized but no hardware/emulator is available yet. Will retry on access.")


    def _check_and_set_sense_instance(self):
        """Ensures the Sense HAT is initialized before use."""
        if not self.sense:
            _initialize_sense_hat() # Attempt re-initialization
            if _sense_hat_initialized:
                self.sense = _sense_instance
                if self.sense:
                    self.sense.clear()
                    # If the polling thread wasn't running, start it now.
                    if not self.polling_thread.is_alive():
                        self.polling_thread.start()
                        logging.info("Sense HAT connection established and polling thread started.")

    def _get_cpu_temperature(self):
        """Reads the CPU temperature for calibration."""
        try:
            with open("/sys/class/thermal/thermal_zone0/temp", "r") as f:
                return float(f.read()) / 1000.0
        except Exception:
            return 45.0 # Return a fallback value

    def _polling_loop(self):
        """Background thread loop for continuously polling Sense HAT data."""
        while not self._polling_stop_event.is_set():
            if not self.sense:
                # If we lose the sense object for any reason, wait before retrying.
                self._polling_stop_event.wait(5)
                self._check_and_set_sense_instance()
                continue

            try:
                # --- Sensor Polling ---
                temp_from_humidity = self.sense.get_temperature_from_humidity()
                temp_from_pressure = self.sense.get_temperature_from_pressure()
                cpu_temp = self._get_cpu_temperature()
                temp_raw_avg = (temp_from_humidity + temp_from_pressure) / 2

                corrected_temp = temp_raw_avg - ((cpu_temp - temp_raw_avg) / 2) if cpu_temp is not None else None

                sensor_data = {
                    "temperature_raw_humidity_c": round(temp_from_humidity, 2),
                    "temperature_raw_pressure_c": round(temp_from_pressure, 2),
                    "temperature_cpu_c": round(cpu_temp, 2) if cpu_temp else None,
                    "temperature_corrected_c": round(corrected_temp, 2) if corrected_temp else None,
                    "pressure_hpa": round(self.sense.get_pressure(), 2),
                    "humidity_percent": round(self.sense.get_humidity(), 2),
                    "orientation_degrees": {k: round(v, 2) for k, v in self.sense.get_orientation_degrees().items()},
                    "accelerometer_raw": {k: round(v, 2) for k, v in self.sense.get_accelerometer_raw().items()},
                }
                self._current_state["sensors"] = sensor_data

                # --- Joystick Polling ---
                joystick_events = [
                    {"timestamp": event.timestamp, "direction": event.direction, "action": event.action}
                    for event in self.sense.stick.get_events()
                ]
                if joystick_events:
                    self._current_state["joystick_events"].extend(joystick_events)
                    self._current_state["joystick_events"] = self._current_state["joystick_events"][-20:]

                self._current_state["last_update"] = time.time()

            except Exception as e:
                logging.error(f"Error in Sense HAT polling loop: {e}", exc_info=True)
                self._current_state["sensors"]["error"] = f"Polling error: {str(e)}"
                self._current_state["joystick_events"] = []
                self.sense = None # Invalidate sense object on error to force re-init
                _sense_hat_initialized = False

            self._polling_stop_event.wait(POLLING_INTERVAL_SECONDS)

    def get_current_state(self):
        """
        Returns the latest polled sensor data and joystick events.
        """
        self._check_and_set_sense_instance() # Ensure connection is active
        if not self.sense:
            return {"error": "Sense HAT hardware is not available or failed to initialize."}
        return self._current_state

    def execute_command(self, command, params=None):
        """
        Executes a command on the Sense HAT LED matrix.
        """
        self._check_and_set_sense_instance() # Ensure connection is active
        if not self.sense:
            return {"error": "Sense HAT hardware not available. Command not executed."}

        params = params or {}
        logging.info(f"Executing Sense HAT command '{command}' with params {params}")

        try:
            if command == "display_message":
                self.sense.show_message(
                    params.get("text", "Hello"),
                    text_colour=params.get("text_colour", [255, 255, 255]),
                    back_colour=params.get("back_colour", [0, 0, 0]),
                    scroll_speed=params.get("scroll_speed", 0.1)
                )
            elif command == "set_pixels":
                pixel_list = params.get("pixel_list")
                if isinstance(pixel_list, list) and len(pixel_list) == 64:
                    self.sense.set_pixels([tuple(p) for p in pixel_list])
                else:
                    return {"error": "Invalid pixel_list format."}
            elif command == "clear":
                self.sense.clear()
            else:
                return {"error": f"Unknown Sense HAT command: {command}"}

            return {"success": True, "message": f"Command '{command}' executed."}
        except Exception as e:
            logging.error(f"Error executing Sense HAT command '{command}': {e}", exc_info=True)
            return {"success": False, "error": str(e)}

    def close(self):
        """
        Stops the background polling thread and cleans up Sense HAT resources.
        """
        logging.info("SenseHatManager: Stopping polling thread and clearing Sense HAT.")
        self._polling_stop_event.set()
        if self.polling_thread and self.polling_thread.is_alive():
            self.polling_thread.join(timeout=2)

        if self.sense:
            try:
                self.sense.clear()
            except Exception as e:
                logging.error(f"Error clearing Sense HAT on close: {e}")
