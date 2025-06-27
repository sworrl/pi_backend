pi_backend Changelog
[2.1.0] - 2025-06-17
Added
Hardware Control (LTE & GPS):

Added GPIO control functions in hardware.py to power cycle the LTE modem (toggle_lte_power) and set its flight mode (set_flight_mode).

Added the ability to query the LTE modem over both UART (/dev/ttyS0) and USB (/dev/ttyUSBx) serial ports.

Added a function to read raw NMEA GPS data directly from the UART serial port (get_gps_from_uart), as an alternative to gpsd.

New API Endpoints (app.py):

POST /api/hardware/lte/power-cycle: Toggles the modem's power via GPIO.

POST /api/hardware/lte/flight-mode: Enables or disables the modem's flight mode.

GET /api/hardware/gps/uart: Gets raw NMEA data from the modem's serial port.

New Dependency: Added python3-rpi.gpio to setup.sh for GPIO control.

Changed
Independent File Versioning: Every Python script now has its own __version__ and a versioning header. This allows for individual updates without changing the entire project version.

Dev Notes: Added a DEV_NOTES section to each script for better maintainability.

API Enhancement: The GET /api/hardware/lte/status endpoint now accepts an optional port query parameter (e.g., ?port=/dev/ttyUSB2) to specify which serial interface to use.

setup.sh: Script updated to install new rpi.gpio dependency.

README.md: Updated to document all new hardware control endpoints and the versioning system.

[2.0.0] - 2025-06-17
Added versioning system, update feature in setup.sh, and basic LTE/GPSD status checks.

Refactored service modules to remove subprocess calls in favor of direct imports.

[1.0.0] - 2025-06-16
Initial release with core features.

Flask server (app.py).

Hardware monitoring (hardware.py): CPU, Memory, Sense HAT, Bluetooth, basic GPS.

External data services: Geocoding (location_services.py), Weather (weather_services.py), Astronomy (astronomy_services.py).

API Key management (config_loader.py, POST /api/keys).

Database support (database.py).

Interactive installer (setup.sh).