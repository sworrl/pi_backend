#
# File: A7670E.py
# Version: 2.1.0 (Corrected Default Port)
#
# Description: A class to interact with the A7670E cellular module.
#              This version corrects the default serial port to /dev/serial0
#              to match common Raspberry Pi configurations. It is streamlined
#              to focus on cellular AT commands.
#
import serial
import time
import logging

class A7670E:
    """
    A class to interact with the A7670E cellular module.
    Handles sending AT commands and parsing responses.
    """
    def __init__(self, port='/dev/serial0', baudrate=115200, timeout=1):
        """
        Initializes the serial connection to the module.
        
        Args:
            port (str): The serial port device path. Defaults to '/dev/serial0',
                        which is the standard symbolic link for the GPIO UART
                        on a Raspberry Pi.
            baudrate (int): The communication speed.
            timeout (int): The read timeout in seconds.
        """
        self.port = port
        self.baudrate = baudrate
        self.timeout = timeout
        self.ser = None
        try:
            self.ser = serial.Serial(self.port, self.baudrate, timeout=self.timeout)
            logging.info(f"Successfully connected to serial port {self.port} at {self.baudrate} baud.")
        except serial.SerialException as e:
            logging.error(f"Failed to open serial port {self.port}: {e}")
            logging.error("Please ensure the user running this script (e.g., 'www-data') is part of the 'dialout' group.")
            raise

    def send_at_command(self, command, expected_response, timeout=2):
        """
        Sends an AT command to the module and waits for an expected response.

        Args:
            command (str): The AT command to send.
            expected_response (str): The string expected in the response.
            timeout (int): Time to wait for a response.

        Returns:
            str or None: The full response line containing the expected text, otherwise None.
        """
        if not self.ser or not self.ser.is_open:
            logging.error("Serial port is not open. Cannot send AT command.")
            return None
        
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
                        return line # Return the line that contains the expected response
                    if 'ERROR' in line:
                        logging.error(f"AT command '{command}' returned an error.")
                        return None
            except serial.SerialException as e:
                logging.error(f"Serial error while reading from port {self.port}: {e}")
                return None

        logging.warning(f"Timeout ({timeout}s) waiting for '{expected_response}' after sending '{command}'.")
        logging.debug(f"Full response received during timeout: {lines}")
        return None

    # --- GNSS functions have been removed from this module. ---
    # The `a7670e-gps-init.service` and the `HardwareManager`'s
    # real-time `cgps` stream now handle all GNSS functionality. This
    # keeps the A7670E driver focused on cellular tasks.

    def close(self):
        """Closes the serial connection if it is open."""
        if self.ser and self.ser.is_open:
            self.ser.close()
            logging.info(f"Serial port {self.port} closed.")

    def __del__(self):
        """Destructor to ensure the serial port is closed."""
        self.close()
