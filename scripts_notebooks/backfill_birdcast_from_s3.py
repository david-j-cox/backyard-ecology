#!/usr/bin/env python3
"""
Backfill BirdCast county-level migration data from the public S3 bucket.

The daily scraper records "last night" totals from the dashboard HTML, but
historical pages only ever show the most recent night. When the scraper
misses a night (e.g. the Pacific flyway regex bug 2026-04-16 -> 2026-05-01),
the only way to recover is to reconstruct totals from the per-10-minute
radar feed in `is-birdcast-observed-prod`.

Each S3 object is one nationwide CSV at a fixed UTC 10-min slot, with rows
keyed on `location` (county code) and `part_of_day` ('N' = night, 'D' = day).
Summing `birds_passed` and taking max `birds_aloft` across the night rows
reproduces the dashboard's "Birds crossed last night" / "Peak birds in
flight" headline values to within rounding (validated against WA-073 on
2026-05-01: 436,799 vs dashboard 436,800; 299,626 vs dashboard 299,600).

Usage:
    python backfill_birdcast_from_s3.py --start 2026-04-16 --end 2026-05-01
    python backfill_birdcast_from_s3.py --start 2026-03-01 --end 2026-05-01 --flyway pacific
    python backfill_birdcast_from_s3.py --dry-run --start 2026-04-16 --end 2026-04-16
"""

import argparse
import csv
import gzip
import io
import logging
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
import requests

# Make sibling modules importable when run directly
sys.path.insert(0, str(Path(__file__).resolve().parent))
import scraper_utils  # noqa: E402
from db import get_connection, init_schema  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger("backfill_birdcast_from_s3")

S3_BASE = "https://is-birdcast-observed-prod.s3.us-east-1.amazonaws.com"
DATA_DIR = Path(__file__).resolve().parent.parent / "data"

FLYWAY_CSVS = {
    "atlantic": "atlantic_flyway_corridor_counties_with_urls.csv",
    "mississippi": "mississippi_flyway_corridor_counties_with_urls.csv",
    "pacific": "pacific_flyway_corridor_counties_with_urls.csv",
}

FLYWAY_PARQUETS = {
    "atlantic": "atlantic_flyway_corridor.parquet",
    "mississippi": "mississippi_flyway_corridor.parquet",
    "pacific": "pacific_flyway_corridor.parquet",
}

FLYWAY_TABLES = {
    "atlantic": "atlantic_flyway",
    "mississippi": "mississippi_flyway",
    "pacific": "pacific_flyway",
}


def load_flyway_county_codes(flyway):
    """Return list of (region_code, region_name) for a flyway."""
    csv_path = DATA_DIR / "county_data_for_birdcast_urls" / FLYWAY_CSVS[flyway]
    counties = []
    with open(csv_path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            url = row.get("birdcast_url", "")
            m = re.search(r"/region/([^/]+)$", url)
            if m:
                code = m.group(1)
                county_name = row.get("county", "")
                state_name = row.get("state", "")
                full_name = f"{county_name} County, {state_name}" if county_name and state_name else ""
                counties.append((code, full_name, url))
    return counties


def list_s3_keys_for_date(d):
    """List all CSV keys for a UTC date. Returns list of full keys."""
    prefix = f"dashboard/{d.year:04d}/{d.month:02d}/{d.day:02d}/"
    keys = []
    continuation = None
    while True:
        params = {"list-type": "2", "prefix": prefix}
        if continuation:
            params["continuation-token"] = continuation
        r = requests.get(S3_BASE, params=params, timeout=30)
        r.raise_for_status()
        keys.extend(re.findall(r"<Key>([^<]+)</Key>", r.text))
        # Continuation token if any
        m = re.search(r"<NextContinuationToken>([^<]+)</NextContinuationToken>", r.text)
        if not m:
            break
        continuation = m.group(1)
    return keys


def fetch_and_parse_csv(key, county_codes_set):
    """
    Download one CSV from S3, gzip-decompress, return a list of dicts
    filtered to rows whose `location` is in `county_codes_set`.
    """
    url = f"{S3_BASE}/{key}"
    try:
        r = requests.get(url, timeout=30)
        if r.status_code != 200:
            logger.warning(f"S3 fetch {r.status_code} for {key}")
            return []
        decoded = gzip.decompress(r.content).decode("utf-8", errors="replace")
    except Exception as e:
        logger.warning(f"Failed to fetch/decompress {key}: {e}")
        return []

    out = []
    reader = csv.DictReader(io.StringIO(decoded))
    for row in reader:
        if row.get("location") in county_codes_set:
            out.append(row)
    return out


def night_of_date(local_dt_str):
    """
    Map a 'YYYY-MM-DDTHH:MM:SS' local timestamp to its 'night-of' date.
    Rule: hour >= 12 -> same date; hour < 12 -> previous date.
    """
    try:
        dt = datetime.fromisoformat(local_dt_str)
    except (ValueError, TypeError):
        return None
    if dt.hour >= 12:
        return dt.date()
    return dt.date() - timedelta(days=1)


def aggregate_rows_to_nights(rows):
    """
    Take a flat list of CSV row dicts, filter to part_of_day='N', and
    aggregate per (location, night_date) producing:
      total_birds = sum(birds_passed)
      peak_birds_in_flight = max(birds_aloft)
      migration_start_utc = first datetime UTC
      migration_end_utc   = last datetime UTC
    Returns dict keyed by (location, night_date) -> aggregated dict.
    """
    agg = {}
    for row in rows:
        if row.get("part_of_day") != "N":
            continue
        nd = night_of_date(row.get("datetime_local", ""))
        if nd is None:
            continue
        key = (row["location"], nd)
        try:
            bp = float(row.get("birds_passed") or 0)
            ba = float(row.get("birds_aloft") or 0)
        except ValueError:
            continue
        utc = row.get("datetime", "")
        if key not in agg:
            agg[key] = {
                "total_passed": 0.0,
                "peak_aloft": 0.0,
                "first_utc": utc,
                "last_utc": utc,
            }
        a = agg[key]
        a["total_passed"] += bp
        if ba > a["peak_aloft"]:
            a["peak_aloft"] = ba
        if utc < a["first_utc"]:
            a["first_utc"] = utc
        if utc > a["last_utc"]:
            a["last_utc"] = utc
    return agg


def format_migration_date(d):
    """Format a date as 'Friday night, May 1' (matching scraper output)."""
    return d.strftime("%A night, %b ") + str(d.day)


def build_records(agg, county_name_map):
    """
    Convert aggregated dict into a list of records matching the schema
    used by scraper_utils.save_to_parquet / save_to_duckdb.
    """
    now_iso = datetime.now(timezone.utc).isoformat()
    records = []
    for (loc, nd), v in agg.items():
        if v["total_passed"] <= 0 and v["peak_aloft"] <= 0:
            continue
        records.append({
            "scrape_timestamp": now_iso,
            "url": f"https://dashboard.birdcast.info/region/{loc}",
            "region_code": loc,
            "region_name": county_name_map.get(loc, ""),
            "total_birds": int(round(v["total_passed"])),
            "peak_birds_in_flight": int(round(v["peak_aloft"])),
            "flight_direction": None,
            "flight_speed_mph": None,
            "flight_altitude_ft": None,
            "migration_start_raw": None,
            "migration_start_utc": v["first_utc"],
            "migration_end_raw": None,
            "migration_end_utc": v["last_utc"],
            "migration_date": format_migration_date(nd),
        })
    return records


def write_to_parquet(records, flyway):
    """Append/upsert records into the flyway parquet using existing helper."""
    if not records:
        return
    parquet_path = DATA_DIR / FLYWAY_PARQUETS[flyway]
    scraper_utils.save_to_parquet(records, str(parquet_path))


def write_to_duckdb(records, flyway):
    """Upsert records into the DuckDB flyway table."""
    if not records:
        return
    table = FLYWAY_TABLES[flyway]
    df = pd.DataFrame(records)
    # Mirror save_to_duckdb's date_key derivation: prefer migration_date, else scrape date
    df["date_key"] = df["migration_date"]
    # Stringify all columns (table is all-VARCHAR)
    for col in df.columns:
        df[col] = df[col].astype(str)
        df[col] = df[col].where(df[col] != "nan", None)
        df[col] = df[col].where(df[col] != "None", None)
    with get_connection() as con:
        init_schema(con)
        con.execute(f"INSERT OR REPLACE INTO {table} SELECT * FROM df")
        count = con.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        logger.info(f"[DuckDB] {table}: {count:,} total rows after backfill")


def parse_args():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--start", required=True, help="Inclusive start night-of date (YYYY-MM-DD)")
    p.add_argument("--end", required=True, help="Inclusive end night-of date (YYYY-MM-DD)")
    p.add_argument("--flyway", choices=list(FLYWAY_CSVS.keys()) + ["all"], default="all")
    p.add_argument("--max-workers", type=int, default=24, help="Parallel S3 fetches")
    p.add_argument("--dry-run", action="store_true", help="Compute but do not write")
    p.add_argument("--no-duckdb", action="store_true", help="Skip DuckDB write")
    p.add_argument("--no-parquet", action="store_true", help="Skip parquet write")
    return p.parse_args()


def daterange(start, end):
    d = start
    while d <= end:
        yield d
        d += timedelta(days=1)


def main():
    args = parse_args()
    start_d = datetime.strptime(args.start, "%Y-%m-%d").date()
    end_d = datetime.strptime(args.end, "%Y-%m-%d").date()

    flyways = list(FLYWAY_CSVS.keys()) if args.flyway == "all" else [args.flyway]

    # Build set of all county codes across selected flyways and per-flyway maps
    county_to_flyway = {}
    flyway_codes = {fw: set() for fw in flyways}
    county_name_map = {}
    for fw in flyways:
        for code, name, _url in load_flyway_county_codes(fw):
            flyway_codes[fw].add(code)
            county_to_flyway[code] = fw
            if name:
                county_name_map[code] = name
    all_codes = set(county_to_flyway.keys())
    logger.info(f"Tracking {len(all_codes)} counties across {len(flyways)} flyway(s)")

    # A night N requires UTC files from N (evening) and N+1 (early morning).
    # So fetch UTC dates [start_d .. end_d + 1].
    utc_dates = list(daterange(start_d, end_d + timedelta(days=1)))
    logger.info(f"Fetching {len(utc_dates)} UTC days of S3 listings")

    # 1. List all keys for the UTC date range
    all_keys = []
    for d in utc_dates:
        try:
            keys = list_s3_keys_for_date(d)
            all_keys.extend(keys)
            logger.info(f"  {d}: {len(keys)} keys")
        except Exception as e:
            logger.error(f"Failed to list S3 for {d}: {e}")

    logger.info(f"Total CSV files to fetch: {len(all_keys)}")
    if args.dry_run and len(all_keys) == 0:
        logger.info("Dry-run with no keys; exiting")
        return

    # 2. Parallel fetch + parse, accumulate filtered rows
    t0 = time.time()
    all_rows = []
    completed = 0
    with ThreadPoolExecutor(max_workers=args.max_workers) as pool:
        futures = {pool.submit(fetch_and_parse_csv, k, all_codes): k for k in all_keys}
        for fut in as_completed(futures):
            rows = fut.result()
            all_rows.extend(rows)
            completed += 1
            if completed % 100 == 0 or completed == len(all_keys):
                elapsed = time.time() - t0
                logger.info(f"  fetched {completed}/{len(all_keys)} ({completed/elapsed:.1f}/s, {len(all_rows):,} matching rows)")

    logger.info(f"Fetched {len(all_rows):,} matching rows in {time.time()-t0:.1f}s")

    # 3. Aggregate per (county, night) and filter to the requested night range
    agg = aggregate_rows_to_nights(all_rows)
    in_range = {k: v for k, v in agg.items() if start_d <= k[1] <= end_d}
    logger.info(f"Aggregated into {len(agg):,} (county, night) pairs; {len(in_range):,} in target range")

    # 4. Split by flyway and write
    for fw in flyways:
        codes = flyway_codes[fw]
        fw_agg = {k: v for k, v in in_range.items() if k[0] in codes}
        records = build_records(fw_agg, county_name_map)
        # Sort by (date, region_code) for deterministic output
        records.sort(key=lambda r: (r["migration_date"], r["region_code"]))
        logger.info(f"  {fw}: {len(records):,} records")

        if args.dry_run:
            for r in records[:5]:
                logger.info(f"    sample: {r['region_code']} {r['migration_date']} total={r['total_birds']:,} peak={r['peak_birds_in_flight']:,}")
            continue

        if not args.no_parquet:
            write_to_parquet(records, fw)
            logger.info(f"  {fw}: parquet updated")
        if not args.no_duckdb:
            write_to_duckdb(records, fw)


if __name__ == "__main__":
    main()
