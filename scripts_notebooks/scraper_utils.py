#!/usr/bin/env python3
"""
BirdCast Scraper Utilities
Common functionality shared across all BirdCast scraper classes
"""

import requests
from bs4 import BeautifulSoup
import json
import csv
import os
import pandas as pd
from datetime import datetime, timezone
import re
import time
import logging
from dateutil import parser as date_parser
import pytz

# Base paths for the project (relative to repo root)
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(BASE_DIR, "data")
LOGS_DIR = os.path.join(BASE_DIR, "logs")
os.makedirs(LOGS_DIR, exist_ok=True)

def setup_logging(log_filename):
    """
    Set up logging configuration for a scraper

    Args:
        log_filename: Name of the log file (e.g., 'atlantic_flyway_scraper.log')

    Returns:
        Configured logger
    """
    log_path = os.path.join(LOGS_DIR, log_filename)

    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s',
        handlers=[
            logging.FileHandler(log_path),
            logging.StreamHandler()
        ]
    )

    return logging.getLogger(__name__)

def create_session():
    """
    Create a requests session with appropriate headers

    Returns:
        Configured requests.Session object
    """
    session = requests.Session()
    session.headers.update({
        'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
    })
    return session

def parse_datetime_string(datetime_str):
    """
    Parse datetime string from BirdCast into ISO format timestamp

    Args:
        datetime_str: Raw datetime string from BirdCast

    Returns:
        ISO formatted datetime string or original string if parsing fails
    """
    if not datetime_str:
        return datetime_str

    try:
        # Remove extra whitespace and normalize
        datetime_str = ' '.join(datetime_str.split())

        # Parse the datetime string
        parsed_dt = date_parser.parse(datetime_str)

        # Convert to UTC if timezone aware, otherwise assume UTC
        if parsed_dt.tzinfo is not None:
            utc_dt = parsed_dt.astimezone(pytz.UTC)
        else:
            utc_dt = pytz.UTC.localize(parsed_dt)

        return utc_dt.isoformat()

    except Exception as e:
        logging.warning(f"Could not parse datetime string '{datetime_str}': {e}")
        return datetime_str  # Return original string if parsing fails

def scrape_single_url(session, url):
    """
    Scrape migration data from a single BirdCast dashboard URL

    Args:
        session: requests.Session object
        url: BirdCast dashboard URL to scrape

    Returns:
        Dictionary containing scraped data or None if scraping failed
    """
    try:
        logging.info(f"Scraping data from {url}")
        response = session.get(url, timeout=30)
        response.raise_for_status()

        # Check if we're getting actual HTML content or just CSS
        content_type = response.headers.get('content-type', '').lower()
        if 'text/html' not in content_type:
            logging.error(f"Unexpected content type: {content_type}")
            return None

        html_content = response.text

        # Check if we got CSS instead of HTML
        if html_content.strip().startswith('@keyframes') or 'css' in html_content[:100].lower():
            logging.error("Received CSS content instead of HTML - the URL might be incorrect")
            return None

        soup = BeautifulSoup(html_content, 'html.parser')

        # Extract data - initialize with all expected fields
        data = {
            'scrape_timestamp': datetime.now(timezone.utc).isoformat(),
            'url': url,
            'region_code': None,
            'region_name': None,
            'total_birds': None,
            'peak_birds_in_flight': None,
            'flight_direction': None,
            'flight_speed_mph': None,
            'flight_altitude_ft': None,
            'migration_start_raw': None,
            'migration_start_utc': None,
            'migration_end_raw': None,
            'migration_end_utc': None,
            'migration_date': None
        }

        # Extract region name from URL and page content
        region_match = re.search(r'/region/([^/]+)$', url)
        if region_match:
            data['region_code'] = region_match.group(1)

        # Try to find region name in the page content
        text_content = soup.get_text()
        region_name_match = re.search(r'Migration Dashboard\s+([A-Za-z\s,]+?)(?:\s+Search|$)', text_content)
        if region_name_match:
            data['region_name'] = region_name_match.group(1).strip()

        # Try to find "xxx Birds crossed" pattern
        birds_crossed_match = re.search(r'(\d{1,3}(?:,?\d{3})*)\s+Birds crossed.*last night', text_content, re.IGNORECASE)
        if birds_crossed_match:
            total_birds_str = birds_crossed_match.group(1).replace(',', '')
            try:
                data['total_birds'] = int(total_birds_str)
            except ValueError:
                logging.warning(f"Could not parse total birds: {total_birds_str}")

        # Try to find "Peak of xxx birds in flight" pattern (old format)
        peak_birds_match = re.search(r'Peak of (\d{1,3}(?:,?\d{3})*) birds in flight', text_content, re.IGNORECASE)
        if not peak_birds_match:
            # Try new format: "PEAK MIGRATION TRAFFIC: 134,500 Birds in flight"
            peak_birds_match = re.search(r'PEAK MIGRATION TRAFFIC:\s*(\d{1,3}(?:,?\d{3})*)\s*Birds in flight', text_content, re.IGNORECASE)
        if not peak_birds_match:
            # Try alternative format: "134,500 Birds in flight (est.)"
            peak_birds_match = re.search(r'(\d{1,3}(?:,?\d{3})*)\s*Birds in flight \(est\.\)', text_content, re.IGNORECASE)

        if peak_birds_match:
            peak_birds_str = peak_birds_match.group(1).replace(',', '')
            try:
                data['peak_birds_in_flight'] = int(peak_birds_str)
            except ValueError:
                logging.warning(f"Could not parse peak birds: {peak_birds_str}")

        # Try to find flight direction - multiple patterns
        direction_match = re.search(r'flying ([A-Z]{1,3})', text_content)  # Old format
        if not direction_match:
            direction_match = re.search(r'Direction:\s*([A-Z]{1,3})', text_content)  # New format

        if direction_match:
            data['flight_direction'] = direction_match.group(1)

        # Try to find flight speed - multiple patterns
        speed_match = re.search(r'at (\d+) mph', text_content)  # Old format
        if not speed_match:
            speed_match = re.search(r'Speed:\s*(\d+)\s*mph', text_content)  # New format

        if speed_match:
            try:
                data['flight_speed_mph'] = int(speed_match.group(1))
            except ValueError:
                logging.warning(f"Could not parse flight speed: {speed_match.group(1)}")

        # Try to find flight altitude - multiple patterns
        altitude_match = re.search(r'at (\d{1,3}(?:,?\d{3})*) feet', text_content)  # Old format
        if not altitude_match:
            altitude_match = re.search(r'Altitude:\s*(\d{1,3}(?:,?\d{3})*)\s*ft?', text_content)  # New format

        if altitude_match:
            altitude_str = altitude_match.group(1).replace(',', '')
            try:
                data['flight_altitude_ft'] = int(altitude_str)
            except ValueError:
                logging.warning(f"Could not parse flight altitude: {altitude_str}")

        # Try to find migration start and end times
        # Look for patterns like "Fri, Oct 24, 2025, 6:00 PM EDT"
        time_patterns = re.findall(r'([A-Za-z]{3}, [A-Za-z]{3} \d{1,2}, \d{4}, \d{1,2}:\d{2} [AP]M [A-Z]{3})', text_content)

        if len(time_patterns) >= 2:
            # Usually the first is start time, second is end time
            data['migration_start_raw'] = time_patterns[0]
            data['migration_end_raw'] = time_patterns[1]

            # Parse to UTC
            data['migration_start_utc'] = parse_datetime_string(time_patterns[0])
            data['migration_end_utc'] = parse_datetime_string(time_patterns[1])

        # Try to find migration date (like "Friday night, Oct 24")
        date_match = re.search(r'([A-Za-z]+ night, [A-Za-z]+ \d{1,2})', text_content)
        if date_match:
            data['migration_date'] = date_match.group(1)

        logging.info(f"Successfully scraped data from {url}")
        return data

    except requests.exceptions.RequestException as e:
        logging.error(f"Request failed for {url}: {e}")
        return None
    except Exception as e:
        logging.error(f"Error scraping {url}: {e}")
        return None

def scrape_data(session, urls, scraper_name="BirdCast"):
    """
    Scrape migration data from multiple URLs

    Args:
        session: requests.Session object
        urls: List of URLs to scrape
        scraper_name: Name of the scraper for logging

    Returns:
        List of scraped data dictionaries
    """
    all_data = []

    logging.info(f"Starting to scrape {len(urls)} {scraper_name} URLs...")

    for url in urls:
        data = scrape_single_url(session, url)
        if data:
            all_data.append(data)

        # Add a small delay to be respectful to the server
        time.sleep(0.5)

    logging.info(f"Completed scraping. Successfully collected data from {len(all_data)} URLs")
    return all_data

def save_to_parquet(data_list, filename):
    """
    Save data to Parquet file (append with deduplication)

    Args:
        data_list: List of data dictionaries or single dictionary
        filename: Full path to the Parquet file
    """
    if not data_list:
        return

    # Handle both single data dict and list of data dicts
    if isinstance(data_list, dict):
        data_list = [data_list]

    # Convert new data to DataFrame
    new_df = pd.DataFrame(data_list)

    # Optimize data types for better compression
    for col in new_df.columns:
        if col in ['total_birds', 'peak_birds_in_flight', 'flight_speed_mph', 'flight_altitude_ft']:
            new_df[col] = pd.to_numeric(new_df[col], errors='coerce').astype('Int64')
        elif col in ['migration_start_utc', 'migration_end_utc', 'scrape_timestamp']:
            # Convert datetime strings to proper datetime objects
            new_df[col] = pd.to_datetime(new_df[col], errors='coerce', utc=True)

    # Load existing data if file exists
    if os.path.isfile(filename):
        try:
            existing_df = pd.read_parquet(filename)

            # Ensure datetime columns in existing data are properly typed
            for col in existing_df.columns:
                if col in ['migration_start_utc', 'migration_end_utc', 'scrape_timestamp']:
                    if existing_df[col].dtype == 'object':
                        existing_df[col] = pd.to_datetime(existing_df[col], errors='coerce', utc=True)

            # Combine with new data
            combined_df = pd.concat([existing_df, new_df], ignore_index=True)
        except Exception as e:
            logging.warning(f"Could not read existing Parquet file: {e}. Creating new file.")
            combined_df = new_df
    else:
        combined_df = new_df

    # Remove duplicates - keep most recent entry per region per day
    if len(combined_df) > 0 and 'scrape_timestamp' in combined_df.columns:
        # Use scrape_timestamp directly since it's already a datetime object
        combined_df['scrape_timestamp_dt'] = combined_df['scrape_timestamp']

        # Create comprehensive deduplication key
        dedup_columns = ['scrape_timestamp_dt']

        # Add region_code if available
        if 'region_code' in combined_df.columns:
            dedup_columns.append('region_code')
        elif 'url' in combined_df.columns:
            # Fallback to URL if region_code is missing
            dedup_columns.append('url')

        # Create date key for deduplication (prefer migration_date, fallback to scrape date)
        if 'migration_date' in combined_df.columns and combined_df['migration_date'].notna().any():
            combined_df['date_key'] = combined_df['migration_date'].fillna(
                combined_df['scrape_timestamp_dt'].dt.date.astype(str)
            )
        else:
            combined_df['date_key'] = combined_df['scrape_timestamp_dt'].dt.date.astype(str)

        # Add date_key to deduplication columns
        if 'region_code' in combined_df.columns or 'url' in combined_df.columns:
            dedup_subset = [col for col in dedup_columns if col != 'scrape_timestamp_dt'] + ['date_key']
        else:
            # If no region identifier, use more strict deduplication
            dedup_subset = ['date_key', 'scrape_timestamp_dt']

        # Sort by timestamp (most recent first) then drop duplicates
        combined_df = combined_df.sort_values('scrape_timestamp_dt', ascending=False)

        # Remove exact duplicates first (all columns identical except timestamp)
        data_columns = [col for col in combined_df.columns if col not in ['scrape_timestamp', 'scrape_timestamp_dt', 'date_key']]
        if len(data_columns) > 0:
            combined_df = combined_df.drop_duplicates(subset=data_columns, keep='first')

        # Then remove duplicates by region and date (keep most recent)
        combined_df = combined_df.drop_duplicates(subset=dedup_subset, keep='first')

        # Remove helper columns
        combined_df = combined_df.drop(['scrape_timestamp_dt', 'date_key'], axis=1)

        logging.info(f"After deduplication: {len(combined_df)} unique records remaining")

    # Save to Parquet with compression
    combined_df.to_parquet(filename, compression='snappy', index=False)

    logging.info(f"Data for {len(data_list)} region(s) saved to {filename} (total records: {len(combined_df)})")

def save_to_json(data_list, filename):
    """
    Save data to JSON file (append to list) - DEPRECATED: Use save_to_parquet instead

    Args:
        data_list: List of data dictionaries or single dictionary
        filename: Full path to the JSON file
    """
    if not data_list:
        return

    # Handle both single data dict and list of data dicts
    if isinstance(data_list, dict):
        data_list = [data_list]

    if os.path.isfile(filename):
        with open(filename, 'r', encoding='utf-8') as f:
            try:
                existing_data = json.load(f)
            except json.JSONDecodeError:
                existing_data = []
    else:
        existing_data = []

    existing_data.extend(data_list)

    with open(filename, 'w', encoding='utf-8') as f:
        json.dump(existing_data, f, indent=2, ensure_ascii=False)

    logging.info(f"Data for {len(data_list)} region(s) saved to {filename}")

def save_to_csv(data_list, filename):
    """
    Save data to CSV file

    Args:
        data_list: List of data dictionaries or single dictionary
        filename: Full path to the CSV file
    """
    if not data_list:
        return

    # Handle both single data dict and list of data dicts
    if isinstance(data_list, dict):
        data_list = [data_list]

    file_exists = os.path.isfile(filename)

    # Define consistent column order for BirdCast data
    expected_fieldnames = [
        'scrape_timestamp',
        'url',
        'region_code',
        'region_name',
        'total_birds',
        'peak_birds_in_flight',
        'flight_direction',
        'flight_speed_mph',
        'flight_altitude_ft',
        'migration_start_raw',
        'migration_start_utc',
        'migration_end_raw',
        'migration_end_utc',
        'migration_date'
    ]

    # Get all unique fieldnames from all records
    all_fieldnames = set()
    for data in data_list:
        all_fieldnames.update(data.keys())

    # Use expected order for known fields, append any unexpected fields at the end
    ordered_fieldnames = []
    for field in expected_fieldnames:
        if field in all_fieldnames:
            ordered_fieldnames.append(field)
            all_fieldnames.remove(field)

    # Add any remaining fields that weren't in the expected list
    ordered_fieldnames.extend(sorted(all_fieldnames))

    with open(filename, 'a', newline='', encoding='utf-8') as csvfile:
        writer = csv.DictWriter(csvfile, fieldnames=ordered_fieldnames)

        if not file_exists:
            writer.writeheader()

        for data in data_list:
            writer.writerow(data)

    logging.info(f"Data for {len(data_list)} region(s) saved to {filename}")

def save_to_duckdb(data_list, table_name):
    """
    Save BirdCast data to DuckDB (INSERT OR REPLACE on region_code, date_key).
    Derives date_key from migration_date (fallback: scrape_timestamp date).

    Args:
        data_list: List of data dictionaries or single dictionary
        table_name: Target DuckDB table name
    """
    if not data_list:
        return

    if isinstance(data_list, dict):
        data_list = [data_list]

    try:
        import pandas as pd
        sys_path_entry = os.path.dirname(os.path.abspath(__file__))
        import sys as _sys
        if sys_path_entry not in _sys.path:
            _sys.path.insert(0, sys_path_entry)
        from db import get_connection, init_schema

        df = pd.DataFrame(data_list)

        # Derive date_key
        if "migration_date" in df.columns and df["migration_date"].notna().any():
            df["date_key"] = df["migration_date"].fillna("")
        else:
            df["date_key"] = ""

        needs_fill = df["date_key"] == ""
        if needs_fill.any() and "scrape_timestamp" in df.columns:
            ts = pd.to_datetime(df.loc[needs_fill, "scrape_timestamp"], errors="coerce", utc=True)
            df.loc[needs_fill, "date_key"] = ts.dt.date.astype(str)

        # Stringify all columns (table is all-VARCHAR for dirty data resilience)
        for col in df.columns:
            if pd.api.types.is_datetime64_any_dtype(df[col]):
                df[col] = df[col].dt.strftime("%Y-%m-%dT%H:%M:%S+00:00")
            else:
                df[col] = df[col].astype(str)
                df[col] = df[col].where(df[col] != "nan", None)
                df[col] = df[col].where(df[col] != "None", None)
                df[col] = df[col].where(df[col] != "NaT", None)

        with get_connection() as con:
            init_schema(con)
            con.execute(f"INSERT OR REPLACE INTO {table_name} SELECT * FROM df")
            count = con.execute(f"SELECT COUNT(*) FROM {table_name}").fetchone()[0]
            logging.info(f"[DuckDB] {table_name}: {count:,} total rows")

    except Exception as e:
        logging.warning(f"[DuckDB WARNING] Failed to write to {table_name}: {e}")


def load_flyway_urls_from_csv(csv_filename):
    """
    Load BirdCast URLs from a flyway corridor analysis CSV file

    Args:
        csv_filename: Name of the CSV file in the county_data_for_birdcast_urls directory

    Returns:
        List of URLs or empty list if file not found
    """
    csv_file = os.path.join(DATA_DIR, "county_data_for_birdcast_urls", csv_filename)

    if not os.path.exists(csv_file):
        logging.error(f"Flyway CSV file not found: {csv_file}")
        logging.error("Please run the appropriate flyway corridor analysis script first to generate the county list")
        return []

    urls = []
    try:
        with open(csv_file, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                if 'birdcast_url' in row and row['birdcast_url']:
                    urls.append(row['birdcast_url'])

        logging.info(f"Loaded {len(urls)} URLs from {csv_file}")
        return urls

    except Exception as e:
        logging.error(f"Error reading CSV file {csv_file}: {e}")
        return []

def print_scraper_summary(data, scraper_name, data_filename):
    """
    Print a summary of scraping results

    Args:
        data: List of scraped data
        scraper_name: Name of the scraper
        data_filename: Name of the data file (without path)
    """
    if data:
        print(f"{scraper_name} - SUCCESS")
        print("=" * (len(scraper_name) + 10))
        print(f"Scraped data for {len(data)} regions at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

        # Count by state if region_code is available
        if data and 'region_code' in data[0]:
            state_counts = {}
            for region_data in data:
                region_code = region_data.get('region_code', '')
                if region_code and len(region_code) >= 5:  # Format: US-XX-XXX
                    state = region_code[3:5]  # Extract state code
                    state_counts[state] = state_counts.get(state, 0) + 1

            if state_counts:
                print(f"\nCounties by state:")
                for state, count in sorted(state_counts.items()):
                    print(f"   {state}: {count} counties")

        # Show sample data
        for i, region_data in enumerate(data[:3]):  # Show first 3 regions
            region_name = region_data.get('region_name', 'Unknown Region')
            total_birds = region_data.get('total_birds', 'N/A')
            peak_birds = region_data.get('peak_birds_in_flight', 'N/A')
            direction = region_data.get('flight_direction', 'N/A')

            print(f"\n{region_name}:")
            print(f"   Total birds: {total_birds:,}" if isinstance(total_birds, int) else f"   Total birds: {total_birds}")
            print(f"   Peak in flight: {peak_birds:,}" if isinstance(peak_birds, int) else f"   Peak in flight: {peak_birds}")
            print(f"   Direction: {direction}")

        if len(data) > 3:
            print(f"\n... and {len(data) - 3} more regions")

        print(f"\nData saved to: {data_filename}")
        print("=" * (len(scraper_name) + 10))

        logging.info("Scraping completed successfully")
    else:
        print(f"{scraper_name} - FAILED")
        print("No data was collected. Check the logs for details.")
        logging.error("Scraping failed")
