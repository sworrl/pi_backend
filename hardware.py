#
# File: hardware.py
# Version: 3.3.0 (Added Chrony Tracking Stats)
#
# Description: Provides functions to interact with Raspberry Pi hardware
#              components like system stats, GPIO, Bluetooth, and chrony.
#
# Changelog (v3.3.0):
# - FEATURE: Added `get_chrony_tracking_stats` to execute `chronyc tracking`
#   and parse its output into a structured dictionary for the new time sync API.
#
# DEV_NOTES:
# - v3.2.0:
#   - REFACTOR: Removed LTE modem power control functions. These are now
#     handled by the dedicated `A7670E.py` module via the `HardwareManager`.
#
import os
import sys
import time
import subprocess
import psutil
from datetime import datetime
import re
import logging

try:
    import RPi.GPIO as GPIO
    GPIO_AVAILABLE = True
except (ImportError, RuntimeError):
    GPIO_AVAILABLE = False
    print("[WARN] RPi.GPIO not found or failed to import. GPIO features disabled.", file=sys.stderr)

try:
    import bluetooth
    BLUETOOTH_AVAILABLE = True
except ImportError:
    BLUETOOTH_AVAILABLE = False
    print("[WARN] PyBluez library not found. Bluetooth features disabled.", file=sys.stderr)


__version__ = "3.3.0"

# --- GPIO Setup (Only for general-purpose GPIO now, not LTE specific) ---
_gpio_setup_done = False
def _setup_gpio():
    """Initializes general-purpose GPIO pins for the application."""
    global _gpio_setup_done, GPIO_AVAILABLE
    if not GPIO_AVAILABLE or _gpio_setup_done:
        return
    try:
        GPIO.setwarnings(False)
        GPIO.setmode(GPIO.BCM)
        _gpio_setup_done = True
        print("[INFO] GPIO setup complete for general purpose pins.", file=sys.stderr)
    except Exception as e:
        print(f"[ERROR] General GPIO setup failed: {e}", file=sys.stderr)
        GPIO_AVAILABLE = False

def cleanup_gpio():
    """Cleans up GPIO resources. Called on application shutdown."""
    if GPIO_AVAILABLE and _gpio_setup_done:
        GPIO.cleanup()
        print("[INFO] GPIO cleaned up.", file=sys.stderr)

_setup_gpio()

# --- System Information (PSUTIL) ---
def get_cpu_usage():
    """Returns the current CPU usage percentage."""
    try:
        return psutil.cpu_percent(interval=0.1)
    except Exception as e:
        return {"error": f"Failed to get CPU usage: {e}"}

def get_memory_usage():
    """Returns the current system memory usage percentage."""
    try:
        return psutil.virtual_memory().percent
    except Exception as e:
        return {"error": f"Failed to get memory usage: {e}"}

def get_disk_usage(path='/'):
    """Returns disk usage statistics for a given path."""
    try:
        du = psutil.disk_usage(path)
        return {
            "path": path,
            "total_gb": round(du.total / (1024**3), 2),
            "used_gb": round(du.used / (1024**3), 2),
            "free_gb": round(du.free / (1024**3), 2),
            "percent": du.percent
        }
    except Exception as e:
        return {"error": f"Failed to get disk usage for {path}: {e}"}

def get_boot_time():
    """Returns the system boot time in a human-readable format."""
    try:
        return datetime.fromtimestamp(psutil.boot_time()).strftime("%Y-%m-%d %H:%M:%S")
    except Exception as e:
        return {"error": f"Failed to get boot time: {e}"}

# --- Bluetooth Functions ---
def find_bluetooth_devices(duration=8):
    """Scans for nearby Bluetooth devices."""
    if not BLUETOOTH_AVAILABLE:
        return {"error": "PyBluez library not available."}

    print("[INFO] Starting Bluetooth device scan...", file=sys.stderr)
    try:
        nearby_devices = bluetooth.discover_devices(duration=duration, lookup_names=True,
                                                    flush_cache=True, lookup_class=False)
        devices = [{"address": addr, "name": name} for addr, name in nearby_devices]
        print(f"[INFO] Found {len(devices)} Bluetooth devices.", file=sys.stderr)
        return {"devices": devices, "device_count": len(devices)}
    except Exception as e:
        return {"error": f"Failed to scan for Bluetooth devices: {e}."}

# --- Chrony Time Sync Functions ---
def get_chrony_tracking_stats():
    """
    Executes 'chronyc tracking' and parses the output into a structured dictionary.
    """
    try:
        # Get chrony tracking data
        result = subprocess.run(['chronyc', 'tracking'], capture_output=True, text=True, check=True)
        tracking_output = result.stdout

        # Get chrony service status
        status_result = subprocess.run(['systemctl', 'is-active', 'chrony'], capture_output=True, text=True)
        service_status = status_result.stdout.strip()

        # Parse the output using regex or simple string splitting
        stats = {}
        for line in tracking_output.splitlines():
            parts = line.split(':')
            if len(parts) >= 2:
                key = parts[0].strip().lower().replace(' ', '_')
                value = ':'.join(parts[1:]).strip()
                stats[key] = value

        # Clean up and format the parsed data
        parsed_data = {
            "reference_id": stats.get("reference_id", "N/A"),
            "stratum": stats.get("stratum", "N/A"),
            "ref_time_utc": stats.get("ref_time", "N/A"),
            "system_time_offset_s": stats.get("system_time", "0.0 seconds").split()[0],
            "last_update_ago_s": stats.get("last_offset", "0.0 seconds").split()[0],
            "rms_offset_s": stats.get("rms_offset", "0.0 seconds").split()[0],
            "frequency_skew_ppm": stats.get("frequency", "0.0 ppm").split()[0],
            "residual_freq_ppm": stats.get("residual_freq", "0.0 ppm").split()[0],
            "root_delay_s": stats.get("root_delay", "0.0 seconds").split()[0],
            "root_dispersion_s": stats.get("root_dispersion", "0.0 seconds").split()[0],
            "update_interval_s": stats.get("update_interval", "0.0 seconds").split()[0],
            "leap_status": stats.get("leap_status", "N/A"),
            "service_status": service_status
        }
        return parsed_data

    except FileNotFoundError:
        logging.error("`chronyc` command not found. Is chrony installed?")
        return {"error": "chronyc command not found. Please ensure chrony is installed and running."}
    except subprocess.CalledProcessError as e:
        logging.error(f"Error executing 'chronyc tracking': {e.stderr}")
        return {"error": f"Failed to get chrony tracking data: {e.stderr}"}
    except Exception as e:
        logging.error(f"An unexpected error occurred while getting chrony stats: {e}")
        return {"error": "An unexpected error occurred."}
