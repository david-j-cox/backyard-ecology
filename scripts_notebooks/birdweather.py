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
from datetime import date, datetime, timedelta
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


# If we have at least this fraction of the API's totalCount, the day is considered complete.
COMPLETENESS_RATIO = 0.95


def parse_args():
    ap = argparse.ArgumentParser(description="Download BirdWeather detections for Duval County (FL), St Johns County (FL), and Essex County (NJ).")
    ap.add_argument("--from", dest="from_date", default="2018-01-01",
                    help="Start date (YYYY-MM-DD). Default: 2018-01-01")
    ap.add_argument("--to", dest="to_date", default=date.today().isoformat(),
                    help="End date (YYYY-MM-DD). Default: today")
    ap.add_argument("--page-size", type=int, default=500, help="Detections per page. Default: 500")
    ap.add_argument("--lookback", type=int, default=30,
                    help="Number of recent days to check for incomplete data. Default: 30")
    ap.add_argument("--force", action="store_true",
                    help="Repull all days in range regardless of existing counts")
    return ap.parse_args()


def get_existing_daily_counts(filepath):
    """Return {(county, date): row_count} from existing parquet."""
    if not filepath.exists():
        return {}
    df = pd.read_parquet(filepath)
    df["timestamp"] = pd.to_datetime(df["timestamp"], errors="coerce", utc=True)
    df["_date"] = df["timestamp"].dt.date
    return df.groupby(["county", "_date"]).size().to_dict()


def remove_county_day(filepath, county, day):
    """Remove all rows for a given county+date from the parquet file."""
    if not filepath.exists():
        return
    df = pd.read_parquet(filepath)
    df["timestamp"] = pd.to_datetime(df["timestamp"], errors="coerce", utc=True)
    df["_date"] = df["timestamp"].dt.date
    mask = (df["county"] == county) & (df["_date"] == day)
    removed = mask.sum()
    if removed > 0:
        df = df[~mask].drop(columns=["_date"])
        df.to_parquet(filepath, engine="pyarrow", index=False)
        print(f"  Removed {removed:,} incomplete rows for {county} on {day}")
    else:
        df.drop(columns=["_date"]).to_parquet(filepath, engine="pyarrow", index=False)


def fetch_one_day(county_key, bbox, day, page_size=500, max_retries=3):
    """Fetch all detections for one county on one day. Returns DataFrame or None on failure."""
    period = {"from": day.isoformat(), "to": day.isoformat()}

    for attempt in range(1, max_retries + 1):
        try:
            all_nodes = []
            for page_nodes in fetch_all_for_bbox(
                bbox["ne"], bbox["sw"], period=period, page_size=page_size, pause=0.25
            ):
                all_nodes.extend(page_nodes)

            if not all_nodes:
                return pd.DataFrame()

            rows = [flatten(node, county=county_key) for node in all_nodes]
            df = pd.DataFrame(rows)
            return convert_dates(df)
        except Exception as e:
            if attempt < max_retries:
                wait = 30 * attempt
                print(f"  Attempt {attempt}/{max_retries} failed for {county_key} {day}: {e}")
                print(f"  Waiting {wait}s before retry...")
                time.sleep(wait)
            else:
                print(f"  FAILED after {max_retries} attempts for {county_key} {day}: {e}")
                return None


def get_api_total_count(bbox, day):
    """
    Ask the API for the totalCount of detections for a bbox on a single day.
    Uses first=1 to minimize data transfer -- we only need the count.
    Returns the totalCount (int) or None on failure.
    """
    period = {"from": day.isoformat(), "to": day.isoformat()}
    variables = {
        "first": 1,
        "after": None,
        "period": period,
        "ne": bbox["ne"],
        "sw": bbox["sw"],
    }
    try:
        resp = requests.post(
            GRAPHQL_URL,
            json={"query": DETECTIONS_QUERY, "variables": variables},
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()
        if "errors" in data:
            return None
        return data["data"]["detections"].get("totalCount")
    except Exception:
        return None


def find_days_to_fetch(county_key, bbox, existing_counts, start, end, lookback, force):
    """
    Identify days that need fetching for a county.

    For each day in the range, compares the local row count against the API's
    totalCount. A day is flagged for (re)pull if:
      - missing entirely (no local data)
      - local count < COMPLETENESS_RATIO * API totalCount
      - force mode is on
    Days within the lookback window are always checked against the API.
    Older days with any local data are only spot-checked if they look suspicious.
    """
    days_to_fetch = []
    today = date.today()
    lookback_start = today - timedelta(days=lookback)

    day = start
    while day <= end:
        existing = existing_counts.get((county_key, day), 0)

        if force:
            days_to_fetch.append(day)
            day += timedelta(days=1)
            continue

        if existing == 0:
            # Missing day -- no need to hit the API, just fetch it
            days_to_fetch.append(day)
            day += timedelta(days=1)
            continue

        # For days with data: check against API totalCount
        # Always check recent days; for older days, only check if count is low
        should_check = day >= lookback_start
        if not should_check:
            # Skip old days that have data -- they're likely fine
            day += timedelta(days=1)
            continue

        api_total = get_api_total_count(bbox, day)
        if api_total is not None and api_total > 0:
            ratio = existing / api_total
            if ratio < COMPLETENESS_RATIO:
                print(f"  {county_key} {day}: incomplete -- {existing:,} local vs {api_total:,} API ({ratio:.0%})")
                days_to_fetch.append(day)
            else:
                print(f"  {county_key} {day}: OK -- {existing:,} local vs {api_total:,} API ({ratio:.0%})")
        elif api_total == 0:
            print(f"  {county_key} {day}: API reports 0 detections, skipping")
        else:
            # API check failed -- be safe and refetch recent days
            print(f"  {county_key} {day}: API check failed, refetching to be safe")
            days_to_fetch.append(day)

        time.sleep(0.25)  # Be nice to the API during count checks
        day += timedelta(days=1)

    return days_to_fetch


def main():
    args = parse_args()

    script_dir = Path(__file__).parent.resolve()
    project_root = script_dir.parent if script_dir.name == "scripts_notebooks" else script_dir
    data_dir = project_root / "data"
    data_dir.mkdir(exist_ok=True)
    output_file = data_dir / "county_level_birdweather.parquet"

    start = date.fromisoformat(args.from_date)
    end = date.fromisoformat(args.to_date)

    print(f"County BirdWeather fetch: {start} to {end}")
    print(f"Lookback window: {args.lookback} days | Completeness threshold: {COMPLETENESS_RATIO:.0%} of API total")
    if args.force:
        print("FORCE mode: repulling all days regardless of existing counts")
    print()

    # Scan existing data to figure out what needs pulling
    existing_counts = get_existing_daily_counts(output_file)
    if existing_counts:
        n_counties = len(set(c for c, _ in existing_counts))
        n_days = len(existing_counts)
        print(f"Found existing data: {n_counties} counties, {n_days} county-day records")
    else:
        print("No existing data found, starting fresh")

    total_fetched = 0
    total_skipped = 0
    failed_days = []

    for county_key, bbox in COUNTY_BBOXES.items():
        # For existing counties, only go back to the lookback window + any gaps.
        # For new counties (no data at all), use the full --from date.
        county_has_data = any(c == county_key for c, _ in existing_counts)
        if county_has_data and not args.force:
            # Find earliest date to scan: the later of --from or the oldest existing date
            county_dates = [d for c, d in existing_counts if c == county_key]
            county_start = max(start, min(county_dates))
        else:
            county_start = start

        days_to_fetch = find_days_to_fetch(
            county_key, bbox, existing_counts, county_start, end, args.lookback, args.force
        )

        if not days_to_fetch:
            print(f"\n=== {county_key}: up to date, nothing to fetch ===")
            total_skipped += 1
            continue

        print(f"\n=== {county_key}: {len(days_to_fetch)} days to fetch ===")

        for day in days_to_fetch:
            existing = existing_counts.get((county_key, day), 0)
            if existing > 0:
                status = f"(replacing: {existing} rows)"
            else:
                status = "(missing)"
            print(f"\n  {county_key} {day} {status}")

            # Remove old data before repulling
            if existing > 0:
                remove_county_day(output_file, county_key, day)

            df = fetch_one_day(county_key, bbox, day, page_size=args.page_size)

            if df is None:
                failed_days.append((county_key, day))
                continue

            if df.empty:
                print(f"  No detections for {county_key} on {day}")
                continue

            print(f"  Fetched {len(df):,} detections for {county_key} on {day}")
            append_to_parquet(df, output_file)
            write_to_duckdb(df)
            total_fetched += len(df)

            time.sleep(1)

    # Summary
    print("\n" + "=" * 50)
    print(f"Complete.")
    print(f"  Fetched: {total_fetched:,} detections")
    print(f"  Counties skipped (up to date): {total_skipped}")
    if failed_days:
        print(f"  FAILED ({len(failed_days)} days):")
        for county, day in failed_days:
            print(f"    {county} {day}")
    else:
        print(f"  No failures.")

    if output_file.exists():
        final_df = pd.read_parquet(output_file)
        print(f"\nFinal file: {len(final_df):,} total rows")
        if "county" in final_df.columns:
            print(f"  Counties: {sorted(final_df['county'].unique())}")

def write_to_duckdb(df):
    """
    INSERT OR REPLACE county birdweather rows into DuckDB.
    Wrapped in try/except so parquet path still works if DuckDB fails.
    """
    if df is None or df.empty:
        return

    try:
        import sys as _sys
        _sys.path.insert(0, str(Path(__file__).resolve().parent))
        from db import get_connection, init_schema

        # Stringify datetime columns for DuckDB VARCHAR storage
        write_df = df.copy()
        for col in write_df.columns:
            if pd.api.types.is_datetime64_any_dtype(write_df[col]):
                write_df[col] = write_df[col].dt.strftime("%Y-%m-%dT%H:%M:%S+00:00")
        write_df = write_df.astype(str)
        write_df = write_df.where(write_df != "nan", None)
        write_df = write_df.where(write_df != "NaT", None)
        write_df = write_df.where(write_df != "None", None)

        with get_connection() as con:
            init_schema(con)
            con.execute("INSERT OR REPLACE INTO county_birdweather SELECT * FROM write_df")
            count = con.execute("SELECT COUNT(*) FROM county_birdweather").fetchone()[0]
            print(f"[DuckDB] county_birdweather: {count:,} total rows")

    except Exception as e:
        print(f"[DuckDB WARNING] Failed to write county birdweather to DuckDB: {e}")


if __name__ == "__main__":
    main()
