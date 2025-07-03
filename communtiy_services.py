#
# File: community_services.py
# Version: 1.5.0 (Overpass Rate Limit Mitigation)
#
# Description: This module provides functionality to find nearby points of
#              interest (POIs) by querying OpenStreetMap and local data files,
#              with optional enrichment from Google Places API.
#
# Changelog (v1.5.0):
# - FEAT: Added a `time.sleep(1)` delay before each Overpass API request in
#   `_fetch_overpass_pois` to mitigate `429 Too Many Requests` errors.
# - FEAT: Expanded `POI_QUERIES` to include a much wider range of infrastructure
#   types (sewage plants, sewage pumps, substations, landfills, water treatment,
#   government offices, airports, train stations, etc.).
# - REFACTOR: `_extract_poi_details` now uses more robust logic to find names
#   and addresses from various OSM tags and handles `relation` geometries.
# - FEAT: `_enrich_poi_with_google_places` is now actively called for each POI
#   to append data from Google Places API if a key is available.
# - FIX: Improved error handling and logging for API calls.
#
import requests
import json
import math
from geopy import distance
from concurrent.futures import ThreadPoolExecutor
import concurrent.futures
import logging
import sys
import time # Added for time.sleep

# Overpass API endpoint for general POIs
OVERPASS_API_URL = "https://overpass-api.de/api/interpreter"
# Local data file for specialized PFAS data
PFAS_DATA_FILE = "/var/lib/pi_backend/pfas_sites.json"

__version__ = "1.5.0"

# Configure logging for this module
logging.basicConfig(level=logging.INFO, stream=sys.stdout, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')

# Expanded POI Queries for infrastructure and other relevant points
POI_QUERIES = {
    # Emergency Services
    "police": '[out:json];node["amenity"="police"]({{bbox}});out;',
    "fire_station": '[out:json];node["amenity"="fire_station"]({{bbox}});out;',
    "hospital": '[out:json];node["amenity"="hospital"]({{bbox}});out;',
    
    # Public Services & Government
    "post_office": '[out:json];node["amenity"="post_office"]({{bbox}});out;',
    "townhall": '[out:json];node["amenity"="townhall"]({{bbox}});out;',
    "courthouse": '[out:json];node["amenity"="courthouse"]({{bbox}});out;',
    "government_office": '[out:json];node["office"="government"]({{bbox}});out;',
    "prison": '[out:json];node["amenity"="prison"]({{bbox}});out;',
    
    # Water Infrastructure
    "water_tower": '[out:json];node["man_made"="water_tower"]({{bbox}});out;',
    "water_treatment_plant": '[out:json];node["water_management"="plant"]({{bbox}});out;node["industrial"="water_treatment"]({{bbox}});out;', # More specific for treatment
    "wastewater_treatment_plant": '[out:json];node["wastewater"="plant"]({{bbox}});out;node["industrial"="wastewater_treatment"]({{bbox}});out;', # More specific for treatment
    "pumping_station_water": '[out:json];node["man_made"="pumping_station"]["pump"="water"]({{bbox}});out;', # Water pumping stations
    "sewage_pumping_station": '[out:json];node["man_made"="sewage_pumping_station"]({{bbox}});out;', # Sewage pumping stations
    "combined_sewer_overflow": '[out:json];node["sewage"="combined_sewer_overflow"]({{bbox}});out;', # CSOs
    "reservoir": '[out:json];node["natural"="reservoir"]({{bbox}});out;way["natural"="reservoir"]({{bbox}});relation["natural"="reservoir"]({{bbox}});out center;', # Large water bodies
    "water_well": '[out:json];node["man_made"="water_well"]({{bbox}});out;', # Significant wells

    # Energy Infrastructure
    "power_plant": '[out:json];node["power"="plant"]({{bbox}});out;',
    "substation": '[out:json];node["power"="substation"]({{bbox}});out;',
    "transformer_station": '[out:json];node["power"="transformer_station"]({{bbox}});out;', # Larger transformer stations
    "wind_turbine": '[out:json];node["power"="generator"]["generator:source"="wind"]({{bbox}});out;',
    "solar_farm": '[out:json];node["power"="generator"]["generator:source"="solar"]({{bbox}});out;relation["power"="generator"]["generator:source"="solar"]({{bbox}});out center;',

    # Waste Management
    "landfill": '[out:json];node["landuse"="landfill"]({{bbox}});out;',
    "recycling_centre": '[out:json];node["amenity"="recycling"]["recycling_type"="centre"]({{bbox}});out;', # Larger recycling centers

    # Transportation Hubs (major ones)
    "airport": '[out:json];node["aeroway"="aerodrome"]({{bbox}});out;relation["aeroway"="aerodrome"]({{bbox}});out center;',
    "bus_station": '[out:json];node["amenity"="bus_station"]({{bbox}});out;',
    "train_station": '[out:json];node["railway"="station"]({{bbox}});out;',
}


def _calculate_bounding_box(lat, lon, search_radius_km):
    """Creates a bounding box string for the Overpass API query."""
    # 1 degree of latitude is approximately 111.1 km
    # 1 degree of longitude is approximately 111.1 * cos(latitude) km
    lat_change = search_radius_km / 111.1
    lon_change = search_radius_km / (111.1 * abs(math.cos(math.radians(lat))))
    min_lat, max_lat = lat - lat_change, lat + lat_change
    min_lon, max_lon = lon - lon_change, lon + lon_change
    return f"{min_lat},{min_lon},{max_lat},{max_lon}"

def _extract_poi_details(element, poi_type):
    """
    Extracts comprehensive POI details from an Overpass API element.
    Prioritizes common tags and provides fallbacks.
    """
    tags = element.get('tags', {})
    
    name = tags.get("name") or tags.get("operator") or tags.get("ref") or tags.get("description")
    if not name:
        # Generate a name if none explicitly found, e.g., "Water Tower (ID: 12345)"
        name = f"{poi_type.replace('_', ' ').title()} (OSM ID: {element.get('id', 'N/A')})"

    address_parts = []
    if tags.get('addr:housenumber'): address_parts.append(tags['addr:housenumber'])
    if tags.get('addr:street'): address_parts.append(tags['addr:street'])
    if tags.get('addr:city'): address_parts.append(tags['addr:city'])
    if tags.get('addr:postcode'): address_parts.append(tags['addr:postcode'])
    address = ", ".join(filter(None, address_parts)).strip() or tags.get('addr:full')

    phone = tags.get("phone") or tags.get("contact:phone")
    website = tags.get("website") or tags.get("contact:website")
    opening_hours = tags.get("opening_hours")

    return {
        "osm_id": element.get('id'),
        "poi_type": poi_type,
        "name": name,
        "latitude": element.get('lat') or element.get('center', {}).get('lat'), # Handle relations
        "longitude": element.get('lon') or element.get('center', {}).get('lon'), # Handle relations
        "address": address or "N/A",
        "phone": phone or "N/A",
        "website": website or "N/A",
        "opening_hours": opening_hours or "N/A",
        "full_tags": tags # Store all tags for full detail
    }

def _fetch_overpass_pois(poi_type, bbox):
    """Fetches and processes POIs for a single type from Overpass API."""
    if poi_type not in POI_QUERIES:
        return poi_type, {"error": "Unknown POI type"}
    query = POI_QUERIES[poi_type].replace('{{bbox}}', bbox)
    
    # For relations (e.g., landuse=water_management), we need to request their center
    if "relation" in query or "way" in query: # Also include 'way' for relations that are ways
        query = query.replace("out;", "out center;")

    try:
        # Add a small delay to mitigate hitting Overpass API rate limits
        time.sleep(1) 
        response = requests.post(OVERPASS_API_URL, data=query, timeout=30)
        response.raise_for_status()
        elements = response.json().get('elements', [])
        
        pois = []
        for el in elements:
            # Ensure element has coordinates (nodes have lat/lon, relations have center.lat/lon)
            if el.get('lat') and el.get('lon') or el.get('center', {}).get('lat') and el.get('center', {}).get('lon'):
                pois.append(_extract_poi_details(el, poi_type))
        
        return poi_type, pois
    except requests.RequestException as e:
        logging.error(f"Overpass API request failed for {poi_type}: {e}")
        return poi_type, {"error": f"Overpass API request failed: {e}"}
    except json.JSONDecodeError:
        logging.error(f"Failed to decode JSON from Overpass API for {poi_type}.")
        return poi_type, {"error": "Failed to decode API response"}
    except Exception as e:
        logging.error(f"An unexpected error occurred in _fetch_overpass_pois for {poi_type}: {e}", exc_info=True)
        return poi_type, {"error": f"An unexpected error occurred: {e}"}

def _load_pfas_data():
    """Loads PFAS site data from the local JSON file."""
    try:
        with open(PFAS_DATA_FILE, 'r') as f:
            return json.load(f)
    except FileNotFoundError:
        logging.warning(f"PFAS data file not found at {PFAS_DATA_FILE}")
        return {"error": f"PFAS data file not found at {PFAS_DATA_FILE}"}
    except json.JSONDecodeError:
        logging.error(f"Failed to parse PFAS JSON file at {PFAS_DATA_FILE}.")
        return {"error": "Failed to parse PFAS JSON file."}
    except Exception as e:
        logging.error(f"An unexpected error occurred loading PFAS data: {e}", exc_info=True)
        return {"error": f"An unexpected error occurred loading PFAS data: {e}"}

def _enrich_poi_with_google_places(poi, db_manager):
    """
    Attempts to enrich a POI's data using the Google Places API.
    Requires GOOGLE_PLACES_API_KEY in the database.
    """
    google_places_api_key = db_manager.get_key_value_by_name('GOOGLE_PLACES_API_KEY')
    if not google_places_api_key or google_places_api_key == "your_google_places_api_key_here":
        logging.info("GOOGLE_PLACES_API_KEY not configured. Skipping Google Places enrichment.")
        return poi # Return original POI if key is missing

    # Use a text search to find place_id, then details for full info
    # Or, if we have a name and address, use Find Place From Text
    
    # For simplicity, let's use Text Search if we have a name and coordinates
    search_query = f"{poi.get('name', '')} {poi.get('address', '')}".strip()
    if not search_query or search_query == "N/A":
        search_query = f"{poi.get('poi_type')} at {poi.get('latitude')},{poi.get('longitude')}"

    find_place_url = "https://maps.googleapis.com/maps/api/place/findplacefromtext/json"
    find_place_params = {
        "input": search_query,
        "inputtype": "textquery",
        "fields": "place_id",
        "key": google_places_api_key
    }
    
    if poi.get('latitude') and poi.get('longitude'):
        find_place_params["locationbias"] = f"circle:5000@{poi['latitude']},{poi['longitude']}" # Bias search to 5km radius

    place_id = None
    try:
        response = requests.get(find_place_url, params=find_place_params, timeout=5)
        response.raise_for_status()
        find_data = response.json()
        if find_data.get('candidates'):
            place_id = find_data['candidates'][0].get('place_id')
    except requests.RequestException as e:
        logging.warning(f"Google Places Find Place failed for '{search_query}': {e}")
    except Exception as e:
        logging.error(f"Error in Google Places Find Place: {e}", exc_info=True)

    if place_id:
        details_url = "https://maps.googleapis.com/maps/api/place/details/json"
        details_params = {
            "place_id": place_id,
            "fields": "name,formatted_address,international_phone_number,website,opening_hours,geometry/location",
            "key": google_places_api_key
        }
        try:
            response = requests.get(details_url, params=details_params, timeout=5)
            response.raise_for_status()
            details_data = response.json()
            if details_data.get('result'):
                google_result = details_data['result']
                poi['name'] = google_result.get('name', poi['name'])
                poi['address'] = google_result.get('formatted_address', poi['address'])
                poi['phone'] = google_result.get('international_phone_number', poi['phone'])
                poi['website'] = google_result.get('website', poi['website'])
                # Overwrite opening_hours if Google has it
                if google_result.get('opening_hours') and google_result['opening_hours'].get('weekday_text'):
                    poi['opening_hours'] = "; ".join(google_result['opening_hours']['weekday_text'])
                # Update coordinates if Google's are more precise
                if google_result.get('geometry') and google_result['geometry'].get('location'):
                    poi['latitude'] = google_result['geometry']['location'].get('lat', poi['latitude'])
                    poi['longitude'] = google_result['geometry']['location'].get('lng', poi['longitude'])
                logging.info(f"Enriched POI '{poi['name']}' with Google Places data.")
        except requests.RequestException as e:
            logging.warning(f"Google Places Details failed for place_id {place_id}: {e}")
        except Exception as e:
            logging.error(f"Error in Google Places Details: {e}", exc_info=True)
    
    return poi


def get_nearby_pois(lat, lon, db_manager, search_radius=50, radius_unit='km', types=None):
    """
    Finds nearby POIs for a given set of types around a lat/lon.
    Handles general POIs from Overpass and specialized data from local files.
    Optionally enriches data with Google Places API.
    Returns all found POIs within the radius.
    """
    if types is None:
        types = list(POI_QUERIES.keys()) + ["pfas_site"]

    # Convert radius to kilometers if unit is miles
    if radius_unit.lower() == 'miles':
        search_radius_km = search_radius * 1.60934
    else: # Default to km
        search_radius_km = search_radius

    all_pois = []
    overpass_types = [t for t in types if t in POI_QUERIES]

    # Handle special local data sources first (e.g., PFAS sites)
    if 'pfas_site' in types:
        pfas_data = _load_pfas_data()
        if isinstance(pfas_data, dict) and "error" in pfas_data:
            all_pois.append({"poi_type": "pfas_site", "error": pfas_data["error"]})
        else:
            for pfas_poi in pfas_data:
                pfas_lat, pfas_lon = pfas_poi.get('lat'), pfas_poi.get('lon')
                if pfas_lat is None or pfas_lon is None:
                    continue
                dist_km = distance.distance((lat, lon), (pfas_lat, pfas_lon)).km
                if dist_km <= search_radius_km:
                    poi_entry = {
                        "osm_id": pfas_poi.get("id", f"PFAS_{pfas_poi.get('name', '')}_{pfas_lat}_{pfas_lon}".replace('.', '').replace('-', '')), # Generate a pseudo-OSM ID
                        "poi_type": "pfas_site",
                        "name": pfas_poi.get("name", "N/A"),
                        "latitude": pfas_lat,
                        "longitude": pfas_lon,
                        "address": pfas_poi.get("address", "N/A"),
                        "phone": pfas_poi.get("phone", "N/A"),
                        "website": pfas_poi.get("website", "N/A"),
                        "distance_km": round(dist_km, 2),
                        "full_tags": pfas_poi # Store full raw data for potential Google enrichment
                    }
                    # Attempt Google enrichment
                    enriched_poi = _enrich_poi_with_google_places(poi_entry, db_manager)
                    all_pois.append(enriched_poi)

    # Handle standard Overpass queries concurrently
    if overpass_types:
        bbox = _calculate_bounding_box(lat, lon, search_radius_km)
        with ThreadPoolExecutor(max_workers=len(overpass_types)) as executor:
            future_to_poi = {executor.submit(_fetch_overpass_pois, poi_type, bbox): poi_type for poi_type in overpass_types}
            for future in concurrent.futures.as_completed(future_to_poi):
                poi_type = future_to_poi[future]
                try:
                    _, poi_list = future.result()
                    if isinstance(poi_list, dict) and "error" in poi_list:
                        all_pois.append({"poi_type": poi_type, "error": poi_list["error"]})
                        continue

                    for poi in poi_list:
                        # Calculate distance for each POI to ensure it's within the exact circular radius
                        poi_lat, poi_lon = poi.get('latitude'), poi.get('longitude')
                        if poi_lat is None or poi_lon is None:
                            continue
                        dist_km = distance.distance((lat, lon), (poi_lat, poi_lon)).km
                        if dist_km <= search_radius_km:
                            poi["distance_km"] = round(dist_km, 2)
                            # Attempt Google enrichment
                            enriched_poi = _enrich_poi_with_google_places(poi, db_manager)
                            all_pois.append(enriched_poi)
                except Exception as e:
                    logging.error(f"An unexpected error occurred processing Overpass POI type {poi_type}: {e}", exc_info=True)
                    all_pois.append({"poi_type": poi_type, "error": f"An unexpected error occurred: {e}"})

    # Group results by POI type for easier consumption by the frontend
    grouped_results = {}
    for poi in all_pois:
        poi_type = poi.get('poi_type', 'unknown')
        if poi_type not in grouped_results:
            grouped_results[poi_type] = []
        grouped_results[poi_type].append(poi)

    return grouped_results

