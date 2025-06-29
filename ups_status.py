#!/usr/bin/python
# -*- coding:utf-8 -*-

#================================================================
# Waveshare UPS Power HAT Status Script (with Funny Sayings)
#================================================================

import smbus
import time
import os
import random

# --- Configuration ---
BATTERY_CAPACITY_MAH = 7000
# Any charging current below this value is considered a "trickle charge".
CURRENT_TRICKLE_MA = 10.0 

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

# --- Funny Sayings for Trickle Charging (Edgy Edition) ---
TRICKLE_CHARGE_SAYINGS = [
    "Great Job!",
    "Let me in... LET ME INNNNN!",
    "De-yellowing the case...",
    "Topping up the 1-hungeos.",
    "Oh, my PKCELL.",
    "It's free real estate.",
    "Checking for leaky capacitors.",
    "Bird up!",
    "My name is...",
    "The dawn is your enemy.",
    "Lookin' for a new nugget.",
    "Time to deliver a pizza ball.",
    "Waka waka, my ol' mate.",
    "Ranch me, mulatto.",
    "Recapping the main board.",
    "Shake zula, the mic rula.",
    "Puttin' on the foil.",
    "This is a real man's watch.",
    "The proprietary blend.",
    "My other computer is a Dell.",
    "I am the globglogabgalab.",
    "Spaghetti and meatballs!",
    "Investigate 311.",
    "This is the worst show on television.",
    "Ya blew it.",
    "Who killed Hannibal?",
    "Praise be to the blessed frank.",
    "Legalize ranch.",
    "The ol' mate's gettin' spicy.",
    "IGNORE ME!"
]

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
        self.bus.write_i2c_block_data(self.addr, REG_CONFIG, [0x01, 0x9F])
        self.bus.write_i2c_block_data(self.addr, REG_CALIBRATION, [0x10, 0x00])

    def read_voltage(self):
        read = self.bus.read_i2c_block_data(self.addr, REG_BUSVOLTAGE, 2)
        p_v = (read[0] * 256 + read[1])
        return (p_v >> 3) * 0.004

    def read_shunt_voltage(self):
        read = self.bus.read_i2c_block_data(self.addr, REG_SHUNTVOLTAGE, 2)
        p_v = (read[0] * 256 + read[1]) if read[0] <= 127 else -((256 - read[0]) * 256 + (255 - read[1]) + 1)
        return p_v * 0.01
        
    def read_current(self):
        current_raw = self.bus.read_i2c_block_data(self.addr, REG_CURRENT, 2)
        current_val = (current_raw[0] << 8) | current_raw[1]
        if current_val > 32767: current_val -= 65536
        return current_val * 0.05

    def read_power(self):
        power_raw = self.bus.read_i2c_block_data(self.addr, REG_POWER, 2)
        return ((power_raw[0] << 8) | power_raw[1]) * 1.0

def get_battery_percentage(voltage):
    min_volt, max_volt = 6.0, 8.4
    percentage = ((max(min(voltage, max_volt), min_volt) - min_volt) / (max_volt - min_volt)) * 100
    return min(100.0, max(0.0, percentage))

def get_dynamic_color(value, thresholds, reverse=False):
    op = (lambda a, b: a <= b) if reverse else (lambda a, b: a >= b)
    if op(value, thresholds['high']): return Colors.C_GREEN
    if op(value, thresholds['medium']): return Colors.C_YELLOW
    return Colors.C_RED

def create_battery_bar(percentage, color):
    bar_width = 20
    filled_length = int(bar_width * percentage / 100)
    bar = '█' * filled_length + '─' * (bar_width - filled_length)
    return f"{color}[{bar}]{Colors.C_OFF}"

def format_time_human_readable(hours):
    if hours > 8760: return "> 1 year"
    total_seconds = int(hours * 3600)
    days, rem = divmod(total_seconds, 86400)
    hours, rem = divmod(rem, 3600)
    minutes, _ = divmod(rem, 60)
    parts = [f"{d} day{'s' if d != 1 else ''}" for d in [days] if d > 0]
    parts += [f"{h} hour{'s' if h != 1 else ''}" for h in [hours] if h > 0]
    parts += [f"{m} min{'s' if m != 1 else ''}" for m in [minutes] if m > 0]
    return ", ".join(parts) if parts else "< 1 minute"

# --- MODIFIED FUNCTION ---
def get_time_estimation(percentage, current_ma):
    """
    Calculates time remaining or until full. During trickle charge,
    returns a random funny saying instead.
    """
    if abs(current_ma) < 1.0: # Truly idle
        return "", "---"

    if current_ma > 0: # Charging
        if percentage >= 99.5: return "", "---"
        
        # This is the new logic for trickle charging
        if current_ma <= CURRENT_TRICKLE_MA:
            return "", random.choice(TRICKLE_CHARGE_SAYINGS)

        label = "Full in:"
        capacity_needed = BATTERY_CAPACITY_MAH * (100 - percentage) / 100
        time_hours = capacity_needed / current_ma
        return label, f"~ {format_time_human_readable(time_hours)}"
    else: # Discharging
        label = "Empty in:"
        capacity_remaining = BATTERY_CAPACITY_MAH * percentage / 100
        time_hours = capacity_remaining / abs(current_ma)
        return label, f"~ {format_time_human_readable(time_hours)}"


def main():
    os.system('clear')

    if not os.path.exists(I2C_BUS_DEVICE):
        print(f"{Colors.C_BOLD}{Colors.C_RED}Error: I2C interface is not enabled!{Colors.C_OFF}")
        return

    try:
        ina219 = INA219()
        bus_voltage = ina219.read_voltage()
        shunt_voltage = ina219.read_shunt_voltage()
        current_ma = ina219.read_current()
        power_mw = ina219.read_power()
        battery_voltage = bus_voltage + (shunt_voltage / 1000)
        percentage = get_battery_percentage(battery_voltage)

        volt_color = get_dynamic_color(battery_voltage, {'high': 7.8, 'medium': 6.8})
        percent_color = get_dynamic_color(percentage, {'high': 60, 'medium': 25})
        
        header = f"{Colors.C_BOLD}{Colors.C_PURPLE}   UPS Power HAT Status   {Colors.C_OFF}"
        separator = f"{Colors.C_PURPLE}{'=' * 40}{Colors.C_OFF}"
        
        print(f"{separator}\n{header}\n{separator}")
        
        label_width = 20
        print(f"  {Colors.C_CYAN}{'Load Voltage:'.ljust(label_width)}{Colors.C_OFF} {volt_color}{bus_voltage: >7.2f} V{Colors.C_OFF}")
        print(f"  {Colors.C_CYAN}{'Battery Voltage:'.ljust(label_width)}{Colors.C_OFF} {volt_color}{battery_voltage: >7.2f} V{Colors.C_OFF}")
        print(f"  {Colors.C_CYAN}{'Shunt Voltage:'.ljust(label_width)}{Colors.C_OFF} {shunt_voltage: >7.2f} mV")
        print(f"  {Colors.C_CYAN}{'Current:'.ljust(label_width)}{Colors.C_OFF} {current_ma: >7.2f} mA")
        print(f"  {Colors.C_CYAN}{'Power:'.ljust(label_width)}{Colors.C_OFF} {power_mw: >7.2f} mW")
        print(f"  {Colors.C_CYAN}{'Configured Capacity:'.ljust(label_width)}{Colors.C_OFF} {Colors.C_WHITE}{BATTERY_CAPACITY_MAH} mAh (2x {BATTERY_CAPACITY_MAH//2}mAh){Colors.C_OFF}")
        
        print(separator)
        
        battery_bar = create_battery_bar(percentage, percent_color)
        print(f"  {battery_bar} {percent_color}{percentage:.1f}%{Colors.C_OFF}")
        
        time_label, time_str = get_time_estimation(percentage, current_ma)
        if time_label:
             print(f"  {Colors.C_CYAN}{time_label}{Colors.C_OFF} {Colors.C_WHITE}{time_str}{Colors.C_OFF}")
        else:
             print(f"  {Colors.C_YELLOW}{time_str}{Colors.C_OFF}")

        print(separator)
        
        if current_ma > 5:
            if percentage >= 99.5: print(f"{Colors.C_BOLD}{Colors.C_GREEN}Status: Battery is CHARGED.{Colors.C_OFF}")
            else: print(f"{Colors.C_BOLD}{Colors.C_GREEN}Status: Battery is CHARGING.{Colors.C_OFF}")
        elif current_ma < -5: print(f"{Colors.C_BOLD}{Colors.C_YELLOW}Status: Battery is DISCHARGING.{Colors.C_OFF}")
        else: print(f"{Colors.C_BOLD}{Colors.C_CYAN}Status: Standby / Trickle Charging.{Colors.C_OFF}")

    except Exception as e:
        print(f"\n{Colors.C_BOLD}{Colors.C_RED}Error: Could not read from the INA219 device.{Colors.C_OFF}\nDetails: {e}")

if __name__ == "__main__":
    main()
