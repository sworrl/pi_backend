#!/usr/bin/python
# -*- coding:utf-8 -*-

#================================================================
# Simple Waveshare UPS Power HAT Status Script
#
# Description:
#   This script clears the screen, checks if I2C is enabled, then
#   reads the voltage, current, power, and battery percentage from
#   a Waveshare UPS Power HAT and prints it in a dynamic,
#   colorized format with a battery bar and detailed time estimation.
#
# Requirements:
#   - python3
#   - python3-smbus (install with: sudo apt-get install python3-smbus)
#   - I2C interface enabled on your Raspberry Pi
#
# How to run:
#   1. Save this file as `ups_status.py`
#   2. Run from the terminal: `python3 ups_status.py`
#================================================================

import smbus
import time
import os

# --- Configuration ---
# This is an estimate for two 3500mAh 18650 batteries.
# Change this value to match the total capacity of your batteries.
BATTERY_CAPACITY_MAH = 7000

# --- Color Definitions ---
class Colors:
    C_OFF = '\033[0m'
    C_RED = '\033[0;31m'
    C_GREEN = '\033[0;32m'
    C_YELLOW = '\033[0;33m'
    C_PURPLE = '\033[0;35m'
    C_CYAN = '\033[0;36m'
    C_WHITE = '\033[0;37m'
    C_BOLD = '\033[1m'

# I2C bus and device address
I2C_BUS_DEVICE = "/dev/i2c-1"
INA219_ADDRESS = 0x42

# INA219 Register Addresses
REG_CONFIG = 0x00
REG_SHUNTVOLTAGE = 0x01
REG_BUSVOLTAGE = 0x02
REG_POWER = 0x03
REG_CURRENT = 0x04
REG_CALIBRATION = 0x05

class INA219:
    def __init__(self, address=INA219_ADDRESS, busnum=1):
        self.bus = smbus.SMBus(busnum)
        self.addr = address
        
        # Default configuration values
        self.bus.write_i2c_block_data(self.addr, REG_CONFIG, [0x01, 0x9F])
        
        # Calibrate for a 0.1-ohm shunt resistor and 2A max current
        self.bus.write_i2c_block_data(self.addr, REG_CALIBRATION, [0x10, 0x00])

    def read_voltage(self):
        read = self.bus.read_i2c_block_data(self.addr, REG_BUSVOLTAGE, 2)
        p_v = (read[0] * 256 + read[1])
        return (p_v >> 3) * 0.004

    def read_shunt_voltage(self):
        read = self.bus.read_i2c_block_data(self.addr, REG_SHUNTVOLTAGE, 2)
        if read[0] > 127:
            read[0] = 256 - read[0]
            read[1] = 255 - read[1]
            p_v = (read[0] * 256 + read[1] + 1) * -1
        else:
            p_v = (read[0] * 256 + read[1])
        return p_v * 0.01
        
    def read_current(self):
        current_raw = self.bus.read_i2c_block_data(self.addr, REG_CURRENT, 2)
        current_val = (current_raw[0] << 8) | current_raw[1]
        if current_val > 32767:
            current_val -= 65536
        return current_val * 0.05

    def read_power(self):
        power_raw = self.bus.read_i2c_block_data(self.addr, REG_POWER, 2)
        power_val = (power_raw[0] << 8) | power_raw[1]
        return power_val * 1.0

def get_battery_percentage(voltage):
    min_volt, max_volt = 6.0, 8.4
    voltage = max(min(voltage, max_volt), min_volt)
    percentage = ((voltage - min_volt) / (max_volt - min_volt)) * 100
    return min(100.0, max(0.0, percentage))

def get_dynamic_color(value, thresholds, reverse=False):
    """Returns a color based on the value and thresholds. Reverse for discharging current."""
    if reverse:
        if value <= thresholds['high']: return Colors.C_GREEN
        if value <= thresholds['medium']: return Colors.C_YELLOW
        return Colors.C_RED
    else:
        if value >= thresholds['high']: return Colors.C_GREEN
        if value >= thresholds['medium']: return Colors.C_YELLOW
        return Colors.C_RED

def create_battery_bar(percentage, color):
    bar_width = 20
    filled_length = int(bar_width * percentage / 100)
    bar = '█' * filled_length + '─' * (bar_width - filled_length)
    return f"{color}[{bar}]{Colors.C_OFF}"

def format_time_human_readable(hours):
    """Formats a decimal number of hours into a human-readable string."""
    if hours > 87600: # > 10 years
        return "> 10 years"
    
    total_seconds = int(hours * 3600)
    
    days, remainder = divmod(total_seconds, 86400)
    hours, remainder = divmod(remainder, 3600)
    minutes, _ = divmod(remainder, 60)
    
    parts = []
    if days > 0:
        parts.append(f"{days} day{'s' if days != 1 else ''}")
    if hours > 0:
        parts.append(f"{hours} hour{'s' if hours != 1 else ''}")
    if minutes > 0:
        parts.append(f"{minutes} min{'s' if minutes != 1 else ''}")
        
    return ", ".join(parts) if parts else "a moment"


def get_time_estimation(percentage, current_ma):
    if abs(current_ma) < 10: # Avoid division by zero and nonsensical estimates
        return "Calculating...", ""

    if current_ma > 0: # Charging
        label = "Full in:"
        capacity_needed = BATTERY_CAPACITY_MAH * (100 - percentage) / 100
        time_hours = capacity_needed / current_ma
    else: # Discharging
        label = "Empty in:"
        capacity_remaining = BATTERY_CAPACITY_MAH * percentage / 100
        time_hours = capacity_remaining / abs(current_ma)
    
    return label, format_time_human_readable(time_hours)


def main():
    os.system('clear')

    if not os.path.exists(I2C_BUS_DEVICE):
        print(f"{Colors.C_BOLD}{Colors.C_RED}Error: I2C interface is not enabled!{Colors.C_OFF}")
        print(f"{Colors.C_YELLOW}Please enable it by running '{Colors.C_WHITE}sudo raspi-config{Colors.C_YELLOW}'")
        print(f"and navigating to '{Colors.C_WHITE}Interface Options -> I2C -> Yes{Colors.C_YELLOW}'.")
        print("Then reboot your Raspberry Pi.")
        return

    try:
        ina219 = INA219()

        bus_voltage = ina219.read_voltage()
        shunt_voltage = ina219.read_shunt_voltage()
        current_ma = ina219.read_current()
        power_mw = ina219.read_power()
        battery_voltage = bus_voltage + (shunt_voltage / 1000)
        percentage = get_battery_percentage(battery_voltage)

        # Dynamic color definitions
        volt_color = get_dynamic_color(battery_voltage, {'high': 7.8, 'medium': 6.8})
        shunt_color = get_dynamic_color(abs(shunt_voltage), {'high': 10, 'medium': 50}, reverse=True)
        current_color = get_dynamic_color(abs(current_ma), {'high': 50, 'medium': 250}, reverse=True) # lower is better
        power_color = get_dynamic_color(abs(power_mw), {'high': 400, 'medium': 2000}, reverse=True) # lower is better
        percent_color = get_dynamic_color(percentage, {'high': 60, 'medium': 25})
        
        # --- Print the results ---
        header = f"{Colors.C_BOLD}{Colors.C_PURPLE}   UPS Power HAT Status   {Colors.C_OFF}"
        separator = f"{Colors.C_PURPLE}{'=' * 40}{Colors.C_OFF}"
        
        print(separator)
        print(header)
        print(separator)
        
        # Use f-string alignment for clean columns
        label_width = 20
        print(f"  {Colors.C_CYAN}{'Load Voltage:'.ljust(label_width)}{Colors.C_OFF} {volt_color}{bus_voltage: >7.2f} V{Colors.C_OFF}")
        print(f"  {Colors.C_CYAN}{'Battery Voltage:'.ljust(label_width)}{Colors.C_OFF} {volt_color}{battery_voltage: >7.2f} V{Colors.C_OFF}")
        print(f"  {Colors.C_CYAN}{'Shunt Voltage:'.ljust(label_width)}{Colors.C_OFF} {shunt_color}{shunt_voltage: >7.2f} mV{Colors.C_OFF}")
        print(f"  {Colors.C_CYAN}{'Current:'.ljust(label_width)}{Colors.C_OFF} {current_color}{current_ma: >7.2f} mA{Colors.C_OFF}")
        print(f"  {Colors.C_CYAN}{'Power:'.ljust(label_width)}{Colors.C_OFF} {power_color}{power_mw: >7.2f} mW{Colors.C_OFF}")
        print(f"  {Colors.C_CYAN}{'Configured Capacity:'.ljust(label_width)}{Colors.C_OFF} {Colors.C_WHITE}{BATTERY_CAPACITY_MAH} mAh (2x {BATTERY_CAPACITY_MAH//2}mAh){Colors.C_OFF}")
        
        print(separator)
        
        battery_bar = create_battery_bar(percentage, percent_color)
        print(f"  {battery_bar} {percent_color}{percentage:.1f}%{Colors.C_OFF}")
        
        time_label, time_str = get_time_estimation(percentage, current_ma)
        print(f"  {Colors.C_CYAN}{time_label}{Colors.C_OFF} {Colors.C_WHITE}{time_str}{Colors.C_OFF}")

        print(separator)
        
        if current_ma > 5:
            print(f"{Colors.C_BOLD}{Colors.C_GREEN}Status: Battery is CHARGING.{Colors.C_OFF}")
        elif current_ma < -5:
            print(f"{Colors.C_BOLD}{Colors.C_YELLOW}Status: Battery is DISCHARGING.{Colors.C_OFF}")
        else:
            print(f"{Colors.C_BOLD}{Colors.C_CYAN}Status: Fully Charged or Standby.{Colors.C_OFF}")


    except Exception as e:
        print(f"\n{Colors.C_BOLD}{Colors.C_RED}Error: Could not read from the INA219 device.{Colors.C_OFF}")
        print("Please ensure the following:")
        print("  1. The UPS Power HAT is properly connected.")
        print("  2. The 'python3-smbus' package is installed (`sudo apt-get install python3-smbus`).")
        print(f"Details: {e}")

if __name__ == "__main__":
    main()

