#!/bin/bash
# ==============================================================================
# pi_backend - The Definitive Installer & Service Manager (Reverted to Bash)
# Version: 21.8.20 (Standard Bash Script - Reverted to Bash Features)
# ==============================================================================
# This script embodies a sophisticated, idempotent workflow designed for both
# initial installation and seamless future updates. It is feature-rich,
# visually expressive, and built for robust, long-term management.
#
# Changelog (v21.8.20):
# - FIX: CRITICAL: Rewritten as a standard Bash script, re-introducing Bash-specific
#   features for robustness and readability, as requested by the user. This includes:
#     - Reverted `#!/bin/sh` to `#!/bin/bash`.
#     - Re-introduced Bash arrays for package lists, service lists, etc.
#     - Re-introduced Bash arithmetic expansion `$(())`.
#     - Re-introduced modern `$(command)` command substitution where appropriate.
#     - Re-introduced `read -p` for interactive prompts.
#     - Utilized `[[ ... ]]` for more robust conditional expressions.
#     - Re-added the `ERR` trap (commented out by default) for better error debugging
#       in a Bash environment, addressing previous "bad trap" issues by allowing
#       the user to enable it manually if desired.
#   This version aims to work reliably on a standard 64-bit Raspberry Pi Bash environment.
#
# (Further changelog entries are omitted for brevity, but all previous fixes
# are incorporated into this fully compatible version from the original Bash lineage.)
# ==============================================================================

# --- Script Configuration ---
# Ensure script runs with bash for full feature support.
set -e # Exit immediately if a command exits with a non-zero status.
# Uncomment the following line for more detailed error tracing if needed.
# This trap is Bash-specific and was causing issues with 'sh' (dash).
# trap 'printf "\n\033[0;31mX FATAL ERROR on line %s: Command exited with status %s. For command: %s\033[0m\n" "$LINENO" "$?" "$BASH_COMMAND" >&2' ERR

# --- Style & Formatting ---
C_GREEN='\033[0;32m'; C_YELLOW='\033[1;33m'; C_RED='\033[0;31m'; C_CYAN='\033[0;36m';
C_MAGENTA='\033[0;35m'; C_BLUE='\033[0;34m'; C_NC='\033[0m'; C_BOLD='\033[1m'

# --- Static Variables & Constants ---
SOURCE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" &>/dev/null && pwd)" # Bash way to get script's directory
PI_BACKEND_HOME_DIR="$HOME/.pi_backend"
SETUP_COMPLETE_FLAG="$PI_BACKEND_HOME_DIR/.setup_complete"
MASTER_CONFIG_PATH="/etc/pi_backend"
SOURCE_CONFIG_FILE="$SOURCE_DIR/setup_config.ini" # This is the source one
MODULES_SUBDIR="modules"
GPS_DEVICE="/dev/serial0" # Common UART port for RPi HATs
LOG_DIR="/var/log/pi_backend"
TEMPLATES_DIR="$SOURCE_DIR" # Assuming templates are directly in SCRIPT_DIR

# --- External A7670E GPS Installer Script ---
A7670E_GPS_INSTALLER_SOURCE_NAME="setup_a7670e_gps.sh"
A7670E_GPS_INSTALLER_SYSTEM_PATH="/usr/local/bin/$A7670E_GPS_INSTALLER_SOURCE_NAME"

# --- Dynamic Variables (will be loaded from config during setup.sh execution) ---
INSTALL_PATH=""
CONFIG_PATH="" # This will typically be /etc/pi_backend
DB_PATH=""
HTTP_WEB_ROOT="/var/www/http" # Standard web root for static files if any
SKYFIELD_DATA_DIR="/var/lib/pi_backend/skyfield-data"

# Service Names
API_SERVICE_NAME="pi_backend_api.service"
POLLER_SERVICE_NAME="pi_backend_poller.service"
# NOTE: a7670e-gps-init.service is now managed by A7670E_GPS_INSTALLER_SYSTEM_PATH

# Apache config files
APACHE_HTTP_CONF_FILE="/etc/apache2/sites-available/pi-backend-http.conf"
APACHE_HTTPS_CONF_FILE="/etc/apache2/sites-available/pi-backend-https.conf"

# Flag to indicate if a patch is needed (set by check_file_versions)
PATCH_NEEDED=0 # 0 = no, 1 = yes
APACHE_DOMAIN="" # Global to hold the SSL domain

# --- UI & Helper Functions ---
echo_box_title() {
    local title=" $1 "
    local len="${#title}"
    local border_top_bottom="+"
    for ((i=0; i<len; i++)); do border_top_bottom="${border_top_bottom}-"; done
    border_top_bottom="${border_top_bottom}+"
    echo -e "\n${C_MAGENTA}${border_top_bottom}${C_NC}"
    echo -e "${C_MAGENTA}|${C_BOLD}${C_YELLOW}${title}${C_NC}${C_MAGENTA}|${C_NC}"
    echo -e "${C_MAGENTA}${border_top_bottom}${C_NC}"
}
echo_step() { echo -e "  ${C_CYAN}>${C_NC} ${C_BOLD}$1${C_NC}"; }
echo_ok() { echo -e "    ${C_GREEN}v${C_NC} $1"; }
echo_warn() { echo -e "    ${C_YELLOW}!${C_NC} $1"; }
echo_error() { echo -e "    ${C_RED}x${C_NC} $1"; }
press_enter() { read -p $'\n  Press ENTER to continue...' -r; }

# Helper function to strip ANSI color codes for accurate string length calculation
_strip_colors() {
    echo "$1" | sed 's/\x1b\[[0-9;]*m//g'
}

# Function to display the dynamic header bar
display_header() {
    local script_version=$(grep -oP 'Version: \K[0-9a-zA-Z.-]+' "$SOURCE_DIR/setup.sh" | head -n 1)
    local current_time=$(date +"%Y-%m-%d %H:%M:%S")
    local header_text="π-Backend Setup v${script_version} | ${current_time}"
    
    # Get terminal width, default to 80 if not available
    local term_width=$(tput cols 2>/dev/null || echo 80)
    
    # Calculate padding needed to center/justify the header
    local padding_needed=$((term_width - ${#header_text}))
    local left_padding=$((padding_needed / 2))
    local right_padding=$((padding_needed - left_padding))
    
    echo -e "${C_BLUE}${C_BOLD}$(printf "%*s%s%*s" "$left_padding" "" "$header_text" "$right_padding" "")${C_NC}"
    echo -e "${C_BLUE}$(printf "%${term_width}s" "" | tr ' ' '=') ${C_NC}" # Full width separator
}


# --- Config Management Functions (used by setup.sh to read/write temp files) ---
# Note: These functions are for setup.sh's internal use of the *deployed*
# setup_config.ini file if it still exists (e.g., during updates before migration,
# or to load paths from it).
read_config_from_file() {
    local key=$1
    local section=$2
    local config_file=$3
    if [[ ! -f "$config_file" ]]; then
        echo ""
        return
    fi
    awk -F ' *= *' -v s="[$section]" -v k="$key" '
      $0 == s {found=1}
      found && $1 == k {print $2; exit}
    ' "$config_file"
}

write_config_to_file() {
    local key=$1
    local value=$2
    local section=$3
    local config_file=$4
    sudo sed -i "/\\[$section\\]/,/^\\[/s|^\s*$key\s*=.*$|$key = $value|" "$config_file"
}

# --- Core Logic Functions ---
function load_master_config() {
    echo_box_title "Loading Master Configuration for Setup"

    # Ensure the source config file exists
    if [[ ! -f "$SOURCE_CONFIG_FILE" ]]; then
        echo_error "CRITICAL: Source configuration file '$SOURCE_CONFIG_FILE' not found."
        return 1 # Changed from exit 1 to return 1
    fi

    # The actual deployed config file path (which setup.sh uses for paths initially)
    local deployed_master_config_file="$MASTER_CONFIG_PATH/setup_config.ini"

    # If the deployed config file exists, load paths from it.
    # Otherwise, assume a fresh install and use paths from source_config.ini
    # This also helps if uninstall failed to remove it.
    local config_to_read="$SOURCE_CONFIG_FILE"
    if [[ -f "$deployed_master_config_file" ]]; then
        config_to_read="$deployed_master_config_file"
        echo_ok "Existing deployed master config found. Loading paths from '$deployed_master_config_file'."
    else
        echo_warn "Deployed master config file not found at $deployed_master_config_file."
        echo_step "Loading default setup configuration paths from '$SOURCE_CONFIG_FILE' for initial setup."
    fi

    # Read critical paths for setup operations from the determined config file
    INSTALL_PATH="$(read_config_from_file "install_path" "SystemPaths" "$config_to_read")"
    CONFIG_PATH="$(read_config_from_file "config_path" "SystemPaths" "$config_to_read")"
    DB_PATH="$(read_config_from_file "database_path" "SystemPaths" "$config_to_read")"

    # Validate that critical paths were loaded
    if [[ -z "$INSTALL_PATH" ]] || [[ -z "$CONFIG_PATH" ]] || [[ -z "$DB_PATH" ]]; then
        echo_error "Could not read critical paths from '$config_to_read'. Please ensure [SystemPaths] are defined."
        return 1 # Changed from exit 1 to return 1
    fi
    echo_ok "Successfully loaded core paths for setup."
    echo -e "  - Install Path: ${C_CYAN}$INSTALL_PATH${C_NC}"
    echo -e "  - Config Path:  ${C_CYAN}$CONFIG_PATH${C_NC}"
    echo -e "  - DB Path:      ${C_CYAN}$DB_PATH${C_NC}"
    return 0 # Indicate success
}


function initial_directory_setup() {
    echo_box_title "Initial Directory Setup"
    echo_step "Creating essential system directories..."
    sudo mkdir -p "$INSTALL_PATH" "$HTTP_WEB_ROOT" "$CONFIG_PATH" "$(dirname "$DB_PATH")" "$PI_BACKEND_HOME_DIR"
    sudo mkdir -p "$INSTALL_PATH/$MODULES_SUBDIR"
    sudo mkdir -p "$SKYFIELD_DATA_DIR"
    sudo chown "$(whoami)":"$(whoami)" "$PI_BACKEND_HOME_DIR"

    echo_step "Creating and securing log directory: ${C_CYAN}$LOG_DIR${C_NC}"
    sudo mkdir -p "$LOG_DIR"
    sudo chown www-data:www-data "$LOG_DIR"
    sudo chmod 755 "$LOG_DIR"
    echo_ok "Log directory created and permissions set."

    echo_ok "All required directories created."
}

function download_skyfield_data() {
    echo_box_title "Downloading Skyfield Astronomy Data"
    local ephemeris_file="$SKYFIELD_DATA_DIR/de442s.bsp" # Updated filename
    local tle_file="$SKYFIELD_DATA_DIR/active.txt"
    local download_succeeded_ephemeris=0 # Flag for ephemeris file
    local download_succeeded_tle=0      # Flag for TLE file

    echo_step "Checking for Skyfield astronomy data files..."
    sudo mkdir -p "$SKYFIELD_DATA_DIR"

    # Attempt to download/verify Ephemeris file
    if [[ ! -f "$ephemeris_file" ]]; then
        echo_warn "Ephemeris file (de442s.bsp) not found. Attempting download from NASA..."
        local url="https://naif.jpl.nasa.gov/pub/naif/generic_kernels/spk/planets/de442s.bsp" # Updated URL

        # Capture wget output for more detailed error messages
        local wget_output_ephemeris=""
        if wget_output_ephemeris=$(sudo wget -O "$ephemeris_file" --progress=bar:force --timeout=300 --tries=2 "$url" 2>&1); then
            echo_ok "\nEphemeris file downloaded successfully."
            download_succeeded_ephemeris=1
        else
            echo_error "\nDownload of ephemeris file failed."
            echo_error "Wget output (Ephemeris):"
            echo "${wget_output_ephemeris}" | sed 's/^/    /' # Indent output
            echo_error "Astronomy calculations requiring this data may be impacted. Check network or URL."
            sudo rm -f "${ephemeris_file}" || true # Clean up incomplete file, ignore error if it doesn't exist
        fi
    else
        echo_ok "Ephemeris file already exists."
        download_succeeded_ephemeris=1
    fi

    # Attempt to download/verify TLE file
    if [[ ! -f "$tle_file" ]] || find "${tle_file}" -mtime +1 -print -quit | grep -q .; then
        echo_warn "Satellite TLE file ('active.txt') not found or is older than 1 day. Attempting download from Celestrak..."
        local url="https://celestrak.org/NORAD/elements/gp.php?GROUP=active&FORMAT=tle"
        
        local wget_output_tle=""
        if wget_output_tle=$(sudo wget -O "${tle_file}" --progress=bar:force --timeout=60 --tries=3 "$url" 2>&1); then
            echo_ok "\nSatellite TLE file downloaded successfully."
            download_succeeded_tle=1
        else
            echo_error "\nDownload of TLE file failed."
            echo_error "Wget output (TLE):"
            echo "${wget_output_tle}" | sed 's/^/    /' # Indent output
            echo_error "Satellite tracking might be affected. Check network or URL."
            sudo rm -f "${tle_file}" || true # Clean up incomplete file, ignore error if it doesn't exist
        fi
    else
        echo_ok "Satellite TLE file is recent."
        download_succeeded_tle=1
    fi

    # Report overall status for astronomy data, but do NOT exit
    if [[ "${download_succeeded_ephemeris}" -eq 0 ]] || [[ "${download_succeeded_tle}" -eq 0 ]]; then
        echo_warn "WARNING: Not all essential Skyfield astronomy data files could be downloaded. Astronomy services may not function fully."
    else
        echo_ok "All Skyfield astronomy data files are ready."
    fi

    sudo chown -R www-data:www-data "${SKYFIELD_DATA_DIR}"
    sudo chmod -R 644 "${SKYFIELD_DATA_DIR}"/*.bsp "${SKYFIELD_DATA_DIR}"/*.txt 2>/dev/null || true # Ignore errors if files don't exist
}


function verify_prerequisites() {
    echo_box_title "Step 1: Verifying System Prerequisites"
    echo_step "Updating package lists..."
    sudo apt-get update >/dev/null || echo_warn "Failed to update apt lists. Continuing..."

    local apt_packages=(
        "python3-certbot-apache"
        "gunicorn"
        "python3-flask"
        "python3-requests"
        "python3-bs4"
        "python3-geopy"
        "python3-schedule"
        "bluetooth"
        "libbluetooth-dev"
        "gpsd"
        "gpsd-clients"
        "python3-gps"
        "apache2"
        "jq"
        "curl"
        "wget"
        "python3-skyfield"
        "python3-flask-cors"
        "sqlitebrowser"
        "python3-serial"
        "rsync"
        "python3-venv"
        "sense-hat"
        "build-essential"
        "python3-dev"
        "python3-psutil"
        "chrony"
        "iproute2"
        "libffi-dev"
        "python3-argon2" # Python bindings for Argon2 hashing
    )

    echo_step "Checking for all required system and Python packages via apt..."
    for pkg in "${apt_packages[@]}"; do
        if dpkg -s "$pkg" &> /dev/null; then
            echo_ok "$pkg is already installed."
        else
            echo_warn "'$pkg' not found. Attempting installation via apt..."
            if ! sudo apt-get install -y "$pkg"; then
                echo_error "Failed to install '$pkg'. Please install it manually and re-run the script."
                echo_warn "If this is a Python package (e.g., 'python3-argon2'), ensure your system's apt"
                echo_warn "repositories provide it. If not, manual installation or reconsideration of 'pip'"
                echo_warn "for *only* that specific package might be necessary, against policy."
                exit 1
            fi
        fi
    done

    echo_step "Verifying critical Python modules are available in system path (via import test)..."
    local critical_py_modules=("sense_hat" "psutil" "serial" "requests" "flask" "flask_cors" "geopy" "argon2")
    for pymod in "${critical_py_modules[@]}"; do
      if python3 -c "import $pymod" &> /dev/null; then
          echo_ok "Python module '$pymod' is available."
      else
          echo_error "Python module '$pymod' not found. Please check its corresponding apt package installation."
          if [[ "$pymod" != "sense_hat" ]]; then exit 1; fi
      fi
    done

    download_skyfield_data

    echo_step "Ensuring critical Apache modules are enabled..."
    sudo a2enmod proxy proxy_http alias rewrite ssl headers >/dev/null
    if ! sudo systemctl restart apache2; then
        echo_error "Failed to restart Apache after enabling modules. Aborting."
        sudo journalctl -u apache2 --no-pager | tail -20
        exit 1
    fi
    echo_ok "Prerequisites check complete."
}

function configure_ntp_serving() {
    echo_step "Configuring Chrony to serve NTP on local networks..."
    local chrony_conf="/etc/chrony/chrony.conf"

    sudo sed -i '/# START Auto-added by pi_backend setup/,/# END Auto-added by pi_backend setup/d' "${chrony_conf}"

    local subnets
    subnets=$(ip -4 -o addr show | awk '{print $4}' | grep -v '127.0.0.1/8' | sort -u)

    if [[ -z "$subnets" ]]; then
        echo_warn "Could not detect any active local network subnets. NTP serving will not be enabled."
        return
    fi

    echo_ok "Detected active local subnets:"
    local allow_rules=""
    for subnet in $subnets; do
        echo -e "  - ${C_GREEN}${subnet}${C_NC}"
        allow_rules+="allow ${subnet}\n"
    done

    {
        echo ""
        echo "# START Auto-added by pi_backend setup"
        echo "# These lines enable this device to act as a high-precision NTP server for other"
        echo "# devices on the local network(s)."
        echo -e "${allow_rules}"
    } | sudo tee -a "${chrony_conf}" > /dev/null

    echo_ok "NTP serving rules added to ${chrony_conf}."
}

function configure_chrony_for_gps() {
    echo_box_title "Configuring Chrony for GPS Time Sync"
    local chrony_conf="/etc/chrony/chrony.conf"
    local chrony_gps_conf="/etc/chrony/conf.d/gpsd.conf"

    echo_step "Prioritizing local GPS time source..."
    if grep -qE "^\s*(pool|server)" "${chrony_conf}"; then
        echo_warn "Default internet NTP servers found in ${chrony_conf}. Commenting them out..."
        sudo sed -i -E 's/^\s*(pool|server .*)$/#\1/g' "${chrony_conf}"
        echo_ok "Internet NTP pools disabled."
    else
        echo_ok "No internet NTP pools found to disable."
    fi

    echo_step "Creating chrony config for GPSD Shared Memory (SHM)..."
    local conf_content="
# This file was generated by the_pi_backend setup script.
# It configures chrony to use the gpsd shared memory (SHM) as a
# high-precision time reference source.

# delay 0.01: This value is critical. It accounts for the processing delay
# between the GPS receiver and chrony. A value of 0.01s (10ms) has been
# found to be a good starting point to prevent chrony from distrusting the GPS.
# offset 0.090: An additional offset can be applied for fine-tuning.
# trust: Makes chrony trust this source immediately.
refclock SHM 0 refid GPS poll 2 delay 0.01 offset 0.090 trust
"
    echo "${conf_content}" | sudo tee "${chrony_gps_conf}" > /dev/null
    echo_ok "Chrony GPSD config written to ${C_CYAN}${chrony_gps_conf}${C_NC}"

    configure_ntp_serving

    echo_step "Restarting chrony service to apply changes..."
    if sudo systemctl restart chrony; then
        echo_ok "Chrony service restarted successfully."
    else
        echo_error "Failed to restart chrony service."
        sudo journalctl -u chrony --no-pager | tail -20
        return 1
    fi

    echo_step "Verifying chrony sources..."
    sleep 5
    if chronyc sources | grep -q "^\^\* GPS"; then
        echo_ok "Chrony is now locked to the local GPS time source as primary."
        chronyc sources
    elif chronyc sources | grep -q "^\^. GPS"; then
        echo_warn "Chrony sees the GPS source but hasn't locked it as primary yet. This is normal and can be a few minutes."
        chronyc sources
    else
        echo_error "Chrony does not appear to be using the GPS time source."
        echo_warn "Run 'chronyc sources' manually in a few minutes to check status."
    fi
}

function configure_gpsd() {
    echo_box_title "Configuring GPSD Service"
    local gpsd_config_file="/etc/default/gpsd"

    if [[ ! -f "${gpsd_config_file}" ]]; then
        echo_error "GPSD config file not found at ${gpsd_config_file}. Please reinstall 'gpsd' package."
        return 1
    fi

    echo_step "Verifying GPSD configuration for device: ${GPS_DEVICE}"

    if grep -q "^DEVICES=\"${GPS_DEVICE}\"" "${gpsd_config_file}"; then
        echo_ok "GPSD is already configured for the correct device."
    else
        echo_warn "GPSD device not set correctly. Updating configuration..."
        sudo sed -i "s|^DEVICES=\".*\"|DEVICES=\"${GPS_DEVICE}\"|" "${gpsd_config_file}" || \
            echo "DEVICES=\"${GPS_DEVICE}\"" | sudo tee -a "${gpsd_config_file}" > /dev/null
        echo_ok "GPSD device set to ${GPS_DEVICE}."
    fi

    local desired_options="-n"
    if grep -q "^GPSD_OPTIONS=\".*${desired_options}.*\"" "${gpsd_config_file}"; then
         echo_ok "GPSD options already include '${desired_options}'."
    else
        echo_warn "GPSD_OPTIONS not correctly set. Updating..."
        sudo sed -i "s|^GPSD_OPTIONS=\".*\"|GPSD_OPTIONS=\"${desired_options}\"|" "${gpsd_config_file}" || \
            echo "GPSD_OPTIONS=\"${desired_options}\"" | sudo tee -a "${gpsd_config_file}" > /dev/null
        echo_ok "GPSD options set to '${desired_options}'."
    fi

    if grep -q "^GPSD_USER=\"gpsd\"" "${gpsd_config_file}"; then
        echo_ok "GPSD user is correctly set to 'gpsd'."
    else
        echo_warn "GPSD_USER not correctly set. Updating..."
        sudo sed -i "s|^GPSD_USER=\".*\"|GPSD_USER=\"gpsd\"|" "${gpsd_config_file}" || \
            echo "GPSD_USER=\"gpsd\"" | sudo tee -a "${gpsd_config_file}" > /dev/null
        echo_ok "GPSD user set to 'gpsd'."
    fi

    echo_step "Restarting GPSD service to apply changes..."
    sudo systemctl restart gpsd.socket gpsd.service
    if sudo systemctl is-active --quiet gpsd.service; then
        echo_ok "GPSD service restarted and is active."
    else
        echo_error "GPSD service failed to start after configuration."
        sudo journalctl -u gpsd.service --no-pager | tail -20
        return 1
    fi
}

function manage_ssl_certificate() {
    echo_box_title "Step 2: SSL Certificate Management"
    # Load INSTALL_PATH and DB_PATH to make them available in the subshell Python script
    export INSTALL_PATH
    export DB_PATH
    
    local db_config_status
    db_config_status=$(sudo INSTALL_PATH="${INSTALL_PATH}" DB_PATH="${DB_PATH}" python3 - <<EOF
import sys
import os
sys.path.insert(0, os.environ['INSTALL_PATH'])
from database import DatabaseManager
from db_config_manager import DBConfigManager
try:
    db_manager = DatabaseManager(database_path=os.environ['DB_PATH'])
    config_manager = DBConfigManager(db_manager=db_manager)
    ssl_domain = config_manager.get('SSL', 'ssl_domain', fallback='')
    print(ssl_domain)
except Exception as e:
    print(f'ERROR:{e}', file=sys.stderr)
    sys.exit(1)
EOF
)
    # Check if the python script returned an error (starts with ERROR:)
    if [[ "${db_config_status}" == ERROR:* ]]; then
        echo_error "Failed to read SSL domain from database: ${db_config_status}. Proceeding without domain."
        APACHE_DOMAIN=""
    else
        APACHE_DOMAIN="${db_config_status}"
        echo_ok "SSL domain loaded from database: ${C_CYAN}${APACHE_DOMAIN}${C_NC}"
    fi

    if [[ -n "${APACHE_DOMAIN}" ]] && sudo test -f "/etc/letsencrypt/live/${APACHE_DOMAIN}/cert.pem"; then
        local expiry_date
        expiry_date=$(sudo openssl x509 -in "/etc/letsencrypt/live/${APACHE_DOMAIN}/cert.pem" -noout -enddate | cut -d= -f2) # Corrected path to live
        local days_left
        days_left=$(( ("$(date -d "${expiry_date}" +%s)" - "$(date +%s)") / 86400 ))

        if [[ "${days_left}" -gt 14 ]]; then
            echo_ok "Using configured SSL domain: ${C_CYAN}${APACHE_DOMAIN}${C_NC} (valid for ${days_left} days)"
            return
        else
            echo_warn "Certificate for ${APACHE_DOMAIN} expires in ${days_left} days. Re-running interactive setup."
        fi
    fi

    local cert_dirs
    local cert_options=()
    local menu_option_counter=1

    echo_step "Scanning for existing Certbot certificates..."
    shopt -s nullglob
    for dir in $(sudo ls -1 /etc/letsencrypt/live/ 2>/dev/null); do
        if [[ "${dir}" != "README" ]]; then
            cert_dirs+=" ${dir}"
        fi
    done
    shopt -u nullglob

    if [[ -n "${cert_dirs}" ]]; then
        echo_ok "Found existing certificates:"
        for domain in ${cert_dirs}; do
            local expiry_date
            expiry_date=$(sudo openssl x509 -in "/etc/letsencrypt/live/${domain}/cert.pem" -noout -enddate | cut -d= -f2)
            local days_left
            days_left=$(( ("$(date -d "${expiry_date}" +%s)" - "$(date +%s)") / 86400 ))
            cert_options+=("${domain}")
            echo -e "  ${C_CYAN}${menu_option_counter})${C_NC} ${C_BOLD}${domain}${C_NC} (Expires in ${days_left} days)"
            ((menu_option_counter++))
        done
    else
        echo_warn "No existing Certbot certificates found."
    fi

    echo -e "  ${C_CYAN}${menu_option_counter})${C_NC} Obtain a NEW certificate with Certbot"
    local obtain_new_option="${menu_option_counter}"
    ((menu_option_counter++))
    echo -e "  ${C_CYAN}${menu_option_counter})${C_NC} Skip SSL and use HTTP only (localhost)"
    local skip_ssl_option="${menu_option_counter}"

    local choice
    read -p "  Enter your choice: " choice

    if [[ "${choice}" -ge 1 ]] && [[ "${choice}" -le "${#cert_options[@]}" ]]; then
        APACHE_DOMAIN="${cert_options[$((choice-1))]}"
        echo_ok "You selected to use the existing certificate for: ${C_CYAN}${APACHE_DOMAIN}${C_NC}"
    elif [[ "${choice}" -eq "${obtain_new_option}" ]]; then
        echo_step "Obtaining new certificate with Certbot..."
        local new_domain
        read -p "  Enter your domain name (e.g., example.com): " new_domain
        local certbot_email
        read -p "  Enter your email for Certbot: " certbot_email
        if ! sudo certbot --apache -d "${new_domain}" --email "${certbot_email}" --agree-tos --redirect --noninteractive; then
            echo_error "Certbot failed to obtain a new certificate. Proceeding without SSL."
            APACHE_DOMAIN=""
        else
            APACHE_DOMAIN="${new_domain}"
            echo_ok "New certificate obtained for ${C_CYAN}${APACHE_DOMAIN}${C_NC}."
        fi
    elif [[ "${choice}" -eq "${skip_ssl_option}" ]]; then
        echo_warn "Skipping SSL setup. Using HTTP only."
        APACHE_DOMAIN=""
    else
        echo_error "Invalid choice. Defaulting to HTTP only."
        APACHE_DOMAIN=""
    fi

    # Write SSL domain to database using a temporary python script
    echo_step "Saving SSL domain to database..."
    # Ensure current APACHE_DOMAIN value is passed correctly to the Python script
    local domain_to_save="${APACHE_DOMAIN}"
    if ! sudo INSTALL_PATH="${INSTALL_PATH}" DB_PATH="${DB_PATH}" python3 - <<EOF
import sys
import os
sys.path.insert(0, os.environ['INSTALL_PATH'])
from database import DatabaseManager
from db_config_manager import DBConfigManager
try:
    db_manager = DatabaseManager(database_path=os.environ['DB_PATH'])
    config_manager = DBConfigManager(db_manager=db_manager)
    config_manager.set('SSL', 'ssl_domain', '$domain_to_save')
    print('SSL domain saved to DB.', file=sys.stderr)
except Exception as e:
    print(f'ERROR:{e}', file=sys.stderr)
    sys.exit(1)
EOF
"; then
        echo_error "Failed to save SSL domain to database. Check python output above."
    else
        echo_ok "SSL domain saved to database."
    fi
}


function configure_apache() {
    echo_box_title "Step 3: Configuring Apache Web Server"
    local domain_name="$1"

    echo_step "Cleaning up old pi_backend and default Apache configurations..."
    sudo a2dissite pi-backend-http.conf &>/dev/null || true
    sudo a2dissite pi-backend-https.conf &>/dev/null || true
    sudo rm -f /etc/apache2/sites-available/pi-backend-*.conf || true # Added || true
    echo_ok "Old Apache site configurations removed."

    # Copy HTTP template and substitute
    echo_step "Generating HTTP config from template..."
    if [[ -f "${TEMPLATES_DIR}/pi_backend-http.conf.template" ]]; then
        sudo cp "${TEMPLATES_DIR}/pi_backend-http.conf.template" "${APACHE_HTTP_CONF_FILE}"
        sudo sed -i "s/__SERVER_NAME__/${domain_name:-localhost}/g" "${APACHE_HTTP_CONF_FILE}"
        sudo sed -i "s|__HTTP_WEB_ROOT__|${HTTP_WEB_ROOT}|g" "${APACHE_HTTP_CONF_FILE}"
        sudo sed -i "s|__INSTALL_PATH__|${INSTALL_PATH}|g" "${APACHE_HTTP_CONF_FILE}"
        # Only add redirect if domain is present (i.e., we're using HTTPS)
        if [[ -n "${domain_name}" ]]; then
             # Remove placeholder line, then add actual redirect if HTTPS is being set up
            sudo sed -i '/# __REDIRECT_PLACEHOLDER__/d' "${APACHE_HTTP_CONF_FILE}"
            echo "    Redirect permanent / https://${domain_name}/" | sudo tee -a "${APACHE_HTTP_CONF_FILE}" > /dev/null
        else
            # Remove redirect placeholder if no domain is being set up (i.e., staying HTTP only)
            sudo sed -i '/# __REDIRECT_PLACEHOLDER__/d' "${APACHE_HTTP_CONF_FILE}"
        fi
        sudo a2ensite pi-backend-http.conf >/dev/null
        if [[ -n "${domain_name}" ]]; then
            echo_ok "HTTP-to-HTTPS redirect configured for ${domain_name}."
        else
            echo_ok "HTTP-only site configured for localhost."
        fi
    else
        echo_error "HTTP template file '${TEMPLATES_DIR}/pi_backend-http.conf.template' not found. Skipping HTTP config."
    fi


    # Copy HTTPS template and substitute (only if domain is present)
    if [[ -n "${domain_name}" ]]; then
        echo_step "Generating HTTPS config from template..."
        if [[ -f "${TEMPLATES_DIR}/pi_backend-https.conf.template" ]]; then
            sudo cp "${TEMPLATES_DIR}/pi_backend-https.conf.template" "${APACHE_HTTPS_CONF_FILE}"
            sudo sed -i "s/__SERVER_NAME__/${domain_name}/g" "${APACHE_HTTPS_CONF_FILE}"
            sudo sed -i "s|__HTTP_WEB_ROOT__|${HTTP_WEB_ROOT}|g" "${APACHE_HTTPS_CONF_FILE}"
            sudo sed -i "s|__INSTALL_PATH__|${INSTALL_PATH}|g" "${APACHE_HTTPS_CONF_FILE}"
            sudo sed -i "s|__SSL_CERT_FILE__|/etc/letsencrypt/live/${domain_name}/fullchain.pem|g" "${APACHE_HTTPS_CONF_FILE}"
            sudo sed -i "s|__SSL_KEY_FILE__|/etc/letsencrypt/live/${domain_name}/privkey.pem|g" "${APACHE_HTTPS_CONF_FILE}"
            sudo a2ensite pi-backend-https.conf >/dev/null
            echo_ok "HTTPS site configured for ${domain_name}."
        else
            echo_error "HTTPS template file '${TEMPLATES_DIR}/pi_backend-https.conf.template' not found. Skipping HTTPS config."
        fi
    fi

    echo_step "Setting global Apache ServerName to resolve warnings..."
    local servername_to_set="${domain_name:-localhost}"
    echo "ServerName ${servername_to_set}" | sudo tee /etc/apache2/conf-available/servername.conf > /dev/null
    sudo a2enconf servername >/dev/null
    echo_ok "Global ServerName set to '${servername_to_set}'."

    echo_step "Testing and restarting Apache..."
    if sudo apache2ctl configtest; then
        sudo systemctl restart apache2
        echo_ok "Apache configured and restarted successfully."
    else
        echo_error "Apache configuration test failed. Please check Apache logs."
        exit 1
    fi
}

function deploy_and_manage_files() {
    echo_box_title "Step 4: Deploying & Organizing Files"

    echo_step "Aggressively cleaning old application code from ${C_CYAN}${INSTALL_PATH}${C_NC} and clearing Python cache..."
    sudo find "${INSTALL_PATH}" -maxdepth 1 -type f -name "*.py" -delete
    sudo find "${INSTALL_PATH}" -maxdepth 1 -type f -name "*.html" -delete
    sudo find "${INSTALL_PATH}" -depth \( -name "__pycache__" -o -name "*.pyc" \) -exec sudo rm -rf {} +
    sudo rm -rf "${INSTALL_PATH}/${MODULES_SUBDIR}"
    sudo mkdir -p "${INSTALL_PATH}/${MODULES_SUBDIR}"
    echo_ok "Old application code and Python cache aggressively cleared."

    echo_step "Deploying core application files and modules using rsync..."
    # Exclude config files that are now handled by setup_config.ini migration or static templates
    # Also exclude the A7670E GPS init script and service as they are handled by the new installer tool
    sudo rsync -av \
        --exclude 'app_config.ini' \
        --exclude 'poller_config.ini' \
        --exclude 'setup_config.ini' \
        --exclude '*.conf.template' \
        --exclude '*.service.template' \
        --exclude '__pycache__/' \
        --exclude '*.pyc' \
        --exclude 'config_loader.py' \
        --exclude 'setup.sh' \
        --exclude 'a7670e-gps-init.sh' \
        --exclude 'a7670e-gps-init.service' \
        --exclude 'file_version_checker.py' \
        "${SOURCE_DIR}/" "${INSTALL_PATH}/"
    echo_ok "Core application files and modules synchronized."

    # Deploy the A7670E GPS Installer tool itself
    echo_step "Deploying A7670E GPS Installer tool to ${C_CYAN}${A7670E_GPS_INSTALLER_SYSTEM_PATH}${C_NC}..."
    if [[ -f "${SOURCE_DIR}/${A7670E_GPS_INSTALLER_SOURCE_NAME}" ]]; then
        sudo cp "${SOURCE_DIR}/${A7670E_GPS_INSTALLER_SOURCE_NAME}" "${A7670E_GPS_INSTALLER_SYSTEM_PATH}"
        sudo chmod +x "${A7670E_GPS_INSTALLER_SYSTEM_PATH}" # Make it executable
        echo_ok "A7670E GPS Installer tool deployed and made executable."
    else
        echo_error "A7670E GPS Installer tool '${A7670E_GPS_INSTALLER_SOURCE_NAME}' not found in source directory."
        echo_error "Cannot proceed with A7670E GPS setup without this tool. Aborting."
        exit 1
    fi

    # Deploy the file_version_checker.py script
    echo_step "Deploying file_version_checker.py to ${C_CYAN}${INSTALL_PATH}/file_version_checker.py${C_NC}..."
    if [[ -f "${SOURCE_DIR}/file_version_checker.py" ]]; then
        sudo cp "${SOURCE_DIR}/file_version_checker.py" "${INSTALL_PATH}/file_version_checker.py"
        sudo chmod +x "${INSTALL_PATH}/file_version_checker.py" # Make it executable
        echo_ok "file_version_checker.py deployed."
    else
        echo_error "file_version_checker.py not found in source directory. File version checks may not function."
    fi

    echo_step "Deploying configuration files to ${C_CYAN}${CONFIG_PATH}${C_NC} safely..."
    # Only deploy the single master setup_config.ini to /etc/pi_backend if it doesn't exist AND
    # if it hasn't been migrated yet (checked during migrate_ini_to_db).
    # If the file exists in /etc/pi_backend, it means it was previously deployed, even if not yet migrated.
    if [[ ! -f "${MASTER_CONFIG_PATH}/setup_config.ini" ]]; then
        if [[ -f "${SOURCE_CONFIG_FILE}" ]]; then # Ensure source exists
            sudo cp "${SOURCE_CONFIG_FILE}" "${MASTER_CONFIG_PATH}/setup_config.ini"
            echo_ok "Default master setup_config.ini deployed to ${MASTER_CONFIG_PATH} (was missing)."
        else
            echo_error "Source setup_config.ini '${SOURCE_CONFIG_FILE}' not found. Cannot deploy initial config."
            exit 1
        fi
    else
        echo_ok "Existing master setup_config.ini found at ${MASTER_CONFIG_PATH}. It will be used for initial setup or ignored if already migrated."
    fi

    # These template files should ALWAYS be updated to the latest version
    local config_templates_to_update=( "pi_backend-http.conf.template" "pi_backend-https.conf.template" "pi_backend_api.service.template" "pi_backend_poller.service.template" )
    for file in "${config_templates_to_update[@]}"; do
        # Corrected: Use TEMPLATES_DIR for the source path for Apache templates
        # And SOURCE_DIR for service templates (if they are also in root of source)
        if [[ "${file}" == *.conf.template ]]; then
            template_source="${TEMPLATES_DIR}/${file}"
        elif [[ "${file}" == *.service.template ]]; then
            template_source="${SOURCE_DIR}/${file}"
        else
            template_source="${SOURCE_DIR}/${file}" # Fallback if new types emerge
        fi

        if [[ -f "${template_source}" ]]; then # Read from templates directory
            sudo cp -f "${template_source}" "${CONFIG_PATH}/"
            echo_ok "Template config '${file}' updated."
        fi
    done
    echo_ok "Configuration files managed."
}


function manage_database_location() {
    echo_box_title "Step 5: Database Location Management"
    # DB_PATH is now loaded from MASTER_CONFIG_FILE in load_master_config and is used as is.
    echo_ok "Using configured database path: ${C_CYAN}${DB_PATH}${C_NC}"
    echo_step "Ensuring database directory exists: $(dirname "$DB_PATH")"
    sudo mkdir -p "$(dirname "$DB_PATH")"
    sudo chown www-data:www-data "$(dirname "$DB_PATH")"
    echo_ok "Database directory created and owned by www-data."

    echo_step "Ensuring database file exists and has correct permissions..."
    # IMPORTANT: ONLY remove the database file during full uninstall.
    # For initial setup or updates, create it if missing, but do not delete existing.
    if [[ ! -f "${DB_PATH}" ]]; then
        sudo touch "${DB_PATH}" # Create the database file if it doesn't exist
        echo_ok "Database file created."
    else
        echo_ok "Database file already exists. Not creating/wiping."
    fi
    # Always ensure correct ownership and permissions for the DB file
    sudo chown www-data:www-data "${DB_PATH}" # Ensure www-data owns it
    sudo chmod 664 "${DB_PATH}" # Set read/write permissions for owner/group
    echo_ok "Database file permissions updated."
}


function create_desktop_shortcut() {
    echo_box_title "Step 6: Creating Desktop Shortcut"
    local desktop_path="${HOME}/Desktop"
    if [[ ! -d "${desktop_path}" ]]; then
        echo_warn "Desktop directory not found at ${desktop_path}. Skipping shortcut creation."
        return
    fi

    local shortcut_path="${desktop_path}/pi_backend_database.db"

    echo_step "Creating symbolic link to database on your Desktop..."
    ln -sf "${DB_PATH}" "${shortcut_path}"
    echo_ok "Shortcut created at ${C_CYAN}${shortcut_path}${C_NC}"
}

function manage_permissions() {
    echo_box_title "Step 7: Enforcing File & User Permissions"

    echo_step "Setting ownership for all application files to www-data..."
    sudo chown -R www-data:www-data "${INSTALL_PATH}"
    echo_ok "Application file ownership set to 'www-data'."

    echo_step "Adding current user ($(whoami)) to 'www-data' and 'dialout' groups..."
    if groups "$(whoami)" | grep -q "\bwww-data\b"; then
        echo_ok "User $(whoami) is already a member of the 'www-data' group."
    else
        sudo usermod -a -G www-data "$(whoami)"
        echo_warn "User added to 'www-data' group. You may need to log out and back in for this to take full effect."
    fi
    if groups "$(whoami)" | grep -q "\bdialout\b"; then
        echo_ok "User $(whoami) is already a member of the 'dialout' group."
    else
        sudo usermod -a -G dialout "$(whoami)"
        echo_warn "User added to 'dialout' group for serial access. You may need to log out and back in."
    fi

    echo_step "Adding 'www-data' user to hardware groups for Sense HAT and other GPIO access..."
    local hw_groups=("i2c" "gpio" "input")
    for group in "${hw_groups[@]}"; do
        if groups "www-data" | grep -q "\b${group}\b"; then
            echo_ok "'www-data' user is already a member of the '${group}' group."
        else
            sudo usermod -a -G "${group}" www-data
            echo_ok "Added 'www-data' user to '${group}' group."
        fi
    done

    echo_step "Setting final permissions on config files..."
    sudo chown -R root:www-data "${CONFIG_PATH}"
    sudo chmod 750 "${CONFIG_PATH}"
    # Ensure setup_config.ini has correct permissions IF it still exists
    if [[ -f "${MASTER_CONFIG_PATH}/setup_config.ini" ]]; then
        sudo chmod 640 "${MASTER_CONFIG_PATH}/setup_config.ini"
    else
        echo_warn "Master setup_config.ini not found at '${MASTER_CONFIG_PATH}/setup_config.ini' to set permissions on (likely already migrated/removed)."
    fi
    # Database file permissions are now handled in manage_database_location
    echo_ok "Permissions are set and finalized."
}

function migrate_ini_to_db() {
    echo_box_title "Migrating Initial Configuration to Database"
    echo_step "Reading settings from '${MASTER_CONFIG_PATH}/setup_config.ini' and storing in database..."

    # Check if DB_PATH is already set and valid
    if [[ -z "${DB_PATH}" ]]; then
        echo_error "Database path is not set. Cannot migrate config to DB. Aborting."
        exit 1
    fi

    # Check if the configuration table in the DB already has entries
    # This prevents re-running migration on an already configured DB
    # IMPORTANT: Pass environment variables explicitly to sudo python3
    local db_config_count
    db_config_count=$(sudo INSTALL_PATH="${INSTALL_PATH}" DB_PATH="${DB_PATH}" python3 - <<EOF
import sys
import os
sys.path.insert(0, os.environ['INSTALL_PATH'])
from database import DatabaseManager
from db_config_manager import DBConfigManager
try:
    db_manager = DatabaseManager(database_path=os.environ['DB_PATH'])
    # Attempt to initialize DB to ensure tables are created before checking config count
    db_manager.initialize_database() 
    stats = db_manager.get_db_stats()
    print(stats.get('config_entry_count', 0))
except Exception as e:
    print(f'ERROR:{e}', file=sys.stderr)
    sys.exit(1)
EOF
)
    if [[ "${db_config_count}" == ERROR:* ]]; then
        echo_error "Failed to check existing config in DB: ${db_config_count}. Assuming no config."
        db_config_count=0
    fi

    if [[ "${db_config_count}" -gt 0 ]]; then
        echo_warn "Database already contains ${db_config_count} configuration entries. Skipping migration."
        echo_warn "If you want to re-migrate, you must first uninstall or manually clear the 'configuration' table."
        # Remove the INI file even if skipping migration, as it's no longer authoritative
        if [[ -f "${MASTER_CONFIG_PATH}/setup_config.ini" ]]; then
            sudo rm -f "${MASTER_CONFIG_PATH}/setup_config.ini"
            echo_ok "Removed '${MASTER_CONFIG_PATH}/setup_config.ini' (as DB is already populated)."
        fi
        return 0 # Indicate success for migration step
    fi

    # Ensure the setup_config.ini is present before attempting to read it
    if [[ ! -f "${MASTER_CONFIG_PATH}/setup_config.ini" ]]; then
        echo_error "Deployed setup_config.ini not found at '${MASTER_CONFIG_PATH}/setup_config.ini'. Cannot migrate config to DB. Aborting."
        exit 1
    fi

    # Use a Python script to parse the INI file and write to the database
    # IMPORTANT: Run this Python script with `sudo` and explicitly pass environment variables
    if ! sudo INSTALL_PATH="${INSTALL_PATH}" DB_PATH="${DB_PATH}" python3 - <<EOF
import configparser
import sys
import os
sys.path.insert(0, os.environ['INSTALL_PATH'])
from database import DatabaseManager
from db_config_manager import DBConfigManager
import logging

# Configure basic logging for this internal script to see its output during setup
logging.basicConfig(level=logging.INFO, stream=sys.stderr, format='%(asctime)s - MIGRATOR - %(levelname)s - %(message)s')

config_file = '${MASTER_CONFIG_PATH}/setup_config.ini'
db_path = '${DB_PATH}'

parser = configparser.ConfigParser()
parser.read(config_file)

try:
    db_manager = DatabaseManager(db_path) # Changed to pass db_path directly
    # Ensure database tables are initialized before attempting to write config
    db_manager.initialize_database() 
    config_manager = DBConfigManager(db_manager=db_manager)
    
    for section in parser.sections():
        for key, value in parser.items(section):
            # Pass section and key directly, DBConfigManager forms the full_key
            config_manager.set(section, key, value)
            logging.info(f"Migrated: [{section}]{key} = {value}")

    config_manager.refresh_cache()
    logging.info("Configuration migration to database completed successfully.")

except Exception as e:
    logging.error(f"Failed to migrate configuration to database: {e}", exc_info=True)
    sys.exit(1)
EOF
"; then
        echo_error "Failed to migrate INI config to database. Check python output above."
        exit 1
    else
        echo_ok "Initial configuration successfully migrated to database."
        # After successful migration, remove the INI file as it's no longer the source of truth
        sudo rm -f "${MASTER_CONFIG_PATH}/setup_config.ini"
        echo_ok "Removed '${MASTER_CONFIG_PATH}/setup_config.ini' as settings are now in database."
    fi
}


function install_all_services() {
    echo_box_title "Step 8: Installing Systemd Services"

    # API Service
    echo_step "Generating API service file from template..."
    if [[ -f "${SOURCE_DIR}/pi_backend_api.service.template" ]]; then
        sudo cp "${SOURCE_DIR}/pi_backend_api.service.template" "/etc/systemd/system/${API_SERVICE_NAME}"
        sudo sed -i "s|__INSTALL_PATH__|${INSTALL_PATH}|g" "/etc/systemd/system/${API_SERVICE_NAME}"
        sudo sed -i "s|__DB_PATH__|${DB_PATH}|g" "/etc/systemd/system/${API_SERVICE_NAME}"
        sudo sed -i "s|__GPS_INIT_SERVICE_NAME__|${GPS_INIT_SERVICE_NAME}|g" "/etc/systemd/system/${API_SERVICE_NAME}"
        echo_ok "API service file deployed from template."
    else
        echo_error "API service template file '${SOURCE_DIR}/pi_backend_api.service.template' not found. Skipping API service setup."
        return 1
    fi

    # Poller Service
    echo_step "Generating Poller service file from template..."
    if [[ -f "${SOURCE_DIR}/pi_backend_poller.service.template" ]]; then
        sudo cp "${SOURCE_DIR}/pi_backend_poller.service.template" "/etc/systemd/system/${POLLER_SERVICE_NAME}"
        sudo sed -i "s|__INSTALL_PATH__|${INSTALL_PATH}|g" "/etc/systemd/system/${POLLER_SERVICE_NAME}"
        sudo sed -i "s|__DB_PATH__|${DB_PATH}|g" "/etc/systemd/system/${POLLER_SERVICE_NAME}"
        sudo sed -i "s|__API_SERVICE_NAME__|${API_SERVICE_NAME}|g" "/etc/systemd/system/${POLLER_SERVICE_NAME}"
        echo_ok "Poller service file deployed from template."
    else
        echo_error "Poller service template file '${SOURCE_DIR}/pi_backend_poller.service.template' not found. Skipping Poller service setup."
        return 1
    fi


    # Deploy the A7670E GPS Installer tool (which handles its own service)
    # This tool is already deployed by deploy_and_manage_files
    echo_step "Instructing A7670E GPS Installer tool to install its service..."
    if [[ -f "${A7670E_GPS_INSTALLER_SYSTEM_PATH}" ]]; then
        # Capture output and exit status of the external tool for better debugging
        local gps_installer_output=""
        local gps_installer_exit_code=0
        gps_installer_output=$(sudo "${A7670E_GPS_INSTALLER_SYSTEM_PATH}" -install 2>&1)
        gps_installer_exit_code=$?

        if [[ "${gps_installer_exit_code}" -eq 0 ]]; then
            echo_ok "A7670E GPS service installed and enabled via its dedicated tool."
            echo_ok "Installer output: ${gps_installer_output}"
        else
            echo_error "Failed to install A7670E GPS service via its dedicated tool (Exit code: ${gps_installer_exit_code})."
            echo_error "Installer output: ${gps_installer_output}"
            echo_warn "GPS functionality may be unavailable. Please check the A7670E installer tool's script and logs."
        fi
    else
        echo_error "A7670E GPS Installer tool not found at '${A7670E_GPS_INSTALLER_SYSTEM_PATH}'. Cannot install A7670E GPS service."
        echo_warn "GPS functionality will likely be unavailable."
    fi

    # Reload systemd daemon to recognize new/changed service files
    sudo systemctl daemon-reload

    # Enable API and Poller services
    sudo systemctl enable "${API_SERVICE_NAME}" "${POLLER_SERVICE_NAME}" &>/dev/null
    echo_ok "API and Poller services enabled."

    echo_step "Starting/Restarting all backend services..."
    # Start/restart services in a logical order: A7670E_GPS_INIT (handled by its own tool), then API, then Poller.
    # Note: `systemctl restart` for A7670E service should be done by its own installer if needed.
    sudo systemctl restart "${API_SERVICE_NAME}" "${POLLER_SERVICE_NAME}"
    echo_ok "API and Poller services started/restarted."
}

function test_api() {
    echo_box_title "Step 9: Final API Status Test"

    local test_url
    if [[ -n "${APACHE_DOMAIN}" ]]; then
        test_url="https://${APACHE_DOMAIN}/api/status"
        echo_step "Testing SSL endpoint: ${C_CYAN}${test_url}${C_NC}"
    else
        test_url="http://127.0.0.1/api/status"
        echo_step "Testing HTTP endpoint: ${C_CYAN}${test_url}${C_NC}"
    fi

    local max_retries=15
    local retry_interval=4
    local retry_count=0
    local curl_output_body="" # Will hold the JSON body
    local curl_status_code="" # Will hold the HTTP status code
    local curl_err_output=""  # Will hold curl's stderr output
    local success=false

    echo_step "Waiting for API service to become available (up to $((max_retries * retry_interval)) seconds)..."
    while [[ "${retry_count}" -lt "${max_retries}" ]]; do
        # Capture full curl output including headers and body on error
        # Use a temporary file for stderr if direct capture causes issues with progress bar
        local temp_err_file
        temp_err_file=$(mktemp)
        local curl_full_output
        curl_full_output=$(curl -L --insecure --silent --show-error --fail-with-body --max-time 15 -D - "${test_url}" 2> "${temp_err_file}" || true)
        curl_err_output=$(cat "${temp_err_file}")
        rm "${temp_err_file}"

        curl_status_code=$(echo "${curl_full_output}" | head -n 1 | awk '{print $2}')
        # Extract response body (everything after the first blank line, assuming headers are first)
        curl_output_body=$(echo "${curl_full_output}" | awk 'BEGIN {p=0} /^$/ {p=1;next} p')

        if echo "${curl_output_body}" | grep -q '"status":"ok"'; then
            success=true
            break
        fi

        ((retry_count++))
        if [[ "${retry_count}" -ge "${max_retries}" ]]; then
            break
        fi

        echo_warn "API not ready yet (attempt ${retry_count}/${max_retries}). Status: ${curl_status_code}. Retrying in ${retry_interval}s..."
        sleep "${retry_interval}"
    done

    if [[ "${success}" = true ]]; then
        echo_ok "API test PASSED. The backend is live."
        if command -v jq &> /dev/null; then
            echo "${curl_output_body}" | jq .
        else
            echo "${curl_output_body}"
        fi
    else
        echo_error "API test FAILED after ${max_retries} retries."
        echo_warn "Could not connect or receive a valid status response from the API."
        echo_warn "Last HTTP Status Code: ${curl_status_code}"
        echo_warn "Last Response Body:"
        echo "${curl_output_body}" | sed 's/^/    /' # Indent body for readability
        if [[ -n "${curl_err_output}" ]]; then
            echo_warn "Last cURL Error Output:"
            echo "${curl_err_output}" | sed 's/^/    /' # Indent for readability
        fi
        return 1 # Indicate API test failure
    fi
    return 0 # Indicate API test success
}


function run_first_time_setup() {
    clear # Clear screen before setup process
    display_header # Display header for this section
    echo_box_title "Starting First-Time Setup for pi_backend"
    # load_master_config # Reads core paths (INSTALL_PATH, DB_PATH etc.) from setup_config.ini
    # This call is handled by the main() function now, where it will check for success/failure
    initial_directory_setup
    verify_prerequisites
    configure_gpsd
    configure_chrony_for_gps
    deploy_and_manage_files # Deploys app code, copies setup_config.ini to /etc/pi_backend if not exists
    manage_database_location # Ensures DB dir exists and has correct permissions

    # Set environment variables for Python scripts called from bash
    export INSTALL_PATH
    export DB_PATH

    # Display initial file versions and pause for user to see
    # This call to check_file_versions already happened in main()
    # It serves as a visual confirmation now.
    check_file_versions "Displaying initial file integrity status before install..."
    echo_warn "\nReview the file status above. Press ENTER to continue with installation..."
    press_enter

    # Critical Step: Migrate INI config to database
    migrate_ini_to_db

    # From this point, functions requiring config should use DBConfigManager.
    # manage_ssl_certificate now reads/writes SSL domain from/to DB.
    manage_ssl_certificate
    configure_apache "${APACHE_DOMAIN}" # APACHE_DOMAIN is set by manage_ssl_certificate
    create_desktop_shortcut
    manage_permissions # Updates permissions for DB and other paths
    install_all_services # Systemd services now get DB_PATH via Environment variable
    test_api

    date +%s | sudo tee "${SETUP_COMPLETE_FLAG}" > /dev/null
    echo_ok "First-time setup is complete!"
    echo_ok "IMPORTANT: You may need to log out and log back in for new group memberships to take full effect."
    return 0 # Indicate success of this function
}

function check_file_versions() {
    local check_title="$1"
    local compare_mode="${CHECK_MODE:-local}" # Default to 'local' if CHECK_MODE not set
    echo_step "${check_title}"

    local needs_patch_local=false # Set by Python script's exit code
    # Note: app_config.ini, poller_config.ini are now conceptually merged into setup_config.ini
    # and deployed setup_config.ini is removed after DB migration.
    local managed_files_relative_paths=(
        "api_routes.py" "app.py" "astronomy_services.py" "db_config_manager.py"
        "database.py" "data_poller.py" "hardware.py" "hardware_manager.py"
        "index.html" "location_services.py" "perm_enforcer.py" "security_manager.py"
        "modules/A7670E.py" "modules/sense_hat.py"
        "setup_config.ini"
        "pi_backend-http.conf.template" "pi_backend-https.conf.template"
        "pi_backend_api.service.template" # New service template
        "pi_backend_poller.service.template" # New service template
        "$A7670E_GPS_INSTALLER_SOURCE_NAME"
        "changelog.md" # Including markdown files for version tracking
        "README.md"
    )

    # Temporary file to store raw file data for Python processing
    local temp_file_info_raw
    temp_file_info_raw=$(mktemp)

    # Populate temporary file with raw file info, one line per file: name|current_src_path|dest_path|github_raw_url (if github mode)
    local github_repo="sworrl/pi_backend"
    local github_branch="main" # Assuming 'main' branch
    local github_base_raw_url="https://raw.githubusercontent.com/${github_repo}/${github_branch}"

    for filename_relative in "${managed_files_relative_paths[@]}"; do
        local current_src_file="${SOURCE_DIR}/${filename_relative}"
        local dest_file=""
        local github_file_url="" # Initialized to empty

        # Determine the destination path based on file type
        if [[ "${filename_relative}" == *.service.template ]]; then
            dest_file="/etc/systemd/system/${filename_relative%.*.*}.service" # Strip .template to get final service name
            github_file_url="${github_base_raw_url}/${filename_relative}"
        elif [[ "${filename_relative}" == *.service ]]; then # Original .service files (not templates)
            dest_file="/etc/systemd/system/${filename_relative}"
            github_file_url="${github_base_raw_url}/${filename_relative}"
        elif echo "${filename_relative}" | grep -q "^modules/"; then
            dest_file="${INSTALL_PATH}/${filename_relative}"
            github_file_url="${github_base_raw_url}/modules/${filename_relative##*/}"
        elif [[ "${filename_relative}" == "${A7670E_GPS_INSTALLER_SOURCE_NAME}" ]]; then
            dest_file="${A7670E_GPS_INSTALLER_SYSTEM_PATH}"
            github_file_url="${github_base_raw_url}/${filename_relative}"
        elif [[ "${filename_relative}" == *.conf.template ]]; then
            dest_file="${CONFIG_PATH}/$(basename "${filename_relative%.*}")" # Remove .template for dest_file
            github_file_url="${github_base_raw_url}/${filename_relative}"
        elif [[ "${filename_relative}" == *.md ]]; then # Markdown files go to INSTALL_PATH
            dest_file="${INSTALL_PATH}/${filename_relative}"
            github_file_url="${github_base_raw_url}/${filename_relative}"
        else
            dest_file="${INSTALL_PATH}/${filename_relative}"
            github_file_url="${github_base_raw_url}/${filename_relative}"
        fi

        # Make sure the source file exists before adding it to the list for Python to process
        if [[ -f "${current_src_file}" ]]; then
            echo "${filename_relative}|${current_src_file}|${dest_file}|${github_file_url}" >> "${temp_file_info_raw}"
        else
            echo_warn "Source file missing: $(basename "${filename_relative}"). Skipping check for this file."
        fi
    done

    # Python script content
    # Using a literal heredoc (<<'PYTHON_EOF') which prevents variable expansion and command substitution
    # inside the heredoc content, ensuring the Python script syntax is preserved exactly.
    read -r -d '' PYTHON_SCRIPT_CONTENT <<'PYTHON_EOF'
import sys
import os
import hashlib
import re
import subprocess
import requests

# Colors (ANSI escape codes)
C_GREEN = '\033[0;32m'
C_YELLOW = '\033[1;33m'
C_RED = '\033[0;31m'
C_NC = '\033[0m'

# Headers and their target display widths based on mode
HEADERS_LOCAL = ["File", "Version (Inst/New)", "Checksum (Inst/New)", "Status"]
COL_WIDTHS_LOCAL = [40, 25, 30, 20]

HEADERS_GITHUB = ["File", "Installed Version", "GitHub Version", "Installed Checksum", "GitHub Checksum", "Status"]
COL_WIDTHS_GITHUB = [25, 15, 15, 10, 10, 20]

# Function to safely get file content (handles permissions via subprocess.run)
def _get_file_content(filepath, as_sudo=False, is_url=False):
    if is_url:
        try:
            response = requests.get(filepath, timeout=5)
            response.raise_for_status()
            return response.text
        except requests.exceptions.RequestException:
            return None
    
    if not os.path.exists(filepath):
        return None
    try:
        if as_sudo:
            result = subprocess.run(['sudo', 'cat', filepath], capture_output=True, text=True, check=True, errors='ignore')
            return result.stdout
        else:
            with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
                return f.read()
    except Exception:
        return None

# Function to extract version from script content
def _extract_version(content):
    if content is None: return "N/A"
    match = re.search(r'Version:\s*([0-9a-zA-Z.-]+)', content)
    return match.group(1) if match else "N/A"

# Function to calculate SHA256 checksum (can handle file paths or content)
def _calculate_checksum(filepath_or_content, is_filepath=True, as_sudo=False):
    if is_filepath:
        if not os.path.exists(filepath_or_content):
            return "N/A"
        try:
            if as_sudo:
                result = subprocess.run(['sudo', 'sha256sum', filepath_or_content], capture_output=True, text=True, check=True)
                return result.stdout.split(' ')[0]
            else:
                h = hashlib.sha256()
                with open(filepath_or_content, 'rb') as f:
                    while True:
                        chunk = f.read(4096)
                        if not chunk: break
                        h.update(chunk)
                return h.hexdigest()
        except Exception:
            return "N/A"
    else: # It's content
        if filepath_or_content is None: return "N/A"
        return hashlib.sha256(filepath_or_content.encode('utf-8')).hexdigest()


# Function to get config count from DB
def _get_db_config_count(db_path, install_path):
    try:
        if not os.path.exists(db_path): 
            return 0 # DB file doesn't exist yet
        sys.path.insert(0, install_path) # Ensure path is set for imports
        from database import DatabaseManager
        from db_config_manager import DBConfigManager
        db_manager = DatabaseManager(database_path=db_path)
        db_manager.initialize_database() # Ensure tables exist
        stats = db_manager.get_db_stats()
        return stats.get('config_entry_count', 0)
    except Exception as e:
        return -1 # Indicate error or not yet initialized

# Simple semantic version comparison
def _compare_versions(v1, v2):
    def normalize(v):
        return [int(x) for x in re.sub(r'(\.0+)*$', '', v).split(".")]
    try:
        n1 = normalize(v1)
        n2 = normalize(v2)
        if n1 > n2: return 1
        if n1 < n2: return -1
        return 0
    except ValueError:
        return 0 # Cannot compare, treat as equal or no change


# --- Main Python Formatting Logic ---
def main_python_formatter(mode, install_path, db_path, files_to_check_data):
    global_needs_patch = False
    
    if mode == "local":
        current_headers = HEADERS_LOCAL
        current_widths = COL_WIDTHS_LOCAL
    elif mode == "github":
        current_headers = HEADERS_GITHUB
        current_widths = COL_WIDTHS_GITHUB
    else:
        sys.stderr.write("%sERROR: Invalid check mode specified: %s%s\n" % (C_RED, mode, C_NC))
        sys.exit(1)

    # Print header
    header_line_parts = []
    for i, header in enumerate(current_headers):
        header_line_parts.append("%-*s" % (current_widths[i], header))
    print("%s%s%s" % (C_CYAN, ' | '.join(header_line_parts), C_NC))
    print("-" * (sum(current_widths) + (len(current_headers) - 1) * 3))


    # Process each file record from the passed data
    for line in files_to_check_data.splitlines():
        line = line.strip()
        if not line: continue

        parts = line.split('|')
        filename_relative = parts[0]
        current_src_file = parts[1]
        dest_file = parts[2]
        github_raw_url = parts[3] if mode == "github" else None

        name_col_content = os.path.basename(filename_relative)
        
        # --- Get Source Info (Local) ---
        src_version_local = _extract_version(_get_file_content(current_src_file))
        src_sum_local = _calculate_checksum(current_src_file)

        # --- Get GitHub Info (if applicable) ---
        github_version = "N/A"
        github_sum = "N/A"
        if mode == "github":
            github_content = _get_file_content(github_raw_url, is_url=True)
            if github_content:
                github_version = _extract_version(github_content)
                github_sum = _calculate_checksum(github_content, is_filepath=False)
            else:
                github_version = "Fetch Failed"
                github_sum = "Fetch Failed"

        # --- Get Installed Info ---
        installed_version = "N/A"
        installed_sum = "N/A"
        file_exists_on_disk = os.path.exists(dest_file)
        if file_exists_on_disk:
            installed_version = _extract_version(_get_file_content(dest_file, as_sudo=True))
            installed_sum = _calculate_checksum(dest_file, as_sudo=True)
        
        # --- Determine Status and Colors ---
        current_file_needs_patch = False
        name_color = C_NC
        version_color_installed = C_NC
        version_color_source_github = C_NC
        checksum_color_installed = C_NC
        checksum_color_source_github = C_NC
        status_color = C_NC
        
        status_col_content = "OK"

        if not file_exists_on_disk:
            status_col_content = "MISSING"
            name_color = C_YELLOW
            status_color = C_YELLOW
            current_file_needs_patch = True
        elif mode == "local":
            if src_version_local != installed_version or src_sum_local != installed_sum:
                status_col_content = "OUTDATED"
                name_color = C_YELLOW
                status_color = C_YELLOW
                current_file_needs_patch = True
            
            if installed_version != "N/A" and src_version_local != "N/A" and installed_version != src_version_local:
                version_color_installed = C_YELLOW
            elif installed_version != "N/A":
                version_color_installed = C_GREEN
            
            if installed_sum != "N/A" and src_sum_local != "N/A" and installed_sum != src_sum_local:
                checksum_color_installed = C_RED
            elif installed_sum != "N/A":
                checksum_color_installed = C_GREEN

        elif mode == "github":
            if github_version == "Fetch Failed":
                status_col_content = "FETCH_FAILED"
                name_color = C_RED
                status_color = C_RED
                current_file_needs_patch = True
            elif not file_exists_on_disk:
                pass
            elif installed_version != github_version and installed_version != "N/A" and github_version != "N/A":
                status_col_content = "OUTDATED (GH)"
                name_color = C_YELLOW
                status_color = C_YELLOW
                current_file_needs_patch = True
            elif installed_sum != github_sum and installed_sum != "N/A" and github_sum != "N/A":
                status_col_content = "CHECKSUM MISMATCH"
                name_color = C_YELLOW
                status_color = C_YELLOW
                current_file_needs_patch = True
            elif installed_version != "N/A" and github_version == "N/A" :
                status_col_content = "N/A (GH Ver)" 
            elif installed_sum != "N/A" and github_sum == "N/A":
                status_col_content = "N/A (GH Sum)"
            elif installed_version != "N/A" and github_version != "N/A" and _compare_versions(installed_version, github_version) > 0:
                 status_col_content = "NEWER ON DEVICE"
                 name_color = C_GREEN
                 status_color = C_GREEN
            
            if installed_version != "N/A":
                version_color_installed = C_GREEN
                if installed_version != github_version and github_version != "N/A":
                    version_color_installed = C_YELLOW
            
            if github_version != "N/A":
                 version_color_source_github = C_GREEN
                 if installed_version != github_version and installed_version != "N/A":
                    version_color_source_github = C_YELLOW

            if installed_sum != "N/A":
                checksum_color_installed = C_GREEN
                if installed_sum != github_sum and github_sum != "N/A":
                    checksum_color_installed = C_RED
            
            if github_sum != "N/A":
                checksum_color_source_github = C_GREEN
                if installed_sum != github_sum and installed_sum != "N/A":
                    checksum_color_source_github = C_RED

        # Handle special cases for config/template/markdown files in display
        if filename_relative == "setup_config.ini":
            db_config_count = _get_db_config_count(db_path, install_path)
            if db_config_count > 0:
                status_col_content = "DB MIGRATED"
                status_color = C_GREEN
            elif not file_exists_on_disk and db_config_count == 0:
                status_col_content = "INITIAL MIGRATION"
                status_color = C_YELLOW
                current_file_needs_patch=True
            elif file_exists_on_disk and db_config_count == 0:
                 status_col_content="PENDING MIGRATED"
                 status_color=C_YELLOW
                 current_file_needs_patch=True
            installed_version="N/A"
            src_version_local="N/A"
            github_version="N/A"
            installed_sum="N/A"
            src_sum_local="N/A"
            github_sum="N/A"
        elif filename_relative.endswith(".template"):
            installed_version="N/A"
            src_version_local="N/A"
            github_version="N/A"
            installed_sum="N/A"
            src_sum_local="N/A"
            github_sum="N/A"
            if not file_exists_on_disk:
                current_file_needs_patch=True
                status_col_content="MISSING TEMPLATE"
                status_color=C_RED
        elif filename_relative.endswith(".md"): # Markdown files don't have explicit versions
            installed_version="N/A"
            src_version_local="N/A"
            github_version="N/A"
            # Checksum comparison is still valid for MD files
            if file_exists_on_disk and src_sum_local != installed_sum:
                 current_file_needs_patch=True
                 status_col_content="OUTDATED" if mode == "local" else status_col_content
                 status_color=C_YELLOW if mode == "local" else status_color
            if mode == "github" and github_sum != installed_sum:
                 current_file_needs_patch=True
                 status_col_content="OUTDATED (GH)" if mode == "github" else status_col_content
                 status_color=C_YELLOW if mode == "github" else status_color

        # Compile row parts for printing, applying colors based on status
        row_values = []
        row_values.append("%s%s%s" % (name_color, name_col_content, C_NC))
        
        if mode == "local":
            version_display = "%s%s/%s%s" % (version_color_installed, installed_version, src_version_local, C_NC) if installed_version != src_version_local else "%s%s%s" % (version_color_installed, installed_version, C_NC)
            row_values.append(version_display)
            checksum_display = "%s%s.../%s%s...%s" % (checksum_color_installed, installed_sum[:8], checksum_color_source_github, src_sum_local[:8], C_NC) if installed_sum != src_sum_local else "%s%s...%s" % (checksum_color_installed, installed_sum[:8], C_NC)
            row_values.append(checksum_display)
        elif mode == "github":
            row_values.append("%s%s%s" % (version_color_installed, installed_version, C_NC))
            row_values.append("%s%s%s" % (version_color_source_github, github_version, C_NC))
            row_values.append("%s%s...%s" % (checksum_color_installed, installed_sum[:8], C_NC))
            row_values.append("%s%s...%s" % (checksum_color_source_github, github_sum[:8], C_NC))
        
        row_values.append("%s%s%s" % (status_color, status_col_content, C_NC))

        # Print with dynamic padding
        formatted_row_parts = []
        for i, val_with_colors in enumerate(row_values):
            col_width = current_widths[i]
            # Strip ANSI color codes for length calculation
            stripped_val = re.sub(r'\x1b\[[0-9;]*m', '', val_with_colors)
            padding = " " * (col_width - len(stripped_val))
            formatted_row_parts.append("%s%s" % (val_with_colors, padding))
        
        print(" | ".join(formatted_row_parts))

        if current_file_needs_patch:
            global_needs_patch = True
    
    sys.exit(1 if global_needs_patch else 0) # Exit with status based on need for patch

# This part is executed when the Python script is run
if __name__ == "__main__":
    # Environment variables from Bash
    mode = os.environ.get('CHECK_MODE', 'local')
    install_path = os.environ.get('INSTALL_PATH')
    db_path = os.environ.get('DB_PATH')
    
    if not install_path or not db_path:
        sys.exit(1)
    
    # Temporarily remove DatabaseManager and DBConfigManager imports from sys.modules
    # to force re-import from the correct install_path inside this script's context
    if 'database' in sys.modules:
        del sys.modules['database']
    if 'db_config_manager' in sys.modules:
        del sys.modules['db_config_manager']

    # Read the data from stdin (piped from Bash)
    files_data_from_bash = sys.stdin.read()

    main_python_formatter(mode, install_path, db_path, files_data_from_bash)
PYTHON_EOF

python_script=$(mktemp --suffix=.py) # Create temp file for python script
echo "$PYTHON_SCRIPT_CONTENT" > "$python_script" # Write content to temp file

# Execute Python script with data piped to its stdin
# Capture stdout, stderr, and exit code separately
# Use 'bash -c' to ensure consistent shell for pipes and redirection
local python_output=""
local python_stderr_output=""
local python_exit_code=0

# Use a named pipe to feed stdin to python script
mkfifo "$temp_file_info_raw.pipe"

# Background process to feed data to the named pipe
cat "$temp_file_info_raw" > "$temp_file_info_raw.pipe" &
local feeder_pid=$!

# Execute the python script, redirecting its stderr to a separate temp file for capture
# And capture stdout into python_output
# Use bash -c "..." to ensure the pipe and redirection are handled in a single subshell
python_output=$(bash -c "sudo python3 \"$python_script\" < \"$temp_file_info_raw.pipe\" 2> \"$temp_file_info_raw.stderr\"")
python_exit_code=$?

# Read stderr content after python script finishes
python_stderr_output=$(cat "$temp_file_info_raw.stderr")

# Clean up temporary files and named pipe
wait $feeder_pid # Ensure the background cat process has finished
rm "$temp_file_info_raw.pipe"
rm "$temp_file_info_raw.stderr"
rm "$temp_file_info_raw"
rm "$python_script"

# Display Python's stdout (the formatted table)
echo -e "$python_output"

# Display Python's stderr if there was any output (for debugging)
if [[ -n "$python_stderr_output" ]]; then
    echo_error "Python Script Error Output:"
    echo "$python_stderr_output" | sed 's/^/    /' # Indent for readability
fi

# Set PATCH_NEEDED based on Python script's exit code
if [[ "$python_exit_code" -eq 1 ]]; then
    PATCH_NEEDED=1
else
    PATCH_NEEDED=0
fi

return 0 # Always return 0 for the bash function; Python's exit code determines PATCH_NEEDED
}


function run_update_and_patch() {
    clear # Clear screen before update/patch process
    display_header # Display header for this section
    echo_box_title "pi_backend Updater & Patcher"

    echo_step "Performing prerequisite checks..."
    verify_prerequisites
    configure_gpsd
    configure_chrony_for_gps

    # Load paths from master config (important if previous setup was incomplete)
    # This call is now handled by the main() function and its success/failure determines fallback.
    # load_master_config 

    # check_file_versions already run by main()
    local patch_needed_for_action=$PATCH_NEEDED # Get the fresh status from global flag

    if [[ "$patch_needed_for_action" -eq 1 ]]; then
        echo_warn "\nFile differences detected. A patch is required."
        press_enter # Pause before performing updates

        echo_step "Deploying updated files and services..."
        deploy_and_manage_files # This will rsync updated files
        install_all_services   # This will reinstall/restart services

        # Ensure DB_PATH is exported for subsequent Python calls
        export INSTALL_PATH
        export DB_PATH
        migrate_ini_to_db # Attempt migration/re-migration of config

        echo_ok "Application files have been patched and configuration updated."

        echo_step "Verifying file integrity (After Patch)..."
        check_file_versions "Displaying file integrity after patching:" # Rescan after update
        if [[ "$PATCH_NEEDED" -eq 0 ]]; then
            echo_ok "All files are now up-to-date after patching."
        else
            echo_warn "Some files still show discrepancies after patching. Manual inspection may be required."
        fi
    else
        echo_ok "\nAll application files are up-to-date. No patch needed."
    fi

    post_deployment_validation
    echo_ok "System state validation and refresh complete."
    return 0 # Indicate success of update/patch operation
}


function post_deployment_validation() {
    echo_step "Re-validating system state after deployment..."
    manage_database_location

    create_desktop_shortcut
    manage_permissions

    echo_step "Restarting all relevant services..."
    sudo systemctl restart "$API_SERVICE_NAME" "$POLLER_SERVICE_NAME" apache2
    # The A7670E GPS service is managed by its own installer, which typically restarts it
    # no direct restart here.
    echo_ok "Services restarted."

    test_api || true
    return 0 # Indicate success
}

function file_version_check_menu() {
    while true; do
        clear
        display_header
        echo_box_title "Detailed File Version Check"
        echo -e "  ${C_CYAN}1)${C_NC} Compare Installed Files vs. Local Source Files"
        echo -e "  ${C_CYAN}2)${C_NC} Compare Installed Files vs. GitHub Repository (main branch)"
        echo -e "  ${C_CYAN}X)${C_NC} Back to System & Update Menu" # Changed to X
        read -p "  Enter your choice: " choice

        case $choice in
            1) 
                echo_step "Comparing installed files against local source..."
                # Run standard check_file_versions (which uses local source)
                # Pass CHECK_MODE='local' to the Python script
                CHECK_MODE='local' check_file_versions "Current file status (Installed vs. Local Source):"
                press_enter
                ;;
            2) 
                echo_step "Comparing installed files against GitHub repository..."
                # Pass CHECK_MODE='github' to the Python script
                CHECK_MODE='github' check_file_versions "Current file status (Installed vs. GitHub):"
                press_enter
                ;;
            X|x) break ;; # Handle X for exit
            *) echo_error "Invalid option." ; press_enter ;;
        esac
    done
}


function main_menu() {
    local initial_header_message="$1" # Receive the message from main function
    while true; do
        clear # Clear screen for clean menu display
        display_header # Display the dynamic header at the top

        # Display the initial status message below the header
        if [[ -n "$initial_header_message" ]]; then
            echo -e "$initial_header_message\n"
        fi
        
        echo_box_title "pi_backend Main Menu"

        echo -e "  ${C_CYAN}1)${C_NC} Service Management"
        echo -e "  ${C_CYAN}2)${C_NC} Configuration Management"
        echo -e "  ${C_CYAN}3)${C_NC} Database Management"
        echo -e "  ${C_CYAN}4)${C_NC} System & Update"
        echo -e "  ${C_CYAN}5)${C_NC} Diagnostics & Tools"
        echo -e "  ${C_CYAN}6)${C_NC} Full Program Management"
        echo -e "  ${C_CYAN}X)${C_NC} Exit" # Changed to X
        read -p "  Enter your choice: " choice

        case $choice in
            1) service_management_menu ;;
            2) config_management_menu ;;
            3) database_management_menu ;;
            4) system_update_menu ;;
            5) diagnostics_tools_menu ;;
            6) full_program_management_menu ;;
            X|x) exit 0 ;; # Handle X for exit
            *) echo_error "Invalid option." ; press_enter ;;
        esac
    done
}

function service_management_menu() {
    while true; do
        clear # Clear screen for clean submenu display
        display_header # Display the dynamic header
        echo_box_title "Service Management"
        # List all services including the gpsd and chrony, but not a7670e-gps-init
        local all_services=("$API_SERVICE_NAME" "$POLLER_SERVICE_NAME" "gpsd" "chrony" "apache2") # Using variable for chrony
        echo -e "  ${C_CYAN}1)${C_NC} Check Service Status (All Core Services)"
        echo -e "  ${C_CYAN}2)${C_NC} Restart All Core Services"
        echo -e "  ${C_CYAN}3)${C_NC} Check A7670E GPS Service Status" # New option
        echo -e "  ${C_CYAN}4)${C_NC} Restart A7670E GPS Service" # New option
        echo -e "  ${C_CYAN}X)${C_NC} Back to Main Menu" # Changed to X
        read -p "  Enter your choice: " choice

        case $choice in
            1) sudo systemctl status "${all_services[@]}" --no-pager || true; press_enter ;;
            2) sudo systemctl restart "${all_services[@]}"; echo_ok "All core services restarted."; press_enter ;;
            3) 
                echo_step "Checking A7670E GPS service status via dedicated tool..."
                if [[ -f "$A7670E_GPS_INSTALLER_SYSTEM_PATH" ]]; then
                    sudo "$A7670E_GPS_INSTALLER_SYSTEM_PATH" -status || true
                else
                    echo_error "A7670E GPS Installer tool not found at '$A7670E_GPS_INSTALLER_SYSTEM_PATH'."
                    echo_warn "Cannot check A7670E GPS service status."
                fi
                press_enter
                ;;
            4) # Restart A7670E GPS Service
                echo_step "Restarting A7670E GPS service via dedicated tool..."
                if [[ -f "$A7670E_GPS_INSTALLER_SYSTEM_PATH" ]]; then
                    sudo "$A7670E_GPS_INSTALLER_SYSTEM_PATH" -restart || true # Assuming -restart option
                    echo_ok "Attempted to restart A7670E GPS service."
                else
                    echo_error "A7670E GPS Installer tool not found. Cannot restart A7670E GPS service."
                fi
                press_enter
                ;;
            X|x) break ;; # Handle X for exit
            *) echo_error "Invalid option." ; press_enter ;;
        esac
    done
}

function config_management_menu() {
    while true; do
        clear
        display_header # Display the dynamic header
        echo_box_title "Configuration Management"
        echo_warn "Configuration is now managed via the web UI in the 'Admin' tab."
        echo_warn "File-based configurations (.ini) are for initial setup only."
        press_enter
        break
    done
}

function database_management_menu() {
    while true; do
        clear
        display_header # Display the dynamic header
        echo_box_title "Database Management"
        echo_warn "Database management features are pending implementation."
        press_enter
        break
    done
}

function system_update_menu() {
    while true; do
        clear
        display_header # Display the dynamic header
        echo_box_title "System & Update"
        echo -e "  ${C_CYAN}1)${C_NC} Run Update & Patch Check"
        echo -e "  ${C_CYAN}2)${C_NC} Manage SSL Certificate"
        echo -e "  ${C_CYAN}3)${C_NC} Detailed File Version Check" # New Menu Option
        echo -e "  ${C_CYAN}X)${C_NC} Back to Main Menu" # Changed to X
        read -p "  Enter your choice: " choice

        case $choice in
            1) run_update_and_patch; press_enter ;;
            2) manage_ssl_certificate; configure_apache "${APACHE_DOMAIN}"; press_enter ;;
            3) file_version_check_menu; press_enter ;; # Call new function
            X|x) break ;; # Handle X for exit
            *) echo_error "Invalid option." ; press_enter ;;
        esac
    done
}

function diagnostics_tools_menu() {

    while true; do
        clear
        display_header # Display the dynamic header
        echo_box_title "Diagnostics & Tools"
        echo -e "  ${C_CYAN}1)${C_NC} Check Live GPSd Status (formatted view)"
        echo -e "  ${C_CYAN}2)${C_NC} Check Live GPSd Status (raw JSON stream)"
        echo -e "  ${C_CYAN}3)${C_NC} Check Chrony Time Sources"
        echo -e "  ${C_CYAN}4)${C_NC} Check Chrony Server Stats (if serving)"
        echo -e "  ${C_CYAN}5)${C_NC} List Current Files" # New Option
        echo -e "  ${C_CYAN}X)${C_NC} Back to Main Menu" # Changed to X
        read -p "  Enter your choice: " choice

        case $choice in
            1)
                echo_step "Checking for 'cgps' tool..."
                if command -v cgps &> /dev/null; then
                    echo_ok "'cgps' found. Starting live view..."
                    echo_warn "Press 'q' to quit the GPS status screen."
                    sleep 2
                    clear
                    display_header # Redraw header after clear by cgps
                    cgps
                    clear # Clear again after cgps exits
                else
                    echo_error "'cgps' command not found. It should be part of the 'gpsd-clients' package."
                fi
                press_enter
                ;;
            2)
                echo_step "Checking for 'gpspipe' tool..."
                if command -v gpspipe &> /dev/null; then
                    echo_ok "'gpspipe' found. Starting raw JSON stream..."
                    echo_warn "Press 'Ctrl+C' to stop the stream."
                    sleep 2
                    # No clear here, as it's a continuous stream
                    gpspipe -w
                else
                    echo_error "'gpspipe' command not found. It should be part of the 'gpsd-clients' package."
                fi
                press_enter
                ;;
            3)
                echo_step "Checking chrony sources..."
                chronyc sources
                press_enter
                ;;
            4)
                echo_step "Checking chrony client access..."
                chronyc clients
                press_enter
                ;;
            5) # List Current Files
                echo_step "Listing currently installed files..."
                CHECK_MODE='local' check_file_versions "Installed Files and their Local Source Status:"
                press_enter
                ;;
            X|x) break ;; # Handle X for exit
            *) echo_error "Invalid option." ; press_enter ;;
        esac
    done
}

function full_program_management_menu() {
    while true; do
        clear
        display_header # Display the dynamic header
        echo_box_title "Full Program Management"
        echo -e "  ${C_CYAN}1)${C_NC} Reinstall Program (Run First-Time Setup)"
        echo -e "  ${C_CYAN}2)${C_NC} Uninstall Program (CAUTION: REMOVES ALL DATA AND FILES!)"
        echo -e "  ${C_CYAN}X)${C_NC} Back to Main Menu" # Changed to X
        read -p "  Enter your choice: " choice

        case $choice in
            1) read -p "${C_YELLOW}WARNING: This will reinstall the entire program. Continue? (y/N): ${C_NC}" confirm
               if [[ "$confirm" == "y" || "$confirm" == "Y" ]]; then run_first_time_setup; fi; press_enter ;;
            2) uninstall_program_prompt; press_enter ;;
            X|x) break ;; # Handle X for exit
            *) echo_error "Invalid option." ; press_enter ;;
        esac
    done
}

function uninstall_program_prompt() {
    clear
    display_header # Display the dynamic header
    echo_box_title "${C_RED}UNINSTALL PROGRAM${C_NC}"
    echo_warn "This will permanently remove ALL pi_backend files, configurations, databases,"
    echo_warn "and systemd services. This action CANNOT be undone."
    read -p "${C_RED}Are you absolutely sure you want to proceed? Type 'YES' to confirm: ${C_NC}" confirm
    if [[ "$confirm" == "YES" ]]; then uninstall_program; echo_ok "Pi_backend has been uninstalled."; exit 0;
    else echo_ok "Uninstall cancelled."; fi
}

function uninstall_program() {
    echo_step "Stopping and disabling services (ignoring errors if not running)..."
    # Ensure to include the new installer tool's service in the stop list for a clean uninstall
    local all_services_to_stop=("$API_SERVICE_NAME" "$POLLER_SERVICE_NAME" "gpsd" "chrony" "apache2") # Using variable for chrony
    
    # First, try to uninstall the A7670E GPS service via its dedicated tool
    if [[ -f "$A7670E_GPS_INSTALLER_SYSTEM_PATH" ]]; then
        echo_step "Instructing A7670E GPS Installer tool to uninstall its service..."
        local gps_installer_output=""
        local gps_installer_exit_code=0
        gps_installer_output=$(sudo "${A7670E_GPS_INSTALLER_SYSTEM_PATH}" -uninstall 2>&1)
        gps_installer_exit_code=$?

        if [[ $gps_installer_exit_code -eq 0 ]]; then
            echo_ok "A7670E GPS service uninstalled via its dedicated tool."
            echo_ok "Installer output: ${gps_installer_output}"
        else
            echo_warn "Failed to uninstall A7670E GPS service via its dedicated tool (Exit code: ${gps_installer_exit_code})."
            echo_warn "Installer output: ${gps_installer_output}"
            # Do NOT exit, allow other cleanup to proceed
        fi
    else
        echo_warn "A7670E GPS Installer tool not found at '$A7670E_GPS_INSTALLER_SYSTEM_PATH'. Skipping A7670E GPS service uninstall."
    fi

    # Now proceed with stopping other services
    for service in "${all_services_to_stop[@]}"; do
        sudo systemctl stop "$service" &>/dev/null || true
        sudo systemctl disable "$service" &>/dev/null || true
        echo_ok "Stopped and disabled $service."
    done

    echo_step "Removing systemd service files..."
    # No longer remove a7670e-gps-init.service directly, its tool handles it.
    sudo rm -f "/etc/systemd/system/$API_SERVICE_NAME" "/etc/systemd/system/$POLLER_SERVICE_NAME"
    sudo systemctl daemon-reload # Reload systemd to recognize removed service files
    echo_ok "Systemd service files removed."

    echo_step "Removing application directories and data (aggressive cleanup)..."
    sudo rm -rf "$INSTALL_PATH" || true
    sudo rm -rf "$MASTER_CONFIG_PATH" || true
    sudo rm -rf "$PI_BACKEND_HOME_DIR" || true
    sudo rm -rf "$SKYFIELD_DATA_DIR" || true
    sudo rm -rf "$LOG_DIR" || true
    
    # Remove the new installer tool itself from /usr/local/bin
    if [[ -f "$A7670E_GPS_INSTALLER_SYSTEM_PATH" ]]; then
        echo_step "Removing A7670E GPS Installer tool from '$A7670E_GPS_INSTALLER_SYSTEM_PATH'..."
        sudo rm -f "$A7670E_GPS_INSTALLER_SYSTEM_PATH" || true
        echo_ok "A7670E GPS Installer tool removed."
    fi

    if [[ -n "$DB_PATH" ]] && [[ -f "$DB_PATH" ]]; then
        echo_step "Removing database file: ${C_CYAN}$DB_PATH${C_NC}"
        sudo rm -f "$DB_PATH" || true
        local db_dir="$(dirname "$DB_PATH")"
        if [[ -d "$db_dir" ]] && [[ "$db_dir" != "/var/lib" ]] && [[ "$db_dir" != "/var" ]] && [[ -z "$(ls -A "$db_dir" 2>/dev/null)" ]]; then
            sudo rmdir "$db_dir" &>/dev/null || true
            echo_ok "Empty database directory removed: $db_dir."
        fi
    else
        echo_warn "Database path not known or DB file not found. Skipping DB file removal."
    fi
    echo_ok "Application directories and data removed."

    echo_step "Removing Apache configs related to pi_backend..."
    sudo a2dissite pi-backend-http.conf &>/dev/null || true
    sudo a2dissite pi-backend-https.conf &>/dev/null || true
    sudo rm -f /etc/apache2/sites-available/pi-backend-*.conf || true
    sudo rm -f "$APACHE_HTTP_CONF_FILE" || true
    sudo rm -f "$APACHE_HTTPS_CONF_FILE" || true
    sudo rm -f /etc/apache2/conf-available/servername.conf || true
    sudo systemctl reload apache2 &>/dev/null || true
    echo_ok "Apache configurations removed."

    echo_step "Removing Chrony GPS config..."
    sudo rm -f /etc/chrony/conf.d/gpsd.conf || true
    echo_ok "Chrony GPS config removed."

    echo_step "Restoring original Chrony config..."
    if [[ -f /etc/chrony/chrony.conf.bak ]]; then
        sudo mv /etc/chrony/chrony.conf.bak /etc/chrony/chrony.conf || true
        echo_ok "Chrony config restored from backup."
    else
       sudo sed -i '/# START Auto-added by pi_backend setup/,/# END Auto-added by pi_backend setup/d' /etc/chrony/chrony.conf &>/dev/null || true
       echo_ok "Auto-added Chrony config lines removed."
    fi
    sudo systemctl restart chrony &>/dev/null || true
    echo_ok "Chrony configuration cleaned."

    echo_ok "All pi_backend components removed successfully."
}

# --- Main Execution Block ---
main() {
    clear
    if [[ "$EUID" -eq 0 ]]; then
        echo_error "Please do not run this script as root directly."
        echo_error "Run it as a normal user, and it will prompt for sudo when necessary."
        exit 1
    fi

    # Display initial header
    display_header
    echo -e "\n${C_BLUE}--- Initializing pi_backend Setup Script ---${C_NC}\n"

    # Load master config paths early so uninstall can use them reliably
    # This block is changed to be POSIX-compliant and handles the return status of load_master_config
    if ! load_master_config; then
        echo_warn "Could not load master configuration paths. Assuming fresh install or incomplete setup."
        INSTALL_PATH="/var/www/pi_backend"
        MASTER_CONFIG_PATH="/etc/pi_backend"
        PI_BACKEND_HOME_DIR="$HOME/.pi_backend"
        SKYFIELD_DATA_DIR="/var/lib/pi_backend/skyfield-data"
        LOG_DIR="/var/log/pi_backend"
        DB_PATH="/var/lib/pi_backend/pi_backend.db"
    fi

    # Export paths so Python sub-scripts can use them
    export INSTALL_PATH
    export DB_PATH

    local initial_status_message=""

    # Always perform a file version check at the beginning
    check_file_versions "Performing initial file integrity check..."
    echo_warn "\nReview the file status above. Press ENTER to continue..."
    press_enter # Pause after displaying file versions

    if [[ ! -f "$SETUP_COMPLETE_FLAG" ]]; then
        # This is a truly first-time run, or after a full uninstall
        echo_box_title "FIRST-TIME INSTALLATION DETECTED"
        echo_step "The '.setup_complete' flag was not found. Initiating full setup process automatically."
        echo_warn "This will install all prerequisites, deploy files, and configure services."
        # No extra press_enter here, as the one above handles it.

        if run_first_time_setup; then
            initial_status_message="${C_GREEN}First-time setup completed successfully!${C_NC}"
            # After successful setup, re-check files to update PATCH_NEEDED flag
            check_file_versions "Verifying post-installation status..."
            if [[ "$PATCH_NEEDED" -eq 1 ]]; then
                 initial_status_message="${C_YELLOW}${C_BOLD}!!! FIRST-TIME SETUP COMPLETED WITH WARNINGS !!!${C_NC}\n${C_YELLOW}!!! Some discrepancies remain. Please run 'System & Update > Run Update & Patch Check'.${C_NC}"
            fi
        else
            initial_status_message="${C_RED}${C_BOLD}!!! FIRST-TIME SETUP FAILED !!!${C_NC}\n${C_RED}!!! Please review logs and manually resolve issues, then run 'Full Program Management > Reinstall Program'.${C_NC}"
        fi
    elif [[ "$PATCH_NEEDED" -eq 1 ]]; then
        # If setup flag exists AND a patch is needed, automatically run update
        echo_box_title "SYSTEM UPDATE / PATCH DETECTED"
        echo_step "Newer or missing files detected. Initiating update process automatically."
        echo_warn "This will apply necessary patches and restart services."
        # No extra press_enter here, as the one above handles it.

        if run_update_and_patch; then
            initial_status_message="${C_GREEN}System updated successfully!${C_NC}"
            # After successful update, re-check files to update PATCH_NEEDED flag
            check_file_versions "Verifying post-update status..."
            if [[ "$PATCH_NEEDED" -eq 0 ]]; then
                initial_status_message="${C_YELLOW}${C_BOLD}!!! UPDATE COMPLETED WITH WARNINGS !!!${C_NC}\n${C_YELLOW}!!! Some discrepancies remain. Please run 'System & Update > Run Update and Patch Check'.${C_NC}"
            fi
        else
            initial_status_message="${C_RED}${C_BOLD}!!! SYSTEM UPDATE FAILED !!!${C_NC}\n${C_RED}!!! Please review logs and manually resolve issues, then run 'System & Update > Run Update and Patch Check' or 'Full Program Management > Reinstall Program'.${C_NC}"
        fi
    else
        initial_status_message="${C_GREEN}System is up-to-date. No action needed.${C_NC}"
    fi

    main_menu "$initial_status_message"

    echo -e "\n${C_BLUE}Exiting installer. Goodbye!${C_NC}\n"
}

main