# --- requirements: requests, pandas, numpy, scipy ---
# pip install requests pandas numpy scipy
# (optional) pip install tqdm
#
# HAIKUBOX DATA COLLECTOR
# =======================
# This script collects bird detection data from your Haikubox device.
#
# TO USE THIS SCRIPT:
# 1. Add your Haikubox serial code to the HAIKUBOX_SERIAL_CODES list below
# 2. Run the script: python haikubox.py
#
# The script will create a single CSV file in the ../data/ directory with:
# - Date, serial code, species name, scientific name, count, and total daily detections

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
HAIKUBOX_API_BASE = "https://api.haikubox.com"

# List of Haikubox serial codes in Duval/St. Johns County area
HAIKUBOX_SERIAL_CODES = [
    "48CA43335FD4", 
]

# Date window (inclusive start, up to today by default)
START_DATE = "2023-01-01"  # Haikubox data typically starts more recently
END_DATE = dt.date.today().isoformat()

# Gentle pacing to be kind to the API
PAUSE_BETWEEN_REQUESTS_S = 0.5

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
# Requests session with retry logic
# -----------------------
def make_session():
    from requests.adapters import HTTPAdapter
    try:
        from urllib3.util.retry import Retry
        retries = Retry(
            total=3,
            backoff_factor=1,
            status_forcelist=(429, 500, 502, 503, 504),
            allowed_methods=frozenset(["GET"]),
            raise_on_status=False,
            respect_retry_after_header=True,
        )
        s = requests.Session()
        s.headers.update({"Accept": "application/json", "User-Agent": "Haikubox-Data-Collector/1.0"})
        s.mount("https://", HTTPAdapter(max_retries=retries))
        s.mount("http://", HTTPAdapter(max_retries=retries))
        return s
    except Exception:
        return requests.Session()

SESSION = make_session()

# -----------------------
# Haikubox API helper with retry logic
# -----------------------
def haikubox_request(endpoint: str, max_attempts: int = 5, base_sleep: float = 1.0) -> Dict[str, Any]:
    """Make a request to the Haikubox API with retry logic."""
    attempt = 0
    url = f"{HAIKUBOX_API_BASE}{endpoint}"
    
    while attempt < max_attempts:
        attempt += 1
        try:
            r = SESSION.get(url, timeout=30)
            status = r.status_code
            
            if status == 200:
                return r.json()
            elif status == 404:
                # Device not found or no data
                return {}
            elif status in {429, 500, 502, 503, 504}:
                if attempt < max_attempts:
                    sleep_s = base_sleep * (2 ** (attempt - 1)) + (0.1 * np.random.random())
                    progress.note(f"Attempt {attempt}/{max_attempts} failed with HTTP {status}. Retrying in {sleep_s:.1f}s...")
                    time.sleep(sleep_s)
                    continue
            else:
                r.raise_for_status()
                
        except (requests.Timeout, requests.ConnectionError, requests.HTTPError) as e:
            if attempt < max_attempts:
                sleep_s = base_sleep * (2 ** (attempt - 1)) + (0.1 * np.random.random())
                progress.note(f"Attempt {attempt}/{max_attempts} failed: {e}. Retrying in {sleep_s:.1f}s...")
                time.sleep(sleep_s)
            else:
                progress.note(f"Max attempts ({max_attempts}) reached for {endpoint}")
                raise
    
    return {}

# -----------------------
# Haikubox API Functions
# -----------------------
def get_haikubox_info(serial_code: str) -> Dict[str, Any]:
    """Get information about a specific Haikubox device."""
    endpoint = f"/haikubox/{serial_code}"
    return haikubox_request(endpoint)

def get_daily_count(serial_code: str, date: str = None) -> Dict[str, Any]:
    """Get daily bird count for a specific Haikubox device."""
    endpoint = f"/haikubox/{serial_code}/daily-count"
    if date:
        endpoint += f"?date={date}"
    return haikubox_request(endpoint)

def get_yearly_count(serial_code: str, year: str = None) -> Dict[str, Any]:
    """Get yearly bird count for a specific Haikubox device."""
    endpoint = f"/haikubox/{serial_code}/yearly-count"
    if year:
        endpoint += f"?year={year}"
    return haikubox_request(endpoint)

def get_recent_detections(serial_code: str, hours: int = 8) -> Dict[str, Any]:
    """Get recent detections from a Haikubox device."""
    endpoint = f"/haikubox/{serial_code}/detections?hours={hours}"
    return haikubox_request(endpoint)

# -----------------------
# Utils
# -----------------------
def date_range(start_date: str, end_date: str) -> List[str]:
    """Generate a list of dates between start_date and end_date (inclusive)."""
    start = dt.datetime.strptime(start_date, "%Y-%m-%d").date()
    end = dt.datetime.strptime(end_date, "%Y-%m-%d").date()
    dates = []
    current = start
    while current <= end:
        dates.append(current.isoformat())
        current += dt.timedelta(days=1)
    return dates

# -----------------------
# 1) Get Haikubox device information
# -----------------------
def fetch_haikubox_info(serial_codes: List[str]) -> pd.DataFrame:
    """Get information about Haikubox devices."""
    if not serial_codes:
        progress.note("No Haikubox serial codes provided. Please add serial codes to HAIKUBOX_SERIAL_CODES list.")
        return pd.DataFrame()
    
    progress.note(f"Fetching information for {len(serial_codes)} Haikubox devices...")
    device_info = []
    
    for serial_code in serial_codes:
        progress.note(f"Getting info for device {serial_code}...")
        info = get_haikubox_info(serial_code)
        if info:
            info['serial_code'] = serial_code
            device_info.append(info)
        time.sleep(PAUSE_BETWEEN_REQUESTS_S)
    
    df = pd.DataFrame(device_info)
    progress.note(f"Retrieved information for {len(device_info)} devices.")
    return df

# -----------------------
# 2) Pull daily counts from Haikubox devices
# -----------------------
def fetch_daily_counts(serial_codes: List[str], start_date: str, end_date: str) -> pd.DataFrame:
    """Fetch daily bird counts from Haikubox devices for a date range."""
    if not serial_codes:
        progress.note("No Haikubox serial codes provided.")
        return pd.DataFrame()
    
    dates = date_range(start_date, end_date)
    total_requests = len(serial_codes) * len(dates)
    progress.note(f"Fetching daily counts for {len(serial_codes)} devices over {len(dates)} days ({total_requests} requests)...")
    
    daily_frames = []
    bar = progress.bar(total=total_requests, desc="Fetching daily counts")
    records_so_far = 0
    t0 = time.time()
    
    for serial_code in serial_codes:
        for date in dates:
            data = get_daily_count(serial_code, date)
            if data and 'species' in data:
                total_detections = sum(species.get('count', 0) for species in data['species'])
                for species in data['species']:
                    daily_frames.append({
                        "date": date,
                        "serial_code": serial_code,
                        "species_name": species.get('name', 'Unknown'),
                        "species_scientific": species.get('scientific_name', ''),
                        "count": species.get('count', 0),
                        "total_daily_detections": total_detections
                    })
                    records_so_far += 1
            
            bar.update(1)
            time.sleep(PAUSE_BETWEEN_REQUESTS_S)
    
    bar.close()
    progress.note(f"Daily counts download complete: {records_so_far} rows in {time.time() - t0:.1f}s.")
    return pd.DataFrame(daily_frames)

# -----------------------
# 3) Save simple data file
# -----------------------
def save_haikubox_data(daily: pd.DataFrame):
    """Save the raw Haikubox data to a single CSV file."""
    if daily.empty:
        progress.note("No data to save.")
        return
    
    progress.note("Saving Haikubox data...")
    
    # Convert date to datetime for better sorting
    daily["date"] = pd.to_datetime(daily["date"])
    daily = daily.sort_values(["date", "species_name"])
    
    # Save to single file
    output_file = "../data/haikubox_bird_detections.csv"
    daily.to_csv(output_file, index=False)
    
    # Print summary
    n_days = daily["date"].nunique()
    n_species = daily["species_name"].nunique()
    total_detections = daily["count"].sum()
    
    progress.note(f"Data saved to {output_file}")
    progress.note(f"SUMMARY → Days: {n_days} | Species: {n_species} | Total detections: {total_detections}")
    
    return daily

# -----------------------
# MAIN
# -----------------------
def main():
    # Check if serial codes are provided
    if not HAIKUBOX_SERIAL_CODES:
        print("ERROR: No Haikubox serial codes provided!")
        print("Please add actual serial codes to the HAIKUBOX_SERIAL_CODES list in the script.")
        return

    # Fetch daily counts from your Haikubox device
    progress.note(f"Fetching daily counts for period: {START_DATE} → {END_DATE}")
    daily = fetch_daily_counts(HAIKUBOX_SERIAL_CODES, START_DATE, END_DATE)
    
    if daily.empty:
        print("No daily data returned for this period. Try a different date range or check device availability.")
        return

    # Save the data to a single file
    save_haikubox_data(daily)

    progress.note("Data collection complete!")
    print("File saved: ../data/haikubox_bird_detections.csv")

if __name__ == "__main__":
    main()
