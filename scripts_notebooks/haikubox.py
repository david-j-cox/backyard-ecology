# --- requirements: requests, pandas, numpy, scipy, scikit-learn ---
# pip install requests pandas numpy scipy scikit-learn
# (optional) pip install tqdm

import sys, math, time, itertools, datetime as dt, json
import pandas as pd
import numpy as np
from collections import defaultdict
from scipy.stats import linregress
import requests
from typing import Dict, Any, List, Tuple

try:
    from tqdm import tqdm
    HAS_TQDM = True
except Exception:
    HAS_TQDM = False

# -----------------------
# CONFIG
# -----------------------
GRAPHQL_URL = "https://app.birdweather.com/graphql"

# Florida-wide bbox (WGS84). Slightly conservative to avoid spillover.
# South 24.396, North 31.000, West -87.635, East -80.031
BBOX = {
    "ne": {"lat": 31.000, "lon": -80.031},
    "sw": {"lat": 24.396, "lon": -87.635},
}

# Optionally keep only stations whose 'state' is Florida/FL
FILTER_TO_FLORIDA_STATE = True

# Date window (inclusive start, up to today by default)
START_DATE = "2017-01-01"
END_DATE = dt.date.today().isoformat()

# Station tiling + paging (to avoid 504s)
TILE_ROWS = 2
TILE_COLS = 3
STATION_PAGE_SIZE = 20  # smaller page sizes reduce payload size

# Alternative: Use even smaller tiles for problematic areas
SMALL_TILE_ROWS = 4
SMALL_TILE_COLS = 6

# Chunk size for station queries to daily counts
STATION_CHUNK = 50

# Gentle pacing to be kind to the API
PAUSE_BETWEEN_TILES_S = 1.0
PAUSE_BETWEEN_DAILY_CHUNKS_S = 0.35

# -----------------------
# Minimal progress helper
# -----------------------
class Progress:
    def __init__(self, use_tqdm: bool = HAS_TQDM):
        self.use_tqdm = use_tqdm
    def bar(self, total: int, desc: str):
        if self.use_tqdm:
            return tqdm(total=total, desc=desc, unit="step", leave=True)
        class _Bar:
            def __init__(self, total, desc):
                self.total = total; self.n = 0; self.desc = desc
                print(f"{desc} (0/{total})")
            def update(self, k=1):
                self.n += k; print(f"{self.desc} ({self.n}/{self.total})")
            def set_postfix(self, *args, **kwargs): pass
            def close(self): pass
        return _Bar(total, desc)
    def note(self, msg: str):
        ts = time.strftime("%H:%M:%S")
        print(f"[{ts}] {msg}")

progress = Progress()

# -----------------------
# Requests session (transport-level retries disabled; we handle app-level backoff)
# -----------------------
def make_session():
    from requests.adapters import HTTPAdapter
    try:
        from urllib3.util.retry import Retry
        retries = Retry(
            total=0,                 # app-level retries below
            backoff_factor=0,
            status_forcelist=(429, 500, 502, 503, 504),
            allowed_methods=frozenset(["POST"]),
            raise_on_status=False,
            respect_retry_after_header=True,
        )
        s = requests.Session()
        s.headers.update({"Accept-Encoding": "gzip, deflate", "Content-Type": "application/json"})
        s.mount("https://", HTTPAdapter(max_retries=retries))
        s.mount("http://", HTTPAdapter(max_retries=retries))
        return s
    except Exception:
        return requests.Session()

SESSION = make_session()

# -----------------------
# Resilient GraphQL helper with exponential backoff + jitter
# -----------------------
TRANSIENT_CODES = {429, 500, 502, 503, 504}
def gql(query: str, variables: Dict[str, Any], max_attempts: int = 15, base_sleep: float = 1.5) -> Dict[str, Any]:
    attempt = 0
    consecutive_504s = 0
    
    while True:
        attempt += 1
        try:
            r = SESSION.post(GRAPHQL_URL, json={"query": query, "variables": variables}, timeout=120)
            status = r.status_code
            
            if status == 200:
                out = r.json()
                if "errors" in out and out["errors"]:
                    # Query/schema errors should surface immediately
                    raise RuntimeError(json.dumps(out["errors"], indent=2))
                consecutive_504s = 0  # Reset counter on success
                return out["data"]
            
            if status == 504:
                consecutive_504s += 1
                if consecutive_504s >= 5:
                    progress.note(f"Too many consecutive 504s ({consecutive_504s}), backing off longer...")
                    time.sleep(30)  # Long backoff for persistent 504s
                    consecutive_504s = 0
            
            if status in TRANSIENT_CODES:
                raise requests.HTTPError(f"HTTP {status} from GraphQL")
            r.raise_for_status()
            
        except (requests.Timeout, requests.ConnectionError, requests.HTTPError) as e:
            if attempt >= max_attempts:
                progress.note(f"Max attempts ({max_attempts}) reached for GraphQL query")
                raise
            
            # Progressive backoff with longer sleeps for 504s
            if "504" in str(e):
                sleep_s = min(30, base_sleep * (3 ** (attempt - 1)) + (0.1 * np.random.random()))
            else:
                sleep_s = (base_sleep * (2 ** (attempt - 1))) + (0.05 * np.random.random())
            
            progress.note(f"Attempt {attempt}/{max_attempts} failed: {e}. Retrying in {sleep_s:.1f}s...")
            time.sleep(sleep_s)

# -----------------------
# Queries
# -----------------------
STATIONS_QUERY = """
query stations($first:Int,$after:String,$ne:InputLocation,$sw:InputLocation){
  stations(first:$first, after:$after, ne:$ne, sw:$sw){
    pageInfo{ endCursor hasNextPage }
    nodes{
      id
      name
      country
      state
      coords { lat lon }
      type
      timezone
      locationPrivacy
      earliestDetectionAt
      latestDetectionAt
    }
    totalCount
  }
}
"""

DAILY_COUNTS_QUERY = """
query dailyDetectionCounts($period: InputDuration, $stationIds: [ID!]) {
  dailyDetectionCounts(period: $period, stationIds: $stationIds){
    date
    total
    counts { speciesId count }
  }
}
"""

# -----------------------
# Utils
# -----------------------
def chunks(lst: List[Any], n: int):
    for i in range(0, len(lst), n):
        yield lst[i:i+n]

def tile_bbox(ne: Dict[str, float], sw: Dict[str, float], rows: int, cols: int):
    """Yield (ne, sw) sub-bboxes covering the input bbox in row-major order."""
    lat_min, lat_max = sw["lat"], ne["lat"]
    lon_min, lon_max = sw["lon"], ne["lon"]
    dlat = (lat_max - lat_min) / rows
    dlon = (lon_max - lon_min) / cols
    for r in range(rows):
        for c in range(cols):
            sub_sw = {"lat": lat_min + r * dlat, "lon": lon_min + c * dlon}
            sub_ne = {"lat": lat_min + (r + 1) * dlat, "lon": lon_min + (c + 1) * dlon}
            yield sub_ne, sub_sw

# -----------------------
# 1) Discover stations in bbox via tiles (avoid 504s)
# -----------------------
def fetch_station_ids_simple(ne, sw, page_size=STATION_PAGE_SIZE):
    """Fallback function for smaller bounding boxes without tiling."""
    all_nodes = []
    all_ids = set()
    after = None
    page_i = 0
    
    progress.note(f"Discovering stations in single bbox (page size={page_size})...")
    
    while True:
        page_i += 1
        try:
            data = gql(STATIONS_QUERY, {"first": page_size, "after": after, "ne": ne, "sw": sw})
            nodes = data["stations"]["nodes"]
            if nodes:
                for n in nodes:
                    if n["id"] not in all_ids:
                        all_ids.add(n["id"])
                        all_nodes.append(n)
            pi = data["stations"]["pageInfo"]
            after = pi["endCursor"]
            if not pi["hasNextPage"]:
                break
            time.sleep(PAUSE_BETWEEN_TILES_S)
        except Exception as e:
            progress.note(f"Error on page {page_i}: {e}")
            if page_i > 3:  # Give up after 3 failed pages
                break
            time.sleep(5)
    
    df = pd.DataFrame(all_nodes)
    progress.note(f"Station discovery complete: {len(all_ids)} unique stations.")
    return list(all_ids), df

def fetch_station_ids_tiled(ne, sw, page_size=STATION_PAGE_SIZE, rows=TILE_ROWS, cols=TILE_COLS):
    all_nodes = []
    all_ids = set()
    tiles = list(tile_bbox(ne, sw, rows, cols))
    progress.note(f"Discovering public stations via {len(tiles)} tiles (page size={page_size})…")
    tile_bar = progress.bar(total=len(tiles), desc="Tiles")

    for ti, (t_ne, t_sw) in enumerate(tiles, start=1):
        after = None
        page_i = 0
        while True:
            page_i += 1
            data = gql(STATIONS_QUERY, {"first": page_size, "after": after, "ne": t_ne, "sw": t_sw})
            nodes = data["stations"]["nodes"]
            if nodes:
                for n in nodes:
                    if n["id"] not in all_ids:
                        all_ids.add(n["id"])
                        all_nodes.append(n)
            pi = data["stations"]["pageInfo"]
            after = pi["endCursor"]
            if not pi["hasNextPage"]:
                break
        if HAS_TQDM:
            tile_bar.update(1)
            tile_bar.set_postfix({"tile": f"{ti}/{len(tiles)}", "stations": len(all_ids)})
        else:
            tile_bar.update(1)
            progress.note(f"Tile {ti}/{len(tiles)} complete, unique stations so far: {len(all_ids)}")
        time.sleep(PAUSE_BETWEEN_TILES_S)

    tile_bar.close()
    df = pd.DataFrame(all_nodes)
    progress.note(f"Station discovery complete: {len(all_ids)} unique stations.")
    return list(all_ids), df

# -----------------------
# 2) Pull daily counts with progress + ETA
# -----------------------
def fetch_daily_counts(station_ids, start_date, end_date, chunk_size=STATION_CHUNK):
    daily_frames = []
    chunk_list = list(chunks(station_ids, chunk_size))
    if not chunk_list:
        return pd.DataFrame()
    bar = progress.bar(total=len(chunk_list), desc="Pulling dailyDetectionCounts")
    records_so_far = 0
    t0 = time.time()
    for i, chunk in enumerate(chunk_list, start=1):
        t_chunk_start = time.time()
        data = gql(DAILY_COUNTS_QUERY, {"period": {"from": start_date, "to": end_date}, "stationIds": chunk})
        rows = data["dailyDetectionCounts"]
        local_count = 0
        for r in rows:
            date = r["date"]
            total = r["total"]
            for c in r["counts"]:
                daily_frames.append({
                    "date": date,
                    "speciesId": c["speciesId"],
                    "count": c["count"],
                    "total": total
                })
                records_so_far += 1
                local_count += 1
        elapsed = time.time() - t0
        done = i
        remaining = len(chunk_list) - done
        avg_per_chunk = elapsed / max(done, 1)
        eta_sec = remaining * avg_per_chunk
        if HAS_TQDM:
            bar.update(1)
            bar.set_postfix({"chunk": f"{i}/{len(chunk_list)}", "rows": records_so_far, "eta": f"{int(eta_sec)}s"})
        else:
            bar.update(1)
            progress.note(f"Chunk {i}/{len(chunk_list)} (+{local_count} rows, {records_so_far} total). ETA ~{int(eta_sec)}s")
        dt_chunk = time.time() - t_chunk_start
        if dt_chunk < PAUSE_BETWEEN_DAILY_CHUNKS_S:
            time.sleep(PAUSE_BETWEEN_DAILY_CHUNKS_S - dt_chunk)
    bar.close()
    progress.note(f"Daily counts download complete: {records_so_far} rows in {time.time() - t0:.1f}s.")
    return pd.DataFrame(daily_frames)

# -----------------------
# 3) Compute metrics and save
# -----------------------
def compute_and_save_metrics(daily: pd.DataFrame):
    progress.note("Computing daily/weekly metrics…")
    daily["date"] = pd.to_datetime(daily["date"])
    daily["week"] = daily["date"].dt.to_period("W").apply(lambda r: r.start_time.date())
    daily["year"] = daily["date"].dt.year

    totals = daily.groupby("date", as_index=False)["total"].max().sort_values("date")
    cv_daily = (totals["total"].std(ddof=1) / totals["total"].mean()) if len(totals) > 1 else np.nan

    richness = daily.groupby("date")["speciesId"].nunique().rename("richness")
    day_species = daily.pivot_table(index="date", columns="speciesId",
                                    values="count", aggfunc="sum", fill_value=0)
    p = day_species.div(day_species.sum(axis=1), axis=0).replace(0, np.nan)
    shannon = (-(p * np.log(p)).sum(axis=1)).rename("shannon_H")

    metrics = pd.concat([totals.set_index("date"), richness, shannon], axis=1).reset_index()

    weekly_presence = (daily.groupby(["week", "speciesId"])["count"]
                       .sum().unstack(fill_value=0) > 0).astype(int)
    sorensen = []
    weeks_sorted = sorted(weekly_presence.index)
    for w_prev, w_curr in zip(weeks_sorted[:-1], weeks_sorted[1:]):
        a = weekly_presence.loc[w_prev]; b = weekly_presence.loc[w_curr]
        a_sum = a.sum(); b_sum = b.sum(); intersection = (a & b).sum()
        denom = (a_sum + b_sum)
        d_s = np.nan if denom == 0 else 1 - (2 * intersection / denom)
        sorensen.append({"week": w_curr, "sorensen_dissimilarity": d_s})
    beta_df = pd.DataFrame(sorensen)

    trend_rows = []
    for yr, sub in totals.groupby(totals["date"].dt.year):
        if len(sub) > 5:
            x = (sub["date"] - sub["date"].min()).dt.days.values
            y = sub["total"].values
            slope, intercept, r, p, se = linregress(x, y)
            trend_rows.append({"year": yr, "slope_det_per_day": slope, "r": r, "p": p})
    trend = pd.DataFrame(trend_rows)

    progress.note("Writing CSV outputs…")
    metrics.to_csv("florida_daily_metrics.csv", index=False)
    beta_df.to_csv("florida_weekly_beta_diversity.csv", index=False)
    trend.to_csv("florida_trends_by_year.csv", index=False)

    try:
        n_days = metrics["date"].nunique()
        n_weeks = beta_df["week"].nunique() if not beta_df.empty else 0
        n_species = daily["speciesId"].nunique()
        progress.note(
            f"SUMMARY → Days: {n_days} | Weeks: {n_weeks} | Species: {n_species} | Daily CV: {cv_daily:.3f}"
        )
    except Exception:
        pass

    return metrics, beta_df, trend, cv_daily

# -----------------------
# MAIN
# -----------------------
def main():
    # 1) Stations in Florida bbox (try tiled first, fallback to simple)
    try:
        progress.note("Attempting tiled station discovery...")
        station_ids, stations_df = fetch_station_ids_tiled(BBOX["ne"], BBOX["sw"],
                                                           page_size=STATION_PAGE_SIZE,
                                                           rows=TILE_ROWS, cols=TILE_COLS)
    except Exception as e:
        progress.note(f"Tiled approach failed: {e}")
        progress.note("Trying with smaller tiles...")
        try:
            station_ids, stations_df = fetch_station_ids_tiled(BBOX["ne"], BBOX["sw"],
                                                               page_size=10,  # Even smaller pages
                                                               rows=SMALL_TILE_ROWS, cols=SMALL_TILE_COLS)
        except Exception as e2:
            progress.note(f"Small tiles also failed: {e2}")
            progress.note("Falling back to simple bbox approach...")
            station_ids, stations_df = fetch_station_ids_simple(BBOX["ne"], BBOX["sw"],
                                                                page_size=10)  # Very small pages
    if stations_df.empty or not station_ids:
        print("No public stations found in Florida bbox.")
        return

    # Optional: keep only stations whose 'state' looks like Florida/FL
    if FILTER_TO_FLORIDA_STATE and "state" in stations_df.columns:
        mask = stations_df["state"].astype(str).str.strip().str.lower().isin({"fl", "florida"})
        stations_df = stations_df[mask].copy()
        kept_ids = set(stations_df["id"])
        station_ids = [sid for sid in station_ids if sid in kept_ids]
        progress.note(f"Filtered to Florida state field → {len(station_ids)} stations remain.")

    # Save station manifest + availability
    for col in ["earliestDetectionAt", "latestDetectionAt"]:
        if col in stations_df.columns:
            stations_df[col] = pd.to_datetime(stations_df[col], errors="coerce")
    if not stations_df.empty:
        overall_earliest = stations_df["earliestDetectionAt"].min()
        overall_latest   = stations_df["latestDetectionAt"].max()
        progress.note("Data availability (Florida public stations):")
        progress.note(f"- Earliest detection: {overall_earliest}")
        progress.note(f"- Latest detection:   {overall_latest}")
    stations_df.to_csv("florida_stations.csv", index=False)
    progress.note("Saved station manifest → florida_stations.csv")

    if not station_ids:
        print("No Florida stations after filtering.")
        return

    # 2) Fetch daily counts (auto-snap start to earliest available if earlier than requested)
    auto_start = START_DATE
    if "earliestDetectionAt" in stations_df.columns and stations_df["earliestDetectionAt"].notna().any():
        earliest_available = stations_df["earliestDetectionAt"].min()
        if pd.notna(earliest_available):
            auto_start = max(pd.to_datetime(START_DATE), earliest_available).date().isoformat()
    progress.note(f"Fetching daily counts for period: {auto_start} → {END_DATE}")
    daily = fetch_daily_counts(station_ids, auto_start, END_DATE, STATION_CHUNK)
    if daily.empty:
        print("No daily data returned for this period. Try a later start date.")
        return

    # 3) Metrics & outputs
    compute_and_save_metrics(daily)

    progress.note("All files saved:")
    print("- florida_stations.csv")
    print("- florida_daily_metrics.csv")
    print("- florida_weekly_beta_diversity.csv")
    print("- florida_trends_by_year.csv")

if __name__ == "__main__":
    main()
