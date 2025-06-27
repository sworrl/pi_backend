π-Backend: Raspberry Pi Control & Monitoring System
Overview
The π-Backend project provides a robust and extensible solution for controlling, monitoring, and managing a Raspberry Pi-based system through a web interface and background services. It integrates various hardware components (like the Sense HAT and A7670E LTE modem with GPS), provides environmental and location services, and offers a comprehensive dashboard for real-time data visualization and administrative tasks.

Key Features
This version brings significant enhancements to stability, automation, and user interface:

Automated Setup and Updates:

setup.sh Refactor: The primary setup script (setup.sh) has been extensively refactored for improved reliability and automation.

Automatic Updates: Detects new local source files or discrepancies with the GitHub repository and automatically triggers a patch/update process on startup, eliminating the need for manual uninstalls for upgrades.

Database Protection: The setup process now intelligently manages the SQLite database, ensuring data is preserved during updates and only wiped during explicit uninstall operations.

Robust A7670E GPS Integration:

Dedicated Installer Tool: Integrates your specialized setup_a7670e_gps.sh tool for precise installation and management of the A7670E GPS initialization script and its systemd service.

Enhanced Diagnostics: The setup script now captures and displays detailed output from the A7670E GPS installer tool, aiding in troubleshooting its setup.

Improved Backend Architecture:

Dependency Injection: Critical Flask application context errors ("Working outside of application context") in weather_services, location_services, app.py, data_poller.py, and api_routes.py have been resolved. Database and configuration managers are now explicitly passed to service functions, ensuring robust operation in all contexts.

New API Endpoint: A /api/system/file-info endpoint has been added, dynamically providing version numbers and SHA256 checksums of installed backend files for integrity checks.

Enhanced Web Dashboard (index.html):

Specialized Tabs: The dashboard now features highly specialized tabs for clearer organization of information:

Overview: Provides high-level summaries of GPS, Database, and core System Status (CPU, Memory, Disk, Sense HAT temp).

GPS: Dedicated tab for detailed GPS data and an OpenStreetMap display.

Time: Dedicated tab for Chrony synchronization status, clock performance, and dynamic explanation of Frequency Skew.

Hardware: Detailed Sense HAT sensor readings and LED controls, along with other hardware actions.

Location: Geocoding, Reverse Geocoding, and Community Services (Nearby POIs).

Weather: External weather service tests with improved card-based display.

Update: New tab! Displays a table comparing installed file versions and checksums against local source files or the GitHub repository (sworrl/pi_backend/main), indicating if files are OK, OUTDATED, MISSING, NEWER_ON_DEVICE, or FETCH_FAILED. Includes a button to trigger updates from GitHub.

Users: For user account management (admin only).

Admin: For API key management and admin login/logout.

Live Clock: A persistent, live-updating digital clock is now integrated directly into the left sidebar for constant visibility.

Improved UI/UX: Cleaner layout, consistent styling with Tailwind CSS, and better feedback mechanisms (in-page toast messages instead of disruptive alert()).

Installation
To install and set up the π-Backend system on your Raspberry Pi:

Clone the repository (or transfer files):

git clone https://github.com/sworrl/pi_backend.git
cd pi_backend

Ensure your setup_a7670e_gps.sh and a7670e-gps-init.sh files are in this directory.

Make setup.sh executable:

chmod +x setup.sh

Run the setup script:

./setup.sh

The script will guide you through the initial setup process. It will automatically detect if it's a first-time installation or if updates are needed.

First-Time Install: It will install prerequisites, deploy files, configure services, and prompt you to set an initial admin password.

Updates: It will automatically detect outdated files by comparing them against your local source, prompt you for confirmation, and then apply the updates and restart necessary services.

Configure Raspberry Pi Serial Port (if using A7670E HAT):

Run sudo raspi-config.

Go to 3 Interface Options.

Select P6 Serial Port.

For "Would you like a login shell to be accessible over serial?", select NO.

For "Would you like the serial port hardware to be enabled?", select YES.

Reboot your Raspberry Pi for changes to take effect: sudo reboot.

Usage
After successful installation, the web dashboard should be accessible via your Raspberry Pi's IP address or configured domain.

Accessing the Dashboard:

Open a web browser and navigate to http://<YOUR_PI_IP_ADDRESS>/ or https://<YOUR_DOMAIN_NAME>/.

Initial Admin Setup: If it's a first-time run, you'll be prompted to set an initial admin password. Use admin as the default username.

Dashboard Navigation: Use the tabs at the top of the main content area to navigate through different sections:

Overview: Quick summaries of system status.

GPS: Detailed GPS fixes and map display.

Time: Chrony synchronization details and clock performance.

Hardware: Sense HAT sensor data and LED controls, Bluetooth scan, LTE modem info.

Location: Geocoding and reverse geocoding tests, community POI searches.

Weather: Test external weather API integrations.

Update: Crucial for maintenance. Compare installed files against local or GitHub versions and initiate updates.

Users: Manage backend user accounts (Admin only).

Admin: Manage API keys for external services and admin login/logout.

Left Sidebar: Provides persistent system status metrics and the live digital clock.

API Endpoints
The backend exposes a RESTful API. Here are some key endpoints:

/api/status: Get overall API status and backend version.

/api/hardware/system-stats: Get CPU, memory, disk usage.

/api/hardware/sensehat/data: Get Sense HAT sensor readings.

/api/hardware/gps/best: Get the best available GPS fix.

/api/services/location-test?location=<query>: Geocode a location string.

/api/services/weather-test?location=<query>: Get weather data.

/api/system/file-info?mode=[local|github]: (Admin only) Get details about installed files.

/api/system/update-files: (Admin only) Trigger a backend file update.

/api/users: Manage user accounts (Admin only).

/api/keys: Manage API keys (Admin only).

Refer to the api_routes.py file for a comprehensive list of all available endpoints.

Troubleshooting
setup.sh issues:

Ensure setup.sh is executable (chmod +x setup.sh).

Run sudo apt update && sudo apt upgrade -y first to ensure system packages are up-to-date.

If encountering Exec format error for .sh scripts, verify file permissions (chmod +x <script_name>) and line endings (convert to Unix/LF using dos2unix <script_name>).

If apt updates fail, check network connectivity.

Service Failures (502, 503 errors from API test):

Check backend service logs: sudo journalctl -u pi_backend_api.service --no-pager -f

Check web server logs (Apache): sudo tail -f /var/log/apache2/error.log

Ensure all Python dependencies are installed.

GPS/Chrony issues:

Check GPSD service status: sudo systemctl status gpsd.service

Check Chrony status: chronyc sources and chronyc clients

Verify serial port configuration in sudo raspi-config.

Check the A7670E GPS installer tool's specific logs: sudo journalctl -u a7670e-gps-init.service --no-pager -f.

Changelog Summary
v21.8.x Series: Introduced robust setup.sh automatic updates and GitHub comparison. Overhauled index.html dashboard for specialized tabs and live clock. Enhanced API debugging.

v21.7.x Series: Refined setup.sh auto-update logic, protected database from accidental wipes, improved file version comparison diagnostics, and introduced the external A7670E GPS installer tool. Initial fixes for "Working outside of application context" errors and ModuleNotFoundError in Python services.

v21.6.x Series: Initial database-backed configuration, systemd service management, prerequisite verification, and basic API setup.