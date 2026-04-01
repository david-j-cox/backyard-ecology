"""
Flyway migration heatmap with interactive date slider.

Reads flyway data from DuckDB, builds a Plotly choropleth with a date slider
so users can scrub through migration intensity day by day.

Usage:
    python flyway_heatmap.py                  # all three flyways combined
    python flyway_heatmap.py --flyway atlantic
    python flyway_heatmap.py --metric peak_birds_in_flight
"""

import argparse
import json
import re
from pathlib import Path
from urllib.request import urlopen

import duckdb
import numpy as np
import pandas as pd
import plotly.graph_objects as go

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
DB_PATH = Path(__file__).resolve().parent.parent / "data" / "backyard_ecology.duckdb"
COUNTY_CSV_DIR = Path(__file__).resolve().parent.parent / "data" / "county_data_for_birdcast_urls"
OUTPUT_DIR = Path(__file__).resolve().parent.parent / "data" / "flyway_heatmaps"

FLYWAY_TABLES = {
    "atlantic": "atlantic_flyway",
    "mississippi": "mississippi_flyway",
    "pacific": "pacific_flyway",
}

FLYWAY_CSV = {
    "atlantic": "atlantic_flyway_corridor_counties_with_urls.csv",
    "mississippi": "mississippi_flyway_corridor_counties_with_urls.csv",
    "pacific": "pacific_flyway_corridor_counties_with_urls.csv",
}

GEOJSON_URL = (
    "https://raw.githubusercontent.com/plotly/datasets/master/geojson-counties-fips.json"
)

BIRDCAST_FALL_END = pd.Timestamp("2025-11-15")
BIRDCAST_SPRING_START = pd.Timestamp("2026-03-01")
WINTER_LABEL = "Winter - No Migration"
N_WINTER_FRAMES = 10


def load_geojson():
    """Download and cache county-level GeoJSON."""
    cache_path = OUTPUT_DIR / "counties_geojson.json"
    if cache_path.exists():
        with open(cache_path) as f:
            return json.load(f)
    print("Downloading county GeoJSON (one-time)...")
    with urlopen(GEOJSON_URL) as resp:
        data = json.loads(resp.read().decode())
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    with open(cache_path, "w") as f:
        json.dump(data, f)
    return data


def build_fips_lookup(flyway: str) -> pd.DataFrame:
    """Build region_code -> zero-padded FIPS mapping from county CSV."""
    csv_path = COUNTY_CSV_DIR / FLYWAY_CSV[flyway]
    df = pd.read_csv(csv_path)
    df["fips"] = df["GEOID"].astype(str).str.zfill(5)
    df["region_code"] = df["birdcast_url"].str.extract(r"region/(.+)$")
    df["flyway"] = flyway
    return df[["region_code", "fips", "state", "state_abbr", "county", "flyway"]]


def parse_birdcast_date(date_key: str) -> pd.Timestamp | None:
    """Parse BirdCast date_key into a proper date."""
    if re.match(r"^\d{4}-\d{2}-\d{2}$", date_key):
        return pd.Timestamp(date_key)
    m = re.search(r"([A-Za-z]+)\s+(\d{1,2})$", date_key)
    if not m:
        return None
    month_str, day_str = m.group(1), m.group(2)
    try:
        month = pd.Timestamp(f"{month_str} 1, 2000").month
    except ValueError:
        return None
    year = 2025 if month >= 8 else 2026
    return pd.Timestamp(year=year, month=month, day=int(day_str))


def load_flyway_data(flyway: str, metric: str) -> pd.DataFrame:
    """Load flyway data from DuckDB, parsing both date formats."""
    table = FLYWAY_TABLES[flyway]
    con = duckdb.connect(str(DB_PATH), read_only=True)
    df = con.execute(
        f"SELECT region_code, {metric}, date_key FROM {table}"
    ).df()
    con.close()
    df[metric] = pd.to_numeric(df[metric], errors="coerce").fillna(0).astype(int)
    df["date"] = df["date_key"].apply(parse_birdcast_date)
    df = df.dropna(subset=["date"])
    return df


def interpolate_dates(
    df: pd.DataFrame, metric: str, max_gap_days: int = 14
) -> pd.DataFrame:
    """
    Fill date gaps by interpolating metric values per county (fips).
    The BirdCast off-season (Nov 16 - Feb 28) is excluded entirely
    and replaced with a small number of winter placeholder frames.
    """
    # Split into fall and spring seasons
    fall = df[df["date"] <= BIRDCAST_FALL_END].copy()
    spring = df[df["date"] >= BIRDCAST_SPRING_START].copy()

    parts = []
    for season_df in [fall, spring]:
        if season_df.empty:
            continue
        date_range = pd.date_range(season_df["date"].min(), season_df["date"].max(), freq="D")
        pivot = season_df.pivot_table(index="date", columns="fips", values=metric, aggfunc="first")
        pivot = pivot.reindex(date_range)
        pivot.index.name = "date"
        pivot = pivot.interpolate(method="linear", limit=max_gap_days, limit_direction="both")
        pivot = pivot.fillna(0)
        melted = pivot.reset_index().melt(id_vars="date", var_name="fips", value_name=metric)
        melted[metric] = melted[metric].round().astype(int)
        parts.append(melted)

    combined = pd.concat(parts, ignore_index=True)

    meta = df[["fips", "region_code", "state", "state_abbr", "county", "flyway"]].drop_duplicates(subset=["fips"])
    combined = combined.merge(meta, on="fips", how="left")
    return combined


def load_all_flyways(metric: str) -> pd.DataFrame:
    """Load and merge data from all three flyways with FIPS codes."""
    frames = []
    for flyway in FLYWAY_TABLES:
        fips_df = build_fips_lookup(flyway)
        data = load_flyway_data(flyway, metric)
        merged = data.merge(fips_df, on="region_code", how="left")
        merged = merged.dropna(subset=["fips"])
        frames.append(merged)
    combined = pd.concat(frames, ignore_index=True)
    print(f"Raw data: {len(combined['date'].unique())} unique dates, interpolating gaps...")
    combined = interpolate_dates(combined, metric)
    print(f"After interpolation: {len(combined['date'].unique())} dates")
    return combined


def build_slider_labels(dates, metric_data):
    """
    Build slider labels, inserting winter placeholder labels
    between the fall and spring seasons.
    """
    labels = []
    date_indices = []  # maps slider position -> date (or None for winter)

    fall_dates = [d for d in dates if pd.Timestamp(d) <= BIRDCAST_FALL_END]
    spring_dates = [d for d in dates if pd.Timestamp(d) >= BIRDCAST_SPRING_START]

    for d in fall_dates:
        labels.append(pd.Timestamp(d).strftime("%Y-%m-%d"))
        date_indices.append(d)

    # Insert winter placeholders
    for i in range(N_WINTER_FRAMES):
        month_offset = int(11 + (i / N_WINTER_FRAMES) * 3)  # Nov -> Feb
        labels.append(WINTER_LABEL)
        date_indices.append(None)

    for d in spring_dates:
        labels.append(pd.Timestamp(d).strftime("%Y-%m-%d"))
        date_indices.append(d)

    return labels, date_indices


def generate_interactive_html(metric: str = "total_birds", flyway: str = "all"):
    """Generate an interactive HTML choropleth with a date slider."""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    if flyway == "all":
        print("Loading all flyway data...")
        data = load_all_flyways(metric)
        title_prefix = "US Flyway Migration"
        filename = f"all_flyways_{metric}"
    else:
        print(f"Loading {flyway} flyway data...")
        fips_df = build_fips_lookup(flyway)
        raw = load_flyway_data(flyway, metric)
        data = raw.merge(fips_df, on="region_code", how="left").dropna(subset=["fips"])
        print(f"Raw data: {len(data['date'].unique())} unique dates, interpolating gaps...")
        data = interpolate_dates(data, metric)
        print(f"After interpolation: {len(data['date'].unique())} dates")
        title_prefix = f"{flyway.title()} Flyway"
        filename = f"{flyway}_flyway_{metric}"

    if data.empty:
        print("No data found.")
        return

    full_geojson = load_geojson()

    # Filter GeoJSON to only include counties in our data — the full US
    # county GeoJSON is 3MB and gets embedded per-frame, so trimming it
    # dramatically reduces the HTML file size.
    used_fips = set(data["fips"].unique())
    geojson = {
        "type": full_geojson["type"],
        "features": [
            f for f in full_geojson["features"]
            if f["id"] in used_fips
        ],
    }
    print(f"Filtered GeoJSON: {len(geojson['features'])} counties (of {len(full_geojson['features'])})")

    # Compute log values
    log_col = f"{metric}_log"
    data[log_col] = np.log10(data[metric].clip(lower=1))
    p99 = np.percentile(data[metric].clip(lower=1), 99)
    vmax_log = np.log10(max(p99, 10))

    dates = sorted(data["date"].unique())
    labels, date_indices = build_slider_labels(dates, data)

    # Get all unique fips for the zero-frame template
    all_fips = data["fips"].unique()
    meta = data[["fips", "state_abbr", "county", "flyway"]].drop_duplicates(subset=["fips"])
    zero_df = meta.copy()
    zero_df[metric] = 0
    zero_df[log_col] = 0.0

    # Build frames
    print(f"Building {len(labels)} slider frames...")
    frames = []
    for i, (label, date_val) in enumerate(zip(labels, date_indices)):
        if date_val is None:
            # Winter placeholder — all zeros
            frame_df = zero_df
        else:
            frame_df = data[data["date"] == date_val]

        frames.append(go.Frame(
            data=[go.Choropleth(
                geojson=geojson,
                locations=frame_df["fips"],
                z=frame_df[log_col],
                zmin=0,
                zmax=vmax_log,
                colorscale="YlOrRd",
                marker_line_width=0.2,
                marker_line_color="white",
                text=frame_df.apply(
                    lambda r: f"{r.get('county', '')}, {r.get('state_abbr', '')}<br>"
                              f"Flyway: {r.get('flyway', '')}<br>"
                              f"{metric.replace('_', ' ').title()}: {r.get(metric, 0):,}",
                    axis=1
                ),
                hoverinfo="text",
                colorbar=dict(
                    title=metric.replace("_", " ").title(),
                    tickvals=[0, 1, 2, 3, 4, 5, 6],
                    ticktext=["0", "10", "100", "1K", "10K", "100K", "1M"],
                ),
                locationmode="geojson-id",
            )],
            name=label,
            layout=go.Layout(
                title_text=f"{title_prefix} - {metric.replace('_', ' ').title()} - {label}",
            ),
        ))

    # Initial frame (first date)
    first_frame = frames[0]

    fig = go.Figure(
        data=first_frame.data,
        layout=go.Layout(
            title=dict(
                text=f"{title_prefix} - {metric.replace('_', ' ').title()} - {labels[0]}",
                x=0.5,
            ),
            geo=dict(
                scope="usa",
                lakecolor="rgb(255, 255, 255)",
                showlakes=True,
            ),
            margin=dict(l=0, r=0, t=50, b=0),
            width=1100,
            height=650,
            sliders=[dict(
                active=0,
                currentvalue=dict(
                    prefix="Date: ",
                    visible=True,
                    xanchor="center",
                ),
                pad=dict(t=30),
                steps=[
                    dict(
                        method="animate",
                        args=[[label], dict(
                            mode="immediate",
                            frame=dict(duration=0, redraw=True),
                            transition=dict(duration=0),
                        )],
                        label=label if label != WINTER_LABEL else "W",
                    )
                    for label in labels
                ],
            )],
            updatemenus=[dict(
                type="buttons",
                showactive=False,
                x=0.05,
                y=-0.04,
                buttons=[
                    dict(
                        label="Play",
                        method="animate",
                        args=[None, dict(
                            frame=dict(duration=300, redraw=True),
                            fromcurrent=True,
                            transition=dict(duration=100),
                        )],
                    ),
                    dict(
                        label="Pause",
                        method="animate",
                        args=[[None], dict(
                            frame=dict(duration=0, redraw=False),
                            mode="immediate",
                            transition=dict(duration=0),
                        )],
                    ),
                ],
            )],
        ),
        frames=frames,
    )

    html_path = OUTPUT_DIR / f"{filename}.html"
    fig.write_html(str(html_path), include_plotlyjs="cdn", auto_open=False)
    print(f"Interactive HTML saved: {html_path}")

    # Also save to dashboard directory with metadata
    dashboard_dir = Path(__file__).resolve().parent.parent / "docs" / "dashboard_plots"
    interactive_dir = dashboard_dir / "interactive"
    interactive_dir.mkdir(parents=True, exist_ok=True)

    dashboard_html = interactive_dir / f"{filename}.html"
    fig.write_html(str(dashboard_html), include_plotlyjs="cdn", auto_open=False)

    from datetime import datetime
    metadata = {
        "title": f"{title_prefix} - {metric.replace('_', ' ').title()}",
        "description": "Interactive choropleth map of bird migration across US flyway corridors with date slider",
        "filename": filename,
        "type": "plotly",
        "created": datetime.now().isoformat(),
        "html_path": f"interactive/{filename}.html",
    }
    with open(dashboard_dir / f"{filename}.json", "w") as f:
        json.dump(metadata, f, indent=2)
    print(f"Dashboard metadata saved: {filename}.json")

    return html_path


def main():
    parser = argparse.ArgumentParser(description="Generate flyway migration heatmap")
    parser.add_argument(
        "--flyway",
        choices=["atlantic", "mississippi", "pacific", "all"],
        default="all",
        help="Which flyway to render (default: all combined)",
    )
    parser.add_argument(
        "--metric",
        choices=["total_birds", "peak_birds_in_flight"],
        default="total_birds",
        help="Which metric to visualize (default: total_birds)",
    )
    args = parser.parse_args()
    path = generate_interactive_html(args.metric, args.flyway)
    if path:
        import webbrowser
        webbrowser.open(f"file://{path}")


if __name__ == "__main__":
    main()
