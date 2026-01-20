#!/usr/bin/env python3
"""
birdweather_counties.py
Fetch all BirdWeather detections for Duval County, FL, St. Johns County, FL, and Essex County, NJ.

Usage:
  python birdweather_counties.py
  # optional date window
  python birdweather_counties.py --from 2018-01-01 --to 2025-10-22
"""

import time
import argparse
from datetime import date, datetime
import requests
from requests.exceptions import HTTPError, RequestException
import pandas as pd
from pathlib import Path

GRAPHQL_URL = "https://app.birdweather.com/graphql"

# County bounding boxes (lat/lon) — slightly expanded to avoid edge misses.
COUNTY_BBOXES = {
    "duval_fl": {
        "ne": {"lat": 30.65, "lon": -81.20},
        "sw": {"lat": 30.00, "lon": -82.10},
    },
    "st_johns_fl": {
        "ne": {"lat": 30.25, "lon": -81.05},
        "sw": {"lat": 29.55, "lon": -81.80},
    },
    "essex_nj": {
        "ne": {"lat": 40.93, "lon": -74.10},
        "sw": {"lat": 40.68, "lon": -74.35},
    },
}

# GraphQL query for detections with cursor pagination
DETECTIONS_QUERY = """
query detections(
  $first: Int,
  $after: String,
  $period: InputDuration,
  $ne: InputLocation,
  $sw: InputLocation
) {
  detections(
    first: $first,
    after: $after,
    period: $period,
    ne: $ne,
    sw: $sw
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
      station { id name }
      soundscape { id url startTime endTime }
    }
  }
}
"""

def fetch_all_for_bbox(ne, sw, period=None, page_size=500, pause=0.25, max_retries=5):
    """
    Pulls all detections for a bbox (ne/sw are dicts with lat/lon) and optional period.
    Yields pages of detection nodes (lists of dicts) as they are fetched.
    
    Handles 504 Gateway Timeout and other server errors with exponential backoff.
    """
    headers = {"Content-Type": "application/json"}
    all_nodes = []
    after = None
    page_num = 0
    total_count = None

    # quick shape check
    for name, pt in (("ne", ne), ("sw", sw)):
        if not (isinstance(pt, dict) and "lat" in pt and "lon" in pt):
            raise ValueError(f"{name} must be a dict with 'lat' and 'lon' keys")

    while True:
        page_num += 1
        variables = {
            "first": page_size,
            "after": after,
            "period": period,
            "ne": ne,
            "sw": sw,
        }

        # Retry loop with exponential backoff for server errors
        for attempt in range(1, max_retries + 1):
            try:
                resp = requests.post(
                    GRAPHQL_URL,
                    json={"query": DETECTIONS_QUERY, "variables": variables},
                    timeout=120,  # Increased timeout for large queries
                )
                resp.raise_for_status()
                data = resp.json()
                if "errors" in data:
                    raise RuntimeError(f"GraphQL errors: {data['errors']}")
                break
            except HTTPError as e:
                # Handle specific HTTP status codes
                status_code = e.response.status_code if e.response else None
                
                if status_code == 504:  # Gateway Timeout
                    wait_time = min(30 * attempt, 300)  # 30s, 60s, 90s, 120s, 150s (max 5 min)
                    if attempt < max_retries:
                        print(f"  ⚠ Gateway Timeout (504) on page {page_num}, attempt {attempt}/{max_retries}. Waiting {wait_time}s before retry...", flush=True)
                        time.sleep(wait_time)
                        continue
                    else:
                        print(f"  ✗ Gateway Timeout (504) after {max_retries} attempts. API may be overloaded.", flush=True)
                        raise
                elif status_code and 500 <= status_code < 600:  # Other server errors
                    wait_time = min(10 * attempt, 120)  # 10s, 20s, 30s, 40s, 50s (max 2 min)
                    if attempt < max_retries:
                        print(f"  ⚠ Server error ({status_code}) on page {page_num}, attempt {attempt}/{max_retries}. Waiting {wait_time}s before retry...", flush=True)
                        time.sleep(wait_time)
                        continue
                    else:
                        print(f"  ✗ Server error ({status_code}) after {max_retries} attempts.", flush=True)
                        raise
                else:
                    # Other HTTP errors (4xx, etc.) - don't retry as aggressively
                    if attempt < max_retries:
                        wait_time = 2 * attempt
                        print(f"  ⚠ HTTP error ({status_code}) on page {page_num}, attempt {attempt}/{max_retries}. Waiting {wait_time}s...", flush=True)
                        time.sleep(wait_time)
                        continue
                    else:
                        raise
            except RequestException as e:
                # Network errors, timeouts, etc.
                if attempt < max_retries:
                    wait_time = min(5 * attempt, 60)  # 5s, 10s, 15s, 20s, 25s (max 1 min)
                    print(f"  ⚠ Network error on page {page_num}, attempt {attempt}/{max_retries}: {type(e).__name__}. Waiting {wait_time}s...", flush=True)
                    time.sleep(wait_time)
                    continue
                else:
                    print(f"  ✗ Network error after {max_retries} attempts: {e}", flush=True)
                    raise
            except Exception as e:
                # Other errors (GraphQL errors, etc.)
                if attempt < max_retries:
                    wait_time = pause * attempt
                    print(f"  ⚠ Error on page {page_num}, attempt {attempt}/{max_retries}: {type(e).__name__}. Waiting {wait_time}s...", flush=True)
                    time.sleep(wait_time)
                    continue
                else:
                    raise

        payload = data["data"]["detections"]
        nodes = payload.get("nodes") or []
        all_nodes.extend(nodes)
        
        # Get total count on first page if available
        if total_count is None:
            total_count = payload.get("totalCount")

        # Progress logging
        if total_count is not None:
            progress_pct = (len(all_nodes) / total_count * 100) if total_count > 0 else 0
            print(f"  Page {page_num}: Retrieved {len(all_nodes):,} / {total_count:,} detections ({progress_pct:.1f}%)", flush=True)
        else:
            print(f"  Page {page_num}: Retrieved {len(all_nodes):,} detections so far...", flush=True)

        # Yield this page of nodes
        yield nodes

        page_info = payload["pageInfo"]
        if not page_info["hasNextPage"]:
            break
        after = page_info["endCursor"]
        time.sleep(pause)

def flatten(node, county=None):
    """Flatten nested detection into a dict suitable for DataFrame."""
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
    if county is not None:
        result["county"] = county
    return result

def convert_dates(df):
    """Convert date/timestamp columns to datetime, handling various formats."""
    date_columns = ["timestamp", "sound_start", "sound_end"]
    for col in date_columns:
        if col in df.columns:
            # Convert to datetime, coercing errors to NaT
            df[col] = pd.to_datetime(df[col], errors="coerce", utc=True)
    return df

def append_to_parquet(df, filepath):
    """Append DataFrame to existing parquet file or create new one."""
    filepath = Path(filepath)
    
    if filepath.exists():
        # Read existing file and append
        existing_df = pd.read_parquet(filepath)
        combined_df = pd.concat([existing_df, df], ignore_index=True)
        # Remove duplicates based on id if it exists
        if "id" in combined_df.columns:
            combined_df = combined_df.drop_duplicates(subset=["id"], keep="last")
        combined_df.to_parquet(filepath, engine="pyarrow", index=False)
    else:
        # Create new file
        df.to_parquet(filepath, engine="pyarrow", index=False)


def parse_args():
    ap = argparse.ArgumentParser(description="Download BirdWeather detections for Duval County (FL), St Johns County (FL), and Essex County (NJ).")
    ap.add_argument("--from", dest="from_date", default="2018-01-01",
                    help="Start date (YYYY-MM-DD). Default: 2018-01-01")
    ap.add_argument("--to", dest="to_date", default=date.today().isoformat(),
                    help="End date (YYYY-MM-DD). Default: today")
    ap.add_argument("--page-size", type=int, default=500, help="Detections per page. Default: 500")
    ap.add_argument("--save-interval", type=int, default=10_000, help="Save every N records. Default: 10000")
    return ap.parse_args()

def main():
    args = parse_args()
    period = {"from": args.from_date, "to": args.to_date}
    save_interval = args.save_interval
    
    # Determine output path - save to data/ folder relative to project root
    # If running from scripts_notebooks/, go up one level; if from root, use current dir
    script_dir = Path(__file__).parent.resolve()
    project_root = script_dir.parent if script_dir.name == "scripts_notebooks" else script_dir
    data_dir = project_root / "data"
    data_dir.mkdir(exist_ok=True)
    output_file = data_dir / "county_level_birdweather.parquet"
    
    # Check if file exists and load existing data to determine what to fetch
    file_exists = output_file.exists()
    existing_df = None
    county_latest_dates = {}
    
    if file_exists:
        print(f"Found existing file {output_file}. Will append new data (duplicates will be removed).")
        existing_df = pd.read_parquet(output_file)
        
        if "county" in existing_df.columns and "timestamp" in existing_df.columns:
            # Convert timestamp if it's not already datetime
            if not pd.api.types.is_datetime64_any_dtype(existing_df["timestamp"]):
                existing_df["timestamp"] = pd.to_datetime(existing_df["timestamp"], errors="coerce", utc=True)
            
            # Find latest date for each county
            for county in existing_df["county"].unique():
                county_data = existing_df[existing_df["county"] == county]
                latest_date = county_data["timestamp"].max()
                if pd.notna(latest_date):
                    county_latest_dates[county] = latest_date
                    print(f"  {county}: latest date = {latest_date.strftime('%Y-%m-%d')}")
        
        existing_counties = set(existing_df["county"].unique()) if "county" in existing_df.columns else set()
    else:
        existing_counties = set()

    total_saved = 0
    base_from_date = pd.to_datetime(period["from"], utc=True)

    for key, bbox in COUNTY_BBOXES.items():
        # Determine the start date for this county
        to_date = pd.to_datetime(period["to"], utc=True)
        
        if key in county_latest_dates:
            # We have existing data - fetch from the day after the latest date
            latest_date = county_latest_dates[key]
            # Use the later of: latest_date+1day or the user's from_date
            county_from_date = max(latest_date + pd.Timedelta(days=1), base_from_date)
            
            # Check if we need to fetch anything
            if county_from_date > to_date:
                print(f"\nSkipping {key} - existing data is up to date (latest: {latest_date.strftime('%Y-%m-%d')}, requested end: {period['to']})")
                continue
            
            print(f"\nFetching detections for {key} (from {county_from_date.strftime('%Y-%m-%d')} to {period['to']}) ...")
            print(f"  (Existing data goes up to {latest_date.strftime('%Y-%m-%d')})")
        else:
            # No existing data - use the user's from_date
            county_from_date = base_from_date
            print(f"\nFetching detections for {key} ({period['from']} to {period['to']}) ...")
        
        # Create period for this county
        county_period = {
            "from": county_from_date.strftime('%Y-%m-%d'),
            "to": period["to"]
        }
        
        # Accumulate nodes for this county
        county_nodes = []
        county_total_fetched = 0
        last_saved_count = 0
        
        # Process pages as they come in
        for page_nodes in fetch_all_for_bbox(bbox["ne"], bbox["sw"], period=county_period, page_size=args.page_size):
            county_nodes.extend(page_nodes)
            county_total_fetched += len(page_nodes)
            
            # Save every save_interval records
            if county_total_fetched - last_saved_count >= save_interval:
                # Save accumulated nodes
                rows = [flatten(node, county=key) for node in county_nodes]
                df = pd.DataFrame(rows)
                df = convert_dates(df)
                
                saved_count = len(df)
                print(f"  Saving {saved_count:,} records (checkpoint at {county_total_fetched:,} total fetched)...", flush=True)
                append_to_parquet(df, output_file)
                total_saved += saved_count
                
                # Reset accumulator and update last saved count
                last_saved_count = county_total_fetched
                county_nodes = []
        
        # Save any remaining nodes after county is complete
        if county_nodes:
            print(f"  Retrieved {county_total_fetched:,} total records for {key}")
            rows = [flatten(node, county=key) for node in county_nodes]
            df = pd.DataFrame(rows)
            df = convert_dates(df)
            
            saved_count = len(df)
            print(f"  Saving final {saved_count:,} records for {key}...", flush=True)
            append_to_parquet(df, output_file)
            total_saved += saved_count
            print(f"  Saved. Total records in file: {total_saved:,}")
        elif county_total_fetched > 0:
            # All nodes were already saved in batches
            print(f"  Retrieved {county_total_fetched:,} total records for {key} (all saved incrementally)")
    
    # Final summary
    if output_file.exists():
        final_df = pd.read_parquet(output_file)
        print(f"\n✓ Complete! Final file {output_file} contains {len(final_df):,} total records")
        if "county" in final_df.columns:
            print(f"  Counties: {sorted(final_df['county'].unique())}")
    else:
        print(f"\n⚠ No data was saved to {output_file}")

if __name__ == "__main__":
    main()
