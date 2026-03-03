#!/usr/bin/env python3
"""
Shared DuckDB database module for backyard-ecology.

Provides:
- DB_PATH: resolved path to data/backyard_ecology.duckdb
- get_connection(): context manager with transaction handling
- init_schema(): idempotent CREATE TABLE IF NOT EXISTS for all tables
"""

import logging
from contextlib import contextmanager
from pathlib import Path

import duckdb

logger = logging.getLogger(__name__)

# Resolve DB path relative to repo root
_REPO_ROOT = Path(__file__).resolve().parent.parent
DB_PATH = _REPO_ROOT / "data" / "backyard_ecology.duckdb"


@contextmanager
def get_connection(read_only=False):
    """
    Context manager that yields a DuckDB connection.

    Wraps the body in a transaction (BEGIN / COMMIT / ROLLBACK).
    Read-only connections skip transaction management.
    """
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(DB_PATH), read_only=read_only)
    if read_only:
        try:
            yield con
        finally:
            con.close()
    else:
        try:
            con.begin()
            yield con
            con.commit()
        except Exception:
            con.rollback()
            raise
        finally:
            con.close()


def init_schema(con):
    """
    Create all tables if they don't already exist. Idempotent.
    """

    con.execute("""
        CREATE TABLE IF NOT EXISTS hourly_weather (
            location            VARCHAR,
            lat                 DOUBLE,
            lon                 DOUBLE,
            requested_dt_utc    VARCHAR,
            observed_dt_utc     VARCHAR,
            observed_dt_local   VARCHAR,
            timezone            VARCHAR,
            timezone_offset_seconds INTEGER,
            sunrise_utc         VARCHAR,
            sunrise_local       VARCHAR,
            sunset_utc          VARCHAR,
            sunset_local        VARCHAR,
            temp                DOUBLE,
            feels_like          DOUBLE,
            pressure            DOUBLE,
            humidity            DOUBLE,
            dew_point           DOUBLE,
            clouds              DOUBLE,
            uvi                 DOUBLE,
            visibility          DOUBLE,
            wind_speed          DOUBLE,
            wind_gust           DOUBLE,
            wind_deg            DOUBLE,
            weather_id          INTEGER,
            weather_main        VARCHAR,
            weather_description VARCHAR,
            rain_1h_mm          DOUBLE,
            snow_1h_mm          DOUBLE,
            PRIMARY KEY (location, requested_dt_utc)
        )
    """)

    con.execute("""
        CREATE TABLE IF NOT EXISTS sunrise_sunset (
            location                VARCHAR,
            lat                     DOUBLE,
            lon                     DOUBLE,
            date_local              VARCHAR,
            timezone                VARCHAR,
            timezone_offset_seconds INTEGER,
            sunrise_local           VARCHAR,
            sunset_local            VARCHAR,
            sunrise_utc             VARCHAR,
            sunset_utc              VARCHAR,
            day_length_minutes      DOUBLE,
            PRIMARY KEY (location, date_local)
        )
    """)

    con.execute("""
        CREATE TABLE IF NOT EXISTS raw_data (
            "Date"          VARCHAR,
            "Bird"          VARCHAR,
            "Time"          VARCHAR,
            "LeftPecks"     VARCHAR,
            "RightPecks"    VARCHAR,
            "LeftSeed"      VARCHAR,
            "RightSeed"     VARCHAR,
            source_sheet    VARCHAR,
            "Notes"         VARCHAR,
            "CoolDown"      VARCHAR,
            PRIMARY KEY (source_sheet, "Date", "Bird", "Time")
        )
    """)

    con.execute("""
        CREATE TABLE IF NOT EXISTS daily_summaries (
            "Date"          VARCHAR,
            source_sheet    VARCHAR,
            "Bird"          VARCHAR,
            "Feeder Visits" VARCHAR,
            PRIMARY KEY (source_sheet, "Date", "Bird")
        )
    """)

    con.execute("""
        CREATE TABLE IF NOT EXISTS phase_changes (
            "DateChangeStarted"     VARCHAR,
            "DescriptionOfChange"   VARCHAR,
            "LocationOfChange"      VARCHAR,
            PRIMARY KEY ("DateChangeStarted", "LocationOfChange")
        )
    """)

    # Base columns for study_site_puc_data — dynamic sensor columns
    # are added at runtime via ALTER TABLE ADD COLUMN IF NOT EXISTS.
    # Note: certainty can be a string label (e.g. "almost_certain") or numeric.
    con.execute("""
        CREATE TABLE IF NOT EXISTS study_site_puc_data (
            id                  VARCHAR PRIMARY KEY,
            "timestamp"         VARCHAR,
            certainty           VARCHAR,
            confidence          VARCHAR,
            probability         VARCHAR,
            score               VARCHAR,
            lat                 VARCHAR,
            lon                 VARCHAR,
            species_common      VARCHAR,
            species_scientific  VARCHAR,
            species_ebird       VARCHAR,
            station_id          VARCHAR,
            station_name        VARCHAR,
            sound_url           VARCHAR,
            sound_start         VARCHAR,
            sound_end           VARCHAR
        )
    """)

    con.execute("""
        CREATE TABLE IF NOT EXISTS county_birdweather (
            id                  VARCHAR PRIMARY KEY,
            "timestamp"         VARCHAR,
            certainty           VARCHAR,
            confidence          VARCHAR,
            probability         VARCHAR,
            score               VARCHAR,
            lat                 VARCHAR,
            lon                 VARCHAR,
            species_common      VARCHAR,
            species_scientific  VARCHAR,
            species_ebird       VARCHAR,
            station_id          VARCHAR,
            station_name        VARCHAR,
            sound_url           VARCHAR,
            sound_start         VARCHAR,
            sound_end           VARCHAR,
            county              VARCHAR
        )
    """)

    # BirdCast tables share the same schema.
    # All columns are VARCHAR to handle dirty scraped data; analytics casts as needed.
    _birdcast_ddl = """
        CREATE TABLE IF NOT EXISTS {table} (
            scrape_timestamp    VARCHAR,
            url                 VARCHAR,
            region_code         VARCHAR,
            region_name         VARCHAR,
            total_birds         VARCHAR,
            peak_birds_in_flight VARCHAR,
            flight_direction    VARCHAR,
            flight_speed_mph    VARCHAR,
            flight_altitude_ft  VARCHAR,
            migration_start_raw VARCHAR,
            migration_start_utc VARCHAR,
            migration_end_raw   VARCHAR,
            migration_end_utc   VARCHAR,
            migration_date      VARCHAR,
            date_key            VARCHAR,
            PRIMARY KEY (region_code, date_key)
        )
    """

    for table_name in ("birdcast_data", "atlantic_flyway",
                       "mississippi_flyway", "pacific_flyway"):
        con.execute(_birdcast_ddl.format(table=table_name))

    logger.info("Schema initialised (all tables created if not present)")
