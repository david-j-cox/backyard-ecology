#!/usr/bin/env python3
"""
One-site analytics script.

Generates seed preference, side-time preference, peck-vs-time comparison and
peck distribution plots for the Jacksonville site.
"""

# Standard library imports
import json
import math
import os
from datetime import datetime

# Third-party imports
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import numpy as np
import pandas as pd
import seaborn as sns
from dotenv import load_dotenv

# ---------------------------------
# Config
# ---------------------------------
RAW_DATA_CSV = '../data/raw_data_all_locations.csv'
BIRDCAST_PARQUET = '../data/birdcast_data.parquet'
PHASE_CHANGES_CSV = '../data/phase_change_data.csv'
SITE_SHEET = 'jacksonville_fl_32259'
SITE_PHASE_LOCATION = 'Jacksonville, FL'
load_dotenv()

# Map raw seed strings to short two-line plot labels
SEED_LABELS = {
    'Special Finch Food': 'Finch\nFood',
    'Golden Safflower': 'Safflower',
    'Sunflower, Safflower, Mealworm, Peanuts': 'Low\nDove',
    'Safflower, Mealworm': 'Saff +\nMworm',
    'Peanuts, Sunflower': 'Pnuts +\nSunfl',
}
NO_SEED_LABEL = 'No\nSeed'
SHORT_PHASE_DAYS = 3  # phases shorter than this skip their text label
# Non-bird visitors to exclude from the peck-data plots (seed preference and
# peck distribution).
EXCLUDE_SPECIES = {'Eastern Gray Squirrel'}
# Rows that are not a single species (e.g. 'Unidentified bird') stay out of per-species plots.
NOT_A_SPECIES_PREFIX = 'unidentified'


def label_for_seed(seed):
    if seed is None or (isinstance(seed, float) and pd.isna(seed)):
        return NO_SEED_LABEL
    return SEED_LABELS.get(seed, str(seed))


def dominant_seed(series):
    """Return the most common known seed value in a phase, or None if all missing."""
    known = series[series.isin(SEED_LABELS.keys())]
    if len(known) > 0:
        return known.mode().iloc[0]
    return None


def assign_condition_letters(ordered_labels):
    """Map condition labels to single-letter codes (A, B, C, ...) in
    first-appearance order. Whitespace/newlines in labels are normalized so
    'Finch\\nFood' and 'Finch Food' collapse to one entry. Returns
    (normalized_label -> letter, [(letter, normalized_label), ...] for a legend).
    Single letters stay readable however many/short the phases get, where full
    text used to overlap neighboring labels and the phase-change lines."""
    import string
    letters, legend = {}, []
    for lab in ordered_labels:
        key = ' '.join(str(lab).split())
        if key and key not in letters:
            code = string.ascii_uppercase[len(letters)] if len(letters) < 26 else f'#{len(letters)}'
            letters[key] = code
            legend.append((code, key))
    return letters, legend

# Create dashboard output directory
DASHBOARD_DIR = '../docs/dashboard_plots'
os.makedirs(DASHBOARD_DIR, exist_ok=True)
os.makedirs(f'{DASHBOARD_DIR}/images', exist_ok=True)
os.makedirs(f'{DASHBOARD_DIR}/interactive', exist_ok=True)

# Time-binning config
TIME_BIN_START_HOUR = 0     # 6 AM
TIME_BIN_END_HOUR = 23      # 8 PM (20 in 24h)
TIME_BIN_MINUTES = 30       # 30-minute bins


# Function to save matplotlib plots
def save_plot_for_dashboard(fig, filename, title, description=""):
    """Save matplotlib figure for dashboard with metadata."""
    # Save as web-resolution PNG (dpi=120). Matches all_sites_all_analytics
    # so dashboard images stay crisp but small enough for reliable Pages
    # deploys as the dataset grows.
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


# ---------------------------------
# Load data
# ---------------------------------
print("Loading data...")
raw_data = pd.read_csv(RAW_DATA_CSV)
raw_data = raw_data[raw_data['source_sheet'] == SITE_SHEET]
raw_data['Date'] = pd.to_datetime(raw_data['Date'])
# Older CSVs predate the side-time columns
for col in ('LeftTime_s', 'RightTime_s'):
    if col not in raw_data.columns:
        raw_data[col] = np.nan
site_raw = raw_data.copy()  # every visit, including squirrels (no pecks) with side time
raw_data = raw_data.dropna(subset=['RightPecks'])

# Load phase changes for this site (canonical source of truth)
print("Loading phase changes...")
phase_changes_all = pd.read_csv(PHASE_CHANGES_CSV)
phase_changes_all['LocationOfChange'] = phase_changes_all['LocationOfChange'].astype(str).str.strip()
site_phase_changes = phase_changes_all[
    phase_changes_all['LocationOfChange'] == SITE_PHASE_LOCATION
].copy()
site_phase_changes['DateChangeStarted'] = pd.to_datetime(
    site_phase_changes['DateChangeStarted'], errors='coerce'
)
phase_boundaries = sorted(
    pd.to_datetime(site_phase_changes['DateChangeStarted'].dropna().unique())
)

# ---------------------------------
# Peck data preparation
# ---------------------------------
print("Preparing peck data...")
peck_data = raw_data[['Date', 'Bird', 'RightPecks', 'LeftPecks', 'RightSeed', 'LeftSeed']]
peck_data = peck_data.groupby(['Date', 'Bird']).agg(
    right_pecks=('RightPecks', 'sum'),
    left_pecks=('LeftPecks', 'sum'),
    right_seeds=('RightSeed', 'first'),
    left_seeds=('LeftSeed', 'first')
).reset_index()
peck_data[['right_pecks', 'left_pecks']] = peck_data[['right_pecks', 'left_pecks']] + 1
peck_data['log_ratio_left_right'] = np.log(peck_data['left_pecks'] / peck_data['right_pecks'])

# ---------------------------------
# Side preference plots (pecks and time on each side)
# ---------------------------------
def build_phases(data_min, data_max, seed_rows):
    """Phases spanning [data_min, data_max] from phase_change_data.csv. Each
    phase is [phase_start, next_phase_start) and is annotated with the dominant
    LeftSeed/RightSeed actually observed in seed_rows for that window."""
    phase_starts = [data_min] + [b for b in phase_boundaries if data_min < b <= data_max]
    phase_ends = phase_starts[1:] + [data_max + pd.Timedelta(days=1)]
    phases = []
    for start, end in zip(phase_starts, phase_ends):
        window = seed_rows[(seed_rows['Date'] >= start) & (seed_rows['Date'] < end)]
        if window.empty:
            continue
        actual_first = window['Date'].min()
        actual_last = window['Date'].max()
        phases.append({
            'start': start,
            'end': end,
            'first_date': actual_first,
            'last_date': actual_last,
            'mid': actual_first + (actual_last - actual_first) / 2,
            'duration_days': (end - start).days,
            'left_label': label_for_seed(dominant_seed(window['LeftSeed'])),
            'right_label': label_for_seed(dominant_seed(window['RightSeed'])),
        })
    return phases


def build_transitions(phases):
    """Transition midpoints + line styles. Solid line: at least one adjacent
    phase has "No Seed" on either side. Dashed: between two food-only conditions."""
    transitions = []
    for i in range(len(phases) - 1):
        prev_phase = phases[i]
        next_phase = phases[i + 1]
        mid = prev_phase['last_date'] + (next_phase['first_date'] - prev_phase['last_date']) / 2
        involves_no_seed = NO_SEED_LABEL in (
            prev_phase['left_label'], prev_phase['right_label'],
            next_phase['left_label'], next_phase['right_label'],
        )
        transitions.append({'mid': mid, 'linestyle': '-' if involves_no_seed else '--'})
    return transitions


def plot_side_ratio_by_bird(daily, seed_rows, exclude, ylabel, filename, title, description,
                            min_days=5, x_pad_left=4, x_pad_right=14, date_fmt='%m-%d'):
    """Small multiples of the daily log(left / right) ratio per bird, broken at
    phase changes, with seed-condition letters (top = left feeder seed, bottom =
    right feeder seed). `daily` has Date, Bird, log_ratio_left_right."""
    data_min = daily['Date'].min()
    data_max = daily['Date'].max()
    phases = build_phases(data_min, data_max, seed_rows)
    transitions = build_transitions(phases)

    # --- Filter birds with at least min_days days of data ---
    days_per_bird = daily.groupby('Bird')['Date'].nunique()
    birds = sorted(b for b in days_per_bird[days_per_bird >= min_days].index
                   if b not in exclude and not str(b).lower().startswith(NOT_A_SPECIES_PREFIX))

    n_birds = len(birds)
    n_cols = 4
    n_rows = max(1, math.ceil(n_birds / n_cols))

    fig, axes = plt.subplots(
        n_rows, n_cols,
        figsize=(7 * n_cols, 4 * n_rows),
        sharex=True,
        sharey=True,
        squeeze=False,
    )
    axes = axes.flatten()

    # Global y-limits
    max_y = max(
        np.abs(daily['log_ratio_left_right'].min()),
        daily['log_ratio_left_right'].max()
    ) + 3

    xlim_left = data_min - pd.Timedelta(days=x_pad_left)
    xlim_right = data_max + pd.Timedelta(days=x_pad_right)

    for ax, bird in zip(axes, birds):
        df = daily[daily['Bird'] == bird].sort_values('Date')

        # Plot each phase as a separate line so the trace breaks at boundaries
        for phase in phases:
            phase_df = df[(df['Date'] >= phase['start']) & (df['Date'] < phase['end'])]
            if phase_df.empty:
                continue
            ax.plot(phase_df['Date'], phase_df['log_ratio_left_right'],
                    marker='o', markersize=4, markerfacecolor='black',
                    markeredgecolor='black', markeredgewidth=1,
                    linewidth=1, color='black')

        # Phase-change lines (solid/dashed determined dynamically above)
        for transition in transitions:
            if pd.notna(transition['mid']):
                ax.axvline(x=transition['mid'], color='black',
                           linestyle=transition['linestyle'], linewidth=1)
        ax.axhline(y=0, color='black', linewidth=1)

        sns.despine(ax=ax, top=True, right=True)
        ax.set_ylim(-max_y, max_y)
        ax.set_xlim(xlim_left, xlim_right)

        ax.set_title(bird, fontsize=14)

    # Phase labels: mark each phase span with a single-letter code (top = Left
    # feeder seed, bottom = Right feeder seed) placed at the span midpoint - away
    # from the phase-change lines at the boundaries - with a legend mapping the
    # letters to conditions. Single letters stay legible however many/short the
    # phases get, where the full text used to overlap the lines and each other.
    labeled_phases = [
        p for p in phases
        if pd.notna(p['mid']) and p['duration_days'] >= SHORT_PHASE_DAYS
    ]
    labeled_phases.sort(key=lambda p: p['mid'])
    # Assign letters over left-side then right-side seeds in chronological order.
    letter_map, legend_entries = assign_condition_letters(
        [p['left_label'] for p in labeled_phases]
        + [p['right_label'] for p in labeled_phases]
    )

    def _code(label):
        return letter_map[' '.join(str(label).split())]

    # Center each letter within its condition span - midway between the bounding
    # phase-change lines (or the axis edges for the first/last span) - rather than
    # at the data midpoint, so codes sit visually centered in each condition.
    n_phases = len(phases)

    def _span_center(j):
        left = xlim_left if j == 0 else transitions[j - 1]['mid']
        right = xlim_right if j == n_phases - 1 else transitions[j]['mid']
        if pd.isna(left):
            left = phases[j]['start']
        if pd.isna(right):
            right = phases[j]['end']
        return left + (right - left) / 2

    y_code = max_y * 0.9
    for ax in axes[:n_birds]:
        for j, phase in enumerate(phases):
            if pd.isna(phase['mid']) or phase['duration_days'] < SHORT_PHASE_DAYS:
                continue
            cx = _span_center(j)
            ax.text(cx, y_code, _code(phase['left_label']),
                    ha='center', va='center', fontsize=11, fontweight='bold')
            ax.text(cx, -y_code, _code(phase['right_label']),
                    ha='center', va='center', fontsize=11, fontweight='bold')

    # Use the first unused grid cell as a legend for the letter codes; hide the rest.
    legend_text = 'Seed condition key\n' + '\n'.join(
        f'{code} = {name}' for code, name in legend_entries
    )
    for j in range(n_birds, len(axes)):
        axes[j].axis('off')
    if n_birds < len(axes):
        axes[n_birds].text(0.02, 0.98, legend_text, transform=axes[n_birds].transAxes,
                           ha='left', va='top', fontsize=12, family='monospace')

    # Format x-ticks and rotate 45 degrees
    for ax in axes:
        ax.xaxis.set_major_formatter(mdates.DateFormatter(date_fmt))
        ax.tick_params(axis='x', labelrotation=45)

    fig.text(0.5, 0.0, 'Date', ha='center', fontsize=30)
    fig.text(0.0825, 0.5, ylabel, va='center', rotation='vertical', fontsize=30)

    plt.subplots_adjust(hspace=0.3)
    save_plot_for_dashboard(fig, filename, title, description)
    plt.close(fig)
    return birds


print("Generating seed preference plot...")
peck_data['Date'] = pd.to_datetime(peck_data['Date'])
plot_side_ratio_by_bird(
    peck_data, raw_data, EXCLUDE_SPECIES,
    'Log(Left Pecks (top) / Right Pecks (bottom))',
    'seed_preference_by_bird',
    'Seed Preference by Bird and Feeder Side\n(Right Side More Open)',
    'Seed preference by bird',
)

# ---------------------------------
# Side time preference (seconds the head was over each side)
# ---------------------------------
# LeftTime_s/RightTime_s are scored from Birdfy clips from 2026-11-05 on: the
# seconds a bird's head was over the left / right tray, sampled at 4 fps. As
# with pecks, 1 is added before the ratio so a side with no time does not
# divide by zero; here the unit is one second.
time_rows = site_raw.dropna(subset=['LeftTime_s', 'RightTime_s'], how='all').copy()
time_rows[['LeftTime_s', 'RightTime_s']] = time_rows[['LeftTime_s', 'RightTime_s']].fillna(0)
time_data = time_rows.groupby(['Date', 'Bird']).agg(
    right_time=('RightTime_s', 'sum'),
    left_time=('LeftTime_s', 'sum'),
).reset_index()
time_data['log_ratio_left_right'] = np.log((time_data['left_time'] + 1) / (time_data['right_time'] + 1))

if time_data.empty:
    print("No side-time data yet; skipping side time plots.")
else:
    print("Generating side time preference plot...")
    # The squirrel stays in: it has side time even though its pecks are not counted.
    plot_side_ratio_by_bird(
        time_data, site_raw, set(),
        'Log(Left Time (top) / Right Time (bottom))',
        'side_time_preference_by_bird',
        'Time on Each Feeder Side by Bird\n(Right Side More Open)',
        'Daily log((seconds on left + 1) / (seconds on right + 1)) per bird, from head position in '
        'Birdfy clips (scored from 2026-11-05). Squirrels are included because their side time is scored.',
        min_days=3, x_pad_left=1, x_pad_right=2,
    )

    # ---------------------------------
    # Pecks vs time: do the two measures of side preference agree?
    # ---------------------------------
    print("Generating peck vs time ratio comparison plot...")
    both = peck_data.merge(time_data, on=['Date', 'Bird'], suffixes=('_pecks', '_time'))
    both = both[~both['Bird'].isin(EXCLUDE_SPECIES)
                & ~both['Bird'].str.lower().str.startswith(NOT_A_SPECIES_PREFIX)]
    if len(both) >= 3:
        from scipy.stats import spearmanr
        xcol, ycol = 'log_ratio_left_right_pecks', 'log_ratio_left_right_time'
        lim = max(both[[xcol, ycol]].abs().max()) + 0.5
        species = sorted(both['Bird'].unique())
        # Species panels need at least 3 days; every bird-day still counts in 'All birds'.
        panels = [('All birds', both)] + [(b, both[both['Bird'] == b]) for b in species
                                          if (both['Bird'] == b).sum() >= 3]
        n_cols = 4
        n_rows = math.ceil(len(panels) / n_cols)
        fig, axes = plt.subplots(n_rows, n_cols, figsize=(5 * n_cols, 5 * n_rows),
                                 sharex=True, sharey=True, squeeze=False)
        axes = axes.flatten()

        def _agreement(df, with_p=False):
            # Same side: both ratios nonzero and with the same sign; days where
            # either measure is exactly balanced (ratio 0) are left out.
            decided = df[(df[xcol] != 0) & (df[ycol] != 0)]
            same = int((np.sign(decided[xcol]) == np.sign(decided[ycol])).sum())
            lines = [f'{len(df)} days; same side on {same} of {len(decided)}']
            if len(df) >= 5 and df[xcol].nunique() > 1 and df[ycol].nunique() > 1:
                rho, p = spearmanr(df[xcol], df[ycol])
                lines.append(f'Spearman rho = {rho:.2f}' + (f' (p = {p:.2g})' if with_p else ''))
            return '\n'.join(lines)

        for ax, (name, df) in zip(axes, panels):
            ax.plot([-lim, lim], [-lim, lim], color='black', linewidth=1, linestyle='--')
            ax.axhline(0, color='grey', linewidth=0.8)
            ax.axvline(0, color='grey', linewidth=0.8)
            ax.scatter(df[xcol], df[ycol], s=36, color='black', alpha=0.75 if name == 'All birds' else 1)
            ax.set_xlim(-lim, lim)
            ax.set_ylim(-lim, lim)
            ax.set_aspect('equal')
            ax.set_title(name, fontsize=14, fontweight='bold' if name == 'All birds' else 'normal')
            ax.text(0.03, 0.97, _agreement(df, with_p=name == 'All birds'), transform=ax.transAxes, ha='left', va='top', fontsize=10)
            sns.despine(ax=ax, top=True, right=True)
        for ax in axes[len(panels):]:
            ax.axis('off')
        fig.text(0.5, 0.02, 'Log(Left Pecks / Right Pecks)', ha='center', fontsize=22)
        fig.text(0.04, 0.5, 'Log(Left Time / Right Time)', va='center', rotation='vertical', fontsize=22)
        plt.subplots_adjust(hspace=0.3, wspace=0.15, left=0.08, bottom=0.1)
        save_plot_for_dashboard(
            fig,
            'peck_vs_time_ratio',
            'Side Preference: Pecks vs Time on Each Side',
            'Each point is one bird on one day: log((left pecks + 1) / (right pecks + 1)) on x and '
            'log((left seconds + 1) / (right seconds + 1)) on y. Points on the dashed line show the same '
            'preference by both measures; points in the top-right or bottom-left quadrant agree on the side. '
            '"Same side" counts bird-days where both measures favor the same side, leaving out days where either is exactly balanced. '
            'Spearman rho is shown for 5 or more days; with this few days per species it is descriptive only. '
            'Species need 3 or more days for their own panel; all bird-days count in "All birds".',
        )
        plt.close(fig)
    else:
        print("Too few bird-days with both pecks and side time; skipping comparison plot.")

# ---------------------------------
# Peck distribution by bird plot
# ---------------------------------
print("Generating peck distribution plot...")

# Get all unique birds (excluding non-birds)
bird_counts = raw_data['Bird'].value_counts().reset_index()
bird_counts = bird_counts[bird_counts['count'] >= 10]
unique_birds = sorted(b for b in bird_counts['Bird'].unique()
                      if b not in EXCLUDE_SPECIES)
n_birds = len(unique_birds)

# Calculate grid dimensions (aim for roughly square layout)
n_cols = int(3)
n_rows = int(np.ceil(n_birds / n_cols))

# Create subplot grid
fig, axes = plt.subplots(n_rows, n_cols, figsize=(6 * n_cols, 6 * n_rows), sharey=True)
axes = axes.flatten() if n_birds > 1 else [axes] if n_rows == 1 and n_cols == 1 else axes.flatten()

# Process and plot each bird
for idx, bird in enumerate(unique_birds):
    ax = axes[idx]

    # Filter data for this bird
    bird_data = raw_data[(raw_data['Bird'] == bird)].copy()
    bird_data['TotalPecks'] = bird_data['RightPecks'] + bird_data['LeftPecks']

    # Process Golden Safflower pecks
    saff_pecks_a = bird_data[bird_data['RightSeed'] == 'Golden Safflower']['RightPecks'].value_counts()
    saff_pecks_b = bird_data[bird_data['LeftSeed'] == 'Golden Safflower']['LeftPecks'].value_counts()
    plot_saff_a = saff_pecks_a.reset_index()
    plot_saff_b = saff_pecks_b.reset_index()
    plot_saff_a.columns = ['Pecks', 'Count']
    plot_saff_b.columns = ['Pecks', 'Count']
    saff_df = pd.merge(plot_saff_a, plot_saff_b, on='Pecks', how='outer').reset_index(drop=True)
    saff_df['Count'] = saff_df['Count_x'].fillna(0) + saff_df['Count_y'].fillna(0)
    saff_df = saff_df[saff_df['Pecks'] > 0]
    saff_df['Count_Proportion'] = saff_df['Count'] / saff_df['Count'].sum()

    # Process Special Finch Food pecks
    finch_pecks_a = bird_data[bird_data['RightSeed'] == 'Special Finch Food']['RightPecks'].value_counts()
    finch_pecks_b = bird_data[bird_data['LeftSeed'] == 'Special Finch Food']['LeftPecks'].value_counts()
    plot_finch_a = finch_pecks_a.reset_index()
    plot_finch_b = finch_pecks_b.reset_index()
    plot_finch_a.columns = ['Pecks', 'Count']
    plot_finch_b.columns = ['Pecks', 'Count']
    finch_df = pd.merge(plot_finch_a, plot_finch_b, on='Pecks', how='outer').reset_index(drop=True)
    finch_df['Count'] = finch_df['Count_x'].fillna(0) + finch_df['Count_y'].fillna(0)
    finch_df = finch_df[finch_df['Pecks'] > 0]
    finch_df['Count_Proportion'] = finch_df['Count'] / finch_df['Count'].sum()

    # Process Low Dove Mix Food pecks
    low_dove_pecks_a = bird_data[bird_data['RightSeed'] == 'Sunflower, Safflower, Mealworm, Peanuts']['RightPecks'].value_counts()
    low_dove_pecks_b = bird_data[bird_data['LeftSeed'] == 'Sunflower, Safflower, Mealworm, Peanuts']['LeftPecks'].value_counts()
    plot_low_dove_a = low_dove_pecks_a.reset_index()
    plot_low_dove_b = low_dove_pecks_b.reset_index()
    plot_low_dove_a.columns = ['Pecks', 'Count']
    plot_low_dove_b.columns = ['Pecks', 'Count']
    low_dove_df = pd.merge(plot_low_dove_a, plot_low_dove_b, on='Pecks', how='outer').reset_index(drop=True)
    low_dove_df['Count'] = low_dove_df['Count_x'].fillna(0) + low_dove_df['Count_y'].fillna(0)
    low_dove_df = low_dove_df[low_dove_df['Pecks'] > 0]
    low_dove_df['Count_Proportion'] = low_dove_df['Count'] / low_dove_df['Count'].sum()

    # Combine data
    saff_df['Seed'] = 'Golden Safflower'
    finch_df['Seed'] = 'Special Finch Food'
    low_dove_df['Seed'] = 'Sunflower, Safflower, Mealworm, Peanuts'
    plot_all = pd.concat([saff_df, finch_df, low_dove_df]).reset_index(drop=True)

    # Plot on this subplot
    if len(plot_all) > 0:
        sns.barplot(
            x='Pecks', y='Count_Proportion', data=plot_all[plot_all['Seed'] == 'Special Finch Food'],
            color='black', ax=ax, label='Special Finch Food', alpha=0.4)
        sns.barplot(
            x='Pecks', y='Count_Proportion', data=plot_all[plot_all['Seed'] == 'Golden Safflower'],
            color='gold', ax=ax, label='Golden Safflower', alpha=0.4)
        sns.barplot(
            x='Pecks', y='Count_Proportion', data=plot_all[plot_all['Seed'] == 'Sunflower, Safflower, Mealworm, Peanuts'],
            color='red', ax=ax, label='Low Dove Mix', alpha=0.4)
        ax.legend(frameon=False, fontsize=12)
        ax.set_ylabel('Proportion of Feeder Visits', fontsize=24, labelpad=12)
        ax.set_xlabel('Number of Pecks', fontsize=20, labelpad=12)
        ax.set_title(bird, fontsize=18, pad=12)
        ax.set_yscale('symlog', linthresh=0.0001)
        ax.set_ylim(0.001, 1.1)
        ax.set_yticks(ticks=[0.001, 0.01, 0.1, 1], labels=['0.001', '0.01', '0.1', '1'])
        xticks = np.arange(1, 41, 2)
        ax.set_xticks(ticks=xticks, labels=xticks)
        ax.set_xlim(0.5, 41)
        sns.despine(top=True, right=True, ax=ax)
    else:
        ax.set_title(bird, fontsize=18, pad=12)
        ax.text(0.5, 0.5, 'No data', ha='center', va='center', transform=ax.transAxes)
        sns.despine(top=True, right=True, ax=ax)

# Hide unused subplots
for idx in range(n_birds, len(axes)):
    axes[idx].set_visible(False)

plt.tight_layout()
plt.subplots_adjust(hspace=0.5)

# Save diversity metrics plot for dashboard
save_plot_for_dashboard(
    fig,
    'peck_distribution_by_bird',
    'Number of Pecks per Visit by Seed Type',
    'The number of pecks per visit by seed type for each bird.'
)
plt.close(fig)

print("one_site_analytics.py complete.")
