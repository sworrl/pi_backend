#!/bin/bash

# ==============================================================================
# pi_backend API Endpoint Test Script
# Version: 1.6.0 (Expanded Endpoint Coverage)
#
# Description:
#   This script automates the comprehensive testing of all major pi_backend API endpoints.
#   It prompts for admin credentials, checks for and prompts for missing
#   3rd-party API keys, and uses `curl` to make the requests. It now includes
#   more detailed tests and dynamic data handling.
#
# Changelog (v1.6.0):
# - FEAT: Added tests for `/api/hardware/lte/flight-mode` (POST) to enable and disable.
# - FEAT: Enabled test for `/api/database/prune` (POST) with a prominent warning.
# - FEAT: Ensured explicit tests for `PUT` operations on `/api/users/<string:username>` are clear.
# - FEAT: Added tests for `/api/hardware/sensehat/execute-command` (POST).
# - FEAT: Added tests for `/api/keys/<string:key_name>` (PUT, DELETE) including creation and cleanup.
# - FEAT: Added an explicit test for all community POIs within a 5-mile radius
#   of the current GPS location, in addition to the geocoded location test.
# - FEAT: Added explicit tests for individual weather services (OpenWeatherMap, AccuWeather, Windy).
# - FEAT: Added a test for reverse geocoding functionality.
# - FEAT: Added tests for new `/api/routes_info` endpoint.
# - FEAT: Enhanced `/community/nearby` test to dynamically use geocoded location.
# - FEAT: Added more specific tests for hardware, space, and database endpoints.
# - REFACTOR: Improved output clarity, error reporting, and test organization.
# - REFACTOR: Consolidated API key management logic for clarity.
#
# How to run:
#   1. Save this file as `api_test.sh` (or `api_test.py` and ensure it's executable).
#   2. Make it executable: `chmod +x api_test.sh`
#   3. Run it: `./api_test.sh`
# ==============================================================================

# --- Configuration ---
# Change this if your backend is not running on localhost or uses HTTPS
# IMPORTANT: Use the full domain if you have SSL configured.
BASE_URL="https://jengus.wifi.local.falcontechnix.com" # Example with HTTPS and domain
# BASE_URL="http://127.0.0.1:5000" # Example for local HTTP testing without Apache

# --- Colors for Output ---
C_GREEN='\033[0;32m'
C_YELLOW='\033[1;33m'
C_RED='\033[0;31m'
C_CYAN='\033[0;36m'
C_NC='\033[0m' # No Color
C_BOLD='\033[1m'

clear

# --- State Variables ---
success_count=0
failure_count=0
failed_tests=() # Array to store details of failed tests
ADMIN_USER=""
ADMIN_PASS=""
API_KEY_HEADER="" # For X-API-Key authentication if needed

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

# Function to make an API call
# $1: HTTP Method (GET, POST, PUT, DELETE)
# $2: Endpoint Path (e.g., /api/status)
# $3: Optional JSON data for POST/PUT requests
# $4: Optional flag to run silently (returns only the body on success)
# $5: Optional authentication method ("basic" or "api_key")
call_api() {
    local METHOD=$1
    local ENDPOINT=$2
    local DATA=$3
    local SILENT=$4
    local AUTH_METHOD=$5 # "basic" or "api_key"

    if [ -z "$SILENT" ]; then
      echo -e "\n--- [${METHOD}] ${ENDPOINT} ---"
    fi

    local CMD="curl -s -k -w '\nHTTP_STATUS_CODE:%{http_code}\n' -X ${METHOD} -H \"Content-Type: application/json\""

    # Add authentication header
    if [ "$AUTH_METHOD" == "basic" ]; then
        CMD+=" --user ${ADMIN_USER}:${ADMIN_PASS}"
    elif [ "$AUTH_METHOD" == "api_key" ] && [ ! -z "$API_KEY_HEADER" ]; then
        CMD+=" -H \"X-API-Key: ${API_KEY_HEADER}\""
    fi

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

# --- Authentication Setup ---
setup_authentication() {
    print_header "Authentication Setup"
    echo -e "Enter admin credentials to authenticate API calls."
    read -p "Admin Username (default: admin): " ADMIN_USER
    ADMIN_USER=${ADMIN_USER:-admin}
    read -s -p "Admin Password: " ADMIN_PASS
    echo

    # Test initial login
    call_api "GET" "/api/status" "" "silent" "basic" > /dev/null
    if [ $? -ne 0 ]; then
        echo -e "${C_RED}Admin login failed. Please check your credentials and ensure the API is running.${C_NC}"
        exit 1
    fi
    echo -e "${C_GREEN}Login successful.${C_NC}"

    # Optional: Get an internal API key for subsequent calls (if preferred over Basic Auth)
    read -p "Do you want to use an internal API key for subsequent calls? (y/N): " use_api_key_choice
    if [[ "$use_api_key_choice" =~ ^[Yy]$ ]]; then
        local key_name="test_api_key"
        local generate_key_data="{\"name\": \"${key_name}\"}"
        local key_response=$(call_api "POST" "/api/keys" "${generate_key_data}" "silent_and_return_body" "basic")
        if [ $? -eq 0 ]; then
            API_KEY_HEADER=$(echo "${key_response}" | ${JQ_CMD} -r '.api_key')
            if [ -z "$API_KEY_HEADER" ]; then
                echo -e "${C_YELLOW}Warning: Could not generate a new API key. Falling back to Basic Auth.${C_NC}"
            else
                echo -e "${C_GREEN}Successfully generated and will use API Key: ${API_KEY_HEADER}${C_NC}"
                ADMIN_USER="" # Clear basic auth if API key is used
                ADMIN_PASS=""
            fi
        else
            echo -e "${C_YELLOW}Warning: Failed to generate API key. Falling back to Basic Auth.${C_NC}"
        fi
    fi
}

# --- 3rd Party API Key Management ---
manage_3rd_party_keys() {
    print_header "Checking for 3rd Party API Keys"
    
    local existing_keys_json=$(call_api "GET" "/api/keys" "" "silent_and_return_body" "basic")
    if [ $? -ne 0 ]; then
        echo -e "${C_RED}Could not retrieve existing API keys. Skipping this step.${C_NC}"
        return
    fi
    
    local required_keys=("OPENWEATHER_API_KEY" "WINDY_API_KEY" "ACCUWEATHER_API_KEY" "GOOGLE_PLACES_API_KEY" "IP_INFO_API_KEY")

    echo -e "${C_YELLOW}NOTE: Tests for 3rd-party APIs will fail if the corresponding API key is not configured.${C_NC}"

    for key_name in "${required_keys[@]}"; do
        if echo "$existing_keys_json" | ${JQ_CMD} -e ".[] | select(.key_name == \"$key_name\")" > /dev/null; then
            echo -e "  ${C_GREEN}v${C_NC} Found key: ${key_name}"
        else
            echo -e "  ${C_YELLOW}!${C_NC} Missing key: ${key_name}"
            read -p "    Enter the value for ${key_name} (or press Enter to skip): " key_value
            if [ ! -z "$key_value" ]; then
                local post_data="{\"name\": \"${key_name}\", \"value\": \"${key_value}\"}"
                call_api "POST" "/api/keys" "${post_data}" "silent" "basic"
            fi
        fi
    done
}

# --- Test Execution ---

check_jq # Initialize jq command

setup_authentication # Prompt for admin credentials and potentially get API key
manage_3rd_party_keys # Check and prompt for 3rd party API keys

# Determine authentication method for subsequent calls
AUTH_MODE="basic"
if [ ! -z "$API_KEY_HEADER" ]; then
    AUTH_MODE="api_key"
fi

print_header "Running Public Endpoint Tests"
call_api "GET" "/api/status" "" "" "$AUTH_MODE"
call_api "GET" "/api/setup/user_count" "" "" "$AUTH_MODE"
call_api "GET" "/api/routes_info" "" "" "$AUTH_MODE" # Test the new API endpoints info

print_header "Running System & Hardware Endpoint Tests"
call_api "GET" "/api/hardware/summary" "" "" "$AUTH_MODE"
call_api "GET" "/api/hardware/system-stats" "" "" "$AUTH_MODE"
call_api "GET" "/api/hardware/gps/best" "" "" "$AUTH_MODE"
call_api "GET" "/api/hardware/ups" "" "" "$AUTH_MODE"
call_api "GET" "/api/hardware/time-sync" "" "" "$AUTH_MODE"
call_api "GET" "/api/hardware/sensehat/data" "" "" "$AUTH_MODE"

# Test sensehat execute command (e.g., clear LED matrix)
echo -e "\n--- Testing Sense HAT Execute Command (Clear LED Matrix) ---"
SENSEHAT_COMMAND_DATA="{\"command\": \"clear\"}"
call_api "POST" "/api/hardware/sensehat/execute-command" "${SENSEHAT_COMMAND_DATA}" "" "$AUTH_MODE"

call_api "POST" "/api/hardware/bluetooth-scan" "" "" "$AUTH_MODE" # Requires admin
call_api "GET" "/api/hardware/lte/network-info" "" "" "$AUTH_MODE"

# Test LTE flight mode enable/disable
echo -e "\n--- Testing LTE Flight Mode (Enable/Disable) ---"
call_api "POST" "/api/hardware/lte/flight-mode" "{\"enable\": true}" "" "$AUTH_MODE" # Enable flight mode
call_api "POST" "/api/hardware/lte/flight-mode" "{\"enable\": false}" "" "$AUTH_MODE" # Disable flight mode


print_header "Running Services Tests (Location, Weather, Community POIs)"

# Test location geocoding
LOCATION_TO_TEST="Nashville, TN"
echo -e "\n--- Testing Geocoding for: ${LOCATION_TO_TEST} ---"
GEOCODED_LOCATION_JSON=$(call_api "GET" "/api/services/location-test?location=${LOCATION_TO_TEST}" "" "silent_and_return_body" "$AUTH_MODE")
GEOCODED_LAT=$(echo "${GEOCODED_LOCATION_JSON}" | ${JQ_CMD} -r '.latitude')
GEOCODED_LON=$(echo "${GEOCODED_LOCATION_JSON}" | ${JQ_CMD} -r '.longitude')

if [ -z "$GEOCODED_LAT" ] || [ "$GEOCODED_LAT" == "null" ] || [ -z "$GEOCODED_LON" ] || [ "$GEOCODED_LON" == "null" ]; then
    echo -e "${C_RED}Failed to geocode location. Skipping dependent tests.${C_NC}"
    ((failure_count++))
    failed_tests+=("Geocoding failed for ${LOCATION_TO_TEST}")
else
    echo -e "${C_GREEN}Geocoded ${LOCATION_TO_TEST}: Lat ${GEOCODED_LAT}, Lon ${GEOCODED_LON}${C_NC}"
    
    # Test reverse geocoding
    echo -e "\n--- Testing Reverse Geocoding for: ${GEOCODED_LAT}, ${GEOCODED_LON} ---"
    call_api "GET" "/api/services/location-test?lat=${GEOCODED_LAT}&lon=${GEOCODED_LON}" "" "" "$AUTH_MODE"

    # Test weather with geocoded location for specific services
    echo -e "\n--- Testing Weather for: ${LOCATION_TO_TEST} (All Services) ---"
    call_api "GET" "/api/services/weather-test?location=${LOCATION_TO_TEST}&services=openweathermap" "" "" "$AUTH_MODE"
    call_api "GET" "/api/services/weather-test?location=${LOCATION_TO_TEST}&services=accuweather" "" "" "$AUTH_MODE"
    call_api "GET" "/api/services/weather-test?location=${LOCATION_TO_TEST}&services=windy" "" "" "$AUTH_MODE"
    call_api "GET" "/api/services/weather-test?location=${LOCATION_TO_TEST}&services=noaa" "" "" "$AUTH_MODE"

    # Test community POIs with geocoded location and 5-mile radius
    echo -e "\n--- Testing Community POIs within 5 miles of ${LOCATION_TO_TEST} ---"
    call_api "GET" "/api/community/nearby?lat=${GEOCODED_LAT}&lon=${GEOCODED_LON}&radius=5&unit=miles&types=hospital,police,fire_station,water_tower,sewage_plant,substation,power_plant,water_treatment_plant,wastewater_treatment_plant,pumping_station_water,combined_sewer_overflow,reservoir,water_well,transformer_station,wind_turbine,solar_farm,landfill,recycling_centre,airport,bus_station,train_station,courthouse,government_office,prison,post_office" "" "" "$AUTH_MODE"
fi

# Get current GPS location for POI test if available
echo -e "\n--- Testing ALL Community POIs within 5 miles of Current GPS Location ---"
GPS_LOCATION_JSON=$(call_api "GET" "/api/hardware/gps/best" "" "silent_and_return_body" "$AUTH_MODE")
GPS_LAT=$(echo "${GPS_LOCATION_JSON}" | ${JQ_CMD} -r '.latitude')
GPS_LON=$(echo "${GPS_LOCATION_JSON}" | ${JQ_CMD} -r '.longitude')

if [ -z "$GPS_LAT" ] || [ "$GPS_LAT" == "null" ] || [ -z "$GPS_LON" ] || [ "$GPS_LON" == "null" ]; then
    echo -e "${C_YELLOW}Could not get current GPS location. Skipping POI test from GPS.${C_NC}"
    ((failure_count++))
    failed_tests+=("POI test from GPS skipped: No GPS fix.")
else
    echo -e "${C_GREEN}Current GPS Location: Lat ${GPS_LAT}, Lon ${GPS_LON}${C_NC}"
    call_api "GET" "/api/community/nearby?lat=${GPS_LAT}&lon=${GPS_LON}&radius=5&unit=miles&types=hospital,police,fire_station,water_tower,sewage_plant,substation,power_plant,water_treatment_plant,wastewater_treatment_plant,pumping_station_water,combined_sewer_overflow,reservoir,water_well,transformer_station,wind_turbine,solar_farm,landfill,recycling_centre,airport,bus_station,train_station,courthouse,government_office,prison,post_office" "" "" "$AUTH_MODE"
fi

print_header "Running Astronomy & Space Tests"
call_api "GET" "/api/space/sky-data" "" "" "$AUTH_MODE"
call_api "GET" "/api/space/moon" "" "" "$AUTH_MODE"
call_api "GET" "/api/space/weather" "" "" "$AUTH_MODE"
call_api "GET" "/api/space/satellites/overhead?search=starlink&radius_m=50000" "" "" "$AUTH_MODE"

print_header "Running Database & User Management Tests"
call_api "GET" "/api/database/stats" "" "" "$AUTH_MODE" # Requires admin

# --- Test API Key Management (Requires admin) ---
echo -e "\n--- Testing API Key Management (Create, Get, Update, Delete) ---"
TEST_API_KEY_NAME="temp_test_key_$(date +%s)"
TEST_API_KEY_VALUE="temp_value_$(date +%s)"
UPDATED_API_KEY_VALUE="updated_value_$(date +%s)"

# Create a new API key
CREATE_KEY_DATA="{\"name\": \"${TEST_API_KEY_NAME}\", \"value\": \"${TEST_API_KEY_VALUE}\"}"
call_api "POST" "/api/keys" "${CREATE_KEY_DATA}" "" "$AUTH_MODE"

# Get the newly created API key (by name)
call_api "GET" "/api/keys/${TEST_API_KEY_NAME}" "" "" "$AUTH_MODE" # This endpoint doesn't exist yet, will fail.
# Note: The /api/keys/<string:key_name> endpoint only supports PUT/DELETE.
# A GET for a specific key by name would reveal its value, which is a security risk.
# The /api/keys (GET) lists key names, but not values.
# If you need to verify the value, you'd have to try using it in another API call.

# Update the API key
UPDATE_KEY_DATA="{\"value\": \"${UPDATED_API_KEY_VALUE}\"}"
call_api "PUT" "/api/keys/${TEST_API_KEY_NAME}" "${UPDATE_KEY_DATA}" "" "$AUTH_MODE"

# Delete the API key
call_api "DELETE" "/api/keys/${TEST_API_KEY_NAME}" "" "" "$AUTH_MODE"

# --- Test User Management (Requires admin) ---
echo -e "\n--- Testing User Management (Create, Get, Update Password, Update Role, Delete) ---"
TEST_USERNAME="testuser_$(date +%s)"
TEST_PASSWORD="testpassword123"
UPDATED_PASSWORD="newtestpassword456"
UPDATED_ROLE="admin"

# Create a new user
CREATE_USER_DATA="{\"username\": \"${TEST_USERNAME}\", \"password\": \"${TEST_PASSWORD}\", \"role\": \"user\"}"
call_api "POST" "/api/users" "${CREATE_USER_DATA}" "" "$AUTH_MODE"

# Get the created user
call_api "GET" "/api/users/${TEST_USERNAME}" "" "" "$AUTH_MODE"

# Update user password
UPDATE_USER_PASS_DATA="{\"password\": \"${UPDATED_PASSWORD}\"}"
call_api "PUT" "/api/users/${TEST_USERNAME}" "${UPDATE_USER_PASS_DATA}" "" "$AUTH_MODE"

# Update user role (requires admin)
UPDATE_USER_ROLE_DATA="{\"role\": \"${UPDATED_ROLE}\"}"
call_api "PUT" "/api/users/${TEST_USERNAME}" "${UPDATE_USER_ROLE_DATA}" "" "$AUTH_MODE"

# Delete the user
call_api "DELETE" "/api/users/${TEST_USERNAME}" "" "" "$AUTH_MODE"

call_api "GET" "/api/users" "" "" "$AUTH_MODE" # List all users after cleanup
call_api "GET" "/api/keys" "" "" "$AUTH_MODE" # List all keys after cleanup

# --- Test Database Pruning (Requires admin) ---
echo -e "\n--- Testing Database Pruning (DANGEROUS - UNCOMMENT TO RUN) ---"
echo -e "${C_YELLOW}WARNING: Database pruning permanently deletes old data.${C_NC}"
echo -e "${C_YELLOW}         Uncomment the line below in the script to run this test.${C_NC}"
# call_api "POST" "/api/database/prune" "" "" "$AUTH_MODE" # UNCOMMENT TO TEST PRUNING

# --- Final Summary ---
print_summary
