#!/bin/bash
set -e

# ==============================================================================
# Non-Interactive A7670E HAT GPS/GNSS Installer (v6 - NTP Server & PPS Fix)
# ==============================================================================
# This version adds functionality to configure the Pi as a local NTP server
# and includes a robust check and configuration for the PPS kernel overlay.
#
# USAGE: sudo ./setup_a7670e_gps.sh [-install|-uninstall|-status]
# ==============================================================================

# --- Configuration ---
INIT_SCRIPT_NAME="a7670e-gps-init.sh"
INIT_SCRIPT_PATH="/usr/local/bin/${INIT_SCRIPT_NAME}"
GPSD_CONFIG_PATH="/etc/default/gpsd"
CHRONY_GPS_CONF_PATH="/etc/chrony/conf.d/gpsd.conf"
BOOT_CONFIG_PATH="/boot/firmware/config.txt"
SERIAL_PORT="/dev/serial0"
PPS_PORT="/dev/pps0"
PPS_GPIO_PIN="4" # Default PPS pin for many Waveshare HATs

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
    echo "  -install    - Performs the full installation and configuration."
    echo "  -uninstall  - Removes all created scripts and services."
    echo "  -status     - Checks for a live GPS/PPS fix and returns exit code 0 (success) or 1 (failure)."
    echo
}

check_root() {
    if [[ $EUID -ne 0 ]]; then
       echo -e "${RED}ERROR: This script must be run as root. Please use sudo.${NC}"
       exit 1
    fi
}

check_status() {
    echo -e "${GREEN}--- Checking GPS/PPS Time Sync Status ---${NC}"
    if ! systemctl is-active --quiet chrony.service; then
        echo -e "${RED}FAILURE: The chrony service is not running.${NC}"
        exit 1
    fi
    echo "INFO: chrony service is active. Checking for PPS lock..."

    if chronyc sources | grep -q '^\#\* PPS'; then
        echo -e "${GREEN}SUCCESS: chrony is running and synchronized to the PPS source.${NC}"
        chronyc sources
        exit 0
    else
        echo -e "${RED}FAILURE: chrony is not synchronized to the PPS source.${NC}"
        echo -e "${YELLOW}         Current sources:${NC}"
        chronyc sources
        echo -e "${YELLOW}\nTroubleshooting Tips:${NC}"
        echo -e "1. Ensure the GPS antenna has a clear view of the sky and has had 5-10 minutes to get a 3D fix."
        echo -e "2. Verify the PPS overlay is active with 'grep pps ${BOOT_CONFIG_PATH}'."
        echo -e "3. Check 'sudo ppstest ${PPS_PORT}' (after stopping gpsd) to see if the kernel is detecting pulses."
        exit 1
    fi
}

create_init_script_content() {
    cat <<EOF
#!/bin/bash
# This script uses stty to ensure the port is at the correct baud rate before sending commands.
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
# This directive runs our init script immediately before starting the gpsd daemon.
ExecStartPre=${INIT_SCRIPT_PATH}
EOF
}

# --- NEW FUNCTION to configure chrony ---
create_chrony_conf_content() {
    cat <<EOF
# This file is managed by the setup_a7670e_gps.sh script.
# It configures chrony to use gpsd for time synchronization.

# Refclock for the NMEA data stream (SHM 0)
# Provides the full timestamp but is less precise.
# We use 'noselect' because we prefer the PPS signal.
refclock SHM 0 offset 0.0 delay 0.02 refid NMEA noselect

# Refclock for the Pulse Per Second signal (SHM 1)
# Provides a hyper-accurate marker for the start of each second.
# 'lock NMEA' pairs the pulse with the full timestamp from NMEA.
# 'prefer trust' tells chrony this is the best and most reliable source.
refclock SHM 1 refid PPS lock NMEA prefer trust

# Allow clients from local networks to connect to this server.
# This makes your Pi an NTP server for your LAN.
# Adjust the IP range if your network is different.
allow 192.168.0.0/16
allow 10.0.0.0/8

# Serve time even if not synchronized to another NTP server (relying on GPS).
local stratum 1
EOF
}

# --- NEW FUNCTION to configure PPS overlay ---
configure_pps_overlay() {
    echo -e "${GREEN}---> [3/7] Configuring PPS GPIO overlay in ${BOOT_CONFIG_PATH}...${NC}"
    # The line to add for the PPS overlay
    local pps_overlay_line="dtoverlay=pps-gpio,gpiopin=${PPS_GPIO_PIN}"

    # Check if the line already exists (commented or not)
    if grep -q "pps-gpio" "${BOOT_CONFIG_PATH}"; then
        echo "PPS overlay already seems to be configured. Skipping."
    else
        # Append the line to the config file
        echo -e "\n# Enable PPS signal on GPIO ${PPS_GPIO_PIN} for GPS time sync" >> "${BOOT_CONFIG_PATH}"
        echo "${pps_overlay_line}" >> "${BOOT_CONFIG_PATH}"
        echo "PPS overlay added. A reboot is required for this to take effect."
    fi
}

perform_install() {
    echo -e "${GREEN}Starting Full GPS Setup...${NC}"
    echo -e "${GREEN}---> [1/7] Installing dependencies...${NC}"
    apt-get update -qq
    apt-get install -y -qq gpsd gpsd-clients chrony pps-tools

    echo -e "${GREEN}---> [2/7] Checking serial port configuration...${NC}"
    # This basic check is helpful for the user.
    if ! grep -q "enable_uart=1" "${BOOT_CONFIG_PATH}"; then
       echo -e "${YELLOW}WARNING: 'enable_uart=1' not found. Please enable the hardware serial port via raspi-config.${NC}"
    fi

    # This is the new, crucial step for PPS
    configure_pps_overlay

    echo -e "${GREEN}---> [4/7] Creating GPS wake-up script...${NC}"
    create_init_script_content > "${INIT_SCRIPT_PATH}"
    chmod +x "${INIT_SCRIPT_PATH}"

    echo -e "${GREEN}---> [5/7] Configuring gpsd to use both Serial and PPS devices...${NC}"
    {
        echo '# Configuration for the gpsd daemon'
        echo 'START_DAEMON="true"'
        echo 'GPSD_OPTIONS="-n"'
        echo "DEVICES=\"${SERIAL_PORT} ${PPS_PORT}\""
        echo 'USBAUTO="false"'
    } > "${GPSD_CONFIG_PATH}"

    echo -e "${GREEN}---> [6/7] Configuring chrony to be an NTP server using GPS...${NC}"
    create_chrony_conf_content > "${CHRONY_GPS_CONF_PATH}"

    echo -e "${GREEN}---> [7/7] Enabling and reloading services...${NC}"
    # The systemd override is no longer needed with this robust setup, but we'll leave the function
    # in case it's needed for other hardware. For now, we link the init script via gpsd's own override.
    mkdir -p /etc/systemd/system/gpsd.service.d
    create_systemd_override_content > /etc/systemd/system/gpsd.service.d/override.conf
    
    systemctl daemon-reload
    systemctl enable gpsd.socket
    systemctl enable chrony.service

    echo -e "\n${GREEN}*** GPS INSTALLATION SCRIPT COMPLETE ***${NC}"
    echo -e "${YELLOW}A system reboot is required to apply all changes.${NC}"
}

perform_uninstall() {
    echo -e "${YELLOW}Starting Uninstallation...${NC}"
    echo -e "${GREEN}---> Stopping and disabling services...${NC}"
    systemctl stop gpsd.socket gpsd.service chrony.service > /dev/null 2>&1 || true
    systemctl disable gpsd.socket chrony.service > /dev/null 2>&1 || true

    echo -e "${GREEN}---> Removing created files...${NC}"
    rm -f "${INIT_SCRIPT_PATH}"
    rm -f "${CHRONY_GPS_CONF_PATH}"
    rm -f /etc/systemd/system/gpsd.service.d/override.conf
    # Note: This script does not remove the line from /boot/firmware/config.txt on uninstall.
    
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
    -status)
        check_status
        ;;
    *)
        echo -e "${RED}Error: Invalid command '$1'${NC}\n"
        display_usage
        exit 1
        ;;
esac

exit 0
