pi_backend
Version: 2.2.0

Project Overview
This project is a comprehensive Python backend designed to run on a Raspberry Pi. It provides a robust API server built with Flask and includes a persistent background service for periodic data collection. It is designed to be the central API and data-logging service for any number of frontend applications.

Core Features
RESTful API Server: Provides endpoints for real-time data and control under the /api/ path.

Background Data Polling Service: A systemd service that runs on boot, periodically fetches data from the API, and stores it in the local database.

Configurable Polling: Polling frequencies for different data points (GNSS, weather, etc.) can be easily changed in a .ini file without touching the code.

Hardware Interfacing: Real-time data and control for the Sense HAT, GNSS (via gpsd or UART), Bluetooth, and LTE Modems (via GPIO and Serial).

Installer & Updater: A comprehensive setup.sh script automates installation, updates, and service management.

Secure API Key Management: Uses a permission-restricted API.keys file and provides an endpoint (/api/keys) to update keys securely from a frontend UI.

The Data Poller Service
A key feature of this backend is the pi_backend_poller service. This is a Python script that runs continuously in the background and is managed by systemd, ensuring it starts automatically on boot.

Its purpose is to automatically collect time-series data without requiring a frontend to be active. It calls its own API (e.g., /api/hardware/gps) and stores the JSON response in a dedicated polled_data table in the database, along with a timestamp and data source.

Configuring the Poller
You can change how often data is collected by editing the configuration file.

Example using the default path:
sudo nano /var/www/pi_backend/poller_config.ini

The file contents are simple:

[Frequencies]

Polling intervals. Do not use quotes.
weather_minutes = 10
climate_days = 7
gps_seconds = 10

Simply change the numbers and save the file. Then, restart the service for the changes to take effect:
sudo systemctl restart pi_backend_poller.service

Setup, Updates, and Service Management
Prerequisites
A Raspberry Pi running a recent version of Raspberry Pi OS.

An active internet connection.

Step 1: Download and Run the Script
Get the pi_backend project files onto your Raspberry Pi. Then, run the interactive installer.

cd /path/to/pi_backend-main/
chmod +x setup.sh
./setup.sh

The script will present a menu:

Install New Backend: For a fresh installation.

Update Existing Backend: Updates the application files while preserving your data and keys.

Install/Update Data Poller Service: Use this after an initial install or update to set up the background service.

Quit

Step 2: CRITICAL - Configure API Keys
After installation, you must edit the API.keys file.

sudo nano /var/www/pi_backend/API.keys

Fill in the values for "YOUR_KEY_HERE". The GEMINI_API_KEY can also be set from a frontend UI.

Running the Backend Server
For testing, you can run the app manually. For production, you should run it as a systemd service.

Navigate to your installation directory
cd /var/www/pi_backend/
python3 app.py

API Endpoint Guide
All API calls should be made to relative paths starting with /api/.

Status and Configuration
Method

Endpoint

Request Body

Description

GET

/api/version

(none)

Returns the version of the running backend, e.g., {"version": "2.2.0"}.

GET

/api/status

(none)

A simple, lightweight endpoint to check if the API is running.

POST

/api/keys

{ "key_name": "GEMINI_API_KEY", "key_value": "AIzaSy..." }

Securely saves or updates an API key in the API.keys file.

Hardware, GNSS & LTE Control
Method

Endpoint

Request Body / Params

Description

GET

/api/hardware/cpu

(none)

Gets current CPU usage percentage.

GET

/api/hardware/memory

(none)

Gets current memory usage percentage.

GET

/api/hardware/sensehat

(none)

Gets sensor data from the Sense HAT.

GET

/api/hardware/gps

(none)

Gets GNSS data from the gpsd service (now handled by gnss_services.py).

GET

/api/hardware/gps/uart

(none)

Gets raw NMEA GNSS data directly from the default serial port (now handled by gnss_services.py).

GET

/api/hardware/gps/status

(none)

Checks if the gpsd service is running (now handled by gnss_services.py).

GET

/api/hardware/lte/status

?port=/dev/ttyUSB2 (optional)

Gets status, signal strength, and operator from a connected LTE modem.

POST

/api/hardware/lte/power-cycle

(none)

Toggles the LTE modem power by pulsing the GPIO power key.

POST

/api/hardware/lte/flight-mode

{ "enable": true } or { "enable": false }

Enables or disables the modem's flight mode via GPIO.

External Data & Database
Method

Endpoint

Query Parameters (Example)

Description

GET

/api/location-data

?location=Tokyo&modules=forecast

Resolves a location and fetches Open-Meteo data. Can use GNSS if no location is provided.

GET

/api/weather-data

?location=London,UK&services=openweather

Fetches aggregated weather data from various APIs.

POST

/api/data

{ "data": "your_string_here" }

Saves a generic string to the database.

GET

/api/data

(none)

Retrieves all saved data entries.