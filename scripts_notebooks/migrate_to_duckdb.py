#!/usr/bin/env python3
"""
One-time migration script: seed DuckDB from existing flat files.

Usage:
  python scripts_notebooks/migrate_to_duckdb.py

After running, upload the DB as a GitHub Release asset:
  gh release create data --title "DuckDB data store" \
    --notes "Pipeline database" data/backyard_ecology.duckdb
"""

import sys
from pathlib import Path

import duckdb
import pandas as pd

# Ensure scripts_notebooks is importable
sys.path.insert(0, str(Path(__file__).resolve().parent))
from db import DB_PATH, get_connection, init_schema

REPO_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = REPO_ROOT / "data"


def _derive_date_key(df):
    """Add a date_key column: prefer migration_date, fallback to scrape_timestamp date."""
    if "migration_date" in df.columns and df["migration_date"].notna().any():
        df["date_key"] = df["migration_date"].fillna("")
    else:
        df["date_key"] = ""

    # Fill blanks from scrape_timestamp
    needs_fill = df["date_key"] == ""
    if needs_fill.any() and "scrape_timestamp" in df.columns:
        ts = pd.to_datetime(df.loc[needs_fill, "scrape_timestamp"], errors="coerce", utc=True)
        df.loc[needs_fill, "date_key"] = ts.dt.date.astype(str)

    return df


def _get_pk_columns(con, table_name):
    """Get primary key columns for a table."""
    # Query DuckDB constraints to find PK columns
    rows = con.execute(f"""
        SELECT column_name
        FROM information_schema.key_column_usage
        WHERE table_name = '{table_name}'
        ORDER BY ordinal_position
    """).fetchall()
    return [r[0] for r in rows]


def load_csv(path, table_name, con):
    """Load a CSV file into a DuckDB table using INSERT OR REPLACE."""
    if not path.exists():
        print(f"  SKIP {path.name} (not found)")
        return 0

    df = pd.read_csv(path, dtype=str)
    if df.empty:
        print(f"  SKIP {path.name} (empty)")
        return 0

    # Replace NaN with None for DuckDB
    df = df.where(df.notna(), None)

    # Drop rows where primary key columns are NULL
    pk_cols = _get_pk_columns(con, table_name)
    if pk_cols:
        before = len(df)
        df = df.dropna(subset=pk_cols)
        dropped = before - len(df)
        if dropped:
            print(f"    (dropped {dropped} rows with NULL in PK columns {pk_cols})")

    _insert_by_name(con, table_name, df)
    count = con.execute(f"SELECT COUNT(*) FROM {table_name}").fetchone()[0]
    print(f"  {path.name} -> {table_name}: {count:,} rows")
    return count


def load_parquet(path, table_name, con, add_date_key=False):
    """Load a parquet file into a DuckDB table using INSERT OR REPLACE."""
    if not path.exists():
        print(f"  SKIP {path.name} (not found)")
        return 0

    df = pd.read_parquet(path)
    if df.empty:
        print(f"  SKIP {path.name} (empty)")
        return 0

    # Stringify all columns for consistent VARCHAR storage
    for col in df.columns:
        if pd.api.types.is_datetime64_any_dtype(df[col]):
            df[col] = df[col].dt.strftime("%Y-%m-%dT%H:%M:%S+00:00")
        else:
            df[col] = df[col].astype(str)
            df[col] = df[col].replace({"nan": None, "None": None, "NaT": None, "<NA>": None})

    if add_date_key:
        df = _derive_date_key(df)

    # Replace NaN/NaT with None
    df = df.where(df.notna(), None)

    # Drop rows where primary key columns are NULL
    pk_cols = _get_pk_columns(con, table_name)
    if pk_cols:
        before = len(df)
        df = df.dropna(subset=pk_cols)
        dropped = before - len(df)
        if dropped:
            print(f"    (dropped {dropped} rows with NULL in PK columns {pk_cols})")

    _insert_by_name(con, table_name, df, "INSERT OR REPLACE")
    count = con.execute(f"SELECT COUNT(*) FROM {table_name}").fetchone()[0]
    print(f"  {path.name} -> {table_name}: {count:,} rows")
    return count


def _insert_by_name(con, table_name, df, verb="INSERT OR REPLACE"):
    """
    Insert DataFrame into DuckDB table matching columns by name, not position.
    """
    cols = ", ".join(f'"{c}"' for c in df.columns)
    con.execute(f"{verb} INTO {table_name} ({cols}) SELECT {cols} FROM df")


def load_study_site_puc(path, con):
    """
    Load study_site_puc_data.csv, handling dynamic sensor columns
    via ALTER TABLE ADD COLUMN IF NOT EXISTS.
    """
    if not path.exists():
        print(f"  SKIP {path.name} (not found)")
        return 0

    df = pd.read_csv(path, dtype=str)
    if df.empty:
        print(f"  SKIP {path.name} (empty)")
        return 0

    df = df.where(df.notna(), None)

    # Get existing table columns
    existing_cols = {
        row[0]
        for row in con.execute(
            "SELECT column_name FROM information_schema.columns WHERE table_name = 'study_site_puc_data'"
        ).fetchall()
    }

    # Add any missing dynamic columns
    for col in df.columns:
        if col not in existing_cols:
            con.execute(f'ALTER TABLE study_site_puc_data ADD COLUMN IF NOT EXISTS "{col}" VARCHAR')

    _insert_by_name(con, "study_site_puc_data", df, "INSERT OR IGNORE")
    count = con.execute("SELECT COUNT(*) FROM study_site_puc_data").fetchone()[0]
    print(f"  {path.name} -> study_site_puc_data: {count:,} rows")
    return count


def main():
    print(f"Creating/opening DuckDB at {DB_PATH}\n")

    # Delete existing DB if present (fresh migration)
    if DB_PATH.exists():
        DB_PATH.unlink()
        print("  Removed existing DB for fresh migration\n")

    with get_connection() as con:
        init_schema(con)
        print("Schema initialised.\n")

        print("Loading flat files:")
        load_csv(DATA_DIR / "hourly_weather.csv", "hourly_weather", con)
        load_csv(DATA_DIR / "sunrise_sunset.csv", "sunrise_sunset", con)
        load_csv(DATA_DIR / "raw_data_all_locations.csv", "raw_data", con)
        load_csv(DATA_DIR / "daily_summaries_all_locations.csv", "daily_summaries", con)
        load_csv(DATA_DIR / "phase_change_data.csv", "phase_changes", con)
        load_study_site_puc(DATA_DIR / "study_site_puc_data.csv", con)
        load_parquet(DATA_DIR / "county_level_birdweather.parquet", "county_birdweather", con)
        load_parquet(DATA_DIR / "birdcast_data.parquet", "birdcast_data", con, add_date_key=True)
        load_parquet(DATA_DIR / "atlantic_flyway_corridor.parquet", "atlantic_flyway", con, add_date_key=True)
        load_parquet(DATA_DIR / "mississippi_flyway_corridor.parquet", "mississippi_flyway", con, add_date_key=True)
        load_parquet(DATA_DIR / "pacific_flyway_corridor.parquet", "pacific_flyway", con, add_date_key=True)

    # Print final row counts
    print("\nFinal row counts:")
    with get_connection(read_only=True) as con:
        tables = [
            "hourly_weather", "sunrise_sunset", "raw_data", "daily_summaries",
            "phase_changes", "study_site_puc_data", "county_birdweather",
            "birdcast_data", "atlantic_flyway", "mississippi_flyway", "pacific_flyway",
        ]
        for t in tables:
            count = con.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
            print(f"  {t}: {count:,}")

    print(f"\nDone. DB file: {DB_PATH}")
    print(f"Size: {DB_PATH.stat().st_size / 1024 / 1024:.1f} MB")


if __name__ == "__main__":
    main()
