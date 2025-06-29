# pi_backend/weather_services.py
# Version: 3.3.1 (Fix Application Context)
#
# Description: Fetches, aggregates, and normalizes weather data, including
#              detailed hourly and daily forecasts from all supported APIs.
#
# Changelog (v3.3.1):
# - FIX: Modified API fetching functions (`fetch_openweather_data`, etc.) to
#   explicitly accept a `db_manager` instance instead of relying on `current_app`.
#   This resolves "Working outside of application context" errors when called
#   from contexts like the data poller service.
# - REFACTOR: `fetch_all_weather_data` now requires `db_manager` and `config_manager`
#   to be passed explicitly for dependency injection.
#
# DEV_NOTES:
# - v3.3.0:
#   - FEATURE: Re-integrated and expanded all weather providers (OpenWeatherMap,
#     NOAA, Windy, AccuWeather).
#   - FEATURE: Expanded fetch and normalization functions to handle detailed
#     hourly and daily forecast data for building a rich UI.
#
import requests
import sys
import json
import time
import concurrent.futures
import logging # Added missing import
# Removed flask's current_app import as it will be passed explicitly
import location_services

__version__ = "3.3.1"

# --- INTERNAL DATA FETCHER (with retries) ---
def _internal_fetch_data(url_info):
    url = url_info.get("url")
    method = url_info.get("method", "GET").upper()
    headers = url_info.get("headers", {})
    body = url_info.get("body")
    if not url: return None, {"error": "No URL provided"}
    retries = 2
    for attempt in range(retries):
        try:
            if method == "POST":
                response = requests.post(url, json=body, headers=headers, timeout=15)
            else:
                response = requests.get(url, headers=headers, timeout=15)
            response.raise_for_status()
            return response.json() if response.content else {}, None
        except requests.exceptions.RequestException as e:
            # Log warning on retry, but only return error on final failure
            if attempt < retries - 1:
                logging.warning(f"Request to {url} failed (attempt {attempt+1}/{retries}): {e}. Retrying...")
                time.sleep(1) # Small delay before retry
            else:
                return None, {"error": f"Request to {url} failed after {retries} attempts: {e}"}
        except json.JSONDecodeError:
            return None, {"error": f"Invalid JSON response from {url}"}
    return None, {"error": f"Failed to fetch data from {url} after multiple retries (should not reach here)."}


# --- DATA NORMALIZATION/PARSING FUNCTIONS ---
def _normalize_openweather(data):
    if not data or 'main' not in data: return {"error": "Invalid OpenWeatherMap data"}
    return {
        "current": {
            "temperature_c": data.get("main", {}).get("temp"),
            "description": data.get("weather", [{}])[0].get("description"),
            "icon": data.get("weather", [{}])[0].get("icon"),
        },
        "hourly": [], # OWM free tier doesn't provide easy hourly forecasts
        "daily": []   # OWM free tier doesn't provide easy daily forecasts
    }

def _normalize_noaa(data):
    if not data or 'properties' not in data or not data['properties'].get('periods'):
        return {"error": "Invalid NOAA data"}

    periods = data['properties']['periods']
    current_period = periods[0] if periods else {} # Handle empty periods gracefully

    daily_forecast = []
    # NOAA provides forecast in ~12h periods. We can group them by day.
    day_entries = {}
    for p in periods:
        date = p['startTime'][:10]
        if date not in day_entries:
            day_entries[date] = {"date": date, "day": None, "night": None}

        # Convert Fahrenheit to Celsius for NOAA, and ensure temperature exists
        temp_f = p.get("temperature")
        temp_c = round((temp_f - 32) * 5/9, 2) if temp_f is not None else None

        if p.get('isDaytime'):
            day_entries[date]['day'] = {
                "temp_c": temp_c,
                "description": p.get("shortForecast")
            }
        else:
            day_entries[date]['night'] = {
                "temp_c": temp_c,
                "description": p.get("shortForecast")
            }
    daily_forecast = list(day_entries.values())

    # Current temperature for NOAA needs to be converted from Fahrenheit
    current_temp_f = current_period.get("temperature")
    current_temp_c = round((current_temp_f - 32) * 5/9, 2) if current_temp_f is not None else None

    return {
        "current": {
            "temperature_c": current_temp_c,
            "description": current_period.get("shortForecast"),
            "icon_url": current_period.get("icon")
        },
        "hourly": [], # NOAA standard API doesn't provide a simple hourly list
        "daily": daily_forecast[:7]
    }

def _normalize_windy(data):
    if not data or "temp-surface" not in data: return {"error": "Invalid Windy data"}
    return {
        "current": {
            # Windy.com GFS model gives temperature in Kelvin, convert to Celsius
            "temperature_c": round(data["temp-surface"][0] - 273.15, 2) if data.get("temp-surface") and data["temp-surface"][0] is not None else None,
            "description": "Windy.com GFS Model"
        },
        "hourly": [], # Requires different API call
        "daily": []
    }

def _normalize_accuweather(data):
    if not data or not isinstance(data, list) or not data: return {"error": "Invalid AccuWeather data"}
    current = data[0]
    return {
        "current": {
            "temperature_c": current.get("Temperature", {}).get("Metric", {}).get("Value"),
            "description": current.get("WeatherText")
        },
        "hourly": [], # Requires different API call
        "daily": []
    }

# --- API-SPECIFIC FETCHING FUNCTIONS ---
# These functions now explicitly accept db_manager to get API keys
def fetch_openweather_data(lat, lon, db_manager):
    api_key = db_manager.get_key_value_by_name('OPENWEATHER_API_KEY')
    if not api_key: return None, {"error": "OPENWEATHER_API_KEY not found in database."}
    url = f"https://api.openweathermap.org/data/2.5/weather?lat={lat}&lon={lon}&appid={api_key}&units=metric"
    return _internal_fetch_data({"url": url})

def fetch_noaa_data(lat, lon, db_manager): # db_manager added, though NOAA typically doesn't need API key
    headers = {'User-Agent': '(pi_backend, contact@example.com)'} # Updated User-Agent for NOAA
    points_url = f"https://api.weather.gov/points/{lat},{lon}"
    points_data, error = _internal_fetch_data({"url": points_url, "headers": headers})
    if error: return None, error
    forecast_url = points_data.get("properties", {}).get("forecast")
    if not forecast_url: return None, {"error": "Could not find forecast URL in NOAA points data."}
    return _internal_fetch_data({"url": forecast_url, "headers": headers})

def fetch_windy_data(lat, lon, db_manager):
    api_key = db_manager.get_key_value_by_name('WINDY_API_KEY')
    if not api_key: return None, {"error": "WINDY_API_KEY not found in database."}
    payload = {
        "url": "https://api.windy.com/api/point-forecast/v2", "method": "POST",
        "headers": {"Content-Type": "application/json"},
        "body": {"lat": lat, "lon": lon, "model": "gfs", "parameters": ["temp", "rh", "wind"], "levels": ["surface"], "key": api_key}
    }
    return _internal_fetch_data(payload)

def fetch_accuweather_data(lat, lon, db_manager):
    api_key = db_manager.get_key_value_by_name('ACCUWEATHER_API_KEY')
    if not api_key: return None, {"error": "ACCUWEATHER_API_KEY not found in database."}

    location_key_url = f"http://dataservice.accuweather.com/locations/v1/cities/geoposition/search?apikey={api_key}&q={lat}%2C{lon}"
    location_data, error = _internal_fetch_data({"url": location_key_url})
    if error: return None, error
    location_key = location_data.get("Key")
    if not location_key: return None, {"error": "Failed to get AccuWeather location key."}

    conditions_url = f"http://dataservice.accuweather.com/currentconditions/v1/{location_key}?apikey={api_key}&details=true"
    return _internal_fetch_data({"url": conditions_url})

# --- MAIN ORCHESTRATION FUNCTION ---
def fetch_all_weather_data(location_query, db_manager, config_manager, services=None):
    """
    Orchestrates fetching data from multiple weather APIs, and normalizes the results.
    Accepts db_manager and config_manager for dependency injection.
    """
    # location_services now also accepts db_manager/config_manager
    lat, lon, resolved_info = location_services.get_location_details(
        location_query=location_query,
        db_manager=db_manager,
        config_manager=config_manager
    )
    if lat is None or lon is None:
        return {"error": f"Failed to resolve location: {resolved_info.get('error', 'Unknown reason')}"}

    combined_data = {"location": resolved_info, "weather_data": {}}

    service_map = {
        'openweathermap': {'fetch': fetch_openweather_data, 'normalize': _normalize_openweather},
        'noaa': {'fetch': fetch_noaa_data, 'normalize': _normalize_noaa},
        'windy': {'fetch': fetch_windy_data, 'normalize': _normalize_windy},
        'accuweather': {'fetch': fetch_accuweather_data, 'normalize': _normalize_accuweather}
    }

    target_services = services if services else list(service_map.keys())

    with concurrent.futures.ThreadPoolExecutor(max_workers=len(target_services)) as executor:
        # Pass db_manager to each fetching function
        future_to_service = {executor.submit(service_map[s]['fetch'], lat, lon, db_manager): s for s in target_services if s in service_map}
        for future in concurrent.futures.as_completed(future_to_service):
            service_name = future_to_service[future]
            try:
                raw_data, error = future.result()
                if error:
                    combined_data["weather_data"][service_name] = {"error": error.get("error")}
                    continue
                normalizer = service_map[service_name]['normalize']
                normalized_data = normalizer(raw_data)
                combined_data["weather_data"][service_name] = {
                    "raw_data": raw_data,
                    "normalized_data": normalized_data
                }
            except Exception as exc:
                combined_data["weather_data"][service_name] = {"error": f"Unexpected error: {exc}"}
    return combined_data