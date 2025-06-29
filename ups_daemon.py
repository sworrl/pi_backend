#!/usr/bin/env python3
# -*- coding:utf-8 -*-

# ==============================================================================
# UPS Power HAT Advanced Monitoring Daemon
# ==============================================================================
# Description:
#   A persistent background service that accurately tracks battery State of
#   Charge (SoC) using coulomb counting. It logs key events like status
#   changes, full charges, and battery empty events, with a placeholder
#   for integration into a SQL database.
#
# Author: Gemini
# Version: 1.0.1 (Integrate with pi_backend INA219, store full state)
# ==============================================================================

import smbus
import time
import os
import json
import argparse
from datetime import datetime, timezone
import traceback # For detailed error logging

# --- Configuration ---
BATTERY_CAPACITY_MAH = 7000.0
VOLTAGE_FULL = 8.35   # Voltage at which we consider the battery fully charged (4.175V per cell)
VOLTAGE_EMPTY = 6.4   # Voltage at which we consider the battery empty (3.2V per cell)
CURRENT_CHARGE_DONE_MA = 20 # Current below which we consider charging to be complete
SAMPLE_RATE_SECONDS = 5     # How often to sample the sensor
SAVE_STATE_INTERVAL_SECONDS = 60 # How often to write the state to disk

# --- File Paths ---
STATE_FILE_PATH = "/var/lib/ups_daemon/state.json"
I2C_BUS_DEVICE = "/dev/i2c-1"

# --- Hardware Constants ---
INA219_ADDRESS = 0x42
REG_CONFIG = 0x00
REG_SHUNTVOLTAGE = 0x01 # Added missing register definition [from ups_status.py]
REG_BUSVOLTAGE = 0x02
REG_POWER = 0x03      # Added missing register definition [from ups_status.py]
REG_CURRENT = 0x04
REG_CALIBRATION = 0x05

# --- Database Integration Placeholder ---
def log_event_to_database(event_type, details_dict):
    """
    Placeholder function for SQL integration.
    This is where you would add your code to connect to your pi_backend
    database and insert a new event record.
    """
    timestamp = datetime.now(timezone.utc).isoformat()
    print(f"[LOG] Event: {event_type} | Timestamp: {timestamp} | Details: {details_dict}")
    
    # --- EXAMPLE SQL INTEGRATION (from ups_daemon.py prompt) ---
    # import sqlite3
    # try:
    #    conn = sqlite3.connect('/path/to/your/backend.db')
    #    cursor = conn.cursor()
    #    cursor.execute(
    #        "INSERT INTO battery_events (timestamp, event_type, details) VALUES (?, ?, ?)",
    #        (timestamp, event_type, json.dumps(details_dict))
    #    )
    #    conn.commit()
    #    conn.close()
    # except Exception as e:
    #    print(f"[LOG ERROR] Failed to write to database: {e}")
    # -------------------------------


class INA219:
    """
    Handles I2C communication with the INA219 sensor.
    Implementation re-aligned with pi_backend/ups_status.py for consistency.
    """
    def __init__(self, address=INA219_ADDRESS, busnum=1):
        self.bus = smbus.SMBus(busnum)
        self.addr = address
        
        # Default configuration values matching ups_status.py
        self.bus.write_i2c_block_data(self.addr, REG_CONFIG, [0x01, 0x9F])
        
        # Calibrate for a 0.1-ohm shunt resistor and 2A max current (matching ups_status.py)
        self.bus.write_i2c_block_data(self.addr, REG_CALIBRATION, [0x10, 0x00])

    def read_voltage(self): # Reads Bus Voltage (VBUS)
        read = self.bus.read_i2c_block_data(self.addr, REG_BUSVOLTAGE, 2)
        p_v = (read[0] * 256 + read[1])
        return (p_v >> 3) * 0.004

    def read_shunt_voltage(self): # Reads Shunt Voltage (VSHUNT)
        read = self.bus.read_i2c_block_data(self.addr, REG_SHUNTVOLTAGE, 2)
        if read[0] > 127: # Handle two's complement for negative shunt voltage
            read[0] = 256 - read[0]
            read[1] = 255 - read[1]
            p_v = (read[0] * 256 + read[1] + 1) * -1
        else:
            p_v = (read[0] * 256 + read[1])
        return p_v * 0.01 # Returns in mV
        
    def read_current(self): # Reads Current (I)
        current_raw = self.bus.read_i2c_block_data(self.addr, REG_CURRENT, 2)
        current_val = (current_raw[0] << 8) | current_raw[1]
        if current_val > 32767: # Handle two's complement for negative current
            current_val -= 65536
        return current_val * 0.05 # Returns in mA

    def read_power(self): # Reads Power (P)
        power_raw = self.bus.read_i2c_block_data(self.addr, REG_POWER, 2)
        power_val = (power_raw[0] << 8) | power_raw[1]
        return power_val * 1.0 # Returns in mW

def load_state():
    """Loads the battery state from the JSON file."""
    if os.path.exists(STATE_FILE_PATH):
        try:
            with open(STATE_FILE_PATH, 'r') as f:
                state = json.load(f)
            # Ensure new keys are present, for compatibility with older state files
            state.setdefault("last_known_bus_voltage", 0.0)
            state.setdefault("last_known_shunt_voltage", 0.0)
            state.setdefault("last_known_battery_voltage", 0.0)
            state.setdefault("last_known_current_ma", 0.0)
            state.setdefault("last_known_power_mw", 0.0)
            state.setdefault("BATTERY_CAPACITY_MAH", BATTERY_CAPACITY_MAH) # Ensure capacity is stored
            return state
        except (json.JSONDecodeError, KeyError) as e:
            print(f"WARNING: Corrupted or old state file found: {e}. Re-initializing state.")
            os.remove(STATE_FILE_PATH) # Remove corrupted file
            return _initial_state()
    else:
        return _initial_state()

def _initial_state():
    """Returns a new, default battery state dictionary."""
    now_iso = datetime.now(timezone.utc).isoformat()
    return {
        "remaining_mah": BATTERY_CAPACITY_MAH,
        "last_known_status": "UNKNOWN",
        "last_full_charge_timestamp": now_iso,
        "last_empty_timestamp": None,
        "total_charge_seconds": 0,
        "total_discharge_seconds": 0,
        "last_update_timestamp": now_iso,
        "last_known_bus_voltage": 0.0,
        "last_known_shunt_voltage": 0.0,
        "last_known_battery_voltage": 0.0,
        "last_known_current_ma": 0.0,
        "last_known_power_mw": 0.0,
        "BATTERY_CAPACITY_MAH": BATTERY_CAPACITY_MAH # Store constant for reference
    }


def save_state(state):
    """Saves the current battery state to the JSON file."""
    # Ensure directory exists
    os.makedirs(os.path.dirname(STATE_FILE_PATH), exist_ok=True)
    with open(STATE_FILE_PATH, 'w') as f:
        json.dump(state, f, indent=4)

def determine_status(voltage, current_ma):
    """Determines the battery's current status string."""
    if current_ma > CURRENT_CHARGE_DONE_MA:
        return "CHARGING"
    elif current_ma < -5: # Discharging if current is significantly negative
        return "DISCHARGING"
    else: # Near-zero current
        if voltage >= VOLTAGE_FULL:
            return "CHARGED"
        elif voltage <= VOLTAGE_EMPTY: # If voltage is very low, it's empty even if not discharging
            return "EMPTY"
        else:
            return "IDLE"

def run_daemon():
    """The main continuous loop for the monitoring service."""
    state = load_state()
    ina219 = None # Initialize INA219 inside the loop for robustness

    while True:
        try:
            if ina219 is None: # Attempt to (re)initialize INA219 if it's not set up
                ina219 = INA219()
                # On successful re-init, log it
                log_event_to_database("INA219_INIT", {"message": "INA219 sensor re-initialized."})

            # Read all sensor values
            bus_voltage = ina219.read_voltage()
            shunt_voltage = ina219.read_shunt_voltage()
            current_ma = ina219.read_current()
            power_mw = ina219.read_power()

            battery_voltage = bus_voltage + (shunt_voltage / 1000.0)

            now = time.time()
            now_iso = datetime.now(timezone.utc).isoformat()
            
            last_update_time = datetime.fromisoformat(state["last_update_timestamp"]).timestamp()
            time_delta_seconds = now - last_update_time

            # Store current live values in state for API access
            state["last_known_bus_voltage"] = round(bus_voltage, 2)
            state["last_known_shunt_voltage"] = round(shunt_voltage, 2)
            state["last_known_battery_voltage"] = round(battery_voltage, 2)
            state["last_known_current_ma"] = round(current_ma, 2)
            state["last_known_power_mw"] = round(power_mw, 2)

            # --- Coulomb Counting ---
            # mAh = (mA * hours) = (mA * seconds / 3600)
            charge_moved_mah = (current_ma * time_delta_seconds) / 3600.0
            state["remaining_mah"] += charge_moved_mah
            # Clamp the value between 0 and full capacity
            state["remaining_mah"] = max(0.0, min(state["BATTERY_CAPACITY_MAH"], state["remaining_mah"]))
            
            # --- Aggregate Timers ---
            if current_ma > 0:
                state["total_charge_seconds"] += time_delta_seconds
            elif current_ma < 0:
                state["total_discharge_seconds"] += time_delta_seconds

            state["last_update_timestamp"] = now_iso
            
            # --- Event Detection ---
            current_status = determine_status(battery_voltage, current_ma)
            if current_status != state["last_known_status"]:
                # Log the status change event
                log_event_to_database("STATUS_CHANGE", {
                    "old_status": state["last_known_status"],
                    "new_status": current_status,
                    "voltage": state["last_known_battery_voltage"],
                    "current_ma": state["last_known_current_ma"],
                    "soc_percent": round((state["remaining_mah"] / state["BATTERY_CAPACITY_MAH"]) * 100, 1)
                })

                # Check for specific "full" or "empty" events
                if current_status == "CHARGED":
                    state["remaining_mah"] = state["BATTERY_CAPACITY_MAH"] # Recalibrate to full
                    state["last_full_charge_timestamp"] = now_iso
                    log_event_to_database("BATTERY_FULL", {"timestamp": now_iso, "voltage": state["last_known_battery_voltage"]})
                
                if current_status == "EMPTY": # Use the new 'EMPTY' status
                    state["remaining_mah"] = 0.0 # Recalibrate to empty
                    state["last_empty_timestamp"] = now_iso
                    log_event_to_database("BATTERY_EMPTY", {"timestamp": now_iso, "voltage": state["last_known_battery_voltage"]})

                state["last_known_status"] = current_status

            # Periodically save state to disk
            if now - last_save_time > SAVE_STATE_INTERVAL_SECONDS:
                save_state(state)
                last_save_time = now

        except (IOError, FileNotFoundError, smbus.i2c.SMBusError) as e:
            # Handle hardware communication errors
            log_event_to_database("SENSOR_ERROR", {"message": f"Could not read from INA219 sensor. Error: {e}", "trace": traceback.format_exc()})
            ina219 = None # Invalidate INA219 object to force re-initialization on next loop
            time.sleep(60) # Wait longer before retrying if there's a hardware error
        except Exception as e:
            # Catch any other unexpected errors
            log_event_to_database("DAEMON_ERROR", {"message": str(e), "trace": traceback.format_exc()})
            time.sleep(60)

        time.sleep(SAMPLE_RATE_SECONDS)

def handle_args():
    """Handles command-line arguments for calibration and status checks."""
    parser = argparse.ArgumentParser(description="UPS HAT Monitoring Daemon and Utility.")
    parser.add_argument('command', nargs='?', choices=['start', 'status', 'calibrate'], help="Command to execute.")
    
    args = parser.parse_args()

    if args.command == 'calibrate':
        print("Calibrating battery state to 100%...")
        now_iso = datetime.now(timezone.utc).isoformat()
        initial_state = _initial_state()
        initial_state["last_known_status"] = "CHARGED" # Calibrate to CHARGED state
        save_state(initial_state)
        print("Calibration complete. The daemon will now use this full state as a baseline.")

    elif args.command == 'status':
        state = load_state()
        percentage = (state["remaining_mah"] / state["BATTERY_CAPACITY_MAH"]) * 100
        print("========================================")
        print("       UPS Daemon Live Status")
        print("========================================")
        print(f"  Status:               {state['last_known_status']}")
        print(f"  Estimated SoC:        {percentage:.1f}%")
        print(f"  Remaining Capacity:   {state['remaining_mah']:.0f} mAh")
        print(f"  Last Known Voltage:   {state['last_known_battery_voltage']:.2f} V")
        print(f"  Last Known Current:   {state['last_known_current_ma']:.2f} mA")
        print(f"  Last Known Power:     {state['last_known_power_mw']:.2f} mW")
        print(f"  Last Full Charge:     {state['last_full_charge_timestamp']}")
        print(f"  Last Empty:           {state['last_empty_timestamp'] or 'N/A'}")
        print(f"  Total Time Charging:  {state['total_charge_seconds']/3600:.2f} hours")
        print(f"  Total Time Discharging: {state['total_discharge_seconds']/3600:.2f} hours")
        print("========================================")

    elif args.command == 'start':
        print("Starting UPS monitoring daemon...")
        run_daemon()
    else:
        print("No command provided. Use 'start', 'status', or 'calibrate'.")
        print("This script is intended to be run as a systemd service.")

if __name__ == "__main__":
    if not os.path.exists(I2C_BUS_DEVICE):
        print(f"Error: I2C interface '{I2C_BUS_DEVICE}' not found.")
        print("Please enable I2C via 'sudo raspi-config'.")
        exit(1)
    
    handle_args()
