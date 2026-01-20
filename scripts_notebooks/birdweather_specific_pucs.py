#!/usr/bin/env python3
"""
birdweather_specific_pucs.py
Fetch BirdWeather detections for specific PYC devices (stations).

This script fetches data for specified BirdWeather station IDs. On first run,
it downloads all historical data. On subsequent runs, it only fetches data
since the last timestamp in the saved file.

Usage:
  python birdweather_specific_pucs.py
  # Specify station IDs
  python birdweather_specific_pucs.py --stations STATION_ID_1 STATION_ID_2
"""

import csv
import logging
import os
import sys
import time
import argparse
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Optional

import requests
from dotenv import load_dotenv

# Load environment variables
load_dotenv()


def setup_logging(script_dir: Path) -> Path:
    """
    Set up logging to both file and console.
    
    Args:
        script_dir: Directory where the script is located
        
    Returns:
        Path to the log file
    """
    # Create logs directory if it doesn't exist
    logs_dir = script_dir.parent / 'logs'
    logs_dir.mkdir(exist_ok=True)
    
    # Create log file with timestamp
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    log_file = logs_dir / f'birdweather_specific_pucs_{timestamp}.log'
    
    # Configure logging
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S',
        handlers=[
            logging.FileHandler(log_file),
            logging.StreamHandler(sys.stdout)
        ]
    )
    
    logger = logging.getLogger(__name__)
    logger.info(f"Logging initialized. Log file: {log_file}")
    
    return log_file


logger = logging.getLogger(__name__)

GRAPHQL_URL = "https://app.birdweather.com/graphql"

# Station ID to API key mapping
# Each station has its own API key from the .env file
# Note: Station IDs are numeric (from the URL: app.birdweather.com/stations/21974)
STATION_API_KEYS = {
    "21974": os.getenv("JAX_BIRDWX_API_KEY"),  # PUC-21974-COX
    "18618": os.getenv("ESSEX_BIRDWX_API_KEY"),  # PUC-18618
}

# Map station names to numeric IDs for convenience
STATION_NAME_TO_ID = {
    "PUC-21974-COX": "21974",
    "PUC-18618": "18618",
}

DEFAULT_STATION_IDS: List[str] = [
    "21974",  # PUC-21974-COX
    "18618"   # PUC-18618
]

# GraphQL query for detections by station IDs with cursor pagination
# Includes available sensor and station data
# Note: stationIds might need to be numeric IDs, not the PUC-XXX format
DETECTIONS_QUERY = """
query detections(
  $first: Int,
  $after: String,
  $period: InputDuration,
  $stationIds: [ID!]
) {
  detections(
    first: $first,
    after: $after,
    period: $period,
    stationIds: $stationIds
  ) {
    totalCount
    pageInfo { hasNextPage endCursor }
    nodes {
      id
      timestamp
      certainty
      confidence
      probability
      score
      coords { lat lon }
      species { id commonName scientificName ebirdCode }
      station { 
        id 
        name
      }
      soundscape { id url startTime endTime }
    }
  }
}
"""

# Query for environment readings (temperature, humidity, pressure, etc.)
# These must be accessed through the station query
ENVIRONMENT_READINGS_QUERY = """
query environmentReadings(
  $first: Int,
  $after: String,
  $period: InputDuration,
  $stationId: ID!
) {
  station(id: $stationId) {
    id
    name
    environmentReadings(
      first: $first,
      after: $after,
      period: $period
    ) {
      totalCount
      pageInfo { hasNextPage endCursor }
      nodes {
        timestamp
        temperature
        humidity
        pressure
        light
        motion
      }
    }
  }
}
"""

# Query for light readings
# These must be accessed through the station query
LIGHT_READINGS_QUERY = """
query lightReadings(
  $first: Int,
  $after: String,
  $period: InputDuration,
  $stationId: ID!
) {
  station(id: $stationId) {
    id
    name
    lightReadings(
      first: $first,
      after: $after,
      period: $period
    ) {
      totalCount
      pageInfo { hasNextPage endCursor }
      nodes {
        timestamp
        value
      }
    }
  }
}
"""

# Query for accelerometer readings
# These must be accessed through the station query
ACCEL_READINGS_QUERY = """
query accelReadings(
  $first: Int,
  $after: String,
  $period: InputDuration,
  $stationId: ID!
) {
  station(id: $stationId) {
    id
    name
    accelReadings(
      first: $first,
      after: $after,
      period: $period
    ) {
      totalCount
      pageInfo { hasNextPage endCursor }
      nodes {
        timestamp
        x
        y
        z
      }
    }
  }
}
"""

# Query for magnetometer readings
# These must be accessed through the station query
MAG_READINGS_QUERY = """
query magReadings(
  $first: Int,
  $after: String,
  $period: InputDuration,
  $stationId: ID!
) {
  station(id: $stationId) {
    id
    name
    magReadings(
      first: $first,
      after: $after,
      period: $period
    ) {
      totalCount
      pageInfo { hasNextPage endCursor }
      nodes {
        timestamp
        x
        y
        z
      }
    }
  }
}
"""

# Alternative: Query stations first to get their IDs
STATIONS_QUERY = """
query stations($names: [String!]) {
  stations(names: $names) {
    nodes {
      id
      name
    }
  }
}
"""

def resolve_station_id(station_name_or_id: str, api_key: Optional[str] = None) -> Optional[str]:
    """
    Try to resolve a station name/ID to the actual station ID used by the API.
    Returns the station ID if found, or None.
    """
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    
    variables = {"names": [station_name_or_id]}
    
    try:
        resp = requests.post(
            GRAPHQL_URL,
            json={"query": STATIONS_QUERY, "variables": variables},
            headers=headers,
            timeout=60,
        )
        resp.raise_for_status()
        data = resp.json()
        
        if "errors" in data:
            logger.debug(f"Error querying stations: {data['errors']}")
            return None
        
        stations = data.get("data", {}).get("stations", {}).get("nodes", [])
        if stations:
            station_id = stations[0].get("id")
            logger.info(f"Resolved station '{station_name_or_id}' to ID: {station_id}")
            return station_id
        else:
            logger.warning(f"Could not resolve station '{station_name_or_id}' - will try using it as-is")
            return station_name_or_id
    except Exception as e:
        logger.warning(f"Error resolving station ID for '{station_name_or_id}': {e}. Will try using as-is.")
        return station_name_or_id


def get_last_timestamp(csv_path: Path) -> Optional[str]:
    """
    Read the last timestamp from the CSV file.
    
    Args:
        csv_path: Path to the CSV file
        
    Returns:
        Last timestamp as ISO string, or None if file doesn't exist or is empty
    """
    if not csv_path.exists():
        logger.info(f"Output file {csv_path} does not exist. Will fetch all historical data.")
        return None
    
    try:
        with open(csv_path, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            rows = list(reader)
            
        if not rows:
            logger.info("Output file is empty. Will fetch all historical data.")
            return None
        
        # Find the latest timestamp
        timestamps = [row.get('timestamp') for row in rows if row.get('timestamp')]
        if not timestamps:
            logger.warning("No timestamps found in existing file. Will fetch all historical data.")
            return None
        
        # Sort and get the latest
        timestamps.sort()
        last_timestamp = timestamps[-1]
        logger.info(f"Found last timestamp in existing file: {last_timestamp}")
        return last_timestamp
        
    except Exception as e:
        logger.error(f"Error reading existing file: {e}. Will fetch all historical data.")
        return None


def fetch_all_for_station(
    station_id: str,
    api_key: Optional[str] = None,
    period: Optional[dict] = None,
    page_size: int = 500,
    pause: float = 0.25,
    max_retries: int = 3
) -> List[dict]:
    """
    Pulls all detections for a single station ID with optional period filter.
    Returns a list of detection nodes (dicts).
    
    Args:
        station_id: Station ID to fetch
        api_key: API key for this specific station
        period: Optional dict with 'from' and 'to' ISO date strings
        page_size: Number of records per page
        pause: Seconds to pause between requests
        max_retries: Maximum number of retry attempts
        
    Returns:
        List of detection nodes
    """
    if not station_id:
        raise ValueError("Station ID must be provided")
    
    all_nodes = []
    after = None
    
    logger.info(f"Fetching detections for station: {station_id}")
    if period:
        logger.info(f"Date range: {period.get('from')} to {period.get('to')}")
    if api_key:
        logger.info(f"Using API key for station {station_id}")
    else:
        logger.warning(f"No API key provided for station {station_id} - attempting unauthenticated request")
    
    while True:
        variables = {
            "first": page_size,
            "after": after,
            "period": period,
            "stationIds": [station_id],  # Single station in a list
        }
        
        # Remove None values
        variables = {k: v for k, v in variables.items() if v is not None}
        
        # Log the variables being sent (without exposing API key)
        logger.debug(f"Query variables: { {k: v if k != 'stationIds' else f'[{len(v)} station(s)]' for k, v in variables.items()} }")
        
        # Prepare headers with station-specific API key
        headers = {"Content-Type": "application/json"}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
            logger.debug("Authorization header set")
        
        # Simple retry loop
        for attempt in range(1, max_retries + 1):
            try:
                resp = requests.post(
                    GRAPHQL_URL,
                    json={"query": DETECTIONS_QUERY, "variables": variables},
                    headers=headers,
                    timeout=60,
                )
                resp.raise_for_status()
                data = resp.json()
                
                if "errors" in data:
                    error_msg = data['errors']
                    # Check if it's an authentication error
                    if any("auth" in str(err).lower() or "unauthorized" in str(err).lower() 
                           for err in error_msg):
                        logger.error(f"Authentication error for station {station_id}. Check API key in .env file.")
                    raise RuntimeError(f"GraphQL errors for station {station_id}: {error_msg}")
                
                # Log response info for debugging
                if "data" in data and "detections" in data["data"]:
                    total_count = data["data"]["detections"].get("totalCount", 0)
                    logger.debug(f"API returned totalCount: {total_count} for station {station_id}")
                
                break
            except Exception as e:
                if attempt == max_retries:
                    raise
                logger.warning(f"Request failed for station {station_id} (attempt {attempt}/{max_retries}): {e}")
                time.sleep(pause * attempt)  # Backoff and retry
        
        payload = data["data"]["detections"]
        total_count = payload.get("totalCount", 0)
        nodes = payload.get("nodes") or []
        all_nodes.extend(nodes)
        
        logger.info(f"Fetched {len(nodes)} records for {station_id} (API reports totalCount: {total_count}, accumulated: {len(all_nodes)})")
        
        page_info = payload["pageInfo"]
        if not page_info["hasNextPage"]:
            if total_count > 0 and len(all_nodes) == 0:
                logger.warning(f"API reports {total_count} total records but returned 0 nodes. This might indicate a query issue.")
            break
        after = page_info["endCursor"]
        time.sleep(pause)
    
    return all_nodes


def fetch_sensor_readings(
    station_id: str,
    query: str,
    query_name: str,
    api_key: Optional[str] = None,
    period: Optional[dict] = None,
    page_size: int = 500,
    pause: float = 0.25,
    max_retries: int = 3
) -> List[dict]:
    """
    Generic function to fetch sensor readings (environment, light, accel, mag).
    
    Args:
        station_id: Station ID to fetch
        query: GraphQL query string
        query_name: Name of the query for logging
        api_key: API key for this specific station
        period: Optional dict with 'from' and 'to' ISO date strings
        page_size: Number of records per page
        pause: Seconds to pause between requests
        max_retries: Maximum number of retry attempts
        
    Returns:
        List of reading nodes
    """
    all_readings = []
    after = None
    
    logger.debug(f"Fetching {query_name} for station: {station_id}")
    
    while True:
        variables = {
            "first": page_size,
            "after": after,
            "period": period,
            "stationId": station_id,
        }
        
        # Remove None values
        variables = {k: v for k, v in variables.items() if v is not None}
        
        # Prepare headers with station-specific API key
        headers = {"Content-Type": "application/json"}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        
        # Simple retry loop
        for attempt in range(1, max_retries + 1):
            try:
                resp = requests.post(
                    GRAPHQL_URL,
                    json={"query": query, "variables": variables},
                    headers=headers,
                    timeout=60,
                )
                resp.raise_for_status()
                data = resp.json()
                
                if "errors" in data:
                    error_msg = data['errors']
                    # Log the actual error
                    logger.info(f"{query_name} query returned errors for station {station_id}: {error_msg}")
                    # Don't fail if sensor readings aren't available
                    if any("undefinedField" in str(err) for err in error_msg):
                        logger.info(f"{query_name} field not available in API schema for station {station_id}")
                        return []
                    raise RuntimeError(f"GraphQL errors for {query_name} station {station_id}: {error_msg}")
                break
            except Exception as e:
                if attempt == max_retries:
                    logger.warning(f"Error fetching {query_name} for station {station_id}: {e}")
                    return []
                time.sleep(pause * attempt)
        
        # Extract readings from response - these are nested under station
        data_root = data.get("data", {})
        if not data_root:
            logger.debug(f"No data in response for {query_name} station {station_id}")
            # Log the actual response structure for debugging
            logger.debug(f"Response structure: {list(data.keys())}")
            break
        
        # Get station data - the query returns data.station
        station_data = data_root.get("station")
        
        if not station_data:
            # Log what keys are actually available
            logger.debug(f"Available keys in data: {list(data_root.keys())}")
            logger.info(f"No station data found in response for station {station_id}")
            break
        
        # Get readings from station - e.g., data.station.environmentReadings
        readings_data = station_data.get(query_name, {})
        
        if not readings_data:
            # Log what keys are actually available in station
            logger.debug(f"Available keys in station: {list(station_data.keys())}")
            logger.info(f"No {query_name} found in station data for station {station_id}")
            break
        
        logger.debug(f"Found {query_name} in station response data")
        
        nodes = readings_data.get("nodes") or []
        total_count = readings_data.get("totalCount", 0)
        all_readings.extend(nodes)
        
        logger.debug(f"Fetched {len(nodes)} {query_name} records (API reports totalCount: {total_count}, accumulated: {len(all_readings)})")
        
        page_info = readings_data.get("pageInfo", {})
        if not page_info.get("hasNextPage"):
            if total_count > 0 and len(all_readings) == 0:
                logger.warning(f"API reports {total_count} total {query_name} but returned 0 nodes for station {station_id}")
            break
        after = page_info.get("endCursor")
        time.sleep(pause)
    
    logger.info(f"Retrieved {len(all_readings)} total {query_name} for station {station_id}")
    return all_readings


def merge_sensor_data_with_detections(detections: List[dict], sensor_readings: dict) -> List[dict]:
    """
    Merge sensor readings with detections based on timestamp proximity.
    Uses nearest timestamp matching within a 5-minute window.
    
    Args:
        detections: List of detection nodes
        sensor_readings: Dict with keys like 'environment', 'light', 'accel', 'mag'
        
    Returns:
        List of detections with merged sensor data
    """
    
    if not sensor_readings:
        logger.debug("No sensor readings to merge")
        return detections
    
    # Parse timestamps and create sorted lists for each sensor type
    sensor_timestamps = {}
    for sensor_type, readings in sensor_readings.items():
        sensor_timestamps[sensor_type] = []
        for reading in readings:
            ts_str = reading.get("timestamp")
            if ts_str:
                try:
                    # Parse timestamp (handle various formats)
                    if 'T' in ts_str:
                        if ts_str.endswith('Z'):
                            ts = datetime.fromisoformat(ts_str.replace('Z', '+00:00'))
                        else:
                            ts = datetime.fromisoformat(ts_str)
                    else:
                        ts = datetime.fromisoformat(ts_str)
                    sensor_timestamps[sensor_type].append((ts, reading))
                except Exception as e:
                    logger.debug(f"Could not parse timestamp {ts_str} for {sensor_type}: {e}")
                    continue
        # Sort by timestamp
        sensor_timestamps[sensor_type].sort(key=lambda x: x[0])
        logger.debug(f"Prepared {len(sensor_timestamps[sensor_type])} {sensor_type} readings for merging")
    
    # Merge sensor data with detections using nearest timestamp matching
    merged = []
    matched_count = 0
    max_time_diff = timedelta(minutes=5)  # 5-minute window for matching
    
    for detection in detections:
        detection_ts_str = detection.get("timestamp")
        if not detection_ts_str:
            merged.append(detection)
            continue
        
        try:
            # Parse detection timestamp
            if detection_ts_str.endswith('Z'):
                detection_ts = datetime.fromisoformat(detection_ts_str.replace('Z', '+00:00'))
            else:
                detection_ts = datetime.fromisoformat(detection_ts_str)
        except Exception as e:
            logger.debug(f"Could not parse detection timestamp {detection_ts_str}: {e}")
            merged.append(detection)
            continue
        
        # Find nearest sensor readings for each sensor type
        for sensor_type, timestamped_readings in sensor_timestamps.items():
            if not timestamped_readings:
                continue
            
            # Binary search for nearest timestamp
            best_match = None
            best_diff = None
            
            for sensor_ts, reading in timestamped_readings:
                diff = abs((detection_ts - sensor_ts).total_seconds())
                if diff <= max_time_diff.total_seconds():
                    if best_diff is None or diff < best_diff:
                        best_diff = diff
                        best_match = reading
            
            if best_match:
                detection[f"_{sensor_type}"] = best_match
                matched_count += 1
        
        merged.append(detection)
    
    logger.info(f"Merged sensor data: {matched_count} sensor readings matched to {len(detections)} detections")
    return merged


def flatten(node):
    """Flatten nested detection into a CSV-friendly dict."""
    sp = node.get("species") or {}
    st = node.get("station") or {}
    coords = node.get("coords") or {}
    sc = node.get("soundscape") or {}
    
    result = {
        "id": node.get("id"),
        "timestamp": node.get("timestamp"),
        "certainty": node.get("certainty"),
        "confidence": node.get("confidence"),
        "probability": node.get("probability"),
        "score": node.get("score"),
        "lat": coords.get("lat"),
        "lon": coords.get("lon"),
        "species_common": sp.get("commonName"),
        "species_scientific": sp.get("scientificName"),
        "species_ebird": sp.get("ebirdCode"),
        "station_id": st.get("id"),
        "station_name": st.get("name"),
        "sound_url": sc.get("url"),
        "sound_start": sc.get("startTime"),
        "sound_end": sc.get("endTime"),
    }
    
    # Extract merged sensor data if available (from _environment, _light, _accel, _mag keys)
    env_data = node.get("_environment") or {}
    if env_data:
        result.update({
            "temperature": env_data.get("temperature"),
            "humidity": env_data.get("humidity"),
            "pressure": env_data.get("pressure"),
            "light": env_data.get("light"),
            "motion": env_data.get("motion"),
        })
    
    light_data = node.get("_light") or {}
    if light_data:
        result["light_reading"] = light_data.get("value")
        if "light_reading_timestamp" not in result:
            result["light_reading_timestamp"] = light_data.get("timestamp")
    
    accel_data = node.get("_accel") or {}
    if accel_data:
        result.update({
            "accel_timestamp": accel_data.get("timestamp"),
            "accel_x": accel_data.get("x"),
            "accel_y": accel_data.get("y"),
            "accel_z": accel_data.get("z"),
        })
    
    mag_data = node.get("_mag") or {}
    if mag_data:
        result.update({
            "mag_timestamp": mag_data.get("timestamp"),
            "mag_x": mag_data.get("x"),
            "mag_y": mag_data.get("y"),
            "mag_z": mag_data.get("z"),
        })
    
    return result


def append_to_csv(new_items: List[dict], csv_path: Path):
    """
    Append new items to CSV file, or create it if it doesn't exist.
    Removes duplicates based on detection ID.
    
    Args:
        new_items: List of detection nodes to add
        csv_path: Path to the CSV file
    """
    if not new_items:
        logger.info("No new items to write.")
        return
    
    # Flatten the new items
    new_rows = [flatten(node) for node in new_items]
    
    # Get existing data if file exists
    existing_ids = set()
    existing_rows = []
    
    if csv_path.exists():
        try:
            with open(csv_path, 'r', encoding='utf-8') as f:
                reader = csv.DictReader(f)
                existing_rows = list(reader)
                existing_ids = {row.get('id') for row in existing_rows if row.get('id')}
            logger.info(f"Found {len(existing_rows)} existing records")
        except Exception as e:
            logger.warning(f"Error reading existing file: {e}. Will create new file.")
            existing_rows = []
    
    # Filter out duplicates
    new_rows_filtered = [row for row in new_rows if row.get('id') not in existing_ids]
    
    if not new_rows_filtered:
        logger.info("All new records already exist in file. No updates needed.")
        return
    
    logger.info(f"Adding {len(new_rows_filtered)} new records (skipped {len(new_rows) - len(new_rows_filtered)} duplicates)")
    
    # Combine existing and new rows
    all_rows = existing_rows + new_rows_filtered
    
    # Build header from all keys
    fields = sorted({k for r in all_rows for k in r.keys()}) if all_rows else list(flatten({}).keys())
    
    # Sort by timestamp to keep chronological order
    all_rows.sort(key=lambda x: x.get('timestamp', ''))
    
    # Write to file
    with open(csv_path, 'w', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(all_rows)
    
    logger.info(f"Wrote {len(all_rows)} total records to {csv_path}")


def parse_args():
    ap = argparse.ArgumentParser(
        description="Download BirdWeather detections for specific PUC stations."
    )
    ap.add_argument(
        "--stations",
        nargs='+',
        default=DEFAULT_STATION_IDS,
        help="Station IDs to fetch (space-separated). Default: from DEFAULT_STATION_IDS in script."
    )
    ap.add_argument(
        "--output",
        default="study_site_puc_data.csv",
        help="Output CSV file path (relative to data/ folder). Default: study_site_puc_data.csv"
    )
    ap.add_argument(
        "--page-size",
        type=int,
        default=500,
        help="Detections per page. Default: 500"
    )
    ap.add_argument(
        "--force-full",
        action='store_true',
        help="Force full historical fetch, ignoring existing data"
    )
    return ap.parse_args()


def main():
    # Get script directory for logging and paths
    script_dir = Path(__file__).parent.resolve()
    
    # Set up logging to file and console
    log_file = setup_logging(script_dir)
    
    args = parse_args()
    
    # If output path is relative, make it relative to the data folder
    # If it's absolute, use it as-is
    if Path(args.output).is_absolute():
        output_path = Path(args.output)
    else:
        # Get the data folder (one level up from scripts_notebooks)
        data_dir = script_dir.parent / 'data'
        data_dir.mkdir(exist_ok=True)  # Ensure data directory exists
        output_path = data_dir / args.output
    
    if not args.stations:
        logger.error("No station IDs provided. Please specify --stations or set DEFAULT_STATION_IDS in the script.")
        sys.exit(1)
    
    # Check API key availability for each station
    missing_keys = []
    for station_id in args.stations:
        api_key = STATION_API_KEYS.get(station_id)
        if api_key:
            logger.debug(f"API key found for station {station_id}")
        else:
            logger.warning(f"No API key found for station {station_id} in STATION_API_KEYS mapping")
            missing_keys.append(station_id)
    
    if missing_keys:
        logger.warning(f"Stations without API keys: {missing_keys}. Will attempt unauthenticated requests.")
    
    logger.info(f"Starting fetch for {len(args.stations)} station(s)")
    logger.info(f"Output file: {output_path}")
    
    # Determine date range
    # Default start date: November 1, 2025
    DEFAULT_START_DATE = "2025-11-01T00:00:00Z"
    
    period = None
    if not args.force_full:
        last_timestamp = get_last_timestamp(output_path)
        if last_timestamp:
            # Parse timestamp and add 1 second to avoid duplicates
            try:
                dt = datetime.fromisoformat(last_timestamp.replace('Z', '+00:00'))
                # Use the timestamp as the 'from' date
                period = {
                    "from": last_timestamp,
                    "to": datetime.now().isoformat() + "Z"
                }
                logger.info(f"Fetching data since last timestamp: {last_timestamp}")
            except Exception as e:
                logger.warning(f"Could not parse last timestamp: {e}. Using default date range.")
                # Fall back to default date range
                period = {
                    "from": DEFAULT_START_DATE,
                    "to": datetime.now().isoformat() + "Z"
                }
        else:
            # No existing data - use default date range (Nov 1, 2025 to today)
            period = {
                "from": DEFAULT_START_DATE,
                "to": datetime.now().isoformat() + "Z"
            }
            logger.info(f"No existing data found. Fetching data from {DEFAULT_START_DATE} to today.")
    else:
        # Force full fetch - use default date range
        period = {
            "from": DEFAULT_START_DATE,
            "to": datetime.now().isoformat() + "Z"
        }
        logger.info(f"Force full fetch requested. Fetching data from {DEFAULT_START_DATE} to today.")
    
    # Fetch data for each station individually with its corresponding API key
    all_nodes = []
    try:
        for station_input in args.stations:
            # Convert station name to numeric ID if needed
            station_id = STATION_NAME_TO_ID.get(station_input, station_input)
            
            # Get API key for this station (try both name and ID)
            api_key = STATION_API_KEYS.get(station_id) or STATION_API_KEYS.get(station_input)
            
            if not api_key:
                # Try to resolve the station ID (in case we have a name instead of ID)
                resolved_id = resolve_station_id(station_input, None)
                if resolved_id and resolved_id != station_input:
                    station_id = resolved_id
                    api_key = STATION_API_KEYS.get(station_id)
            
            logger.info(f"Using station ID: {station_id} for input: {station_input}")
            
            try:
                # Fetch detections
                nodes = fetch_all_for_station(
                    station_id=station_id,
                    api_key=api_key,
                    period=period,
                    page_size=args.page_size
                )
                logger.info(f"Retrieved {len(nodes)} detection records for station {station_input} (ID: {station_id})")
                
                # Fetch sensor readings
                sensor_readings = {}
                logger.info(f"Fetching sensor readings for station {station_id}...")
                
                # Fetch environment readings
                try:
                    logger.info(f"Attempting to fetch environment readings for station {station_id}...")
                    env_readings = fetch_sensor_readings(
                        station_id=station_id,
                        query=ENVIRONMENT_READINGS_QUERY,
                        query_name="environmentReadings",
                        api_key=api_key,
                        period=period,
                        page_size=args.page_size
                    )
                    if env_readings:
                        sensor_readings["environment"] = env_readings
                        logger.info(f"Successfully retrieved {len(env_readings)} environment readings")
                    else:
                        logger.info(f"No environment readings returned for station {station_id}")
                except Exception as e:
                    logger.warning(f"Could not fetch environment readings for station {station_id}: {e}", exc_info=True)
                
                # Fetch light readings
                try:
                    logger.info(f"Attempting to fetch light readings for station {station_id}...")
                    light_readings = fetch_sensor_readings(
                        station_id=station_id,
                        query=LIGHT_READINGS_QUERY,
                        query_name="lightReadings",
                        api_key=api_key,
                        period=period,
                        page_size=args.page_size
                    )
                    if light_readings:
                        sensor_readings["light"] = light_readings
                        logger.info(f"Successfully retrieved {len(light_readings)} light readings")
                    else:
                        logger.info(f"No light readings returned for station {station_id}")
                except Exception as e:
                    logger.warning(f"Could not fetch light readings for station {station_id}: {e}", exc_info=True)
                
                # Fetch accelerometer readings
                try:
                    logger.info(f"Attempting to fetch accelerometer readings for station {station_id}...")
                    accel_readings = fetch_sensor_readings(
                        station_id=station_id,
                        query=ACCEL_READINGS_QUERY,
                        query_name="accelReadings",
                        api_key=api_key,
                        period=period,
                        page_size=args.page_size
                    )
                    if accel_readings:
                        sensor_readings["accel"] = accel_readings
                        logger.info(f"Successfully retrieved {len(accel_readings)} accelerometer readings")
                    else:
                        logger.info(f"No accelerometer readings returned for station {station_id}")
                except Exception as e:
                    logger.warning(f"Could not fetch accelerometer readings for station {station_id}: {e}", exc_info=True)
                
                # Fetch magnetometer readings
                try:
                    logger.info(f"Attempting to fetch magnetometer readings for station {station_id}...")
                    mag_readings = fetch_sensor_readings(
                        station_id=station_id,
                        query=MAG_READINGS_QUERY,
                        query_name="magReadings",
                        api_key=api_key,
                        period=period,
                        page_size=args.page_size
                    )
                    if mag_readings:
                        sensor_readings["mag"] = mag_readings
                        logger.info(f"Successfully retrieved {len(mag_readings)} magnetometer readings")
                    else:
                        logger.info(f"No magnetometer readings returned for station {station_id}")
                except Exception as e:
                    logger.warning(f"Could not fetch magnetometer readings for station {station_id}: {e}", exc_info=True)
                
                # Log sensor reading summary
                total_sensor_readings = sum(len(readings) for readings in sensor_readings.values())
                if total_sensor_readings > 0:
                    logger.info(f"Sensor reading summary for station {station_id}:")
                    for sensor_type, readings in sensor_readings.items():
                        logger.info(f"  - {sensor_type}: {len(readings)} readings")
                else:
                    logger.warning(f"No sensor readings retrieved for station {station_id}")
                
                # Merge sensor data with detections
                if sensor_readings:
                    nodes = merge_sensor_data_with_detections(nodes, sensor_readings)
                    logger.info(f"Merged sensor data with detections for station {station_id}")
                else:
                    logger.warning(f"No sensor readings to merge for station {station_id}")
                
                all_nodes.extend(nodes)
            except Exception as e:
                logger.error(f"Error fetching data for station {station_input} (ID: {station_id}): {e}")
                # Continue with other stations even if one fails
                continue
        
        logger.info(f"Retrieved {len(all_nodes)} total records from all stations")
        
        if not all_nodes:
            logger.warning("No records retrieved from any station.")
            return
        
        # Append to CSV
        append_to_csv(all_nodes, output_path)
        
        logger.info("Data fetch completed successfully")
        
    except Exception as e:
        logger.error(f"Error fetching data: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
