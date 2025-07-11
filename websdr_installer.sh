#!/bin/bash

# This script installs, configures, manages, and uninstalls OpenWebRX
# using a Docker container, ensuring compatibility and isolating dependencies.

# --- Configuration Variables ---
# Default host port for OpenWebRX. Container's internal port is 8073.
# Ensure this host port does not conflict with 80, 443, or 5000.
HOST_WEBSDR_PORT="8001"
CONTAINER_WEBSDR_PORT="8073" # Standard internal port for jketterl/openwebrx image

# Docker container and volume names
WEBSDR_CONTAINER_NAME="openwebrx_container"
WEBSDR_VOLUME_NAME="openwebrx-settings"
WEBSDR_TMPFS_PATH="/tmp/openwebrx" # Path inside the container for temporary files

# Admin user credentials for OpenWebRX settings (SET THESE SECURELY!)
# You MUST change 'your_secure_admin_password' to a strong, unique password.
# The user will be created automatically on first run if these are set.
OPENWEBRX_ADMIN_USER="root"
OPENWEBRX_ADMIN_PASSWORD="P@ssc0de!@#$" # <<<--- CHANGE THIS!

# Directory on host for custom OpenWebRX configuration file to be mounted into Docker
CUSTOM_CONFIG_HOST_DIR="/opt/openwebrx_config"
CUSTOM_CONFIG_FILE_NAME="config_webrx.py"
CUSTOM_CONFIG_PATH="${CUSTOM_CONFIG_HOST_DIR}/${CUSTOM_CONFIG_FILE_NAME}"

# --- Helper Functions ---

log_info() {
    echo -e "\n\033[0;32mINFO: $1\033[0m" # Green text for info
}

log_warn() {
    echo -e "\n\033[0;33mWARNING: $1\033[0m" # Yellow text for warnings
}

log_error() {
    echo -e "\n\033[0;31mERROR: $1\033[0m" # Red text for errors
    exit 1
}

# Function to check for root privileges
check_root() {
    if [[ $EUID -ne 0 ]]; then
        log_error "This script must be run with sudo or as root. Please run: sudo ./$(basename "$0") $@"
    fi
}

# Function to install Docker and common system packages
install_docker_and_dependencies() {
    log_info "Updating package lists and installing Docker and common dependencies..."
    sudo apt update || log_error "Failed to update package lists."
    
    # Install necessary packages for Docker and RTL-SDR tools
    sudo apt install -y apt-transport-https ca-certificates curl gnupg lsb-release \
        rtl-sdr net-tools || log_error "Failed to install core dependencies for Docker or rtl-sdr."

    # Add Docker's official GPG key
    if [ ! -f /etc/apt/keyrings/docker.gpg ]; then
        log_info "Adding Docker's official GPG key..."
        sudo mkdir -p /etc/apt/keyrings
        curl -fsSL https://download.docker.com/linux/debian/gpg | sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg || log_error "Failed to add Docker GPG key."
    fi

    # Set up the stable Docker repository
    if [ ! -f /etc/apt/sources.list.d/docker.list ]; then
        log_info "Setting up Docker APT repository..."
        echo \
            "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/debian \
            $(lsb_release -cs) stable" | sudo tee /etc/apt/sources.list.d/docker.list > /dev/null || log_error "Failed to add Docker APT repository."
    fi
    
    sudo apt update || log_error "Failed to update package lists after adding Docker repository."
    
    log_info "Installing Docker Engine..."
    sudo apt install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin || log_error "Failed to install Docker Engine."

    log_info "Adding current user to 'docker' group to run Docker commands without sudo (requires logout/login)..."
    sudo usermod -aG docker "$USER"
    log_info "Docker installed. Please log out and log back in, or reboot, for Docker group changes to take effect."
    log_info "You can then run 'docker run hello-world' to test Docker installation."

    # Blacklist the default DVB-T driver which can conflict with RTL-SDR
    log_info "Blacklisting conflicting DVB-T kernel modules on host (optional for Docker but good practice)..."
    echo 'blacklist dvb_usb_rtl28xxu' | sudo tee /etc/modprobe.d/blacklist-rtl.conf > /dev/null
    echo 'blacklist rtl2832' | sudo tee -a /etc/modprobe.d/blacklist-rtl.conf > /dev/null
    echo 'blacklist rtl2830' | sudo tee -a /etc/modprobe.d/blacklist-rtl.conf > /dev/null
    sudo depmod -a
    sudo update-initramfs -u
    log_info "Conflicting kernel modules blacklisted. A reboot might be required for this to take effect on the host system."
}

# Function to create custom OpenWebRX config with HFCGS profiles
create_custom_webrx_config() {
    log_info "Creating custom OpenWebRX configuration file with HFCGS profiles..."
    sudo mkdir -p "${CUSTOM_CONFIG_HOST_DIR}" || log_error "Failed to create custom config directory."

    # Define the Python configuration content with desired profiles
    # Note: Internal http_port is 8073 for the jketterl/openwebrx image
    sudo tee "${CUSTOM_CONFIG_PATH}" > /dev/null <<EOF
# /etc/openwebrx/config_webrx.py
# Generated by websdr-installer script
# DO NOT EDIT MANUALLY IF YOU WANT YOUR CHANGES TO PERSIST ACROSS CONTAINER RECREATIONS
# Use the installer script to regenerate or manage via web UI settings.

http_port = ${CONTAINER_WEBSDR_PORT}

# --- SDR Devices Configuration ---
sdrs = {
    "rtlsdr_hf": {
        "name": "RTL-SDR HF/VHF/UHF Receiver", # Updated name to reflect broader coverage
        "type": "rtl_sdr",
        "ppm": 0,  # IMPORTANT: Adjust this PPM correction for your specific dongle via web UI settings later.
        "direct_samp": True, # Enable direct sampling for HF reception (Q-branch recommended for most RTL-SDRs)
        "profiles": {
            # HFCGS Frequencies (USB)
            "hfgcs_4724": {
                "name": "HFGCS 4724 kHz (USB)",
                "center_freq": 4724000,
                "modulations": { "usb": {} },
                "bandwidth": 2048000, # Max stable bandwidth for RTL-SDRs
                "audio_compression": "opus"
            },
            "hfgcs_6739": {
                "name": "HFGCS 6739 kHz (USB)",
                "center_freq": 6739000,
                "modulations": { "usb": {} },
                "bandwidth": 2048000,
                "audio_compression": "opus"
            },
            "hfgcs_8992": {
                "name": "HFGCS 8992 kHz (USB)",
                "center_freq": 8992000,
                "modulations": { "usb": {} },
                "bandwidth": 2048000,
                "audio_compression": "opus"
            },
            "hfgcs_11175": {
                "name": "HFGCS 11175 kHz (USB)",
                "center_freq": 11175000,
                "modulations": { "usb": {} },
                "bandwidth": 2048000,
                "audio_compression": "opus"
            },
            "hfgcs_13200": {
                "name": "HFGCS 13200 kHz (USB)",
                "center_freq": 13200000,
                "modulations": { "usb": {} },
                "bandwidth": 2048000,
                "audio_compression": "opus"
            },
            "hfgcs_15016": {
                "name": "HFGCS 15016 kHz (USB)",
                "center_freq": 15016000,
                "modulations": { "usb": {} },
                "bandwidth": 2048000,
                "audio_compression": "opus"
            },
            # Common Amateur Radio (Ham) Bands (LSB/USB on HF)
            "ham_80m_lsb": {
                "name": "80m Ham Band (LSB)",
                "center_freq": 3800000, # Center of typical LSB segment
                "modulations": { "lsb": {} },
                "bandwidth": 2048000,
                "audio_compression": "opus"
            },
            "ham_40m_lsb": {
                "name": "40m Ham Band (LSB)",
                "center_freq": 7150000, # Center of typical LSB segment
                "modulations": { "lsb": {} },
                "bandwidth": 2048000,
                "audio_compression": "opus"
            },
            "ham_20m_usb": {
                "name": "20m Ham Band (USB)",
                "center_freq": 14200000, # Center of typical USB segment
                "modulations": { "usb": {} },
                "bandwidth": 2048000,
                "audio_compression": "opus"
            },
            "ham_10m_usb": {
                "name": "10m Ham Band (USB)",
                "center_freq": 28400000, # Center of typical USB segment
                "modulations": { "usb": {} },
                "bandwidth": 2048000,
                "audio_compression": "opus"
            },
            # Common Shortwave Broadcast Bands (AM)
            "sw_49m_am": {
                "name": "Shortwave Broadcast (49m AM)",
                "center_freq": 6000000, # Common 49m band center
                "modulations": { "am": {} },
                "bandwidth": 2048000,
                "audio_compression": "opus"
            },
            "sw_31m_am": {
                "name": "Shortwave Broadcast (31m AM)",
                "center_freq": 9800000, # Common 31m band center
                "modulations": { "am": {} },
                "bandwidth": 2048000,
                "audio_compression": "opus"
            },
            "sw_25m_am": {
                "name": "Shortwave Broadcast (25m AM)",
                "center_freq": 11900000, # Common 25m band center
                "modulations": { "am": {} },
                "bandwidth": 2048000,
                "audio_compression": "opus"
            },
            "sw_19m_am": {
                "name": "Shortwave Broadcast (19m AM)",
                "center_freq": 15300000, # Common 19m band center
                "modulations": { "am": {} },
                "bandwidth": 2048000,
                "audio_compression": "opus"
            },
            # FM Broadcast Radio
            "fm_broadcast": {
                "name": "FM Broadcast (88-108 MHz)",
                "center_freq": 98000000, # Center of the FM broadcast band
                "modulations": { "wfm": {} },
                "bandwidth": 2048000, # Still using SDR's sample rate, WFM filter applies
                "audio_compression": "opus"
            },
            # NOAA Weather Radio (NFM)
            "noaa_162_400": {
                "name": "NOAA Weather 162.400 MHz",
                "center_freq": 162400000,
                "modulations": { "nfm": {} },
                "bandwidth": 2048000,
                "audio_compression": "opus"
            },
            "noaa_162_425": {
                "name": "NOAA Weather 162.425 MHz",
                "center_freq": 162425000,
                "modulations": { "nfm": {} },
                "bandwidth": 2048000,
                "audio_compression": "opus"
            },
            "noaa_162_550": {
                "name": "NOAA Weather 162.550 MHz",
                "center_freq": 162550000,
                "modulations": { "nfm": {} },
                "bandwidth": 2048000,
                "audio_compression": "opus"
            }
        }
    }
}
EOF
    log_info "Custom config file generated at ${CUSTOM_CONFIG_PATH}"
    # Set permissions for the config file (read-only for others)
    sudo chmod 644 "${CUSTOM_CONFIG_PATH}"
}


# Function to install and configure OpenWebRX via Docker
install_webrx_docker() {
    log_info "Checking if Docker service is running..."
    if ! systemctl is-active --quiet docker; then
        log_info "Docker service is not running. Starting Docker..."
        sudo systemctl start docker || log_error "Failed to start Docker service."
        sudo systemctl enable docker || log_error "Failed to enable Docker service to start on boot."
    fi

    log_info "Creating Docker volume '$WEBSDR_VOLUME_NAME' for settings persistence..."
    sudo docker volume create "$WEBSDR_VOLUME_NAME" || log_error "Failed to create Docker volume."

    log_info "Pulling OpenWebRX Docker image 'jketterl/openwebrx:stable'..."
    sudo docker pull jketterl/openwebrx:stable || log_error "Failed to pull OpenWebRX Docker image."

    log_info "Starting OpenWebRX Docker container '$WEBSDR_CONTAINER_NAME' on port $HOST_WEBSDR_PORT..."
    # Stop and remove any existing container with the same name
    sudo docker stop "$WEBSDR_CONTAINER_NAME" 2>/dev/null || true
    sudo docker rm "$WEBSDR_CONTAINER_NAME" 2>/dev/null || true

    # Create the custom config file before running the container
    create_custom_webrx_config

    sudo docker run -d \
        --name "$WEBSDR_CONTAINER_NAME" \
        --restart unless-stopped \
        --device /dev/bus/usb:/dev/bus/usb \
        -p "$HOST_WEBSDR_PORT":"$CONTAINER_WEBSDR_PORT" \
        -v "$WEBSDR_VOLUME_NAME":/var/lib/openwebrx \
        -v "${CUSTOM_CONFIG_PATH}":/etc/openwebrx/config_webrx.py:ro \
        --tmpfs="$WEBSDR_TMPFS_PATH" \
        -e OPENWEBRX_ADMIN_USER="$OPENWEBRX_ADMIN_USER" \
        -e OPENWEBRX_ADMIN_PASSWORD="$OPENWEBSDR_ADMIN_PASSWORD" \
        jketterl/openwebrx:stable || log_error "Failed to start OpenWebRX Docker container."
    
    log_info "OpenWebRX Docker container started successfully on port $HOST_WEBSDR_PORT."
    log_info "You can access it at http://$(hostname -I | awk '{print $1}'):$HOST_WEBSDR_PORT"
    log_info "Initial configuration will be copied to the '$WEBSDR_VOLUME_NAME' volume on first startup."
    log_info "Use username '$OPENWEBRX_ADMIN_USER' and the password you set in the script to log in to the settings."
    log_info "Remember to configure your SDR dongle's gain and the exact PPM correction for your device via the OpenWebRX web interface."
}

# Function to check SDR presence (on host, primarily for basic verification)
check_sdr() {
    log_info "Checking for RTL-SDR dongle presence on host system..."
    if command -v rtl_test &> /dev/null; then
        log_info "rtl_test command found. Running test (requires SDR to not be in use by container)..."
        # Run rtl_test for a short duration and check its exit code
        if ! sudo systemctl is-active --quiet docker || ! sudo docker ps -q -f name="$WEBSDR_CONTAINER_NAME" | grep -q .; then
             # Only run rtl_test if Docker container is not running or not found
            if timeout 5s rtl_test -t -s 1M -d 0 -r 2>&1 | grep -q "Found"; then
                log_info "RTL-SDR dongle detected on host and appears to be working (when not in use by Docker)."
            else
                log_warn "No RTL-SDR dongle detected on host, or it's not working correctly."
                log_warn "Ensure your RTL-SDR is plugged in and the blacklisting of DVB-T modules has taken effect (may require reboot)."
                log_info "Full rtl_test output (if available):"
                timeout 5s rtl_test -t || echo "rtl_test timed out or produced no output."
            fi
        else
            log_warn "OpenWebRX Docker container is running. rtl_test on host might fail as SDR is in use by the container."
            log_info "If the container started successfully with --device /dev/bus/usb, SDR access should be working within the container."
        fi
    else
        log_warn "rtl_test not found. It should be installed with Docker dependencies. Please run '-install'."
    fi
}

# Function to display status
status_webrx() {
    log_info "Checking Docker service status..."
    sudo systemctl status docker || true # true to prevent script from exiting on non-zero status
    
    log_info "Checking OpenWebRX Docker container status..."
    sudo docker ps -a -f name="$WEBSDR_CONTAINER_NAME"
    
    log_info "Checking listening ports on host..."
    sudo netstat -tuln | grep "$HOST_WEBSDR_PORT"
    
    log_info "OpenWebRX should be accessible at http://$(hostname -I | awk '{print $1}'):$HOST_WEBSDR_PORT"
    log_info "RTL-SDR dongle status (on host):"
    check_sdr
}

# Function to clear OpenWebRX data and configuration for a fresh start
reset_webrx() {
    log_warn "Resetting OpenWebRX to default settings..."
    log_warn "This will stop and remove the container, delete the settings volume, and remove the custom config file."
    log_warn "You will need to re-run '-install' after a reset."

    log_warn "Stopping and removing OpenWebRX Docker container '$WEBSDR_CONTAINER_NAME'..."
    sudo docker stop "$WEBSDR_CONTAINER_NAME" 2>/dev/null || true
    sudo docker rm "$WEBSDR_CONTAINER_NAME" 2>/dev/null || true
    
    log_warn "Removing Docker volume '$WEBSDR_VOLUME_NAME' (this will delete OpenWebRX settings/data)..."
    sudo docker volume rm "$WEBSDR_VOLUME_NAME" 2>/dev/null || true
    
    log_warn "Removing custom OpenWebRX configuration directory: ${CUSTOM_CONFIG_HOST_DIR}..."
    sudo rm -rf "${CUSTOM_CONFIG_HOST_DIR}" || log_warn "Failed to remove custom config directory. Manual removal might be needed."

    log_info "OpenWebRX reset complete. Please run 'sudo ./$(basename "$0") -install' and then reboot your Raspberry Pi."
}


# Function to uninstall OpenWebRX Docker setup
uninstall_webrx() {
    log_warn "Stopping and removing OpenWebRX Docker container '$WEBSDR_CONTAINER_NAME'..."
    sudo docker stop "$WEBSDR_CONTAINER_NAME" 2>/dev/null || true
    sudo docker rm "$WEBSDR_CONTAINER_NAME" 2>/dev/null || true
    
    log_warn "Removing Docker volume '$WEBSDR_VOLUME_NAME' (this will delete OpenWebRX settings/data)..."
    sudo docker volume rm "$WEBSDR_VOLUME_NAME" 2>/dev/null || true
    
    log_warn "Removing custom OpenWebRX configuration directory: ${CUSTOM_CONFIG_HOST_DIR}..."
    sudo rm -rf "${CUSTOM_CONFIG_HOST_DIR}" || log_warn "Failed to remove custom config directory. Manual removal might be needed."

    log_info "OpenWebRX Docker uninstallation complete."
    log_info "Note: Docker Engine itself is NOT uninstalled. You can remove it manually if no longer needed."
    log_info "You may also want to manually remove the DVB-T blacklisting file: /etc/modprobe.d/blacklist-rtl.conf"
}

# Function to update OpenWebRX Docker image
update_webrx() {
    log_info "Stopping OpenWebRX Docker container '$WEBSDR_CONTAINER_NAME' for update..."
    sudo docker stop "$WEBSDR_CONTAINER_NAME" 2>/dev/null || true # Stop quietly if not running
    
    log_info "Pulling latest OpenWebRX Docker image 'jketterl/openwebrx:stable'..."
    sudo docker pull jketterl/openwebrx:stable || log_error "Failed to pull latest Docker image."
    
    log_info "Removing old container and starting a new one with the updated image..."
    sudo docker rm "$WEBSDR_CONTAINER_NAME" 2>/dev/null || true # Remove old container quietly

    # Recreate the custom config file during update to ensure latest profile settings are applied
    create_custom_webrx_config

    sudo docker run -d \
        --name "$WEBSDR_CONTAINER_NAME" \
        --restart unless-stopped \
        --device /dev/bus/usb:/dev/bus/usb \
        -p "$HOST_WEBSDR_PORT":"$CONTAINER_WEBSDR_PORT" \
        -v "$WEBSDR_VOLUME_NAME":/var/lib/openwebrx \
        -v "${CUSTOM_CONFIG_PATH}":/etc/openwebrx/config_webrx.py:ro \
        --tmpfs="$WEBSDR_TMPFS_PATH" \
        -e OPENWEBRX_ADMIN_USER="$OPENWEBRX_ADMIN_USER" \
        -e OPENWEBRX_ADMIN_PASSWORD="$OPENWEBSDR_ADMIN_PASSWORD" \
        jketterl/openwebrx:stable || log_error "Failed to restart OpenWebRX Docker container with updated image."
    
    log_info "OpenWebRX Docker container updated and restarted."
}

# --- Main Script Logic ---

if [ "$#" -eq 0 ]; then
    log_error "No arguments provided. Usage: $(basename "$0") [-install|-status|-uninstall|-update|-check_sdr|-reset]"
fi

# Parse command line arguments
case "$1" in
    -install)
        check_root "$@"
        install_docker_and_dependencies
        install_webrx_docker
        ;;
    -status)
        status_webrx
        ;;
    -uninstall)
        check_root "$@"
        uninstall_webrx
        ;;
    -update)
        check_root "$@"
        update_webrx
        ;;
    -check_sdr)
        check_sdr
        ;;
    -reset)
        check_root "$@"
        reset_webrx
        ;;
    *)
        log_error "Invalid argument: $1. Usage: $(basename "$0") [-install|-status|-uninstall|-update|-check_sdr|-reset]"
        ;;
esac

log_info "Operation complete."
