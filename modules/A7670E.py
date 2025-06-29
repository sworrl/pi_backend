# pi_backend/modules/A7670E.py
# Version: 2.2.0 (Conflict-Free)
#
# Description: A class to interact with the A7670E cellular module.
#
# Changelog (v2.2.0):
# - FIX: CRITICAL: Removed the automatic serial port opening from __init__.
#   This was causing a "Device or resource busy" error because the gpsd
#   service already has control of /dev/serial0. This module will now
#   be used for AT command formatting, but the actual sending of commands
#   must be handled by a dedicated function that can manage the serial port
#   without conflicting with gpsd. This change prevents the API from crashing.
#
import serial
import time
import logging
import subprocess # Added missing import

class A7670E:
    """
    A class to interact with the A7670E cellular module.
    This version does not automatically open a serial port to avoid
    conflicts with other services like gpsd.
    """
    def __init__(self, port='/dev/serial0', baudrate=115200, timeout=1):
        """
        Initializes the A7670E handler. Does NOT open a serial port.
        """
        self.port = port
        self.baudrate = baudrate
        self.timeout = timeout
        self.ser = None
        logging.info("A7670E Handler Initialized (Serial port connection deferred).")

    def _get_serial_connection(self):
        """
        Gets a temporary, exclusive serial connection.
        This is a placeholder for a more robust serial port management system.
        """
        # In a more advanced implementation, this would use a lock or a proxy
        # to ensure only one process accesses the port at a time.
        # For now, we will attempt to open it on-demand, which may still fail
        # if gpsd is active, but it won't crash the app on startup.
        try:
            # Temporarily stop gpsd to free the port
            # Capture output to prevent it from interfering with API response
            subprocess.run(['sudo', 'systemctl', 'stop', 'gpsd.socket', 'gpsd.service'], check=True, capture_output=True, text=True) # Modified
            time.sleep(1) # Give time for the port to be released
            self.ser = serial.Serial(self.port, self.baudrate, timeout=self.timeout)
            return True
        except Exception as e:
            logging.error(f"Failed to acquire serial port {self.port}: {e}")
            # Restart gpsd since we failed
            # Capture output to prevent it from interfering with API response
            subprocess.run(['sudo', 'systemctl', 'start', 'gpsd.socket', 'gpsd.service'], capture_output=True, text=True) # Modified
            return False

    def _release_serial_connection(self):
        """Closes the on-demand serial connection and restarts gpsd."""
        if self.ser and self.ser.is_open:
            self.ser.close()
        self.ser = None
        # Always restart gpsd to return control
        # Capture output to prevent it from interfering with API response
        subprocess.run(['sudo', 'systemctl', 'start', 'gpsd.socket', 'gpsd.service'], capture_output=True, text=True) # Modified


    def send_at_command(self, command, expected_response, timeout=2):
        """
        Sends an AT command to the module and waits for an expected response.
        Manages acquiring and releasing the serial port around the command.
        """
        if not self._get_serial_connection():
            return f"Error: Could not acquire serial port '{self.port}'. It may be in use by gpsd."

        try:
            logging.debug(f"AT=> {command}")
            self.ser.reset_input_buffer()
            self.ser.write((command + '\r\n').encode())
            
            lines = []
            start_time = time.time()
            while time.time() - start_time < timeout:
                try:
                    line = self.ser.readline().decode('utf-8', errors='ignore').strip()
                    if line:
                        logging.debug(f"AT<= {line}")
                        lines.append(line)
                        if expected_response in line:
                            return line
                        if 'ERROR' in line:
                            logging.error(f"AT command '{command}' returned an error.")
                            return None
                except serial.SerialException as e:
                    logging.error(f"Serial error while reading from port {self.port}: {e}")
                    return None

            logging.warning(f"Timeout ({timeout}s) waiting for '{expected_response}' after sending '{command}'.")
            return None
        finally:
            # CRITICAL: Always release the port and restart gpsd
            self._release_serial_connection()

    def close(self):
        """Ensures the serial connection is closed if open."""
        # The new design manages the connection per-command, so this is mostly a no-op.
        pass

    def __del__(self):
        """Destructor to ensure the serial port is closed."""
        self.close()