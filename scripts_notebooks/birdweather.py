#!/usr/bin/env python3
"""
birdweather_counties.py
Fetch all BirdWeather detections for Duval County, FL and St. Johns County, FL.

Usage:
  python birdweather_counties.py
  # optional date window
  python birdweather_counties.py --from 2018-01-01 --to 2025-10-22
"""

import csv
import time
import argparse
from datetime import date
import requests

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

def fetch_all_for_bbox(ne, sw, period=None, page_size=500, pause=0.25, max_retries=3):
    """
    Pulls all detections for a bbox (ne/sw are dicts with lat/lon) and optional period.
    Returns a list of detection nodes (dicts).
    """
    headers = {"Content-Type": "application/json"}
    all_nodes = []
    after = None

    # quick shape check
    for name, pt in (("ne", ne), ("sw", sw)):
        if not (isinstance(pt, dict) and "lat" in pt and "lon" in pt):
            raise ValueError(f"{name} must be a dict with 'lat' and 'lon' keys")

    while True:
        variables = {
            "first": page_size,
            "after": after,
            "period": period,
            "ne": ne,
            "sw": sw,
        }

        # simple retry loop
        for attempt in range(1, max_retries + 1):
            try:
                resp = requests.post(
                    GRAPHQL_URL,
                    json={"query": DETECTIONS_QUERY, "variables": variables},
                    timeout=60,
                )
                resp.raise_for_status()
                data = resp.json()
                if "errors" in data:
                    raise RuntimeError(f"GraphQL errors: {data['errors']}")
                break
            except Exception as e:
                if attempt == max_retries:
                    raise
                time.sleep(pause * attempt)  # backoff and retry

        payload = data["data"]["detections"]
        nodes = payload.get("nodes") or []
        all_nodes.extend(nodes)

        page_info = payload["pageInfo"]
        if not page_info["hasNextPage"]:
            break
        after = page_info["endCursor"]
        time.sleep(pause)

    return all_nodes

def flatten(node):
    """Flatten nested detection into a CSV-friendly dict."""
    sp = node.get("species") or {}
    st = node.get("station") or {}
    coords = node.get("coords") or {}
    sc = node.get("soundscape") or {}
    return {
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

def write_csv(items, path):
    rows = [flatten(x) for x in items]
    # Build header from all keys so we don't miss fields if some rows are sparse
    fields = sorted({k for r in rows for k in r.keys()}) if rows else list(flatten({}).keys())
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)

def parse_args():
    ap = argparse.ArgumentParser(description="Download BirdWeather detections for Duval and St Johns counties (FL).")
    ap.add_argument("--from", dest="from_date", default="2018-01-01",
                    help="Start date (YYYY-MM-DD). Default: 2018-01-01")
    ap.add_argument("--to", dest="to_date", default=date.today().isoformat(),
                    help="End date (YYYY-MM-DD). Default: today")
    ap.add_argument("--page-size", type=int, default=500, help="Detections per page. Default: 500")
    return ap.parse_args()

def main():
    args = parse_args()
    period = {"from": args.from_date, "to": args.to_date}

    for key, bbox in COUNTY_BBOXES.items():
        print(f"Fetching detections for {key} ({period['from']} → {period['to']}) ...")
        nodes = fetch_all_for_bbox(bbox["ne"], bbox["sw"], period=period, page_size=args.page_size)
        print(f"  Retrieved {len(nodes)} records")
        out_path = f"birdweather_{key}.csv"
        write_csv(nodes, out_path)
        print(f"  Wrote {out_path}")

if __name__ == "__main__":
    main()
