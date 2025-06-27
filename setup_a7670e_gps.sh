#!/bin/bash
set -e

# ==============================================================================
# Non-Interactive A7670E HAT GPS/GNSS Installer (v3 - Automation Friendly)
# ==============================================================================
# This script uses flags (-install) and provides a script-friendly status
# check that returns a proper exit code.
#
# USAGE: sudo ./setup_a7670e_gps.sh [-install|-uninstall|-status|-test]
# ==============================================================================

# --- Configuration ---
INIT_SCRIPT_NAME="a7670e-gps-init.sh"
INIT_SCRIPT_PATH="/usr/local/bin/${INIT_SCRIPT_NAME}"
SYSTEMD_SERVICE_NAME="a7670e-gps-init.service"
SYSTEMD_SERVICE_PATH="/etc/systemd/system/${SYSTEMD_SERVICE_NAME}"
GPSD_CONFIG_PATH="/etc/default/gpsd"
SERIAL_PORT="/dev/serial0"

# --- Colors for Output ---
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

# --- Functions ---

display_usage() {
    echo -e "${GREEN}A7670E HAT GPS/GNSS Installer & Manager${NC}"
    echo "-------------------------------------------"
    echo "Usage: sudo $0 [command]"
    echo
    echo "Commands:"
    echo "  -install    - Performs the full non-interactive installation."
    echo "  -uninstall  - Removes all created scripts and services."
    echo "  -status     - Checks for a live GPS fix and returns exit code 0 (success) or 1 (failure)."
    echo "  -test       - Alias for -status."
    echo
}

check_root() {
    if [[ $EUID -ne 0 ]]; then
       echo -e "${RED}ERROR: This script must be run as root. Please use sudo.${NC}"
       exit 1
    fi
}

# --- NEW ROBUST STATUS CHECK ---
check_status() {
    echo -e "${GREEN}--- Checking GPS Status ---${NC}"

    # 1. Check if the gpsd service is running at all.
    if ! systemctl is-active --quiet gpsd.service; then
        echo -e "${RED}FAILURE: The gpsd.service is not running.${NC}"
        exit 1
    fi
    echo "INFO: gpsd.service is active. Awaiting a valid GPS fix..."

    # 2. Use gpspipe to wait for a TPV (Time-Position-Velocity) report.
    # This proves we have a real fix. We'll wait up to 30 seconds.
    # The 'grep' command will return exit code 0 if it finds "TPV".
    if timeout 30s gpspipe -w -n 10 | grep -q -m 1 '"class":"TPV"'; then
        echo -e "${GREEN}SUCCESS: gpsd is running and has a GPS fix.${NC}"
        exit 0
    else
        echo -e "${RED}FAILURE: Timed out after 30 seconds. Could not get a GPS fix from gpsd.${NC}"
        echo -e "${YELLOW}         (This is normal if the device is indoors or has just started).${NC}"
        exit 1
    fi
}

# (The rest of the script remains the same, but is included for completeness)

create_init_script_content() {
    cat <<EOF
#!/bin/bash
stty -F ${SERIAL_PORT} 115200 raw -echo
sleep 0.5
echo -e "AT+CGNSSPWR=1\\r\\n" > ${SERIAL_PORT}
sleep 1
echo -e "AT+CGNSSTST=1\\r\\n" > ${SERIAL_PORT}
sleep 1
echo -e "AT+CGNSSPORTSWITCH=0,1\\r\\n" > ${SERIAL_PORT}
exit 0
EOF
}

create_systemd_override_content() {
    cat <<EOF
[Service]
ExecStartPre=${INIT_SCRIPT_PATH}
EOF
}

perform_install() {
    echo -e "${GREEN}Starting Full GPS Setup...${NC}"
    echo -e "${GREEN}---> [1/5] Installing dependencies...${NC}"
    apt-get update -qq
    apt-get install -y -qq gpsd gpsd-clients

    echo -e "${GREEN}---> [2/5] Creating GPS wake-up script...${NC}"
    create_init_script_content > "${INIT_SCRIPT_PATH}"
    chmod +x "${INIT_SCRIPT_PATH}"

    echo -e "${GREEN}---> [3/5] Configuring gpsd default file...${NC}"
    echo 'DEVICES="/dev/serial0"' > "${GPSD_CONFIG_PATH}"
    echo 'GPSD_OPTIONS="-n"' >> "${GPSD_CONFIG_PATH}"
    echo 'USBAUTO="false"' >> "${GPSD_CONFIG_PATH}"

    echo -e "${GREEN}---> [4/5] Creating systemd override for gpsd...${NC}"
    # This creates the directory and the override file
    mkdir -p /etc/systemd/system/gpsd.service.d
    create_systemd_override_content > /etc/systemd/system/gpsd.service.d/override.conf

    echo -e "${GREEN}---> [5/5] Enabling and reloading services...${NC}"
    systemctl daemon-reload
    # Enable the socket so gpsd starts on demand
    systemctl enable gpsd.socket

    echo -e "\n${GREEN}*** GPS INSTALLATION SCRIPT COMPLETE ***${NC}"
    echo -e "${YELLOW}A system reboot is required to apply all changes.${NC}"
}

perform_uninstall() {
    echo -e "${YELLOW}Starting Uninstallation...${NC}"
    echo -e "${GREEN}---> Stopping and disabling services...${NC}"
    systemctl stop gpsd.socket gpsd.service > /dev/null 2>&1 || true
    systemctl disable gpsd.socket > /dev/null 2>&1 || true

    echo -e "${GREEN}---> Removing created files...${NC}"
    rm -f "${INIT_SCRIPT_PATH}"
    rm -f /etc/systemd/system/gpsd.service.d/override.conf
    # We leave the /etc/default/gpsd file as it's part of the package
    
    echo -e "${GREEN}---> Reloading systemd daemon...${NC}"
    systemctl daemon-reload

    echo -e "\n${GREEN}*** UNINSTALLATION COMPLETE ***${NC}"
}

# --- Main Logic ---

check_root

if [ -z "$1" ]; then
    display_usage
    exit 1
fi

case "$1" in
    -install)
        perform_install
        ;;
    -uninstall)
        perform_uninstall
        ;;
    -status|-test)
        check_status
        ;;
    *)
        echo -e "${RED}Error: Invalid command '$1'${NC}\n"
        display_usage
        exit 1
        ;;
esac

exit 0
