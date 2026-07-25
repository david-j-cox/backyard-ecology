#!/usr/bin/env python3
"""
birdweather_specific_pucs.py
Fetch BirdWeather detections for specific PUC devices (stations).

Fetches data for specified BirdWeather station IDs using day-by-day pulls.
Checks recent days against the API's totalCount to detect incomplete pulls
(< 95% completeness) and automatically repulls gaps.

Usage:
  python birdweather_specific_pucs.py
  python birdweather_specific_pucs.py --stations STATION_ID_1 STATION_ID_2
  python birdweather_specific_pucs.py --lookback 30   # check last 30 days
  python birdweather_specific_pucs.py --force-full     # repull everything
"""

import csv
import logging
import os
import sys
import time
import argparse
from datetime import date, datetime, timedelta
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

# If we have at least this fraction of the API's totalCount, the day is considered complete.
COMPLETENESS_RATIO = 0.95

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


def get_existing_daily_counts(csv_path: Path) -> dict:
    """Return {(station_id, date): row_count} from existing CSV."""
    if not csv_path.exists():
        return {}
    try:
        with open(csv_path, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            rows = list(reader)
    except Exception as e:
        logger.warning(f"Error reading existing file for daily counts: {e}")
        return {}

    counts = {}
    for row in rows:
        ts = row.get('timestamp')
        sid = row.get('station_id')
        if not ts or not sid:
            continue
        try:
            dt = datetime.fromisoformat(ts.replace('Z', '+00:00'))
            day = dt.date()
            key = (sid, day)
            counts[key] = counts.get(key, 0) + 1
        except Exception:
            continue
    return counts


def get_api_total_count_for_station(station_id: str, api_key: Optional[str], day: date) -> Optional[int]:
    """
    Ask the API for the totalCount of detections for a station on a single day.
    Uses first=1 to minimize data transfer -- we only need the count.
    """
    period = {"from": day.isoformat(), "to": day.isoformat()}
    variables = {
        "first": 1,
        "after": None,
        "period": period,
        "stationIds": [station_id],
    }
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    try:
        resp = requests.post(
            GRAPHQL_URL,
            json={"query": DETECTIONS_QUERY, "variables": variables},
            headers=headers,
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()
        if "errors" in data:
            return None
        return data["data"]["detections"].get("totalCount")
    except Exception:
        return None


def write_csv_atomic(rows: List[dict], fieldnames: List[str], csv_path: Path):
    """
    Write a CSV via a sibling temp file plus an atomic rename.

    Opening the real path with mode 'w' truncates it before a single row is
    written, so a process killed mid-write leaves a partial file -- and CI
    uploads whatever is on disk to the release even when the job fails.
    """
    # Trailing .tmp so the repo's existing *.tmp ignore rule keeps an orphan
    # (left by a hard kill, when the finally below cannot run) out of commits.
    tmp = csv_path.with_name(f".{csv_path.name}.{os.getpid()}.tmp")
    for stale in csv_path.parent.glob(f".{csv_path.name}.*.tmp"):
        try:
            stale.unlink()
            logger.info(f"  Cleaned up orphaned temp file: {stale.name}")
        except OSError:
            pass
    try:
        with open(tmp, 'w', newline='', encoding='utf-8') as f:
            w = csv.DictWriter(f, fieldnames=fieldnames)
            w.writeheader()
            w.writerows(rows)
        os.replace(tmp, csv_path)
    finally:
        if tmp.exists():
            tmp.unlink()


def replace_station_day(csv_path: Path, station_id: str, day: date, new_nodes: List[dict]):
    """
    Swap a station+date's rows for freshly fetched ones in a single rewrite.

    The old rows are only dropped once new_nodes is in hand, so a failed or
    interrupted fetch leaves existing data untouched rather than deleting it
    and then dying before the replacement arrives.
    """
    new_rows = [flatten(node) for node in new_nodes]

    if not csv_path.exists():
        fields = sorted({k for r in new_rows for k in r.keys()}) if new_rows else list(flatten({}).keys())
        write_csv_atomic(new_rows, fields, csv_path)
        logger.info(f"Wrote {len(new_rows)} records to {csv_path}")
        return

    try:
        with open(csv_path, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            rows = list(reader)
    except Exception as e:
        logger.warning(f"Error reading existing file: {e}. Skipping write to avoid data loss.")
        return

    kept = []
    removed = 0
    for row in rows:
        ts = row.get('timestamp')
        sid = row.get('station_id')
        if sid == station_id and ts:
            try:
                dt = datetime.fromisoformat(ts.replace('Z', '+00:00'))
                if dt.date() == day:
                    removed += 1
                    continue
            except Exception:
                pass
        kept.append(row)

    if removed > 0:
        logger.info(f"  Replacing {removed:,} incomplete rows for station {station_id} on {day}")

    # Drop any new row whose id already survives elsewhere in the file
    kept_ids = {row.get('id') for row in kept if row.get('id')}
    fresh = [r for r in new_rows if r.get('id') not in kept_ids]

    all_rows = kept + fresh
    fields = sorted({k for r in all_rows for k in r.keys()}) if all_rows else list(flatten({}).keys())
    all_rows.sort(key=lambda x: x.get('timestamp', ''))

    write_csv_atomic(all_rows, fields, csv_path)
    logger.info(f"Wrote {len(all_rows)} total records to {csv_path} (+{len(fresh)} new)")


def find_days_to_fetch_for_station(
    station_id: str, api_key: Optional[str], existing_counts: dict,
    start: date, end: date, lookback: int, force: bool
) -> List[date]:
    """
    Identify days that need fetching for a station.

    For each day in the range, compares the local row count against the API's
    totalCount. A day is flagged for (re)pull if:
      - missing entirely (no local data)
      - local count < COMPLETENESS_RATIO * API totalCount
      - force mode is on
    Days within the lookback window are always checked against the API.
    Older days with any local data are skipped.
    """
    days_to_fetch = []
    today = date.today()
    lookback_start = today - timedelta(days=lookback)

    day = start
    while day <= end:
        existing = existing_counts.get((station_id, day), 0)

        if force:
            days_to_fetch.append(day)
            day += timedelta(days=1)
            continue

        if existing == 0:
            days_to_fetch.append(day)
            day += timedelta(days=1)
            continue

        should_check = day >= lookback_start
        if not should_check:
            day += timedelta(days=1)
            continue

        api_total = get_api_total_count_for_station(station_id, api_key, day)
        if api_total is not None and api_total > 0:
            ratio = existing / api_total
            if ratio < COMPLETENESS_RATIO:
                logger.info(f"  station {station_id} {day}: incomplete -- {existing:,} local vs {api_total:,} API ({ratio:.0%})")
                days_to_fetch.append(day)
            else:
                logger.info(f"  station {station_id} {day}: OK -- {existing:,} local vs {api_total:,} API ({ratio:.0%})")
        elif api_total == 0:
            logger.info(f"  station {station_id} {day}: API reports 0 detections, skipping")
        else:
            logger.info(f"  station {station_id} {day}: API check failed, refetching to be safe")
            days_to_fetch.append(day)

        time.sleep(0.25)
        day += timedelta(days=1)

    return days_to_fetch


def fetch_one_day_for_station(
    station_id: str, api_key: Optional[str], day: date,
    page_size: int = 500, max_retries: int = 3
) -> Optional[List[dict]]:
    """Fetch all detections for one station on one day. Returns list of nodes or None on failure."""
    period = {"from": day.isoformat(), "to": day.isoformat()}

    for attempt in range(1, max_retries + 1):
        try:
            nodes = fetch_all_for_station(
                station_id=station_id,
                api_key=api_key,
                period=period,
                page_size=page_size,
            )
            return nodes
        except Exception as e:
            if attempt < max_retries:
                wait = 30 * attempt
                logger.warning(f"  Attempt {attempt}/{max_retries} failed for station {station_id} {day}: {e}")
                logger.info(f"  Waiting {wait}s before retry...")
                time.sleep(wait)
            else:
                logger.error(f"  FAILED after {max_retries} attempts for station {station_id} {day}: {e}")
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
    ap.add_argument(
        "--lookback", type=int, default=30,
        help="Number of recent days to check for incomplete data. Default: 30"
    )
    ap.add_argument(
        "--from", dest="from_date", default="2025-11-01",
        help="Start date (YYYY-MM-DD). Default: 2025-11-01"
    )
    ap.add_argument(
        "--to", dest="to_date", default=date.today().isoformat(),
        help="End date (YYYY-MM-DD). Default: today"
    )
    return ap.parse_args()


def fetch_sensor_readings_for_day(station_id, api_key, day, page_size):
    """Fetch all sensor readings for a station on a single day."""
    period = {"from": day.isoformat(), "to": day.isoformat()}
    sensor_readings = {}

    sensor_configs = [
        (ENVIRONMENT_READINGS_QUERY, "environmentReadings", "environment"),
        (LIGHT_READINGS_QUERY, "lightReadings", "light"),
        (ACCEL_READINGS_QUERY, "accelReadings", "accel"),
        (MAG_READINGS_QUERY, "magReadings", "mag"),
    ]

    for query, query_name, key in sensor_configs:
        try:
            readings = fetch_sensor_readings(
                station_id=station_id,
                query=query,
                query_name=query_name,
                api_key=api_key,
                period=period,
                page_size=page_size
            )
            if readings:
                sensor_readings[key] = readings
        except Exception as e:
            logger.debug(f"Could not fetch {key} readings for station {station_id} on {day}: {e}")

    return sensor_readings


def main():
    # Get script directory for logging and paths
    script_dir = Path(__file__).parent.resolve()

    # Set up logging to file and console
    log_file = setup_logging(script_dir)

    args = parse_args()

    # If output path is relative, make it relative to the data folder
    if Path(args.output).is_absolute():
        output_path = Path(args.output)
    else:
        data_dir = script_dir.parent / 'data'
        data_dir.mkdir(exist_ok=True)
        output_path = data_dir / args.output

    if not args.stations:
        logger.error("No station IDs provided. Please specify --stations or set DEFAULT_STATION_IDS in the script.")
        sys.exit(1)

    start = date.fromisoformat(args.from_date)
    end = date.fromisoformat(args.to_date)

    logger.info(f"PUC station fetch: {start} to {end}")
    logger.info(f"Lookback window: {args.lookback} days | Completeness threshold: {COMPLETENESS_RATIO:.0%} of API total")
    if args.force_full:
        logger.info("FORCE mode: repulling all days regardless of existing counts")
    logger.info(f"Output file: {output_path}")

    # Scan existing data to figure out what needs pulling
    existing_counts = get_existing_daily_counts(output_path)
    if existing_counts:
        n_stations = len(set(s for s, _ in existing_counts))
        n_days = len(existing_counts)
        logger.info(f"Found existing data: {n_stations} stations, {n_days} station-day records")
    else:
        logger.info("No existing data found, starting fresh")

    total_fetched = 0
    total_skipped = 0
    failed_days = []

    for station_input in args.stations:
        # Convert station name to numeric ID if needed
        station_id = STATION_NAME_TO_ID.get(station_input, station_input)

        # Get API key for this station
        api_key = STATION_API_KEYS.get(station_id) or STATION_API_KEYS.get(station_input)

        if not api_key:
            resolved_id = resolve_station_id(station_input, None)
            if resolved_id and resolved_id != station_input:
                station_id = resolved_id
                api_key = STATION_API_KEYS.get(station_id)

        if not api_key:
            logger.warning(f"No API key for station {station_id} -- will attempt unauthenticated requests")

        # Determine scan range for this station
        station_has_data = any(s == station_id for s, _ in existing_counts)
        if station_has_data and not args.force_full:
            station_dates = [d for s, d in existing_counts if s == station_id]
            station_start = max(start, min(station_dates))
        else:
            station_start = start

        days_to_fetch = find_days_to_fetch_for_station(
            station_id, api_key, existing_counts, station_start, end,
            args.lookback, args.force_full
        )

        if not days_to_fetch:
            logger.info(f"\n=== Station {station_id}: up to date, nothing to fetch ===")
            total_skipped += 1
            continue

        logger.info(f"\n=== Station {station_id}: {len(days_to_fetch)} days to fetch ===")

        for day in days_to_fetch:
            existing = existing_counts.get((station_id, day), 0)
            status = f"(replacing: {existing} rows)" if existing > 0 else "(missing)"
            logger.info(f"\n  Station {station_id} {day} {status}")

            nodes = fetch_one_day_for_station(
                station_id, api_key, day, page_size=args.page_size
            )

            if nodes is None:
                # Fetch failed. Existing rows stay put -- the next run re-checks
                # this day against the API and repulls if still short.
                failed_days.append((station_id, day))
                continue

            if not nodes:
                # find_days_to_fetch_for_station already skips days the API
                # reports as empty, so an empty result here means the API
                # disagreed with itself. Keep what we have.
                logger.info(f"  No detections for station {station_id} on {day}")
                continue

            # Fetch and merge sensor readings for this day
            sensor_readings = fetch_sensor_readings_for_day(
                station_id, api_key, day, args.page_size
            )
            if sensor_readings:
                nodes = merge_sensor_data_with_detections(nodes, sensor_readings)

            logger.info(f"  Fetched {len(nodes):,} detections for station {station_id} on {day}")
            replace_station_day(output_path, station_id, day, nodes)
            write_to_duckdb(nodes)
            total_fetched += len(nodes)

            time.sleep(1)

    # Summary
    logger.info("\n" + "=" * 50)
    logger.info(f"Complete.")
    logger.info(f"  Fetched: {total_fetched:,} detections")
    logger.info(f"  Stations skipped (up to date): {total_skipped}")
    if failed_days:
        logger.info(f"  FAILED ({len(failed_days)} days):")
        for sid, day in failed_days:
            logger.info(f"    station {sid} {day}")
    else:
        logger.info(f"  No failures.")


def write_to_duckdb(nodes):
    """
    INSERT OR IGNORE new detections into study_site_puc_data.
    Handles dynamic sensor columns via ALTER TABLE ADD COLUMN IF NOT EXISTS.
    """
    if not nodes:
        return

    try:
        import pandas as pd
        from db import get_connection, init_schema

        rows = [flatten(node) for node in nodes]
        df = pd.DataFrame(rows).astype(str)
        df = df.where(df != "nan", None)
        df = df.where(df != "None", None)

        with get_connection() as con:
            init_schema(con)

            # Add any dynamic columns that aren't in the base schema
            existing_cols = {
                row[0]
                for row in con.execute(
                    "SELECT column_name FROM information_schema.columns "
                    "WHERE table_name = 'study_site_puc_data'"
                ).fetchall()
            }
            for col in df.columns:
                if col not in existing_cols:
                    con.execute(
                        f'ALTER TABLE study_site_puc_data ADD COLUMN IF NOT EXISTS "{col}" VARCHAR'
                    )

            con.execute("INSERT OR IGNORE INTO study_site_puc_data SELECT * FROM df")
            count = con.execute("SELECT COUNT(*) FROM study_site_puc_data").fetchone()[0]
            logger.info(f"[DuckDB] study_site_puc_data: {count:,} total rows")

    except Exception as e:
        logger.warning(f"[DuckDB WARNING] Failed to write PUC data to DuckDB: {e}")


if __name__ == "__main__":
    main()
