#!/usr/bin/env python3
"""
Compact the DuckDB file before it is uploaded to the `data` release.

DuckDB does not shrink a database file when rows are deleted, so DELETE-and-
reload writes leave dead blocks behind and the file grows over time (a daily
full reload of study_site_puc_data took it past the limit in October 2026).
GitHub release assets are capped at 2 GiB, and `gh release upload --clobber`
deletes the old asset before uploading the new one, so an oversized file
wipes the release copy.

This script rewrites the database into a fresh file with COPY FROM DATABASE,
swaps it into place, and exits non-zero if the result is still too large to
upload.

Usage:
  python scripts_notebooks/compact_duckdb.py
"""

import sys

import duckdb

from db import DB_PATH

# GitHub release asset limit is 2 GiB; leave headroom
MAX_UPLOAD_BYTES = 2 * 1024**3 - 64 * 1024**2


def compact(db_path=DB_PATH):
    tmp_path = db_path.with_name(db_path.stem + ".compact.duckdb")
    tmp_path.unlink(missing_ok=True)

    before = db_path.stat().st_size
    con = duckdb.connect()
    try:
        con.execute(f"ATTACH '{db_path}' AS src (READ_ONLY)")
        con.execute(f"ATTACH '{tmp_path}' AS dst")
        con.execute("COPY FROM DATABASE src TO dst")
    finally:
        con.close()

    tmp_path.replace(db_path)
    after = db_path.stat().st_size
    print(f"Compacted {db_path.name}: {before / 1024**2:,.1f} MB -> {after / 1024**2:,.1f} MB")
    return after


def main():
    if not DB_PATH.exists():
        print(f"No DuckDB file at {DB_PATH}; nothing to compact")
        return 0

    size = compact()
    if size >= MAX_UPLOAD_BYTES:
        print(
            f"ERROR: {DB_PATH.name} is {size / 1024**3:.2f} GiB after compaction, "
            "over the GitHub release asset limit. Not safe to upload."
        )
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
