#!/usr/bin/env python3
"""
Backfill hourly weather data from OpenWeather One Call API 3.0 (timemachine)
for a set of locations, from a start date to an end date.

The script automatically resumes from the latest existing data for each location,
so subsequent runs will only fetch new data since the last run.

Outputs:
- data/hourly_weather.csv : one row per (location, hour)
- data/sunrise_sunset.csv : one row per (location, local date)
"""

import os
import time
import csv
import argparse
from pathlib import Path
from datetime import datetime, date, time as dtime, timedelta, timezone
from zoneinfo import ZoneInfo

import requests
from dotenv import load_dotenv

load_dotenv()

# Allow either WEATHER_API_KEY or OPENWEATHER_API_KEY to be set
OPENWEATHER_API_KEY = (
    os.getenv("WEATHER_API_KEY") or
    os.getenv("OPENWEATHER_API_KEY")
)

API_URL = "https://api.openweathermap.org/data/3.0/onecall/timemachine"

# NOTE: longitudes for US sites should be negative (west of Greenwich)
LOCATIONS = [
    {"name": "Jacksonville, FL", "lat": 30.3501, "lon": -81.6035},
    {"name": "Essex Fells, NJ", "lat": 40.8308, "lon": -74.2831},
    {"name": "Southampton, UK", "lat": 50.9105, "lon": -1.4049},
    {"name": "Auburn, AL", "lat": 32.6099, "lon": -85.4808},
]


def get_latest_timestamps_by_location(hourly_path: Path):
    """
    Read existing hourly_weather.csv and return a dict mapping location name
    to the latest requested_dt_utc datetime (or None if no data exists).
    
    Returns: dict[str, datetime | None]
    """
    latest_by_location = {}
    
    if not hourly_path.exists():
        return latest_by_location
    
    try:
        with hourly_path.open("r", newline="") as f:
            reader = csv.DictReader(f)
            for row in reader:
                loc_name = row.get("location")
                if not loc_name:
                    continue
                
                # Try requested_dt_utc first, fallback to observed_dt_utc
                dt_str = row.get("requested_dt_utc") or row.get("observed_dt_utc")
                if not dt_str:
                    continue
                
                try:
                    # Parse ISO format datetime
                    dt = datetime.fromisoformat(dt_str.replace("Z", "+00:00"))
                    if dt.tzinfo is None:
                        dt = dt.replace(tzinfo=timezone.utc)
                    
                    # Update latest timestamp for this location
                    if loc_name not in latest_by_location:
                        latest_by_location[loc_name] = dt
                    else:
                        latest_by_location[loc_name] = max(
                            latest_by_location[loc_name], dt
                        )
                except (ValueError, AttributeError) as e:
                    print(f"[WARN] Could not parse datetime '{dt_str}' for {loc_name}: {e}")
                    continue
    except Exception as e:
        print(f"[WARN] Error reading existing hourly data: {e}")
    
    return latest_by_location


def generate_hourly_utc(start_date: date, end_date: date, start_dt_override: datetime = None, end_dt_override: datetime = None):
    """
    Yield UTC datetimes at hourly intervals from start_date 00:00 (or start_dt_override if provided)
    through end_date 23:00 (or end_dt_override if provided), inclusive.
    Stops at the earliest of end_date 23:00 or end_dt_override.
    """
    if start_dt_override is not None:
        start_dt = start_dt_override
        # Round down to the nearest hour if needed
        if start_dt.minute != 0 or start_dt.second != 0 or start_dt.microsecond != 0:
            start_dt = start_dt.replace(minute=0, second=0, microsecond=0)
    else:
        start_dt = datetime.combine(start_date, dtime(0, 0, tzinfo=timezone.utc))
    
    # Calculate the maximum end datetime based on end_date
    end_dt_max = datetime.combine(end_date, dtime(23, 0, tzinfo=timezone.utc))
    
    # Use end_dt_override if provided, otherwise use end_date 23:00
    # Always use the earlier of end_dt_override and end_dt_max to avoid future forecasts
    if end_dt_override is not None:
        end_dt_override_rounded = end_dt_override.replace(minute=0, second=0, microsecond=0)
        end_dt = min(end_dt_override_rounded, end_dt_max)
    else:
        end_dt = end_dt_max

    current = start_dt
    while current <= end_dt:
        yield current
        current = current + timedelta(hours=1)


def fetch_observation(session: requests.Session,
                      api_key: str,
                      lat: float,
                      lon: float,
                      dt_unix: int,
                      units: str = "metric",
                      max_retries: int = 3):
    """
    Call the One Call 3.0 timemachine endpoint for a single timestamp.

    Returns parsed JSON on success, or None on failure after retries.
    """
    params = {
        "lat": lat,
        "lon": lon,
        "dt": dt_unix,      # Unix UTC timestamp
        "appid": api_key,
        "units": units,
    }

    for attempt in range(1, max_retries + 1):
        try:
            resp = session.get(API_URL, params=params, timeout=15)
        except requests.RequestException as e:
            print(f"[WARN] Request error (attempt {attempt}) for dt={dt_unix}: {e}")
            time.sleep(5)
            continue

        if resp.status_code == 200:
            return resp.json()

        if resp.status_code == 429:
            # Rate limit hit: pause a bit and retry
            print("[WARN] HTTP 429 (rate limited). Sleeping before retry...")
            time.sleep(65)
            continue

        # Other error: log and (maybe) retry
        print(f"[WARN] HTTP {resp.status_code} for dt={dt_unix}: {resp.text}")
        time.sleep(5)

    print(f"[ERROR] Failed after {max_retries} attempts for dt={dt_unix}")
    return None


def hourly_fieldnames():
    """
    Define the hourly CSV schema.
    """
    return [
        "location",
        "lat",
        "lon",
        "requested_dt_utc",
        "observed_dt_utc",
        "observed_dt_local",
        "timezone",
        "timezone_offset_seconds",
        "sunrise_utc",
        "sunrise_local",
        "sunset_utc",
        "sunset_local",
        "temp",
        "feels_like",
        "pressure",
        "humidity",
        "dew_point",
        "clouds",
        "uvi",
        "visibility",
        "wind_speed",
        "wind_gust",
        "wind_deg",
        "weather_id",
        "weather_main",
        "weather_description",
        "rain_1h_mm",
        "snow_1h_mm",
    ]


def sunrise_fieldnames():
    """
    Define the daily sunrise/sunset CSV schema.
    """
    return [
        "location",
        "lat",
        "lon",
        "date_local",
        "timezone",
        "timezone_offset_seconds",
        "sunrise_local",
        "sunset_local",
        "sunrise_utc",
        "sunset_utc",
        "day_length_minutes",
    ]


def write_row(
    hourly_writer: csv.DictWriter,
    sunrise_writer: csv.DictWriter,
    daily_seen: set,
    location: dict,
    dt_utc: datetime,
    payload: dict,
):
    tz_offset = payload.get("timezone_offset", 0)  # seconds
    tz_name = payload.get("timezone", "UTC")
    data_list = payload.get("data") or []

    if not data_list:
        print(f"[WARN] No 'data' array in response for dt={dt_utc.isoformat()}")
        return

    obs = data_list[0]  # one timestamp per response

    # 1. Observation time in UTC
    obs_dt_utc = datetime.fromtimestamp(obs["dt"], tz=timezone.utc)

    # 2. Convert to *real* local time using the timezone name, with DST
    try:
        local_tz = ZoneInfo(tz_name)
        obs_dt_local = obs_dt_utc.astimezone(local_tz)
    except Exception:
        # Fallback: fixed-offset timezone if for some reason ZoneInfo fails
        local_tz = timezone(timedelta(seconds=tz_offset))
        obs_dt_local = obs_dt_utc.astimezone(local_tz)

    # Sunrise / sunset (if provided; they should be)
    sunrise_ts = obs.get("sunrise")
    sunset_ts = obs.get("sunset")

    if sunrise_ts is not None:
        sunrise_utc = datetime.fromtimestamp(sunrise_ts, tz=timezone.utc)
        sunrise_local = sunrise_utc.astimezone(local_tz)
    else:
        sunrise_utc = None
        sunrise_local = None

    if sunset_ts is not None:
        sunset_utc = datetime.fromtimestamp(sunset_ts, tz=timezone.utc)
        sunset_local = sunset_utc.astimezone(local_tz)
    else:
        sunset_utc = None
        sunset_local = None

    weather = (obs.get("weather") or [{}])[0]

    rain_1h = None
    if isinstance(obs.get("rain"), dict):
        rain_1h = obs["rain"].get("1h")

    snow_1h = None
    if isinstance(obs.get("snow"), dict):
        snow_1h = obs["snow"].get("1h")

    # ---- hourly row ----
    hourly_row = {
        "location": location["name"],
        "lat": payload.get("lat", location["lat"]),
        "lon": payload.get("lon", location["lon"]),
        "requested_dt_utc": dt_utc.isoformat(),
        "observed_dt_utc": obs_dt_utc.isoformat(),
        "observed_dt_local": obs_dt_local.isoformat(),
        "timezone": tz_name,
        "timezone_offset_seconds": tz_offset,
        "sunrise_utc": sunrise_utc.isoformat() if sunrise_utc else None,
        "sunrise_local": sunrise_local.isoformat() if sunrise_local else None,
        "sunset_utc": sunset_utc.isoformat() if sunset_utc else None,
        "sunset_local": sunset_local.isoformat() if sunset_local else None,
        "temp": obs.get("temp"),
        "feels_like": obs.get("feels_like"),
        "pressure": obs.get("pressure"),
        "humidity": obs.get("humidity"),
        "dew_point": obs.get("dew_point"),
        "clouds": obs.get("clouds"),
        "uvi": obs.get("uvi"),
        "visibility": obs.get("visibility"),
        "wind_speed": obs.get("wind_speed"),
        "wind_gust": obs.get("wind_gust"),
        "wind_deg": obs.get("wind_deg"),
        "weather_id": weather.get("id"),
        "weather_main": weather.get("main"),
        "weather_description": weather.get("description"),
        "rain_1h_mm": rain_1h,
        "snow_1h_mm": snow_1h,
    }

    hourly_writer.writerow(hourly_row)

    # ---- daily sunrise/sunset row (one per location x local date) ----
    if sunrise_local and sunset_local:
        date_local_str = sunrise_local.date().isoformat()
        key = (location["name"], date_local_str)
        if key not in daily_seen:
            daily_seen.add(key)
            day_length_minutes = (sunset_local - sunrise_local).total_seconds() / 60.0

            sunrise_row = {
                "location": location["name"],
                "lat": payload.get("lat", location["lat"]),
                "lon": payload.get("lon", location["lon"]),
                "date_local": date_local_str,
                "timezone": tz_name,
                "timezone_offset_seconds": tz_offset,
                "sunrise_local": sunrise_local.isoformat(),
                "sunset_local": sunset_local.isoformat(),
                "sunrise_utc": sunrise_utc.isoformat(),
                "sunset_utc": sunset_utc.isoformat(),
                "day_length_minutes": round(day_length_minutes, 2),
            }
            sunrise_writer.writerow(sunrise_row)


def main():
    parser = argparse.ArgumentParser(
        description="Backfill hourly weather from OpenWeather One Call 3.0 timemachine"
    )
    parser.add_argument(
        "--start",
        default="2025-10-01",
        help="Start date (YYYY-MM-DD), default: 2025-10-01. Only used for locations with no existing data.",
    )
    parser.add_argument(
        "--end",
        default=date.today().strftime("%Y-%m-%d"),
        help="End date (YYYY-MM-DD), default: today (UTC)",
    )
    parser.add_argument(
        "--hourly-output",
        "-o",
        default="data/hourly_weather.csv",
        help="Output CSV file for hourly weather",
    )
    parser.add_argument(
        "--sunrise-output",
        default="data/sunrise_sunset.csv",
        help="Output CSV file for daily sunrise/sunset",
    )
    parser.add_argument(
        "--units",
        choices=["standard", "metric", "imperial"],
        default="metric",
        help="Units for temperature and wind (default: metric)",
    )
    parser.add_argument(
        "--sleep",
        type=float,
        default=1.0,
        help="Seconds to sleep between calls to avoid rate limits (default: 1.0)",
    )

    args = parser.parse_args()

    start_date = datetime.strptime(args.start, "%Y-%m-%d").date()
    end_date = datetime.strptime(args.end, "%Y-%m-%d").date()

    if end_date < start_date:
        raise ValueError("End date must be on or after start date.")

    api_key = OPENWEATHER_API_KEY
    if not api_key:
        raise RuntimeError(
            "Please set your OpenWeather API key in the WEATHER_API_KEY or "
            "OPENWEATHER_API_KEY environment variable."
        )

    # Resolve paths relative to script location (repo root) if they're default paths
    script_dir = Path(__file__).parent
    repo_root = script_dir.parent
    
    # If using default paths, resolve relative to repo root
    if args.hourly_output == "data/hourly_weather.csv":
        hourly_path = repo_root / "data" / "hourly_weather.csv"
    else:
        hourly_path = Path(args.hourly_output)
    
    if args.sunrise_output == "data/sunrise_sunset.csv":
        sunrise_path = repo_root / "data" / "sunrise_sunset.csv"
    else:
        sunrise_path = Path(args.sunrise_output)

    hourly_exists = hourly_path.exists()
    sunrise_exists = sunrise_path.exists()

    # Get latest timestamps for each location from existing data
    latest_timestamps = get_latest_timestamps_by_location(hourly_path)
    
    # Track which (location, date_local) we have already written
    daily_seen = set()
    if sunrise_exists:
        with sunrise_path.open("r", newline="") as sf:
            reader = csv.DictReader(sf)
            for row in reader:
                daily_seen.add((row["location"], row["date_local"]))

    h_fields = hourly_fieldnames()
    s_fields = sunrise_fieldnames()

    # Ensure data directory exists (if user runs from repo root)
    hourly_path.parent.mkdir(parents=True, exist_ok=True)
    sunrise_path.parent.mkdir(parents=True, exist_ok=True)

    # Calculate current UTC time rounded down to the nearest hour to avoid fetching future forecasts
    now_utc = datetime.now(timezone.utc)
    max_end_dt = now_utc.replace(minute=0, second=0, microsecond=0)

    with hourly_path.open("a", newline="") as hf, \
         sunrise_path.open("a", newline="") as sf, \
         requests.Session() as session:

        hourly_writer = csv.DictWriter(hf, fieldnames=h_fields)
        sunrise_writer = csv.DictWriter(sf, fieldnames=s_fields)

        if not hourly_exists:
            hourly_writer.writeheader()
        if not sunrise_exists:
            sunrise_writer.writeheader()

        for loc in LOCATIONS:
            loc_name = loc["name"]
            print(f"=== Processing location: {loc_name} ({loc['lat']}, {loc['lon']}) ===")
            
            # Determine start datetime for this location
            latest_dt = latest_timestamps.get(loc_name)
            if latest_dt:
                # Start from the next hour after the latest timestamp
                loc_start_dt = latest_dt + timedelta(hours=1)
                # Ensure it's at an hour boundary
                loc_start_dt = loc_start_dt.replace(minute=0, second=0, microsecond=0)
                loc_start_date = loc_start_dt.date()
                loc_start_dt_override = loc_start_dt
                print(f"  Resuming from {loc_start_dt.isoformat()} (latest existing data: {latest_dt.isoformat()})")
            else:
                # No existing data for this location, use the provided start date
                loc_start_date = start_date
                loc_start_dt_override = None
                print(f"  Starting from {loc_start_date} (no existing data found)")
            
            # Only process if start datetime is before or equal to max_end_dt (current time)
            check_dt = loc_start_dt_override if loc_start_dt_override else datetime.combine(loc_start_date, dtime(0, 0, tzinfo=timezone.utc))
            if check_dt > max_end_dt:
                print(f"  Skipping {loc_name}: start datetime ({check_dt.isoformat()}) is after current time ({max_end_dt.isoformat()})")
                continue
            
            # Track current day to notify when a new day starts
            current_day = None
            for dt_utc in generate_hourly_utc(loc_start_date, end_date, start_dt_override=loc_start_dt_override, end_dt_override=max_end_dt):
                # Safety check: skip any hours that are in the future (shouldn't happen, but be defensive)
                if dt_utc > max_end_dt:
                    print(f"  Skipping future hour: {dt_utc.isoformat()} (current time: {max_end_dt.isoformat()})")
                    break
                
                # Check if we've moved to a new day
                day_utc = dt_utc.date()
                if current_day is None:
                    # First iteration - print the starting day
                    current_day = day_utc
                    print(f"  Processing day: {current_day.isoformat()}")
                elif day_utc != current_day:
                    # New day started
                    current_day = day_utc
                    print(f"  Processing day: {current_day.isoformat()}")
                
                unix_ts = int(dt_utc.timestamp())
                payload = fetch_observation(
                    session=session,
                    api_key=api_key,
                    lat=loc["lat"],
                    lon=loc["lon"],
                    dt_unix=unix_ts,
                    units=args.units,
                )

                if payload:
                    write_row(
                        hourly_writer=hourly_writer,
                        sunrise_writer=sunrise_writer,
                        daily_seen=daily_seen,
                        location=loc,
                        dt_utc=dt_utc,
                        payload=payload,
                    )

                # Stay comfortably under the 60 calls/minute limit
                time.sleep(args.sleep)

    # Dual-write: bulk-load CSVs into DuckDB
    write_to_duckdb(hourly_path, sunrise_path)


def write_to_duckdb(hourly_path: Path, sunrise_path: Path):
    """
    Bulk-load the CSV files into DuckDB (INSERT OR IGNORE).
    Called at the end of main() as a dual-write alongside the CSV output.
    """
    try:
        from db import get_connection, init_schema
        import pandas as pd

        with get_connection() as con:
            init_schema(con)

            if hourly_path.exists():
                df = pd.read_csv(hourly_path, dtype=str)
                df = df.where(df.notna(), None)
                if not df.empty:
                    con.execute("INSERT OR IGNORE INTO hourly_weather SELECT * FROM df")
                    count = con.execute("SELECT COUNT(*) FROM hourly_weather").fetchone()[0]
                    print(f"[DuckDB] hourly_weather: {count:,} total rows")

            if sunrise_path.exists():
                df = pd.read_csv(sunrise_path, dtype=str)
                df = df.where(df.notna(), None)
                if not df.empty:
                    con.execute("INSERT OR IGNORE INTO sunrise_sunset SELECT * FROM df")
                    count = con.execute("SELECT COUNT(*) FROM sunrise_sunset").fetchone()[0]
                    print(f"[DuckDB] sunrise_sunset: {count:,} total rows")

    except Exception as e:
        print(f"[DuckDB WARNING] Failed to write weather data to DuckDB: {e}")


if __name__ == "__main__":
    main()
