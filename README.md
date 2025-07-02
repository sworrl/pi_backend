π-Backend: The Raspberry Pi Command Center 🚀
Version: 2.0.10

⚡️ Quick Install (One-Liner)
Get your π-Backend up and running with a single command. This will download the installer and guide you through the setup. Always review scripts before running them with sudo!

``` curl -sL https://raw.githubusercontent.com/sworrl/pi_backend/main/setup.py | sudo python3 - ```

📝 Table of Contents
Overview

Key Features

Architecture

🚀 Quick Start (One-Liner)

🛠️ Installation Guide

Prerequisites

Manual Installation Steps

Initial Setup & Configuration Prompts

Updating Your Backend

🖥️ Usage

📋 API Endpoints Reference

⚠️ Known Issues & Troubleshooting

🤝 Contributing

📄 License

Overview
The π-Backend is a comprehensive, self-contained Python backend designed specifically for Raspberry Pi devices. It transforms your Pi into a powerful command center, providing a robust API server, continuous data logging, and seamless hardware integration. It's built as a flexible foundation for various frontend applications, from personal dashboards to IoT monitoring systems.

🌟 Key Features
RESTful API Server (Flask + Gunicorn): Exposes a secure, well-documented API for real-time data access and hardware control.

Intelligent Data Polling Service: A persistent systemd service that intelligently polls various internal and external API endpoints (including weather, astronomy, and community POIs) at configurable intervals, storing data directly into a local SQLite database.

Smart Polling: Configurable frequencies to avoid over-polling infrequently changing data (e.g., daily for moon data, hourly for space weather, weekly for POIs).

Comprehensive Hardware Interfacing

GNSS (GPS): Real-time position, velocity, and satellite data via gpsd.

Waveshare UPS HAT: Detailed battery metrics (voltage, current, percentage, status) and power events (charging/discharging, plugged/unplugged) logged continuously via ups_status.py directly to the main database.

Sense HAT: Environmental sensors (temperature, humidity, pressure) and joystick input.

LTE Modems (e.g., A7670E): Network information, signal quality, and flight mode control.

Bluetooth: Device scanning capabilities.

Robust Data Storage (SQLite): All collected data, system logs, and configuration settings are stored in a local SQLite database, ensuring persistence and easy access.

Enhanced Community POI Data: Fetches and aggregates Points of Interest from OpenStreetMap, with intelligent data enrichment (phone numbers, websites, precise addresses) using Google Places API (requires API key). Includes a wide range of infrastructure types (water, sewage, power, government, emergency services).

Dynamic API Endpoint Documentation: A dedicated API endpoint (/api/routes_info) exposes a live, machine-readable list of all available API routes, their methods, and descriptions.

Secure User & API Key Management: Database-backed user authentication (admin/user roles) and secure storage for external API keys.

Automated Installer & Updater: A powerful Python setup.py script automates initial installation, updates, dependency management, service setup, and Apache configuration (including SSL with Certbot).

Web-Based Dashboard: A simple HTML/JavaScript test page (index.html) provides a live view of system status, sensor data, and interactive API testing.

Apache Web Server Integration: Configures Apache for secure hosting, including HTTPS (with Let's Encrypt), static file serving from a dedicated secure web root, and reverse proxying API calls to the Flask API.

🏛️ Architecture
The π-Backend follows a modular and layered architecture:

Hardware Layer: Direct interaction with Raspberry Pi GPIO, I2C, serial ports, and system utilities (e.g., gpsd, chrony).

Modules Layer (pi_backend/modules/): Python classes encapsulating specific hardware components (e.g., A7670E.py, sense_hat.py, ina219.py).

Services Layer (pi_backend/): Python modules providing high-level functionalities by interacting with hardware modules and external APIs (e.g., location_services.py, weather_services.py, astronomy_services.py, communtiy_services.py).

Data Layer (pi_backend/database.py, pi_backend/db_config_manager.py): Manages SQLite database interactions for data logging, configuration, and user/API key management.

API Layer (pi_backend/app.py, pi_backend/api_routes.py): A Flask application served by Gunicorn, exposing RESTful endpoints.

System Services: systemd manages long-running processes like the Flask API (pi_backend_api.service), the data poller (pi_backend_poller.service), and GPS initialization (a7670e-gps-init.service).

Web Server (Apache): Handles incoming HTTP/HTTPS requests, serves the static dashboard (index.html), and reverse proxies API calls to Gunicorn.

+-------------------+       +-------------------+       +-------------------+
|     Frontend      | <---> | Apache Web Server | <---> |  Gunicorn/Flask   |
| (Browser/App)     |       | (HTTPS/Proxy)     |       |   (pi_backend_api)|
+-------------------+       +-------------------+       +---------|---------+
                                                                    |
                                                                    v
                                                          +---------|---------+
                                                          |  API Endpoints    |
                                                          | (`api_routes.py`) |
                                                          +---------|---------+
                                                                    |
                                        +---------------------------+---------------------------+
                                        |                           |                           |
                                        v                           v                           v
                              +--------------------+      +--------------------+      +--------------------+
                              |  Service Logic     |      |  Data Poller       |      |  Hardware Managers |
                              | (`weather_services`)|      | (`data_poller.py`) |      | (`hardware_manager`)|
                              | (`communtiy_services`)|      | (Systemd Service)  |      | (`A7670E`, `SenseHAT`)|
                              +----------|---------+      +----------|---------+      +----------|---------+
                                         |                           |                           |
                                         v                           v                           v
                                +-----------------------------------------------------------------+
                                |                     SQLite Database (`pi_backend.db`)         |
                                | (Sensor Data, Location, POIs, UPS Metrics, Config, Users, Keys) |
                                +-----------------------------------------------------------------+

🛠️ Installation Guide
Prerequisites
A Raspberry Pi (Raspberry Pi OS Lite or Desktop recommended).

An active internet connection.

Basic Linux command-line familiarity.

Manual Installation Steps
If you prefer to manually control the installation process:

Clone the Repository:

git clone https://github.com/sworrl/pi_backend.git
cd pi_backend

Make the Setup Script Executable:

chmod +x setup.py

Run the Setup Script:

sudo ./setup.py

The script is interactive. Follow the prompts carefully. It will guide you through:

Installing system dependencies.

Setting up directories and permissions.

Configuring GPSD and Chrony.

Deploying application files.

Crucially, it will prompt you to create the initial admin user, configure SSL, and enter 3rd-party API keys.

Installing systemd services.

Configuring Apache.

Initial Setup & Configuration Prompts
During the first-time installation, setup.py will prompt you for:

Database Path: Default is /var/lib/pi_backend/pi_backend.db.

Initial Admin Password: You must create an admin user for security.

SSL Certificate: Option to obtain a free Let's Encrypt SSL certificate for your domain (highly recommended for secure access).

WebSDR Proxy: Option to enable a reverse proxy for a local WebSDR instance (if you run one).

3rd-Party API Keys: The script will check for and prompt you to enter keys for services like OpenWeatherMap, Windy, AccuWeather, and Google Places API. These are crucial for external data fetching.

Updating Your Backend
To update your π-Backend to the latest version while preserving your configurations and data:

Navigate to your pi_backend source directory:

cd /path/to/your/pi_backend  # e.g., /home/pi/pi_backend

Pull the latest changes from GitHub:

git pull

Run the setup script again:

sudo ./setup.py

Select option 3 (System & Update) then 1 (Run Update & Patch Check). This will redeploy updated files and reinstall services, ensuring everything is fresh.

🖥️ Usage
Once installed and running, access your π-Backend dashboard and API:

Dashboard URL:

If you configured SSL: https://your_domain_name/ (e.g., https://jengus.wifi.local.falcontechnix.com/)

If no SSL: http://your_pi_ip_address/ (e.g., http://192.168.1.100/)

API Base URL: The API endpoints are accessible under /api/ relative to your dashboard URL.

Example: https://your_domain_name/api/status

📋 API Endpoints Reference
For a live, up-to-date, and interactive list of all available API endpoints, their methods, and descriptions, navigate to the "API Endpoints" tab on your deployed dashboard. This tab dynamically fetches information directly from your running backend, ensuring accuracy.

Example: https://your_domain_name/ -> Click "API Endpoints" tab.

⚠️ Known Issues & Troubleshooting
This section highlights common issues and provides debugging steps.

chrony.service failure:

Symptom: systemctl status chrony.service shows failed, and journalctl -xeu chrony.service might show errors related to time sources or permissions.

Cause: Often occurs if GPS signal is not immediately available or if previous NTP services conflict.

Solution:

Ensure your GPS HAT has a clear view of the sky.

After setup.py completes, a sudo reboot can often resolve this as it allows all services to start cleanly.

If persistent, manually check sudo chronyc sources and sudo journalctl -u chrony.service --no-pager.

You can manage Chrony config via sudo ./setup.py -> Diagnostics & Tools.

"Service Unavailable" / API Not Reachable:

Symptom: When accessing https://your_domain_name/ or https://your_domain_name/api/status, you see a "Service Unavailable" or "Couldn't connect to server" error.

Cause: This means Apache is running, but your Flask API (run by Gunicorn) is not reachable on http://127.0.0.1:5000.

Solution:

Check API Service Status: systemctl status pi_backend_api.service. It should be active (running). If failed, proceed.

Review API Service Logs: journalctl -u pi_backend_api.service --no-pager -n 50. Look for Python tracebacks (e.g., ModuleNotFoundError, NameError), Gunicorn binding errors, or Flask application errors.

Verify Gunicorn Listener: sudo ss -tuln | grep 5000. You should see LISTEN on port 5000.

Permissions: Ensure /var/www/pi_backend (your __INSTALL_PATH__) and its contents are owned by www-data:www-data. Run sudo ./setup.py and select "Enforce Final File & User Permissions".

Apache Config: Ensure DocumentRoot is correctly pointing to /var/www/pi_backend_static and ProxyPass /api/ is correct. setup.py should handle this, but verify the templates if necessary.

Reboot: A sudo reboot often resolves transient issues.

Missing Google Places API Data:

Symptom: POI data on the map or via API lacks phone numbers, websites, or has generic addresses.

Cause: The GOOGLE_PLACES_API_KEY is either missing or invalid in your database.

Solution: Run sudo ./setup.py and select the "Keys & Admin" tab (login as admin if needed). Ensure GOOGLE_PLACES_API_KEY is present and correct.

UPS Data Not Updating:

Symptom: UPS HAT data on the dashboard or API is stale or missing.

Cause: The ups_status.py script, which continuously logs data, might not be running. The old ups_daemon.py is no longer used.

Solution: Ensure ups_status.py is running in continuous mode in the background. You can start it manually for testing: python3 /path/to/pi_backend/ups_status.py -c. For persistent logging, set it up as a systemd service if you haven't already done so (this would be a manual systemd unit creation not currently covered by setup.py but is a planned enhancement).


🤝 Contributing
Contributions are welcome! If you find a bug or have a feature request, please open an issue on the GitHub repository.

📄 License
This project is licensed under the MIT License - see the LICENSE file for details.
