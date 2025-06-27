# ==============================================================================
# Database Configuration Manager for pi_backend
# Version: 1.0.0 (Initial Database-Backed Configuration)
# ==============================================================================
# This module provides a class-based mechanism for loading and accessing
# configuration settings stored directly in the application's SQLite database.
# It replaces the previous file-based config loader.
# ==============================================================================

import logging
import json # For handling complex types if needed, though values are stored as TEXT

class DBConfigManager:
    """
    A class to load and manage configuration from the application's database.
    """
    def __init__(self, db_manager):
        """
        Initializes the DBConfigManager.

        Args:
            db_manager (DatabaseManager): An instance of the application's DatabaseManager.
        """
        if not db_manager:
            raise ValueError("DatabaseManager instance cannot be None for DBConfigManager.")
            
        self.db_manager = db_manager
        self._cache = {} # Simple in-memory cache for loaded settings
        self._load_all_settings_to_cache()
        logging.info("DBConfigManager initialized and settings loaded into cache.")

    def _load_all_settings_to_cache(self):
        """Loads all configuration settings from the database into the in-memory cache."""
        self._cache = self.db_manager.get_all_config_values()
        logging.debug(f"Loaded {len(self._cache)} config entries from DB into cache.")

    def get(self, section, key, fallback=None):
        """
        Retrieves a setting from the configuration.
        Keys are stored in the database as 'section_key' (e.g., 'API_Weather_API_URL').
        """
        full_key = f"{section}_{key}"
        value = self._cache.get(full_key)

        if value is None:
            # If not in cache, try fetching from DB (might be a fresh start or cache invalidation needed)
            value = self.db_manager.get_config_value(full_key, fallback=None)
            if value is not None:
                self._cache[full_key] = value # Update cache
                logging.debug(f"Config '{full_key}' fetched from DB and cached.")
            else:
                logging.debug(f"Config key '{full_key}' not found in DB or cache. Using fallback.")
                return fallback # Return provided fallback if not found

        # Attempt to convert known types if necessary (e.g., boolean, int, float)
        # This part assumes simple string storage; more complex parsing can be added.
        if isinstance(fallback, bool) and str(value).lower() in ('true', 'false'):
            return str(value).lower() == 'true'
        if isinstance(fallback, int):
            try: return int(value)
            except (ValueError, TypeError): pass
        if isinstance(fallback, float):
            try: return float(value)
            except (ValueError, TypeError): pass
        
        return value

    def set(self, section, key, value):
        """
        Sets a configuration value in the database and updates the cache.
        """
        full_key = f"{section}_{key}"
        if self.db_manager.set_config_value(full_key, value):
            self._cache[full_key] = str(value) # Update cache with string representation
            logging.info(f"Config '{full_key}' set to '{value}' in DB and cache.")
            return True
        return False

    # Helper methods for type-specific retrieval (similar to configparser)
    def getint(self, section, key, fallback=None):
        value = self.get(section, key)
        try:
            return int(value)
        except (ValueError, TypeError):
            return fallback

    def getboolean(self, section, key, fallback=None):
        value = self.get(section, key)
        if isinstance(value, str):
            return value.lower() in ('true', '1', 't', 'y', 'yes', 'on')
        return bool(value) if value is not None else fallback

    def getfloat(self, section, key, fallback=None):
        value = self.get(section, key)
        try:
            return float(value)
        except (ValueError, TypeError):
            return fallback

    def has_key(self, section, key):
        """Checks if a given configuration key exists."""
        full_key = f"{section}_{key}"
        return full_key in self._cache or self.db_manager.get_config_value(full_key) is not None

    def refresh_cache(self):
        """Forces a reload of all settings from the database into the cache."""
        self._load_all_settings_to_cache()
        logging.info("DBConfigManager cache refreshed from database.")

