#!/usr/bin/env python3
"""
One-time fix: re-fetch county birdweather data for days where shared-station
detections were incorrectly deduplicated across counties.

The old append_to_parquet() used drop_duplicates(subset=["id"], keep="last"),
which meant the same detection in overlapping county bboxes would be kept for
only one county — whichever was fetched last. This caused counts to bounce
between Duval and St. Johns on the dashboard.

This script:
1. Reads the existing parquet
2. Identifies days where shared-station detections are missing from a county
3. Re-fetches those county-days from the BirdWeather API
4. Writes a corrected parquet with (id, county) deduplication

Usage:
    python fix_county_dedup.py
    python fix_county_dedup.py --dry-run   # just report what needs fixing
"""

import argparse
from datetime import date, timedelta
from pathlib import Path

import pandas as pd

from birdweather import (
    COUNTY_BBOXES,
    fetch_one_day,
    convert_dates,
    flatten,
)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true",
                        help="Report affected days without re-fetching")
    args = parser.parse_args()

    script_dir = Path(__file__).parent.resolve()
    project_root = script_dir.parent if script_dir.name == "scripts_notebooks" else script_dir
    parquet_path = project_root / "data" / "county_level_birdweather.parquet"

    if not parquet_path.exists():
        print(f"Parquet not found: {parquet_path}")
        return

    df = pd.read_parquet(parquet_path)
    print(f"Loaded {len(df):,} rows from {parquet_path}")

    # Step 1: find detection IDs that appear in only one county but whose
    # station appears in multiple counties (i.e., they were deduplicated away).
    df["sid"] = df["station_id"].astype(str)
    station_counties = df.groupby("sid")["county"].nunique()
    multi_county_stations = set(station_counties[station_counties > 1].index)
    print(f"Stations appearing in multiple counties: {len(multi_county_stations)}")

    # For each county, find dates where multi-county stations have suspiciously
    # low counts compared to their usual pattern.
    df["timestamp_dt"] = pd.to_datetime(df["timestamp"], errors="coerce", utc=True)
    df["_date"] = df["timestamp_dt"].dt.date

    # Identify county-days to re-fetch: those where shared-station detections
    # are present in one county but largely missing from another.
    jax_stj = {"duval_fl", "st_johns_fl"}
    shared_df = df[df["sid"].isin(multi_county_stations) & df["county"].isin(jax_stj)]

    daily_shared = shared_df.groupby(["_date", "county"]).size().unstack(fill_value=0)
    if "duval_fl" not in daily_shared.columns or "st_johns_fl" not in daily_shared.columns:
        print("Not enough data to detect alternation pattern")
        return

    # A day is "bad" if one county has < 5% of the other's shared-station count
    ratio_threshold = 0.05
    bad_days = []
    for d in daily_shared.index:
        duval = daily_shared.loc[d, "duval_fl"]
        stj = daily_shared.loc[d, "st_johns_fl"]
        total = duval + stj
        if total == 0:
            continue
        if duval > 0 and stj > 0:
            ratio = min(duval, stj) / max(duval, stj)
            if ratio < ratio_threshold:
                low_county = "st_johns_fl" if stj < duval else "duval_fl"
                bad_days.append((d, low_county, duval, stj))

    print(f"\nDays with suspected missing shared-station data: {len(bad_days)}")
    if not bad_days:
        print("No bad days found -- data looks clean.")
        return

    for d, low_county, duval, stj in bad_days[:20]:
        print(f"  {d}: duval_fl={duval:,}  st_johns_fl={stj:,}  (re-fetch {low_county})")
    if len(bad_days) > 20:
        print(f"  ... and {len(bad_days) - 20} more")

    if args.dry_run:
        print("\n--dry-run: no changes made")
        return

    # Step 2: Re-fetch the bad county-days
    print(f"\nRe-fetching {len(bad_days)} county-days...")

    new_rows = []
    for i, (day, county, _, _) in enumerate(bad_days):
        print(f"\n[{i+1}/{len(bad_days)}] {county} {day}")
        bbox = COUNTY_BBOXES[county]
        day_df = fetch_one_day(county, bbox, day)
        if day_df is not None and not day_df.empty:
            print(f"  Fetched {len(day_df):,} detections")
            new_rows.append(day_df)
        else:
            print(f"  No data returned")

    if not new_rows:
        print("No new data fetched.")
        return

    new_df = pd.concat(new_rows, ignore_index=True)
    print(f"\nTotal new detections: {len(new_df):,}")

    # Step 3: Merge with existing data using (id, county) dedup
    combined = pd.concat([df.drop(columns=["sid", "timestamp_dt", "_date"]), new_df],
                         ignore_index=True)
    before = len(combined)
    combined = combined.drop_duplicates(subset=["id", "county"], keep="last")
    print(f"After (id, county) dedup: {len(combined):,} rows (removed {before - len(combined):,} dupes)")

    combined.to_parquet(parquet_path, engine="pyarrow", index=False)
    print(f"Wrote {parquet_path}")


if __name__ == "__main__":
    main()
