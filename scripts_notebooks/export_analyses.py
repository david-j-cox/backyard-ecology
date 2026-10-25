#!/usr/bin/env python3
"""
Export the data behind the interactive study analyses on docs/index.html.

Writes docs/data/analyses.json, loaded by the page after the main view:
- visit timestamps per site and species (bout analysis, time of day), read
  from raw_data_all_locations.csv so repeat visits in the same minute count
- daily summary visits per site and species (multiple baseline, diversity)
- weather for every local hour that had a visit (visits by weather)
- Jacksonville pecks and seed per visit (seed/side preference, pecks)
- behavioral momentum fits for every extinction phase, overall and by
  species, using the same models, starting values, bounds, and metrics as
  all_sites_all_analytics.py

Weather is matched to visits on the local clock hour.

Usage (from scripts_notebooks/):
    python export_analyses.py
"""

import json
import warnings
from datetime import datetime, timezone

import duckdb
import numpy as np
import pandas as pd
from scipy.optimize import curve_fit

from db import DB_PATH
from export_dashboard_data import PHASE_LOCATIONS, REPO_ROOT, SITES, clean_species, load_raw_visits

OUTPUT_PATH = REPO_ROOT / "docs" / "data" / "analyses.json"

# Minutes are counted from this local-time origin to keep numbers short
EPOCH = pd.Timestamp("2025-01-01")

SUMMARY_SHEETS = {
    "Jacksonville, FL 32259 Daily Su": "jacksonville_fl_32259",
    "Essex Fells, NJ 07021 Daily Sum": "essex_fells_nj_07021",
    "Southampton daily summaries": "southampton_uk",
    "Auburn, AL 36830 Daily Sum": "auburn_al_36830",
}
SITE_KEYS = ["jacksonville_fl_32259", "essex_fells_nj_07021", "southampton_uk", "auburn_al_36830"]
WEATHER_LOCATIONS = {v: k for k, v in PHASE_LOCATIONS.items()}

# Behavioral momentum: same window and models as all_sites_all_analytics.py
BM_START = pd.Timestamp("2025-10-05")
BM_MIN_POINTS = 4


class Index:
    """Stable integer codes for repeated strings."""

    def __init__(self):
        self.names, self.codes = [], {}

    def __call__(self, name):
        if name not in self.codes:
            self.codes[name] = len(self.names)
            self.names.append(name)
        return self.codes[name]


def export_visits(raw, species):
    """One row per visit, repeat visits included: [site, species, minutes since EPOCH]."""
    df = raw[["source_sheet", "Date", "Bird", "Time"]].copy()
    df["Bird"] = df["Bird"].map(lambda b: None if pd.isna(b) else clean_species(b))
    df = df.dropna(subset=["Bird", "Time", "Date"])
    stamp = pd.to_datetime(df["Date"].str[:10] + " " + df["Time"].str[:8], errors="coerce")
    df = df.assign(minute=((stamp - EPOCH).dt.total_seconds() // 60)).dropna(subset=["minute"])
    df = df.sort_values(["source_sheet", "minute"])
    return [[SITE_KEYS.index(s), species(b), int(m)] for s, b, m in zip(df["source_sheet"], df["Bird"], df["minute"])]


def export_daily_summaries(con, species):
    """Daily summary visits: [site, date, species, visits]."""
    out = []
    for sheet, day, bird, visits in con.execute(
        'SELECT source_sheet, "Date", "Bird", "Feeder Visits" FROM daily_summaries'
    ).fetchall():
        site = SUMMARY_SHEETS.get(sheet)
        bird = clean_species(bird)
        try:
            visits = int(float(visits))
        except (TypeError, ValueError):
            continue
        if site and bird and day and visits > 0:
            out.append([SITE_KEYS.index(site), day[:10], species(bird), visits])
    return sorted(out, key=lambda r: (r[0], r[1]))


def export_visit_weather(con, visits):
    """Temperature and wind for each local hour that had a visit: [site, hour since EPOCH, temp C, wind m/s]."""
    hours = {(s, m // 60) for s, _sp, m in visits}
    out = []
    for loc, local, temp, wind in con.execute(
        """
        SELECT location, observed_dt_local, TRY_CAST(temp AS DOUBLE), TRY_CAST(wind_speed AS DOUBLE)
        FROM hourly_weather
        """
    ).fetchall():
        site = PHASE_LOCATIONS.get(loc)
        if site not in SITE_KEYS or not local or temp is None:
            continue
        # observed_dt_local carries the site's own clock time; keep it, ignore the offset
        hour = int((pd.Timestamp(local[:19]) - EPOCH).total_seconds() // 3600)
        key = (SITE_KEYS.index(site), hour)
        if key in hours:
            out.append([key[0], hour, round(temp, 1), None if wind is None else round(wind, 2)])
    return out


def export_pecks(raw, species, seeds):
    """Jacksonville visits with peck counts: [species, minutes, left pecks, right pecks, left seed, right seed]."""
    df = raw[raw["source_sheet"] == "jacksonville_fl_32259"].copy()
    df["Bird"] = df["Bird"].map(lambda b: None if pd.isna(b) else clean_species(b))
    df = df.dropna(subset=["Bird", "Time", "Date"])
    left = pd.to_numeric(df["LeftPecks"], errors="coerce")
    right = pd.to_numeric(df["RightPecks"], errors="coerce")
    df = df[left.notna() | right.notna()].assign(left=left, right=right)
    stamp = pd.to_datetime(df["Date"].str[:10] + " " + df["Time"].str[:8], errors="coerce")
    df = df.assign(minute=((stamp - EPOCH).dt.total_seconds() // 60)).dropna(subset=["minute"])

    def seed(value):
        value = "" if value is None or pd.isna(value) else str(value).strip()
        return None if value.lower() in ("", "none", "nan") else seeds(value)

    return [
        [species(b), int(m), None if pd.isna(lp) else int(lp), None if pd.isna(rp) else int(rp), seed(ls), seed(rs)]
        for b, m, lp, rp, ls, rs in zip(df["Bird"], df["minute"], df["left"], df["right"], df["LeftSeed"], df["RightSeed"])
    ]


def _bm_2param(t, B0, b):
    return B0 * np.exp(-b * t)


def _bm_3param(t, B0, b, c):
    return B0 * np.exp(-b * t) + c


def _fit_metrics(y_obs, y_pred, k):
    n = len(y_obs)
    ss_res = np.sum((y_obs - y_pred) ** 2)
    ss_tot = np.sum((y_obs - np.mean(y_obs)) ** 2)
    r2 = 1.0 - ss_res / ss_tot if ss_tot > 0 else np.nan
    mae = float(np.mean(np.abs(y_obs - y_pred)))
    rmse = float(np.sqrt(np.mean((y_obs - y_pred) ** 2)))
    if n > k + 1 and ss_res > 0:
        aicc = n * np.log(ss_res / n) + 2 * k + (2 * k ** 2 + 2 * k) / (n - k - 1)
    else:
        aicc = np.nan
    return r2, mae, rmse, aicc


def _clean(value, digits=4):
    return None if value is None or not np.isfinite(value) else round(float(value), digits)


def _fit(t, y, three_param):
    """Same p0, bounds, and maxfev as the study's get_bm_fits."""
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        try:
            if three_param:
                c0 = max(float(np.percentile(y, 10)), 0.5)
                popt, _ = curve_fit(_bm_3param, t, y, p0=[float(y[0]), 0.15, c0],
                                    bounds=([1e-3, 1e-6, 0], [1e6, 10.0, 1e6]), maxfev=10000)
                pred, k = _bm_3param(t, *popt), 3
            else:
                popt, _ = curve_fit(_bm_2param, t, y, p0=[float(y[0]), 0.15],
                                    bounds=([1e-3, 1e-6], [1e6, 10.0]), maxfev=10000)
                pred, k = _bm_2param(t, *popt), 2
        except Exception:
            return None
    r2, mae, rmse, aicc = _fit_metrics(y, pred, k)
    fit = {"B0": _clean(popt[0]), "b": _clean(popt[1], 5), "R2": _clean(r2), "MAE": _clean(mae), "RMSE": _clean(rmse),
           "AICc": _clean(aicc), "n": int(len(y))}
    if three_param:
        fit["c"] = _clean(popt[2])
    return fit


def export_momentum(con, summaries, species_names):
    """
    Behavioral momentum fits for every extinction phase, overall and by species.

    Matches the study: daily summary visits from 2025-10-05, each extinction
    runs until the next phase change (or the last date + 1 day), zero-visit
    days are dropped, and t is days since the extinction started.
    """
    phases = con.execute(
        'SELECT "DateChangeStarted", "DescriptionOfChange", "LocationOfChange" FROM phase_changes'
    ).df()
    phases["site"] = phases["LocationOfChange"].str.strip().map(PHASE_LOCATIONS)
    phases["start"] = pd.to_datetime(phases["DateChangeStarted"].str[:10], errors="coerce")
    summ = pd.DataFrame(summaries, columns=["site", "date", "species", "visits"])
    summ["date"] = pd.to_datetime(summ["date"])
    overall, by_species = [], []
    for site_idx, site in enumerate(SITE_KEYS):
        changes = phases[phases["site"] == site].dropna(subset=["start"]).sort_values("start").reset_index(drop=True)
        data = summ[(summ["site"] == site_idx) & (summ["date"] >= BM_START)]
        if changes.empty or data.empty:
            continue
        extinctions = changes[changes["DescriptionOfChange"].str.lower().str.contains("extinct", na=False)]
        for number, (_, ext) in enumerate(extinctions.iterrows(), start=1):
            later = changes[changes["start"] > ext["start"]]
            end = later.iloc[0]["start"] if not later.empty else data["date"].max() + pd.Timedelta(days=1)
            seg = data[(data["date"] >= ext["start"]) & (data["date"] < end)]
            totals = seg.groupby("date")["visits"].sum()
            totals = totals[totals > 0]
            record = {"site": site, "transition": number, "start": ext["start"].strftime("%Y-%m-%d"),
                      "end": end.strftime("%Y-%m-%d"), "points": [], "fit2": None, "fit3": None}
            if len(totals) >= BM_MIN_POINTS:
                t = (totals.index - ext["start"]).days.values.astype(float)
                y = totals.values.astype(float)
                record["points"] = [[int(a), int(b)] for a, b in zip(t, y)]
                record["fit2"], record["fit3"] = _fit(t, y, False), _fit(t, y, True)
            overall.append(record)
            for sp, rows in seg.groupby("species"):
                per_day = rows.groupby("date")["visits"].sum()
                per_day = per_day[per_day > 0]
                if len(per_day) < BM_MIN_POINTS:
                    continue
                t = (per_day.index - ext["start"]).days.values.astype(float)
                fit = _fit(t, per_day.values.astype(float), False)
                if fit:
                    by_species.append({"site": site, "transition": number, "species": int(sp), **fit})
    return overall, by_species


def main():
    species, seeds = Index(), Index()
    raw = load_raw_visits()
    with duckdb.connect(str(DB_PATH), read_only=True) as con:
        visits = export_visits(raw, species)
        summaries = export_daily_summaries(con, species)
        visit_weather = export_visit_weather(con, visits)
        pecks = export_pecks(raw, species, seeds)
        momentum, momentum_species = export_momentum(con, summaries, species.names)

    payload = {
        "generated": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "epoch": EPOCH.strftime("%Y-%m-%d"),
        "sites": SITE_KEYS,
        "species": species.names,
        "seeds": seeds.names,
        "visits": {"cols": ["site", "species", "minute"], "rows": visits},
        "dailySummaries": {"cols": ["site", "date", "species", "visits"], "rows": summaries},
        "visitWeather": {"cols": ["site", "hour", "temp", "wind"], "rows": visit_weather},
        "pecks": {"cols": ["species", "minute", "left", "right", "leftSeed", "rightSeed"], "rows": pecks},
        "momentum": momentum,
        "momentumSpecies": momentum_species,
    }
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(json.dumps(payload, separators=(",", ":"), default=str))
    print(f"Analyses data written to {OUTPUT_PATH} ({OUTPUT_PATH.stat().st_size / 1024:,.0f} KB)")
    print(f"  {len(visits):,} visits, {len(summaries):,} daily summary rows, {len(visit_weather):,} visit-hours "
          f"with weather, {len(pecks):,} visits with pecks, {len(momentum)} extinction phases, "
          f"{len(momentum_species)} species fits")


if __name__ == "__main__":
    main()
