#!/bin/bash

# ==============================================================================
# pi_backend API Endpoint Test Script
#
# Description:
#   This script automates the testing of all major pi_backend API endpoints.
#   It prompts for admin credentials, checks for and prompts for missing
#   3rd-party API keys, and uses `curl` to make the requests.
#
# How to run:
#   1. Save this file as `api_test.sh` on your Raspberry Pi.
#   2. Make it executable: `chmod +x api_test.sh`
#   3. Run it: `./api_test.sh`
# ==============================================================================

# --- Configuration ---
# Change this if your backend is not running on localhost or uses HTTPS
BASE_URL="http://localhost"

# --- Colors for Output ---
C_GREEN='\033[0;32m'
C_YELLOW='\033[1;33m'
C_RED='\033[0;31m'
C_CYAN='\033[0;36m'
C_NC='\033[0m' # No Color

clear

# --- State Variables ---
success_count=0
failure_count=0
# Array to store details of failed tests
failed_tests=()

# --- Helper Functions ---

# Function to print a formatted header
print_header() {
    echo -e "\n${C_CYAN}=============================================================${C_NC}"
    echo -e "${C_CYAN}  $1"
    echo -e "${C_CYAN}=============================================================${C_NC}"
}

# Function to check if jq is installed for pretty-printing JSON
check_jq() {
    if command -v jq &> /dev/null; then
        JQ_CMD="jq"
    else
        echo -e "${C_YELLOW}WARNING: 'jq' is not installed. JSON output will not be formatted.${C_NC}"
        echo -e "${C_YELLOW}         Install it with: sudo apt-get install jq${C_NC}"
        JQ_CMD="cat" # Fallback to cat if jq is not available
    fi
}

# --- Main Script ---

# 1. Check for dependencies
check_jq

# 2. Get User Credentials
echo -e "Please enter your admin credentials to test authenticated endpoints."
read -p "Admin Username: " ADMIN_USER
read -s -p "Admin Password: " ADMIN_PASS
echo

# Function to make an API call
# $1: HTTP Method (GET, POST, etc.)
# $2: Endpoint Path (e.g., /api/status)
# $3: Optional JSON data for POST requests
# $4: Optional flag to run silently (returns only the body on success)
call_api() {
    local METHOD=$1
    local ENDPOINT=$2
    local DATA=$3
    local SILENT=$4

    if [ -z "$SILENT" ]; then
      echo -e "\n--- [${METHOD}] ${ENDPOINT} ---"
    fi

    local CMD="curl -s -w '\nHTTP_STATUS_CODE:%{http_code}\n' -X ${METHOD} --user ${ADMIN_USER}:${ADMIN_PASS} -H \"Content-Type: application/json\""

    if [ ! -z "$DATA" ]; then
        CMD+=" -d '${DATA}'"
    fi

    CMD+=" ${BASE_URL}${ENDPOINT}"

    # Execute the command
    RESPONSE=$(eval ${CMD})

    # Separate body and status code
    HTTP_BODY=$(echo "$RESPONSE" | sed '$d')
    HTTP_STATUS=$(echo "$RESPONSE" | tail -n1 | cut -d: -f2)

    # Check status and update counts
    if [[ "$HTTP_STATUS" -ge 200 && "$HTTP_STATUS" -lt 300 ]]; then
        if [ "$SILENT" == "silent_and_return_body" ]; then
          echo "$HTTP_BODY"
          return 0
        fi
        if [ -z "$SILENT" ]; then
          echo -e "${C_GREEN}SUCCESS (HTTP ${HTTP_STATUS})${C_NC}"
          echo "$HTTP_BODY" | ${JQ_CMD}
        fi
        ((success_count++))
        return 0 # Success
    else
        if [ -z "$SILENT" ]; then
          echo -e "${C_RED}FAILURE (HTTP ${HTTP_STATUS})${C_NC}"
          echo "$HTTP_BODY" | ${JQ_CMD}
        fi
        ((failure_count++))
        # Add details of the failure to our array
        local failure_detail="[${METHOD}] ${ENDPOINT} (HTTP ${HTTP_STATUS}): $(echo "$HTTP_BODY" | ${JQ_CMD} -c . 2>/dev/null || echo "$HTTP_BODY")"
        failed_tests+=("${failure_detail}")
        return 1 # Failure
    fi
}

# --- New Function to Manage API Keys ---
manage_api_keys() {
    print_header "Checking for 3rd Party API Keys"
    
    # Get all keys currently in the database
    local existing_keys_json=$(call_api "GET" "/api/keys" "" "silent_and_return_body")
    if [ $? -ne 0 ]; then
        echo -e "${C_RED}Could not retrieve existing API keys. Skipping this step.${C_NC}"
        return
    fi
    
    # Define which keys are required for full functionality
    local required_keys=("GOOGLE_GEOCODING_API_KEY" "OPENWEATHER_API_KEY" "WINDY_API_KEY" "ACCUWEATHER_API_KEY")

    for key_name in "${required_keys[@]}"; do
        # Check if the key exists in the JSON response from the DB
        if echo "$existing_keys_json" | ${JQ_CMD} -e ".[] | select(.key_name == \"$key_name\")" > /dev/null; then
            echo -e "  ${C_GREEN}v${C_NC} Found key: ${key_name}"
        else
            echo -e "  ${C_YELLOW}!${C_NC} Missing key: ${key_name}"
            read -p "    Enter the value for ${key_name} (or press Enter to skip): " key_value
            if [ ! -z "$key_value" ]; then
                # User entered a key, so let's try to save it
                local post_data="{\"name\": \"${key_name}\", \"value\": \"${key_value}\"}"
                call_api "POST" "/api/keys" "${post_data}"
            fi
        fi
    done
}


# Function to print the final summary
print_summary() {
    print_header "Test Summary"
    local total=$((success_count + failure_count))
    echo -e "Total Tests: ${total}"
    echo -e "${C_GREEN}Successful:  ${success_count}${C_NC}"
    echo -e "${C_RED}Failed:      ${failure_count}${C_NC}"

    # If there were failures, print the detailed list
    if [ ${#failed_tests[@]} -gt 0 ]; then
        echo -e "\n${C_YELLOW}--- Failure Details (for easy copying) ---${C_NC}"
        printf " - %s\n" "${failed_tests[@]}"
    fi
    echo -e "\n"
}


# --- Test Execution ---

# Login check
print_header "Attempting Login"
# Use a simple, authenticated endpoint to verify login
call_api "GET" "/api/status" "" "silent" > /dev/null
if [ $? -ne 0 ]; then
    echo -e "${C_RED}Admin login failed. Please check your credentials and ensure the API is running.${C_NC}"
    exit 1
fi
echo -e "${C_GREEN}Login successful.${C_NC}"

# Manage API Keys (New Step)
manage_api_keys

print_header "Running Public Endpoint Tests"
call_api "GET" "/api/status"
call_api "GET" "/api/setup/user_count"

print_header "Running System & Hardware Endpoint Tests"
call_api "GET" "/api/hardware/system-stats"
call_api "GET" "/api/hardware/summary"
call_api "GET" "/api/hardware/gps/best"
call_api "GET" "/api/hardware/ups"
call_api "GET" "/api/hardware/time-sync"
call_api "GET" "/api/hardware/sensehat/data"
call_api "POST" "/api/hardware/bluetooth-scan"

print_header "Running Services Tests (Location, Weather, etc.)"
call_api "GET" "/api/services/location-test?location=Nashville,TN"
call_api "GET" "/api/services/weather-test"
call_api "GET" "/api/community/nearby?types=hospital"

print_header "Running Astronomy Tests"
call_api "GET" "/api/astronomy/sky-data"
call_api "GET" "/api/astronomy/satellite-passes?search=starlink"

print_header "Running Admin & Database Tests"
call_api "GET" "/api/database/stats"
call_api "GET" "/api/users"
call_api "GET" "/api/keys"

# --- Final Summary ---
print_summary
