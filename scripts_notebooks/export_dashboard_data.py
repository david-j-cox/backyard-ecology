#!/usr/bin/env python3
"""
Export compact daily summaries for the interactive dashboard (docs/index.html).

Reads the pipeline's DuckDB store and the county BirdWeather parquet, and
writes docs/data/dashboard.json: a few hundred KB of daily aggregates that the
page charts in the browser, plus the last date seen for every data source so
the page can flag anything that has stopped updating.

Usage (from scripts_notebooks/):
    python export_dashboard_data.py
"""

import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

import duckdb

from db import DB_PATH

REPO_ROOT = Path(__file__).resolve().parent.parent
COUNTY_PARQUET = REPO_ROOT / "data" / "county_level_birdweather.parquet"
PUC_ENVIRONMENT_CSV = REPO_ROOT / "data" / "puc_environment_hourly.csv"
OUTPUT_PATH = REPO_ROOT / "docs" / "data" / "dashboard.json"

# Feeder sites: raw_data source_sheet -> display metadata
SITES = {
    "jacksonville_fl_32259": {"name": "Jacksonville, FL", "tz": "America/New_York"},
    "essex_fells_nj_07021": {"name": "Essex Fells, NJ", "tz": "America/New_York"},
    "southampton_uk": {"name": "Southampton, UK", "tz": "Europe/London"},
}
# Auburn only exists as daily summaries
SUMMARY_ONLY_SITES = {
    "Auburn, AL 36830 Daily Sum": ("auburn_al_36830", "Auburn, AL"),
}

# BirdWeather PUC stations at the study sites
STATIONS = {
    "21974": {"name": "Jacksonville", "site": "jacksonville_fl_32259", "tz": "America/New_York"},
    "18618": {"name": "Essex Fells", "site": "essex_fells_nj_07021", "tz": "America/New_York"},
}

# County-level BirdWeather (all stations in the county bounding box)
COUNTIES = {
    "duval_fl": {"name": "Duval County, FL", "site": "jacksonville_fl_32259", "tz": "America/New_York"},
    "st_johns_fl": {"name": "St. Johns County, FL", "site": "jacksonville_fl_32259", "tz": "America/New_York"},
    "essex_nj": {"name": "Essex County, NJ", "site": "essex_fells_nj_07021", "tz": "America/New_York"},
}

# BirdCast regions: region_code -> display name, linked site
BIRDCAST_REGIONS = {
    "US-FL-031": {"name": "Duval County, FL", "site": "jacksonville_fl_32259"},
    "US-NJ-013": {"name": "Essex County, NJ", "site": "essex_fells_nj_07021"},
    "US-AL-081": {"name": "Lee County, AL", "site": "auburn_al_36830"},
    "US-CO-013": {"name": "Boulder County, CO", "site": None},
    "US-CA-013": {"name": "Contra Costa County, CA", "site": None},
}

PHASE_LOCATIONS = {
    "Jacksonville, FL": "jacksonville_fl_32259",
    "Essex Fells, NJ": "essex_fells_nj_07021",
    "Southampton, UK": "southampton_uk",
    "Auburn, AL": "auburn_al_36830",
}

# Spelling variants seen in the hand-entered feeder sheets
SPECIES_ALIASES = {
    "caroline chickadee": "Carolina Chickadee",
    "red-bellied woodpecker": "Red-bellied Woodpecker",
}

NOT_A_VISIT = {"", "none", "nan", "null"}


def clean_species(name):
    if name is None:
        return None
    name = re.sub(r"\s+", " ", str(name)).strip()
    if name.lower() in NOT_A_VISIT:
        return None
    return SPECIES_ALIASES.get(name.lower(), name)


def export_feeder(con):
    """Visits per site, day, and species; visits per site, day, and hour."""
    rows = con.execute(
        """
        SELECT source_sheet, Date, Bird, Time
        FROM raw_data
        WHERE source_sheet IN (SELECT unnest(?))
        """,
        [list(SITES)],
    ).fetchall()

    daily = {}
    hourly = {}
    for site, day, bird, time in rows:
        bird = clean_species(bird)
        if bird is None or not day:
            continue
        key = (site, day[:10], bird)
        daily[key] = daily.get(key, 0) + 1
        try:
            hour = int(str(time)[:2])
        except (TypeError, ValueError):
            continue
        hkey = (site, day[:10], hour)
        hourly[hkey] = hourly.get(hkey, 0) + 1

    for sheet, (site, _name) in SUMMARY_ONLY_SITES.items():
        for day, bird, visits in con.execute(
            'SELECT Date, Bird, "Feeder Visits" FROM daily_summaries WHERE source_sheet = ?',
            [sheet],
        ).fetchall():
            bird = clean_species(bird)
            try:
                visits = int(float(visits))
            except (TypeError, ValueError):
                continue
            if bird is None or visits <= 0 or not day:
                continue
            key = (site, day[:10], bird)
            daily[key] = daily.get(key, 0) + visits

    return (
        [[s, d, b, n] for (s, d, b), n in sorted(daily.items())],
        [[s, d, h, n] for (s, d, h), n in sorted(hourly.items())],
    )


def export_station_puc(con):
    """Detections per station per local day, and per-species stats."""
    daily, species = [], []
    for station_id, meta in STATIONS.items():
        local = f"timezone('{meta['tz']}', CAST(\"timestamp\" AS TIMESTAMPTZ))"
        daily += [
            [station_id, d, n, k]
            for d, n, k in con.execute(
                f"""
                SELECT strftime({local}, '%Y-%m-%d') AS day,
                       count(*), count(DISTINCT species_common)
                FROM study_site_puc_data
                WHERE station_id = ?
                GROUP BY 1 ORDER BY 1
                """,
                [station_id],
            ).fetchall()[:-1]  # the last day is still being fetched
        ]
        species += [
            [station_id, sp, sci, first, last, total, d7, d30]
            for sp, sci, first, last, total, d7, d30 in con.execute(
                f"""
                WITH d AS (
                    SELECT species_common AS sp, species_scientific AS sci,
                           CAST({local} AS DATE) AS day
                    FROM study_site_puc_data
                    WHERE station_id = ? AND species_common IS NOT NULL
                ), latest AS (SELECT max(day) AS m FROM d)
                SELECT sp, any_value(sci),
                       strftime(min(day), '%Y-%m-%d'), strftime(max(day), '%Y-%m-%d'),
                       count(*),
                       count(*) FILTER (WHERE day > (SELECT m FROM latest) - 7),
                       count(*) FILTER (WHERE day > (SELECT m FROM latest) - 30)
                FROM d GROUP BY sp ORDER BY 5 DESC
                """,
                [station_id],
            ).fetchall()
        ]
    return daily, species


def export_county_puc(con):
    """Detections per county per local day (empty if the parquet is missing)."""
    if not COUNTY_PARQUET.exists():
        print(f"County parquet not found at {COUNTY_PARQUET}; skipping county PUC")
        return []
    out = []
    for county, meta in COUNTIES.items():
        out += [
            [county, d, n, k]
            for d, n, k in con.execute(
                f"""
                SELECT strftime(timezone('{meta['tz']}', "timestamp"), '%Y-%m-%d') AS day,
                       count(*), count(DISTINCT species_common)
                FROM read_parquet(?)
                WHERE county = ?
                GROUP BY 1 ORDER BY 1
                """,
                [str(COUNTY_PARQUET), county],
            ).fetchall()[:-1]  # the last day is still being fetched
        ]
    return out


def birdcast_night(scrape_timestamp, migration_date):
    """
    Resolve "Wednesday night, Sep 9" to an ISO date using the scrape year.

    BirdCast omits the year, so take it from the scrape and step back a year
    when the night would otherwise land after the scrape (a January scrape of
    a December night).
    """
    match = re.search(r"([A-Z][a-z]{2}) (\d{1,2})\s*$", migration_date or "")
    if not match or not scrape_timestamp:
        return None
    scraped = datetime.fromisoformat(scrape_timestamp).date()
    night = datetime.strptime(f"{match.group(1)} {match.group(2)} {scraped.year}", "%b %d %Y").date()
    if night > scraped + timedelta(days=1):
        night = night.replace(year=night.year - 1)
    return night.isoformat()


def export_migration(con):
    """Birds crossing each BirdCast region per night."""
    nights = {}
    for code, scraped, mdate, total in con.execute(
        "SELECT region_code, scrape_timestamp, migration_date, total_birds FROM birdcast_data"
    ).fetchall():
        if code not in BIRDCAST_REGIONS:
            continue
        night = birdcast_night(scraped, mdate)
        try:
            total = int(float(total))
        except (TypeError, ValueError):
            continue
        if night:
            # Later scrapes of the same night win
            nights[(code, night)] = (scraped, total)
    return [[c, n, t] for (c, n), (_s, t) in sorted(nights.items())]


def export_phases(con):
    out = []
    for started, desc, loc, ratio in con.execute(
        "SELECT DateChangeStarted, DescriptionOfChange, LocationOfChange, SeedRatio FROM phase_changes"
    ).fetchall():
        site = PHASE_LOCATIONS.get((loc or "").strip())
        if site and started:
            out.append([site, str(started)[:10], desc, ratio])
    return sorted(out, key=lambda r: (r[0], r[1]))


def export_weather(con):
    """Daily weather per site from the hourly OpenWeather / Open-Meteo record."""
    rows = con.execute(
        """
        SELECT location, left(observed_dt_local, 10) AS day,
               min(TRY_CAST(temp AS DOUBLE)), avg(TRY_CAST(temp AS DOUBLE)), max(TRY_CAST(temp AS DOUBLE)),
               sum(coalesce(TRY_CAST(rain_1h_mm AS DOUBLE), 0)),
               avg(TRY_CAST(wind_speed AS DOUBLE)), max(TRY_CAST(wind_gust AS DOUBLE)),
               avg(TRY_CAST(humidity AS DOUBLE)), avg(TRY_CAST(clouds AS DOUBLE))
        FROM hourly_weather
        GROUP BY 1, 2 HAVING count(*) >= 20  -- skip partial days
        ORDER BY 1, 2
        """
    ).fetchall()
    out = []
    for loc, day, *values in rows:
        site = PHASE_LOCATIONS.get(loc)
        if site:
            out.append([site, day, *[None if v is None else round(v, 2) for v in values]])
    return out


def export_puc_environment(con):
    """Daily summaries of the PUC's on-board sensors (empty if not fetched yet)."""
    if not PUC_ENVIRONMENT_CSV.exists():
        print(f"PUC environment CSV not found at {PUC_ENVIRONMENT_CSV}; skipping")
        return []
    rows = con.execute(
        """
        WITH h AS (
            SELECT *, left(hour_local, 10) AS day, CAST(substr(hour_local, 12, 2) AS INTEGER) AS hr
            -- Keep hour_local as text: parsing it would shift hours to UTC dates
            FROM read_csv(?, header = true, types = {'station_id': 'VARCHAR', 'hour_local': 'VARCHAR'})
        )
        -- The station often drops out overnight and restarts mid-morning, so
        -- each statistic needs only the hours it depends on: the low needs the
        -- pre-dawn hours, the high the afternoon, and daily means a full day.
        SELECT station_id, day,
               CASE WHEN count(*) FILTER (WHERE hr BETWEEN 2 AND 7) >= 5 THEN min(temperature_c) END,
               CASE WHEN count(*) >= 20 THEN avg(temperature_c) END,
               CASE WHEN count(*) FILTER (WHERE hr BETWEEN 12 AND 16) >= 4 THEN max(temperature_c) END,
               CASE WHEN count(*) >= 20 THEN avg(humidity_pct) END,
               CASE WHEN count(*) >= 20 THEN avg(pressure_hpa) END,
               CASE WHEN count(*) >= 20 THEN avg(aqi) END,
               CASE WHEN count(*) >= 20 THEN avg(sound_pressure_db) END,
               count(*)
        FROM h
        GROUP BY 1, 2
        ORDER BY 1, 2
        """,
        [str(PUC_ENVIRONMENT_CSV)],
    ).fetchall()
    return [[sid, day, *[None if v is None else round(v, 2) for v in values]] for sid, day, *values in rows]


def last_dates(rows, key_idx, date_idx):
    latest = {}
    for r in rows:
        k, d = r[key_idx], r[date_idx]
        if k not in latest or d > latest[k]:
            latest[k] = d
    return latest


def build_freshness(feeder_daily, station_daily, county_daily, migration, weather, environment):
    """Last date per source, so the page can show what has stopped updating."""
    sources = []
    feeder_last = last_dates(feeder_daily, 0, 1)
    for site, meta in SITES.items():
        sources.append({"group": "Feeder visits", "name": meta["name"], "site": site,
                        "last": feeder_last.get(site)})
    station_last = last_dates(station_daily, 0, 1)
    for sid, meta in STATIONS.items():
        sources.append({"group": "PUC station", "name": meta["name"], "site": meta["site"],
                        "last": station_last.get(sid)})
    county_last = last_dates(county_daily, 0, 1)
    for county, meta in COUNTIES.items():
        sources.append({"group": "PUC county", "name": meta["name"], "site": meta["site"],
                        "last": county_last.get(county)})
    migration_last = last_dates(migration, 0, 1)
    for code, meta in BIRDCAST_REGIONS.items():
        if meta["site"]:
            sources.append({"group": "BirdCast migration", "name": meta["name"], "site": meta["site"],
                            "last": migration_last.get(code)})
    environment_last = last_dates(environment, 0, 1)
    for sid, meta in STATIONS.items():
        sources.append({"group": "Backyard sensors", "name": meta["name"], "site": meta["site"],
                        "last": environment_last.get(sid)})
    weather_last = last_dates(weather, 0, 1)
    for site, last in weather_last.items():
        sources.append({"group": "Weather", "name": "Open-Meteo", "site": site, "last": last})
    return sources


def main():
    with duckdb.connect(str(DB_PATH), read_only=True) as con:
        feeder_daily, feeder_hourly = export_feeder(con)
        station_daily, station_species = export_station_puc(con)
        county_daily = export_county_puc(con)
        migration = export_migration(con)
        phases = export_phases(con)
        weather = export_weather(con)
        environment = export_puc_environment(con)
    freshness = build_freshness(feeder_daily, station_daily, county_daily, migration, weather, environment)

    sites = {k: {"name": v["name"]} for k, v in SITES.items()}
    sites.update({key: {"name": name} for key, name in SUMMARY_ONLY_SITES.values()})

    payload = {
        "generated": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "sites": sites,
        "stations": {k: {"name": v["name"], "site": v["site"]} for k, v in STATIONS.items()},
        "counties": {k: {"name": v["name"], "site": v["site"]} for k, v in COUNTIES.items()},
        "birdcastRegions": BIRDCAST_REGIONS,
        "freshness": freshness,
        # Row arrays keep the file small; column order documented per key
        "feederDaily": {"cols": ["site", "date", "species", "visits"], "rows": feeder_daily},
        "feederHourly": {"cols": ["site", "date", "hour", "visits"], "rows": feeder_hourly},
        "stationDaily": {"cols": ["station", "date", "detections", "species"], "rows": station_daily},
        "stationSpecies": {
            "cols": ["station", "species", "scientific", "first", "last", "total", "last7", "last30"],
            "rows": station_species,
        },
        "countyDaily": {"cols": ["county", "date", "detections", "species"], "rows": county_daily},
        "migration": {"cols": ["region", "night", "birds"], "rows": migration},
        "phases": {"cols": ["site", "start", "description", "ratio"], "rows": phases},
        "weatherDaily": {
            "cols": ["site", "date", "tempMin", "tempMean", "tempMax", "rainMm", "windMean", "gustMax",
                     "humidity", "clouds"],
            "rows": weather,
        },
        "sensorDaily": {
            "cols": ["station", "date", "tempMin", "tempMean", "tempMax", "humidity", "pressure", "aqi",
                     "soundDb", "hours"],
            "rows": environment,
        },
    }

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(json.dumps(payload, separators=(",", ":"), default=str))
    size_kb = OUTPUT_PATH.stat().st_size / 1024
    print(f"Dashboard data written to {OUTPUT_PATH} ({size_kb:,.0f} KB)")
    for s in freshness:
        print(f"  {s['group']:<20} {s['name']:<26} last: {s['last']}")


if __name__ == "__main__":
    main()
