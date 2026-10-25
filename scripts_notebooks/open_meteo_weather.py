#!/usr/bin/env python3
"""
Fill hourly weather from Open-Meteo (free, no API key) into the same files
weather.py writes, picking up where the existing data for each location ends.

Replaces the OpenWeather fetch, which was disabled after its per-call rate
limit (HTTP 429) made the daily run time out. Open-Meteo's historical forecast
API returns a whole date range per request, with no reporting lag.

Outputs (appended, same schema as weather.py):
- data/hourly_weather.csv : one row per (location, hour)
- data/sunrise_sunset.csv : one row per (location, local date)

Usage (from scripts_notebooks/):
    python open_meteo_weather.py [--end YYYY-MM-DD]
"""

import argparse
import csv
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import requests

from weather import (
    LOCATIONS,
    get_latest_timestamps_by_location,
    hourly_fieldnames,
    sunrise_fieldnames,
    write_to_duckdb,
)

API_URL = "https://historical-forecast-api.open-meteo.com/v1/forecast"

TIMEZONES = {
    "Jacksonville, FL": "America/New_York",
    "Essex Fells, NJ": "America/New_York",
    "Southampton, UK": "Europe/London",
    "Auburn, AL": "America/Chicago",
}

# Open-Meteo variable -> hourly_weather.csv column (units match OpenWeather metric)
HOURLY_VARS = {
    "temperature_2m": "temp",
    "apparent_temperature": "feels_like",
    "pressure_msl": "pressure",
    "relative_humidity_2m": "humidity",
    "dew_point_2m": "dew_point",
    "cloud_cover": "clouds",
    "uv_index": "uvi",
    "visibility": "visibility",
    "wind_speed_10m": "wind_speed",
    "wind_gusts_10m": "wind_gust",
    "wind_direction_10m": "wind_deg",
    "rain": "rain_1h_mm",
    "snowfall": "snow_1h_mm",
    "weather_code": "weather_id",
}

# WMO weather codes -> OpenWeather-style main group
WMO_MAIN = {
    0: "Clear", 1: "Clouds", 2: "Clouds", 3: "Clouds", 45: "Fog", 48: "Fog",
    51: "Drizzle", 53: "Drizzle", 55: "Drizzle", 56: "Drizzle", 57: "Drizzle",
    61: "Rain", 63: "Rain", 65: "Rain", 66: "Rain", 67: "Rain",
    71: "Snow", 73: "Snow", 75: "Snow", 77: "Snow",
    80: "Rain", 81: "Rain", 82: "Rain", 85: "Snow", 86: "Snow",
    95: "Thunderstorm", 96: "Thunderstorm", 99: "Thunderstorm",
}


def fetch(location, start, end, tz_name):
    """Hourly observations (UTC) and daily sunrise/sunset (local) for a date range."""
    common = {
        "latitude": location["lat"],
        "longitude": location["lon"],
        "start_date": start.isoformat(),
        "end_date": end.isoformat(),
        "wind_speed_unit": "ms",
    }
    hourly = requests.get(API_URL, params={**common, "hourly": ",".join(HOURLY_VARS), "timezone": "GMT"}, timeout=60)
    hourly.raise_for_status()
    daily = requests.get(API_URL, params={**common, "daily": "sunrise,sunset", "timezone": tz_name}, timeout=60)
    daily.raise_for_status()
    return hourly.json()["hourly"], daily.json()["daily"]


def hourly_rows(location, hourly, tz_name, after_utc):
    tz = ZoneInfo(tz_name)
    for i, stamp in enumerate(hourly["time"]):
        obs_utc = datetime.fromisoformat(stamp).replace(tzinfo=timezone.utc)
        if after_utc and obs_utc <= after_utc:
            continue
        obs_local = obs_utc.astimezone(tz)
        row = {
            "location": location["name"],
            "lat": location["lat"],
            "lon": location["lon"],
            "requested_dt_utc": obs_utc.isoformat(),
            "observed_dt_utc": obs_utc.isoformat(),
            "observed_dt_local": obs_local.isoformat(),
            "timezone": tz_name,
            "timezone_offset_seconds": int(obs_local.utcoffset().total_seconds()),
        }
        for var, col in HOURLY_VARS.items():
            row[col] = hourly[var][i]
        if row["snow_1h_mm"] is not None:
            row["snow_1h_mm"] = round(row["snow_1h_mm"] * 10, 2)  # cm -> mm
        code = row["weather_id"]
        row["weather_main"] = WMO_MAIN.get(code)
        row["weather_description"] = f"WMO code {code}" if code is not None else None
        yield row


def sunrise_rows(location, daily, tz_name, after_day):
    tz = ZoneInfo(tz_name)
    for day, rise, sets in zip(daily["time"], daily["sunrise"], daily["sunset"]):
        if (after_day and day <= after_day) or not rise or not sets:
            continue
        rise_local = datetime.fromisoformat(rise).replace(tzinfo=tz)
        set_local = datetime.fromisoformat(sets).replace(tzinfo=tz)
        yield {
            "location": location["name"],
            "lat": location["lat"],
            "lon": location["lon"],
            "date_local": day,
            "timezone": tz_name,
            "timezone_offset_seconds": int(rise_local.utcoffset().total_seconds()),
            "sunrise_local": rise_local.isoformat(),
            "sunset_local": set_local.isoformat(),
            "sunrise_utc": rise_local.astimezone(timezone.utc).isoformat(),
            "sunset_utc": set_local.astimezone(timezone.utc).isoformat(),
            "day_length_minutes": round((set_local - rise_local).total_seconds() / 60, 2),
        }


def latest_sunrise_dates(sunrise_path):
    latest = {}
    if sunrise_path.exists():
        with open(sunrise_path, newline="") as f:
            for row in csv.DictReader(f):
                loc, day = row["location"], row["date_local"]
                if day > latest.get(loc, ""):
                    latest[loc] = day
    return latest


def append_rows(path, fieldnames, rows):
    new_file = not path.exists()
    with open(path, "a", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        if new_file:
            writer.writeheader()
        count = 0
        for row in rows:
            writer.writerow(row)
            count += 1
    return count


def main():
    parser = argparse.ArgumentParser(description="Fill hourly weather from Open-Meteo")
    parser.add_argument("--end", type=date.fromisoformat, default=date.today() - timedelta(days=1),
                        help="Last date to fetch, inclusive (default: yesterday)")
    parser.add_argument("--default-start", type=date.fromisoformat, default=date(2025, 9, 30),
                        help="Start date for a location with no existing data")
    args = parser.parse_args()

    data_dir = Path(__file__).resolve().parent.parent / "data"
    hourly_path = data_dir / "hourly_weather.csv"
    sunrise_path = data_dir / "sunrise_sunset.csv"
    latest_hourly = get_latest_timestamps_by_location(hourly_path)
    latest_sun = latest_sunrise_dates(sunrise_path)

    for location in LOCATIONS:
        name = location["name"]
        tz_name = TIMEZONES[name]
        after_utc = latest_hourly.get(name)
        start = after_utc.astimezone(ZoneInfo(tz_name)).date() if after_utc else args.default_start
        if start > args.end:
            print(f"{name}: up to date")
            continue
        try:
            hourly, daily = fetch(location, start, args.end, tz_name)
        except requests.RequestException as e:
            print(f"[WARN] {name}: Open-Meteo request failed: {e}")
            continue
        n_hours = append_rows(hourly_path, hourly_fieldnames(), hourly_rows(location, hourly, tz_name, after_utc))
        n_days = append_rows(sunrise_path, sunrise_fieldnames(), sunrise_rows(location, daily, tz_name, latest_sun.get(name)))
        print(f"{name}: {start} to {args.end}, {n_hours} hourly rows, {n_days} sunrise rows")

    write_to_duckdb(hourly_path, sunrise_path)


if __name__ == "__main__":
    main()
