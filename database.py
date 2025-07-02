#
# File: database.py
# Version: 6.1.3 (UPS Metrics & Events)
#
# Description: This module provides a high-level, class-based interface for all database
#              operations, including initialization, data insertion, and querying.
#
# Changelog:
# - v6.0.0: Unified API Key Management.
# - v6.0.1: Implemented Argon2 password hashing.
# - v6.1.0: Added a 'configuration' table to the database schema. Introduced
#           methods for storing, retrieving, and listing configuration values
#           directly in the database. This allows all application settings
#           to be centrally managed and persisted.
# - v6.1.1: Added new tables for astronomy data, satellite passes, space weather,
#           and community POIs with upserting logic.
# - v6.1.2: Added GOOGLE_PLACES_API_KEY to the API key management.
# - v6.1.3: Added dedicated tables for UPS metrics and events (`ups_metrics`, `ups_events`).
#           Implemented `add_ups_metric`, `add_ups_event`, and `get_latest_ups_metric`.
#
import sqlite3
import logging
from threading import Lock
from datetime import datetime, timedelta
import json
import os
import secrets

# Import Argon2 hasher
try:
    from argon2 import PasswordHasher
    from argon2.exceptions import VerifyMismatchError
    PH = PasswordHasher()
    ARGON2_AVAILABLE = True
    logging.info("DatabaseManager: Argon2 PasswordHasher initialized.")
except ImportError:
    ARGON2_AVAILABLE = False
    logging.critical("DatabaseManager: CRITICAL ERROR: 'argon2-cffi' not found. Password hashing will be insecure.")
    # Fallback to a dummy hasher for basic functionality, but WARN severely
    class DummyPasswordHasher:
        def hash(self, password):
            logging.warning("DatabaseManager: Using insecure dummy hashing (Argon2 not available).")
            return password # Return plaintext if Argon2 isn't available - DANGER!
        def verify(self, hashed_password, password):
            logging.warning("DatabaseManager: Using insecure dummy verification (Argon2 not available).")
            return hashed_password == password # Direct comparison - DANGER!
    PH = DummyPasswordHasher()
except Exception as e:
    ARGON2_AVAILABLE = False
    logging.critical(f"DatabaseManager: CRITICAL ERROR: Failed to initialize Argon2 PasswordHasher: {e}")
    PH = DummyPasswordHasher()


class DatabaseManager:
    """
    Manages all database interactions for the pi_backend application.
    This class is thread-safe.
    """
    def __init__(self, database_path):
        if not database_path:
            raise ValueError("Database path cannot be None.")

        self.database_path = database_path
        self.connection = None
        self.lock = Lock()
        self.initialize_database()

    def _get_connection(self):
        """Establishes and returns a database connection."""
        try:
            # check_same_thread=False is important for multi-threaded Flask/Gunicorn environments
            self.connection = sqlite3.connect(self.database_path, check_same_thread=False)
            self.connection.row_factory = sqlite3.Row
            return self.connection
        except sqlite3.Error as e:
            logging.error(f"Error connecting to database: {e}")
            return None

    def _close_connection(self):
        """Closes the current database connection."""
        if self.connection:
            self.connection.close()
            self.connection = None

    def execute_query(self, query, params=(), fetch=None):
        """Executes a given SQL query in a thread-safe manner."""
        with self.lock:
            conn = None
            try:
                conn = self._get_connection()
                if conn is None: return None
                cursor = conn.cursor()
                cursor.execute(query, params)

                if fetch == 'one':
                    return cursor.fetchone()
                elif fetch == 'all':
                    return cursor.fetchall()
                else:
                    conn.commit()
                    return cursor
            except sqlite3.Error as e:
                logging.error(f"Database query failed: {e}\nQuery: {query}\nParams: {params}")
                return None
            finally:
                if conn:
                    self._close_connection()

    def initialize_database(self):
        """Initializes the database by creating all necessary tables."""
        logging.info("Initializing database tables...")
        table_schemas = {
            "users": """
                CREATE TABLE IF NOT EXISTS [users] (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    username TEXT UNIQUE NOT NULL,
                    password_hash TEXT NOT NULL,
                    role TEXT NOT NULL CHECK(role IN ('admin', 'user')),
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
            """,
            "api_keys": """
                CREATE TABLE IF NOT EXISTS [api_keys] (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    key_name TEXT UNIQUE NOT NULL,
                    key_value TEXT NOT NULL,
                    is_internal BOOLEAN DEFAULT 1 NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
            """,
            "sensor_data": """
                CREATE TABLE IF NOT EXISTS [sensor_data] (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    source TEXT NOT NULL, type TEXT NOT NULL,
                    value REAL, unit TEXT, metadata TEXT
                );
            """,
            "location_data": """
                CREATE TABLE IF NOT EXISTS [location_data] (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    latitude REAL NOT NULL, longitude REAL NOT NULL,
                    altitude REAL, source TEXT NOT NULL, metadata TEXT
                );
            """,
             "system_logs": """
                CREATE TABLE IF NOT EXISTS [system_logs] (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    level TEXT NOT NULL, source TEXT NOT NULL,
                    message TEXT NOT NULL, details TEXT
                );
            """,
            "configuration": """
                CREATE TABLE IF NOT EXISTS [configuration] (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    key TEXT UNIQUE NOT NULL,
                    value TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
            """,
            # NEW TABLES FOR POLLED DATA
            "astronomy_data": """
                CREATE TABLE IF NOT EXISTS [astronomy_data] (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    data_type TEXT NOT NULL, -- e.g., 'sun_moon_events', 'planet_visibility', 'meteor_showers'
                    location_lat REAL,
                    location_lon REAL,
                    data_json TEXT NOT NULL, -- Full JSON blob of the data
                    UNIQUE(timestamp, data_type, location_lat, location_lon) ON CONFLICT REPLACE
                );
            """,
            "satellite_passes": """
                CREATE TABLE IF NOT EXISTS [satellite_passes] (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL, -- When the pass data was recorded/fetched
                    satellite_norad_id INTEGER NOT NULL,
                    satellite_name TEXT NOT NULL,
                    pass_start_utc TEXT NOT NULL, -- Start time of this specific pass
                    pass_end_utc TEXT NOT NULL, -- End time of this specific pass
                    pass_details_json TEXT NOT NULL, -- Full JSON blob for this pass
                    UNIQUE(satellite_norad_id, pass_start_utc) ON CONFLICT REPLACE
                );
            """,
            "space_weather_data": """
                CREATE TABLE IF NOT EXISTS [space_weather_data] (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL, -- When the data was recorded/fetched
                    report_time_utc TEXT, -- Official time of the report if available
                    kp_index REAL,
                    solar_flare_level TEXT,
                    geomagnetic_storm_level TEXT,
                    data_json TEXT NOT NULL, -- Full JSON blob of the data
                    UNIQUE(timestamp, report_time_utc) ON CONFLICT REPLACE
                );
            """,
            "community_pois": """
                CREATE TABLE IF NOT EXISTS [community_pois] (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    osm_id INTEGER UNIQUE NOT NULL, -- OpenStreetMap ID for unique identification
                    timestamp TEXT NOT NULL, -- When the POI data was recorded/fetched
                    poi_type TEXT NOT NULL, -- e.g., 'hospital', 'police', 'pfas_site'
                    name TEXT,
                    latitude REAL NOT NULL,
                    longitude REAL NOT NULL,
                    address TEXT,
                    phone TEXT,
                    website TEXT,
                    details_json TEXT NOT NULL -- Full JSON blob of all details from API
                );
            """,
            # NEW TABLES FOR UPS DATA
            "ups_metrics": """
                CREATE TABLE IF NOT EXISTS [ups_metrics] (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL UNIQUE,
                    bus_voltage_V REAL,
                    shunt_voltage_mV REAL,
                    battery_voltage_V REAL,
                    current_mA REAL,
                    power_mW REAL,
                    battery_percentage REAL,
                    remaining_mah REAL,
                    status_text TEXT
                );
            """,
            "ups_events": """
                CREATE TABLE IF NOT EXISTS [ups_events] (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    event_type TEXT NOT NULL, -- e.g., 'STATUS_CHANGE', 'BATTERY_FULL', 'BATTERY_EMPTY'
                    details_json TEXT -- JSON blob of event details
                );
            """
        }
        for table, schema in table_schemas.items():
            self.execute_query(schema)
        logging.info("Database initialization complete.")

    # --- Configuration Management Methods (New) ---
    def set_config_value(self, key, value):
        """
        Sets or updates a configuration value in the database.
        Values are stored as TEXT. Complex types (lists/dicts) should be JSON-serialized.
        """
        try:
            # Check if key exists
            existing = self.execute_query("SELECT id FROM configuration WHERE key = ?", (key,), fetch='one')
            if existing:
                self.execute_query(
                    "UPDATE configuration SET value = ?, updated_at = CURRENT_TIMESTAMP WHERE key = ?",
                    (str(value), key) # Ensure value is stored as string
                )
                logging.debug(f"Config key '{key}' updated.")
            else:
                self.execute_query(
                    "INSERT INTO configuration (key, value) VALUES (?, ?)",
                    (key, str(value)) # Ensure value is stored as string
                )
                logging.debug(f"Config key '{key}' inserted.")
            return True
        except sqlite3.Error as e:
            logging.error(f"Failed to set config value for key '{key}': {e}")
            return False

    def get_config_value(self, key, fallback=None):
        """
        Retrieves a configuration value by its key from the database.
        Returns the raw string value.
        """
        record = self.execute_query(
            "SELECT value FROM configuration WHERE key = ?",
            (key,), fetch='one'
        )
        if record:
            return record['value']
        return fallback

    def get_all_config_values(self):
        """Retrieves all configuration key-value pairs from the database."""
        records = self.execute_query(
            "SELECT key, value FROM configuration ORDER BY key",
            fetch='all'
        )
        return {row['key']: row['value'] for row in records} if records else {}

    # --- User Management Methods ---
    def add_user(self, username, password, role):
        """Adds a new user to the database with a hashed password."""
        if not ARGON2_AVAILABLE:
            logging.error("Argon2 not available. Cannot add user securely.")
            return False

        try:
            hashed_password = PH.hash(password)
            self.execute_query(
                "INSERT INTO users (username, password_hash, role) VALUES (?, ?, ?)",
                (username, hashed_password, role)
            )
            logging.info(f"User '{username}' added successfully (password hashed).")
            return True
        except sqlite3.IntegrityError:
            logging.warning(f"Attempted to add existing user: '{username}'.")
            return False
        except Exception as e:
            logging.error(f"Error hashing/adding user '{username}': {e}")
            return False


    def get_user(self, username):
        """Retrieves user details by username (excluding password hash)."""
        user_record = self.execute_query(
            "SELECT id, username, role, created_at FROM users WHERE username = ?",
            (username,), fetch='one'
        )
        return dict(user_record) if user_record else None

    def get_user_with_hash(self, username):
        """Retrieves user details including password hash for internal verification."""
        user_record = self.execute_query(
            "SELECT id, username, password_hash, role, created_at FROM users WHERE username = ?",
            (username,), fetch='one'
        )
        return dict(user_record) if user_record else None

    def list_all_users(self):
        """Retrieves a list of all users (excluding password hashes)."""
        records = self.execute_query(
            "SELECT id, username, role, created_at FROM users ORDER BY username",
            fetch='all'
        )
        return [dict(row) for row in records] if records else []

    def update_user_password(self, username, new_password):
        """Updates a user's password with a new hash."""
        if not ARGON2_AVAILABLE:
            logging.error("Argon2 not available. Cannot update password securely.")
            return False
        try:
            hashed_password = PH.hash(new_password)
            cursor = self.execute_query(
                "UPDATE users SET password_hash = ? WHERE username = ?",
                (hashed_password, username)
            )
            if cursor and cursor.rowcount > 0:
                logging.info(f"Password for user '{username}' updated successfully (re-hashed).")
                return True
            logging.warning(f"User '{username}' not found for update.")
            return False
        except Exception as e:
            logging.error(f"Error hashing/updating password for user '{username}': {e}")
            return False

    def update_user_role(self, username, new_role):
        """Updates a user's role."""
        cursor = self.execute_query(
            "UPDATE users SET role = ? WHERE username = ?",
            (new_role, username)
        )
        if cursor and cursor.rowcount > 0:
            logging.info(f"Role for user '{username}' updated to '{new_role}'.")
            return True
        return False

    def delete_user(self, username):
        """Deletes a user from the database."""
        # Prevent deletion of the last admin user
        if username.lower() == 'admin':
            admin_count_result = self.execute_query("SELECT COUNT(*) FROM users WHERE role = 'admin'", fetch='one')
            if admin_count_result and admin_count_result[0] <= 1:
                logging.error("Cannot delete the last admin user.")
                return False

        cursor = self.execute_query("DELETE FROM users WHERE username = ?", (username,))
        return cursor and cursor.rowcount > 0

    def check_if_default_credentials_exist(self):
        """Checks if any user exists, implying initial admin setup might be needed if none exist."""
        user_count_record = self.execute_query("SELECT COUNT(*) FROM users", fetch='one')
        return user_count_record[0] == 0 if user_count_record else True # True if no users exist


    # --- Unified API Key Management Methods ---
    def add_api_key(self, key_name, key_value=None):
        """
        Adds a new API key to the database. If key_value is None, it's generated
        as an internal key. Otherwise, it's stored as an external key.
        """
        is_internal = key_value is None
        if is_internal:
            key_value = secrets.token_hex(24)

        try:
            self.execute_query(
                "INSERT INTO api_keys (key_name, key_value, is_internal) VALUES (?, ?, ?)",
                (key_name, key_value, is_internal)
            )
            logging.info(f"API key '{key_name}' added successfully.")
            return True, f"API key '{key_name}' added.", key_value if is_internal else None
        except sqlite3.IntegrityError:
            logging.warning(f"Attempted to add existing API key name: '{key_name}'.")
            return False, "API key name already exists.", None

    def update_api_key(self, key_name, new_key_value):
        """Updates the value of an existing API key."""
        cursor = self.execute_query(
            "UPDATE api_keys SET key_value = ? WHERE key_name = ?",
            (new_key_value, key_name)
        )
        if cursor and cursor.rowcount > 0:
            logging.info(f"API key '{key_name}' updated successfully.")
            return True
        logging.warning(f"API key '{key_name}' not found for update.")
        return False

    def get_key_value_by_name(self, key_name):
        """Retrieves an API key's value by its name. Used by internal services."""
        record = self.execute_query(
            "SELECT key_value FROM api_keys WHERE key_name = ?",
            (key_name,), fetch='one'
        )
        return record['key_value'] if record else None

    def get_api_key_for_auth(self, key_value):
        """
        Retrieves API key details by its value for authenticating inbound requests.
        IMPORTANT: This only validates against internal keys.
        """
        key_record = self.execute_query(
            "SELECT id, key_name, created_at FROM api_keys WHERE key_value = ? AND is_internal = 1",
            (key_value,), fetch='one'
        )
        return dict(key_record) if key_record else None

    def list_api_keys(self):
        """Retrieves a list of all API keys (values are omitted for security)."""
        records = self.execute_query(
            "SELECT id, key_name, is_internal, created_at FROM api_keys ORDER BY key_name",
            fetch='all'
        )
        return [dict(row) for row in records] if records else []

    def delete_api_key(self, key_name):
        """Deletes an API key by its name."""
        cursor = self.execute_query("DELETE FROM api_keys WHERE key_name = ?", (key_name,))
        return cursor and cursor.rowcount > 0

    # --- Database Statistics ---
    def get_db_stats(self):
        """Returns statistics about the database."""
        stats_queries = {
            "user_count": "SELECT COUNT(*) FROM users",
            "sensor_data_count": "SELECT COUNT(*) FROM sensor_data",
            "location_data_count": "SELECT COUNT(*) FROM location_data",
            "api_keys_count": "SELECT COUNT(*) FROM api_keys",
            "system_logs_count": "SELECT COUNT(*) FROM system_logs",
            "config_entry_count": "SELECT COUNT(*) FROM configuration",
            "astronomy_data_count": "SELECT COUNT(*) FROM astronomy_data",
            "satellite_passes_count": "SELECT COUNT(*) FROM satellite_passes",
            "space_weather_data_count": "SELECT COUNT(*) FROM space_weather_data",
            "community_pois_count": "SELECT COUNT(*) FROM community_pois",
            "ups_metrics_count": "SELECT COUNT(*) FROM ups_metrics", # New
            "ups_events_count": "SELECT COUNT(*) FROM ups_events" # New
        }

        results = {}
        for key, query in stats_queries.items():
            count = self.execute_query(query, fetch='one')
            results[key] = count[0] if count else 0

        try:
            db_size_bytes = os.path.getsize(self.database_path)
            results["db_size_mb"] = round(db_size_bytes / (1024 * 1024), 2)
        except OSError:
            results["db_size_mb"] = 0

        results["db_path"] = self.database_path
        return results

    # --- Data Storage and Pruning ---
    def add_data(self, data_type, value, unit=None, source="Unknown", timestamp=None, metadata=None):
        """Adds generic sensor/polled data to the database."""
        if timestamp is None:
            timestamp = datetime.now()

        self.execute_query(
            "INSERT INTO sensor_data (timestamp, source, type, value, unit, metadata) VALUES (?, ?, ?, ?, ?, ?)",
            (timestamp.isoformat(), source, data_type, value, unit, json.dumps(metadata) if metadata else None)
        )
        return True

    def prune_sensor_data(self, retention_days=90):
        """Deletes sensor data older than a specified retention period."""
        threshold = datetime.now() - timedelta(days=retention_days)
        cursor = self.execute_query("DELETE FROM sensor_data WHERE timestamp < ?", (threshold.isoformat(),))
        rows = cursor.rowcount if cursor else 0
        if cursor:
             return rows, True, f"Successfully pruned {rows} entries older than {retention_days} days."
        else:
            return 0, False, "Failed to execute prune operation."

    # --- NEW: Specific data storage and retrieval methods ---

    def add_astronomy_data(self, data_type, location_lat, location_lon, data_json, timestamp=None):
        """Adds or updates astronomy data (sun/moon events, planet visibility, meteor showers)."""
        if timestamp is None:
            timestamp = datetime.now()
        self.execute_query(
            """
            INSERT INTO astronomy_data (timestamp, data_type, location_lat, location_lon, data_json)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(timestamp, data_type, location_lat, location_lon) DO UPDATE SET
                data_json = excluded.data_json;
            """,
            (timestamp.isoformat(), data_type, location_lat, location_lon, json.dumps(data_json))
        )
        return True

    def get_astronomy_data(self, data_type, start_time=None, end_time=None, limit=1):
        """Retrieves astronomy data for a given type and time range."""
        query = "SELECT * FROM astronomy_data WHERE data_type = ?"
        params = [data_type]
        if start_time:
            query += " AND timestamp >= ?"
            params.append(start_time.isoformat())
        if end_time:
            query += " AND timestamp <= ?"
            params.append(end_time.isoformat())
        query += " ORDER BY timestamp DESC LIMIT ?"
        params.append(limit)
        records = self.execute_query(query, params, fetch='all')
        if records:
            return [json.loads(row['data_json']) for row in records]
        return []

    def add_satellite_pass(self, satellite_norad_id, satellite_name, pass_start_utc, pass_end_utc, pass_details_json, timestamp=None):
        """Adds or updates a satellite pass record."""
        if timestamp is None:
            timestamp = datetime.now()
        self.execute_query(
            """
            INSERT INTO satellite_passes (timestamp, satellite_norad_id, satellite_name, pass_start_utc, pass_end_utc, pass_details_json)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(satellite_norad_id, pass_start_utc) DO UPDATE SET
                satellite_name = excluded.satellite_name,
                pass_end_utc = excluded.pass_end_utc,
                pass_details_json = excluded.pass_details_json,
                timestamp = excluded.timestamp;
            """,
            (timestamp.isoformat(), satellite_norad_id, satellite_name, pass_start_utc, pass_end_utc, json.dumps(pass_details_json))
        )
        return True

    def get_satellite_passes(self, satellite_norad_id=None, start_time=None, end_time=None, limit=100):
        """Retrieves satellite passes based on criteria."""
        query = "SELECT * FROM satellite_passes WHERE 1=1"
        params = []
        if satellite_norad_id:
            query += " AND satellite_norad_id = ?"
            params.append(satellite_norad_id)
        if start_time:
            query += " AND pass_start_utc >= ?"
            params.append(start_time.isoformat())
        if end_time:
            query += " AND pass_end_utc <= ?"
            params.append(end_time.isoformat())
        query += " ORDER BY pass_start_utc ASC LIMIT ?"
        params.append(limit)
        records = self.execute_query(query, params, fetch='all')
        if records:
            return [json.loads(row['pass_details_json']) for row in records]
        return []

    def add_space_weather_data(self, report_time_utc, kp_index, solar_flare_level, geomagnetic_storm_level, data_json, timestamp=None):
        """Adds or updates space weather data."""
        if timestamp is None:
            timestamp = datetime.now()
        self.execute_query(
            """
            INSERT INTO space_weather_data (timestamp, report_time_utc, kp_index, solar_flare_level, geomagnetic_storm_level, data_json)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(timestamp, report_time_utc) DO UPDATE SET
                kp_index = excluded.kp_index,
                solar_flare_level = excluded.solar_flare_level,
                geomagnetic_storm_level = excluded.geomagnetic_storm_level,
                data_json = excluded.data_json;
            """,
            (timestamp.isoformat(), report_time_utc, kp_index, solar_flare_level, geomagnetic_storm_level, json.dumps(data_json))
        )
        return True

    def get_latest_space_weather(self):
        """Retrieves the latest space weather report."""
        record = self.execute_query(
            "SELECT * FROM space_weather_data ORDER BY timestamp DESC LIMIT 1",
            fetch='one'
        )
        if record:
            return json.loads(record['data_json'])
        return None

    def add_community_poi(self, osm_id, poi_type, name, latitude, longitude, address=None, phone=None, website=None, details_json=None, timestamp=None):
        """Adds or updates a community POI."""
        if timestamp is None:
            timestamp = datetime.now()
        self.execute_query(
            """
            INSERT INTO community_pois (osm_id, timestamp, poi_type, name, latitude, longitude, address, phone, website, details_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(osm_id) DO UPDATE SET
                timestamp = excluded.timestamp,
                poi_type = excluded.poi_type,
                name = excluded.name,
                latitude = excluded.latitude,
                longitude = excluded.longitude,
                address = excluded.address,
                phone = excluded.phone,
                website = excluded.website,
                details_json = excluded.details_json;
            """,
            (osm_id, timestamp.isoformat(), poi_type, name, latitude, longitude, address, phone, website, json.dumps(details_json) if details_json else None)
        )
        return True

    def get_community_pois(self, poi_type=None, latitude=None, longitude=None, radius_km=None, limit=100):
        """Retrieves community POIs, optionally filtered by type and proximity."""
        query = "SELECT * FROM community_pois WHERE 1=1"
        params = []
        if poi_type:
            query += " AND poi_type = ?"
            params.append(poi_type)
        query += " ORDER BY timestamp DESC LIMIT ?"
        params.append(limit)

        records = self.execute_query(query, params, fetch='all')
        
        # Implement proximity filtering in Python for simplicity, if radius_km is provided
        # This is not optimized for large datasets and should be done in SQL with spatial extensions for performance
        results = []
        if records:
            for row in records:
                poi = dict(row)
                if latitude is not None and longitude is not None and radius_km is not None:
                    try:
                        from geopy import distance
                        poi_coords = (poi['latitude'], poi['longitude'])
                        origin_coords = (latitude, longitude)
                        dist = distance.distance(origin_coords, poi_coords).km
                        if dist <= radius_km:
                            poi['distance_km'] = round(dist, 2)
                            if poi['details_json']:
                                poi['details_json'] = json.loads(poi['details_json'])
                            results.append(poi)
                    except ImportError:
                        logging.warning("geopy not installed, cannot perform proximity filtering for POIs.")
                        if poi['details_json']:
                            poi['details_json'] = json.loads(poi['details_json'])
                        results.append(poi) # Add without filtering if geopy isn't available
                else:
                    if poi['details_json']:
                        poi['details_json'] = json.loads(poi['details_json'])
                    results.append(poi)
        return results

    # --- UPS Data Methods (New) ---
    def add_ups_metric(self, timestamp, bus_voltage_V, shunt_voltage_mV, battery_voltage_V, current_mA, power_mW, battery_percentage, remaining_mah, status_text):
        """Adds a new UPS metric reading to the database."""
        self.execute_query(
            """
            INSERT INTO ups_metrics (timestamp, bus_voltage_V, shunt_voltage_mV, battery_voltage_V, current_mA, power_mW, battery_percentage, remaining_mah, status_text)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(timestamp) DO UPDATE SET
                bus_voltage_V = excluded.bus_voltage_V,
                shunt_voltage_mV = excluded.shunt_voltage_mV,
                battery_voltage_V = excluded.battery_voltage_V,
                current_mA = excluded.current_mA,
                power_mW = excluded.power_mW,
                battery_percentage = excluded.battery_percentage,
                remaining_mah = excluded.remaining_mah,
                status_text = excluded.status_text;
            """,
            (timestamp, bus_voltage_V, shunt_voltage_mV, battery_voltage_V, current_mA, power_mW, battery_percentage, remaining_mah, status_text)
        )
        return True

    def add_ups_event(self, timestamp, event_type, details=None):
        """Adds a new UPS event to the database."""
        self.execute_query(
            "INSERT INTO ups_events (timestamp, event_type, details_json) VALUES (?, ?, ?)",
            (timestamp, event_type, json.dumps(details) if details else None)
        )
        return True

    def get_latest_ups_metric(self):
        """Retrieves the most recent UPS metric reading."""
        record = self.execute_query(
            "SELECT * FROM ups_metrics ORDER BY timestamp DESC LIMIT 1",
            fetch='one'
        )
        return dict(record) if record else None

