# ==============================================================================
# Configuration Loader for pi_backend
# Version: 2.2.0 (Class-Based Refactor)
# ==============================================================================
# This module provides a robust, class-based mechanism for loading and
# accessing configuration settings from .ini files.
#
# Changelog:
# - v2.1.0: Initial functional version.
# - v2.2.0: CRITICAL FIX: Refactored the module from a functional approach to a
#           class-based one. The main application (`app.py`) was attempting
#           to instantiate a `ConfigLoader` class, which did not exist in the
#           previous version, causing a fatal `ImportError`. This new class
#           structure aligns with the application's design and resolves the
#           crash.
# ==============================================================================

import configparser
import logging

class ConfigLoader:
    """
    A class to load and manage configuration from an INI file.
    """
    def __init__(self, config_path=None):
        """
        Initializes the ConfigLoader and loads the configuration from the given path.

        Args:
            config_path (str): The full path to the configuration .ini file.
        """
        if not config_path:
            raise ValueError("Configuration file path cannot be None.")
            
        self.config_path = config_path
        self.config = configparser.ConfigParser()
        
        try:
            # read() returns a list of files that were successfully read.
            # If the list is empty, the file was not found or was unreadable.
            if not self.config.read(self.config_path):
                logging.error(f"Configuration file not found or is empty: {self.config_path}")
                # We don't raise an exception here to allow the app to handle
                # the missing config gracefully, but we log a severe error.
        except configparser.Error as e:
            logging.error(f"Failed to parse configuration file {self.config_path}: {e}")
            # Reset the config object on error to ensure a clean state.
            self.config = configparser.ConfigParser()

    def get(self, section, key, fallback=None):
        """
        Retrieves a setting from the configuration.

        Args:
            section (str): The section of the .ini file (e.g., 'Database').
            key (str): The key within the section.
            fallback (any, optional): The value to return if the key is not found.
                                     Defaults to None.

        Returns:
            str: The value of the setting, or the fallback value.
        """
        return self.config.get(section, key, fallback=fallback)

    def getint(self, section, key, fallback=None):
        """
        Retrieves a setting as an integer.
        """
        return self.config.getint(section, key, fallback=fallback)

    def getboolean(self, section, key, fallback=None):
        """
        Retrieves a setting as a boolean.
        """
        return self.config.getboolean(section, key, fallback=fallback)

    def getfloat(self, section, key, fallback=None):
        """
        Retrieves a setting as a float.
        """
        return self.config.getfloat(section, key, fallback=fallback)

    def has_section(self, section):
        """
        Checks if a given section exists in the configuration.
        """
        return self.config.has_section(section)

    def has_option(self, section, option):
        """
        Checks if a given option exists within a section.
        """
        return self.config.has_option(section, option)

