# 🥧 pi-backend

<p align="center">
  <img src="https://raw.githubusercontent.com/sworrl/pi_backend/main/icon.png" alt="pi-backend logo" width="150"/>
</p>

<p align="center">
  <strong>A comprehensive, hardware-integrated backend for the Raspberry Pi.</strong>
  <br />
  <br />
  <img src="https://img.shields.io/badge/version-v4.6.0-blue.svg" alt="Version" />
  <img src="https://img.shields.io/badge/python-3.x-green.svg" alt="Python" />
  <img src="https://img.shields.io/badge/license-MIT-lightgrey.svg" alt="License" />
</p>

---

**π-Backend** transforms your Raspberry Pi into a powerful, multi-purpose server. It provides a robust RESTful API built with Flask, a persistent background service for data collection, and a deep integration with a wide range of hardware components. Whether you're building a personal dashboard, a remote sensor station, or a home automation hub, this project provides the foundational services you need.

## ✨ Features

| Feature                   | Description                                                                                             |
| ------------------------- | ------------------------------------------------------------------------------------------------------- |
| 🌐 **RESTful API Server** | A secure, extensible API serving real-time data and control functions, powered by Flask and Gunicorn.     |
| 🔄 **Background Polling** | A `systemd` service runs on boot, automatically collecting and logging time-series data to a database.  |
| 🔒 **Unified Security** | Integrated user authentication (Argon2 hashing) and API key management for secure endpoint access.      |
| 🤖 **Hardware Interface** | Direct control and data retrieval from Sense HAT, GPS/GNSS modules, LTE modems, and Bluetooth.          |
| ☁️ **Cloud Service Bridge** | Aggregates data from multiple external weather and location APIs (OpenWeather, NOAA, Windy, etc.).      |
| 🛰️ **Local Services** | Provides local information like nearby points of interest (police, fire stations) and astronomy data. |
| 🗄️ **Database-Driven** | All application data, logs, and configuration are managed within a central SQLite database.            |
| 🚀 **Automated Installer** | A comprehensive installer script handles all dependencies, setup, service installation, and updates.  |

## ⚙️ Core Services

### 1. RESTful API Server (`app.py`)

The heart of the project is the Flask API server, run as a `gunicorn` process and managed by `systemd`. It exposes all hardware and data functions through a set of secure, authenticated endpoints.

### 2. Background Data Poller (`data_poller.py`)

The `pi_backend_poller` is a persistent background service that starts on boot. Its primary role is to automatically collect time-series data from its own API and external sources, storing the results in the database. This ensures a continuous log of sensor, GPS, and weather data without requiring an active frontend client.

Polling frequencies are now managed in the database and can be configured via the web UI.

## 🚀 Installation & Management

The entire lifecycle of the application is managed by a single, powerful installer script.

### Prerequisites

- A Raspberry Pi running a recent 64-bit version of Raspberry Pi OS.
- An active internet connection for the initial setup.

### Step-by-Step Installation

1.  **Download Project:** Get the `pi_backend` project files onto your Raspberry Pi.
2.  **Make Executable:** Open a terminal and navigate to the project directory.
    ```bash
    chmod +x setup.sh
    ```
3.  **Run Installer:** Execute the script as a regular user (it will ask for `sudo` when needed).
    ```bash
    ./setup.sh
    ```

The script will guide you through an interactive menu to handle:
- **First-Time Installation:** Installs all dependencies, deploys files, configures hardware, and sets up the `systemd` services.
- **Updates & Patches:** Compares local files against the source and applies updates as needed.
- **Service Management:** Start, stop, and check the status of all backend services.
- **Full Uninstall:** Securely removes all files and configurations.

---

## 🔐 Security

All API endpoints (with the exception of initial setup routes) are protected and require authentication.

- **User Authentication:** Use Basic Authentication with a username and password. An `admin` user can be created through the web UI on the first run if no users exist in the database.
- **API Key Authentication:** Pass a valid API key in the `X-API-Key` request header. Keys can be generated and managed in the **Keys & Admin** tab of the web dashboard.

## 📡 API Endpoint Guide

### Authentication
All requests must include either Basic Auth credentials or an `X-API-Key` header.

### Status & System

| Method | Endpoint                    | Description                                                                 |
| :----- | :-------------------------- | :-------------------------------------------------------------------------- |
| `GET`  | `/api/status`               | Checks if the API is running. Returns version and default credential status.|
| `GET`  | `/api/system/file-info`     | Returns version and checksum information for all managed backend files.     |
| `GET`  | `/api/hardware/system-stats`| Gets detailed system statistics (CPU, memory, disk, boot time).             |
| `GET`  | `/api/hardware/time-sync`   | Gets detailed time synchronization statistics from `chrony`.                |

### Hardware Control & Data

| Method | Endpoint                            | Request Body / Params                                        | Description                                                              |
| :----- | :---------------------------------- | :----------------------------------------------------------- | :----------------------------------------------------------------------- |
| `GET`  | `/api/hardware/summary`             | (none)                                                       | Provides a high-level summary of detected hardware status (SenseHAT, GPS, LTE). |
| `GET`  | `/api/hardware/sensehat/data`       | (none)                                                       | Gets all current sensor data from the Sense HAT.                         |
| `POST` | `/api/hardware/sensehat/execute-command` | `{ "command": "...", "params": {...} }`                 | Executes a command on the Sense HAT (e.g., scroll text, clear display). |
| `POST` | `/api/hardware/bluetooth-scan`      | (none)                                                       | Scans for nearby Bluetooth devices.                                      |
| `GET`  | `/api/hardware/gps/best`            | (none)                                                       | Gets the best available GNSS/GPS data from all available sources.        |
| `GET`  | `/api/hardware/lte/network-info`    | (none)                                                       | Gets status, signal strength, and operator from a connected LTE modem.   |
| `POST` | `/api/hardware/lte/flight-mode`     | `{ "enable": true }` or `{ "enable": false }`                | Enables or disables the LTE modem's flight mode.                         |

### Data Services (Weather, Location, Community)

| Method | Endpoint                  | Query Parameters (Example)                                   | Description                                                              |
| :----- | :------------------------ | :----------------------------------------------------------- | :----------------------------------------------------------------------- |
| `GET`  | `/api/services/weather-test` | `?location=Paris,France`                                     | Fetches and aggregates weather data from all configured external services (OpenWeather, NOAA, etc.). Uses GPS if no location is provided. |
| `GET`  | `/api/services/location-test` | `?location=Eiffel+Tower` or `?lat=48.8&lon=2.3`              | Geocodes a location string to coordinates or reverse geocodes coordinates to an address. |
| `GET`  | `/api/community/nearby`   | `?types=police,fire_station`                                 | Finds the closest points of interest (police, fire stations, hospitals, etc.) and PFAS sites based on the device's current GPS location. |

### User & Key Management (Admin Only)

These endpoints require authentication as an `admin` user.

| Method   | Endpoint                | Description                                                |
| :------- | :---------------------- | :--------------------------------------------------------- |
| `GET`    | `/api/users`            | Lists all registered users in the system.                  |
| `POST`   | `/api/users`            | Creates a new user with a specified username, password, and role. |
| `GET`    | `/api/users/<username>` | Gets the details for a specific user.                      |
| `PUT`    | `/api/users/<username>` | Updates a user's password or role.                         |
| `DELETE` | `/api/users/<username>` | Deletes a user.                                            |
| `GET`    | `/api/keys`             | Lists all API keys (names only, for security).             |
| `POST`   | `/api/keys`             | Adds a new API key. Can be for external services or a generated internal key. |
| `DELETE` | `/api/keys/<key_name>`  | Deletes an API key.                                        |

---

## 🔧 Configuration

The `pi_backend` uses a database-first approach for configuration.

1.  **Initial Setup:** On the very first run, a `setup_config.ini` file is used to determine essential system paths.
2.  **Database Migration:** The installer immediately migrates all settings from this `.ini` file into the main application database (`pi_backend.db`). The `.ini` file is then removed.
3.  **Ongoing Management:** All subsequent configuration changes (API keys, polling intervals, etc.) are managed directly through the web dashboard, providing a central and secure way to control the application.

## 📄 License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.
