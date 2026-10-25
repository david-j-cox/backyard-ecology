#!/usr/bin/env python3
"""
Fetch the BirdWeather PUC's on-board environment sensor history (temperature,
humidity, pressure, air quality, sound level) and store hourly means.

The PUC logs a reading roughly every 40 seconds. This is the backyard's own
microclimate, measured at the feeder rather than at a weather model grid point.
Days the station was offline have no readings and stay as gaps.

Resumes from the last stored day per station (re-fetching that day in case it
was partial), so a first run backfills from the station's first detection.

Outputs:
- data/puc_environment_hourly.csv : one row per (station, local hour)
- DuckDB table puc_environment_hourly

Usage (from scripts_notebooks/):
    python puc_environment.py [--from YYYY-MM-DD] [--to YYYY-MM-DD]
"""

import argparse
import os
import time
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd
import requests
from dotenv import load_dotenv

load_dotenv()

GRAPHQL_URL = "https://app.birdweather.com/graphql"

STATIONS = {
    "21974": {"name": "Jacksonville", "tz": "America/New_York", "key": os.getenv("JAX_BIRDWX_API_KEY")},
    "18618": {"name": "Essex Fells", "tz": "America/New_York", "key": os.getenv("ESSEX_BIRDWX_API_KEY")},
}

QUERY = """
query env($stationId: ID!, $period: InputDuration, $first: Int, $after: String) {
  station(id: $stationId) {
    earliestDetectionAt
    sensors {
      environmentHistory(first: $first, after: $after, period: $period) {
        pageInfo { hasNextPage endCursor }
        nodes { timestamp temperature humidity barometricPressure aqi eco2 voc soundPressureLevel }
      }
    }
  }
}
"""

# API field -> stored column
FIELDS = {
    "temperature": "temperature_c",
    "humidity": "humidity_pct",
    "barometricPressure": "pressure_hpa",
    "aqi": "aqi",
    "eco2": "eco2_ppm",
    "voc": "voc",
    "soundPressureLevel": "sound_pressure_db",
}
COLUMNS = ["station_id", "hour_local", "readings", *FIELDS.values()]

# Physically possible ranges; readings outside them are sensor glitches
# (pressure of 0 or 3,000+ hPa, humidity of 0) and are dropped before averaging
VALID_RANGES = {
    "temperature": (-40, 60),
    "humidity": (0.1, 100),
    "barometricPressure": (900, 1100),
    "aqi": (0.1, 500),
    "eco2": (0.1, 60000),
    "voc": (0, 500),
    "soundPressureLevel": (20, 130),
}


def run_query(station_id, key, variables, max_retries=3):
    headers = {"Content-Type": "application/json"}
    if key:
        headers["Authorization"] = f"Bearer {key}"
    for attempt in range(1, max_retries + 1):
        try:
            resp = requests.post(GRAPHQL_URL, json={"query": QUERY, "variables": {"stationId": station_id, **variables}},
                                 headers=headers, timeout=60)
            resp.raise_for_status()
            body = resp.json()
            if body.get("errors"):
                raise RuntimeError(body["errors"][0].get("message"))
            return body["data"]["station"]
        except (requests.RequestException, RuntimeError) as e:
            if attempt == max_retries:
                raise
            print(f"  Attempt {attempt} failed for station {station_id}: {e}; retrying")
            time.sleep(2 * attempt)


def fetch_day(station_id, key, day):
    """All environment readings for one station-day."""
    nodes, after = [], None
    while True:
        station = run_query(station_id, key, {"period": {"from": day.isoformat(), "to": day.isoformat()},
                                              "first": 5000, "after": after})
        page = station["sensors"]["environmentHistory"]
        nodes += page["nodes"]
        if not page["pageInfo"]["hasNextPage"]:
            return nodes
        after = page["pageInfo"]["endCursor"]


def hourly_means(station_id, tz_name, nodes):
    if not nodes:
        return pd.DataFrame(columns=COLUMNS)
    df = pd.DataFrame(nodes)
    for field, (lo, hi) in VALID_RANGES.items():
        if field in df:
            df[field] = df[field].where(df[field].between(lo, hi))
    # Floor in UTC, then convert: flooring local time fails on the repeated
    # hour when daylight saving ends. Offsets keep the two 1 AM hours distinct.
    hour = pd.to_datetime(df["timestamp"], utc=True).dt.floor("h").dt.tz_convert(tz_name)
    df["hour_local"] = hour.map(lambda t: t.isoformat())
    agg = df.groupby("hour_local").agg(readings=("timestamp", "size"), **{
        col: (field, "mean") for field, col in FIELDS.items() if field in df
    }).reset_index()
    agg.insert(0, "station_id", station_id)
    return agg.reindex(columns=COLUMNS).round(3)


def main():
    parser = argparse.ArgumentParser(description="Fetch PUC environment sensor history as hourly means")
    parser.add_argument("--from", dest="start", type=date.fromisoformat, help="First day to fetch (default: resume)")
    parser.add_argument("--to", dest="end", type=date.fromisoformat, default=date.today() - timedelta(days=1),
                        help="Last day to fetch, inclusive (default: yesterday)")
    parser.add_argument("--pause", type=float, default=0.25, help="Seconds between requests")
    args = parser.parse_args()

    data_dir = Path(__file__).resolve().parent.parent / "data"
    csv_path = data_dir / "puc_environment_hourly.csv"
    existing = pd.read_csv(csv_path, dtype={"station_id": str}) if csv_path.exists() else pd.DataFrame(columns=COLUMNS)

    def save(frames):
        combined = pd.concat([f for f in frames if not f.empty], ignore_index=True)
        # Re-fetched hours replace stored ones
        combined = combined.drop_duplicates(["station_id", "hour_local"], keep="last")
        combined = combined.sort_values(["station_id", "hour_local"])[COLUMNS]
        combined.to_csv(csv_path, index=False)
        print(f"Wrote {len(combined):,} hourly rows to {csv_path}")
        return combined

    frames = [existing]
    for station_id, meta in STATIONS.items():
        stored = existing.loc[existing["station_id"] == station_id, "hour_local"]
        if args.start:
            start = args.start
        elif len(stored):
            start = date.fromisoformat(stored.max()[:10])
        else:
            first = run_query(station_id, meta["key"], {"first": 1})["earliestDetectionAt"]
            start = datetime.fromisoformat(first).astimezone(ZoneInfo(meta["tz"])).date()

        days = [start + timedelta(days=i) for i in range((args.end - start).days + 1)]
        print(f"{meta['name']} ({station_id}): fetching {len(days)} days from {start} to {args.end}")
        empty = 0
        for day in days:
            try:
                nodes = fetch_day(station_id, meta["key"], day)
            except Exception as e:
                print(f"  {day}: failed ({e}); will retry next run")
                continue
            if not nodes:
                empty += 1
            frames.append(hourly_means(station_id, meta["tz"], nodes))
            time.sleep(args.pause)
        print(f"  done; {empty} day(s) had no readings (station offline)")
        # Save after each station so a later failure keeps this one's work
        combined = save(frames)
        frames = [combined]

    try:
        from db import get_connection, init_schema
        with get_connection() as con:
            init_schema(con)
            con.execute("DELETE FROM puc_environment_hourly")
            con.execute("INSERT INTO puc_environment_hourly SELECT * FROM combined")
            print(f"[DuckDB] puc_environment_hourly: {len(combined):,} rows")
    except Exception as e:
        print(f"[DuckDB WARNING] Failed to write PUC environment data to DuckDB: {e}")


if __name__ == "__main__":
    main()
