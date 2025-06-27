# ==============================================================================
# Database Manager for pi_backend
# Version: 6.1.0 (Database-Backed Configuration)
# ==============================================================================
# This module provides a high-level, class-based interface for all database
# operations, including initialization, data insertion, and querying.
#
# Changelog:
# - v6.0.0: Unified API Key Management.
# - v6.0.1: Implemented Argon2 password hashing.
# - v6.1.0: Added a 'configuration' table to the database schema. Introduced
#           methods for storing, retrieving, and listing configuration values
#           directly in the database. This allows all application settings
#           to be centrally managed and persisted.
# ==============================================================================

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
            logging.warning(f"User '{username}' not found for password update.")
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
            "config_entry_count": "SELECT COUNT(*) FROM configuration"
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

    def get_data_by_type(self, data_type, limit=100):
        """Retrieves historical data for a specific type."""
        records = self.execute_query(
            "SELECT * FROM sensor_data WHERE type = ? ORDER BY timestamp DESC LIMIT ?",
            (data_type, limit), fetch='all'
        )

        results = []
        if records:
            for record in records:
                row_dict = dict(record)
                if row_dict.get('metadata'):
                    try:
                        row_dict['metadata'] = json.loads(row_dict['metadata'])
                    except (json.JSONDecodeError, TypeError):
                        pass # Leave metadata as is if it's not valid JSON
                results.append(row_dict)
        return results

    def prune_sensor_data(self, retention_days=90):
        """Deletes sensor data older than a specified retention period."""
        threshold = datetime.now() - timedelta(days=retention_days)
        cursor = self.execute_query("DELETE FROM sensor_data WHERE timestamp < ?", (threshold.isoformat(),))
        rows = cursor.rowcount if cursor else 0
        if cursor:
             return rows, True, f"Successfully pruned {rows} entries older than {retention_days} days."
        else:
            return 0, False, "Failed to execute prune operation."
