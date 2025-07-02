#================================================================
# Smart UPS Monitor for Waveshare UPS Power HAT
# Version: 1.1.0 (Logs to Main DB)
#
# Description:
#   This single script automatically detects your environment.
#   - In a GUI session, it launches a movable widget with selectable
#     themes and operating modes via a right-click menu. The graph is
#     now integrated into the main window.
#   - In a text-only terminal, it prints a one-time status report,
#     or runs continuously with an interactive menu using the -c flag.
#
#   This version has been modified to log its data directly to the
#   main pi_backend SQLite database (pi_backend.db) instead of its
#   own separate database.
#
# How to run:
#   1. Save this file as `smart_monitor.py`.
#   2. Install all required libraries (no pip needed):
#      sudo apt-get update && sudo apt-get install python3-smbus python3-tk python3-matplotlib python3-pil python3-pil.imagetk
#   3. Ensure I2C is enabled on your Pi (using 'sudo raspi-config').
#   4. Ensure the main pi_backend database is initialized.
#   5. Run the script:
#      - For GUI: `python3 smart_monitor.py`
#      - For one-shot TUI: `python3 smart_monitor.py`
#      - For continuous TUI: `python3 smart_monitor.py -c`
#      - To create a desktop shortcut: `python3 smart_monitor.py --install-shortcut`
#================================================================

import time
import os
import sys
import threading
import tkinter as tk
from tkinter import font as tkFont
from tkinter import ttk
import random
import math
import signal
import tty
import termios
# Removed sqlite3 import as we now use the main DatabaseManager
from datetime import datetime, timedelta
from matplotlib.figure import Figure
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from PIL import Image, ImageDraw, ImageTk

# Import the main DatabaseManager from pi_backend
# Adjust this path if ups_status.py is not in the same directory as database.py
script_dir = os.path.dirname(os.path.abspath(__file__))
# Assuming pi_backend/ups_status.py is in pi_backend/modules/ups_status.py
# and database.py is in pi_backend/database.py, we need to go up two levels
# and then down into pi_backend to find database.py
sys.path.insert(0, os.path.abspath(os.path.join(script_dir, '..', '..'))) 
from pi_backend.database import DatabaseManager

# Attempt to import smbus, with error handling for common issues
try:
    import smbus
except ImportError:
    print("Error: 'smbus' module not found. Please install it using:")
    print("  sudo apt-get install python3-smbus")
    sys.exit(1)
except Exception as e:
    print(f"An unexpected error occurred while importing 'smbus': {e}")
    sys.exit(1)


#================================================================
# --- USER CONFIGURATION ---
#================================================================
class Config:
    BATTERY_CAPACITY_MAH = 7000
    CURRENT_TRICKLE_MA = 10.0
    VOLTAGE_PACK_MIN = 6.4
    VOLTAGE_PACK_MAX = 8.0 # Changed: Anything 8.0V and above is now considered 100%
    VOLTAGE_CELL_MIN = 3.2
    VOLTAGE_CELL_MAX = 4.1

#================================================================
# --- THEMES ---
#================================================================
THEMES = {
    "Dank Slate":      { "bg": "#2d3748", "fg": "#e2e8f0", "sec": "#a0aec0", "acc": "#4fd1c5", "grn": "#48bb78", "yel": "#f6e05e", "red": "#f56565", "font_main": "Helvetica", "font_style": "bold", "pur": "#a78bfa" },
    "Light Mode":      { "bg": "#f7fafc", "fg": "#2d3748", "sec": "#718096", "acc": "#319795", "grn": "#48bb78", "yel": "#d69e2e", "red": "#e53e3e", "font_main": "Helvetica", "font_style": "normal", "pur": "#7c3aed" },
    "Ocean Blue":      { "bg": "#2b6cb0", "fg": "#f7fafc", "sec": "#a0aec0", "acc": "#63b3ed", "grn": "#48bb78", "yel": "#f6e05e", "red": "#f56565", "font_main": "Helvetica", "font_style": "bold", "pur": "#bf616a" },
    "Terminal Green": { "bg": "#000000", "fg": "#00ff00", "sec": "#00bb00", "acc": "#00ff00", "grn": "#00ff00", "yel": "#00ff00", "red": "#ff0000", "font_main": "monospace", "font_style": "normal", "pur": "#ff00ff" },
    "Oh My PKCell":    { "bg": "#1a1a1a", "fg": "#ffffff", "sec": "#b3b3b3", "acc": "#ff0000", "grn": "#00ff00", "yel": "#ffff00", "red": "#ff0000", "font_main": "Helvetica", "font_style": "bold", "pur": "#800080" },
    "One Hungeo":      { "bg": "#c0c0c0", "fg": "#000000", "sec": "#4d4d4d", "acc": "#ff0000", "grn": "#000000", "yel": "#000000", "red": "#ff0000", "font_main": "Impact", "font_style": "normal", "pur": "#800080" },
    "Frank's Hot Dogs":{ "bg": "#ffcc00", "fg": "#ff0000", "sec": "#cc0000", "acc": "#0000ff", "grn": "#009900", "yel": "#ff9900", "red": "#ff0000", "font_main": "Comic Sans MS", "font_style": "bold", "pur": "#800080" },
    "LGR Woodgrain":   { "bg": "#8b4513", "fg": "#ffffff", "sec": "#deb887", "acc": "#ffa500", "grn": "#9acd32", "yel": "#ffd700", "red": "#cd5c5c", "font_main": "Times", "font_style": "bold", "pur": "#800080" },
    "LGR Thing":       { "bg": "#00008b", "fg": "#ffffff", "sec": "#add8e6", "acc": "#ff00ff", "grn": "#00ff00", "yel": "#ffff00", "red": "#ff0000", "font_main": "Helvetica", "font_style": "italic", "pur": "#800080" },
    "Straight Line":   { "bg": "#228b22", "fg": "#ffffff", "sec": "#ffffff", "acc": "#ff0000", "grn": "#ffffff", "yel": "#ffffff", "red": "#ff0000", "font_main": "Arial", "font_style": "bold", "pur": "#800080" },
    "Tom's Puffer":    { "bg": "#0000ff", "fg": "#ffffff", "sec": "#ffa500", "acc": "#ffa500", "grn": "#ffffff", "yel": "#ffa500", "red": "#ff0000", "font_main": "Helvetica", "font_style": "bold", "pur": "#800080" },
    "CRT Glow":        { "bg": "#1a1a1a", "fg": "#00ff00", "sec": "#00cc00", "acc": "#00ff00", "grn": "#00ff00", "yel": "#00ff00", "red": "#ff0000", "font_main": "monospace", "font_style": "normal", "pur": "#ff00ff" },
    "90s Beige":       { "bg": "#f5f5dc", "fg": "#000000", "sec": "#808080", "acc": "#000080", "grn": "#008000", "yel": "#808000", "red": "#800000", "font_main": "Sans", "font_style": "normal", "pur": "#800080" },
    "The Dingus":      { "bg": "#c0c0c0", "fg": "#000000", "sec": "#808080", "acc": "#ff0000", "grn": "#00ff00", "yel": "#ffff00", "red": "#ff0000", "font_main": "Comic Sans MS", "font_style": "bold", "pur": "#800080" },
    "Mmm, Film":       { "bg": "#f5deb3", "fg": "#8b4513", "sec": "#a0522d", "acc": "#d2691e", "grn": "#228b22", "yel": "#b8860b", "red": "#a52a2a", "font_main": "Serif", "font_style": "normal", "pur": "#800080" },
    "Synthwave":       { "bg": "#2e004d", "fg": "#ff00ff", "sec": "#00ffff", "acc": "#00ffff", "grn": "#00ff00", "yel": "#ffff00", "red": "#ff0000", "font_main": "Courier", "font_style": "bold", "pur": "#bd93f9" },
    "Dracula":         { "bg": "#282a36", "fg": "#f8f8f2", "sec": "#6272a4", "acc": "#bd93f9", "grn": "#50fa7b", "yel": "#f1fa8c", "red": "#ff5555", "font_main": "monospace", "font_style": "normal", "pur": "#ff00ff" },
    "Solarized Dark":  { "bg": "#002b36", "fg": "#839496", "sec": "#586e75", "acc": "#268bd2", "grn": "#859900", "yel": "#b58900", "red": "#dc322f", "font_main": "Helvetica", "font_style": "normal", "pur": "#6c71c4" },
    "Nord":            { "bg": "#2e3440", "fg": "#d8dee9", "sec": "#4c566a", "acc": "#88c0d0", "grn": "#a3be8c", "yel": "#ebcb8b", "red": "#bf616a", "font_main": "Helvetica", "font_style": "normal", "pur": "#b48ead" },
    "Monokai":         { "bg": "#272822", "fg": "#f8f8f2", "sec": "#75715e", "acc": "#66d9ef", "grn": "#a6e22e", "yel": "#e6db74", "red": "#f92672", "font_main": "monospace", "font_style": "normal", "pur": "#ae81ff" },
}

# --- Text-UI Colors ---
class TuiColors:
    C_OFF, C_RED, C_GREEN, C_YELLOW, C_PURPLE, C_CYAN, C_WHITE, C_BOLD = ('\033[0m', '\033[0;31m', '\033[0;32m', '\033[0;33m', '\033[0;35m', '\033[0;36m', '\033[0;37m', '\033[1m')

# --- Shared Lists ---
TRICKLE_CHARGE_SAYINGS = [
    "Great Job!", "Let me in... LET ME INNNNN!", "De-yellowing the case...",
    "Topping up the 1-hungeos.", "Oh, my PKCELL.", "It's free real estate.",
    "Checking for leaky capacitors.", "Bird up!", "My name is...",
    "The dawn is your enemy.", "Lookin' for a new nugget.", "Time to deliver a pizza ball.",
    "Waka waka, my ol' mate.", "Ranch me, mulatto.", "Recapping the main board.",
    "Shake zula, the mic rula.", "Puttin' on the foil.", "This is a real man's watch.",
    "The proprietary blend.", "My other computer is a Dell.", "I am the globglogabgalab.",
    "Spaghetti and meatballs!", "Investigate 311.", "This is the worst show on television.",
    "Ya blew it.", "Who killed Hannibal?", "Praise be to the blessed frank.",
    "Legalize ranch.", "The ol' mate's gettin' spicy.", "IGNORE ME!"
]

# I2C setup
I2C_BUS_DEVICE = "/dev/i2c-1"
INA219_ADDRESS = 0x42
REG_CONFIG, REG_SHUNTVOLTAGE, REG_BUSVOLTAGE, REG_POWER, REG_CURRENT, REG_CALIBRATION = 0x00, 0x01, 0x02, 0x03, 0x04, 0x05

# --- Shared Core Logic ---
class INA219:
    RST, BRNG_16V, PG_40MV, ADC_12BIT_1S = 0x8000, 0x0000, 0x0000, 0x0180
    POWER_DOWN, SVOLT_TRIGGERED, SVOLT_BVOLT_CONTINUOUS = 0x0000, 0x0001, 0x0007
    
    def __init__(self, address=INA219_ADDRESS, busnum=1):
        self.bus = smbus.SMBus(busnum)
        self.addr = address
        
        self.set_configuration()

    def set_configuration(self, mode=SVOLT_BVOLT_CONTINUOUS, adc_res=ADC_12BIT_1S):
        config = self.BRNG_16V | self.PG_40MV | adc_res | mode
        config_bytes = [(config >> 8) & 0xFF, config & 0xFF]
        try:
            self.bus.write_i2c_block_data(self.addr, REG_CONFIG, config_bytes)
            self.bus.write_i2c_block_data(self.addr, REG_CALIBRATION, [0x10, 0x00])
        except IOError as e:
            raise IOError(f"I2C Communication Error during configuration: {e}. Please check: 1. UPS HAT connections. 2. I2C is enabled (sudo raspi-config). 3. Correct I2C address (0x42).")
        except Exception as e:
            raise Exception(f"An unexpected error occurred during INA219 configuration: {e}")

    def power_down(self):
        try:
            self.set_configuration(mode=self.POWER_DOWN)
        except Exception as e:
            print(f"Failed to power down INA219 sensor: {e}") 

    def get_bus_voltage(self):
        try:
            read = self.bus.read_i2c_block_data(self.addr, REG_BUSVOLTAGE, 2)
            p_v = (read[0] << 8) | read[1]
            return (p_v >> 3) * 0.004
        except Exception as e:
            raise IOError(f"Failed to read bus voltage from INA219: {e}")

    def get_shunt_voltage(self):
        try:
            read = self.bus.read_i2c_block_data(self.addr, REG_SHUNTVOLTAGE, 2)
            val = (read[0] << 8) | read[1]
            if val > 32767: val -= 65536
            return val * 0.01
        except Exception as e:
            raise IOError(f"Failed to read shunt voltage from INA219: {e}")

    def get_current(self):
        try:
            val = self.bus.read_i2c_block_data(self.addr, REG_CURRENT, 2)
            current_val = (val[0] << 8) | val[1]
            if current_val > 32767: current_val -= 65536
            return current_val * 0.05
        except Exception as e:
            raise IOError(f"Failed to read current from INA219: {e}")

    def get_power(self):
        try:
            val = self.bus.read_i2c_block_data(self.addr, REG_POWER, 2)
            return ((val[0] << 8) | val[1]) * 1.0
        except Exception as e:
            raise IOError(f"Failed to read power from INA219: {e}")

def get_pack_percentage(voltage):
    # Ensure the voltage is within the defined min/max range for percentage calculation
    # Clamps voltage between min and max, so anything above max or below min is treated as max/min respectively.
    voltage = max(min(voltage, Config.VOLTAGE_PACK_MAX), Config.VOLTAGE_PACK_MIN)
    return ((voltage - Config.VOLTAGE_PACK_MIN) / (Config.VOLTAGE_PACK_MAX - Config.VOLTAGE_PACK_MIN)) * 100

# Helper function to convert percentage back to voltage scale
def convert_percent_to_voltage_scale(percentage):
    """Maps a 0-100% value to the voltage scale defined by VOLTAGE_PACK_MIN/MAX."""
    voltage_range = Config.VOLTAGE_PACK_MAX - Config.VOLTAGE_PACK_MIN
    return Config.VOLTAGE_PACK_MIN + (percentage / 100.0) * voltage_range


def get_cell_percentage(voltage):
    voltage = max(min(voltage, Config.VOLTAGE_CELL_MAX), Config.VOLTAGE_CELL_MIN)
    return ((voltage - Config.VOLTAGE_CELL_MIN) / (Config.VOLTAGE_CELL_MAX - Config.VOLTAGE_CELL_MIN)) * 100

def logarithmic_scale(linear_percent):
    if linear_percent <= 0: return 0.0
    return 100 * (math.log(linear_percent + 1) / math.log(101))

def parabolic_scale(linear_percent):
    if linear_percent <= 0: return 0.0
    return (linear_percent / 100.0) ** 2 * 100.0

def format_time_human_readable(hours):
    if not isinstance(hours, (int, float)) or hours == float('inf') or hours > 8760:
        return "> 1 year"
    total_seconds, parts = int(hours * 3600), []
    days, rem = divmod(total_seconds, 86400)
    if days > 0: parts.append(f"{days} day{'s' if days != 1 else ''}")
    hours_rem, rem = divmod(rem, 3600)
    if hours_rem > 0: parts.append(f"{hours_rem} hour{'s' if hours_rem != 1 else ''}")
    minutes, _ = divmod(rem, 60)
    if minutes > 0: parts.append(f"{minutes} min{'s' if minutes != 1 else ''}")
    return ", ".join(parts) if parts else "< 1 minute"

def get_status_and_time(percentage, current_ma):
    pessimism_factor = 1.0 + ((100.0 - percentage) / 100.0) * 0.8
    if current_ma > Config.CURRENT_TRICKLE_MA:
        status, time_str, state = "⚡ Charging", "", "charging"
        if percentage < 99.5:
            capacity_needed = Config.BATTERY_CAPACITY_MAH * (100 - percentage) / 100
            time_hours = capacity_needed / current_ma if current_ma > 0 else float('inf')
            time_str = f"Full in: ~{format_time_human_readable(time_hours)}"
    elif current_ma > 5:
        status, time_str, state = "⚡ Trickle Charging", random.choice(TRICKLE_CHARGE_SAYINGS), "charging"
    else: # current_ma is between -5 and 5, or less than -5
        if current_ma < -5:
            status, state = "🔋 Discharging", "discharging"
            capacity_remaining = Config.BATTERY_CAPACITY_MAH * percentage / 100
            time_hours = (capacity_remaining / abs(current_ma)) / pessimism_factor if current_ma < 0 else float('inf')
            time_str = f"Empty in: ~{format_time_human_readable(time_hours)}"
        else: # current_ma is between -5 and 5, considered idle/standby
            status, time_str, state = "✅ Standby / Full", "", "standby"
    return status, time_str, state


def get_all_data_and_status(ina219, mode):
    if mode == INA219.SVOLT_TRIGGERED:
        ina219.set_configuration(mode=INA219.SVOLT_TRIGGERED)
        time.sleep(0.1) # Give sensor time to measure

    if mode != INA219.POWER_DOWN:
        bus_v = ina219.get_bus_voltage()
        shunt_v = ina219.get_shunt_voltage()
        current = ina219.get_current()
        power = ina219.get_power()
        
        batt_v = bus_v + (shunt_v / 1000)
        percent = get_pack_percentage(batt_v)
        status, time_str, charging_state = get_status_and_time(percent, current)
        status_text = f"{status}\n{time_str}" if time_str else status
    else:
        bus_v, shunt_v, current, power, percent, batt_v, status, charging_state = 0,0,0,0,0,0, "Sensor Powered Down", "unknown"
        status_text = status

    return {
        "percent": percent, "bus_v": bus_v, "batt_v": batt_v, "shunt_v": shunt_v,
        "current": current, "power": power, "status_text": status_text, 
        "status": status, "charging_state": charging_state
    }

# --- Database Manager (Removed - now using main DatabaseManager) ---
# class DatabaseManager: ... (This class is no longer here)


# --- GUI-Specific Code ---
class BatteryMonitorApp:
    def __init__(self, db_manager, ina219_instance):
        self.db_manager = db_manager
        self.ina219 = ina219_instance # Pass in already initialized INA219 object
        self.root = tk.Tk()
        self.root.withdraw()
        self.is_running = True
        self.current_theme_name = random.choice(list(THEMES.keys()))
        self.current_mode = INA219.SVOLT_BVOLT_CONTINUOUS
        
        self.vars = {name: tk.StringVar(value="--") for name in ["percent", "status", "load_v", "batt_v", "shunt_v", "current", "power"]}
        
        self.previous_charging_state = None
        self.update_job = None
        self.graph_update_job = None
        
        self.bidoof_icon_tk = self.load_bidoof_icon_for_gui() # Load icon for GUI
        
        self.apply_theme()
        self.root.bind('<Button-1>', self.click_win)
        self.root.bind('<B1-Motion>', self.drag_win)
        self.root.bind('<Button-3>', self.show_exit_menu)
        
    def _start_periodic_updates(self):
        """Initializes and starts the periodic update threads."""
        threading.Thread(target=self.update_status, daemon=True).start()
        threading.Thread(target=self.update_graph, daemon=True).start()

    def load_bidoof_icon_for_gui(self):
        # Create the Bidoof icon PNG if it doesn't exist
        icon_path = os.path.join(os.path.expanduser("~"), ".local/share/icons/bidoof_icon.png")
        if not os.path.exists(icon_path):
            create_bidoof_icon() # Ensures the icon file is present
        
        # Load the image using PIL and convert to PhotoImage
        try:
            pil_image = Image.open(icon_path).resize((32, 32), Image.Resampling.LANCZOS) # Resize for GUI
            return ImageTk.PhotoImage(pil_image)
        except Exception as e:
            print(f"Error loading Bidoof icon for GUI: {e}")
            return None

    def apply_theme(self):
        self.theme = THEMES[self.current_theme_name]
        self.root.config(bg=self.theme["bg"])
        self.root.overrideredirect(True)
        # Start with a larger geometry for the graph
        self.root.geometry("400x550+300+300")
        for widget in self.root.winfo_children(): widget.destroy()
        self.setup_ui()
        if hasattr(self, 'canvas'):
            self.update_graph_from_thread()

    def setup_ui(self):
        # Main container
        main_container = tk.Frame(self.root, bg=self.theme["bg"])
        main_container.pack(fill="both", expand=True, padx=1, pady=1)

        # Top frame for stats and icon
        # Increased padx for top_frame to give more horizontal space
        top_frame = tk.Frame(main_container, bg=self.theme["bg"], padx=25, pady=10) 
        top_frame.pack(fill="x", expand=False)
        
        # Bidoof icon in top_frame
        if self.bidoof_icon_tk:
            icon_label = tk.Label(top_frame, image=self.bidoof_icon_tk, bg=self.theme["bg"])
            icon_label.pack(side=tk.LEFT, anchor=tk.NW, padx=(0, 10)) # Adjust padding as needed

        # Increased font sizes for better readability
        font_main_bold = tkFont.Font(family=self.theme["font_main"], size=36, weight="bold") # Increased from 28
        font_status = tkFont.Font(family=self.theme["font_main"], size=14, weight=self.theme["font_style"]) # Increased from 11
        font_label = tkFont.Font(family=self.theme["font_main"], size=12) # Increased from 9
        font_value = tkFont.Font(family=self.theme["font_main"], size=12, weight="bold") # Increased from 9

        self.percent_label = tk.Label(top_frame, textvariable=self.vars["percent"], font=font_main_bold, bg=self.theme["bg"])
        self.percent_label.pack(pady=5)
        # Increased wraplength to utilize more horizontal space
        self.status_label = tk.Label(top_frame, textvariable=self.vars["status"], font=font_status, bg=self.theme["bg"], wraplength=370, justify='center')
        self.status_label.pack()

        stats_frame = tk.Frame(top_frame, bg=self.theme["bg"])
        stats_frame.pack(pady=10, padx=5, fill='x')
        self.stat_labels = {}
        self.create_stat_row(stats_frame, "Load Voltage:", self.vars["load_v"], 0, font_label, font_value)
        self.create_stat_row(stats_frame, "Battery Voltage:", self.vars["batt_v"], 1, font_label, font_value)
        self.create_stat_row(stats_frame, "Shunt Voltage:", self.vars["shunt_v"], 2, font_label, font_value)
        self.create_stat_row(stats_frame, "Current:", self.vars["current"], 3, font_label, font_value)
        self.create_stat_row(stats_frame, "Power:", self.vars["power"], 4, font_label, font_value)
        stats_frame.grid_columnconfigure(0, weight=1)
        stats_frame.grid_columnconfigure(1, weight=1)
        
        # Bottom frame for the graph
        graph_frame = tk.Frame(main_container, bg=self.theme['sec'])
        graph_frame.pack(fill="both", expand=True)

        self.fig = Figure(figsize=(4, 3), dpi=100, facecolor=self.theme["bg"])
        # Use subplots_adjust to give more room for right y-axis and top legend
        # Adjusted top margin to make space for the legend
        # Adjusted right margin to give more space for combined axis labels
        # Adjusted left margin to give more space for current axis labels
        self.fig.subplots_adjust(right=0.7, top=0.8, left=0.2, bottom=0.15) 
        self.ax1 = self.fig.add_subplot(111, facecolor=self.theme["bg"])
        self.canvas = FigureCanvasTkAgg(self.fig, master=graph_frame)
        self.canvas.get_tk_widget().pack(side=tk.TOP, fill=tk.BOTH, expand=True)
        self.fig.tight_layout(pad=0.5) # Decreased padding on the graph from 2.5 to 0.5

    def create_stat_row(self, parent, label_text, data_var, row, font_label, font_value):
        label = tk.Label(parent, text=label_text, font=font_label, fg=self.theme["sec"], bg=self.theme["bg"], anchor='e')
        label.grid(row=row, column=0, sticky='ew', padx=5)
        val_label = tk.Label(parent, textvariable=data_var, font=font_value, fg=self.theme["fg"], bg=self.theme["bg"], anchor='w')
        val_label.grid(row=row, column=1, sticky='w', padx=5)
        self.stat_labels[row] = val_label

    def update_ui_from_thread(self, data):
        self.vars["percent"].set(f"{data['percent']:.1f}%")
        self.vars["load_v"].set(f"{data['bus_v']:.2f} V")
        self.vars["batt_v"].set(f"{data['batt_v']:.2f} V")
        self.vars["shunt_v"].set(f"{data['shunt_v']:.2f} mV")
        self.vars["current"].set(f"{data['current']:.2f} mA")
        self.vars["power"].set(f"{data['power']:.2f} mW")
        self.vars["status"].set(data['status_text'])
        
        theme = self.theme
        volt_color = theme["grn"] if data['batt_v'] >= 8.0 else theme["yel"] if data['batt_v'] >= 7.6 else theme["red"]
        percent_color = theme["grn"] if data['percent'] >= 60 else theme["yel"] if data['percent'] >= 25 else theme["red"]
        status_color = theme["grn"] if "Charging" in data['status'] or "Full" in data['status'] else theme["yel"] if "Discharging" in data['status'] else theme["acc"]

        self.percent_label.config(fg=percent_color)
        self.status_label.config(fg=status_color)
        # Update specific stat label colors based on voltage. Note: stat_labels[0] is Load Voltage, stat_labels[1] is Battery Voltage
        self.stat_labels[0].config(fg=volt_color) 
        self.stat_labels[1].config(fg=volt_color)

    def update_graph_from_thread(self):
        self.ax1.clear()
        # Clear existing twinx axes if they exist
        if hasattr(self, 'ax2'):
            self.ax2.remove() # Remove old ax2
            del self.ax2
        if hasattr(self, 'ax_combined_right'):
            self.ax_combined_right.remove() # Remove old combined right axis
            del self.ax_combined_right

        # Fetch data from db
        # Changed to fetch from the main database's ups_metrics table
        # Fetching all data and then filtering in Python for simplicity in this example
        # For large datasets, this should be optimized with SQL queries for specific time ranges
        all_metrics = self.db_manager.execute_query("SELECT timestamp, battery_voltage_V, current_mA FROM ups_metrics ORDER BY timestamp ASC", fetch='all')
        voltage_data = [(m['timestamp'], m['battery_voltage_V']) for m in all_metrics]
        current_data = [(m['timestamp'], m['current_mA']) for m in all_metrics]

        # Fetch events from the main database's ups_events table
        events = self.db_manager.execute_query("SELECT timestamp, event_type FROM ups_events ORDER BY timestamp ASC", fetch='all')
        
        # Prepare data for plotting
        datetimes_v, values_v, values_percent_scaled_to_voltage = [], [], []
        if voltage_data:
            times_v_raw, values_v_raw = zip(*voltage_data)
            datetimes_v = [datetime.fromisoformat(ts) for ts in times_v_raw]
            values_v = list(values_v_raw) 
            # Scale percentage values to the voltage axis range
            values_percent_scaled_to_voltage = [convert_percent_to_voltage_scale(get_pack_percentage(v)) for v in values_v] 

        datetimes_c, values_c = [], []
        if current_data:
            times_c_raw, values_c_raw = zip(*current_data)
            datetimes_c = [datetime.fromisoformat(ts) for ts in times_c_raw]
            values_c = list(values_c_raw)

        # Create the left Y-axis for Current
        self.ax1.set_ylabel("Current (mA)", color=self.theme["yel"], fontsize=9)
        self.ax1.tick_params(axis='y', labelcolor=self.theme["yel"])
        p_current, = self.ax1.plot(datetimes_c, values_c, color=self.theme["yel"], linestyle='--', label='Current (mA)')
        
        # Create the right combined Y-axis for Voltage and Percentage
        self.ax_combined_right = self.ax1.twinx()
        
        # Plot Voltage on the combined right axis
        p_voltage, = self.ax_combined_right.plot(datetimes_v, values_v, color=self.theme["acc"], label='Voltage (V)')
        
        # Plot Percentage on the same combined right axis (using scaled values)
        p_percent, = self.ax_combined_right.plot(datetimes_v, values_percent_scaled_to_voltage, color=self.theme["pur"], linestyle=':', label='Percentage (%)')
        
        # Configure ticks for the combined right axis
        percent_ticks = [0, 25, 50, 75, 100]
        voltage_range = Config.VOLTAGE_PACK_MAX - Config.VOLTAGE_PACK_MIN
        voltage_at_percent = [Config.VOLTAGE_PACK_MIN + (p / 100.0) * voltage_range for p in percent_ticks]

        tick_labels_percent = [f"{p}%" for p in percent_ticks]
        tick_positions_percent = voltage_at_percent

        staggered_voltage_labels = []
        staggered_voltage_positions = []
        for i in range(len(percent_ticks) - 1):
            mid_voltage = (voltage_at_percent[i] + voltage_at_percent[i+1]) / 2
            staggered_voltage_labels.append(f"{mid_voltage:.1f}V")
            staggered_voltage_positions.append(mid_voltage)

        # Combine and sort all tick positions and labels
        all_tick_data = []
        for i in range(len(percent_ticks)):
            all_tick_data.append((tick_positions_percent[i], tick_labels_percent[i], 'percent'))
            if i < len(staggered_voltage_positions):
                all_tick_data.append((staggered_voltage_positions[i], staggered_voltage_labels[i], 'voltage'))
        
        sorted_all_tick_data = sorted(all_tick_data, key=lambda x: x[0])
        sorted_positions = [item[0] for item in sorted_all_tick_data]
        sorted_labels = [item[1] for item in sorted_all_tick_data]
        sorted_types = [item[2] for item in sorted_all_tick_data]

        self.ax_combined_right.set_yticks(sorted_positions)
        self.ax_combined_right.set_yticklabels(sorted_labels)
        
        # Set individual label colors
        for i, label_obj in enumerate(self.ax_combined_right.get_yticklabels()):
            if sorted_types[i] == 'percent':
                label_obj.set_color(self.theme["pur"])
            elif sorted_types[i] == 'voltage':
                label_obj.set_color(self.theme["acc"])


        # Set Y-axis limits for the combined right axis to span the full range
        self.ax_combined_right.set_ylim(Config.VOLTAGE_PACK_MIN, Config.VOLTAGE_PACK_MAX)


        self.ax1.set_title("Historical Data & Power Events", color=self.theme["fg"], fontsize=10)
        self.fig.autofmt_xdate()

        # Plot power events
        plots_for_legend = [p_current, p_voltage, p_percent] 
        
        added_plugged_in_legend = False
        added_unplugged_legend = False

        for event in events:
            event_time = datetime.fromisoformat(event['timestamp'])
            event_type = event['event_type']
            if event_type == 'plugged_in':
                line = self.ax1.axvline(event_time, color=self.theme['grn'], linestyle='-', linewidth=2.5, alpha=0.7) 
                if not added_plugged_in_legend:
                    line.set_label('Plugged In Event') 
                    plots_for_legend.append(line)
                    added_plugged_in_legend = True
            elif event_type == 'unplugged':
                line = self.ax1.axvline(event_time, color=self.theme['red'], linestyle=':', linewidth=2.5, alpha=0.7) 
                if not added_unplugged_legend:
                    line.set_label('Unplugged Event') 
                    plots_for_legend.append(line)
                    added_unplugged_legend = True

        # Style and legends
        self.ax1.grid(True, color=self.theme["sec"], linestyle=':', linewidth=0.5, alpha=0.5)
        self.ax1.spines['top'].set_visible(False)
        self.ax_combined_right.spines['top'].set_visible(False)
        
        # Create legend from all collected plot handles
        labels = [p.get_label() for p in plots_for_legend]
        self.ax1.legend(plots_for_legend, labels, loc='lower center', bbox_to_anchor=(0.5, 1.15), ncol=3,
                        fontsize=7, facecolor=self.theme['bg'], edgecolor=self.theme['sec'], labelcolor=self.theme['fg'])


        self.fig.tight_layout(pad=0.5) 
        self.canvas.draw()

    def update_status(self):
        if not self.is_running: return
        try:
            data = get_all_data_and_status(self.ina219, self.current_mode)
            
            current_timestamp = datetime.now().isoformat()

            # Log metric data to the main database
            self.db_manager.add_ups_metric(
                timestamp=current_timestamp,
                bus_voltage_V=data['bus_v'],
                shunt_voltage_mV=data['shunt_v'],
                battery_voltage_V=data['batt_v'],
                current_mA=data['current'],
                power_mW=data['power'],
                battery_percentage=data['percent'],
                remaining_mah=None, # This script doesn't track remaining_mah explicitly, ups_daemon does.
                status_text=data['status']
            )

            current_charging_state = data['charging_state']
            # Only log 'plugged_in' if transitioning from 'discharging' to 'charging'
            # or if the previous state was unknown and current is charging.
            # Suppress logging 'plugged_in' if already charging or full (trickle charging)
            if self.previous_charging_state == 'discharging' and current_charging_state == 'charging': 
                self.db_manager.add_ups_event(current_timestamp, 'plugged_in')
                self.root.after(0, self.update_graph_from_thread) 
            # Only log 'unplugged' if transitioning from 'charging' or 'standby' to 'discharging'
            elif (self.previous_charging_state == 'charging' or self.previous_charging_state == 'standby') and current_charging_state == 'discharging': 
                self.db_manager.add_ups_event(current_timestamp, 'unplugged')
                self.root.after(0, self.update_graph_from_thread) 
            # Also log initial 'plugged_in' if starting in charging state
            elif self.previous_charging_state is None and current_charging_state == 'charging':
                self.db_manager.add_ups_event(current_timestamp, 'plugged_in')
                self.root.after(0, self.update_graph_from_thread)

            self.previous_charging_state = current_charging_state

            if self.is_running: 
                self.root.after(0, self.update_ui_from_thread, data)
        except IOError as e: 
            error_data = {"status_text": f"Error: Sensor Read Failed! {e}"}
            if self.is_running: self.root.after(0, lambda: self.vars["status"].set(error_data["status_text"]))
            print(f"GUI update error (I2C): {e}")
            return 
        except Exception as e:
            error_data = {"status_text": f"Error: GUI Update Failed! {e}"}
            if self.is_running: self.root.after(0, lambda: self.vars["status"].set(error_data["status_text"]))
            print(f"GUI update error: {e}")
            
        if self.is_running and self.current_mode == INA219.SVOLT_BVOLT_CONTINUOUS:
            self.update_job = self.root.after(5000, self.update_status)

    def update_graph(self):
        """Periodically triggers a graph update."""
        if not self.is_running: return
        try:
            if self.is_running and hasattr(self, 'canvas'):
                self.root.after(0, self.update_graph_from_thread)
        except Exception as e:
            print(f"Graph update error: {e}")
            
        if self.is_running:
            self.graph_update_job = self.root.after(60000, self.update_graph)
    
    def manual_update(self):
        threading.Thread(target=self.update_status, daemon=True).start()

    def change_mode(self, mode):
        self.current_mode = mode
        try:
            self.ina219.set_configuration(mode=mode)
            mode_name = next((k for k, v in {"Continuous": INA219.SVOLT_BVOLT_CONTINUOUS, "Triggered": INA219.SVOLT_TRIGGERED, "Power Down": INA219.POWER_DOWN}.items() if v == mode), "Unknown")
            self.vars["status"].set(f"Mode set to {mode_name}")
        except Exception as e:
            self.vars["status"].set(f"Error setting mode: {e}")
            print(f"Error setting INA219 mode: {e}")
        
        if self.update_job: self.root.after_cancel(self.update_job)
        if mode == INA219.SVOLT_BVOLT_CONTINUOUS:
             self.update_status()

    def set_theme(self, theme_name):
        self.current_theme_name = theme_name
        self.apply_theme()

    def show(self): self.root.deiconify()
    def click_win(self, e): self._offset_x, self._offset_y = e.x, e.y
    def drag_win(self, e): self.root.geometry(f"+{self.root.winfo_pointerx() - self._offset_x}+{self.root.winfo_pointery() - self._offset_y}")
    
    def show_exit_menu(self, e):
        menu = tk.Menu(self.root, tearoff=0, bg=self.theme["bg"], fg=self.theme["fg"], relief='flat')
        theme_menu = tk.Menu(menu, tearoff=0, bg=self.theme["bg"], fg=self.theme["fg"])
        mode_menu = tk.Menu(menu, tearoff=0, bg=self.theme["bg"], fg=self.theme["fg"])
        for theme_name in sorted(THEMES.keys()):
            theme_menu.add_command(label=theme_name, command=lambda t=theme_name: self.set_theme(t))
        mode_options = {"Continuous": INA219.SVOLT_BVOLT_CONTINUOUS, "Triggered": INA219.SVOLT_TRIGGERED, "Power Down": INA219.POWER_DOWN}
        for mode_name, mode_val in mode_options.items():
            mode_menu.add_command(label=mode_name, command=lambda m=mode_val: self.change_mode(m))
        menu.add_cascade(label="Change Theme", menu=theme_menu)
        menu.add_cascade(label="Operating Mode", menu=mode_menu)
        menu.add_command(label="Refresh Graph", command=self.update_graph_from_thread)
        menu.add_separator()
        menu.add_command(label="Exit", command=self.exit_app)
        menu.tk_popup(e.x_root, e.y_root)

    def exit_app(self):
        self.is_running = False
        if self.update_job: self.root.after_cancel(self.update_job)
        if self.graph_update_job: self.root.after_cancel(self.graph_update_job)
        try:
            self.ina219.power_down()
        except Exception as e:
            print(f"Error powering down sensor on GUI exit: {e}")
        self.root.quit()

def main_gui(db_path="/var/lib/pi_backend/pi_backend.db"):
    db_manager = DatabaseManager(database_path=db_path)
    if db_manager.connection is None:
        print("Database connection failed. Cannot run GUI. Please check database file permissions.")
        raise Exception("Database connection failed for GUI.")

    ina219_instance = None
    try:
        ina219_instance = INA219()
        app = BatteryMonitorApp(db_manager, ina219_instance)
        app.show()
        app.root.after(100, app._start_periodic_updates)
        app.root.mainloop()
    except IOError as e:
        print(f"Hardware Error: Could not initialize or communicate with INA219 sensor for GUI.")
        print(f"Details: {e}")
        print("Please check: 1. UPS HAT connections. 2. I2C is enabled (sudo raspi-config). 3. Correct I2C address (0x42).")
        raise
    except Exception as e:
        print(f"An unexpected error occurred during GUI setup or mainloop: {e}")
        raise
    finally:
        db_manager.close()


# --- TUI-Specific Code ---

# Helper function to generate ASCII sparkline
def generate_ascii_sparkline(data_points, width=20, min_val=0, max_val=100):
    if not data_points:
        return " " * width

    # Normalize data to fit within 8 character "height" for sparkline
    gradient_chars = "  ▂▃▄▅▆▇█" 
    
    scaled_data = []
    for val in data_points:
        normalized_val = (val - min_val) / (max_val - min_val)
        scaled_val = int(normalized_val * (len(gradient_chars) - 1))
        scaled_data.append(max(0, min(len(gradient_chars) - 1, scaled_val)))
    
    display_data = scaled_data[-width:]
    
    sparkline = ""
    for val in display_data:
        sparkline += gradient_chars[val]
        
    sparkline = " " * (width - len(sparkline)) + sparkline
    return sparkline


class TuiController:
    def __init__(self, ina219, db_manager):
        self.ina219 = ina219
        self.db_manager = db_manager
        self.is_running = True
        self.current_mode = INA219.SVOLT_BVOLT_CONTINUOUS
        self.previous_charging_state_tui = None

    def get_char(self):
        fd = sys.stdin.fileno()
        old_settings = termios.tcgetattr(fd)
        try:
            tty.setraw(sys.stdin.fileno())
            ch = sys.stdin.read(1)
        finally:
            termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)
        return ch

    def key_listener(self):
        while self.is_running:
            char = self.get_char().lower()
            if char in ['x', '\x03', '\x18']:
                self.is_running = False
                break
            elif char == 'c':
                self.current_mode = INA219.SVOLT_BVOLT_CONTINUOUS
                print_tui_status(self.ina219, self.db_manager, self.current_mode, self, clear=True)
            elif char == 't':
                self.current_mode = INA219.SVOLT_TRIGGERED
                print_tui_status(self.ina219, self.db_manager, self.current_mode, self, clear=True)
            elif char == 'p':
                self.current_mode = INA219.POWER_DOWN
                print_tui_status(self.ina219, self.db_manager, self.current_mode, self, clear=True)
            time.sleep(0.1)

    def run(self):
        listener_thread = threading.Thread(target=self.key_listener, daemon=True)
        listener_thread.start()
        while self.is_running:
            print_tui_status(self.ina219, self.db_manager, self.current_mode, self, clear=True) 
            print("\n[C]ontinuous | [T]riggered | [P]ower Down | E[x]it")
            time.sleep(5)

def print_tui_status(ina219, db_manager, mode=INA219.SVOLT_TRIGGERED, tui_controller=None, clear=False):
    if clear: sys.stdout.write("\033[H\033[J")
    try:
        data = get_all_data_and_status(ina219, mode)
        current_timestamp = datetime.now().isoformat()

        # Log metric data to the main database
        db_manager.add_ups_metric(
            timestamp=current_timestamp,
            bus_voltage_V=data['bus_v'],
            shunt_voltage_mV=data['shunt_v'],
            battery_voltage_V=data['batt_v'],
            current_mA=data['current'],
            power_mW=data['power'],
            battery_percentage=data['percent'],
            remaining_mah=None, # This script doesn't track remaining_mah explicitly, ups_daemon does.
            status_text=data['status']
        )

        current_charging_state = data['charging_state']
        if tui_controller: # Ensure tui_controller exists
            # Refined power event logging for TUI
            if tui_controller.previous_charging_state_tui == 'discharging' and current_charging_state in ('charging', 'standby'): # Plugged in from discharging
                db_manager.add_ups_event(current_timestamp, 'plugged_in')
            elif (tui_controller.previous_charging_state_tui == 'charging' or tui_controller.previous_charging_state_tui == 'standby') and current_charging_state == 'discharging': # Unplugged
                db_manager.add_ups_event(current_timestamp, 'unplugged')
            elif tui_controller.previous_charging_state_tui is None and current_charging_state in ('charging', 'standby'): # Initial state is plugged in
                db_manager.add_ups_event(current_timestamp, 'plugged_in')
            tui_controller.previous_charging_state_tui = current_charging_state


        volt_color = TuiColors.C_GREEN if data['batt_v'] >= 8.0 else TuiColors.C_YELLOW if data['batt_v'] >= 7.6 else TuiColors.C_RED
        percent_color = TuiColors.C_GREEN if data['percent'] >= 60 else TuiColors.C_YELLOW if data['percent'] >= 25 else TuiColors.C_RED
        
        header_text = "UPS Power HAT Status"
        header = f"{TuiColors.C_BOLD}{TuiColors.C_PURPLE}{header_text:^40}{TuiColors.C_OFF}"
        separator = f"{TuiColors.C_PURPLE}{'=' * 40}{TuiColors.C_OFF}"
        print(f"{separator}\n{header}\n{separator}")
        
        label_width = 20
        print(f"  {TuiColors.C_CYAN}{'Load Voltage:'.ljust(label_width)}{TuiColors.C_OFF} {volt_color}{data['bus_v']:7.2f} V{TuiColors.C_OFF}")
        print(f"  {TuiColors.C_CYAN}{'Battery Voltage:'.ljust(label_width)}{TuiColors.C_OFF} {volt_color}{data['batt_v']:7.2f} V{TuiColors.C_OFF}")
        print(f"  {TuiColors.C_CYAN}{'Shunt Voltage:'.ljust(label_width)}{TuiColors.C_OFF} {data['shunt_v']:7.2f} mV")
        print(f"  {TuiColors.C_CYAN}{'Current:'.ljust(label_width)}{TuiColors.C_OFF} {data['current']:7.2f} mA")
        print(f"  {TuiColors.C_CYAN}{'Power:'.ljust(label_width)}{TuiColors.C_OFF} {data['power']:7.2f} mW")
        print(f"  {TuiColors.C_CYAN}{'Configured Capacity:'.ljust(label_width)}{TuiColors.C_OFF} {TuiColors.C_WHITE}{Config.BATTERY_CAPACITY_MAH} mAh (2x {Config.BATTERY_CAPACITY_MAH//2}mAh){TuiColors.C_OFF}")
        print(separator)

        log_percent = logarithmic_scale(data['percent'])
        bar_width, filled_len = 20, int(20 * log_percent / 100)
        bar = '█' * filled_len + '─' * (bar_width - filled_len)
        print(f"  Pack (Log): {percent_color}[{bar}]{TuiColors.C_OFF} {percent_color}{data['percent']:.1f}%{TuiColors.C_OFF}")
        
        cell_v = data['batt_v'] / 2
        cell_percent = get_cell_percentage(cell_v)
        parabolic_cell = parabolic_scale(cell_percent)
        bar_width, filled_len = 20, int(20 * parabolic_cell / 100)
        cell_volt_color = TuiColors.C_GREEN if cell_v >= 3.9 else TuiColors.C_YELLOW if cell_v >= 3.5 else TuiColors.C_RED
        bar = '█' * filled_len + '─' * (bar_width - filled_len)
        print(f"  Cell (Parabolic): {cell_volt_color}[{bar}]{TuiColors.C_OFF} ~{cell_volt_color}{cell_v:.2f}V{TuiColors.C_OFF}")
        print(separator)
        
        status, time_str, _ = get_status_and_time(data['percent'], data['current'])
        if data['current'] > Config.CURRENT_TRICKLE_MA: color = TuiColors.C_GREEN
        elif data['current'] > 5: color = TuiColors.C_CYAN
        elif data['current'] < -5: color = TuiColors.C_YELLOW
        else: color = TuiColors.C_GREEN

        print(f"  Status: {color}{status}{TuiColors.C_OFF}")
        if time_str: print(f"  {TuiColors.C_YELLOW}{time_str}{TuiColors.C_OFF}")

        # --- TUI Sparkline for Battery Percentage ---
        # Fetching all data and then filtering in Python for simplicity in this example
        # For large datasets, this should be optimized with SQL queries for specific time ranges
        all_metrics = db_manager.execute_query("SELECT timestamp, battery_voltage_V FROM ups_metrics ORDER BY timestamp ASC", fetch='all')
        recent_voltages = [m['battery_voltage_V'] for m in all_metrics if (datetime.now() - datetime.fromisoformat(m['timestamp'])).total_seconds() < 3600] # Last 1 hour
        recent_percentages_scaled = [get_pack_percentage(v) for v in recent_voltages]
        
        sparkline = generate_ascii_sparkline(recent_percentages_scaled, width=30) # Adjust width as needed
        print(f"  {TuiColors.C_CYAN}{'Recent Trend (%):'.ljust(label_width)}{TuiColors.C_OFF} {sparkline}")
        print(separator)

    except IOError as e: 
        print(f"\n{TuiColors.C_BOLD}{TuiColors.C_RED}Hardware Error (I2C): {e}{TuiColors.C_OFF}")
        print(f"{TuiColors.C_RED}Please ensure the UPS HAT is connected and I2C is enabled.{TuiColors.C_OFF}")
    except Exception as e:
        print(f"\n{TuiColors.C_BOLD}{TuiColors.C_RED}An unexpected error occurred in TUI update:{TuiColors.C_OFF}\nDetails: {e}")

def main_tui(db_path="/var/lib/pi_backend/pi_backend.db", continuous=False):
    db_manager = DatabaseManager(database_path=db_path)
    if db_manager.connection is None:
        print("Database connection failed. Exiting TUI. Please check database file permissions.")
        sys.exit(1)

    ina219_instance = None
    try:
        ina219_instance = INA219()
    except IOError as e:
        print(f"Hardware Error: Could not initialize INA219 sensor for TUI.")
        print(f"Details: {e}")
        print("Please check: 1. UPS HAT connections. 2. I2C is enabled (sudo raspi-config). 3. Correct I2C address (0x42).")
        db_manager.close()
        sys.exit(1)
    except Exception as e:
        print(f"An unexpected error occurred during INA219 initialization for TUI: {e}")
        db_manager.close()
        sys.exit(1)

    if continuous:
        controller = TuiController(ina219_instance, db_manager)
        controller.run()
    else:
        print_tui_status(ina219_instance, db_manager, clear=False) 
    db_manager.close()

def create_bidoof_icon():
    brown, dark_brown, white, black = (139, 69, 19), (101, 67, 33), (255, 255, 255), (0, 0, 0)
    img = Image.new('RGBA', (64, 64), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    # Body
    draw.ellipse((5, 20, 59, 60), fill=brown, outline=black, width=2)
    # Head
    draw.ellipse((20, 10, 44, 30), fill=brown, outline=black, width=2)
    # Eyes
    draw.ellipse((22, 30, 30, 38), fill=white, outline=black, width=1)
    draw.ellipse((34, 30, 42, 38), fill=white, outline=black, width=1)
    draw.ellipse((25, 33, 27, 35), fill=black)
    draw.ellipse((37, 33, 39, 35), fill=black)
    # Nose/Mouth
    draw.ellipse((29, 38, 35, 43), fill=dark_brown, outline=black, width=1)
    # Teeth
    draw.rectangle((26, 43, 30, 48), fill=white, outline=black, width=1)
    draw.rectangle((34, 43, 38, 48), fill=white, outline=black, width=1)
    
    home_dir = os.path.expanduser("~")
    icon_path = os.path.join(home_dir, ".local/share/icons/bidoof_icon.png")
    os.makedirs(os.path.dirname(icon_path), exist_ok=True)
    img.save(icon_path)
    return icon_path

def install_shortcut():
    script_path, home_dir = os.path.abspath(__file__), os.path.expanduser("~")
    desktop_path = os.path.join(home_dir, "Desktop")
    if not os.path.exists(desktop_path):
        print(f"Desktop directory not found at {desktop_path}. Aborting.")
        return
    print("Creating Bidoof icon...")
    icon_path = create_bidoof_icon()
    # Changed Name to "Bidoof Battery Manager" as requested
    shortcut_content = f"[Desktop Entry]\nVersion=1.0\nName=Bidoof Battery Manager\nComment=Monitor the Waveshare UPS HAT\nExec=python3 \"{script_path}\"\nIcon={icon_path}\nTerminal=false\nType=Application\nCategories=Utility;\n"
    shortcut_path = os.path.join(desktop_path, "bidoof_monitor.desktop")
    try:
        with open(shortcut_path, "w") as f: f.write(shortcut_content)
        os.chmod(shortcut_path, 0o755)
        print(f"\nShortcut created successfully on your desktop!\nPath: {shortcut_path}")
    except Exception as e:
        print(f"\nFailed to create desktop shortcut: {e}")

# --- Main Execution ---
def signal_handler(sig, frame):
    print("\nExiting. Attempting to power down the INA219 sensor...")
    try:
        temp_ina219 = INA219()
        temp_ina219.power_down() # Fixed typo: INA291 to INA219
    except Exception as e:
        print(f"Could not power down sensor: {e}")
    sys.exit(0)

if __name__ == "__main__":
    signal.signal(signal.SIGINT, signal_handler)
    
    # Define the default database path for the main pi_backend database
    # This should match the path used by the main pi_backend application
    DEFAULT_PI_BACKEND_DB_PATH = "/var/lib/pi_backend/pi_backend.db"

    if "--install-shortcut" in sys.argv:
        install_shortcut()
        sys.exit(0)
        
    is_continuous = "-c" in sys.argv or "--continuous" in sys.argv
    is_gui = os.environ.get('DISPLAY')
    
    if not os.path.exists(I2C_BUS_DEVICE):
        print(f"Error: I2C bus device '{I2C_BUS_DEVICE}' not found.")
        print("Please ensure I2C is enabled on your Raspberry Pi using 'sudo raspi-config'.")
        sys.exit(1)
        
    try:
        if is_gui:
            print("DISPLAY environment variable detected. Attempting to launch GUI...")
            main_gui(db_path=DEFAULT_PI_BACKEND_DB_PATH)
        else:
            print("DISPLAY environment variable not found. Launching Text-based UI (TUI).")
            print("To run the GUI, ensure you are in a graphical environment or use 'ssh -X'.")
            main_tui(db_path=DEFAULT_PI_BACKEND_DB_PATH, continuous=is_continuous)
    except tk.TclError as e:
        print(f"\nGUI Error: Could not start graphical interface. This usually means Tkinter or your X server is not correctly configured or available.")
        print(f"Details: {e}")
        print("Please ensure 'python3-tk' and 'python3-matplotlib' are installed.")
        print("Falling back to Text-based UI (TUI).")
        main_tui(db_path=DEFAULT_PI_BACKEND_DB_PATH, continuous=is_continuous)
    except IOError as e:
        print(f"\nHardware/Communication Error: {e}")
        print("Falling back to Text-based UI (TUI) as GUI/sensor communication failed.")
        main_tui(db_path=DEFAULT_PI_BACKEND_DB_PATH, continuous=is_continuous)
    except Exception as e:
        print(f"\nAn unexpected critical error occurred: {e}")
        print("The application cannot continue. Please review the error message.")
    finally:
        pass

