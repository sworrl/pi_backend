#
# File: community_services.py
# Version: 1.1.0 (PFAS Site Integration)
#
# Description: This module provides functionality to find nearby points of
#              interest (POIs) by querying OpenStreetMap and local data files.
#
# Changelog (v1.1.0):
# - FEATURE: Added functionality to find the nearest PFAS site by loading
#   data from a local JSON file (`/var/lib/pi_backend/pfas_sites.json`).
# - FIX: Added missing `import math` for bounding box calculation.
#
import requests
import json
import math
from geopy import distance
from concurrent.futures import ThreadPoolExecutor

# Overpass API endpoint for general POIs
OVERPASS_API_URL = "https://overpass-api.de/api/interpreter"
# Local data file for specialized PFAS data
PFAS_DATA_FILE = "/var/lib/pi_backend/pfas_sites.json"

POI_QUERIES = {
    "police": '[out:json];node["amenity"="police"]({{bbox}});out;',
    "fire_station": '[out:json];node["amenity"="fire_station"]({{bbox}});out;',
    "hospital": '[out:json];node["amenity"="hospital"]({{bbox}});out;',
    "post_office": '[out:json];node["amenity"="post_office"]({{bbox}});out;',
    "prison": '[out:json];node["amenity"="prison"]({{bbox}});out;',
    "townhall": '[out:json];node["amenity"="townhall"]({{bbox}});out;',
    "power_plant": '[out:json];node["power"="plant"]({{bbox}});out;',
    "water_tower": '[out:json];node["man_made"="water_tower"]({{bbox}});out;',
    "water_works": '[out:json];node["man_made"="water_works"]({{bbox}});out;',
}

def _calculate_bounding_box(lat, lon, search_radius_km=50):
    """Creates a bounding box string for the Overpass API query."""
    lat_change = search_radius_km / 111.1
    lon_change = search_radius_km / (111.1 * abs(math.cos(math.radians(lat))))
    min_lat, max_lat = lat - lat_change, lat + lat_change
    min_lon, max_lon = lon - lon_change, lon + lon_change
    return f"{min_lat},{min_lon},{max_lat},{max_lon}"

def _find_closest_poi(origin_lat, origin_lon, poi_list):
    """Calculates the distance to each POI and returns the closest one."""
    closest_poi = None
    min_dist = float('inf')
    if not poi_list:
        return None

    for poi in poi_list:
        poi_lat, poi_lon = poi.get('lat'), poi.get('lon')
        if poi_lat is None or poi_lon is None:
            continue
        dist = distance.distance((origin_lat, origin_lon), (poi_lat, poi_lon)).km
        if dist < min_dist:
            min_dist = dist
            closest_poi = poi
            closest_poi['distance_km'] = round(dist, 2)
    return closest_poi

def _fetch_overpass_pois(poi_type, bbox):
    """Fetches and processes POIs for a single type from Overpass API."""
    if poi_type not in POI_QUERIES:
        return poi_type, {"error": "Unknown POI type"}
    query = POI_QUERIES[poi_type].replace('{{bbox}}', bbox)
    try:
        response = requests.post(OVERPASS_API_URL, data=query, timeout=30)
        response.raise_for_status()
        return poi_type, response.json().get('elements', [])
    except requests.RequestException as e:
        return poi_type, {"error": f"API request failed: {e}"}
    except json.JSONDecodeError:
        return poi_type, {"error": "Failed to decode API response"}

def _load_pfas_data():
    """Loads PFAS site data from the local JSON file."""
    try:
        with open(PFAS_DATA_FILE, 'r') as f:
            return json.load(f)
    except FileNotFoundError:
        return {"error": f"PFAS data file not found at {PFAS_DATA_FILE}"}
    except json.JSONDecodeError:
        return {"error": "Failed to parse PFAS JSON file."}
    except Exception as e:
        return {"error": f"An unexpected error occurred loading PFAS data: {e}"}

def get_nearby_pois(lat, lon, types=None):
    """
    Finds the closest POIs for a given set of types around a lat/lon.
    Handles general POIs from Overpass and specialized data from local files.
    """
    if types is None:
        types = list(POI_QUERIES.keys()) + ["pfas_site"]

    results = {}
    overpass_types = [t for t in types if t in POI_QUERIES]

    # Handle special local data sources first
    if 'pfas_site' in types:
        pfas_data = _load_pfas_data()
        if isinstance(pfas_data, dict) and "error" in pfas_data:
            results['pfas_site'] = pfas_data
        else:
            closest_pfas = _find_closest_poi(lat, lon, pfas_data)
            if closest_pfas:
                results['pfas_site'] = {
                    "name": closest_pfas.get("name", "N/A"),
                    "distance_km": closest_pfas.get("distance_km"),
                    "latitude": closest_pfas.get("lat"),
                    "longitude": closest_pfas.get("lon"),
                    "tags": closest_pfas.get("tags", {})
                }
            else:
                 results['pfas_site'] = {"message": "No PFAS sites found in local data file."}

    # Handle standard Overpass queries concurrently
    if overpass_types:
        bbox = _calculate_bounding_box(lat, lon, search_radius_km=50) 
        with ThreadPoolExecutor(max_workers=len(overpass_types)) as executor:
            future_to_poi = {executor.submit(_fetch_overpass_pois, poi_type, bbox): poi_type for poi_type in overpass_types}
            for future in concurrent.futures.as_completed(future_to_poi):
                poi_type = future_to_poi[future]
                try:
                    _, poi_list = future.result()
                    if isinstance(poi_list, dict) and "error" in poi_list:
                        results[poi_type] = poi_list
                        continue

                    closest = _find_closest_poi(lat, lon, poi_list)
                    if closest:
                        tags = closest.get('tags', {})
                        results[poi_type] = {
                            "name": tags.get("name", "N/A"),
                            "distance_km": closest.get("distance_km"),
                            "latitude": closest.get("lat"),
                            "longitude": closest.get("lon"),
                            "address": f"{tags.get('addr:housenumber', '')} {tags.get('addr:street', '')}".strip()
                        }
                    else:
                        results[poi_type] = {"message": "No matching POI found in search area."}
                except Exception as e:
                    results[poi_type] = {"error": f"An unexpected error occurred: {e}"}

    return results

