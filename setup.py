#!/usr/bin/env python3
# ==============================================================================
# pi_backend_py_installer - The Definitive Installer & Service Manager
# Version: 2.0.10 (Enhanced Gunicorn Debugging)
#
# Description:
# This script is a full Python rewrite of the original `pi_backend` bash
# installer. It provides an idempotent workflow for initial installation,
# updates, and system management.
#
# Changelog (v2.0.10):
# - FIX: Enhanced `test_api` function to provide more specific debugging guidance
#   if the API test fails, including checking the `pi_backend_api.service` status
#   and its journal logs, which is crucial for diagnosing "Service Unavailable" errors.
#   Also explicitly checks for Gunicorn process.
# - FEAT: Introduced `self.static_web_root` to separate web-accessible static
#   files (like index.html) from backend Python code for improved security.
# - REFACTOR: Modified `deploy_and_manage_files` to copy `index.html` to
#   `self.static_web_root` and ensure Python files remain in `self.install_path`.
# - REFACTOR: Updated `configure_apache` to set `DocumentRoot` to `self.static_web_root`,
#   add `DirectoryIndex index.html`, and explicitly deny direct web access to
#   `self.install_path` (where Python files reside).
# - FIX: Corrected `NameError` in `download_skyfield_data`.
# - FEAT: Modified `run_update_and_patch` to always perform file deployment and
#   service reinstallation when invoked, ensuring services are refreshed
#   with every update check, even if no file differences are automatically detected.
#
# Author: Gemini
# ==============================================================================

import os
import sys
import subprocess
import configparser
import hashlib
import re
import requests
import time
import getpass
import shutil
import sqlite3
import textwrap
from datetime import datetime

# --- Style & Formatting (Updated for Readability) ---
C_GREEN = '\033[0;32m'
C_YELLOW = '\033[1;33m'
C_RED = '\033[0;31m'
C_CYAN = '\033[0;36m'
C_NC = '\033[0m' # No Color
C_BOLD = '\033[1m'

class PiBackendManager:
    """
    Manages the installation, configuration, and maintenance of the pi_backend application.
    """
    def __init__(self):
        self.script_version = "2.0.10" # Updated version for this release
        self.source_dir = os.path.dirname(os.path.abspath(__file__))
        self.current_user = getpass.getuser()

        # --- Dynamic paths (loaded from config) - MOVED TO TOP to prevent AttributeError ---
        self.install_path = "/var/www/pi_backend" # Backend Python code location
        self.static_web_root = "/var/www/pi_backend_static" # Publicly accessible web files (index.html)
        self.config_path = "/etc/pi_backend"
        self.db_path = "/var/lib/pi_backend/pi_backend.db"

        # --- Static Paths & Configuration ---
        self.pi_backend_home_dir = os.path.expanduser("~/.pi_backend")
        self.setup_complete_flag = os.path.join(self.pi_backend_home_dir, ".setup_complete")
        self.master_config_path = "/etc/pi_backend" # Still needed for loading config
        self.source_config_file = os.path.join(self.source_dir, "setup_config.ini")
        self.modules_subdir = "modules"
        self.gps_device = "/dev/serial0"
        self.log_dir = "/var/log/pi_backend"
        self.templates_dir = self.source_dir
        self.skyfield_data_dir = "/var/lib/pi_backend/skyfield-data"
        
        # External Installer Script
        self.a7670e_installer_source_name = "setup_a7670e_gps.sh"
        self.a7670e_installer_system_path = f"/usr/local/bin/{self.a7670e_installer_source_name}"
        
        # Service Names
        self.api_service_name = "pi_backend_api.service"
        self.poller_service_name = "pi_backend_poller.service"
        self.gps_init_service_name = "a7670e-gps-init.service"
        # Removed ups_daemon_service_name from core_services
        self.core_services = [self.api_service_name, self.poller_service_name, "gpsd", "chrony", "apache2"]


        # Apache Configs
        self.apache_http_conf_file = "/etc/apache2/sites-available/pi-backend-http.conf"
        self.apache_https_conf_file = "/etc/apache2/sites-available/pi-backend-https.conf"
        self.apache_websdr_conf_file = "/etc/apache2/sites-available/pi-backend-websdr.conf"

        # State
        self.apache_domain = ""
        self.patch_needed = False

        self._load_master_config()

    # --- UI & Helper Functions ---
    def _run_command(self, command, capture=False, as_sudo=True, check=False, shell=False):
        """Runs a shell command."""
        if as_sudo and os.geteuid() != 0:
            cmd_list = ['sudo'] + command
        else:
            cmd_list = command

        try:
            # For non-capture, we let the output stream directly.
            if not capture:
                return subprocess.run(cmd_list, check=check, text=True, errors='ignore')

            process = subprocess.run(
                cmd_list if not shell else " ".join(cmd_list),
                capture_output=capture,
                text=True,
                check=check,
                errors='ignore',
                shell=shell
            )
            return process
        except FileNotFoundError:
            self._echo_error(f"Command not found: {cmd_list[0]}")
            return None
        except subprocess.CalledProcessError as e:
            self._echo_error(f"Command failed: {' '.join(cmd_list)}")
            if e.stderr: self._echo_error(f"Stderr: {e.stderr.strip()}")
            if e.stdout: self._echo_error(f"Stdout: {e.stdout.strip()}")
            return e
            
    def _read_sudo_file(self, file_path):
        """Reads a file that requires sudo permissions."""
        result = self._run_command(['cat', file_path], capture=True, as_sudo=True)
        return result.stdout if result and result.returncode == 0 else None

    def _write_sudo_file(self, file_path, content):
        """Writes content to a file that requires sudo permissions."""
        temp_path = f"/tmp/pi_backend_temp_{os.getpid()}"
        with open(temp_path, 'w') as f:
            f.write(content)
        self._run_command(['mv', temp_path, file_path])

    def _strip_colors(self, text):
        """Removes ANSI color codes from a string."""
        return re.sub(r'\x1b\[[0-9;]*m', '', text)

    def _echo_box_title(self, title):
        title_text = f" {title} "
        try:
            # Calculate width based on visible characters
            stripped_title = self._strip_colors(title_text)
            border = "+" + "-" * (len(stripped_title)) + "+"
            
            print(f"\n{C_CYAN}{border}{C_NC}")
            print(f"{C_CYAN}|{C_BOLD}{C_YELLOW}{title_text}{C_NC}{C_CYAN}|{C_NC}")
            print(f"{C_CYAN}{border}{C_NC}")
        except OSError: # Fallback for non-interactive terminals
            print(f"\n--- {title} ---")

    def _echo_step(self, msg): print(f"  {C_CYAN}>{C_NC} {C_BOLD}{msg}{C_NC}")
    def _echo_ok(self, msg): print(f"    {C_GREEN}v{C_NC} {msg}")
    def _echo_warn(self, msg): print(f"    {C_YELLOW}!{C_NC} {msg}")
    def _echo_error(self, msg): print(f"    {C_RED}x{C_NC} {msg}")
    def _press_enter(self): input(f"\n  Press ENTER to continue...")
    
    def _display_header(self):
        try:
            term_width = shutil.get_terminal_size((80, 20)).columns
            current_time = time.strftime("%Y-%m-%d %H:%M:%S")
            header_text = f"π-Backend Setup v{self.script_version} (Python) | {current_time}"
            print(f"{C_GREEN}{C_BOLD}{header_text:^{term_width}}{C_NC}")
            print(f"{C_GREEN}{'=' * term_width}{C_NC}")
        except OSError:
            print(f"--- pi_backend Setup v{self.script_version} ---")

    # --- Config Management ---
    def _load_master_config(self):
        config_to_read = self.source_config_file
        deployed_config = os.path.join(self.master_config_path, "setup_config.ini")

        if os.path.exists(deployed_config):
            config_to_read = deployed_config
        elif not os.path.exists(self.source_config_file):
            return

        parser = configparser.ConfigParser()
        parser.read(config_to_read)

        if 'SystemPaths' in parser:
            # These are reassigned here from the config file, if found
            self.install_path = parser.get('SystemPaths', 'install_path', fallback=self.install_path)
            self.config_path = parser.get('SystemPaths', 'config_path', fallback=self.config_path)
            self.db_path = parser.get('SystemPaths', 'database_path', fallback=self.db_path)

    # --- Database Interaction (Corrected) ---
    def _get_db_connection(self):
        """Establishes and returns a database connection."""
        try:
            conn = sqlite3.connect(self.db_path)
            conn.row_factory = sqlite3.Row
            return conn
        except sqlite3.Error as e:
            self._echo_error(f"Database connection error: {e}")
            return None

    def _initialize_database(self, retry=True):
        """Initializes the database, recreating if it's readonly."""
        self._echo_step("Initializing/Verifying database schema...")
        conn = None
        try:
            self.manage_database_location() 
            conn = self._get_db_connection()
            if not conn: 
                self._echo_error("Failed to get a database connection after managing location.")
                return False

            cursor = conn.cursor()
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS [configuration] (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    key TEXT UNIQUE NOT NULL,
                    value TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
            """)
            conn.commit()
            self._echo_ok("Database schema verified.")
            return True
        except sqlite3.Error as e:
            if "readonly database" in str(e).lower() and retry:
                self._echo_warn(f"Database is readonly. Attempting to fix by recreating...")
                if conn: conn.close()
                self._run_command(['rm', '-f', self.db_path])
                return self._initialize_database(retry=False) 
            else:
                self._echo_error(f"Failed to initialize tables: {e}")
                return False
        finally:
            if conn: conn.close()
            
    def _get_config_from_db(self, section, key, fallback=''):
        """Gets a config value from the DB using the correct key format."""
        full_key = f"{section}_{key}"
        conn = self._get_db_connection()
        if not conn: return fallback
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT value FROM configuration WHERE key = ?", (full_key,))
            row = cursor.fetchone()
            return row['value'] if row else fallback
        except sqlite3.Error as e:
            self._echo_error(f"Failed to get config '{full_key}' from DB: {e}")
            return fallback
        finally:
            if conn: conn.close()
            
    def _set_config_in_db(self, section, key, value):
        """Sets a config value in the DB using the correct key format."""
        full_key = f"{section}_{key}"
        conn = self._get_db_connection()
        if not conn: return False
        try:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO configuration (key, value, updated_at)
                VALUES (?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = CURRENT_TIMESTAMP
            """, (full_key, str(value)))
            conn.commit()
            self._echo_ok(f"Config set in DB: {full_key} = {value}")
            return True
        except sqlite3.Error as e:
            self._echo_error(f"Failed to set config in DB for key '{full_key}': {e}")
            return False
        finally:
            if conn: conn.close()
            
    # --- Core Logic Functions ---
    def _configure_database_path(self):
        """Prompts the user to confirm or change the database path during first-time setup."""
        self._echo_box_title("Database Configuration")
        self._echo_step(f"The default database path is: {C_GREEN}{self.db_path}{C_NC}")
        
        while True:
            new_path = input("  Press ENTER to accept, or enter a new absolute path (must end in .db): ").strip()
            
            if not new_path:
                self._echo_ok(f"Using default path: {self.db_path}")
                break # User accepts the default
            
            if not new_path.endswith(".db"):
                self._echo_error("Invalid path. The path must end with '.db'. Please try again.")
                continue

            if not os.path.isabs(new_path):
                self._echo_error("Invalid path. Please provide an absolute path (e.g., /home/user/my_db.db).")
                continue

            parent_dir = os.path.dirname(new_path)
            try:
                self._run_command(['mkdir', '-p', parent_dir])
                self._run_command(['chown', f'{self.current_user}:{self.current_user}', parent_dir])
                if not os.access(parent_dir, os.W_OK):
                     self._echo_error(f"The directory '{parent_dir}' is not writable. Please choose a different location or fix permissions.")
                     continue
                
                self.db_path = new_path
                self._echo_ok(f"Database path set to: {self.db_path}")
                break
            except Exception as e:
                 self._echo_error(f"Could not access or create directory '{parent_dir}': {e}")
                 continue

    def run_first_time_setup(self):
        self._echo_box_title("Starting First-Time Setup")
        self.initial_directory_setup()
        self.verify_prerequisites()
        
        self._configure_database_path()

        self.configure_gpsd()
        self.configure_chrony_for_gps()
        self.deploy_and_manage_files()
        
        if not self._initialize_database():
            self._echo_error("CRITICAL: Database could not be initialized. Aborting setup.")
            sys.exit(1)
        self.migrate_ini_to_db()

        self._set_config_in_db('SystemPaths', 'database_path', self.db_path)
        
        self._echo_box_title("Optional: WebSDR Proxy Setup")
        websdr_confirm = input("  Do you want to enable a reverse proxy for a local WebSDR instance at /WebSDR? (y/N): ").lower()
        if websdr_confirm == 'y':
            self._set_config_in_db('WebSDR', 'enable_proxy', 'true')
        else:
            self._set_config_in_db('WebSDR', 'enable_proxy', 'false')

        self.manage_ssl_certificate()
        self.configure_apache()
        self.create_desktop_shortcut()
        self.enforce_file_permissions() # Replaces manage_permissions
        self.install_all_services()
        self.test_api()
        
        self._run_command(['touch', self.setup_complete_flag], as_sudo=False)
        self._echo_ok("First-time setup is complete!")
        self._echo_warn("You may need to log out and log back in for new group memberships to take full effect.")

    def initial_directory_setup(self):
        self._echo_box_title("Initial Directory Setup")
        self._echo_step("Creating essential system directories...")
        dirs_to_create = [
            self.install_path, self.static_web_root, self.config_path,
            os.path.dirname(self.db_path), self.pi_backend_home_dir,
            # self.ups_daemon_state_dir # Removed: No longer needed
        ]
        self._run_command(['mkdir', '-p', self.log_dir])
        self._run_command(['chown', 'www-data:www-data', self.log_dir])
        self._run_command(['chmod', '755', self.log_dir])
        
        for d in dirs_to_create:
            self._run_command(['mkdir', '-p', d])
        
        self._run_command(['chown', f'{self.current_user}:{self.current_user}', self.pi_backend_home_dir], as_sudo=True)
        # Removed: ups_daemon_state_dir management
        # self._run_command(['chown', 'www-data:www-data', self.ups_daemon_state_dir])
        # self._run_command(['chmod', '775', self.ups_daemon_state_dir])
        self._echo_ok("All required directories created and permissions set.")


    def verify_prerequisites(self):
        self._echo_box_title("Verifying System Prerequisites")
        
        self._echo_step(f"Adding current user ({self.current_user}) to 'www-data' and 'i2c' groups...")
        for group in ['www-data', 'i2c']:
            if self._run_command(['groups', self.current_user], as_sudo=False, capture=True).stdout.find(group) == -1:
                self._run_command(['usermod', '-a', '-G', group, self.current_user])
                self._echo_warn(f"User added to '{group}' group. A logout/login is required for all changes to take full effect.")
            else:
                self._echo_ok(f"User is already in '{group}' group.")

        self._echo_step("Updating package lists...")
        self._run_command(['apt-get', 'update'], capture=True)

        apt_packages = [
            "python3-certbot-apache", "gunicorn", "python3-flask", "python3-requests",
            "python3-bs4", "python3-geopy", "python3-schedule", "bluetooth",
            "libbluetooth-dev", "gpsd", "gpsd-clients", "python3-gps", "apache2",
            "jq", "curl", "wget", "python3-skyfield", "python3-flask-cors",
            "sqlitebrowser", "python3-serial", "rsync", "python3-venv", "sense-hat",
            "build-essential", "python3-dev", "python3-psutil", "chrony", "iproute2",
            "libffi-dev", "python3-argon2", "python3-smbus",
            "python3-matplotlib", "python3-pil", "python3-pil.imagetk"
        ]
        
        self._echo_step("Checking required system packages...")
        packages_to_install = []
        for pkg in apt_packages:
            result = self._run_command(['dpkg', '-s', pkg], as_sudo=False, capture=True)
            if not (result and result.returncode == 0):
                packages_to_install.append(pkg)
        
        if packages_to_install:
            self._echo_warn(f"The following packages will be installed: {', '.join(packages_to_install)}")
            self._press_enter()
            install_result = self._run_command(['apt-get', 'install', '-y'] + packages_to_install)
            if not install_result or install_result.returncode != 0:
                self._echo_error(f"Failed to install required packages. Please install them manually.")
                sys.exit(1)
        else:
            self._echo_ok("All system packages are already installed.")

        self._echo_step("Ensuring apache2 service is enabled to start on boot...")
        if self._run_command(['systemctl', 'enable', 'apache2']).returncode == 0:
            self._echo_ok("Apache2 service enabled.")
        else:
            self._echo_error("Failed to enable apache2 service.")

        self._echo_step("Ensuring critical Apache modules are enabled...")
        self._run_command(['a2enmod', 'proxy', 'proxy_http', 'proxy_wstunnel', 'alias', 'rewrite', 'ssl', 'headers'])
        if self._run_command(['systemctl', 'restart', 'apache2']).returncode != 0:
            self._echo_error("Failed to restart Apache. Aborting.")
            self._run_command(['journalctl', '-u', 'apache2', '--no-pager', '-n', '20'])
            sys.exit(1)
            
        self.download_skyfield_data()
        self._echo_ok("Prerequisites check complete.")

    def migrate_ini_to_db(self):
        self._echo_box_title("Migrating Configuration to Database")
        deployed_config_file = os.path.join(self.master_config_path, "setup_config.ini")
        if not os.path.exists(deployed_config_file):
            self._echo_warn("No .ini file to migrate. Skipping.")
            return

        conn = self._get_db_connection()
        if not conn: return
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM configuration")
            if cursor.fetchone()[0] > 0:
                self._echo_warn("Database already contains configuration. Skipping migration.")
                self._run_command(['rm', '-f', deployed_config_file])
                return

            parser = configparser.ConfigParser()
            parser.read(deployed_config_file)
            for section in parser.sections():
                for key, value in parser.items(section):
                    self._set_config_in_db(section, key, value)
            
            self._echo_ok("Configuration successfully migrated to database.")
            self._run_command(['rm', '-f', deployed_config_file])
            self._echo_ok("Removed old .ini file.")
        except Exception as e:
            self._echo_error(f"Failed to migrate INI config: {e}")
        finally:
            if conn: conn.close()
    
    def _get_cert_details(self, domain):
        """Gets details for a specific SSL certificate."""
        cert_path = f"/etc/letsencrypt/live/{domain}/fullchain.pem"
        
        details = {'domain': domain}
        try:
            # Get expiry date
            expiry_cmd = ['openssl', 'x509', '-in', cert_path, '-noout', '-enddate']
            expiry_result = self._run_command(expiry_cmd, capture=True)
            if expiry_result and expiry_result.returncode == 0:
                expiry_str = expiry_result.stdout.replace("notAfter=", "").strip()
                expiry_date = datetime.strptime(expiry_str, "%b %d %H:%M:%S %Y %Z")
                details['expiry_date'] = expiry_date.strftime("%Y-%m-%d")
                days_left = (expiry_date - datetime.now()).days
                details['days_remaining'] = days_left
            
            # Get fingerprint
            fp_cmd = ['openssl', 'x509', '-in', cert_path, '-noout', '-fingerprint', '-sha256']
            fp_result = self._run_command(fp_cmd, capture=True)
            if fp_result and fp_result.returncode == 0:
                details['fingerprint'] = fp_result.stdout.replace("SHA256 Fingerprint=", "").strip()

            return details
        except Exception as e:
            self._echo_warn(f"Could not parse certificate details for {domain}: {e}")
            return None

    def manage_ssl_certificate(self):
        self._echo_box_title("SSL Certificate Management")
        self.apache_domain = self._get_config_from_db('SSL', 'ssl_domain', '')
        
        # Proactively scan for any existing certificates using sudo
        live_certs_path = "/etc/letsencrypt/live"
        existing_certs_result = self._run_command(['ls', '-1', live_certs_path], capture=True)
        existing_certs = []
        if existing_certs_result and existing_certs_result.returncode == 0:
             # Filter out non-directory entries like README
            for d in existing_certs_result.stdout.splitlines():
                check_dir_cmd = self._run_command(['test', '-d', os.path.join(live_certs_path, d)], check=False)
                if check_dir_cmd.returncode == 0:
                    existing_certs.append(d)

        # If we have a domain in the DB and a matching cert exists, we are done.
        if self.apache_domain and self.apache_domain in existing_certs:
             cert_details = self._get_cert_details(self.apache_domain)
             self._echo_ok(f"Using configured SSL domain: {C_GREEN}{self.apache_domain}{C_NC}")
             if cert_details:
                 self._echo_ok(f"  -> Expires: {cert_details['expiry_date']} ({cert_details['days_remaining']} days left)")
             return

        # If no domain in DB, but certs exist, prompt the user to use one.
        if not self.apache_domain and existing_certs:
            self._echo_warn("Found existing SSL certificates on this system:")
            for i, cert_domain in enumerate(existing_certs):
                details = self._get_cert_details(cert_domain)
                if details:
                    print(f"  {C_CYAN}{i+1}){C_NC} {C_BOLD}{details['domain']}{C_NC}")
                    print(f"     Expires: {details['expiry_date']} ({details['days_remaining']} days)")
                    print(f"     Fingerprint (SHA256): {details['fingerprint']}")
            
            choice = input(f"  Enter the number to use a certificate, or press Enter to obtain a new one: ")
            try:
                choice_idx = int(choice) - 1
                if 0 <= choice_idx < len(existing_certs):
                    chosen_domain = existing_certs[choice_idx]
                    self._echo_ok(f"Selected existing certificate for: {chosen_domain}")
                    self._set_config_in_db('SSL', 'ssl_domain', chosen_domain)
                    self.apache_domain = chosen_domain
                    return
            except (ValueError, IndexError):
                pass

        # If we reach here, we need to obtain a new cert or skip.
        self._echo_warn("No valid SSL domain configured. Prompting for new certificate.")
        new_domain = input("  Enter your domain name (or leave blank for HTTP only): ").strip()
        if new_domain:
            email = input("  Enter your email for Certbot: ").strip()
            self._echo_step("Running Certbot...")
            result = self._run_command([
                'certbot', '--apache', '-d', new_domain, '--email', email,
                '--agree-tos', '--redirect', '--non-interactive'
            ])
            if result and result.returncode == 0:
                self.apache_domain = new_domain
                self._set_config_in_db('SSL', 'ssl_domain', self.apache_domain)
                self._echo_ok(f"Certificate obtained for {self.apache_domain}")
            else:
                self._echo_error("Certbot failed. Proceeding without SSL.")
                self.apache_domain = ""
                self._set_config_in_db('SSL', 'ssl_domain', "")
        else:
            self.apache_domain = ""
            self._set_config_in_db('SSL', 'ssl_domain', "")
            self._echo_warn("Skipping SSL setup.")

    def configure_apache(self):
        self._echo_box_title("Configuring Apache")
        self.apache_domain = self._get_config_from_db('SSL', 'ssl_domain', '')
        enable_websdr = self._get_config_from_db('WebSDR', 'enable_proxy', 'false').lower() == 'true'

        self._echo_step("Cleaning old configurations...")
        self._run_command(['a2dissite', 'pi-backend-http.conf'], capture=True)
        self._run_command(['a2dissite', 'pi-backend-https.conf'], capture=True)
        self._run_command(['a2dissite', 'pi-backend-websdr.conf'], capture=True)
        self._run_command(['rm', '-f', '/etc/apache2/sites-available/pi-backend-*.conf'])

        def process_template(template_name, output_file, replacements):
            template_path = os.path.join(self.templates_dir, template_name)
            if not os.path.exists(template_path):
                self._echo_error(f"Template not found: {template_path}")
                return False
            with open(template_path, 'r') as f:
                content = f.read()
            for key, value in replacements.items():
                content = content.replace(key, str(value))
            self._write_sudo_file(output_file, content)
            self._echo_ok(f"Generated config: {output_file}")
            return True

        # HTTP Conf
        replacements_http = {
            "__SERVER_NAME__": self.apache_domain or "localhost",
            "__STATIC_WEB_ROOT__": self.static_web_root,
            "__INSTALL_PATH__": self.install_path,
            "# __REDIRECT_PLACEHOLDER__": f"Redirect permanent / https://{self.apache_domain}/" if self.apache_domain else ""
        }
        if process_template("pi-backend-http.conf.template", self.apache_http_conf_file, replacements_http):
            self._run_command(['a2ensite', os.path.basename(self.apache_http_conf_file)])
        
        # HTTPS Conf
        if self.apache_domain:
            replacements_https = {
                "__SERVER_NAME__": self.apache_domain,
                "__STATIC_WEB_ROOT__": self.static_web_root,
                "__INSTALL_PATH__": self.install_path,
                "__SSL_CERT_FILE__": f"/etc/letsencrypt/live/{self.apache_domain}/fullchain.pem",
                "__SSL_KEY_FILE__": f"/etc/letsencrypt/live/{self.apache_domain}/privkey.pem"
            }
            if process_template("pi-backend-https.conf.template", self.apache_https_conf_file, replacements_https):
                self._run_command(['a2ensite', os.path.basename(self.apache_https_conf_file)])
        
        # WebSDR Conf (if enabled and we have a domain for SSL)
        if enable_websdr and self.apache_domain:
            self._echo_step("Generating WebSDR proxy config...")
            replacements_websdr = {
                "__SERVER_NAME__": self.apache_domain,
                "__SSL_CERT_FILE__": f"/etc/letsencrypt/live/{self.apache_domain}/fullchain.pem",
                "__SSL_KEY_FILE__": f"/etc/letsencrypt/live/{self.apache_domain}/privkey.pem"
            }
            if process_template("pi-backend-websdr.conf.template", self.apache_websdr_conf_file, replacements_websdr):
                self._run_command(['a2ensite', os.path.basename(self.apache_websdr_conf_file)])
        elif enable_websdr and not self.apache_domain:
            self._echo_warn("WebSDR proxy is enabled in config, but cannot be activated without an SSL domain.")


        self._echo_step("Reloading Apache...")
        self._run_command(['apache2ctl', 'configtest'])
        self._run_command(['systemctl', 'reload', 'apache2'])
        self._echo_ok("Apache configuration complete.")

    def configure_gpsd(self):
        self._echo_box_title("Configuring GPSD Service")
        gpsd_config_file = "/etc/default/gpsd"
        content = self._read_sudo_file(gpsd_config_file)
        if content is None:
            self._echo_error(f"GPSD config not found at {gpsd_config_file}. Reinstall 'gpsd'.")
            return

        original_content = content
        content = re.sub(r'^DEVICES=".*"', f'DEVICES="{self.gps_device}"', content, count=1, flags=re.MULTILINE)
        content = re.sub(r'^GPSD_OPTIONS=".*"', 'GPSD_OPTIONS="-n"', content, count=1, flags=re.MULTILINE)

        if content != original_content:
            self._echo_ok("Updating GPSD configuration.")
            self._write_sudo_file(gpsd_config_file, content)
        else:
            self._echo_ok("GPSD already configured correctly.")

        self._echo_step("Restarting GPSD service to apply changes...")
        self._run_command(['systemctl', 'restart', 'gpsd.socket', 'gpsd.service'])

        self._echo_step("Checking for live GPS data stream (5s timeout)...")
        gps_pipe_cmd = ['timeout', '5', 'gpspipe', '-w', '-n', '10']
        gps_data = self._run_command(gps_pipe_cmd, as_sudo=False, capture=True)
        if gps_data and 'TPV' in gps_data.stdout:
            self._echo_ok("Live GPS data stream detected.")
        else:
            self._echo_warn("No live GPS data received. This is normal if indoors or at first start.")
            self._echo_warn("Ensure HAT is connected and has a clear view of the sky.")


    def configure_chrony_for_gps(self):
        self._echo_box_title("Configuring Chrony for GPS Time Sync")
        chrony_conf = "/etc/chrony/chrony.conf"
        content = self._read_sudo_file(chrony_conf)
        if content is None:
            self._echo_error("Chrony config not found. Reinstall 'chrony'.")
            return
        
        new_content = re.sub(r'^(\s*(pool|server)\s.*)', r'#\1', content, flags=re.MULTILINE)
        if new_content != content:
            self._echo_ok("Commented out default NTP pools.")
            self._write_sudo_file(chrony_conf, new_content)
        
        gps_conf_path = "/etc/chrony/conf.d/gpsd.conf"
        gps_conf_content = textwrap.dedent("""
            # Generated by pi_backend installer
            # Use gpsd shared memory as a time source.
            refclock SHM 0 refid GPS poll 2 delay 0.2 trust
        """).strip()
        self._write_sudo_file(gps_conf_path, gps_conf_content)
        self._echo_ok(f"Created Chrony GPSD config at {gps_conf_path}")

        self._echo_step("Restarting Chrony service...")
        self._run_command(['systemctl', 'restart', 'chrony'])
        
        self._echo_step("Verifying Chrony sources (please wait)...")
        time.sleep(5)
        self._run_command(['chronyc', 'sources'])

    def deploy_and_manage_files(self):
        self._echo_box_title("Deploying & Organizing Files")
        
        # 1. Ensure backend install path exists
        self._echo_step(f"Ensuring backend install directory {self.install_path} exists...")
        self._run_command(['mkdir', '-p', self.install_path])
        
        # 2. Sync backend Python files and templates (excluding index.html and ups_daemon.py)
        self._echo_step(f"Synchronizing backend application files to {self.install_path} with rsync...")
        rsync_backend_command = [
            'rsync',
            '-av',
            '--delete',
            '--exclude=index.html',
            '--exclude=ups_daemon.py',
            '--include=*/',
            '--include=*.py',
            '--include=*.template',
            '--include=modules/***',
            '--exclude=*',
            f'{self.source_dir}/',
            f'{self.install_path}/'
        ]
        result_backend = self._run_command(rsync_backend_command, capture=True)
        if result_backend.returncode != 0:
            self._echo_error(f"Rsync failed to deploy backend files.\n{result_backend.stderr}")
            return

        self._echo_ok("Core backend files synchronized successfully.")

        # 3. Ensure static web root exists
        self._echo_step(f"Ensuring static web root directory {self.static_web_root} exists...")
        self._run_command(['mkdir', '-p', self.static_web_root])

        # 4. Copy index.html to the static web root
        self._echo_step(f"Copying index.html to static web root {self.static_web_root}...")
        index_html_src = os.path.join(self.source_dir, "index.html")
        if os.path.exists(index_html_src):
            self._run_command(['cp', index_html_src, self.static_web_root])
            self._echo_ok(f"Copied index.html to {self.static_web_root}.")
        else:
            self._echo_error(f"index.html not found in source directory: {index_html_src}")

        # 5. Deploy A7670E installer script
        a7670e_src = os.path.join(self.source_dir, self.a7670e_installer_source_name)
        if os.path.exists(a7670e_src):
            self._run_command(['cp', a7670e_src, self.a7670e_installer_system_path])
            self._run_command(['chmod', '+x', self.a7670e_installer_system_path])
            self._echo_ok(f"Deployed A7670E GPS installer tool to {self.a7670e_installer_system_path}.")
        else:
            self._echo_warn(f"Installer script not found, cannot deploy: {a7670e_src}")


    def manage_database_location(self):
        db_dir = os.path.dirname(self.db_path)
        if not os.path.exists(db_dir):
             self._run_command(['mkdir', '-p', db_dir])
        self._run_command(['chown', 'www-data:www-data', db_dir])
        self._run_command(['chmod', '775', db_dir])
        if not os.path.exists(self.db_path):
            self._run_command(['touch', self.db_path])
        self._run_command(['chown', 'www-data:www-data', self.db_path])
        self._run_command(['chmod', '664', self.db_path])

    def create_desktop_shortcut(self):
        self._echo_box_title("Creating Desktop Shortcut")
        desktop_path = os.path.expanduser("~/Desktop")
        if not os.path.isdir(desktop_path):
            self._echo_warn("Desktop directory not found. Skipping shortcut.")
            return
        
        shortcut_path = os.path.join(desktop_path, "pi_backend_database.db")
        if os.path.lexists(shortcut_path):
            os.remove(shortcut_path)
            
        try:
            os.symlink(self.db_path, shortcut_path)
            self._echo_ok(f"Shortcut created at {shortcut_path}")
        except OSError as e:
            self._echo_error(f"Failed to create shortcut: {e}")
        
    def enforce_file_permissions(self):
        self._echo_box_title("Enforcing Final File & User Permissions")
        
        self._echo_step("Setting ownership for all application files to www-data...")
        self._run_command(['chown', '-R', 'www-data:www-data', self.install_path])
        self._run_command(['chown', '-R', 'www-data:www-data', self.static_web_root])
        self._run_command(['chown', '-R', 'www-data:www-data', self.log_dir])
        self.manage_database_location()
        
        self._echo_step(f"Adding current user ({self.current_user}) to required groups...")
        for group in ['dialout', 'i2c', 'gpio', 'input']:
            if self._run_command(['groups', self.current_user], as_sudo=False, capture=True).stdout.find(group) == -1:
                self._run_command(['usermod', '-a', '-G', group, self.current_user])
                self._echo_warn(f"Added user to group '{group}'. A logout/login may be required.")
        
        self._echo_ok("Final permissions are set.")
        
    def _process_service_template(self, template_name, output_file, replacements_dict):
        template_path = os.path.join(self.templates_dir, template_name)
        if not os.path.exists(template_path):
            self._echo_error(f"Template not found: {template_path}")
            return False
        with open(template_path, 'r') as f:
            content = f.read()
        
        for key, value in replacements_dict.items():
            content = content.replace(key, str(value))
        
        self._write_sudo_file(output_file, content)
        self._echo_ok(f"Generated service file: {output_file}")
        return True

    def install_all_services(self):
        self._echo_box_title("Installing/Reinstalling All Services")
        self._reinstall_service(self.api_service_name, "pi_backend_api.service.template")
        self._reinstall_service(self.poller_service_name, "pi_backend_poller.service.template")
        self._reinstall_a7670e_service()

    def _reinstall_service(self, service_name, template_name):
        self._echo_step(f"Reinstalling {service_name}...")
        service_file_path = f"/etc/systemd/system/{service_name}"
        replacements = {
            "__INSTALL_PATH__": self.install_path,
            "__DB_PATH__": self.db_path,
            "__API_SERVICE_NAME__": self.api_service_name,
            "__GPS_INIT_SERVICE_NAME__": self.gps_init_service_name,
            "__POLLER_SERVICE_NAME__": self.poller_service_name
        }
        
        if self._process_service_template(template_name, service_file_path, replacements):
            self._run_command(['systemctl', 'daemon-reload'])
            self._run_command(['systemctl', 'enable', service_name])
            
            self._echo_warn(f"Stopping {service_name} before restart...")
            self._run_command(['systemctl', 'stop', service_name], check=False)
            time.sleep(2)

            restart_result = self._run_command(['systemctl', 'restart', service_name], check=False)
            if restart_result and restart_result.returncode == 0:
                self._echo_ok(f"{service_name} reinstalled and restarted successfully.")
            else:
                self._echo_error(f"Failed to restart {service_name}. Check logs with 'journalctl -u {service_name}'.")
        else:
            self._echo_error(f"Failed to reinstall {service_name}, template file '{template_name}' was missing.")

    def _reinstall_a7670e_service(self):
        self._echo_step("Reinstalling A7670E GPS Service...")
        if os.path.exists(self.a7670e_installer_system_path):
            status_result = self._run_command([self.a7670e_installer_system_path, '-status'], capture=True)
            if status_result and status_result.returncode == 0:
                self._echo_ok("A7670E GPS service is already running correctly.")
            else:
                self._echo_warn("A7670E GPS service not running or has no fix. Proceeding with installation.")
                self._run_command([self.a7670e_installer_system_path, '-install'])
                self._echo_ok("A7670E GPS service reinstall command executed.")
        else:
            self._echo_error(f"Installer script not found at {self.a7670e_installer_system_path}")
        
    def test_api(self):
        self._echo_box_title("Final API Status Test")
        test_url = f"https://{self.apache_domain}/api/status" if self.apache_domain else "http://127.0.0.1/api/status"
        self._echo_step(f"Testing endpoint: {test_url}")
        
        requests.packages.urllib3.disable_warnings(requests.packages.urllib3.exceptions.InsecureRequestWarning)

        api_reachable = False
        for i in range(15):
            self._echo_warn(f"Attempt {i+1}/15...")
            try:
                response = requests.get(test_url, timeout=10, verify=False)
                if response.status_code == 200 and response.json().get("status") == "ok":
                    self._echo_ok("API test PASSED. The backend is live.")
                    import json
                    print(json.dumps(response.json(), indent=2))
                    api_reachable = True
                    break
            except requests.exceptions.RequestException as e:
                self._echo_warn(f"API test attempt {i+1} failed: {e}")
            time.sleep(4)
        
        if not api_reachable:
            self._echo_error("API test FAILED after multiple retries.")
            self._echo_warn(f"Attempting to diagnose the issue with '{self.api_service_name}'...")
            
            # Check service status
            self._echo_step(f"Checking status of {self.api_service_name}:")
            self._run_command(['systemctl', 'status', self.api_service_name], check=False)
            
            # Check service logs
            self._echo_step(f"Checking journal logs for {self.api_service_name} (last 20 lines):")
            self._run_command(['journalctl', '-u', self.api_service_name, '--no-pager', '-n', '20'], check=False)
            
            # Check if Gunicorn is listening on port 5000
            self._echo_step("Checking if Gunicorn is listening on port 5000:")
            self._run_command(['ss', '-tuln', '|', 'grep', '5000'], check=False, shell=True)
            
            self._echo_warn("Please review the service status and logs above for more details to troubleshoot why the API is not reachable.")
            self._echo_warn("Common issues: Flask app errors, Gunicorn configuration, port conflicts, or permissions.")
            self._press_enter()


    def download_skyfield_data(self):
        self._echo_box_title("Downloading Skyfield Astronomy Data")
        self._run_command(['mkdir', '-p', self.skyfield_data_dir])
        
        files_to_download = {
            "de442s.bsp": "https://naif.jpl.nasa.gov/pub/naif/generic_kernels/spk/planets/de442s.bsp",
            "active.txt": "https://celestrak.org/NORAD/elements/gp.php?GROUP=active&FORMAT=tle"
        }

        for filename, url in files_to_download.items():
            dest_path = os.path.join(self.skyfield_data_dir, filename)
            if os.path.exists(dest_path):
                 self._echo_ok(f"'{filename}' already exists.")
                 continue
            
            self._echo_step(f"Downloading {filename}...")
            try:
                response = requests.get(url, stream=True, timeout=300)
                response.raise_for_status()
                temp_dest_path = f"/tmp/{filename}"
                with open(temp_dest_path, "wb") as f:
                    shutil.copyfileobj(response.raw, f)
                self._run_command(['mv', temp_dest_path, dest_path])
                self._echo_ok(f"'{filename}' downloaded successfully.")
            except requests.exceptions.RequestException as e:
                self._echo_error(f"Failed to download '{filename}': {e}")
        
        self._run_command(['chown', '-R', 'www-data:www-data', self.skyfield_data_dir])
        
    # --- Menu Implementations ---
    def _edit_config_file(self, file_path, description):
        """Helper to open a config file in nano."""
        self._echo_box_title(f"Editing {description}")
        self._echo_warn(f"You are about to manually edit {file_path}.")
        self._echo_warn("Incorrect changes can cause system instability.")
        confirm = input("  Are you sure you want to continue? (y/N): ").lower()
        if confirm == 'y':
            self._run_command(['nano', file_path])
            self._echo_ok(f"Finished editing {description}. You may need to restart related services for changes to take effect.")
        else:
            self._echo_ok("Edit cancelled.")
        self._press_enter()

    def main_menu(self):
        while True:
            os.system('clear')
            self._display_header()
            self._echo_box_title("pi_backend Main Menu")
            print(f"  {C_CYAN}1){C_NC} Service Management")
            print(f"  {C_CYAN}2){C_NC} Apache Management")
            print(f"  {C_CYAN}3){C_NC} System & Update")
            print(f"  {C_CYAN}4){C_NC} Diagnostics & Tools")
            print(f"  {C_CYAN}5){C_NC} Full Program Management")
            print(f"  {C_CYAN}X){C_NC} Exit")
            choice = input("\n  Enter your choice: ").strip().lower()

            if choice == '1': self.service_management_menu()
            elif choice == '2': self.apache_management_menu()
            elif choice == '3': self.system_update_menu()
            elif choice == '4': self.diagnostics_tools_menu()
            elif choice == '5': self.full_program_management_menu()
            elif choice == 'x': sys.exit(0)
            else: self._echo_error("Invalid option.")

    def service_management_menu(self):
        while True:
            os.system('clear')
            self._display_header()
            self._echo_box_title("Service Management")
            print(f"  {C_CYAN}1){C_NC} Check All Core Services Status")
            print(f"  {C_CYAN}2){C_NC} Restart All Core Services")
            print(f"  {C_CYAN}3){C_NC} Manage Service Boot Status (Enable/Disable)")
            print(f"\n  --- A7670E GPS Service ---")
            print(f"  {C_CYAN}4){C_NC} Check A7670E GPS Service Status")
            print(f"  {C_CYAN}5){C_NC} Restart A7670E GPS Service")
            print(f"\n  --- Reinstall ---")
            print(f"  {C_CYAN}6){C_NC} Reinstall All Services")
            print(f"\n  {C_CYAN}X){C_NC} Back to Main Menu")
            choice = input("\n  Enter your choice: ").strip().lower()

            if choice == '1':
                self._run_command(['systemctl', 'status'] + self.core_services, check=False)
                self._press_enter()
            elif choice == '2':
                self._echo_step("Restarting core services...")
                self._run_command(['systemctl', 'restart'] + self.core_services)
                self._press_enter()
            elif choice == '3':
                self.service_boot_status_menu()
            elif choice == '4':
                self._run_command([self.a7670e_installer_system_path, '-status'])
                self._press_enter()
            elif choice == '5':
                self._run_command([self.a7670e_installer_system_path, '-restart'])
                self._press_enter()
            elif choice == '6':
                self.install_all_services()
                self._press_enter()
            elif choice == 'x': break
            else: self._echo_error("Invalid option.")

    def service_boot_status_menu(self):
        """Submenu to enable or disable services from starting on boot."""
        while True:
            os.system('clear')
            self._display_header()
            self._echo_box_title("Manage Service Boot Status")
            
            # Display status for each service
            for i, service in enumerate(self.core_services):
                is_enabled_result = self._run_command(['systemctl', 'is-enabled', service], capture=True, check=False)
                status = is_enabled_result.stdout.strip() if is_enabled_result else 'unknown'
                status_color = C_GREEN if status == 'enabled' else C_RED
                print(f"  {C_CYAN}{i+1}){C_NC} {service:<30} {status_color}{status.upper()}{C_NC}")

            print(f"\n  {C_CYAN}X){C_NC} Back to Service Management")
            choice = input("\n  Enter number to toggle service, or X to exit: ").strip().lower()

            if choice == 'x':
                break
            
            try:
                choice_idx = int(choice) - 1
                if 0 <= choice_idx < len(self.core_services):
                    service_to_toggle = self.core_services[choice_idx]
                    is_enabled_result = self._run_command(['systemctl', 'is-enabled', service_to_toggle], capture=True, check=False)
                    is_enabled = is_enabled_result.stdout.strip() == 'enabled' if is_enabled_result else False
                    
                    if is_enabled:
                        self._echo_step(f"Disabling {service_to_toggle} from starting on boot...")
                        self._run_command(['systemctl', 'disable', service_to_toggle])
                    else:
                        self._echo_step(f"Enabling {service_to_toggle} to start on boot...")
                        self._run_command(['systemctl', 'enable', service_to_toggle])
                    time.sleep(1) # Pause to show the result
                else:
                    self._echo_error("Invalid number.")
                    time.sleep(1)
            except ValueError:
                self._echo_error("Invalid input. Please enter a number.")
                time.sleep(1)

    def apache_management_menu(self):
        """Manages the Apache web server configuration."""
        while True:
            os.system('clear')
            self._display_header()
            self._echo_box_title("Apache Web Server Management")
            print(f"  {C_CYAN}1){C_NC} Check Apache Service Status")
            print(f"  {C_CYAN}2){C_NC} View Enabled Apache Site-Configs")
            print(f"  {C_CYAN}3){C_NC} View a Specific Apache Config File")
            print(f"  {C_CYAN}4){C_NC} Enable/Disable WebSDR Proxy (/WebSDR)")
            print(f"  {C_CYAN}5){C_NC} Re-apply All Apache Configurations")
            print(f"\n  {C_CYAN}X){C_NC} Back to Main Menu")
            choice = input("\n  Enter your choice: ").strip().lower()

            if choice == '1':
                self._run_command(['systemctl', 'status', 'apache2'], check=False)
                self._press_enter()
            elif choice == '2':
                self._echo_step("Listing enabled Apache sites...")
                self._run_command(['ls', '-l', '/etc/apache2/sites-enabled/'])
                self._press_enter()
            elif choice == '3':
                self._view_apache_configs_menu()
            elif choice == '4':
                enable_websdr = self._get_config_from_db('WebSDR', 'enable_proxy', 'false').lower() == 'true'
                prompt = "disable" if enable_websdr else "enable"
                confirm = input(f"  WebSDR proxy is currently {'ENABLED' if enable_websdr else 'DISABLED'}. Do you want to {prompt} it? (y/N): ").lower()
                if confirm == 'y':
                    new_state = 'false' if enable_websdr else 'true'
                    self._set_config_in_db('WebSDR', 'enable_proxy', new_state)
                    self._echo_step("Applying new configuration...")
                    self.configure_apache() # Re-run configure apache to apply
                else:
                    self._echo_ok("No changes made.")
                self._press_enter()
            elif choice == '5':
                self._echo_step("Re-applying all Apache configurations...")
                self.configure_apache()
                self._echo_ok("Apache configurations re-applied.")
                self._press_enter()
            elif choice == 'x':
                break
            else:
                self._echo_error("Invalid option.")
                
    def _view_apache_configs_menu(self):
        """Submenu to view specific enabled config files."""
        sites_enabled_path = "/etc/apache2/sites-enabled"
        result = self._run_command(['ls', '-1', sites_enabled_path], capture=True)
        if not result or result.returncode != 0 or not result.stdout:
            self._echo_error("Could not list enabled sites or directory is empty.")
            self._press_enter()
            return
            
        enabled_sites = result.stdout.strip().split('\n')
        
        while True:
            os.system('clear')
            self._display_header()
            self._echo_box_title("View Apache Config File")
            for i, site in enumerate(enabled_sites):
                print(f"  {C_CYAN}{i+1}){C_NC} {site}")
            print(f"\n  {C_CYAN}X){C_NC} Back to Apache Menu")
            choice = input("\n  Enter number of config to view: ").strip().lower()

            if choice == 'x':
                break
                
            try:
                choice_idx = int(choice) - 1
                if 0 <= choice_idx < len(enabled_sites):
                    config_name = enabled_sites[choice_idx]
                    config_path = os.path.join("/etc/apache2/sites-available", config_name)
                    self._echo_step(f"Contents of {config_path}:")
                    content = self._read_sudo_file(config_path)
                    print("-" * 60)
                    print(content if content else "Could not read file or file is empty.")
                    print("-" * 60)
                    self._press_enter()
                else:
                    self._echo_error("Invalid number.")
                    time.sleep(1)
            except ValueError:
                self._echo_error("Invalid input. Please enter a number.")
                time.sleep(1)


    def system_update_menu(self):
        while True:
            os.system('clear')
            self._display_header()
            self._echo_box_title("System & Update")
            print(f"  {C_CYAN}1){C_NC} Run Update & Patch Check")
            print(f"  {C_CYAN}2){C_NC} Manage SSL Certificate")
            print(f"\n  {C_CYAN}X){C_NC} Back to Main Menu")
            choice = input("\n  Enter your choice: ").strip().lower()

            if choice == '1':
                 self.run_update_and_patch()
            elif choice == '2':
                self.manage_ssl_certificate()
                self.configure_apache()
                self._press_enter()
            elif choice == 'x': break
            else: self._echo_error("Invalid option.")

    def diagnostics_tools_menu(self):
        while True:
            os.system('clear')
            self._display_header()
            self._echo_box_title("Diagnostics & Tools")
            print(f"  {C_CYAN}1){C_NC} Check Live GPSd Status (cgps)")
            print(f"  {C_CYAN}2){C_NC} Check Live GPSd Raw Stream (gpspipe)")
            print(f"  {C_CYAN}3){C_NC} Check Chrony Time Sources")
            print(f"  {C_CYAN}4){C_NC} Edit GPSD Config File")
            print(f"  {C_CYAN}5){C_NC} Edit Chrony Config File")
            print(f"\n  {C_CYAN}X){C_NC} Back to Main Menu")
            choice = input("\n  Enter your choice: ").strip().lower()

            if choice == '1':
                self._echo_warn("Press 'q' to quit the GPS status screen.")
                time.sleep(2)
                os.system('clear')
                self._run_command(['cgps'], as_sudo=False)
            elif choice == '2':
                self._echo_warn("Press Ctrl+C to stop the stream.")
                time.sleep(2)
                self._run_command(['gpspipe', '-w'], as_sudo=False)
            elif choice == '3':
                self._run_command(['chronyc', 'sources'])
                self._press_enter()
            elif choice == '4':
                self._edit_config_file("/etc/default/gpsd", "GPSD Config")
            elif choice == '5':
                self._edit_config_file("/etc/chrony/chrony.conf", "Chrony Config")
            elif choice == 'x': break
            else: self._echo_error("Invalid option.")

    def full_program_management_menu(self):
         while True:
            os.system('clear')
            self._display_header()
            self._echo_box_title("Full Program Management")
            print(f"  {C_CYAN}1){C_NC} Reinstall Program")
            print(f"  {C_CYAN}2){C_NC} {C_RED}Uninstall Program (DESTRUCTIVE){C_NC}")
            print(f"  {C_CYAN}X){C_NC} Back to Main Menu")
            choice = input("\n  Enter your choice: ").strip().lower()

            if choice == '1':
                confirm = input(f"{C_YELLOW}WARNING: This will reinstall the entire program. Continue? (y/N): {C_NC}").lower()
                if confirm == 'y': self.run_first_time_setup()
            elif choice == '2': self.uninstall_program()
            elif choice == 'x': break
            else: self._echo_error("Invalid option.")

    def uninstall_program(self):
        self._echo_box_title("UNINSTALL PROGRAM")
        self._echo_warn("This will permanently remove ALL pi_backend files, data, and services.")
        confirm = input(f"{C_RED}Type 'YES' to confirm: {C_NC}")
        if confirm != "YES":
            self._echo_ok("Uninstall cancelled.")
            return

        self._echo_step("Stopping and disabling services...")
        self._run_command(['systemctl', 'stop'] + self.core_services, capture=True)
        self._run_command(['systemctl', 'disable'] + self.core_services, capture=True)

        self._echo_step("Removing files and directories...")
        paths_to_remove = [
            self.install_path, self.static_web_root, self.master_config_path, self.pi_backend_home_dir,
            self.skyfield_data_dir, self.log_dir, self.db_path,
            self.apache_http_conf_file, self.apache_https_conf_file, self.apache_websdr_conf_file,
            os.path.join("/etc/systemd/system", self.api_service_name),
            os.path.join("/etc/systemd/system", self.poller_service_name),
            "/etc/chrony/conf.d/gpsd.conf"
        ]
        for path in paths_to_remove:
            if os.path.isdir(path) and not os.path.islink(path):
                self._run_command(['rm', '-rf', path])
            elif os.path.exists(path):
                self._run_command(['rm', '-f', path])
        
        self._run_command(['systemctl', 'daemon-reload'])
        self._echo_ok("Pi_backend has been uninstalled.")
        self._press_enter()
        sys.exit(0)
        
    def run(self):
        """Main entry point for the script."""
        os.system('clear')
        if os.geteuid() == 0:
            self._echo_error("Please do not run this script as root directly.")
            sys.exit(1)

        self._display_header()
        print(f"\n{C_GREEN}--- Initializing pi_backend Python Installer ---{C_NC}\n")
        
        if not self._initialize_database():
             self._echo_error("CRITICAL: Initial database check/creation failed. Aborting.")
             sys.exit(1)

        self.patch_needed = self.check_file_versions(display=False)
        
        if not os.path.exists(self.setup_complete_flag):
            self._echo_box_title("FIRST-TIME INSTALLATION DETECTED")
            self._press_enter()
            self.run_first_time_setup()
        elif self.patch_needed:
            self._echo_box_title("SYSTEM UPDATE REQUIRED")
            self.check_file_versions(display=True)
            self._echo_warn("File differences detected. Initiating update process.")
            self._press_enter()
            self.run_update_and_patch()
        else:
            self._echo_ok("System is up-to-date. Launching main menu.")
            self._press_enter()

        self.main_menu()

    # --- Update & Patch Functionality ---
    def run_update_and_patch(self):
        """
        Applies updates to the system, forcing file deployment and service reinstall.
        This function is designed to be idempotent and ensure a clean update.
        """
        os.system('clear')
        self._display_header()
        self._echo_box_title("pi_backend Updater & Patcher")

        # Check file versions for reporting, but always proceed with deployment/reinstall
        self.patch_needed = self.check_file_versions(display=True)
        if not self.patch_needed:
            self._echo_warn("\nNo file differences detected, but proceeding with full update/reinstall as requested.")
        else:
            self._echo_warn("\nFile differences detected. Initiating update process.")
        self._press_enter()

        self._echo_step("Deploying updated files...")
        self.deploy_and_manage_files()
        
        self._echo_step("Reinstalling services with new configurations...")
        self.install_all_services()
        
        self._echo_step("Re-applying permissions...")
        self.enforce_file_permissions()
        
        self._echo_ok("File deployment and service installation complete.")

        self._echo_step("Verifying file integrity after patching...")
        self.check_file_versions(display=True)
        self._press_enter()

    def check_file_versions(self, display=True):
        if display:
            self._echo_box_title("File Version & Integrity Check")

        managed_files = [
            "api_routes.py", "app.py", "astronomy_services.py", "db_config_manager.py",
            "database.py", "data_poller.py", "hardware.py", "hardware_manager.py",
            "index.html", # index.html is now managed separately
            "location_services.py", "perm_enforcer.py", "security_manager.py",
            os.path.join(self.modules_subdir, "A7670E.py"),
            os.path.join(self.modules_subdir, "sense_hat.py"),
            os.path.join(self.modules_subdir, "ina219.py"),
            os.path.join(self.modules_subdir, "ups_status.py"),
        ]

        table_data = []
        any_mismatch = False

        for rel_path in managed_files:
            source_path = os.path.join(self.source_dir, rel_path)
            
            # Determine destination path based on file type
            if rel_path == "index.html":
                dest_path = os.path.join(self.static_web_root, rel_path)
            elif rel_path.startswith(self.modules_subdir + os.sep):
                dest_path = os.path.join(self.install_path, rel_path)
            else:
                dest_path = os.path.join(self.install_path, rel_path)
            
            status = ""
            status_color = C_GREEN

            if not os.path.exists(source_path):
                continue

            try:
                with open(source_path, 'r', errors='ignore') as f:
                    source_ver = self._extract_version_from_content(f.read())
            except IOError:
                source_ver = "N/A"

            source_sum = self._calculate_checksum(source_path, is_path=True)
            
            if not os.path.exists(dest_path):
                status = "MISSING"
                status_color = C_YELLOW
                any_mismatch = True
                dest_ver, dest_sum = "N/A", "N/A"
            else:
                dest_content = self._read_sudo_file(dest_path)
                dest_ver = self._extract_version_from_content(dest_content)
                dest_sum = self._calculate_checksum(dest_path, is_path=True, as_sudo=True)

                if source_sum != dest_sum:
                    status = "OUTDATED"
                    status_color = C_YELLOW
                    any_mismatch = True
                else:
                    status = "OK"
            
            table_data.append([
                os.path.basename(rel_path),
                f"{dest_ver}/{source_ver}",
                f"{dest_sum[:8]}.../{source_sum[:8]}...",
                f"{status_color}{status}{C_NC}"
            ])
        
        if display:
            self._print_table(["File", "Version (Inst/Src)", "Checksum (Inst/Src)", "Status"], table_data)
        
        return any_mismatch

    def _extract_version_from_content(self, content):
        if content is None: return "N/A"
        match = re.search(r'Version:\s*([0-9a-zA-Z.-]+)', content, re.IGNORECASE)
        return match.group(1) if match else "N/A"

    def _calculate_checksum(self, path_or_content, is_path=False, as_sudo=False):
        if is_path:
            if not os.path.exists(path_or_content): return "N/A"
            if as_sudo:
                result = self._run_command(['sha256sum', path_or_content], capture=True)
                return result.stdout.split()[0] if result and result.returncode == 0 else "N/A"
            else:
                hasher = hashlib.sha256()
                with open(path_or_content, 'rb') as f:
                    buf = f.read(65536)
                    while len(buf) > 0:
                        hasher.update(buf)
                        buf = f.read(65536)
                return hasher.hexdigest()
        else: # content is a string
            return hashlib.sha256(path_or_content.encode('utf-8')).hexdigest()

    def _print_table(self, headers, rows):
        """Prints a formatted table."""
        if not rows:
            self._echo_ok("No items to display.")
            return

        # Calculate column widths
        num_columns = len(headers)
        widths = [len(h) for h in headers]
        for row in rows:
            for i, cell in enumerate(row):
                widths[i] = max(widths[i], len(self._strip_colors(cell)))

        # Print header
        header_line = " | ".join(f"{C_CYAN}{headers[i]:<{widths[i]}}{C_NC}" for i in range(num_columns))
        print(header_line)
        separator = "-+-".join("-" * w for w in widths)
        print(separator)

        # Print rows
        for row in rows:
            row_line = " | ".join(f"{cell:<{widths[i] + len(cell) - len(self._strip_colors(cell))}}" for i, cell in enumerate(row))
            print(row_line)

if __name__ == "__main__":
    try:
        manager = PiBackendManager()
        manager.run()
    except KeyboardInterrupt:
        print("\n\nScript interrupted by user. Exiting.")
        sys.exit(1)

