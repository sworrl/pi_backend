# pi_backend/weather_services.py
# Version: 3.4.0 (Meteorologist's Dream)
#
# Description: Fetches, aggregates, and normalizes comprehensive weather data,
#              including detailed current conditions, hourly, and daily forecasts
#              from all supported APIs.
#
# Changelog (v3.4.0):
# - FEAT: Expanded data extraction and normalization for OpenWeatherMap, NOAA,
#   Windy, and AccuWeather to include more detailed meteorological parameters
#   (e.g., wind gust, visibility, cloud cover, UV index, dew point, pressure at sea level,
#   precipitation details).
# - FEAT: Improved hourly and daily forecast parsing for all APIs where available.
# - REFACTOR: Enhanced error handling and logging within normalization functions.
# - FIX: Modified API fetching functions (`fetch_openweather_data`, etc.) to
#   explicitly accept a `db_manager` instance instead of relying on `current_app`.
#
import requests
import sys
import json
import time
import concurrent.futures
import logging
from datetime import datetime, timedelta, timezone # Added timezone for UTC handling
import location_services

__version__ = "3.4.0"

# --- INTERNAL DATA FETCHER (with retries) ---
def _internal_fetch_data(url_info):
    url = url_info.get("url")
    method = url_info.get("method", "GET").upper()
    headers = url_info.get("headers", {})
    body = url_info.get("body")
    if not url: return None, {"error": "No URL provided"}
    retries = 3 # Increased retries
    for attempt in range(retries):
        try:
            if method == "POST":
                response = requests.post(url, json=body, headers=headers, timeout=15)
            else:
                response = requests.get(url, headers=headers, timeout=15)
            response.raise_for_status()
            return response.json() if response.content else {}, None
        except requests.exceptions.Timeout:
            logging.warning(f"Request to {url} timed out (attempt {attempt+1}/{retries}). Retrying...")
            time.sleep(2) # Longer delay for timeouts
        except requests.exceptions.ConnectionError as e:
            logging.warning(f"Connection error to {url} (attempt {attempt+1}/{retries}): {e}. Retrying...")
            time.sleep(2)
        except requests.exceptions.RequestException as e:
            if attempt < retries - 1:
                logging.warning(f"Request to {url} failed (attempt {attempt+1}/{retries}): {e}. Retrying...")
                time.sleep(1)
            else:
                logging.error(f"Request to {url} failed after {retries} attempts: {e}")
                return None, {"error": f"Request to {url} failed after {retries} attempts: {e}"}
        except json.JSONDecodeError:
            logging.error(f"Invalid JSON response from {url}")
            return None, {"error": f"Invalid JSON response from {url}"}
    return None, {"error": f"Failed to fetch data from {url} after multiple retries (should not reach here)."}


# --- DATA NORMALIZATION/PARSING FUNCTIONS ---
def _normalize_openweather(data):
    if not data or 'main' not in data:
        return {"error": "Invalid OpenWeatherMap data"}

    current = data.get("main", {})
    weather_desc = data.get("weather", [{}])[0]
    wind = data.get("wind", {})
    clouds = data.get("clouds", {})
    sys_info = data.get("sys", {})

    normalized = {
        "current": {
            "timestamp_utc": datetime.fromtimestamp(data.get("dt", time.time()), tz=timezone.utc).isoformat(),
            "temperature_c": current.get("temp"),
            "feels_like_c": current.get("feels_like"),
            "description": weather_desc.get("description"),
            "icon": weather_desc.get("icon"),
            "humidity_percent": current.get("humidity"),
            "pressure_hpa": current.get("pressure"),
            "sea_level_pressure_hpa": current.get("sea_level"), # Not always available
            "ground_level_pressure_hpa": current.get("grnd_level"), # Not always available
            "wind_speed_mps": wind.get("speed"),
            "wind_direction_deg": wind.get("deg"),
            "wind_gust_mps": wind.get("gust"),
            "visibility_m": data.get("visibility"),
            "cloud_cover_percent": clouds.get("all"),
            "sunrise_utc": datetime.fromtimestamp(sys_info.get("sunrise", 0), tz=timezone.utc).isoformat() if sys_info.get("sunrise") else None,
            "sunset_utc": datetime.fromtimestamp(sys_info.get("sunset", 0), tz=timezone.utc).isoformat() if sys_info.get("sunset") else None,
            "rain_1h_mm": data.get("rain", {}).get("1h"),
            "rain_3h_mm": data.get("rain", {}).get("3h"),
            "snow_1h_mm": data.get("snow", {}).get("1h"),
            "snow_3h_mm": data.get("snow", {}).get("3h"),
        },
        "hourly": [], # OpenWeatherMap's free tier 'weather' endpoint doesn't provide hourly
        "daily": []   # OpenWeatherMap's free tier 'weather' endpoint doesn't provide daily
    }
    return normalized

def _normalize_noaa(data):
    if not data or 'properties' not in data or not data['properties'].get('periods'):
        return {"error": "Invalid NOAA data"}

    periods = data['properties']['periods']
    
    current_data = {}
    hourly_forecast = []
    daily_forecast = []

    # NOAA provides forecast in ~12h periods. First period is current/next 12h.
    if periods:
        # Current conditions from the first period
        first_period = periods[0]
        current_temp_f = first_period.get("temperature")
        current_temp_c = round((current_temp_f - 32) * 5/9, 2) if current_temp_f is not None else None
        
        current_data = {
            "timestamp_utc": first_period.get("startTime"),
            "temperature_c": current_temp_c,
            "description": first_period.get("shortForecast"),
            "icon_url": first_period.get("icon"),
            "wind_speed_mph": first_period.get("windSpeed"), # NOAA provides mph
            "wind_direction": first_period.get("windDirection"),
            "is_daytime": first_period.get("isDaytime"),
            "detailed_forecast": first_period.get("detailedForecast")
        }

        # Process hourly (effectively 12-hour blocks) and daily
        day_entries = {}
        for p in periods:
            # For hourly, we'll just take the periods as they are, converting temp
            hourly_temp_f = p.get("temperature")
            hourly_temp_c = round((hourly_temp_f - 32) * 5/9, 2) if hourly_temp_f is not None else None
            hourly_forecast.append({
                "timestamp_utc": p.get("startTime"),
                "temperature_c": hourly_temp_c,
                "description": p.get("shortForecast"),
                "icon_url": p.get("icon"),
                "wind_speed_mph": p.get("windSpeed"),
                "wind_direction": p.get("windDirection"),
                "is_daytime": p.get("isDaytime")
            })

            # For daily, group by date and find min/max temps
            date_str = p['startTime'][:10]
            if date_str not in day_entries:
                day_entries[date_str] = {
                    "date": date_str,
                    "time_utc": p['startTime'], # Use start time of first period for the day
                    "temp_max_c": -float('inf'),
                    "temp_min_c": float('inf'),
                    "description_day": None,
                    "description_night": None,
                    "icon_day_url": None,
                    "icon_night_url": None
                }
            
            if p.get("temperature") is not None:
                temp_c = round((p["temperature"] - 32) * 5/9, 2)
                day_entries[date_str]["temp_max_c"] = max(day_entries[date_str]["temp_max_c"], temp_c)
                day_entries[date_str]["temp_min_c"] = min(day_entries[date_str]["temp_min_c"], temp_c)
            
            if p.get('isDaytime'):
                day_entries[date_str]['description_day'] = p.get("shortForecast")
                day_entries[date_str]['icon_day_url'] = p.get("icon")
            else:
                day_entries[date_str]['description_night'] = p.get("shortForecast")
                day_entries[date_str]['icon_night_url'] = p.get("icon")
        
        for date_str, data in day_entries.items():
            # Handle cases where min/max might still be inf if no temps were found
            if data["temp_max_c"] == -float('inf'): data["temp_max_c"] = None
            if data["temp_min_c"] == float('inf'): data["temp_min_c"] = None
            
            daily_forecast.append({
                "date": data["date"],
                "time_utc": data["time_utc"],
                "temp_max_c": data["temp_max_c"],
                "temp_min_c": data["temp_min_c"],
                "description_day": data["description_day"],
                "description_night": data["description_night"],
                "icon_day_url": data["icon_day_url"],
                "icon_night_url": data["icon_night_url"]
            })
    
    return {
        "current": current_data,
        "hourly": hourly_forecast, # NOAA periods are already somewhat hourly/12-hourly
        "daily": daily_forecast[:7] # Limit to 7 days
    }

def _normalize_windy(data):
    if not data or "temp-surface" not in data: return {"error": "Invalid Windy data"}
    
    # Windy GFS model data is typically arrays of values over time
    # Assuming the first element is current
    current_temp_k = data.get("temp-surface", [None])[0]
    current_temp_c = round(current_temp_k - 273.15, 2) if current_temp_k is not None else None
    
    current_rh = data.get("rh-surface", [None])[0] # Relative humidity
    current_wind_u = data.get("wind_u-surface", [None])[0] # U-component of wind (east-west)
    current_wind_v = data.get("wind_v-surface", [None])[0] # V-component of wind (north-south)
    current_pressure_pa = data.get("pressure-surface", [None])[0] # Pressure in Pascals
    current_tcc = data.get("total_cloud_cover-surface", [None])[0] # Total cloud cover (0-1)

    wind_speed_mps = None
    wind_direction_deg = None
    if current_wind_u is not None and current_wind_v is not None:
        wind_speed_mps = math.sqrt(current_wind_u**2 + current_wind_v**2)
        wind_direction_deg = (math.degrees(math.atan2(current_wind_u, current_wind_v)) + 360) % 360 # Convert to meteorological degrees

    normalized = {
        "current": {
            "timestamp_utc": datetime.now(timezone.utc).isoformat(), # Windy point forecast doesn't give precise current timestamp
            "temperature_c": current_temp_c,
            "description": "Windy.com GFS Model", # No textual description from this endpoint
            "humidity_percent": round(current_rh * 100, 2) if current_rh is not None else None,
            "pressure_hpa": round(current_pressure_pa / 100, 2) if current_pressure_pa is not None else None, # Pa to hPa
            "wind_speed_mps": round(wind_speed_mps, 2) if wind_speed_mps is not None else None,
            "wind_direction_deg": round(wind_direction_deg, 2) if wind_direction_deg is not None else None,
            "cloud_cover_percent": round(current_tcc * 100, 2) if current_tcc is not None else None,
        },
        "hourly": [], # Requires different API call or more complex parsing of GFS model output
        "daily": []
    }
    return normalized

def _normalize_accuweather(data):
    if not data or not isinstance(data, list) or not data: return {"error": "Invalid AccuWeather data"}
    current_conditions = data[0]

    normalized = {
        "current": {
            "timestamp_utc": current_conditions.get("LocalObservationDateTime"),
            "temperature_c": current_conditions.get("Temperature", {}).get("Metric", {}).get("Value"),
            "feels_like_c": current_conditions.get("RealFeelTemperature", {}).get("Metric", {}).get("Value"),
            "description": current_conditions.get("WeatherText"),
            "icon": current_conditions.get("WeatherIcon"), # Numeric icon code
            "humidity_percent": current_conditions.get("RelativeHumidity"),
            "pressure_hpa": current_conditions.get("Pressure", {}).get("Metric", {}).get("Value"),
            "wind_speed_mps": current_conditions.get("Wind", {}).get("Speed", {}).get("Metric", {}).get("Value"),
            "wind_direction_deg": current_conditions.get("Wind", {}).get("Direction", {}).get("Degrees"),
            "wind_direction_cardinal": current_conditions.get("Wind", {}).get("Direction", {}).get("Localized"),
            "visibility_m": current_conditions.get("Visibility", {}).get("Metric", {}).get("Value"),
            "cloud_cover_percent": current_conditions.get("CloudCover"),
            "uv_index": current_conditions.get("UVIndex"),
            "dew_point_c": current_conditions.get("DewPoint", {}).get("Metric", {}).get("Value"),
            "precip_1h_mm": current_conditions.get("PrecipitationSummary", {}).get("Precipitation", {}).get("Metric", {}).get("Value"),
            "is_day_time": current_conditions.get("IsDayTime")
        },
        "hourly": [], # Requires different API call
        "daily": []
    }
    return normalized

# --- API-SPECIFIC FETCHING FUNCTIONS ---
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
    
    # Define all parameters to fetch for a comprehensive dataset
    parameters = [
        "temp", "rh", "wind_u", "wind_v", "pressure", "total_cloud_cover",
        "dewpoint", "uv_index", "precipitation", "snow_depth"
    ]
    levels = ["surface"] # Can add more levels if needed, e.g., "500hpa"

    payload = {
        "url": "https://api.windy.com/api/point-forecast/v2", "method": "POST",
        "headers": {"Content-Type": "application/json"},
        "body": {
            "lat": lat, "lon": lon, "model": "gfs",
            "parameters": parameters,
            "levels": levels,
            "key": api_key
        }
    }
    return _internal_fetch_data(payload)

def fetch_accuweather_data(lat, lon, db_manager):
    api_key = db_manager.get_key_value_by_name('ACCUWEATHER_API_KEY')
    if not api_key: return None, {"error": "ACCUWEATHER_API_KEY not found in database."}

    location_key_url = f"http://dataservice.accuweather.com/locations/v1/cities/geoposition/search?apikey={api_key}&q={lat}%2C{lon}&details=true"
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
                logging.error(f"Error processing weather data for {service_name}: {exc}", exc_info=True)
                combined_data["weather_data"][service_name] = {"error": f"Unexpected error: {exc}"}
    return combined_data
