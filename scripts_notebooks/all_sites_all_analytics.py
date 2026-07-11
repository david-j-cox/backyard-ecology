#!/usr/bin/env python3
"""
All-sites analytics script.

Generates all dashboard plots from multi-site bird feeder data.
Converted from all_sites_all_analytics.ipynb.
"""

import matplotlib
matplotlib.use('Agg')

# --- Cell 0 ---
# Standard library imports
import argparse
import json
import os
import sys
from datetime import date, datetime, time as dtime
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from urllib.parse import urlencode

# Data manipulation and analysis
import numpy as np
import pandas as pd

# Visualization
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D
from mpl_toolkits.mplot3d import Axes3D  # Register 3D projection
import plotly.express as px
import plotly.graph_objects as go
import seaborn as sns
import matplotlib.dates as mdates
import matplotlib.gridspec as gridspec
import matplotlib.ticker as mtick

# Scientific computing
from scipy.cluster.hierarchy import dendrogram, linkage
from scipy.optimize import curve_fit
from scipy.spatial.distance import pdist, squareform

# Machine learning
from sklearn.cluster import AgglomerativeClustering
from sklearn.ensemble import HistGradientBoostingRegressor, RandomForestRegressor
from sklearn.linear_model import PoissonRegressor, Ridge
from sklearn.model_selection import KFold, cross_val_predict
from sklearn.neural_network import MLPRegressor
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import MinMaxScaler, StandardScaler

# Dimensionality reduction
# Suppress OpenMP deprecation warning from umap-learn
import contextlib
import io
with contextlib.redirect_stderr(io.StringIO()):
    import umap

# HTTP requests
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# Environment variables
from dotenv import load_dotenv

# ---------------------------------
# Config
# ---------------------------------
PHASE_CHANGES = '../data/phase_change_data.csv'
RAW_DATA = '../data/raw_data_all_locations.csv'
DAILY_SUMS = '../data/daily_summaries_all_locations.csv'
BIRDCAST_PARQUET = '../data/birdcast_data.parquet'
BIRDCAST_CSV = '../data/birdcast_data.csv'
load_dotenv()

# Time-binning config
TIME_BIN_START_HOUR = 0     # 6 AM
TIME_BIN_END_HOUR = 23      # 8 PM (20 in 24h)
TIME_BIN_MINUTES = 30       # 30-minute bins

# Plot config
PLOTLY_RENDERER = 'browser'

pd.set_option('display.max_columns', None)
pd.set_option('display.max_rows', 200)

# ---------------------------------
# Dashboard Export Functions
# ---------------------------------
# Create dashboard output directory
DASHBOARD_DIR = '../docs/dashboard_plots'
os.makedirs(DASHBOARD_DIR, exist_ok=True)
os.makedirs(f'{DASHBOARD_DIR}/images', exist_ok=True)
os.makedirs(f'{DASHBOARD_DIR}/interactive', exist_ok=True)

print(f"Dashboard plots will be saved to: {DASHBOARD_DIR}")

# Function to save matplotlib plots
def save_plot_for_dashboard(fig, filename, title, description=""):
    """Save matplotlib figure for dashboard with metadata."""
    # Save as web-resolution PNG. dpi=120 keeps figures crisp on retina
    # displays (~3000px wide for the large panels) while cutting file size
    # ~4x vs dpi=300. This keeps the Pages deploy artifact small enough to
    # deploy reliably as more days of data accumulate.
    png_path = f'{DASHBOARD_DIR}/images/{filename}.png'
    fig.savefig(png_path, dpi=120, bbox_inches='tight', facecolor='white')
    
    # Create metadata file
    metadata = {
        'title': title,
        'description': description,
        'filename': filename,
        'type': 'matplotlib',
        'created': datetime.now().isoformat(),
        'image_path': f'images/{filename}.png'
    }
    
    with open(f'{DASHBOARD_DIR}/{filename}.json', 'w') as f:
        json.dump(metadata, f, indent=2)

    print(f"Saved: {title} -> {filename}")
    return filename


def assign_condition_letters(ordered_labels):
    """Map phase-condition labels to single-letter codes (A, B, C, ...) in
    first-appearance order, normalizing whitespace/newlines so 'No\\nSeed' and
    'No Seed' collapse to one entry. Returns (normalized_label -> letter,
    [(letter, normalized_label), ...] for a legend). A single centered letter
    per condition span stays legible where full text overlapped the phase
    lines and neighboring labels as the study accrued more phases."""
    import string
    letters, legend = {}, []
    for lab in ordered_labels:
        key = ' '.join(str(lab).split())
        if key and key not in letters:
            code = string.ascii_uppercase[len(letters)] if len(letters) < 26 else f'#{len(letters)}'
            letters[key] = code
            legend.append((code, key))
    return letters, legend


def draw_condition_key(fig, legend, x=0.5, y=0.965, fontsize=13):
    """Render a one-line horizontal 'Condition key' legend across the figure
    for the letter codes produced by assign_condition_letters()."""
    if not legend:
        return
    parts = '    '.join(f'{code} = {name}' for code, name in legend)
    fig.text(x, y, f'Condition key:   {parts}', ha='center', va='top',
             fontsize=fontsize)


def condition_spans(location_phase_changes, observed_dates, baseline='Seed'):
    """Return [(center_date, condition_str), ...] - one entry per phase span,
    centered between phase-change lines. Spans are: the baseline period before
    the first change, then each change to the next change (or to the last
    observed date). Used to place single-letter codes clear of the lines."""
    obs = pd.Series(list(observed_dates)).dropna()
    if obs.empty:
        return []
    obs = np.sort(pd.to_datetime(obs.unique()))
    data_start, data_end = obs[0], obs[-1]
    boundaries = []  # (line_date, condition_description)
    for _, row in location_phase_changes.iterrows():
        change_date = pd.to_datetime(row['DateChangeStarted'])
        prior = obs[obs < change_date]
        if len(prior) == 0:
            continue
        line_date = prior[-1] + (change_date - prior[-1]) / 2
        boundaries.append((line_date, row['DescriptionOfChange']))
    boundaries.sort(key=lambda b: b[0])
    edges = [data_start] + [b[0] for b in boundaries] + [data_end]
    conditions = [baseline] + [b[1] for b in boundaries]
    return [(edges[i] + (edges[i + 1] - edges[i]) / 2, conditions[i])
            for i in range(len(conditions))]


def condition_span_placements(location_phase_changes, observed_dates, baseline='Seed'):
    """Single-location convenience: return (placements, legend) with letters
    assigned from this location's own conditions. placements =
    [(center_date, letter), ...]; legend = [(letter, condition), ...]."""
    spans = condition_spans(location_phase_changes, observed_dates, baseline)
    letters, legend = assign_condition_letters([c for _, c in spans])
    placements = [(center, letters[' '.join(str(c).split())]) for center, c in spans]
    return placements, legend

# --- Cell 1 ---
# ---------------------------------
# Helpers for time-binning & plots
# ---------------------------------
def build_time_bins(start_hour: int = TIME_BIN_START_HOUR,
                    end_hour: int = TIME_BIN_END_HOUR,
                    step_minutes: int = TIME_BIN_MINUTES) -> Tuple[List[dtime], List[str]]:
    time_bins: List[dtime] = []
    for hour in range(start_hour, end_hour + 1):
        for minute in range(0, 60, step_minutes):
            if hour == end_hour and minute >= 60:
                break
            time_bins.append(dtime(hour, minute))
    time_labels = [t.strftime('%I:%M %p') for t in time_bins]
    return time_bins, time_labels


def assign_time_bin_factory(time_bins: List[dtime]):
    # Returns a function that maps a datetime.time -> index of its bin
    def assign_time_bin(t):
        if t is None or pd.isna(t):
            return None
        t_minutes = t.hour * 60 + t.minute
        for i, bin_time in enumerate(time_bins):
            bin_minutes = bin_time.hour * 60 + bin_time.minute
            if t_minutes < bin_minutes + TIME_BIN_MINUTES:
                return i
        return len(time_bins) - 1
    return assign_time_bin


def prepare_complete_data(raw_df: pd.DataFrame,
                          time_bins: List[dtime]) -> Tuple[pd.DataFrame, List[str], list, list, pd.DataFrame]:
    # Ensure Time column is datetime.time
    if not np.issubdtype(pd.Series(raw_df['Time']).dtype, np.dtype('O')):
        raw_df = raw_df.copy()
        raw_df['Time'] = pd.to_datetime(raw_df['Time'], format='%H:%M:%S').dt.time

    time_bins, time_labels = build_time_bins()
    assign_time_bin = assign_time_bin_factory(time_bins)

    df = raw_df.copy()
    df['TimeBin'] = pd.to_datetime(df['Time']).apply(assign_time_bin)
    df = df.dropna(subset=['TimeBin'])

    grouped_data = df.groupby(['Date', 'TimeBin']).size().reset_index(name='Count')

    all_dates = sorted(df['Date'].unique())
    all_time_bins = list(range(len(time_bins)))

    complete_grid = pd.DataFrame([(date, tb) for date in all_dates for tb in all_time_bins],
                                 columns=['Date', 'TimeBin'])

    complete_data = complete_grid.merge(grouped_data, on=['Date', 'TimeBin'], how='left').fillna(0)

    dates = sorted(complete_data['Date'].unique())
    time_bin_indices = sorted(complete_data['TimeBin'].unique())
    return complete_data, time_labels, dates, time_bin_indices, grouped_data

def plot_heatmap_counts_subplots(location_data: dict,
                                title: str = 'Heatmap: Date vs Time of Day vs Observation Count') -> None:
    locations = sorted(list(location_data.keys())) 
    n_locations = len(locations)
    
    # Stack locations vertically (n rows x 1 col) so each heatmap gets the
    # full width; each row keeps the same height, so the figure is n x taller.
    fig, axes = plt.subplots(n_locations, 1, figsize=(18*n_locations, 10*n_locations))
    
    # Ensure axes is always a list for consistent indexing
    if n_locations == 1:
        axes = [axes]
    
    for i, location in enumerate(locations):
        ax = axes[i]
        complete_data = location_data[location]['complete_data']
        time_labels = location_data[location]['time_labels']
        
        heatmap_data = complete_data.pivot(index='TimeBin', columns='Date', values='Count')
        
        sns.heatmap(
            heatmap_data,
            xticklabels=[d.strftime('%m/%d') for d in heatmap_data.columns],
            yticklabels=[time_labels[int(i)] for i in heatmap_data.index],
            cmap='viridis',
            cbar_kws={'label': 'Count of Observations'},
            annot=True,
            annot_kws={'size':8},
            fmt='g',
            linewidths=0.5,
            ax=ax
        )
        
        ax.set_title(location, fontsize=30, fontweight='bold')
        ax.set_xlabel('Date', fontsize=24, labelpad=12)
        ax.set_ylabel('Time of Day', fontsize=24, labelpad=12)
        ax.tick_params(axis='x', rotation=45, labelsize=10)
        ax.tick_params(axis='y', rotation=0, labelsize=10)
        ax.invert_yaxis()
    
    plt.tight_layout()
    plt.subplots_adjust(hspace=0.3)
    return fig


def plot_heatmap_proportions_subplots(location_data: dict,
                                     title: str = 'Heatmap: Date vs Time of Day vs Proportion of Observations') -> None:
    locations = sorted(list(location_data.keys())) 
    n_locations = len(locations)
    
    # Stack locations vertically (n rows x 1 col) so each heatmap gets the
    # full width; each row keeps the same height, so the figure is n x taller.
    fig, axes = plt.subplots(n_locations, 1, figsize=(18*n_locations, 10*n_locations))
    
    # Ensure axes is always a list for consistent indexing
    if n_locations == 1:
        axes = [axes]
    
    for i, location in enumerate(locations):
        ax = axes[i]
        complete_data = location_data[location]['complete_data']
        time_labels = location_data[location]['time_labels']
        
        complete_with_totals = complete_data.copy()
        complete_with_totals['Daily Total'] = complete_with_totals.groupby('Date')['Count'].transform('sum')
        complete_with_totals['Daily Proportion'] = (complete_with_totals['Count'] / complete_with_totals['Daily Total']).round(2)
        heatmap_data = complete_with_totals.pivot(index='TimeBin', columns='Date', values='Daily Proportion')
        
        sns.heatmap(
            heatmap_data,
            xticklabels=[d.strftime('%m/%d') for d in heatmap_data.columns],
            yticklabels=[time_labels[int(i)] for i in heatmap_data.index],
            cmap='viridis',
            cbar_kws={'label': 'Proportion of Observations'},
            annot=True,
            annot_kws={'size':8},
            fmt='g',
            linewidths=0.5,
            ax=ax
        )
        
        ax.set_title(location, fontsize=30, fontweight='bold')
        ax.set_xlabel('Date', fontsize=24, labelpad=12)
        ax.set_ylabel('Time of Day', fontsize=24, labelpad=12)
        ax.tick_params(axis='x', rotation=45, labelsize=10)
        ax.tick_params(axis='y', rotation=0, labelsize=10)
        ax.invert_yaxis()
    
    plt.tight_layout()
    plt.subplots_adjust(hspace=0.3)
    return fig


# ---------------------------------
# Helpers for sunrise/sunset relative time-binning & plots
# ---------------------------------
def load_sunrise_sunset_data(sunrise_sunset_path: str = '../data/sunrise_sunset.csv') -> pd.DataFrame:
    """Load sunrise/sunset data and parse datetime columns."""
    ss_df = pd.read_csv(sunrise_sunset_path)
    ss_df['date_local'] = pd.to_datetime(ss_df['date_local'])
    ss_df['sunrise_local'] = pd.to_datetime(ss_df['sunrise_local'])
    ss_df['sunset_local'] = pd.to_datetime(ss_df['sunset_local'])
    return ss_df


def calculate_relative_time(obs_time: dtime, sunrise: datetime, sunset: datetime) -> Optional[float]:
    """
    Calculate relative time position between sunrise and sunset.
    Returns a value between 0 (sunrise) and 1 (sunset), or None if outside range.
    """
    # Check for None or NaN values (including float NaN)
    if obs_time is None or pd.isna(obs_time):
        return None
    if sunrise is None or pd.isna(sunrise) or (isinstance(sunrise, float) and np.isnan(sunrise)):
        return None
    if sunset is None or pd.isna(sunset) or (isinstance(sunset, float) and np.isnan(sunset)):
        return None
    
    # Ensure sunrise and sunset are datetime-like objects
    if not isinstance(sunrise, (datetime, pd.Timestamp)):
        return None
    if not isinstance(sunset, (datetime, pd.Timestamp)):
        return None
    
    # Convert obs_time to datetime.time if it's a string
    if isinstance(obs_time, str):
        try:
            obs_time = pd.to_datetime(obs_time, format='%H:%M:%S').time()
        except:
            try:
                obs_time = pd.to_datetime(obs_time).time()
            except:
                return None
    elif not isinstance(obs_time, dtime):
        return None
    
    # Convert observation time to datetime on the same date as sunrise
    # Use pandas to handle timezone-aware datetimes properly
    if isinstance(sunrise, pd.Timestamp):
        # Get the date from sunrise and combine with obs_time
        # Create a naive datetime first
        naive_dt = datetime.combine(sunrise.date(), obs_time)
        obs_datetime = pd.Timestamp(naive_dt)
        # If sunrise is timezone-aware, make obs_datetime aware too
        if sunrise.tz is not None:
            # Localize to the same timezone as sunrise
            obs_datetime = obs_datetime.tz_localize(sunrise.tz)
    else:
        # Standard datetime objects
        obs_datetime = datetime.combine(sunrise.date(), obs_time)
        # If sunrise is timezone-aware, make obs_datetime aware too
        if hasattr(sunrise, 'tzinfo') and sunrise.tzinfo is not None:
            obs_datetime = obs_datetime.replace(tzinfo=sunrise.tzinfo)
    
    # If observation is before sunrise or after sunset, return None
    if obs_datetime < sunrise or obs_datetime > sunset:
        return None
    
    # Calculate relative position (0 = sunrise, 1 = sunset)
    total_duration = (sunset - sunrise).total_seconds()
    time_since_sunrise = (obs_datetime - sunrise).total_seconds()
    
    if total_duration == 0:
        return None
    
    relative_time = time_since_sunrise / total_duration
    return relative_time


def assign_relative_time_bin(relative_time: float, n_bins: int = 30) -> Optional[int]:
    """
    Assign a relative time (0-1) to a bin index (0 to n_bins-1).
    Returns None if relative_time is None or outside [0, 1].
    """
    if relative_time is None or pd.isna(relative_time):
        return None
    
    if relative_time < 0 or relative_time > 1:
        return None
    
    # Clamp to [0, 1) and assign to bin
    bin_index = int(relative_time * n_bins)
    # Handle edge case where relative_time == 1.0
    if bin_index >= n_bins:
        bin_index = n_bins - 1
    
    return bin_index


def prepare_relative_time_data(raw_df: pd.DataFrame,
                               sunrise_sunset_df: pd.DataFrame,
                               location_col: str = 'source_sheet',
                               n_bins: int = 30) -> Tuple[pd.DataFrame, List[str], list, list]:
    """
    Prepare data with time bins relative to sunrise/sunset.
    
    Args:
        raw_df: DataFrame with Date, Time, and location column
        sunrise_sunset_df: DataFrame with sunrise/sunset times
        location_col: Column name for location in raw_df
        n_bins: Number of bins between sunrise and sunset (default 30)
    
    Returns:
        Tuple of (complete_data, bin_labels, dates, time_bin_indices)
    """
    # Ensure Time column is datetime.time
    # Check if Time is already time objects, or if it needs conversion
    df = raw_df.copy()
    if df['Time'].dtype == 'object':
        # Try to convert string times to time objects
        try:
            df['Time'] = pd.to_datetime(df['Time'], format='%H:%M:%S', errors='coerce').dt.time
        except:
            try:
                df['Time'] = pd.to_datetime(df['Time'], errors='coerce').dt.time
            except:
                pass
    elif not isinstance(df['Time'].iloc[0] if len(df) > 0 else None, dtime):
        # If not object type and not already time, try conversion
        try:
            df['Time'] = pd.to_datetime(df['Time'], format='%H:%M:%S', errors='coerce').dt.time
        except:
            pass
    
    # Ensure Date is datetime
    if not pd.api.types.is_datetime64_any_dtype(df['Date']):
        df['Date'] = pd.to_datetime(df['Date'])
    
    # Merge with sunrise/sunset data
    # Match on location and date
    df_merged = df.merge(
        sunrise_sunset_df[['location', 'date_local', 'sunrise_local', 'sunset_local']],
        left_on=[location_col, 'Date'],
        right_on=['location', 'date_local'],
        how='left'
    )
    
    # Calculate relative time for each observation
    df_merged['RelativeTime'] = df_merged.apply(
        lambda row: calculate_relative_time(
            row['Time'],
            row['sunrise_local'],
            row['sunset_local']
        ),
        axis=1
    )
    
    # Assign to bins
    df_merged['RelativeTimeBin'] = df_merged['RelativeTime'].apply(
        lambda rt: assign_relative_time_bin(rt, n_bins)
    )
    
    # Filter out observations outside sunrise-sunset range
    df_merged = df_merged.dropna(subset=['RelativeTimeBin'])
    
    # Group by Date and RelativeTimeBin
    grouped_data = df_merged.groupby(['Date', 'RelativeTimeBin']).size().reset_index(name='Count')
    
    # Create complete grid
    all_dates = sorted(df_merged['Date'].unique())
    all_time_bins = list(range(n_bins))
    
    complete_grid = pd.DataFrame(
        [(date, tb) for date in all_dates for tb in all_time_bins],
        columns=['Date', 'RelativeTimeBin']
    )
    
    complete_data = complete_grid.merge(
        grouped_data,
        on=['Date', 'RelativeTimeBin'],
        how='left'
    ).fillna(0)
    
    # Create bin labels (proportion from sunrise)
    bin_labels = [f'{i/n_bins:.2f}' for i in range(n_bins)]
    
    dates = sorted(complete_data['Date'].unique())
    time_bin_indices = sorted(complete_data['RelativeTimeBin'].unique())
    
    return complete_data, bin_labels, dates, time_bin_indices


def plot_heatmap_relative_time_proportions(location_data: dict,
                                          title: str = 'Heatmap: Date vs Relative Time (Sunrise-Sunset) vs Proportion of Observations') -> None:
    """
    Plot heatmap showing proportion of visits by date and relative time between sunrise and sunset.
    
    Args:
        location_data: Dictionary with location names as keys, each containing:
            - 'complete_data': DataFrame with Date, RelativeTimeBin, Count columns
            - 'bin_labels': List of labels for relative time bins
        title: Plot title
    """
    locations = sorted(list(location_data.keys()))
    n_locations = len(locations)
    
    # Stack locations vertically (n rows x 1 col) so each heatmap gets the
    # full width; each row keeps the same height, so the figure is n x taller.
    fig, axes = plt.subplots(n_locations, 1, figsize=(18*n_locations, 10*n_locations))
    
    # Ensure axes is always a list for consistent indexing
    if n_locations == 1:
        axes = [axes]
    
    for i, location in enumerate(locations):
        ax = axes[i]
        complete_data = location_data[location]['complete_data']
        bin_labels = location_data[location]['bin_labels']
        
        # Calculate proportions
        complete_with_totals = complete_data.copy()
        complete_with_totals['Daily Total'] = complete_with_totals.groupby('Date')['Count'].transform('sum')
        complete_with_totals['Daily Proportion'] = (
            complete_with_totals['Count'] / complete_with_totals['Daily Total']
        ).round(3)
        
        # Replace inf/NaN with 0 (for days with no observations)
        complete_with_totals['Daily Proportion'] = complete_with_totals['Daily Proportion'].replace([np.inf, -np.inf, np.nan], 0)
        
        heatmap_data = complete_with_totals.pivot(
            index='RelativeTimeBin',
            columns='Date',
            values='Daily Proportion'
        )
        
        # Create y-axis labels showing relative position (0 = sunrise, 1 = sunset)
        y_labels = [f'{float(bin_labels[int(i)]):.2f}' for i in heatmap_data.index]
        
        sns.heatmap(
            heatmap_data,
            xticklabels=[d.strftime('%m/%d') for d in heatmap_data.columns],
            yticklabels=y_labels,
            cmap='viridis',
            cbar_kws={'label': 'Proportion of Observations'},
            annot=True,
            annot_kws={'size':8},
            fmt='.2f',
            linewidths=0.5,
            ax=ax
        )
        
        ax.set_title(location, fontsize=30, fontweight='bold')
        ax.set_xlabel('Date', fontsize=24, labelpad=12)
        ax.set_ylabel('Relative Time (0=Sunrise, 1=Sunset)', fontsize=24, labelpad=12)
        ax.tick_params(axis='x', rotation=45, labelsize=10)
        ax.tick_params(axis='y', rotation=0, labelsize=10)
        ax.invert_yaxis()
    
    plt.tight_layout()
    plt.subplots_adjust(hspace=0.3)
    return fig

# --- Cell 2 ---
print("Loading data...")
# Load data
raw_data = pd.read_csv(RAW_DATA)
raw_data['Date'] = pd.to_datetime(raw_data['Date'])

daily_summs = pd.read_csv(DAILY_SUMS)
daily_summs['Date'] = pd.to_datetime(daily_summs['Date'])

phase_changes = pd.read_csv(PHASE_CHANGES)

# Source Sheet dicts for renaming
locations_dict = {
    'southampton_uk': 'Southampton, UK',
    'jacksonville_fl_32259': 'Jacksonville, FL',
    'essex_fells_nj_07021': 'Essex Fells, NJ',
    'auburn_al_36830': 'Auburn, AL',
}
raw_data['source_sheet'] = raw_data['source_sheet'].map(locations_dict)

locations_dict = {
    'Southampton daily summaries': 'Southampton, UK',
    'Jacksonville, FL 32259 Daily Su': 'Jacksonville, FL',
    'Essex Fells, NJ 07021 Daily Sum': 'Essex Fells, NJ',
    'Auburn, AL 36830 Daily Sum': 'Auburn, AL',
}
daily_summs['source_sheet'] = daily_summs['source_sheet'].map(locations_dict)


# # Basic plots of the action

# --- Cell 4 ---
# Define custom colors for each bird species
bird_colors = {
    'American Crow': '#1a1a1a',             # Near-black with crow sheen
    'American Goldfinch': '#FEB813',        # Bright Yellow
    'American Robin': '#FF6347',            # Tomato red-orange
    'Black-capped Chickadee': '#FFFFFF',    # White
    'Blue Jay': '#0000FF',                  # Blue
    'Blue tit': '#4169E1',                  # Royal blue
    'Brown Headed Cowbird': '#411900',      # Chocolate Brown
    'Brown Headed Nuthatch': 'gray',        # Gray
    'Carolina Chickadee': '#FFFFFF',        # White
    'Carolina Wren': '#8B4513',             # Medium brown
    'Chestnut-backed Chickadee': 'white',   # White
    'Chipping Sparrow': '#A81C07',          # Rufous
    'Common Grackle': 'black',              # Black
    'Dark-eyed Junco': '#3C4043',           # Dark Gray
    'Downy Woodpecker': '#4B0082',          # Indigo (dark blue-purple)
    'Eastern Bluebird': '#0000FF',          # Blue
    'Eastern Gray Squirrel': '#808080',     # Gray
    'Eastern Phoebe': '#3C4043',            # Dark Gray
    'Coal tit': '#2F4F4F',                  # Dark slate gray
    'Common Ground Dove': '#D2B48C',        # Tan
    'Gray Catbird': '#808080',              # Gray
    'Great tit': '#FFD700',                 # Gold
    'Hairy Woodpecker': 'black',            # Black
    'House Finch': '#A7947F',               # Muted Brown-Gray
    'House Sparrow': '#954535',             # Chestnut
    'Indigo Bunting': '#213B4E',            # Dark Blue
    'Mourning Dove': '#D2B48C',             # Tan
    'Northern Cardinal': '#DC143C',         # Cardinal red
    'Northern Mockingbird': 'white',        # White
    'Nuthatch': '#8FBC8F',                  # Dark sea green
    'Pine Warbler': '#FFD700',              # Gold
    'Red-breasted Nuthatch': '#913E27',     # Cinnamon Red 
    'Red-bellied Woodpecker': '#FF0000',    # Red
    'Pigeon.1': '#708090',                  # Slate gray
    'Pigeon': '#708090',                    # Slate gray
    'Robin': '#FF6347',                     # Tomato red-orange
    'Song Sparrow': '#F3D2B5',              # Light Brown
    'Tufted Titmouse': '#B0C4DE',           # Light blue gray
    'Western Honeybee': 'black',            # Black
    'White-breasted Nuthatch': '#F0E68C',   # Khaki (light yellow-green)
    'White-throated Sparrow': 'white',      # White
    'Yellow Rumped Warbler': '#FFD700',     # Gold
    'Yellow-rumped Warbler': '#FFD700',     # Gold
    'Yellow-throated Warbler': '#FFD700',   # Gold
}

# Define marker edge colors for birds that need black outlines
bird_edge_colors = {
    'American Crow': '#2a3a5a',
    'American Goldfinch': 'black',
    'American Robin': 'black',
    'Black-capped Chickadee': 'black',
    'Blue Jay': 'black',
    'Blue tit': 'black',
    'Brown Headed Cowbird': '#411900',
    'Brown Headed Nuthatch': '#8B4513', 
    'Carolina Chickadee': 'black',
    'Carolina Wren': '#8B4513',
    'Chestnut-backed Chickadee': '#954535', 
    'Chipping Sparrow': '#D2B48C', 
    'Common Ground Dove': '#D2B48C',
    'Common Grackle': 'black', 
    'Coal tit': 'black',
    'Dark-eyed Junco': 'black',
    'Downy Woodpecker': 'black',
    'Eastern Bluebird': '#8B4513',
    'Eastern Gray Squirrel': 'black',
    'Eastern Phoebe': '#FFD700',
    'Gray Catbird': 'black',
    'Great tit': 'black',
    'Hairy Woodpecker': 'black',
    'House Finch': '#D9534F',
    'House Sparrow': 'black',
    'Indigo Bunting': '#213B4E',
    'Mourning Dove': 'black',
    'Northern Cardinal': '#DC143C',
    'Northern Mockingbird': 'black',
    'Nuthatch': 'black',
    'Pigeon': 'black',
    'Pigeon.1': 'black',
    'Pine Warbler': '#8FBC8F', 
    'Red-breasted Nuthatch': '#886448', 
    'Red-bellied Woodpecker': 'black',
    'Robin': 'black',
    'Song Sparrow': '#62360F',
    'Tufted Titmouse': '#B0C4DE',
    'Western Honeybee': 'black',
    'White-breasted Nuthatch': 'black',
    'White-throated Sparrow': 'black',
    'Yellow Rumped Warbler': 'black', 
    'Yellow-rumped Warbler': 'black', 
    'Yellow-throated Warbler': 'black', 
}

# Define marker symbols for each bird species
bird_markers = {
    'American Crow': 'D',
    'American Goldfinch': '^',
    'American Robin': '^',
    'Black-capped Chickadee': 'o',
    'Blue tit': 'o',
    'Blue Jay': 'o',
    'Brown Headed Cowbird': '^',
    'Brown Headed Nuthatch': '^',
    'Carolina Chickadee': 'o',
    'Carolina Wren': 'o',
    'Chestnut-backed Chickadee': '^', 
    'Chipping Sparrow': '^', 
    'Coal tit': 'o',
    'Common Grackle': 'o', 
    'Common Ground Dove': 'o',
    'Dark-eyed Junco': '^',
    'Downy Woodpecker': 'o',
    'Eastern Bluebird': 'o',
    'Eastern Gray Squirrel': 's',
    'Eastern Phoebe': '^',
    'Gray Catbird': 'o',
    'Great tit': 'o',
    'Hairy Woodpecker': '^',
    'House Finch': 'o',
    'House Sparrow': '^',
    'Indigo Bunting': '^',
    'Mourning Dove': 'o',
    'Northern Cardinal': 'o',
    'Northern Mockingbird': '^',
    'Nuthatch': 'o',
    'Pigeon': '^',
    'Pigeon.1': '^',
    'Pine Warbler': 'o', 
    'Red-breasted Nuthatch': 'o', 
    'Red-bellied Woodpecker': 'o',
    'Robin': 'o',
    'Song Sparrow': '^',
    'Tufted Titmouse': 'o',
    'Western Honeybee': '*',
    'White-breasted Nuthatch': 'o',
    'White-throated Sparrow': '^',
    'Yellow Rumped Warbler': '^',
    'Yellow-rumped Warbler': '^',
    'Yellow-throated Warbler': '*',
}

# --- Cell 5 ---
print("Generating species visits plot...")

# Get unique locations
locations = sorted(daily_summs['source_sheet'].unique())
n_locations = len(locations)

# Create 2x2 subplot layout
fig, axes = plt.subplots(4, 1, figsize=(26, 20), sharey=True, sharex=True)

# Flatten axes array for easier indexing
axes = axes.flatten()

# Track birds that need specific colors
birds_needing_colors = set()

# Plot each location separately
for i, location in enumerate(locations):
    ax = axes[i]
    location_data = daily_summs[daily_summs['source_sheet'] == location].dropna(subset=['Bird']).replace(0, np.nan).reset_index(drop=True)
    
    # Check for phase changes for this location
    location_phase_changes = phase_changes[phase_changes['LocationOfChange'] == location]
    
    # Get all phase change dates sorted chronologically
    phase_change_dates = []
    if not location_phase_changes.empty:
        phase_change_dates = sorted([
            pd.to_datetime(date) 
            for date in location_phase_changes['DateChangeStarted'].unique()
        ])
    
    # Plot each bird species individually with custom colors
    for bird in location_data['Bird'].unique():
        bird_data = location_data[location_data['Bird'] == bird].copy()
        bird_data = bird_data.sort_values('Date')
        bird_data['Date'] = pd.to_datetime(bird_data['Date'])
        
        # Check if bird has predefined colors
        if bird in bird_colors:
            line_color = bird_colors[bird]
            marker_color = bird_colors[bird]
            edge_color = bird_edge_colors.get(bird, 'black')
        else:
            # Generate random colors for unknown birds
            np.random.seed(hash(bird) % 2**32)  # Consistent colors per bird
            line_color = f'#{np.random.randint(0, 0xFFFFFF):06x}'
            marker_color = line_color
            edge_color = 'black'
            birds_needing_colors.add(bird)
        
        # Special handling for Carolina Chickadee
        if (bird == 'Carolina Chickadee') or (bird == 'Black-capped Chickadee'):
            line_color = '#000000'  # Black line
            marker_color = '#FFFFFF'  # White marker
        
        # Split data at all phase changes if they exist
        if len(phase_change_dates) > 0:
            # Create segments: before first change, between changes, after last change
            segments = []
            
            # First segment: before first phase change
            first_segment = bird_data[bird_data['Date'] < phase_change_dates[0]]
            if not first_segment.empty:
                segments.append(first_segment)
            
            # Middle segments: between consecutive phase changes
            for j in range(len(phase_change_dates) - 1):
                segment = bird_data[
                    (bird_data['Date'] >= phase_change_dates[j]) & 
                    (bird_data['Date'] < phase_change_dates[j + 1])
                ]
                if not segment.empty:
                    segments.append(segment)
            
            # Last segment: after last phase change
            last_segment = bird_data[bird_data['Date'] >= phase_change_dates[-1]]
            if not last_segment.empty:
                segments.append(last_segment)
            
            # Plot each segment separately
            for seg_idx, segment in enumerate(segments):
                if not segment.empty:
                    ax.plot(
                        segment['Date'], 
                        segment['Feeder Visits'], 
                        marker=bird_markers.get(bird, 'o'),
                        markersize=8,
                        markerfacecolor=marker_color,
                        markeredgecolor=edge_color,
                        markeredgewidth=1.5,
                        linewidth=1,
                        color=line_color,
                        label=bird if seg_idx == 0 else "",  # Only label first segment
                        alpha=0.7, 
                    )
        else:
            # No phase change, plot normally
            ax.plot(
                bird_data['Date'], 
                bird_data['Feeder Visits'], 
                marker='o', 
                markersize=8,
                markerfacecolor=marker_color,
                markeredgecolor=edge_color,
                markeredgewidth=1.5,
                linewidth=1,
                color=line_color,
                label=bird, 
                alpha=0.7
            )
    
    # Add phase change vertical lines for this location.
    # First collect each label with its anchor date (drawing the vertical
    # lines as we go), then place the labels staggered across a few height
    # tiers so adjacent phase annotations never overlap - this scales as
    # more phases accumulate, instead of colliding once dates get dense.
    phase_labels = []  # list of (anchor_date, label_text)
    for _, phase_row in location_phase_changes.iterrows():
        change_date = pd.to_datetime(phase_row['DateChangeStarted'])
        description = phase_row['DescriptionOfChange']

        # Find the date before the change date
        location_dates = location_data['Date'].unique()
        location_dates = pd.to_datetime(location_dates)
        location_dates = np.sort(location_dates)

        before_change_idx = np.where(location_dates < change_date)[0]
        if len(before_change_idx) > 0:
            date_before = location_dates[before_change_idx[-1]]
            halfway_date = date_before + (change_date - date_before) / 2

            ax.axvline(x=halfway_date, color='black', linestyle='-', linewidth=1.5, alpha=0.8)

            anchor_date = halfway_date + pd.Timedelta(days=0.5)
            if len(description.split(" ")) <= 2:
                label_text = description.replace(" ", "\n")
            else:
                label_text = description.replace(" (", "\n(")
            phase_labels.append((anchor_date, label_text))

    # Add "Seed" baseline label at the beginning (to the right of y-axis)
    if not location_data.empty:
        first_date = pd.to_datetime('2025-09-22')
        phase_labels.append((first_date + pd.Timedelta(days=0.5), 'Seed'))

    # Place labels staggered across height tiers. The number of tiers grows
    # with how tightly the phases are packed relative to the axis span, so
    # labels only step down as far as needed to stay clear of each other.
    # Positions use the x-axis transform (data x, axes-fraction y) so labels
    # sit in the upper band regardless of the log y-scale.
    phase_labels.sort(key=lambda x: x[0])
    if phase_labels:
        xs = np.array([mdates.date2num(pd.to_datetime(a)) for a, _ in phase_labels])
        span = (xs.max() - xs.min()) or 1.0
        min_gap = np.min(np.diff(xs)) if len(xs) > 1 else span
        n_tiers = int(np.clip(np.ceil(span / max(min_gap * 6, 1)), 1, 4))
        tier_y = np.linspace(0.97, 0.97 - 0.09 * (n_tiers - 1), n_tiers)
        for k, (anchor_date, label_text) in enumerate(phase_labels):
            ax.text(anchor_date, tier_y[k % n_tiers], label_text,
                    transform=ax.get_xaxis_transform(),
                    rotation=0, ha='left', va='top', fontsize=10, linespacing=0.9,
                    bbox=dict(boxstyle='round,pad=0.15', fc='white', ec='none', alpha=0.6))

    # Set labels and formatting for each subplot
    # Only show ylabel on left column (i % 2 == 0)
    ax.set_ylabel('Number of Visits', fontsize=28, labelpad=12)
    if i == 3:
        ax.set_xlabel('Date', fontsize=28, labelpad=12)
    else:
        ax.set_xlabel('')
    ax.set_title(location, fontsize=22, fontweight='bold', pad=20)
    
    # X-axis dates: matplotlib's auto date locator picks a readable number
    # of month ticks that stays clean as more days accumulate.
    ax.tick_params(labelsize=12)
    ax.tick_params(rotation=45, axis='x', pad=10)
    for label in ax.get_xticklabels():
        label.set_fontweight('normal')
        label.set_fontfamily('sans-serif')
    
    ax.set_ylim(0.8, 1000)
    ax.set_yscale('log')
    ax.set_yticks([1, 10, 100, 1000])
    ax.set_yticklabels(['1', '10', '100', '1000'])
    sns.despine(top=True, right=True)
    
    if i==0:
        handles, labels = ax.get_legend_handles_labels()
        labels_sorted, handles_sorted = zip(*sorted(zip(labels, handles), key=lambda x: x[0].lower()))
        ax.legend(handles_sorted, labels_sorted, loc=(1.02, 0.0), frameon=False, fontsize=10, ncol=2)
    else:
        handles, labels = ax.get_legend_handles_labels()
        labels_sorted, handles_sorted = zip(*sorted(zip(labels, handles), key=lambda x: x[0].lower()))
        ax.legend(handles_sorted, labels_sorted, loc=(1.02, 0.1), frameon=False, fontsize=10, ncol=1)
plt.tight_layout()
plt.subplots_adjust(wspace=1, hspace=0.3)

# Print birds that need specific colors
if birds_needing_colors:
    print("\nBirds that need specific colors added to bird_colors dictionary:")
    for bird in birds_needing_colors:
        print(f"    '{bird}'")
else:
    print("\nAll birds have predefined colors.")

# --- Cell 6 ---
# Save species visits plot for dashboard
save_plot_for_dashboard(
    fig, 
    'species_visits_by_date', 
    'Daily Bird Feeder Visits by Species',
    'Line plot showing daily feeder visits for each bird species with custom color coding'
)
plt.close('all')


# ## Set up data for heatmap plots

# --- Cell 8 ---
print("Building heatmap data...")
# Build complete data and plot 3D surface using helpers for each location
_time_bins, _time_labels = build_time_bins()

# Dictionary to store data for each location
location_data = {}

# Get unique locations
locations = raw_data['source_sheet'].unique()

# Prepare complete data for each location
for location in locations:
    location_raw_data = raw_data[raw_data['source_sheet'] == location]
    complete_data, time_labels, dates, time_bin_indices, grouped_data = prepare_complete_data(location_raw_data, _time_bins)
    
    location_data[location] = {
        'complete_data': complete_data,
        'time_labels': time_labels,
        'dates': dates,
        'time_bin_indices': time_bin_indices,
        'grouped_data': grouped_data
    }

# --- Cell 9 ---
# Plot heatmaps for each location
fig = plot_heatmap_counts_subplots(location_data)

# Save heatmap plots for dashboard
save_plot_for_dashboard(
    fig, 
    'heatmap_counts', 
    'Heatmap: Date vs Time of Day as a Count of Observations',
    'Heatmap showing bird activity patterns across dates and times of day for each location'
)
plt.close('all')

# --- Cell 10 ---
# Plot proportions heatmaps for each location
fig = plot_heatmap_proportions_subplots(location_data)

# Save proportions heatmap for dashboard
save_plot_for_dashboard(
    fig, 
    'heatmap_proportions', 
    'Heatmap: Date vs Time of Day as a Proportion of Observations',
    'Heatmap showing proportional bird activity patterns across dates and times of day for each location'
)
plt.close('all')

# --- Cell 11 ---
# # Load sunrise/sunset data
# sunrise_sunset_df = load_sunrise_sunset_data()

# # Prepare data for each location
# location_data = {}
# for location in raw_data['source_sheet'].unique():
#     location_df = raw_data[raw_data['source_sheet'] == location]
#     complete_data, bin_labels, dates, time_bin_indices = prepare_relative_time_data(
#         location_df, 
#         sunrise_sunset_df,
#         location_col='source_sheet',
#         n_bins=30
#     )
#     location_data[location] = {
#         'complete_data': complete_data,
#         'bin_labels': bin_labels
#     }

# # Plot the heatmap
# fig = plot_heatmap_relative_time_proportions(location_data)

# # Save proportions heatmap for dashboard
# save_plot_for_dashboard(
#     fig, 
#     'heatmap_proportions_sunrise_sunset', 
#     'Heatmap: Date vs Relative Time Sunrise-Sunset as a Proportion of Observations',
#     'Heatmap showing proportional bird activity patterns across dates and relative times to sunrise-sunset for each location'
# )


# # Weather-Related Plots

# --- Cell 13 ---
print("Processing weather data...")
# Read in weather data
weather_data = pd.read_csv('../data/hourly_weather.csv')
weather_data = weather_data[[
    'location', 'observed_dt_local', 
    'temp', 'feels_like',	'pressure',	'humidity',	'dew_point', 'clouds',
    'uvi', 'visibility', 'wind_speed', 'wind_gust', 'wind_deg',
    'rain_1h_mm', 'snow_1h_mm'
]]
weather_data['observed_dt_local'] = pd.to_datetime(weather_data['observed_dt_local'], utc=True, errors='coerce')
weather_data['date'] = weather_data['observed_dt_local'].dt.date
weather_data['hour'] = weather_data['observed_dt_local'].dt.hour
weather_data['location'] = weather_data['location'].astype(str).str.strip()
weather_data = weather_data.sort_values(['location', 'date', 'hour'])
weather_data.reset_index(drop=True, inplace=True)
weather_data = weather_data.drop(['observed_dt_local'], axis=1).fillna(0)
weather_data['date'] = weather_data['date'].astype(str)
weather_data['hour'] = weather_data['hour'].astype(int)

# Prep raw data for merge
raw_weather_data = raw_data.copy()
raw_weather_data = raw_weather_data[['Date', 'Time', 'Bird', 'source_sheet']].dropna(subset=['Time']).reset_index(drop=True)
raw_weather_data['Time'] = pd.to_datetime(raw_weather_data['Time'])
raw_weather_data['hour'] = raw_weather_data['Time'].dt.hour
raw_weather_data['hour'] = raw_weather_data['hour'].astype(int)
raw_weather_data.columns = ['date', 'time', 'bird', 'location', 'hour']
raw_weather_data['date'] = raw_weather_data['date'].astype(str)


# Merge weather data with raw data
raw_weather_data = raw_weather_data.merge(weather_data, on=['location', 'date', 'hour'], how='left')

# --- Cell 14 ---
def prepare_hourly_data(df, species=None):
    """
    Aggregate row-level visit data to hourly counts + mean weather.

    Parameters
    ----------
    df : DataFrame
        Raw data with one row per visit.
    species : str or None
        If given, filter to that species first.

    Returns
    -------
    agg : DataFrame
        One row per (location, bird, date, hour) with count + weather features.
    X : DataFrame
        Design matrix of predictors.
    y : Series
        Visit count per hour.
    """
    if species is not None:
        df = df[df["bird"] == species].copy()

    # Ensure we only keep rows with all needed weather columns
    cols_needed = ["location", "bird", "date", "hour"] + WEATHER_COLS
    df = df[cols_needed].copy()

    # Aggregate to hourly counts and mean weather
    agg = (
        df
        .groupby(["location", "bird", "date", "hour"], as_index=False)
        .agg(
            visits=("bird", "size"),
            **{col: (col, "mean") for col in WEATHER_COLS}
        )
    )

    # Add time-of-day features (optional but helps models)
    agg["hour_sin"] = np.sin(2 * np.pi * agg["hour"] / 24)
    agg["hour_cos"] = np.cos(2 * np.pi * agg["hour"] / 24)

    feature_cols = WEATHER_COLS + ["hour_sin", "hour_cos"]
    X = agg[feature_cols].copy()
    y = agg["visits"].astype(float)

    # Apply min-max scaling to features
    scaler = MinMaxScaler()
    X_scaled = scaler.fit_transform(X)
    X = pd.DataFrame(X_scaled, columns=feature_cols, index=X.index)

    return agg, X, y


# --- Cell 15 ---
def get_models():
    """
    Return a dictionary of modeling approaches.
    Keys are model names, values are sklearn estimators or pipelines.
    """
    models = {}

    # Poisson regression (GLM-like). No scaling strictly needed, but harmless.
    models["Poisson"] = make_pipeline(
        StandardScaler(with_mean=False),
        PoissonRegressor(alpha=1e-6, max_iter=2000)
    )

    # Linear baseline (Ridge regression) for comparison
    models["Ridge"] = make_pipeline(
        StandardScaler(),
        Ridge(alpha=1.0)
    )

    # Random Forest
    models["RandomForest"] = RandomForestRegressor(
        n_estimators=1000,
        max_depth=None,
        min_samples_leaf=2,
        random_state=112225
    )

    # Gradient Boosting (fast, good default)
    models["HistGB"] = HistGradientBoostingRegressor(
        max_depth=None,
        learning_rate=0.05,
        max_iter=100,
        random_state=112225
    )

    # Neural network
    models["MLP"] = make_pipeline(
        StandardScaler(),
        MLPRegressor(
            hidden_layer_sizes=(128, 64, 64, 64, 32),
            activation="relu",
            solver="adam",
            max_iter=1000,
            random_state=112225,
            early_stopping=True, 
            alpha=0.0001, 
            learning_rate="adaptive", 
            batch_size='auto',
        )
    )

    return models


def evaluate_models_cv(X, y, models=None, cv_splits=5, use_cv_for_poisson=False):
    """
    For each model, get predictions (via cross-validation where appropriate)
    and residuals.

    Returns
    -------
    results : dict
        results[model_name] = {
            "y_pred": np.array,
            "residuals": np.array
        }
    """
    if models is None:
        models = get_models()

    cv = KFold(n_splits=cv_splits, shuffle=True, random_state=42)
    results = {}

    for name, estimator in models.items():
        if name == "Poisson" and not use_cv_for_poisson:
            # Fit once on full data, predict in-sample
            estimator.fit(X, y)
            y_pred = estimator.predict(X)
        else:
            # Out-of-fold predictions via cross-validation
            y_pred = cross_val_predict(
                estimator, X, y, cv=cv, n_jobs=-1, method="predict"
            )

        residuals = y - y_pred
        results[name] = {"y_pred": y_pred, "residuals": residuals}

    return results


# --- Cell 16 ---
def plot_model_comparison_grid(y, results, suptitle=None):
    """
    Create a 2 x N grid where N = number of models.

    Top row: Observed vs Predicted
    Bottom row: Residual vs Predicted
    """
    model_names = list(results.keys())
    n_models = len(model_names)

    fig, axes = plt.subplots(
        2, n_models, figsize=(4 * n_models, 8), sharey="row", sharex=True,
    )

    if n_models == 1:
        # Ensure 2xN indexing even when N=1
        axes = np.array(axes).reshape(2, 1)

    y = np.asarray(y)

    for j, name in enumerate(model_names):
        y_pred = np.asarray(results[name]["y_pred"])
        residuals = np.asarray(results[name]["residuals"])

        # Top: observed vs predicted
        ax_top = axes[0, j]
        ax_top.scatter(y_pred, y, alpha=0.4, s=10, color='black')
        min_val = min(y.min(), y_pred.min())
        max_val = max(y.max(), y_pred.max())
        ax_top.plot([min_val, max_val], [min_val, max_val], "k--", linewidth=1)
        ax_top.set_xlabel("", fontsize=20, labelpad=12)
        if j == 0:
            ax_top.set_ylabel("Observed visits", fontsize=20, labelpad=12)
        ax_top.set_title(name, fontsize=20, fontweight='bold')
        ax_top.set_xscale('log')
        ax_top.set_yscale('log')

        # Bottom: residuals vs predicted
        ax_bottom = axes[1, j]
        ax_bottom.scatter(y_pred, residuals, alpha=0.4, s=10, color='black')
        ax_bottom.axhline(0.0, color="k", linestyle="--", linewidth=1)
        ax_bottom.set_xlabel("Predicted visits", fontsize=20, labelpad=12)
        if j == 0:
            ax_bottom.set_ylabel("Residual (obs - pred)", fontsize=20, labelpad=12)
        ax_bottom.set_xscale('log')
        ax_bottom.set_yscale('symlog')

    if suptitle:
        fig.suptitle(suptitle, fontsize=16)
    fig.tight_layout()
    return fig


# --- Cell 17 ---
WEATHER_COLS = [
    "temp", "feels_like", "pressure", "humidity", "dew_point",
    "clouds", "uvi", "visibility", "wind_speed", "wind_gust",
    "wind_deg", "rain_1h_mm", "snow_1h_mm"
]

# agg_all, X_all, y_all = prepare_hourly_data(raw_weather_data.fillna(0))
# models = get_models()
# results_all = evaluate_models_cv(X_all, y_all, models=models, cv_splits=5)

# fig = plot_model_comparison_grid(y_all, results_all)
# # plot_model_comparison_grid(y_gt, results_gt, suptitle="Great tit")

# save_plot_for_dashboard(
#     fig, 
#     'visit_predict_from_weather', 
#     'Can We Predict Visits from Weather?',
#     'Test models to predict visits from weather'
# )

# --- Cell 18 ---
# def plot_correlation_matrix(df, location_name, axes, n_vars, numeric_cols):
#     # Get data for this location
#     location_data = df[df['location'] == location_name][numeric_cols].copy()
    
#     for i in range(n_vars):
#         for j in range(n_vars):
#             ax = axes[i, j]
            
#             # --- PLOTTING ---
#             if i == j:
#                 # Diagonal: Histogram
#                 ax.hist(location_data[numeric_cols[i]], bins=20, edgecolor='black', alpha=0.7)
#             elif i > j:
#                 # Lower diagonal: Scatter
#                 sns.regplot(data=location_data, x=numeric_cols[j], y=numeric_cols[i], 
#                            ax=ax, scatter_kws={'alpha': 0.3, 's': 4}, 
#                            line_kws={'color': 'black', 'linewidth': 1}, ci=95)
#             else:
#                 # Upper diagonal: Correlation
#                 # Handle NaNs for correlation calculation
#                 valid_idx = location_data[numeric_cols[j]].notna() & location_data[numeric_cols[i]].notna()
#                 if valid_idx.sum() > 1:
#                     corr = location_data.loc[valid_idx, numeric_cols[j]].corr(location_data.loc[valid_idx, numeric_cols[i]])
#                     ax.text(0.5, 0.5, f'{corr:.2f}', 
#                                  ha='center', va='center', fontsize=10, fontweight='bold')
#                 ax.axis('off')

#             # --- CLEANING LABELS (Crucial for spacing) ---
#             # Only show Y labels for the first column (j==0)
#             if j == 0:
#                 ax.set_ylabel(numeric_cols[i], fontsize=9, labelpad=10)
#                 ax.tick_params(axis='y', labelsize=6)
#             else:
#                 ax.set_ylabel('')
#                 ax.set_yticklabels([]) # Hide ticks
                
#             # Only show X labels for the last row (i==n_vars-1)
#             if i == n_vars - 1:
#                 ax.set_xlabel(numeric_cols[j], fontsize=9, labelpad=10)
#                 ax.tick_params(axis='x', labelsize=6, rotation=90) # Rotate x labels for space
#             else:
#                 ax.set_xlabel('')
#                 ax.set_xticklabels([]) # Hide ticks

# # --- MAIN SETUP ---

# # Get numeric columns
# exclude_cols = ['date', 'time', 'bird', 'location']
# numeric_cols = raw_weather_data.select_dtypes(include=[np.number]).columns.tolist()
# numeric_cols = [col for col in numeric_cols if col not in exclude_cols]
# n_vars = len(numeric_cols)

# locations = sorted(raw_weather_data['location'].unique())
# n_locations = len(locations)

# # Create figure
# # Increased height to accommodate the stack
# fig = plt.figure(figsize=(18, 18 * n_locations)) 

# # Outer Grid: 3 Rows, 1 Column
# gs = gridspec.GridSpec(n_locations, 1, figure=fig, hspace=0.2)

# for idx, location in enumerate(locations):
#     # --- FIX 1: Add wspace/hspace here ---
#     # This pushes the subplots APART within the matrix
#     gs_sub = gridspec.GridSpecFromSubplotSpec(n_vars, n_vars, subplot_spec=gs[idx], 
#                                               wspace=0.1, hspace=0.1)
    
#     axes = np.empty((n_vars, n_vars), dtype=object)
    
#     # Create axes
#     for i in range(n_vars):
#         for j in range(n_vars):
#             axes[i, j] = fig.add_subplot(gs_sub[i, j])
            
#     # Run Plotter
#     plot_correlation_matrix(raw_weather_data, location, axes, n_vars, numeric_cols)

#     # Add Title for the whole block
#     box = gs[idx].get_position(fig)
#     fig.text(0.5, box.y1 + 0.005, location, ha='center', va='bottom', fontsize=20, fontweight='bold')

# plt.tight_layout()
# plt.subplots_adjust(hspace=0.1)
# plt.show()

# --- Cell 19 ---
# save_plot_for_dashboard(
#     fig,
#     'cor_plot_weather_data',
#     'Correlation Matrix of Weather Data by Location',
#     'Correlation matrix showing a regresson plot (lower diagonal), histogram (diagonal), and correlation coefficient (upper diagonal).'
# )
# plt.close('all')

# --- Cell 20 ---
print("Generating weather cluster plots...")
def build_species_weather_matrix(agg, temp_bins=10, wind_bins=10):
    """
    Build a species x (temp_bin x wind_bin) matrix of mean visit rates.
    """
    # Bin temperature and wind speed
    agg = agg.copy()
    agg["temp_bin"] = pd.cut(agg["temp"], bins=temp_bins)
    agg["wind_bin"]  = pd.cut(agg["wind_speed"], bins=wind_bins)

    # Filter to only birds with a certain number of visits. 
    bird_counts = agg.groupby("bird")["visits"].sum()
    birds_to_keep = bird_counts[bird_counts >= 50].index
    agg = agg[agg["bird"].isin(birds_to_keep)].reset_index(drop=True)

    pivot = (
        agg
        .groupby(["bird", "temp_bin", "wind_bin"])
        .agg(mean_visits=("visits", "mean"))
        .reset_index()
        .pivot_table(
            index="bird",
            columns=["temp_bin", "wind_bin"],
            values="mean_visits",
            fill_value=0.0
        )
    )
    return pivot


def cluster_species_by_weather(pivot, n_clusters=None):
    """
    Cluster species based on their temp x wind speed profiles.
    Returns linkage matrix and order.
    """
    # Convert to z-scores across columns
    X = StandardScaler().fit_transform(pivot.values)

    # Hierarchical clustering
    Z = linkage(X, method="ward")
    return Z


def plot_species_clustermap(pivot, Z):
    """
    Plot a clustered heatmap of species x weather bins.
    """
    # Use the linkage to order the rows
    fig = sns.clustermap(
        pivot,
        row_linkage=Z,
        col_cluster=False,
        cmap="gray_r", 
        cbar_pos=(1.0, 0.275, 0.03, 0.6)  # (left, bottom, width, height) in figure coordinates
    )
    # Set labels
    fig.ax_heatmap.set_xlabel("Temperature × Wind Speed Bins", fontsize=30, y=0)
    fig.ax_heatmap.set_ylabel("", fontsize=20, x=0)

    return fig

agg_all, X_all, y_all = prepare_hourly_data(raw_weather_data.fillna(0))
pivot = build_species_weather_matrix(agg_all, temp_bins=10, wind_bins=10)
Z = cluster_species_by_weather(pivot)
fig = plot_species_clustermap(pivot, Z)

save_plot_for_dashboard(
    fig, 
    'species_cluster_visits_by_weather', 
    'Species Clustermap Using Visits and Weather',
    'Species clusters by weather'
)
plt.close('all')

# --- Cell 21 ---
def plot_weather_contours(agg, x_col="temp", y_col="wind_speed",
                          x_bins=20, y_bins=20, species=None):
    """
    2D contour / heatmap of mean visit rate as a function of (x_col, y_col).
    If species is None, plot for each species in agg['bird'].
    Normalized to 0-1 proportions within each species.
    """
    if species is None:
        val_counts = agg["bird"].value_counts().reset_index()
        val_counts.columns = ["bird", "count"]
        val_counts = val_counts[val_counts["count"] > 10]
        species_list = sorted(val_counts["bird"].unique())
    else:
        species_list = [species]

    n_species = len(species_list)
    n_cols = min(n_species, 5)
    n_rows = int(np.ceil(n_species / n_cols))
    fig, axes = plt.subplots(
        n_rows, n_cols, figsize=(5 * n_cols, 4 * n_rows), squeeze=False, 
        sharex=True, sharey=True
    )

    # Second pass: create plots with normalized proportions
    contour_objects = []
    for i, sp in enumerate(species_list):
        ax = axes[i // n_cols, i % n_cols]
        sub = agg[agg["bird"] == sp]

        # Bin
        x = sub[x_col].values
        # Convert temperature from Celsius to Fahrenheit if x_col is "temp"
        if x_col == "temp":
            x = (x * 9/5) + 32
        y = sub[y_col].values
        z = sub["visits"].values

        x_edges = np.linspace(x.min(), x.max(), x_bins + 1)
        y_edges = np.linspace(y.min(), y.max(), y_bins + 1)

        # Digitize to grid
        x_idx = np.digitize(x, x_edges) - 1
        y_idx = np.digitize(y, y_edges) - 1

        grid = np.full((x_bins, y_bins), np.nan)
        counts = np.zeros_like(grid)

        for xi, yi, zi in zip(x_idx, y_idx, z):
            if 0 <= xi < x_bins and 0 <= yi < y_bins:
                if np.isnan(grid[xi, yi]):
                    grid[xi, yi] = 0.0
                grid[xi, yi] += zi
                counts[xi, yi] += 1

        # Mean visits per bin
        with np.errstate(invalid="ignore", divide="ignore"):
            grid_mean = grid / counts
        grid_mean[np.isnan(grid_mean)] = 0.0
        
        # Normalize to 0-1 proportions within this species
        grid_max = grid_mean.max()
        if grid_max > 0:
            grid_mean = grid_mean / grid_max
        else:
            grid_mean = grid_mean  # Already all zeros

        Xc, Yc = np.meshgrid(
            0.5 * (x_edges[:-1] + x_edges[1:]),
            0.5 * (y_edges[:-1] + y_edges[1:]),
            indexing="ij"
        )

        cf = ax.contourf(Xc, Yc, grid_mean, levels=15, vmin=0, vmax=1, cmap='gray_r')
        contour_objects.append(cf)
        ax.set_title(sp)

    # Remove any empty subplots
    for j in range(i + 1, n_rows * n_cols):
        fig.delaxes(axes[j // n_cols, j % n_cols])

    # Configure ticks: show ticks and labels on all subplots
    for row in range(n_rows):
        for col in range(n_cols):
            if row < axes.shape[0] and col < axes.shape[1]:
                try:
                    ax = axes[row, col]
                    if ax in fig.axes:  # Check if axis still exists (not deleted)
                        # Show ticks and labels on all subplots
                        ax.tick_params(which='both', bottom=True, top=False, left=True, right=False, 
                                     labelbottom=True, labelleft=True)
                except (IndexError, AttributeError):
                    pass

    # Add single xlabel and ylabel for entire figure
    # Determine unit based on x_col
    if x_col == "temp":
        x_unit = "°F"
    else:
        x_unit = "°C"  # Keep original unit for other columns
    fig.supxlabel(f"{x_col.capitalize()} ({x_unit})", fontsize=40, y=0.05)
    fig.supylabel(f"{y_col.replace('_', ' ').capitalize()} (km/h)", fontsize=40, x=0.075)

    # Reserve space for colorbar BEFORE creating it
    fig.subplots_adjust(right=0.88, hspace=0.3)
    
    # Create colorbar in the reserved space
    cbar = fig.colorbar(contour_objects[-1], ax=axes, label="\nProportion of Visits\n(normalized)", 
                        location='right', pad=0.02, shrink=0.8)
    cbar.ax.yaxis.label.set_fontsize(40)
    for label in cbar.ax.get_yticklabels():
        label.set_fontsize(20)
    
    sns.despine(top=True, right=True)
    return fig

agg_all, X_all, y_all = prepare_hourly_data(raw_weather_data.fillna(0))
fig = plot_weather_contours(agg_all, x_col="temp", y_col="wind_speed")

save_plot_for_dashboard(
    fig, 
    'prop_visits_wind_temp', 
    'Proportion of visits by wind speed and temperature',
    'Proportion of visits by wind speed and temperature'
)
plt.close('all')


# # Bout Analyses

# --- Cell 23 ---
print("Running bout analyses...")
# Add inter-visit interval (IVI) data 
raw_data_ivi = pd.DataFrame()
for location in raw_data['source_sheet'].unique():
    location_data = raw_data[raw_data['source_sheet'] == location].copy()
    
    # Convert to datetime
    location_data['Date'] = pd.to_datetime(location_data['Date'])
    location_data['Time'] = pd.to_datetime(location_data['Time'])
    
    # Combine date and time, handling NaT values
    location_data['date_time'] = location_data['Date'] + pd.to_timedelta(location_data['Time'].dt.hour, unit='h') + pd.to_timedelta(location_data['Time'].dt.minute, unit='m') + pd.to_timedelta(location_data['Time'].dt.second, unit='s')
    location_data = location_data.sort_values(by='date_time', ascending=True).reset_index(drop=True)
    
    # Calculate IVI (inter-visit interval) in minutes
    location_data['IVI (mins)'] = location_data['date_time'].diff().dt.total_seconds() / 60
    
    raw_data_ivi = pd.concat([raw_data_ivi, location_data])

raw_data_ivi = raw_data_ivi.dropna(subset=['IVI (mins)']).reset_index(drop=True)

# --- Cell 24 ---
# --- normalize in place ---
raw_data_ivi['source_sheet'] = raw_data_ivi['source_sheet'].astype(str).str.strip()
raw_data_ivi['Date'] = pd.to_datetime(raw_data_ivi['Date'], errors='coerce')

phase_changes['LocationOfChange'] = phase_changes['LocationOfChange'].astype(str).str.strip()
phase_changes['DateChangeStarted'] = pd.to_datetime(phase_changes['DateChangeStarted'], errors='coerce')

BASELINE = 'Seed'

def to_condition(txt: str) -> str:
    t = str(txt).lower()
    if 'seed' in t and 'extinct' not in t:
        return 'Seed'
    if 'extinct' in t or 'extinction' in t or 'no seed' in t:
        return 'No Seed'
    return 'No Seed'

phase_changes['Condition'] = phase_changes['DescriptionOfChange'].map(to_condition)

# Will hold the result keyed by the existing index of raw_data_ivi
seed_status = pd.Series(index=raw_data_ivi.index, dtype=object)

for loc, sub in raw_data_ivi.groupby('source_sheet'):
    loc_idx = sub.index
    dates = sub['Date'].to_numpy(dtype='datetime64[ns]')

    pc = (phase_changes
          .loc[phase_changes['LocationOfChange'].eq(loc),
               ['DateChangeStarted','Condition']]
          .sort_values('DateChangeStarted'))

    if pc.empty:
        seed_status.loc[loc_idx] = BASELINE
        continue

    change_dates = pc['DateChangeStarted'].to_numpy(dtype='datetime64[ns]')
    labels = pc['Condition'].to_numpy(object)

    # most recent change at or before each date (ties -> apply new change now)
    ix = np.searchsorted(change_dates, dates, side='right') - 1

    loc_status = np.where(ix >= 0, labels[np.clip(ix, 0, len(labels)-1)], BASELINE)
    seed_status.loc[loc_idx] = loc_status

# write back to the original df
raw_data_ivi['SeedStatus'] = seed_status

# --- Cell 25 ---
from scipy.special import gammainc, gamma

def double_exponential_survivor(t, A1, lambda1, A2, lambda2):
    """Double exponential survivor function (current model)"""
    return A1 * np.exp(-lambda1 * t) + A2 * np.exp(-lambda2 * t)

def double_exponential_log_survivor(t, A1, lambda1, A2, lambda2):
    """Double exponential in log-space"""
    return np.log(A1 * np.exp(-lambda1 * t) + A2 * np.exp(-lambda2 * t) + 1e-10)

def double_gamma_pdf(x, Q, k_b, theta_b, k_w, theta_w):
    """Double-gamma probability density function from paper:
    p(IRT = x) = Q * [1 / (Γ(k_b) * θ_b^k_b)] * x^(k_b - 1) * e^(-x/θ_b)
                 + (1 - Q) * [1 / (Γ(k_w) * θ_w^k_w)] * x^(k_w - 1) * e^(-x/θ_w)
    """
    term_b = Q * (1.0 / (gamma(k_b) * (theta_b ** k_b))) * (x ** (k_b - 1)) * np.exp(-x / theta_b)
    term_w = (1.0 - Q) * (1.0 / (gamma(k_w) * (theta_w ** k_w))) * (x ** (k_w - 1)) * np.exp(-x / theta_w)
    return term_b + term_w

def double_gamma_survivor(t, Q, k_b, theta_b, k_w, theta_w):
    """Double-gamma survivor function: S(t) = 1 - CDF(t)
    where CDF is computed from the double-gamma PDF using incomplete gamma functions.
    
    For a gamma distribution with shape k and scale θ:
    CDF(x) = gammainc(k, x/θ) where gammainc is the regularized incomplete gamma function.
    """
    # Handle edge cases: ensure t is non-negative and parameters are valid
    t = np.maximum(t, 0)
    
    # CDF for gamma distribution: P(k, x/θ) where P is regularized incomplete gamma
    # gammainc(k, x) = P(k, x) = lower regularized incomplete gamma function
    cdf_b = gammainc(k_b, t / theta_b)  # CDF for between-bout component
    cdf_w = gammainc(k_w, t / theta_w)  # CDF for within-bout component
    cdf = Q * cdf_b + (1 - Q) * cdf_w
    
    # Survivor function: S(t) = 1 - CDF(t)
    # Ensure result is in valid range [0, 1] and handle numerical precision
    survivor = 1 - cdf
    survivor = np.clip(survivor, 1e-10, 1.0)  # Clip to avoid numerical issues
    
    return survivor

def double_gamma_log_survivor(t, Q, k_b, theta_b, k_w, theta_w):
    """Double-gamma survivor function in log-space for fitting"""
    return np.log(double_gamma_survivor(t, Q, k_b, theta_b, k_w, theta_w) + 1e-10)

# status → color (match what you want in the legend)
STATUS_PALETTE = [
    ('Seed', 'black'),
    ('No Seed', 'white'),
    ('Unknown', 'gray'),
]

# Get unique locations
locations = sorted(raw_data_ivi['source_sheet'].unique())
n_locations = len(locations)

# Create 2xN subplot layout (2 rows for fit types)
fig, axes = plt.subplots(2, n_locations, figsize=(6*n_locations, 10), sharey=True, sharex='col')
if n_locations == 1:
    axes = axes.reshape(2, 1)

def _dedupe_legend(ax):
    handles, labels = ax.get_legend_handles_labels()
    seen = set()
    h2, l2 = [], []
    for h, l in zip(handles, labels):
        if l not in seen:
            seen.add(l); h2.append(h); l2.append(l)
    ax.legend(h2, l2, loc='lower left', fontsize=10, frameon=False)

# Process each location
for col, location in enumerate(locations):
    # Get data for this location
    location_data = raw_data_ivi[raw_data_ivi['source_sheet'] == location]
    loc_df = location_data[['IVI (mins)', 'SeedStatus']].dropna().copy()
    if loc_df.empty:
        continue

    loc_df['SeedStatus'] = loc_df['SeedStatus'].fillna('Unknown')
    loc_df = loc_df.sort_values('IVI (mins)')

    # Survivor function inputs
    x = loc_df['IVI (mins)'].to_numpy()
    n = len(x)
    y = np.arange(n, 0, -1) / n
    status = loc_df['SeedStatus'].to_numpy()

    # Fitting
    time_points = x
    survivor = y
    initial_guess_current = [0.4, 0.5, 0.6, 0.02]
    # Initial guess for double-gamma model: Q=0.5, k_b=1.5, theta_b=2.0, k_w=1.0, theta_w=0.5
    # (k=1 gives exponential, so k>1 gives more flexibility)
    initial_guess_gamma = [0.5, 1.5, 2.0, 1.0, 0.5]

    try:
        # Current model: Linear-space fit
        popt_linear, pcov_linear = curve_fit(
            double_exponential_survivor, time_points, survivor,
            p0=initial_guess_current, maxfev=10000
        )
        y_pred_linear = double_exponential_survivor(time_points, *popt_linear)
        r_squared_linear = 1 - (np.sum((survivor - y_pred_linear) ** 2) /
                                np.sum((survivor - np.mean(survivor)) ** 2))
        mae_linear = float(np.mean(np.abs(survivor - y_pred_linear)))

        # Double-gamma model: Fit with bounds
        # Q in [0,1], k_b, k_w > 0 (shape parameters), theta_b, theta_w > 0 (scale parameters)
        popt_gamma, pcov_gamma = curve_fit(
            double_gamma_survivor, time_points, survivor,
            p0=initial_guess_gamma, maxfev=10000,
            bounds=([0, 0.1, 0.01, 0.1, 0.01], [1, 10, 100, 10, 10])
        )
        y_pred_gamma = double_gamma_survivor(time_points, *popt_gamma)
        r_squared_gamma = 1 - (np.sum((survivor - y_pred_gamma) ** 2) /
                               np.sum((survivor - np.mean(survivor)) ** 2))
        mae_gamma = float(np.mean(np.abs(survivor - y_pred_gamma)))

        # Log-space fit (current model)
        log_survivor = np.log(survivor + 1e-10)
        popt_log, pcov_log = curve_fit(
            double_exponential_log_survivor, time_points, log_survivor,
            p0=initial_guess_current, maxfev=10000
        )
        y_pred_log = double_exponential_log_survivor(time_points, *popt_log)
        y_pred_log_linear = np.exp(y_pred_log)
        r_squared_log = 1 - (np.sum((survivor - y_pred_log_linear) ** 2) /
                             np.sum((survivor - np.mean(survivor)) ** 2))
        mae_log = float(np.mean(np.abs(survivor - y_pred_log_linear)))

        # Double-gamma model: Log-space fit
        log_survivor = np.log(survivor + 1e-10)
        popt_gamma_log, pcov_gamma_log = curve_fit(
            double_gamma_log_survivor, time_points, log_survivor,
            p0=initial_guess_gamma, maxfev=10000,
            bounds=([0, 0.1, 0.01, 0.1, 0.01], [1, 10, 100, 10, 10])
        )
        # Transform back from log-space to linear-space for evaluation
        y_pred_gamma_log = double_gamma_survivor(time_points, *popt_gamma_log)
        r_squared_gamma_log = 1 - (np.sum((survivor - y_pred_gamma_log) ** 2) /
                                    np.sum((survivor - np.mean(survivor)) ** 2))
        mae_gamma_log = float(np.mean(np.abs(survivor - y_pred_gamma_log)))

        # Smooth fit curves
        t_smooth = np.linspace(0, x.max(), 200)
        y_smooth_linear = double_exponential_survivor(t_smooth, *popt_linear)
        y_smooth_gamma = double_gamma_survivor(t_smooth, *popt_gamma)
        y_smooth_log_linear = np.exp(double_exponential_log_survivor(t_smooth, *popt_log))
        # Transform back from log-space fit for plotting
        y_smooth_gamma_log = double_gamma_survivor(t_smooth, *popt_gamma_log)

        text_x = 0.95
        text_y = 0.65
        second_offset = 0.065

        # ---------- TOP: linear-space fit ----------
        ax1 = axes[0, col]
        ax1.semilogy(x, y, '-', linewidth=1, color='0.6', label=f'Observed ($N$={n})')

        # one scatter per SeedStatus (avoids long list for c=)
        for lbl, colr in STATUS_PALETTE:
            m = (status == lbl)
            if m.any():
                ax1.scatter(x[m], y[m], s=18, color=colr, edgecolor='black', zorder=3, label=lbl)

        ax1.semilogy(t_smooth, y_smooth_linear, '-', linewidth=2, color='red', label='Double Exponential Model')
        ax1.semilogy(t_smooth, y_smooth_gamma, '-', linewidth=2, color='blue', label='Double-Gamma Model')
        ax1.set_xlabel('')
        ax1.set_ylabel('')
        ax1.set_yticks([0.001, 0.01, 0.1, 1])
        ax1.set_yticklabels(['0.001', '0.01', '0.1', '1'], fontsize=16)
        ax1.tick_params(axis='x', labelsize=16)
        ax1.set_ylim(0.0001, 1.1)
        sns.despine(top=True, right=True, ax=ax1)

        # Add metrics for both models
        ax1.text(text_x, text_y, f'Double Exponential: $R^2 = {r_squared_linear:.3f}$, $MAE = {mae_linear:.3f}$',
                 transform=ax1.transAxes,
                 bbox=dict(boxstyle="round,pad=0.3", facecolor="white", alpha=0.1, edgecolor='white'),
                 fontsize=10, ha='right', color='red')
        ax1.text(text_x, text_y-second_offset, f'Double-Gamma Model: $R^2 = {r_squared_gamma:.3f}$, $MAE = {mae_gamma:.3f}$',
                 transform=ax1.transAxes,
                 bbox=dict(boxstyle="round,pad=0.3", facecolor="white", alpha=0.1, edgecolor='white'),
                 fontsize=10, ha='right', color='blue')
        ax1.set_title(f"{location}: Linear Space Fit", fontsize=16)
        _dedupe_legend(ax1)
        ax1.legend(loc='best', fontsize=10, frameon=False)

        # ---------- BOTTOM: log-space fit (shown in linear scale) ----------
        ax2 = axes[1, col]
        ax2.semilogy(x, y, '-', linewidth=1, color='0.6', label=f'Observed ($N$={n})')
        for lbl, colr in STATUS_PALETTE:
            m = (status == lbl)
            if m.any():
                ax2.scatter(x[m], y[m], s=18, color=colr, edgecolor='black', zorder=3, label=lbl)

        ax2.semilogy(t_smooth, y_smooth_log_linear, '-', linewidth=2, color='red', label='Double Exponential Model')
        ax2.semilogy(t_smooth, y_smooth_gamma_log, '-', linewidth=2, color='blue', label='Double-Gamma Model')
        ax2.set_xlabel('')
        ax2.set_ylabel('')
        ax2.set_yticks([0.0001, 0.001, 0.01, 0.1, 1])
        ax2.set_yticklabels(['0.0001', '0.001', '0.01', '0.1', '1'], fontsize=16)
        ax2.tick_params(axis='x', labelsize=16)
        ax2.set_ylim(0.00001, 1.1)
        sns.despine(top=True, right=True, ax=ax2)

        # Add metrics for both models
        ax2.text(text_x, text_y, f'Double Exponential: $R^2 = {r_squared_log:.3f}$, $MAE = {mae_log:.3f}$',
                 transform=ax2.transAxes,
                 bbox=dict(boxstyle="round,pad=0.3", facecolor="white", alpha=0.1, edgecolor='white'),
                 fontsize=10, ha='right', color='red')
        ax2.text(text_x, text_y-second_offset, f'Double-Gamma Model: $R^2 = {r_squared_gamma_log:.3f}$, $MAE = {mae_gamma_log:.3f}$',
                 transform=ax2.transAxes,
                 bbox=dict(boxstyle="round,pad=0.3", facecolor="white", alpha=0.1, edgecolor='white'),
                 fontsize=10, ha='right', color='blue')
        ax2.set_title(f"{location}: Log Space Fit", fontsize=16)
        _dedupe_legend(ax2)
        ax2.legend(loc='best', fontsize=10, frameon=False)

    except Exception as e:
        print(f"Error fitting data for {location}: {e}")
        axes[0, col].text(0.5, 0.5, f"Error fitting data\nfor {location}",
                          transform=axes[0, col].transAxes, ha='center', va='center')
        axes[1, col].text(0.5, 0.5, f"Error fitting data\nfor {location}",
                          transform=axes[1, col].transAxes, ha='center', va='center')

# Add single super labels
fig.supxlabel('Elapsed time, $t$ (mins)', fontsize=40, y=-0.0)
fig.supylabel('Proportion of IVIs > $t$', fontsize=40, x=0.0)

plt.tight_layout()
plt.subplots_adjust(hspace=0.2, wspace=0.05)

# --- Cell 26 ---
# Save bout analysis plot for dashboard
save_plot_for_dashboard(
    fig, 
    'all_birds_bout_analysis', 
    'All Birds: Bout Analysis',
    'Analysis of bout durations for all birds'
)
plt.close('all')

# --- Cell 27 ---
# Same plot as above but filtering out first IRT of each date (only using within-date IRTs)
# Filter raw_data_ivi to exclude the first IRT of each date (which represents cross-date interval)
raw_data_ivi_within_date = raw_data_ivi.copy()

# Group by location and date, then drop the first row of each group
# (the first row has the IVI from the previous date)
raw_data_ivi_within_date = (raw_data_ivi_within_date
    .sort_values(['source_sheet', 'Date', 'date_time'])
    .groupby(['source_sheet', 'Date'], group_keys=False)
    .apply(lambda x: x.iloc[1:] if len(x) > 1 else x)
    .reset_index(drop=True))

def double_exponential_survivor(t, A1, lambda1, A2, lambda2):
    """Double exponential survivor function"""
    return A1 * np.exp(-lambda1 * t) + A2 * np.exp(-lambda2 * t)

def double_exponential_log_survivor(t, A1, lambda1, A2, lambda2):
    """Double exponential in log-space"""
    return np.log(A1 * np.exp(-lambda1 * t) + A2 * np.exp(-lambda2 * t) + 1e-10)

# status → color (match what you want in the legend)
STATUS_PALETTE = [
    ('Seed', 'black'),
    ('No Seed', 'white'),
    ('Unknown', 'gray'),
]

# Get unique locations
locations = sorted(raw_data_ivi_within_date['source_sheet'].unique())
n_locations = len(locations)

# Create 2xN subplot layout (2 rows for fit types)
fig, axes = plt.subplots(2, n_locations, figsize=(6*n_locations, 10), sharey=True, sharex='col')
if n_locations == 1:
    axes = axes.reshape(2, 1)

def _dedupe_legend(ax):
    handles, labels = ax.get_legend_handles_labels()
    seen = set()
    h2, l2 = [], []
    for h, l in zip(handles, labels):
        if l not in seen:
            seen.add(l); h2.append(h); l2.append(l)
    ax.legend(h2, l2, loc='lower left', fontsize=10, frameon=False)

# Process each location
for col, location in enumerate(locations):
    # Get data for this location
    location_data = raw_data_ivi_within_date[raw_data_ivi_within_date['source_sheet'] == location]
    loc_df = location_data[['IVI (mins)', 'SeedStatus']].dropna().copy()
    if loc_df.empty:
        continue

    loc_df['SeedStatus'] = loc_df['SeedStatus'].fillna('Unknown')
    loc_df = loc_df.sort_values('IVI (mins)')

    # Survivor function inputs
    x = loc_df['IVI (mins)'].to_numpy()
    n = len(x)
    y = np.arange(n, 0, -1) / n
    status = loc_df['SeedStatus'].to_numpy()

    # Fitting
    time_points = x
    survivor = y
    initial_guess = [0.4, 0.5, 0.6, 0.02]

    try:
        # Linear-space fit
        popt_linear, pcov_linear = curve_fit(
            double_exponential_survivor, time_points, survivor,
            p0=initial_guess, maxfev=10000
        )
        y_pred_linear = double_exponential_survivor(time_points, *popt_linear)
        r_squared_linear = 1 - (np.sum((survivor - y_pred_linear) ** 2) /
                                np.sum((survivor - np.mean(survivor)) ** 2))
        mae_linear = float(np.mean(np.abs(survivor - y_pred_linear)))

        # Log-space fit
        log_survivor = np.log(survivor + 1e-10)
        popt_log, pcov_log = curve_fit(
            double_exponential_log_survivor, time_points, log_survivor,
            p0=initial_guess, maxfev=10000
        )
        y_pred_log = double_exponential_log_survivor(time_points, *popt_log)
        y_pred_log_linear = np.exp(y_pred_log)
        r_squared_log = 1 - (np.sum((survivor - y_pred_log_linear) ** 2) /
                             np.sum((survivor - np.mean(survivor)) ** 2))
        mae_log = float(np.mean(np.abs(survivor - y_pred_log_linear)))

        # Smooth fit curves
        t_smooth = np.linspace(0, x.max(), 200)
        y_smooth_linear = double_exponential_survivor(t_smooth, *popt_linear)
        y_smooth_log_linear = np.exp(double_exponential_log_survivor(t_smooth, *popt_log))

        text_x = 0.975
        text_y = 0.65

        # ---------- TOP: linear-space fit ----------
        ax1 = axes[0, col]
        ax1.semilogy(x, y, '-', linewidth=1, color='0.6', label=f'Observed ($N$={n})')

        # one scatter per SeedStatus (avoids long list for c=)
        for lbl, colr in STATUS_PALETTE:
            m = (status == lbl)
            if m.any():
                ax1.scatter(x[m], y[m], s=18, color=colr, edgecolor='black', zorder=3, label=lbl)

        ax1.semilogy(t_smooth, y_smooth_linear, '-', linewidth=2, color='red', label='Double Exponential')
        ax1.set_xlabel('')
        ax1.set_ylabel('')
        ax1.set_yticks([0.0001, 0.001, 0.01, 0.1, 1])
        ax1.set_yticklabels(['0.0001', '0.001', '0.01', '0.1', '1'], fontsize=16)
        ax1.tick_params(axis='x', labelsize=16)
        ax1.set_ylim(0.00001, 1.1)
        sns.despine(top=True, right=True, ax=ax1)

        eq1 = (f'$P(IVI>t) = {popt_linear[0]:.1f}e^{{-{popt_linear[1]:.2f}t}}'
               f' + {popt_linear[2]:.1f}e^{{-{popt_linear[3]:.2f}t}}$')
        ax1.text(text_x, text_y, eq1, transform=ax1.transAxes,
                 bbox=dict(boxstyle="round,pad=0.3", facecolor="white", alpha=0.8, edgecolor='white'),
                 fontsize=10, ha='right')
        ax1.text(text_x, text_y-0.1, f'$R^2 = {r_squared_linear:.3f}$\n$MAE = {mae_linear:.3f}$',
                 transform=ax1.transAxes,
                 bbox=dict(boxstyle="round,pad=0.3", facecolor="white", alpha=0.8, edgecolor='white'),
                 fontsize=10, ha='right')
        ax1.set_title(f"{location}: Linear Space Fit\n(Within-Date Only)", fontsize=16)
        _dedupe_legend(ax1)
        ax1.legend(loc='best', fontsize=10, frameon=False)

        # ---------- BOTTOM: log-space fit (shown in linear scale) ----------
        ax2 = axes[1, col]
        ax2.semilogy(x, y, '-', linewidth=1, color='0.6', label=f'Observed ($N$={n})')
        for lbl, colr in STATUS_PALETTE:
            m = (status == lbl)
            if m.any():
                ax2.scatter(x[m], y[m], s=18, color=colr, edgecolor='black', zorder=3, label=lbl)

        ax2.semilogy(t_smooth, y_smooth_log_linear, '-', linewidth=2, color='red', label='Double Exponential')
        ax2.set_xlabel('')
        ax2.set_ylabel('')
        ax2.set_yticks([0.0001, 0.001, 0.01, 0.1, 1])
        ax2.set_yticklabels(['0.0001', '0.001', '0.01', '0.1', '1'], fontsize=16)
        ax2.tick_params(axis='x', labelsize=16)
        ax2.set_ylim(0.00001, 1.1)
        sns.despine(top=True, right=True, ax=ax2)

        eq2 = (f'$P(IVI>t) = {popt_log[0]:.1f}e^{{-{popt_log[1]:.2f}t}}'
               f' + {popt_log[2]:.1f}e^{{-{popt_log[3]:.2f}t}}$')
        ax2.text(text_x, text_y, eq2, transform=ax2.transAxes,
                 bbox=dict(boxstyle="round,pad=0.3", facecolor="white", alpha=0.8, edgecolor='white'),
                 fontsize=10, ha='right')
        ax2.text(text_x, text_y-0.1, f'$R^2 = {r_squared_log:.3f}$\n$MAE = {mae_log:.3f}$',
                 transform=ax2.transAxes,
                 bbox=dict(boxstyle="round,pad=0.3", facecolor="white", alpha=0.8, edgecolor='white'),
                 fontsize=10, ha='right')
        ax2.set_title(f"{location}: Log Space Fit\n(Within-Date Only)", fontsize=16)
        _dedupe_legend(ax2)
        ax2.legend(loc='best', fontsize=10, frameon=False)

    except Exception as e:
        print(f"Error fitting data for {location}: {e}")
        axes[0, col].text(0.5, 0.5, f"Error fitting data\nfor {location}",
                          transform=axes[0, col].transAxes, ha='center', va='center')
        axes[1, col].text(0.5, 0.5, f"Error fitting data\nfor {location}",
                          transform=axes[1, col].transAxes, ha='center', va='center')

# Add single super labels
fig.supxlabel('Elapsed time, $t$ (mins)', fontsize=40, y=-0.0)
fig.supylabel('Proportion of IVIs > $t$', fontsize=40, x=0.0)

plt.tight_layout()
plt.subplots_adjust(hspace=0.2, wspace=0.05)


# --- Cell 28 ---
# Save bout analysis plot for dashboard
save_plot_for_dashboard(
    fig, 
    'all_birds_bout_analysis_within_date', 
    'All Birds: Bout Analysis (Within-Date Only)',
    'Analysis of bout durations for all birds (within-date only)'
)
plt.close('all')

# --- Cell 29 ---
def double_exponential_survivor(t, A1, lambda1, A2, lambda2):
    """Double exponential survivor function"""
    return A1 * np.exp(-lambda1 * t) + A2 * np.exp(-lambda2 * t)

def double_exponential_log_survivor(t, A1, lambda1, A2, lambda2):
    """Double exponential in log-space"""
    return np.log(A1 * np.exp(-lambda1 * t) + A2 * np.exp(-lambda2 * t) + 1e-10)

# Get unique locations
locations = sorted(raw_data_ivi['source_sheet'].unique())
n_locations = len(locations)

# Create 2xN subplot layout (2 rows for fit types)
fig, axes = plt.subplots(2, n_locations, figsize=(6*n_locations, 10), sharey=True, sharex=False)
if n_locations == 1:
    axes = axes.reshape(2, 1)

def _dedupe_legend(ax):
    handles, labels = ax.get_legend_handles_labels()
    seen = set()
    h2, l2 = [], []
    for h, l in zip(handles, labels):
        if l not in seen:
            seen.add(l); h2.append(h); l2.append(l)
    ax.legend(h2, l2, loc='lower left', fontsize=10, frameon=False)

def fit_model(df, initial_guess, use_log_space=False):
    """Helper function to fit model to a dataframe"""
    if df.empty or len(df) < 5:
        return None, None, None, None
    
    df = df.sort_values('IVI (mins)')
    x = df['IVI (mins)'].to_numpy()
    n = len(x)
    y = np.arange(n, 0, -1) / n
    time_points = x
    survivor = y
    
    try:
        if use_log_space:
            log_survivor = np.log(survivor + 1e-10)
            popt, pcov = curve_fit(
                double_exponential_log_survivor, time_points, log_survivor,
                p0=initial_guess, maxfev=10000
            )
            y_pred_log = double_exponential_log_survivor(time_points, *popt)
            y_pred = np.exp(y_pred_log)
        else:
            popt, pcov = curve_fit(
                double_exponential_survivor, time_points, survivor,
                p0=initial_guess, maxfev=10000
            )
            y_pred = double_exponential_survivor(time_points, *popt)
        
        r_squared = 1 - (np.sum((survivor - y_pred) ** 2) /
                         np.sum((survivor - np.mean(survivor)) ** 2))
        mae = float(np.mean(np.abs(survivor - y_pred)))
        
        return popt, pcov, r_squared, mae
    except Exception as e:
        return None, None, None, None

# Process each location
for col, location in enumerate(locations):
    # Get data for this location
    location_data = raw_data_ivi[raw_data_ivi['source_sheet'] == location]
    loc_df = location_data[['IVI (mins)', 'SeedStatus']].dropna().copy()
    if loc_df.empty:
        continue

    loc_df['SeedStatus'] = loc_df['SeedStatus'].fillna('Unknown')
    
    # Separate seed vs no seed data
    seed_df = loc_df[loc_df['SeedStatus'] == 'Seed'].copy()
    no_seed_df = loc_df[loc_df['SeedStatus'] == 'No Seed'].copy()
    
    initial_guess = [0.4, 0.5, 0.6, 0.02]
    
    # Fit models separately for seed and no seed
    popt_seed_linear, _, r2_seed_linear, mae_seed_linear = fit_model(seed_df, initial_guess, use_log_space=False)
    popt_seed_log, _, r2_seed_log, mae_seed_log = fit_model(seed_df, initial_guess, use_log_space=True)
    popt_no_seed_linear, _, r2_no_seed_linear, mae_no_seed_linear = fit_model(no_seed_df, initial_guess, use_log_space=False)
    popt_no_seed_log, _, r2_no_seed_log, mae_no_seed_log = fit_model(no_seed_df, initial_guess, use_log_space=True)
    
    # Get max time for smooth curves
    max_time = max(
        seed_df['IVI (mins)'].max() if not seed_df.empty else 0,
        no_seed_df['IVI (mins)'].max() if not no_seed_df.empty else 0
    )
    t_smooth = np.linspace(0, max_time, 200)
    
    text_x = 1
    text_y = 1.05
    
    # ---------- TOP: linear-space fit ----------
    ax1 = axes[0, col]
    
    # Plot seed data (black filled circles)
    if not seed_df.empty and len(seed_df) >= 5:
        seed_df_sorted = seed_df.sort_values('IVI (mins)')
        x_seed = seed_df_sorted['IVI (mins)'].to_numpy()
        n_seed = len(x_seed)
        y_seed = np.arange(n_seed, 0, -1) / n_seed
        ax1.semilogy(x_seed, y_seed, '-', linewidth=1, color='0.6', alpha=0.3)
        ax1.scatter(x_seed, y_seed, s=18, color='black', edgecolor='black', 
                   zorder=3, label=f'Seed ($N$={n_seed})', alpha=0.8)
        
        # Plot seed fit
        if popt_seed_linear is not None:
            y_smooth_seed = double_exponential_survivor(t_smooth, *popt_seed_linear)
            ax1.semilogy(t_smooth, y_smooth_seed, '-', linewidth=2, color='red', 
                        alpha=0.7, label='Seed Fit')
    
    # Plot no seed data (white/open circles)
    if not no_seed_df.empty and len(no_seed_df) >= 5:
        no_seed_df_sorted = no_seed_df.sort_values('IVI (mins)')
        x_no_seed = no_seed_df_sorted['IVI (mins)'].to_numpy()
        n_no_seed = len(x_no_seed)
        y_no_seed = np.arange(n_no_seed, 0, -1) / n_no_seed
        ax1.semilogy(x_no_seed, y_no_seed, '-', linewidth=1, color='0.6', alpha=0.3)
        ax1.scatter(x_no_seed, y_no_seed, s=18, facecolor='white', edgecolor='black', 
                   linewidth=1.5, zorder=3, label=f'No Seed ($N$={n_no_seed})', alpha=0.8)
        
        # Plot no seed fit
        if popt_no_seed_linear is not None:
            y_smooth_no_seed = double_exponential_survivor(t_smooth, *popt_no_seed_linear)
            ax1.semilogy(t_smooth, y_smooth_no_seed, '--', linewidth=2, color='blue', 
                        alpha=0.7, label='No Seed Fit')
    
    ax1.set_xlabel('')
    ax1.set_ylabel('')
    ax1.set_yticks([0.0001, 0.001, 0.01, 0.1, 1])
    ax1.set_yticklabels(['0.0001', '0.001', '0.01', '0.1', '1'], fontsize=16)
    ax1.tick_params(axis='x', labelsize=16)
    ax1.set_ylim(0.00001, 1.1)
    sns.despine(top=True, right=True, ax=ax1)
    
    # Add equations and metrics
    if popt_seed_linear is not None:
        eq_seed = (f'Seed: $P(IVI>t) = {popt_seed_linear[0]:.1f}e^{{-{popt_seed_linear[1]:.2f}t}}'
                  f' + {popt_seed_linear[2]:.1f}e^{{-{popt_seed_linear[3]:.2f}t}}$')
        ax1.text(text_x, text_y, eq_seed, transform=ax1.transAxes,
                 bbox=dict(boxstyle="round,pad=0.3", facecolor="white", alpha=0.8, edgecolor='white'),
                 fontsize=9, ha='right')
        ax1.text(text_x, text_y-0.08, f'Seed: $R^2 = {r2_seed_linear:.3f}$, $MAE = {mae_seed_linear:.3f}$',
                 transform=ax1.transAxes,
                 bbox=dict(boxstyle="round,pad=0.3", facecolor="white", alpha=0.8, edgecolor='white'),
                 fontsize=9, ha='right')
    
    if popt_no_seed_linear is not None:
        eq_no_seed = (f'No Seed: $P(IVI>t) = {popt_no_seed_linear[0]:.1f}e^{{-{popt_no_seed_linear[1]:.2f}t}}'
                     f' + {popt_no_seed_linear[2]:.1f}e^{{-{popt_no_seed_linear[3]:.2f}t}}$')
        y_offset = text_y - 0.16 if popt_seed_linear is not None else text_y
        ax1.text(text_x, y_offset, eq_no_seed, transform=ax1.transAxes,
                 bbox=dict(boxstyle="round,pad=0.3", facecolor="white", alpha=0.8, edgecolor='white'),
                 fontsize=9, ha='right')
        y_offset_metrics = text_y - 0.24 if popt_seed_linear is not None else text_y - 0.08
        ax1.text(text_x, y_offset_metrics, f'No Seed: $R^2 = {r2_no_seed_linear:.3f}$, $MAE = {mae_no_seed_linear:.3f}$',
                 transform=ax1.transAxes,
                 bbox=dict(boxstyle="round,pad=0.3", facecolor="white", alpha=0.8, edgecolor='white'),
                 fontsize=9, ha='right')
    
    ax1.set_title(f"{location}: Linear Space Fit", fontsize=16, pad=40)
    _dedupe_legend(ax1)
    ax1.legend(loc=(0.125, 0.85), fontsize=10, frameon=False)

    # ---------- BOTTOM: log-space fit (shown in linear scale) ----------
    ax2 = axes[1, col]
    
    # Plot seed data (black filled circles)
    if not seed_df.empty and len(seed_df) >= 5:
        seed_df_sorted = seed_df.sort_values('IVI (mins)')
        x_seed = seed_df_sorted['IVI (mins)'].to_numpy()
        n_seed = len(x_seed)
        y_seed = np.arange(n_seed, 0, -1) / n_seed
        ax2.semilogy(x_seed, y_seed, '-', linewidth=1, color='0.6', alpha=0.3)
        ax2.scatter(x_seed, y_seed, s=18, color='black', edgecolor='black', 
                   zorder=3, label=f'Seed ($N$={n_seed})', alpha=0.8)
        
        # Plot seed fit
        if popt_seed_log is not None:
            y_smooth_seed = np.exp(double_exponential_log_survivor(t_smooth, *popt_seed_log))
            ax2.semilogy(t_smooth, y_smooth_seed, '-', linewidth=2, color='red', 
                        alpha=0.7, label='Seed Fit')
    
    # Plot no seed data (white/open circles)
    if not no_seed_df.empty and len(no_seed_df) >= 5:
        no_seed_df_sorted = no_seed_df.sort_values('IVI (mins)')
        x_no_seed = no_seed_df_sorted['IVI (mins)'].to_numpy()
        n_no_seed = len(x_no_seed)
        y_no_seed = np.arange(n_no_seed, 0, -1) / n_no_seed
        ax2.semilogy(x_no_seed, y_no_seed, '-', linewidth=1, color='0.6', alpha=0.3)
        ax2.scatter(x_no_seed, y_no_seed, s=18, facecolor='white', edgecolor='black', 
                   linewidth=1.5, zorder=3, label=f'No Seed ($N$={n_no_seed})', alpha=0.8)
        
        # Plot no seed fit
        if popt_no_seed_log is not None:
            y_smooth_no_seed = np.exp(double_exponential_log_survivor(t_smooth, *popt_no_seed_log))
            ax2.semilogy(t_smooth, y_smooth_no_seed, '--', linewidth=2, color='blue', 
                        alpha=0.7, label='No Seed Fit')
    
    ax2.set_xlabel('')
    ax2.set_ylabel('')
    ax2.set_yticks([0.0001, 0.001, 0.01, 0.1, 1])
    ax2.set_yticklabels(['0.0001', '0.001', '0.01', '0.1', '1'], fontsize=16)
    ax2.tick_params(axis='x', labelsize=16)
    ax2.set_ylim(0.00001, 1.1)
    sns.despine(top=True, right=True, ax=ax2)
    
    # Add equations and metrics
    if popt_seed_log is not None:
        eq_seed = (f'Seed: $P(IVI>t) = {popt_seed_log[0]:.1f}e^{{-{popt_seed_log[1]:.2f}t}}'
                  f' + {popt_seed_log[2]:.1f}e^{{-{popt_seed_log[3]:.2f}t}}$')
        ax2.text(text_x, text_y, eq_seed, transform=ax2.transAxes,
                 bbox=dict(boxstyle="round,pad=0.3", facecolor="white", alpha=0.8, edgecolor='white'),
                 fontsize=9, ha='right')
        ax2.text(text_x, text_y-0.08, f'Seed: $R^2 = {r2_seed_log:.3f}$, $MAE = {mae_seed_log:.3f}$',
                 transform=ax2.transAxes,
                 bbox=dict(boxstyle="round,pad=0.3", facecolor="white", alpha=0.8, edgecolor='white'),
                 fontsize=9, ha='right')
    
    if popt_no_seed_log is not None:
        eq_no_seed = (f'No Seed: $P(IVI>t) = {popt_no_seed_log[0]:.1f}e^{{-{popt_no_seed_log[1]:.2f}t}}'
                     f' + {popt_no_seed_log[2]:.1f}e^{{-{popt_no_seed_log[3]:.2f}t}}$')
        y_offset = text_y - 0.16 if popt_seed_log is not None else text_y
        ax2.text(text_x, y_offset, eq_no_seed, transform=ax2.transAxes,
                 bbox=dict(boxstyle="round,pad=0.3", facecolor="white", alpha=0.8, edgecolor='white'),
                 fontsize=9, ha='right')
        y_offset_metrics = text_y - 0.24 if popt_seed_log is not None else text_y - 0.08
        ax2.text(text_x, y_offset_metrics, f'No Seed: $R^2 = {r2_no_seed_log:.3f}$, $MAE = {mae_no_seed_log:.3f}$',
                 transform=ax2.transAxes,
                 bbox=dict(boxstyle="round,pad=0.3", facecolor="white", alpha=0.8, edgecolor='white'),
                 fontsize=9, ha='right')
    
    ax2.set_title(f"{location}: Log Space Fit", fontsize=16, pad=40)
    _dedupe_legend(ax2)
    ax2.legend(loc=(0.125, 0.85), fontsize=10, frameon=False)

# Add single super labels
fig.supxlabel('Elapsed time, $t$ (mins)', fontsize=40, y=-0.0)
fig.supylabel('Proportion of IVIs > $t$', fontsize=40, x=0.0)

plt.tight_layout()
plt.subplots_adjust(hspace=0.5, wspace=0.05)

# --- Cell 30 ---
# Save bout analysis plot for dashboard
save_plot_for_dashboard(
    fig, 
    'all_birds_bout_seed_no_seed_separate', 
    'All Birds: Bout Analysis Separating Seed and No Seed Conditions',
    'Analysis of bout durations for all birds'
)
plt.close('all')


# ## Fit within each species

# --- Cell 32 ---
print("Fitting species-level bout models...")
def double_exponential_log_survivor(t, A1, lambda1, A2, lambda2):
    """Double exponential in log-space"""
    return np.log(A1 * np.exp(-lambda1 * t) + A2 * np.exp(-lambda2 * t) + 1e-10)

def fit_bout_model_for_bird(data, bird_species):
    # Data is already filtered by bird and location, so just extract IVI values
    bird_data = data['IVI (mins)'].dropna()
    
    if len(bird_data) < 5:
        return None, None, None, None
    
    sorted_ivi = np.sort(bird_data)
    n = len(sorted_ivi)
    survivor = np.arange(n, 0, -1) / n
    time_points = sorted_ivi
    
    # Work in log-space
    log_survivor = np.log(survivor + 1e-10)
    
    # More flexible initial guess based on data characteristics
    mean_ivi = bird_data.mean()
    std_ivi = bird_data.std()
    
    # Try multiple initial guesses
    initial_guesses = [
        [0.8, 1.0/mean_ivi, 0.2, 0.01/mean_ivi],  # Original
        [0.6, 0.5/mean_ivi, 0.4, 0.05/mean_ivi],   # Alternative 1
        [0.9, 2.0/mean_ivi, 0.1, 0.001/mean_ivi],   # Alternative 2
        [0.5, 0.1/mean_ivi, 0.5, 0.1/mean_ivi],     # Alternative 3
    ]
    
    # Much more relaxed bounds
    bounds = ([0.01, 0.001, 0.01, 0.0001], [1.0, 50, 1.0, 10])
    
    for initial_guess in initial_guesses:
        try:
            # Fit in log-space
            popt, pcov = curve_fit(double_exponential_log_survivor, time_points, log_survivor, 
                                 p0=initial_guess, bounds=bounds, maxfev=20000)
            
            # Convert back to linear space for evaluation
            y_pred_log = double_exponential_log_survivor(time_points, *popt)
            y_pred = np.exp(y_pred_log)
            
            # Calculate metrics in linear space
            r_squared = 1 - (np.sum((survivor - y_pred) ** 2) / np.sum((survivor - np.mean(survivor)) ** 2))
            mae = np.mean(np.abs(survivor - y_pred))
            
            # Only return if we get a reasonable fit
            # Lower threshold to allow more birds to get fits (was 0.5)
            if r_squared > 0.1:  # Minimum R² threshold
                return popt, pcov, r_squared, mae
                
        except:
            continue
    
    return None, None, None, None

# First, calculate IVIs for each bird separately
raw_data_ivi = pd.DataFrame()

# Get unique bird-location combinations
raw_data = raw_data.dropna(subset=['Bird'])
# raw_data = raw_data[raw_data['Bird'] != 'Gray Catbird']
bird_location_pairs = raw_data[['Bird', 'source_sheet']].drop_duplicates()

for _, row in bird_location_pairs.iterrows():
    bird = row['Bird']
    location = row['source_sheet']
    
    # Get data for this specific bird-location combination
    bird_data = raw_data[(raw_data['Bird'] == bird) & (raw_data['source_sheet'] == location)].copy()
    
    if len(bird_data) < 5:  # Skip if insufficient data
        continue
    
    # Convert to datetime with explicit format to avoid warnings
    bird_data['Date'] = pd.to_datetime(bird_data['Date'], format='%Y-%m-%d')
    bird_data['Time'] = pd.to_datetime(bird_data['Time'], format='%H:%M:%S')
    
    # Combine date and time, handling NaT values
    bird_data['date_time'] = bird_data['Date'] + pd.to_timedelta(bird_data['Time'].dt.hour, unit='h') + pd.to_timedelta(bird_data['Time'].dt.minute, unit='m') + pd.to_timedelta(bird_data['Time'].dt.second, unit='s')
    bird_data = bird_data.sort_values(by='date_time', ascending=True).reset_index(drop=True)
    
    # Calculate IVI (inter-visit interval) in minutes
    bird_data['IVI (mins)'] = bird_data['date_time'].diff().dt.total_seconds() / 60
    
    raw_data_ivi = pd.concat([raw_data_ivi, bird_data])

# Remove rows with NaN IVI values
raw_data_ivi = raw_data_ivi.dropna(subset=['IVI (mins)'])

# Sort by bird name
bird_location_pairs = bird_location_pairs.sort_values('Bird')

# Calculate number of subplots needed for square-ish layout
n_species = len(bird_location_pairs)
n_cols = 8
n_rows = int(np.ceil(n_species / n_cols))  # Calculate rows dynamically

# Create subplots
fig, axes = plt.subplots(n_rows, n_cols, figsize=(5*n_cols, 5*n_rows), sharey=True)
if n_rows == 1:
    axes = axes.reshape(1, -1)
elif n_cols == 1:
    axes = axes.reshape(-1, 1)

# Plot for each bird species
for i, (_, row) in enumerate(bird_location_pairs.iterrows()):
    bird = row['Bird']
    location = row['source_sheet']
    
    row_idx = i // n_cols
    col_idx = i % n_cols
    ax = axes[row_idx, col_idx]
    
    # Get data for this bird-location combination
    bird_data = raw_data_ivi[(raw_data_ivi['Bird'] == bird) & (raw_data_ivi['source_sheet'] == location)]['IVI (mins)'].dropna()
    
    if len(bird_data) < 5:
        ax.text(0.5, 0.5, f'Insufficient data', 
                ha='center', va='center', transform=ax.transAxes, fontsize=12)
        ax.set_title(f'{bird}\n({location})', fontsize=14)
        sns.despine(top=True, right=True)
        continue
    
    # Sort the data
    sorted_ivi = np.sort(bird_data)
    
    # Calculate survivor function
    n = len(sorted_ivi)
    survivor = np.arange(n, 0, -1) / n
    
    # Create time points for fitting
    time_points = sorted_ivi
    
    # Fit the model
    popt, pcov, r_squared, mae = fit_bout_model_for_bird(raw_data_ivi[(raw_data_ivi['Bird'] == bird) & (raw_data_ivi['source_sheet'] == location)], bird)
    
    if popt is not None:
        # Plot observed data
        ax.semilogy(time_points, survivor, 'ko-', markersize=4, linewidth=1, 
                   label=f'Observed ($n$={len(bird_data)})')
        
        # Plot fitted model - transform back to linear space
        t_smooth = np.linspace(0, bird_data.max(), 100)
        y_smooth_log = double_exponential_log_survivor(t_smooth, *popt)
        y_smooth = np.exp(y_smooth_log)
        ax.semilogy(t_smooth, y_smooth, 'r-', linewidth=2, 
                   label=f'Double Exponential')
        
        # Plot individual components - transform back to linear space
        within_bout_log = np.log(popt[0] * np.exp(-popt[1] * t_smooth) + 1e-10)
        between_bout_log = np.log(popt[2] * np.exp(-popt[3] * t_smooth) + 1e-10)
        within_bout = np.exp(within_bout_log)
        between_bout = np.exp(between_bout_log)
        
        text_x = 0.1
        
        # Add metrics text
        metrics_text = f'$R^2 = {r_squared:.3f}$\n$MAE = {mae:.3f}$'
        ax.text(text_x, 0.1, metrics_text, transform=ax.transAxes, 
               bbox=dict(boxstyle="round,pad=0.3", facecolor="white", alpha=0.8, edgecolor='white'),
               fontsize=12)
    else:
        # Plot just the observed data if model fitting failed
        ax.semilogy(time_points, survivor, 'ko-', markersize=4, linewidth=1, 
                   label=f'Observed ($n$={len(bird_data)})')
        metrics_text = f'Model fitting failed'
        ax.text(text_x, 0.1, metrics_text, transform=ax.transAxes, 
               bbox=dict(boxstyle="round,pad=0.3", facecolor="white", alpha=0.8, edgecolor='white'),
               fontsize=12)
    
    # Remove individual labels
    ax.set_xlabel('')
    ax.set_ylabel('')
    
    # Set formatting
    ax.legend(loc='best', fontsize=10, frameon=False)
    ax.set_yticks(ticks=[0.0001, 0.001, 0.01, 0.1, 1], 
                  labels=['0.0001', '0.001', '0.01', '0.1', '1'], 
                  fontsize=8)
    ax.tick_params(axis='x', labelsize=8)
    ax.set_ylim(0.0001, 1.1)
    ax.set_title(f'{bird}\n({location})', fontsize=14)
    
    sns.despine(top=True, right=True)

# Hide empty subplots
for i in range(n_species, n_rows * n_cols):
    row_idx = i // n_cols
    col_idx = i % n_cols
    axes[row_idx, col_idx].set_visible(False)

# Add single super labels
fig.supxlabel('Elapsed time, $t$ (mins)', fontsize=60, y=0.02)
fig.supylabel('Proportion of IVIs > $t$', fontsize=60, x=0.07)

plt.subplots_adjust(hspace=0.5, wspace=0.2)

# --- Cell 33 ---
# Save migration correlation plot for dashboard
save_plot_for_dashboard(
    fig, 
    'individual_species_bout_analysis', 
    'Bird Species: Bout Analysis (log space)',
    'Analysis of bout durations for individual bird species'
)

plt.close('all')


# ## MTB Data

# --- Cell 35 ---
print("Generating multiple baseline plot...")
# Convert both date columns to string format YYYY-MM-DD
all_birds_feeder = daily_summs.groupby(['Date', 'source_sheet']).agg({'Feeder Visits': 'sum'}).reset_index()
all_birds_feeder['Date_str'] = pd.to_datetime(all_birds_feeder['Date']).dt.strftime('%Y-%m-%d')
merged_data = all_birds_feeder.copy()
merged_data = merged_data.dropna(subset=['source_sheet']).copy()

# --- Cell 36 ---
# ---------- Prep ----------
merged_data['Date_dt'] = pd.to_datetime(merged_data['Date_str'])
phase_changes['DateChangeStarted'] = pd.to_datetime(phase_changes['DateChangeStarted'])

regions_order = ['Essex Fells, NJ', 'Jacksonville, FL', 'Southampton, UK', 'Auburn, AL']

# Collect change rows per location
changes_by_loc = {
    loc: phase_changes[phase_changes['LocationOfChange'] == loc].copy().sort_values('DateChangeStarted')
    for loc in regions_order
}

def phase_midpoint(df_with_dt, change_dt):
    """
    Return the halfway datetime between the last point BEFORE change_dt and
    the first point AT/AFTER change_dt. Falls back sensibly if edges are missing.
    If change_dt is after all data points, return change_dt (puts line to the right of last point).
    """
    dates = np.sort(df_with_dt['Date_dt'].dropna().unique())
    if dates.size == 0:
        return None

    left_candidates = dates[dates < change_dt]
    right_candidates = dates[dates >= change_dt]

    if left_candidates.size and right_candidates.size:
        left, right = left_candidates[-1], right_candidates[0]
        return left + (right - left) / 2
    elif right_candidates.size == 0:
        return change_dt
    elif left_candidates.size == 0:
        return change_dt
    else:
        if dates.size >= 2:
            left, right = dates[-2], dates[-1]
        else:
            left = right = dates[0]
        return left + (right - left) / 2

# ---------- Calculate overall date range from entire dataset ----------
merged_data_filtered = merged_data[merged_data['Date_dt'] >= pd.to_datetime('2025-10-05')]
overall_date_min = merged_data_filtered['Date_dt'].min() if not merged_data_filtered.empty else pd.to_datetime('2025-10-05')
overall_date_max = merged_data_filtered['Date_dt'].max() if not merged_data_filtered.empty else pd.to_datetime('2026-01-09')
overall_date_max_extended = overall_date_max + pd.Timedelta(days=7)

# ---------- Phase labels configuration ----------
# Labels are now derived dynamically from phase_changes data

# ========== BEHAVIORAL MOMENTUM FITTING ==========
import warnings as _warnings

def _bm_2param(t, B0, b):
    """Extinction model: B(t) = B0 * exp(-b*t)"""
    return B0 * np.exp(-b * t)

def _bm_3param(t, B0, b, c):
    """Extinction model with asymptote: B(t) = B0 * exp(-b*t) + c"""
    return B0 * np.exp(-b * t) + c

def _fit_metrics(y_obs, y_pred, k):
    n = len(y_obs)
    ss_res = np.sum((y_obs - y_pred) ** 2)
    ss_tot = np.sum((y_obs - np.mean(y_obs)) ** 2)
    r2 = 1.0 - ss_res / ss_tot if ss_tot > 0 else np.nan
    mae = float(np.mean(np.abs(y_obs - y_pred)))
    rmse = float(np.sqrt(np.mean((y_obs - y_pred) ** 2)))
    # AICc: corrected Akaike Information Criterion
    if n > k + 1 and ss_res > 0:
        aic = n * np.log(ss_res / n) + 2 * k
        aicc = aic + (2 * k ** 2 + 2 * k) / (n - k - 1)
    else:
        aicc = np.nan
    return r2, mae, rmse, aicc

def get_bm_fits(region, phase_changes_df, region_data_df):
    """Fit 2- and 3-param BM extinction models for each Seed→Extinction transition."""
    loc_changes = (
        phase_changes_df[phase_changes_df['LocationOfChange'] == region]
        .copy()
        .sort_values('DateChangeStarted')
        .reset_index(drop=True)
    )
    rdf = (
        region_data_df[region_data_df['source_sheet'] == region]
        .copy()
        .sort_values('Date_dt')
        .reset_index(drop=True)
    )
    rdf = rdf[rdf['Date_dt'] >= pd.to_datetime('2025-10-05')]
    extinctions = loc_changes[
        loc_changes['DescriptionOfChange'].str.lower().str.contains('extinct')
    ].reset_index(drop=True)
    fits = []
    for _, ext_row in extinctions.iterrows():
        ext_start = pd.to_datetime(ext_row['DateChangeStarted'])
        after = loc_changes[loc_changes['DateChangeStarted'] > ext_row['DateChangeStarted']]
        ext_end = (
            pd.to_datetime(after.iloc[0]['DateChangeStarted'])
            if not after.empty
            else rdf['Date_dt'].max() + pd.Timedelta(days=1)
        )
        seg = rdf[(rdf['Date_dt'] >= ext_start) & (rdf['Date_dt'] < ext_end)].copy()
        seg['visits'] = seg['Feeder Visits'].replace(0, np.nan)
        valid = seg.dropna(subset=['visits'])
        if len(valid) < 4:
            fits.append({'start': ext_start, 'end': ext_end, '2p': None, '3p': None})
            continue
        t = (valid['Date_dt'] - ext_start).dt.days.values.astype(float)
        y = valid['visits'].values.astype(float)
        fit_res = {'start': ext_start, 'end': ext_end}
        with _warnings.catch_warnings():
            _warnings.simplefilter('ignore')
            try:
                popt, _ = curve_fit(
                    _bm_2param, t, y,
                    p0=[float(y[0]), 0.15],
                    bounds=([1e-3, 1e-6], [1e6, 10.0]),
                    maxfev=10000
                )
                yp = _bm_2param(t, *popt)
                r2, mae, rmse, aicc = _fit_metrics(y, yp, k=2)
                fit_res['2p'] = {'B0': popt[0], 'b': popt[1], 'R2': r2, 'MAE': mae, 'RMSE': rmse, 'AICc': aicc}
            except Exception:
                fit_res['2p'] = None
            try:
                c0 = max(float(np.percentile(y, 10)), 0.5)
                popt, _ = curve_fit(
                    _bm_3param, t, y,
                    p0=[float(y[0]), 0.15, c0],
                    bounds=([1e-3, 1e-6, 0], [1e6, 10.0, 1e6]),
                    maxfev=10000
                )
                yp = _bm_3param(t, *popt)
                r2, mae, rmse, aicc = _fit_metrics(y, yp, k=3)
                fit_res['3p'] = {'B0': popt[0], 'b': popt[1], 'c': popt[2], 'R2': r2, 'MAE': mae, 'RMSE': rmse, 'AICc': aicc}
            except Exception:
                fit_res['3p'] = None
        fits.append(fit_res)
    return fits

_bm_locs = ['Essex Fells, NJ', 'Jacksonville, FL', 'Southampton, UK']
bm_fits = {loc: get_bm_fits(loc, phase_changes, merged_data) for loc in _bm_locs}

# ---------- Figure ----------
fig = plt.figure(figsize=(22, 14))
_gs = gridspec.GridSpec(4, 2, figure=fig, width_ratios=[2.2, 1.8], hspace=0.08, wspace=0.06)
axes = [fig.add_subplot(_gs[0, 0])]
for _i in range(1, 4):
    axes.append(fig.add_subplot(_gs[_i, 0], sharex=axes[0]))
ax_table = fig.add_subplot(_gs[:, 1])
ax_table.axis('off')

# IMPORTANT: store the exact midpoints that were actually plotted (after filtering/filling)
plotted_mids_by_region = {}
dashed_indices_by_region = {}
mbd_condition_legend = []  # (letter, condition) for the figure-level key

for ax, region in zip(axes, regions_order):

    # Prepare region data
    region_df = (
        merged_data[merged_data['source_sheet'] == region]
        .copy()
        .sort_values('Date_dt')
    )

    # Filter by date, but if that removes all data, use all available data
    region_df_filtered = region_df[region_df['Date_dt'] >= pd.to_datetime('2025-10-05')]
    if not region_df_filtered.empty:
        region_df = region_df_filtered

    date_min = region_df['Date_dt'].min()
    date_max = region_df['Date_dt'].max()

    # Fill in missing dates with 0 visits
    if not region_df.empty and pd.notna(date_min) and pd.notna(date_max):

        complete_dates = pd.date_range(start=date_min, end=date_max, freq='D')

        complete_df = pd.DataFrame({
            'Date_dt': complete_dates,
            'source_sheet': region
        })

        other_columns = [
            col for col in region_df.columns
            if col not in ['Date_dt', 'source_sheet', 'Feeder Visits']
        ]

        region_df = complete_df.merge(
            region_df,
            on=['Date_dt', 'source_sheet'],
            how='left'
        )

        if 'Feeder Visits' in region_df.columns:
            region_df['Feeder Visits'] = region_df['Feeder Visits'].fillna(0)
        else:
            region_df['Feeder Visits'] = 0

        for col in other_columns:
            if col in region_df.columns:
                if region_df[col].dtype in ['int64', 'float64', 'Int64', 'Float64']:
                    region_df[col] = region_df[col].fillna(0)

        region_df = region_df.sort_values('Date_dt').reset_index(drop=True)

    # Replace all 0 feeder visits with np.nan so it doesn't impact log scale
    region_df['Feeder Visits'] = region_df['Feeder Visits'].replace(0, np.nan)

    all_changes = changes_by_loc[region]

    # Recompute phase midpoints using the filtered region_df (these are the lines you actually draw)
    all_mids = []
    if not all_changes.empty and not region_df.empty:
        for _, change_row in all_changes.iterrows():
            mid = phase_midpoint(region_df, change_row['DateChangeStarted'])
            if mid is not None:
                all_mids.append(mid)

    # STORE the plotted midpoints for connectors (dashed indices stored after computation below)
    plotted_mids_by_region[region] = all_mids

    # Plot data split at phase changes
    if not all_changes.empty:
        change_dates = sorted(all_changes['DateChangeStarted'].tolist())

        segments = []
        if len(change_dates) > 0:
            segments.append(region_df[region_df['Date_dt'] < change_dates[0]])
            for i in range(len(change_dates) - 1):
                segments.append(region_df[
                    (region_df['Date_dt'] >= change_dates[i]) &
                    (region_df['Date_dt'] < change_dates[i + 1])
                ])
            segments.append(region_df[region_df['Date_dt'] >= change_dates[-1]])
        else:
            segments = [region_df]

        for seg_df in segments:
            if not seg_df.empty:
                sns.lineplot(
                    x='Date_dt', y='Feeder Visits', data=seg_df,
                    marker='o', markersize=8, color='black', ax=ax, legend=False,
                    linewidth=0.5
                )
    else:
        sns.lineplot(
            x='Date_dt', y='Feeder Visits', data=region_df,
            marker='o', markersize=8, color='black', ax=ax, legend=False,
            linewidth=0.5
        )

    # Determine line style: dashed for within-condition changes
    # (e.g., changing seed type), solid for across-condition changes
    # (e.g., seed to no seed, or no seed to seed).
    def _broad_condition(desc):
        """Map a phase change description to 'seed' or 'no_seed'."""
        d = str(desc).lower()
        if 'extinct' in d or 'removed' in d:
            return 'no_seed'
        return 'seed'

    dashed_indices = set()
    if not all_changes.empty:
        descs = all_changes['DescriptionOfChange'].tolist()
        # Start with the baseline condition (Seed) before any changes
        prev_condition = 'seed'
        for ci in range(len(descs)):
            curr_condition = _broad_condition(descs[ci])
            if curr_condition == prev_condition:
                dashed_indices.add(ci)
            prev_condition = curr_condition
    dashed_indices_by_region[region] = dashed_indices

    # Draw vertical lines for ALL phase changes
    for idx, mid in enumerate(all_mids):
        if mid is not None:
            if idx in dashed_indices:
                ax.axvline(mid, color='black', linewidth=0.5, alpha=0.9, linestyle='--')
            else:
                ax.axvline(mid, color='black', linewidth=1.5, alpha=0.9)

    # Phase labels for the first row only: a single-letter code centered in
    # each condition span (with a figure-level legend drawn after the loop).
    # Single letters replace the multi-line text that overlapped once phases
    # packed close together.
    if region == regions_order[0]:
        y_pos_log = 1200

        def _to_label(desc):
            d = str(desc).lower()
            if 'removed' in d:
                return 'Feeder Removed'
            if 'extinct' in d or 'no seed' in d:
                return 'No Seed'
            if 'seed' in d or 'mix' in d:
                return 'Seed'
            return ''

        if not all_changes.empty:
            change_dates = sorted(all_changes['DateChangeStarted'].tolist())
            phase_boundaries = [date_min] + change_dates + [date_max]

            span_conditions = []  # (x_center, condition) in chronological order
            for i in range(len(phase_boundaries) - 1):
                phase_start = phase_boundaries[i]
                phase_end = phase_boundaries[i + 1]

                if i == 0:
                    condition = 'Seed'
                else:
                    change_at_start = all_changes[all_changes['DateChangeStarted'] == phase_start]
                    if not change_at_start.empty:
                        condition = _to_label(change_at_start.iloc[0]['DescriptionOfChange'])
                    else:
                        condition = ''

                if condition:
                    x_center = phase_start + (phase_end - phase_start) / 2
                    span_conditions.append((x_center, condition))

            _letter_map, mbd_condition_legend = assign_condition_letters(
                [c for _, c in span_conditions]
            )
            for x_center, condition in span_conditions:
                ax.text(x_center, y_pos_log,
                        _letter_map[' '.join(str(condition).split())],
                        ha='center', va='center', fontsize=16, fontweight='bold')

    # No condition labels for rows below the first — the connectors
    # from the top row indicate which phase changes correspond.

    # Panel cosmetics
    ax.set_ylabel(f'{region}\nVisits', fontsize=18, rotation=0, ha='center', labelpad=90)
    ax.spines['top'].set_visible(False)
    ax.spines['right'].set_visible(False)
    ax.set_yscale('log')
    ax.set_ylim(0.8, 1000)

# Set xlim and xticks for all axes using overall dataset range.
# Space ticks so the count stays bounded (~18 max) as more days accumulate:
# weekly early on, then every 2/3/4 weeks once the study runs longer. This
# keeps the rotated date labels from overlapping into an unreadable smear.
_tick_span_days = (overall_date_max_extended - overall_date_min).days
_weeks = max(_tick_span_days / 7.0, 1)
_week_step = int(np.ceil(_weeks / 18.0))  # weeks between ticks
_tick_freq = f'{_week_step}W' if _week_step > 1 else 'W'
_xticks = pd.date_range(start=overall_date_min, end=overall_date_max_extended, freq=_tick_freq)
for ax in axes:
    ax.set_xlim(pd.to_datetime('2025-10-04'), overall_date_max_extended)
    ax.set_xticks(_xticks)

# Format y-axis for all axes
fmt = plt.matplotlib.ticker.FuncFormatter(lambda y, _: f'{int(y):d}' if y >= 1 else f'{y:g}')
for ax in axes:
    ax.yaxis.set_major_formatter(fmt)
    ax.yaxis.set_minor_formatter(plt.matplotlib.ticker.NullFormatter())

# ---------- Multi-baseline connectors ----------
def draw_connector(fig, axes, top_ax_idx, bottom_ax_idx, top_mid, bottom_mid,
                   linewidth=1.5, alpha=0.9, color='black'):
    if top_mid is None or bottom_mid is None:
        return

    # Horizontal connector across TOP of the BOTTOM panel
    x1, x2 = sorted([top_mid, bottom_mid])
    axes[bottom_ax_idx].plot(
        [x1, x2], [1, 1],
        transform=axes[bottom_ax_idx].get_xaxis_transform(),
        color=color, linewidth=linewidth, alpha=alpha
    )

    # Vertical connector between panels at x = top_mid
    ax_top = axes[top_ax_idx]
    xnum_top = ax_top.convert_xunits(top_mid)
    x_disp = ax_top.transData.transform((xnum_top, 0))[0]
    x_fig = fig.transFigure.inverted().transform((x_disp, 0))[0]

    top_bbox = axes[top_ax_idx].get_position()
    bottom_bbox = axes[bottom_ax_idx].get_position()

    fig.lines.append(
        Line2D([x_fig, x_fig], [bottom_bbox.y1, top_bbox.y0],
               transform=fig.transFigure, color=color, linewidth=linewidth, alpha=alpha)
    )

# Connect across-condition (solid) lines between adjacent panels.
# Skip within-condition (dashed) lines — they are site-specific and
# don't correspond to phase changes in the other panel.
panel_pairs = [
    (0, 1, 'Essex Fells, NJ', 'Jacksonville, FL'),
    (1, 2, 'Jacksonville, FL', 'Southampton, UK'),
]

for top_idx, bottom_idx, top_region, bottom_region in panel_pairs:
    top_mids = plotted_mids_by_region.get(top_region, [])
    bottom_mids = plotted_mids_by_region.get(bottom_region, [])
    top_dashed = dashed_indices_by_region.get(top_region, set())
    bottom_dashed = dashed_indices_by_region.get(bottom_region, set())

    # Filter to only solid (across-condition) midpoints
    top_solid = [m for i, m in enumerate(top_mids) if i not in top_dashed and m is not None]
    bottom_solid = [m for i, m in enumerate(bottom_mids) if i not in bottom_dashed and m is not None]

    # Pair from the front, then connect last-to-last.
    # If one side has more solid lines than the other, the extras
    # in the middle are site-specific and get skipped.
    n = min(len(top_solid), len(bottom_solid))
    if n == 0:
        continue
    # Front pairs: first (n-1)
    for i in range(n - 1):
        draw_connector(fig, axes, top_idx, bottom_idx, top_solid[i], bottom_solid[i])
    # Last pair: connect the final solid line from each
    draw_connector(fig, axes, top_idx, bottom_idx, top_solid[-1], bottom_solid[-1])

# Bottom x-axis formatting
axes[-1].set_xlabel('Date', fontsize=20, labelpad=12)
axes[-1].tick_params(axis='x', rotation=45)
for ax in axes[:-1]:
    ax.tick_params(axis='x', labelbottom=False)
    ax.set_xlabel('')

# ========== BEHAVIORAL MOMENTUM TABLE ==========

def _fmt_cell(fit_d, model):
    if fit_d is None:
        return "\u2014"
    _aicc_str = f"{fit_d['AICc']:.1f}" if np.isfinite(fit_d.get('AICc', np.nan)) else "N/A"
    if model == '2p':
        return (
            f"B\u2080={fit_d['B0']:.1f}  b={fit_d['b']:.3f}\n"
            f"R\u00b2={fit_d['R2']:.3f}  AICc={_aicc_str}\n"
            f"MAE={fit_d['MAE']:.1f}  RMSE={fit_d['RMSE']:.1f}"
        )
    else:
        return (
            f"B\u2080={fit_d['B0']:.1f}  b={fit_d['b']:.3f}\n"
            f"c={fit_d['c']:.1f}\n"
            f"R\u00b2={fit_d['R2']:.3f}  AICc={_aicc_str}\n"
            f"MAE={fit_d['MAE']:.1f}  RMSE={fit_d['RMSE']:.1f}"
        )

def _get_cell(fits_list, idx, model):
    if not fits_list or idx >= len(fits_list):
        return "\u2014"
    entry = fits_list[idx]
    if entry is None:
        return "\u2014"
    return _fmt_cell(entry.get(model), model)

_n_trans = {'Essex Fells, NJ': 2, 'Jacksonville, FL': 3, 'Southampton, UK': 2}
_c2p = '#ddeeff'   # light blue — 2-param rows
_c3p = '#fff3cc'   # light yellow — 3-param rows
_cna = '#f2f2f2'   # light grey — N/A cells
_cell_text = []
_cell_colors = []
for _loc in _bm_locs:
    _fits = bm_fits.get(_loc, [])
    _ntrans = _n_trans[_loc]
    for _model, _rc in [('2p', _c2p), ('3p', _c3p)]:
        _label = f"{_loc}\n({'2-param' if _model == '2p' else '3-param'})"
        _row = [_label]
        _rcolors = [_rc]
        for _i in range(3):
            if _i < _ntrans:
                _row.append(_get_cell(_fits, _i, _model))
                _rcolors.append(_rc)
            else:
                _row.append("\u2014")
                _rcolors.append(_cna)
        _cell_text.append(_row)
        _cell_colors.append(_rcolors)

_tbl = ax_table.table(
    cellText=_cell_text,
    colLabels=["Location & Model", "1st Extinction", "2nd Extinction", "3rd Extinction"],
    cellLoc='center',
    cellColours=_cell_colors,
    colColours=['#909090'] * 4,
    loc='center',
    bbox=[0.0, 0.0, 1.0, 0.84],
)
_tbl.auto_set_font_size(False)
_tbl.set_fontsize(11)
for _j in range(4):
    _tbl[0, _j].set_text_props(fontweight='bold', fontsize=12)

ax_table.text(
    0.5, 0.97, 'Behavioral Momentum',
    ha='center', va='top', transform=ax_table.transAxes,
    fontsize=18, fontweight='bold',
)
ax_table.text(
    0.5, 0.91,
    'B(t) = B\u2080 \u00b7 exp(\u2212bt)  [2-param, blue]\n'
    'B(t) = B\u2080 \u00b7 exp(\u2212bt) + c  [3-param, yellow]',
    ha='center', va='top', transform=ax_table.transAxes,
    fontsize=11, style='italic',
)

fig.suptitle('Multiple Baseline of Feeder Visits', fontsize=16, fontweight='bold', y=1.005)
plt.tight_layout(rect=[0, 0, 1, 0.94])
# Condition key for the single-letter phase codes, above the top panel.
draw_condition_key(fig, mbd_condition_legend, x=0.5, y=0.965, fontsize=13)


# --- Cell 37 ---
# Save migration correlation plot for dashboard
save_plot_for_dashboard(
    fig, 
    'mbd_plot', 
    'Multiple Baseline of Feeder Visits',
    'Multiple Baseline of feeder visits across three sites'
)
plt.close('all')


# --- Cell 37b ---
print("Generating species-level behavioral momentum plot...")

def get_species_bm_fits(region, phase_changes_df, daily_summs_df, min_points=4):
    """Fit 2-param BM extinction model per species per Seed->No Seed transition."""
    loc_changes = (
        phase_changes_df[phase_changes_df['LocationOfChange'] == region]
        .copy()
        .sort_values('DateChangeStarted')
        .reset_index(drop=True)
    )
    rdf = daily_summs_df[daily_summs_df['source_sheet'] == region].copy()
    rdf['Date_dt'] = pd.to_datetime(rdf['Date'])
    rdf = rdf[rdf['Date_dt'] >= pd.to_datetime('2025-10-05')]

    extinctions = loc_changes[
        loc_changes['DescriptionOfChange'].str.lower().str.contains('extinct')
    ].reset_index(drop=True)

    records = []
    for trans_idx, (_, ext_row) in enumerate(extinctions.iterrows()):
        ext_start = pd.to_datetime(ext_row['DateChangeStarted'])
        after = loc_changes[loc_changes['DateChangeStarted'] > ext_row['DateChangeStarted']]
        ext_end = (
            pd.to_datetime(after.iloc[0]['DateChangeStarted'])
            if not after.empty
            else rdf['Date_dt'].max() + pd.Timedelta(days=1)
        )
        seg = rdf[(rdf['Date_dt'] >= ext_start) & (rdf['Date_dt'] < ext_end)].copy()
        species_daily = (
            seg.groupby(['Date_dt', 'Bird'])['Feeder Visits']
            .sum()
            .reset_index()
        )
        for species, sp_data in species_daily.groupby('Bird'):
            sp_data = sp_data.sort_values('Date_dt').copy()
            sp_data['visits'] = sp_data['Feeder Visits'].replace(0, np.nan)
            valid = sp_data.dropna(subset=['visits'])
            if len(valid) < min_points:
                continue
            t = (valid['Date_dt'] - ext_start).dt.days.values.astype(float)
            y = valid['visits'].values.astype(float)
            try:
                with _warnings.catch_warnings():
                    _warnings.simplefilter('ignore')
                    popt, _ = curve_fit(
                        _bm_2param, t, y,
                        p0=[float(y[0]), 0.15],
                        bounds=([1e-3, 1e-6], [1e6, 10.0]),
                        maxfev=10000
                    )
                yp = _bm_2param(t, *popt)
                r2, mae, rmse, aicc = _fit_metrics(y, yp, k=2)
                records.append({
                    'Location': region,
                    'Species': species,
                    'Transition': trans_idx + 1,
                    'B0': popt[0],
                    'b': popt[1],
                    'R2': r2,
                    'MAE': mae,
                    'RMSE': rmse,
                    'AICc': aicc,
                    'n': len(valid),
                })
            except Exception:
                pass
    return records

_sp_records = []
for _loc in _bm_locs:
    _sp_records.extend(get_species_bm_fits(_loc, phase_changes, daily_summs))
species_bm_df = pd.DataFrame(_sp_records)

if not species_bm_df.empty:
    # Sort species by median b so most resistant (low b) are on the left
    _sp_order = (
        species_bm_df.groupby('Species')['b']
        .median()
        .sort_values()
        .index.tolist()
    )
    _loc_colors = {
        'Essex Fells, NJ': '#4e79a7',
        'Jacksonville, FL': '#f28e2b',
        'Southampton, UK':  '#59a14f',
    }
    fig_sp, ax_sp = plt.subplots(figsize=(max(14, len(_sp_order) * 1.0), 8))
    sns.swarmplot(
        data=species_bm_df,
        x='Species', y='b',
        hue='Location',
        order=_sp_order,
        palette=_loc_colors,
        dodge=True,
        size=9,
        alpha=0.85,
        ax=ax_sp,
    )
    ax_sp.set_xlabel('Species', fontsize=24, labelpad=12)
    ax_sp.set_ylabel('b  (extinction rate)', fontsize=24, labelpad=12)
    ax_sp.set_title(
        'Behavioral Momentum by Species\n'
        r'$B(t) = B_0 \cdot e^{-bt}$  —  higher b = faster extinction',
        fontsize=16, fontweight='bold',
    )
    ax_sp.tick_params(axis='x', rotation=45)
    ax_sp.set_xticklabels(ax_sp.get_xticklabels(), ha='right', fontsize=11)
    ax_sp.spines['top'].set_visible(False)
    ax_sp.spines['right'].set_visible(False)
    ax_sp.yaxis.grid(True, linestyle='--', alpha=0.5)
    ax_sp.set_axisbelow(True)
    ax_sp.legend(title='Location', fontsize=12, title_fontsize=13,
                 bbox_to_anchor=(1.01, 1), loc='upper left', frameon=False)
    plt.tight_layout()
    save_plot_for_dashboard(
        fig_sp,
        'bm_by_species',
        'Behavioral Momentum by Species',
        'Extinction rate (b) from B(t)=B0*exp(-bt) per species per No Seed transition'
    )
    plt.close('all')
else:
    print("  No species cleared the minimum data threshold — skipping BM species plot.")


# ## Calculating Daily and Weekly Diversity

# --- Cell 39 ---
print("Calculating diversity metrics...")
def calculate_species_richness_by_region(daily_summs_df):
    """
    Calculate species richness (number of unique species) per day per region.
    
    Parameters:
    daily_summs_df: DataFrame with columns ['Date', 'Bird', 'Feeder Visits', 'source_sheet', ...]
    
    Returns:
    DataFrame with Date, source_sheet, and richness columns
    """
    daily = daily_summs_df.copy()
    daily['Date'] = pd.to_datetime(daily['Date'])
    
    daily = daily[daily['Feeder Visits'] > 0].reset_index(drop=True)
    richness = daily.groupby(["Date", "source_sheet"])["Bird"].nunique().reset_index()
    richness.columns = ['Date', 'source_sheet', 'richness']
    
    return richness

def calculate_shannon_h_by_region(daily_summs_df):
    """
    Calculate Shannon H (alpha diversity) per day per region.
    
    Parameters:
    daily_summs_df: DataFrame with columns ['Date', 'Bird', 'Feeder Visits', 'source_sheet', ...]
    
    Returns:
    DataFrame with Date, source_sheet, and shannon_H columns
    """
    daily = daily_summs_df.copy()
    daily['Date'] = pd.to_datetime(daily['Date'])
    
    # Create pivot table: dates and regions as rows, bird species as columns, feeder visits as values
    day_species = daily.pivot_table(
        index=["Date", "source_sheet"], 
        columns="Bird", 
        values="Feeder Visits", 
        aggfunc="sum", 
        fill_value=0
    )
    
    # Calculate proportions (relative abundance) for each species on each day/region
    # Replace 0 with NaN to avoid log(0) issues
    p = day_species.div(day_species.sum(axis=1), axis=0).replace(0, np.nan)
    
    # Calculate Shannon H: -sum(p * log(p))
    shannon = (-(p * np.log(p)).sum(axis=1)).reset_index()
    shannon.columns = ['Date', 'source_sheet', 'shannon_H']
    
    return shannon

def calculate_u_value_by_region(daily_summs_df):
    """
    Calculate U-value (evenness metric) per day per region.
    
    U-value = - Σ (from i=1 to β) [ (α_i × log(α_i)) / log(β) ]
    where β = total number of unique species seen to date (cumulative)
    and α_i = relative frequency of species i on that day.
    
    Parameters:
    daily_summs_df: DataFrame with columns ['Date', 'Bird', 'Feeder Visits', 'source_sheet', ...]
    
    Returns:
    DataFrame with Date, source_sheet, and u_value columns
    """
    daily = daily_summs_df.copy()
    daily['Date'] = pd.to_datetime(daily['Date'])
    
    # Filter to only observations with feeder visits > 0
    daily = daily[daily['Feeder Visits'] > 0].reset_index(drop=True)
    
    u_values = []
    
    # Process each location separately
    for location in daily['source_sheet'].unique():
        location_data = daily[daily['source_sheet'] == location].copy()
        location_data = location_data.sort_values('Date')
        
        # Track cumulative unique species seen up to each date
        cumulative_species = set()
        
        # Process each date in chronological order
        for date in sorted(location_data['Date'].unique()):
            date_data = location_data[location_data['Date'] == date]
            
            # Add species seen on this date to cumulative set
            species_on_date = set(date_data['Bird'].unique())
            cumulative_species.update(species_on_date)
            
            # β = total number of unique species seen to date
            beta = len(cumulative_species)
            
            if beta == 0:
                u_values.append({'Date': date, 'source_sheet': location, 'u_value': np.nan})
                continue
            
            # Create pivot table for this date: species as columns, feeder visits as values
            day_species = date_data.pivot_table(
                index="Date",
                columns="Bird",
                values="Feeder Visits",
                aggfunc="sum",
                fill_value=0
            )
            
            # Calculate proportions (relative abundance) for each species on this day
            # α_i = relative frequency of species i
            total_visits = day_species.sum(axis=1).iloc[0]
            if total_visits == 0:
                u_values.append({'Date': date, 'source_sheet': location, 'u_value': np.nan})
                continue
            
            alpha = day_species.iloc[0] / total_visits
            
            # Calculate U-value: - Σ [ (α_i × log(α_i)) / log(β) ]
            # Only include species that were actually observed on this day (alpha > 0)
            observed_species = alpha[alpha > 0]
            if len(observed_species) == 0:
                u_values.append({'Date': date, 'source_sheet': location, 'u_value': np.nan})
                continue
            
            u_value = -((observed_species * np.log(observed_species)) / np.log(beta)).sum()
            u_values.append({'Date': date, 'source_sheet': location, 'u_value': u_value})
    
    u_value_df = pd.DataFrame(u_values)
    u_value_df['Date'] = pd.to_datetime(u_value_df['Date'])
    
    return u_value_df

def calculate_weekly_sorensen_dissimilarity_by_region(daily_summs_df):
    """
    Calculate Sørensen dissimilarity between consecutive weeks per region.
    
    Parameters:
    daily_summs_df: DataFrame with columns ['Date', 'Bird', 'Feeder Visits', 'source_sheet', ...]
    
    Returns:
    DataFrame with Date, source_sheet, and sorensen_dissimilarity columns
    """
    daily = daily_summs_df.copy()
    daily = daily.dropna().reset_index(drop=True)
    daily['Date'] = pd.to_datetime(daily['Date'])
    daily['week'] = daily['Date'].dt.isocalendar().week
    
    # Create weekly presence/absence matrix per region
    weekly_presence = (daily.groupby(["week", "source_sheet", "Bird"])["Feeder Visits"]
                       .sum().unstack(fill_value=0) > 0).astype(int)
    
    # Calculate Sørensen dissimilarity between consecutive weeks for each region
    sorensen = []
    
    for region in daily['source_sheet'].unique():
        region_data = daily[daily['source_sheet'] == region]
        region_weeks = sorted(region_data['week'].unique())
        
        for w_prev, w_curr in zip(region_weeks[:-1], region_weeks[1:]):
            try:
                a = weekly_presence.loc[(w_prev, region)]  # Previous week species presence
                b = weekly_presence.loc[(w_curr, region)]  # Current week species presence
                
                a_sum = a.sum()  # Number of species in previous week
                b_sum = b.sum()  # Number of species in current week
                intersection = (a & b).sum()  # Number of species in both weeks
                
                # Sørensen dissimilarity formula: 1 - (2 * intersection) / (a_sum + b_sum)
                denom = (a_sum + b_sum)
                d_s = np.nan if denom == 0 else 1 - (2 * intersection / denom)
                
                sorensen.append({
                    "week": w_curr, 
                    "source_sheet": region,
                    "sorensen_dissimilarity": d_s
                })
            except KeyError:
                continue
    
    # Convert to DataFrame
    beta_df = pd.DataFrame(sorensen)
    
    # Get all dates and their weeks per region
    all_dates = daily[['Date', 'week', 'source_sheet']].drop_duplicates().sort_values(['source_sheet', 'Date'])
    
    # Merge with Sørensen dissimilarity data
    result_df = all_dates.merge(beta_df, on=['week', 'source_sheet'], how='left')
    result_df = result_df[['Date', 'source_sheet', 'sorensen_dissimilarity']]
    
    return result_df

def calculate_rolling_sorensen_dissimilarity_by_region(daily_summs_df):
    """
    Calculate Sørensen dissimilarity using rolling 3-day comparisons per region.
    
    Parameters:
    daily_summs_df: DataFrame with columns ['Date', 'Bird', 'Feeder Visits', 'source_sheet', ...]
    
    Returns:
    DataFrame with Date, source_sheet, and rolling_sorensen_dissimilarity columns
    """
    daily = daily_summs_df.copy()
    daily['Date'] = pd.to_datetime(daily['Date'])
    
    sorensen_results = []
    
    # Process each region separately
    for region in daily['source_sheet'].unique():
        region_data = daily[daily['source_sheet'] == region].sort_values('Date').reset_index(drop=True)
        region_data['source_sheet'] = region_data['source_sheet'].fillna(region)
        
        # Create daily presence/absence matrix for this region
        daily_presence = (region_data.groupby(["Date", "Bird"])["Feeder Visits"]
                          .sum().unstack(fill_value=0) > 0).astype(int)
        
        # Get sorted dates for this region
        dates_sorted = sorted(daily_presence.index)
        
        # Calculate rolling 3-day Sørensen dissimilarity
        for i in range(len(dates_sorted)):
            current_date = dates_sorted[i]
            
            # Define the two 3-day periods to compare
            period_a_dates = []
            period_b_dates = []
            
            # Get dates for period A (7-9 days ago)
            for offset in [9, 8, 7]:
                if i - offset >= 0:
                    period_a_dates.append(dates_sorted[i - offset])
            
            # Get dates for period B (0-2 days ago)
            for offset in [2, 1, 0]:
                if i - offset >= 0:
                    period_b_dates.append(dates_sorted[i - offset])
            
            # Only calculate if we have at least one date in each period
            if len(period_a_dates) > 0 and len(period_b_dates) > 0:
                # Get species presence for each period
                period_a_presence = daily_presence.loc[period_a_dates].any(axis=0)
                period_b_presence = daily_presence.loc[period_b_dates].any(axis=0)
                
                # Calculate Sørensen dissimilarity
                a_sum = period_a_presence.sum()
                b_sum = period_b_presence.sum()
                intersection = (period_a_presence & period_b_presence).sum()
                
                # Sørensen dissimilarity formula: 1 - (2 * intersection) / (a_sum + b_sum)
                denom = (a_sum + b_sum)
                d_s = np.nan if denom == 0 else 1 - (2 * intersection / denom)
                
                sorensen_results.append({
                    'Date': current_date,
                    'source_sheet': region,
                    'rolling_sorensen_dissimilarity': d_s
                })
            else:
                sorensen_results.append({
                    'Date': current_date,
                    'source_sheet': region,
                    'rolling_sorensen_dissimilarity': np.nan
                })
    
    # Create result DataFrame
    result_df = pd.DataFrame(sorensen_results)
    
    return result_df

# Calculate each metric separately
richness_df = calculate_species_richness_by_region(daily_summs)
shannon_df = calculate_shannon_h_by_region(daily_summs)
u_value_df = calculate_u_value_by_region(daily_summs)
weekly_sorensen_df = calculate_weekly_sorensen_dissimilarity_by_region(daily_summs)
rolling_sorensen_df = calculate_rolling_sorensen_dissimilarity_by_region(daily_summs)

# Merge all metrics into a single dataframe
diversity_metrics_clean = richness_df.merge(shannon_df, on=['Date', 'source_sheet'], how='outer')
diversity_metrics_clean = diversity_metrics_clean.merge(u_value_df, on=['Date', 'source_sheet'], how='outer')
diversity_metrics_clean = diversity_metrics_clean.merge(weekly_sorensen_df, on=['Date', 'source_sheet'], how='outer')
diversity_metrics_clean = diversity_metrics_clean.merge(rolling_sorensen_df, on=['Date', 'source_sheet'], how='outer')

# Sort by date and region
diversity_metrics_clean = diversity_metrics_clean.sort_values(['source_sheet', 'Date']).reset_index(drop=True)

# --- Cell 40 ---
print("Plotting diversity metrics...")
# Get unique locations
locations = sorted(diversity_metrics_clean['source_sheet'].unique())
n_locations = len(locations)

# Create 4x3 subplot layout (4 rows for metrics, 3 columns for locations)
fig, axes = plt.subplots(5, n_locations, figsize=(9*n_locations, 25), sharex='col', sharey='row')

# Ensure axes is always a 2D array for consistent indexing
if n_locations == 1:
    axes = axes.reshape(5, 1)

# Define plot configurations (one per metric/row)
plot_configs = [
    {
        'row_idx': 0,
        'y_col': 'shannon_H',
        'title': 'Species Diversity Within Each Day',
        'ylabel': 'Shannon H\n(Alpha Diversity)',
        'show_legend': True,
        'equation': r'$H = -\sum_{i} p_i \cdot \ln(p_i)$',
        'description': '$p_i$ = proportion of species $i$\nHigher values = more diversity',
        'eq_pos': (0.05, 0.90),
        'desc_pos': (0.05, 0.775),
        'eq_align': 'left', 
        'ylim': (0, 3)
    },
    {
        'row_idx': 1,
        'y_col': 'richness',
        'title': 'Number of Unique Species Per Day',
        'ylabel': 'Species Richness',
        'show_legend': False,
        'equation': r'$S = \sum_{i} \text{species}_i$',
        'description': r'$\text{species}_i$ = presence of species $i$',
        'eq_pos': (0.05, 0.9),
        'desc_pos': (0.05, 0.825),
        'eq_align': 'left', 
        'ylim': (0, 15)
    },
        {
        'row_idx': 2,
        'y_col': 'u_value',
        'title': 'Species Evenness (U-value)',
        'ylabel': 'U-value\n(Evenness)',
        'show_legend': False,
        'equation': r'$U = -\sum_{i=1}^{\beta} \frac{\alpha_i \cdot \ln(\alpha_i)}{\ln(\beta)}$',
        'description': '$alpha_i$ = relative frequency of species $i$' + '\n' + '$beta$ = total unique species seen to date' + '\n' + 'Higher values = more even use of categories',
        'eq_pos': (0.05, 0.9),
        'desc_pos': (0.05, 0.775),
        'eq_align': 'left',
        'ylim': None  # Let it auto-scale
    },
    {
        'row_idx': 3,
        'y_col': 'sorensen_dissimilarity',
        'title': 'Species Turnover Between Weeks',
        'ylabel': 'Sørensen Dissimilarity\n(Weekly Beta Diversity)',
        'show_legend': False,
        'equation': r'$D_s = 1 - \frac{2C}{A + B}$',
        'description': '$C$ = shared species; $A,B$ = total species\nHigher values = more rapid changes',
        'eq_pos': (0.05, 0.9),
        'desc_pos': (0.05, 0.775),
        'eq_align': 'left',
        'ylim': (0, 1),
        'data_filter': lambda df: df.dropna(subset=['sorensen_dissimilarity'])
    },
    {
        'row_idx': 4,
        'y_col': 'rolling_sorensen_dissimilarity',
        'title': 'Species Turnover (Rolling 3-day)',
        'ylabel': 'Sørensen Dissimilarity\n(Rolling 3-day Beta Diversity)',
        'show_legend': False,
        'equation': r'$D_s = 1 - \frac{2C}{A + B}$',
        'description': '$C$ = shared species; $A,B$ = total species\nHigher values = more rapid changes',
        'eq_pos': (0.05, 0.9),
        'desc_pos': (0.05, 0.775),
        'eq_align': 'left',
        'ylim': (0, 1),
        'data_filter': lambda df: df.dropna(subset=['rolling_sorensen_dissimilarity'])
    }
]

# Global condition -> letter map for the whole diversity figure, so the same
# condition gets the same letter across every site panel and one shared legend
# explains them. Single letters centered in each span replace the rotated full
# text that used to sit on the phase-change lines.
_div_conditions = ['Seed']
for _loc in locations:
    for _, _r in phase_changes[phase_changes['LocationOfChange'] == _loc].iterrows():
        _div_conditions.append(_r['DescriptionOfChange'])
diversity_letter_map, diversity_condition_legend = assign_condition_letters(_div_conditions)

# Plot all subplots: iterate over metrics (rows) and locations (columns)
for config in plot_configs:
    row_idx = config['row_idx']
    
    # Filter data if needed (for the entire metric)
    plot_data = config.get('data_filter', lambda df: df)(diversity_metrics_clean)
    
    for col_idx, location in enumerate(locations):
        ax = axes[row_idx, col_idx]
        
        # Get data for this location and metric
        location_data = plot_data[plot_data['source_sheet'] == location].copy()
        
                # Check for phase changes for this location
        location_phase_changes = phase_changes[phase_changes['LocationOfChange'] == location]
        
        # Get all phase change dates if they exist
        phase_change_dates = []
        if not location_phase_changes.empty:
            phase_change_dates = sorted([pd.to_datetime(row['DateChangeStarted']) 
                                       for _, row in location_phase_changes.iterrows()])
        
        if not location_data.empty and location_data[config['y_col']].notna().any():
            # Ensure Date is datetime
            location_data['Date'] = pd.to_datetime(location_data['Date'])
            location_data = location_data.sort_values('Date')
            
            # Split data at all phase changes if they exist
            if phase_change_dates:
                # Create segments: before first change, between changes, after last change
                segments = []
                
                # Data before first phase change
                before_first = location_data[location_data['Date'] < phase_change_dates[0]]
                if not before_first.empty:
                    segments.append(before_first)
                
                # Data between phase changes
                for i in range(len(phase_change_dates) - 1):
                    between = location_data[
                        (location_data['Date'] >= phase_change_dates[i]) & 
                        (location_data['Date'] < phase_change_dates[i + 1])
                    ]
                    if not between.empty:
                        segments.append(between)
                
                # Data after last phase change
                after_last = location_data[location_data['Date'] >= phase_change_dates[-1]]
                if not after_last.empty:
                    segments.append(after_last)
                
                # Plot each segment separately
                for segment in segments:
                    if not segment.empty and segment[config['y_col']].notna().any():
                        ax.plot(
                            segment['Date'], 
                            segment[config['y_col']], 
                            marker='o', 
                            markersize=6,
                            linewidth=1, 
                            alpha=0.7,
                            color='black',
                            label=location if row_idx == 0 and col_idx == 0 and config['show_legend'] else ""
                        )
            else:
                # No phase change, plot normally
                ax.plot(
                    location_data['Date'], 
                    location_data[config['y_col']], 
                    marker='o', 
                    markersize=6,
                    linewidth=1, 
                    alpha=0.7,
                    color='black',
                    label=location if row_idx == 0 and col_idx == 0 and config['show_legend'] else ""
                )
            
            # Add phase change vertical lines for this location
            for _, phase_row in location_phase_changes.iterrows():
                change_date = pd.to_datetime(phase_row['DateChangeStarted'])

                # Find the date before the change date
                location_dates = location_data['Date'].unique()
                location_dates = pd.to_datetime(location_dates)
                location_dates = np.sort(location_dates)

                before_change_idx = np.where(location_dates < change_date)[0]
                if len(before_change_idx) > 0:
                    date_before = location_dates[before_change_idx[-1]]
                    halfway_date = date_before + (change_date - date_before) / 2
                    ax.axvline(x=halfway_date, color='black', linestyle='-', linewidth=3, alpha=0.8)

            # Single-letter condition codes centered in each span (shared legend
            # is drawn once for the whole figure).
            if 'ylim' in config and config['ylim'] is not None:
                ylim_max = config['ylim'][1]
            else:
                ylim_max = ax.get_ylim()[1]
            for _center, _cond in condition_spans(location_phase_changes, location_data['Date']):
                ax.text(_center, ylim_max,
                        diversity_letter_map[' '.join(str(_cond).split())],
                        ha='center', va='top', fontsize=13, fontweight='bold')
            
            # Set labels
            if col_idx == 0:
                ax.set_ylabel(config['ylabel'], fontsize=24, labelpad=12)
            else:
                ax.set_ylabel('')
            
            if row_idx == len(plot_configs) - 1:
                ax.set_xlabel('Date', fontsize=24, labelpad=12)
            else:
                ax.set_xlabel('')
            
            # Set title
            if row_idx == 0:
                # Top row: location names as column headers
                ax.set_title(location, fontsize=30, fontweight='bold', pad=15)
            # elif col_idx == 0:
            #     # First column: metric titles as row labels
            #     ax.set_title(config['title'], fontsize=12, fontweight='bold', pad=15)
            else:
                ax.set_title('')
            
            # Set y-axis limits if specified
            if 'ylim' in config and config['ylim'] is not None:
                ax.set_ylim(config['ylim'])
            
            # Remove legend
            # ax.legend().remove()
            
            # Add equation and description (only for first column)
            if col_idx == 0:
                ax.text(config['eq_pos'][0], config['eq_pos'][1], config['equation'], 
                       transform=ax.transAxes, fontsize=12, 
                       ha=config['eq_align'], va='bottom')
                ax.text(config['desc_pos'][0], config['desc_pos'][1], config['description'], 
                       transform=ax.transAxes, fontsize=10, 
                       ha=config['eq_align'], va='bottom')
        else:
            # Show "no data" message
            ax.text(0.5, 0.5, f'No {config["y_col"]} data available', 
                   ha='center', va='center', transform=ax.transAxes, fontsize=12)
            # Set title
            if row_idx == 0:
                ax.set_title(location, fontsize=12, fontweight='bold', pad=15)
            # elif col_idx == 0:
            #     ax.set_title(config['title'], fontsize=12, fontweight='bold', pad=15)
            else:
                ax.set_title('')
        
        # Apply styling
        sns.despine(top=True, right=True, ax=ax)
        ax.tick_params(axis='x', rotation=45, labelsize=9)
        ax.tick_params(axis='y', labelsize=9)

plt.tight_layout()
plt.subplots_adjust(hspace=0.2, top=0.92)
draw_condition_key(fig, diversity_condition_legend, x=0.5, y=0.98, fontsize=16)

# --- Cell 41 ---
# Save diversity metrics plot for dashboard
save_plot_for_dashboard(
    fig, 
    'diversity_metrics', 
    'Ecological Diversity Metrics',
    'Shannon H diversity and species richness metrics over time'
)
plt.close('all')

# --- Cell 42 ---
print("Generating diversity correlation matrix...")
# Correlation matrix crossing dicversity measures
# Prepare data for correlation matrix
# First, merge diversity metrics with phase changes to get condition labels
correlation_data = diversity_metrics_clean.copy()

# Create condition column based on phase changes
correlation_data['condition'] = 'None'
correlation_data['Date'] = pd.to_datetime(correlation_data['Date'])

# For each location, label dates based on phase changes
for location in correlation_data['source_sheet'].unique():
    location_mask = correlation_data['source_sheet'] == location
    location_phase_changes = phase_changes[phase_changes['LocationOfChange'] == location].copy()
    
    if not location_phase_changes.empty:
        location_phase_changes['DateChangeStarted'] = pd.to_datetime(location_phase_changes['DateChangeStarted'])
        
        # Sort phase changes by date
        location_phase_changes = location_phase_changes.sort_values('DateChangeStarted')
        
        # Label each date based on the most recent phase change
        for idx, row in correlation_data[location_mask].iterrows():
            date = row['Date']
            # Find the most recent phase change before or on this date
            recent_changes = location_phase_changes[location_phase_changes['DateChangeStarted'] <= date]
            
            if not recent_changes.empty:
                # Get the most recent change
                most_recent = recent_changes.iloc[-1]
                description = most_recent['DescriptionOfChange'].lower()
                
                # Classify condition
                if 'extinction' in description:
                    correlation_data.loc[idx, 'condition'] = 'Extinction'
                elif 'seed' in description:
                    correlation_data.loc[idx, 'condition'] = 'Seed'
                elif 'feeder' in description and 'remove' in description:
                    correlation_data.loc[idx, 'condition'] = 'Feeder Removed'

# Select metrics for correlation matrix
metrics = ['shannon_H', 'richness', 'u_value', 'sorensen_dissimilarity', 'rolling_sorensen_dissimilarity']
metric_labels = ['Shannon H', 'Species Richness', 'U-value', 'Weekly Sørensen', 'Rolling Sørensen']

# Remove rows with any NaN values in the metrics
correlation_data_clean = correlation_data[metrics + ['condition', 'source_sheet']].dropna(subset=metrics)
correlation_data_clean = correlation_data_clean[correlation_data_clean['condition'] != 'None'].reset_index(drop=True)

# Create color mapping for conditions
condition_colors = {
    'None': 'gray',
    'Extinction': 'red',
    'Seed': 'green',
    'Feeder Removed': 'orange'
}

# Create the correlation matrix plot
n_metrics = len(metrics)
fig, axes = plt.subplots(n_metrics, n_metrics, figsize=(4*n_metrics, 4*n_metrics))

# Calculate correlation matrix for upper triangle
corr_matrix = correlation_data_clean[metrics].corr()

for i in range(n_metrics):
    for j in range(n_metrics):
        ax = axes[i, j]
        
        if i == j:
            # Diagonal: histograms separated by condition
            metric = metrics[i]
            data = correlation_data_clean[[metric, 'condition']].dropna()
            
            # Get unique conditions present in data
            conditions = data['condition'].unique()
            
            # Create histogram for each condition
            for cond in conditions:
                cond_data = data[data['condition'] == cond][metric]
                if len(cond_data) > 0:
                    ax.hist(cond_data, alpha=0.6, label=cond, 
                           color=condition_colors.get(cond, 'blue'), bins=50)
            
            # Only show xlabel on bottom row
            if i == n_metrics - 1:
                ax.set_xlabel(metric_labels[i], fontsize=20)
            else:
                ax.set_xlabel('')
            
            # Only show ylabel on left column
            if j == 0:
                ax.set_ylabel(metric_labels[i], fontsize=20)
            else:
                ax.set_ylabel('')
            
            if i == 0 and j == 0:
                ax.legend(fontsize=14, loc='upper right', frameon=False)
            else:
                ax.legend().remove()
            ax.tick_params(labelsize=12)
            ax.spines['top'].set_visible(False)
            ax.spines['right'].set_visible(False)
            
        elif i > j:
            # Lower triangle: scatterplots colored by condition
            x_metric = metrics[j]
            y_metric = metrics[i]
            
            # Plot each condition separately to get proper colors
            for cond in correlation_data_clean['condition'].unique():
                cond_data = correlation_data_clean[correlation_data_clean['condition'] == cond]
                if len(cond_data) > 0:
                    # Scatter plot
                    ax.scatter(cond_data[x_metric], cond_data[y_metric], 
                             alpha=0.5, s=20, 
                             color=condition_colors.get(cond, 'blue'),
                             label='')
                    
                    # KDE contour lines
                    if len(cond_data) > 1:  # Need at least 2 points for KDE
                        try:
                            from scipy.stats import gaussian_kde
                            kde_data = cond_data[[x_metric, y_metric]].dropna()
                            if len(kde_data) > 1:
                                kde = gaussian_kde(kde_data.T)
                                x_min, x_max = cond_data[x_metric].min(), cond_data[x_metric].max()
                                y_min, y_max = cond_data[y_metric].min(), cond_data[y_metric].max()
                                x_range = x_max - x_min
                                y_range = y_max - y_min
                                
                                # Create grid for contour
                                xx = np.linspace(x_min - 0.1*x_range, x_max + 0.1*x_range, 50)
                                yy = np.linspace(y_min - 0.1*y_range, y_max + 0.1*y_range, 50)
                                XX, YY = np.meshgrid(xx, yy)
                                positions = np.vstack([XX.ravel(), YY.ravel()])
                                Z = kde(positions).reshape(XX.shape)
                                
                                # Plot contour lines only
                                ax.contour(XX, YY, Z, levels=3, colors=condition_colors.get(cond, 'blue'), 
                                         linewidths=1.5, alpha=0.7)
                        except:
                            pass  # Skip KDE if it fails
            
            # Only show xlabel on bottom row
            if i == n_metrics - 1:
                ax.set_xlabel(metric_labels[j], fontsize=20)
            else:
                ax.set_xlabel('')
            
            # Only show ylabel on left column
            if j == 0:
                ax.set_ylabel(metric_labels[i], fontsize=20)
            else:
                ax.set_ylabel('')
            
            ax.tick_params(labelsize=12)
            ax.legend().remove()
            ax.spines['top'].set_visible(False)
            ax.spines['right'].set_visible(False)
            
        else:
            # Upper triangle: correlation coefficient
            corr_value = corr_matrix.loc[metrics[i], metrics[j]]
            
            # Calculate correlations for Seed and Extinction conditions
            x_metric = metrics[j]
            y_metric = metrics[i]
            
            # Seed condition correlation
            seed_data = correlation_data_clean[correlation_data_clean['condition'] == 'Seed'][[x_metric, y_metric]].dropna()
            seed_corr = seed_data[x_metric].corr(seed_data[y_metric]) if len(seed_data) > 1 else np.nan
            
            # Extinction condition correlation
            extinction_data = correlation_data_clean[correlation_data_clean['condition'] == 'Extinction'][[x_metric, y_metric]].dropna()
            extinction_corr = extinction_data[x_metric].corr(extinction_data[y_metric]) if len(extinction_data) > 1 else np.nan
            
            # Clear the axis and add text
            ax.clear()
            # Overall correlation (black/default color)
            ax.text(0.5, 0.5, f'{corr_value:.2f}', 
                   ha='center', va='center', fontsize=30, fontweight='bold',
                   transform=ax.transAxes)
            # Seed correlation (green)
            # Extinction correlation (red)
            if not np.isnan(extinction_corr):
                ax.text(0.5, 0.2, f'{extinction_corr:.2f}', 
                       ha='center', va='center', fontsize=24, fontweight='bold',
                       color='red', transform=ax.transAxes)
            if not np.isnan(seed_corr):
                ax.text(0.5, 0.35, f'{seed_corr:.2f}', 
                       ha='center', va='center', fontsize=24, fontweight='bold',
                       color='green', transform=ax.transAxes)
            ax.set_xticks([])
            ax.set_yticks([])
            ax.spines['top'].set_visible(False)
            ax.spines['right'].set_visible(False)
            ax.spines['bottom'].set_visible(False)
            ax.spines['left'].set_visible(False)

plt.subplots_adjust(wspace=0.1, hspace=0.1)
plt.tight_layout()

# --- Cell 43 ---
# Save correlation metrics for dashboard
save_plot_for_dashboard(
    fig, 
    'diversity_metrics_corr_matrix', 
    'Correlation Matrix of Diversity Metrics',
    'Correlation matrix crossing diversity measures'
)
plt.close('all')


# ## Bring in PUC Data

# --- Cell 45 ---
print("Processing PUC study site data...")
# Read in the study site data
study_site_data = pd.read_csv('../data/study_site_puc_data.csv')

# Site Dict
site_dict = {
    'Essex Fells, NJ_JCV': 'Essex Fells',
    'PUC-21974-COX': 'Jacksonville'
}
study_site_data['station_name'] = study_site_data['station_name'].map(site_dict)

# Make sure data are in the right format
study_site_data['date'] = pd.to_datetime(study_site_data['timestamp'])
study_site_data['date'] = study_site_data['date'].astype(str)
study_site_data['date'] = [val.split(' ')[0] for val in study_site_data['date']]
study_site_data['date'] = pd.to_datetime(study_site_data['date'])

# Remove today's data because incomplete
today = datetime.now().strftime('%Y-%m-%d')
study_site_data = study_site_data[study_site_data['date'] != today]

# Create only high probability and confidence data
prob_threshold = 0.7
conf_threshold = 0.7
high_prob_conf_df = study_site_data[(study_site_data['confidence'] > conf_threshold) & (study_site_data['probability'] > prob_threshold)].reset_index(drop=True)
high_prob_conf_df = high_prob_conf_df[['id', 'species_common', 'confidence', 'probability', 'station_name', 'timestamp', 'date']]

# --- Cell 46 ---
# Get counts of sounds by date
count_by_date_all = study_site_data.groupby(['date', 'station_name']).agg(
    count = ('id', 'count'), 
    probability = ('probability', 'sum'),   # Historical likelihood of seeing a particular species in this location at this time of year. 
    confidence = ('confidence', 'sum'),     # How confident BirdNET AI is that this is the species identified
    unique_species = ('species_common', 'nunique')
).reset_index()

# Get counts of sounds by date
count_by_date_high_pc = high_prob_conf_df.groupby(['date', 'station_name']).agg(
    count = ('id', 'count'), 
    probability = ('probability', 'sum'),
    confidence = ('confidence', 'sum'),
    unique_species = ('species_common', 'nunique')
).reset_index()

# --- Cell 47 ---
def calculate_rolling_sorensen_dissimilarity_by_region_study_site(study_site_df, col_to_process='station_name'):
    daily = study_site_df.copy()
    daily['date'] = pd.to_datetime(daily['date'])
    
    sorensen_results = []
    
    # Process each station separately
    for station in daily[col_to_process].unique():
        station_data = daily[daily[col_to_process] == station].sort_values('date').reset_index(drop=True)
        
        # Create daily presence/absence matrix for this station
        # Use count > 0 to determine presence
        daily_presence = (station_data.groupby(["date", "species_common"])["id"]
                          .count().unstack(fill_value=0) > 0).astype(int)
        
        # Get sorted dates for this station
        dates_sorted = sorted(daily_presence.index)
        
        # Calculate rolling 3-day Sørensen dissimilarity
        for i in range(len(dates_sorted)):
            current_date = dates_sorted[i]
            
            # Define the two 3-day periods to compare
            period_a_dates = []
            period_b_dates = []
            
            # Get dates for period A (7-9 days ago)
            for offset in [9, 8, 7]:
                if i - offset >= 0:
                    period_a_dates.append(dates_sorted[i - offset])
            
            # Get dates for period B (0-2 days ago)
            for offset in [2, 1, 0]:
                if i - offset >= 0:
                    period_b_dates.append(dates_sorted[i - offset])
            
            # Only calculate if we have at least one date in each period
            if len(period_a_dates) > 0 and len(period_b_dates) > 0:
                # Get species presence for each period
                period_a_presence = daily_presence.loc[period_a_dates].any(axis=0)
                period_b_presence = daily_presence.loc[period_b_dates].any(axis=0)
                
                # Calculate Sørensen dissimilarity
                a_sum = period_a_presence.sum()
                b_sum = period_b_presence.sum()
                intersection = (period_a_presence & period_b_presence).sum()
                
                # Sørensen dissimilarity formula: 1 - (2 * intersection) / (a_sum + b_sum)
                denom = (a_sum + b_sum)
                d_s = np.nan if denom == 0 else 1 - (2 * intersection / denom)
                
                sorensen_results.append({
                    'date': current_date,
                    f'{col_to_process}': station,
                    'rolling_sorensen': d_s
                })
            else:
                sorensen_results.append({
                    'date': current_date,
                    f'{col_to_process}': station,
                    'rolling_sorensen': np.nan
                })
    
    # Create result DataFrame
    result_df = pd.DataFrame(sorensen_results)
    
    return result_df


def calculate_hill_q2_by_station(study_site_df, col_to_process='station_name'):
    """
    Calculate Hill Q=2 (Simpson's effective number) per date and station.
    Hill Q=2 = 1 / (sum of p_i^2) where p_i is the proportion of species i
    """
    daily = study_site_df.copy()
    daily['date'] = pd.to_datetime(daily['date'])
    
    hill_results = []
    
    # Process each date-station combination
    for (date, station), group in daily.groupby(['date', f'{col_to_process}']):
        # Count occurrences per species for this date-station
        species_counts = group.groupby('species_common')['id'].count()
        
        # Calculate proportions
        total_count = species_counts.sum()
        if total_count > 0:
            proportions = species_counts / total_count
            
            # Calculate Hill Q=2: 1 / sum(p_i^2)
            sum_squared_proportions = (proportions ** 2).sum()
            hill_q2 = 1 / sum_squared_proportions if sum_squared_proportions > 0 else np.nan
        else:
            hill_q2 = np.nan
        
        hill_results.append({
            'date': date,
            f'{col_to_process}': station,
            'hill_q_2': hill_q2
        })
    
    # Create result DataFrame
    result_df = pd.DataFrame(hill_results)
    
    return result_df

# --- Cell 48 ---
# Calculate the metrics
rolling_sorensen_all = calculate_rolling_sorensen_dissimilarity_by_region_study_site(study_site_data)
hill_q2_all = calculate_hill_q2_by_station(study_site_data)

rolling_sorensen_high_pc = calculate_rolling_sorensen_dissimilarity_by_region_study_site(high_prob_conf_df)
hill_q2_high_pc = calculate_hill_q2_by_station(high_prob_conf_df)

# Merge with count_by_date
count_by_date_all = count_by_date_all.merge(
    rolling_sorensen_all[['date', 'station_name', 'rolling_sorensen']], 
    on=['date', 'station_name'], 
    how='left'
)
count_by_date_all = count_by_date_all.merge(
    hill_q2_all[['date', 'station_name', 'hill_q_2']], 
    on=['date', 'station_name'], 
    how='left'
)

# Merge with count_by_date
count_by_date_high_pc = count_by_date_high_pc.merge(
    rolling_sorensen_high_pc[['date', 'station_name', 'rolling_sorensen']], 
    on=['date', 'station_name'], 
    how='left'
)
count_by_date_high_pc = count_by_date_high_pc.merge(
    hill_q2_high_pc[['date', 'station_name', 'hill_q_2']], 
    on=['date', 'station_name'], 
    how='left'
)

# --- Cell 49 ---
def plot_puc_data(station_name=None, puc_name=None, prob_threshold=prob_threshold, conf_threshold=conf_threshold):
    plot_all = count_by_date_all.loc[count_by_date_all['station_name'] == station_name]
    plot_high_pc = count_by_date_high_pc.loc[count_by_date_high_pc['station_name'] == station_name]
    # Phase changes for this station (match LocationOfChange to station_name)
    location_phase_changes = phase_changes[phase_changes['LocationOfChange'].astype(str).str.strip().str.startswith(station_name)]
    # Single-letter condition codes (centered in each phase span) + legend
    puc_placements, puc_legend = condition_span_placements(
        location_phase_changes, plot_all['date']
    )
    # Plot trends - 2x3 subplot
    fig, axes = plt.subplots(nrows=2, ncols=3, figsize=(28, 12), sharex=True)
    fig.tight_layout(pad=4.0)

    # Define plot configurations: (row, col, column_name, ylabel)
    plot_configs = [
        (0, 0, 'count', 'Number of Sounds'),
        (0, 1, 'probability', 'Probability'),
        (0, 2, 'confidence', 'Confidence'),
        (1, 0, 'unique_species', 'Unique Species'),
        (1, 1, 'rolling_sorensen', 'Rolling Sørensen'),
        (1, 2, 'hill_q_2', 'Hill Q=2'),
    ]

    # Plot each metric
    _puc_handles, _puc_labels = [], []
    for row, col, col_name, ylabel in plot_configs:
        ax = axes[row, col]

        # Check if column exists in dataframe
        if col_name in count_by_date_all.columns:
            sns.lineplot(
                x='date', 
                y=col_name, 
                data=plot_all, 
                ax=ax, 
                color='black', 
                markers=True,
                marker='o',  
                markersize=10, 
                markeredgewidth=0.5,
                alpha=0.7,
                label='All Data'
            )
            sns.lineplot(
                x='date', 
                y=col_name, 
                data=plot_high_pc, 
                ax=ax, 
                color='red', 
                markers=True,
                marker='o',  
                markersize=10, 
                markeredgewidth=0.5,
                alpha=0.7,
                label=f'High PC Data (p={prob_threshold}, c={conf_threshold})'
            )
            # Phase change vertical lines + single-letter condition codes
            # centered in each span (legend drawn once for the figure below).
            if not location_phase_changes.empty and not plot_all.empty:
                location_dates = pd.to_datetime(plot_all['date'].unique())
                location_dates = np.sort(location_dates)
                for _, phase_row in location_phase_changes.iterrows():
                    change_date = pd.to_datetime(phase_row['DateChangeStarted'])
                    before_change_idx = np.where(location_dates < change_date)[0]
                    if len(before_change_idx) > 0:
                        date_before = location_dates[before_change_idx[-1]]
                        halfway_date = date_before + (change_date - date_before) / 2
                        ax.axvline(x=halfway_date, color='black', linestyle='-', linewidth=3, alpha=0.8)
                ylim_max = ax.get_ylim()[1]
                for center, letter in puc_placements:
                    ax.text(center, ylim_max, letter, ha='center', va='top',
                            fontsize=15, fontweight='bold')
            ax.set_ylabel(ylabel, fontsize=30, labelpad=8)
            ax.tick_params(labelsize=18)
            
            # Only show x-axis labels on bottom row
            if row == 1:
                ax.set_xlabel('Date', fontsize=30, labelpad=8)
                # Format dates properly
                ax.xaxis.set_major_formatter(plt.matplotlib.dates.DateFormatter('%Y-%m-%d'))
                ax.tick_params(axis='x', labelsize=18, rotation=45)
            else:
                ax.set_xlabel('')
                ax.tick_params(axis='x', labelbottom=False)
            
            # Capture the data-series legend once; it is drawn at the figure
            # top (below) so it never collides with the span letters.
            if row == 0 and col == 0:
                _puc_handles, _puc_labels = ax.get_legend_handles_labels()
            if ax.get_legend() is not None:
                ax.legend().remove()
        else:
            # If column doesn't exist, show a message
            ax.text(0.5, 0.5, f'Column "{col_name}"\nnot found', 
                    ha='center', va='center', fontsize=12, 
                    transform=ax.transAxes)
            ax.set_ylabel(ylabel, fontsize=30, labelpad=8)
            if row == 1:
                ax.set_xlabel('Date', fontsize=30, labelpad=12)
        
        sns.despine(top=True, right=True, ax=ax)

    plt.subplots_adjust(wspace=0.2, hspace=0.1, bottom=0.10, top=0.86)
    # Data-series legend at the very top, condition key just below it - both
    # above the panels and clear of the span letters.
    if _puc_handles:
        fig.legend(_puc_handles, _puc_labels, fontsize=20, frameon=False,
                   loc='upper center', bbox_to_anchor=(0.5, 1.0), ncol=2)
    draw_condition_key(fig, puc_legend, x=0.5, y=0.94, fontsize=16)
    return fig

# --- Cell 50 ---
fig = plot_puc_data(station_name='Essex Fells', puc_name='PUC = Essex Fells, NJ_JCV')
save_plot_for_dashboard(
    fig, 
    'puc_audio_data_nj_jcv', 
    'Auditory Data from Essex Fells PUC',
    'Auditory data from Essex Fells PUC. Probability = historical likelihood of seeing a particular species in this location at this time of year. Confidence = how confident BirdNET AI is that this is the species identified. Unique Species = number of unique species identified in a given day.'
)
plt.close('all')

# --- Cell 51 ---
fig = plot_puc_data(station_name='Jacksonville', puc_name='PUC = PUC-21974-COX')
save_plot_for_dashboard(
    fig, 
    'puc_audio_data_puc_21974_cox', 
    'Auditory Data from Jacksonville PUC',
    'Auditory data from Jacksonville PUC. Probability = historical likelihood of seeing a particular species in this location at this time of year. Confidence = how confident BirdNET AI is that this is the species identified. Unique Species = number of unique species identified in a given day.'
)
plt.close('all')


# # Add County PUC for Nested Analyses

# --- Cell 53 ---
print("Processing county-level PUC data...")
# Read in all PUC data from surrounding county
# Wrapped in try/except because county_level_birdweather.parquet may not exist
# on first CI run or if the BirdWeather fetch failed
try:
    county_puc_data = pd.read_parquet('../data/county_level_birdweather.parquet')

    # Make sure data are in the right format
    county_puc_data['date'] = pd.to_datetime(county_puc_data['timestamp'])
    county_puc_data['date'] = county_puc_data['date'].astype(str)
    county_puc_data['date'] = [val.split(' ')[0] for val in county_puc_data['date']]
    county_puc_data['date'] = pd.to_datetime(county_puc_data['date'])
    county_puc_data = county_puc_data[county_puc_data['date'] >= '2025-06-01']

    # Remove today's data because incomplete
    today = datetime.now().strftime('%Y-%m-%d')
    county_puc_data = county_puc_data[county_puc_data['date'] != today]

    # Create only high probability and confidence data
    county_puc_data_high_pc = county_puc_data[(county_puc_data['confidence'] > conf_threshold) & (county_puc_data['probability'] > prob_threshold)].reset_index(drop=True)

    # --- Cell 54 ---
    # Get counts of sounds by date
    count_by_date_all_county = county_puc_data.groupby(['date', 'county']).agg(
        count = ('id', 'count'),
        probability = ('probability', 'sum'),
        confidence = ('confidence', 'sum'),
        unique_species = ('species_common', 'nunique')
    ).reset_index()

    # Get counts of sounds by date
    count_by_date_high_pc_county = county_puc_data_high_pc.groupby(['date', 'county']).agg(
        count = ('id', 'count'),
        probability = ('probability', 'sum'),
        confidence = ('confidence', 'sum'),
        unique_species = ('species_common', 'nunique')
    ).reset_index()

    # Calculate the metrics
    rolling_sorensen_all_county = calculate_rolling_sorensen_dissimilarity_by_region_study_site(county_puc_data, col_to_process='county')
    hill_q2_all_county = calculate_hill_q2_by_station(county_puc_data, col_to_process='county')

    rolling_sorensen_high_pc_county = calculate_rolling_sorensen_dissimilarity_by_region_study_site(county_puc_data_high_pc, col_to_process='county')
    hill_q2_high_pc_county = calculate_hill_q2_by_station(county_puc_data_high_pc, col_to_process='county')

    # Merge with count_by_date
    count_by_date_all_county = count_by_date_all_county.merge(
        rolling_sorensen_all_county[['date', 'county', 'rolling_sorensen']],
        on=['date', 'county'],
        how='left'
    )
    count_by_date_all_county = count_by_date_all_county.merge(
        hill_q2_all_county[['date', 'county', 'hill_q_2']],
        on=['date', 'county'],
        how='left'
    )

    # Merge with count_by_date
    count_by_date_high_pc_county = count_by_date_high_pc_county.merge(
        rolling_sorensen_high_pc_county[['date', 'county', 'rolling_sorensen']],
        on=['date', 'county'],
        how='left'
    )
    count_by_date_high_pc_county = count_by_date_high_pc_county.merge(
        hill_q2_high_pc_county[['date', 'county', 'hill_q_2']],
        on=['date', 'county'],
        how='left'
    )

    # --- Cell 55 ---
    # Add station relations for merging
    count_by_date_all_county['station_name'] = count_by_date_all_county['county'].map({
        'essex_nj': 'Essex Fells',
        'duval_fl': 'Jacksonville',
        'st_johns_fl': 'St. Johns',
    })

    # Merge study site with county
    count_by_date_merge = count_by_date_all.merge(
        count_by_date_all_county,
        on=['date', 'station_name'],
        how='right',
        suffixes=('_study_site', '_county')
    )

    # Ensure county count is always >= study site count.
    # The study site PUC should be a subset of county PUCs, but they are
    # collected independently so the county scrape may miss the local station.
    # When study site exceeds county, add study site into county total.
    site_exceeds = count_by_date_merge['count_study_site'] > count_by_date_merge['count_county']
    count_by_date_merge.loc[site_exceeds, 'count_county'] = (
        count_by_date_merge.loc[site_exceeds, 'count_county']
        + count_by_date_merge.loc[site_exceeds, 'count_study_site']
    )

    # --- Cell 56 ---
    # Load BirdCast migration data for overlay
    birdcast_region_to_station = {
        'US-FL-031': 'Jacksonville',
        'US-NJ-013': 'Essex Fells',
    }
    try:
        birdcast_df = pd.read_parquet(BIRDCAST_PARQUET)
        birdcast_df = birdcast_df[birdcast_df['region_code'].isin(birdcast_region_to_station.keys())].copy()
        birdcast_df['station_name'] = birdcast_df['region_code'].map(birdcast_region_to_station)
        birdcast_df['total_birds'] = pd.to_numeric(birdcast_df['total_birds'], errors='coerce')
        # Parse date from migration_date field, fall back to scrape_timestamp
        birdcast_df['date'] = pd.to_datetime(birdcast_df['migration_start_utc'], errors='coerce').dt.normalize()
        birdcast_df.loc[birdcast_df['date'].isna(), 'date'] = pd.to_datetime(
            birdcast_df.loc[birdcast_df['date'].isna(), 'scrape_timestamp'], errors='coerce'
        ).dt.normalize()
        birdcast_df = birdcast_df.dropna(subset=['date', 'total_birds'])
        # Strip timezone so dates are compatible with PUC data for merging
        birdcast_df['date'] = birdcast_df['date'].dt.tz_localize(None)
        # Keep one row per date per station (max total_birds if duplicates)
        birdcast_df = birdcast_df.groupby(['date', 'station_name'])['total_birds'].max().reset_index()
        # Insert NaN rows at gaps > 7 days so matplotlib doesn't draw connecting lines
        gap_rows = []
        for station in birdcast_df['station_name'].unique():
            sdf = birdcast_df[birdcast_df['station_name'] == station].sort_values('date')
            gaps = sdf['date'].diff()
            for idx in gaps[gaps > pd.Timedelta(days=7)].index:
                gap_rows.append({'date': sdf.loc[idx, 'date'] - pd.Timedelta(days=1), 'station_name': station, 'total_birds': np.nan})
        if gap_rows:
            birdcast_df = pd.concat([birdcast_df, pd.DataFrame(gap_rows)], ignore_index=True).sort_values(['station_name', 'date'])
        has_birdcast = len(birdcast_df) > 0
    except (FileNotFoundError, Exception):
        has_birdcast = False

    fig, ax = plt.subplots(figsize=(12, 7))
    plot_data = count_by_date_merge[count_by_date_merge['date'] >= '2025-11-01']
    sns.lineplot(
        x='date', y='count_county',
        data=plot_data,
        hue='station_name', palette='Set1', alpha=0.7,
    )
    sns.lineplot(
        x='date', y='count_study_site',
        data=plot_data,
        hue='station_name', palette='Set1', alpha=0.7,
        linestyle='--', legend=False,
    )

    # Overlay BirdCast migration counts on secondary y-axis
    if has_birdcast:
        ax2 = ax.twinx()
        birdcast_plot = birdcast_df[birdcast_df['date'] >= '2025-11-01']
        palette = sns.color_palette('Set1')
        station_colors = {name: palette[i] for i, name in enumerate(plot_data['station_name'].unique())}
        for station_name, sdf in birdcast_plot.groupby('station_name'):
            sdf = sdf.sort_values('date')
            color = station_colors.get(station_name, 'grey')
            ax2.plot(sdf['date'], sdf['total_birds'], linestyle=':', marker='D', markersize=5, color=color, alpha=0.3)
        ax2.set_ylabel('Migration Count (BirdCast)', fontsize=20, labelpad=10)
        ax2.tick_params(labelsize=14)
        ax2.set_yscale('log')
        ax2.yaxis.set_major_formatter(mtick.FuncFormatter(lambda x, p: f'{x:,.0f}'))
        sns.despine(top=True, left=False, right=False, ax=ax2)

    # Add line-style legend entries via proxy artists
    proxy_handles = [
        Line2D([0], [0], color='black', linestyle='--', linewidth=1.5, label='Study Site'),
        Line2D([0], [0], color='black', linestyle='-', linewidth=1.5, label='County'),
    ]
    if has_birdcast:
        proxy_handles.append(
            Line2D([0], [0], color='black', linestyle=':', marker='D', markersize=4, linewidth=1.5, alpha=0.5, label='Migration (BirdCast)')
        )

    ax.set_xlabel('Date', fontsize=24, labelpad=10)
    ax.set_ylabel('PUC Count', fontsize=24, labelpad=10)
    ax.set_yscale('log')
    ax.set_ylim(1, 50_000)
    ax.yaxis.set_major_formatter(mtick.FuncFormatter(lambda x, p: f'{x:,.2f}'))
    sns.despine(top=True, right=has_birdcast, ax=ax)
    # Combine seaborn's hue legend with line-style proxies
    hue_handles, hue_labels = ax.get_legend_handles_labels()
    ax.legend(handles=hue_handles + proxy_handles, loc='lower left', fontsize=14, frameon=False)
    ax.grid(False)
    if has_birdcast:
        ax2.grid(False)

    save_plot_for_dashboard(
        fig,
        'puc_audio_data_puc_site_to_county',
        'Auditory Data from Study Site vs County with Migration',
        'Auditory data from PUCs at each study site (---) vs. PUC data from surrounding county (—) with BirdCast nightly migration counts (···)'
    )
    plt.close('all')

    # --- Cell 57 ---
    # Faceted small multiples -- one panel per station
    # Three nested layers: migration (outermost fill) > county (middle fill) > study site (line)
    print("Generating faceted study site vs county plot...")
    plot_data = count_by_date_merge[count_by_date_merge['date'] >= '2025-11-01'].copy()
    stations = [s for s in plot_data['station_name'].unique() if s != 'St. Johns']
    n_stations = len(stations)

    fig, axes = plt.subplots(nrows=n_stations, ncols=1, figsize=(14, 5 * n_stations), sharex=True)
    if n_stations == 1:
        axes = [axes]

    palette = sns.color_palette('Set1')
    station_colors = {name: palette[i] for i, name in enumerate(plot_data['station_name'].unique())}

    for i, station in enumerate(stations):
        ax = axes[i]
        sdf = plot_data[plot_data['station_name'] == station].sort_values('date')
        color = station_colors.get(station, 'grey')

        # Migration as outermost filled area (merge BirdCast onto PUC dates)
        if has_birdcast:
            bc_station = birdcast_df[(birdcast_df['date'] >= '2025-11-01') & (birdcast_df['station_name'] == station)].dropna(subset=['total_birds'])
            if len(bc_station) > 0:
                sdf_bc = sdf.merge(bc_station[['date', 'total_birds']], on='date', how='left')
                ax.fill_between(sdf_bc['date'], 1, sdf_bc['total_birds'], alpha=0.1, color=color, label='Migration (BirdCast)')

        # County as middle filled area
        ax.fill_between(sdf['date'], 1, sdf['count_county'], alpha=0.25, color=color, label='County')
        # Study site as solid line
        ax.plot(sdf['date'], sdf['count_study_site'], color=color, linewidth=2, label='Study Site')

        ax.set_yscale('log')
        ax.set_ylabel('Count', fontsize=18, labelpad=10)
        ax.set_title(station, fontsize=20, fontweight='bold', pad=10)
        ax.tick_params(labelsize=14)
        ax.yaxis.set_major_formatter(mtick.FuncFormatter(lambda x, p: f'{x:,.0f}'))
        sns.despine(top=True, right=True, ax=ax)
        ax.grid(False)

        # Legend on first panel only
        if i == 0:
            proxy = [
                Line2D([0], [0], color='black', linewidth=2, label='Study Site'),
                plt.Rectangle((0, 0), 1, 1, fc='grey', alpha=0.25, label='County'),
            ]
            if has_birdcast:
                proxy.append(plt.Rectangle((0, 0), 1, 1, fc='grey', alpha=0.1, label='Migration (BirdCast)'))
            ax.legend(handles=proxy, loc='upper right', fontsize=12, frameon=False)

    axes[-1].set_xlabel('Date', fontsize=20, labelpad=10)
    plt.tight_layout()

    save_plot_for_dashboard(
        fig,
        'puc_site_county_faceted',
        'Study Site vs County PUC Activity by Station',
        'Faceted view showing nested spatial scales per station. Outermost fill = BirdCast nightly migration count, middle fill = county-level PUC activity, solid line = study site PUC activity. Log scale.'
    )
    plt.close('all')

except FileNotFoundError:
    print("Skipping county-level PUC analysis: county_level_birdweather.parquet not found")

print("all_sites_all_analytics.py complete.")