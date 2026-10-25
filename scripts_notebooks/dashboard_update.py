#!/usr/bin/env python3
"""
Study page generator - reads saved plots and writes docs/study.html.

The figures come from the analytics scripts (one JSON metadata file per plot in
docs/dashboard_plots/). They are grouped by topic so they are easy to find and
present: each figure has a direct link, a full-screen view, and a PNG download.
The interactive backyard view (docs/index.html) is static and reads
docs/data/dashboard.json instead.
"""
import glob
import json
from datetime import datetime
from html import escape
from pathlib import Path

# Sections in presentation order: (section title, [(plot filename, fallback title), ...])
STUDY_SECTIONS = [
    ("Feeder visits and study phases", [
        ("species_visits_by_date", "Daily Bird Feeder Visits by Species"),
        ("mbd_plot", "Multiple Baseline of Feeder Visits"),
    ]),
    ("Ecological diversity", [
        ("diversity_metrics", "Ecological Diversity Metrics"),
        ("diversity_metrics_corr_matrix", "Correlation Matrix of Diversity Metrics"),
    ]),
    ("Acoustic monitoring and migration", [
        ("puc_audio_data_nj_jcv", "Auditory Data from Essex Fells PUC"),
        ("puc_audio_data_puc_21974_cox", "Auditory Data from Jacksonville PUC"),
        ("puc_audio_data_puc_site_to_county", "Auditory Data from Study Site vs County with Migration"),
        ("puc_site_county_faceted", "Study Site vs County PUC Activity by Station"),
        ("all_flyways_total_birds", "US Flyway Migration - Total Birds"),
    ]),
    ("Time of day", [
        ("heatmap_counts", "Heatmap: Date vs Time of Day as a Count of Observations"),
        ("heatmap_proportions", "Heatmap: Date vs Time of Day as a Proportion of Observations"),
        ("heatmap_proportions_sunrise_sunset", "Heatmap: Proportion of Observations Relative to Sunrise and Sunset"),
    ]),
    ("Weather", [
        ("prop_visits_wind_temp", "Proportion of Visits by Wind Speed and Temperature"),
        ("species_cluster_visits_by_weather", "Species Clustermap Using Visits and Weather"),
        ("cor_plot_weather_data", "Correlation of Visits with Weather"),
        ("visit_predict_from_weather", "Predicting Visits from Weather"),
    ]),
    ("Bout analysis", [
        ("all_birds_bout_analysis", "All Birds: Bout Analysis"),
        ("all_birds_bout_seed_no_seed_separate", "All Birds: Bout Analysis Separating Seed and No Seed Conditions"),
        ("all_birds_bout_analysis_within_date", "All Birds: Bout Analysis (Within-Date Only)"),
        ("individual_species_bout_analysis", "Bird Species: Bout Analysis (log space)"),
    ]),
    ("Behavioral momentum", [
        ("bm_by_species", "Behavioral Momentum by Species"),
    ]),
    ("Seed preference and pecks", [
        ("seed_preference_by_bird", "Seed Preference by Bird and Feeder Side"),
        ("peck_distribution_by_bird", "Number of Pecks per Visit by Seed Type"),
    ]),
]

PAGE_SCRIPT = """
document.querySelectorAll('[data-fullscreen]').forEach((btn) => {
  btn.addEventListener('click', () => {
    const fig = document.getElementById(btn.dataset.fullscreen);
    if (document.fullscreenElement) document.exitFullscreen();
    else if (fig.requestFullscreen) fig.requestFullscreen();
  });
});
document.querySelectorAll('[data-copy]').forEach((btn) => {
  btn.addEventListener('click', async () => {
    const url = location.href.split('#')[0] + '#' + btn.dataset.copy;
    try {
      await navigator.clipboard.writeText(url);
      btn.textContent = 'Link copied';
    } catch (e) {
      location.hash = btn.dataset.copy;
      btn.textContent = 'Link in address bar';
    }
    setTimeout(() => { btn.textContent = 'Copy link'; }, 2000);
  });
});
"""


def load_plot_metadata(dashboard_dir):
    """Map plot filename -> metadata dict written by the analytics scripts."""
    plots = {}
    for plot_file in glob.glob(f"{dashboard_dir}/*.json"):
        try:
            with open(plot_file, 'r') as f:
                metadata = json.load(f)
            if metadata.get('filename'):
                plots[metadata['filename']] = metadata
        except Exception as e:
            print(f"Warning: Could not load {plot_file}: {e}")
    return plots


def figure_html(filename, fallback_title, plot, docs_dir):
    """One figure card, or None if this run's analytics did not produce the plot."""
    if not plot:
        return None
    title = escape(plot.get('title') or fallback_title)
    created = escape(str(plot.get('created', ''))[:10])
    plot_type = plot.get('type', 'matplotlib')
    fig_id = escape(filename)

    if plot_type == 'plotly':
        html_path = plot.get('html_path', '')
        if html_path.startswith('interactive/'):
            html_path = f"dashboard_plots/{html_path}"
        body = (f'<iframe src="{escape(html_path)}" title="{title}" loading="lazy"></iframe>')
        actions = f'<a href="{escape(html_path)}" target="_blank" rel="noopener">Open interactive version</a>'
    else:
        image_path = plot.get('image_path', '')
        if image_path.startswith('images/'):
            image_path = f"dashboard_plots/{image_path}"
        if not (docs_dir / image_path).exists():
            return None
        body = f'<img src="{escape(image_path)}" alt="{title}" loading="lazy">'
        actions = (f'<button type="button" data-fullscreen="{fig_id}">Full screen</button>'
                   f'<a href="{escape(image_path)}" download>Download PNG</a>')

    updated = f'<span class="updated">Updated {created}</span>' if created else ''
    return f"""
      <figure class="study-figure" id="{fig_id}">
        <figcaption>
          <h3><a href="#{fig_id}">{title}</a></h3>
          <div class="fig-actions">{actions}<button type="button" data-copy="{fig_id}">Copy link</button>{updated}</div>
        </figcaption>
        {body}
      </figure>"""


def create_simple_dashboard():
    """Write docs/study.html from the saved plots."""
    script_dir = Path(__file__).resolve().parent
    docs_dir = script_dir.parent / 'docs'
    dashboard_dir = docs_dir / 'dashboard_plots'
    plots = load_plot_metadata(dashboard_dir)

    listed = {name for _, figs in STUDY_SECTIONS for name, _ in figs}
    # Figures the analytics produce that are not placed in a section yet
    extras = [(name, plots[name].get('title', name)) for name in sorted(plots) if name not in listed]
    sections = STUDY_SECTIONS + ([("Other figures", extras)] if extras else [])

    toc, body = [], []
    for i, (section_title, figs) in enumerate(sections):
        cards = [c for c in (figure_html(n, t, plots.get(n), docs_dir) for n, t in figs) if c]
        if not cards:
            continue
        sec_id = f"section-{i + 1}"
        toc.append(f'<li><a href="#{sec_id}">{escape(section_title)}</a> <span>{len(cards)}</span></li>')
        body.append(f'<section class="study-section" id="{sec_id}"><h2>{escape(section_title)}</h2>{"".join(cards)}</section>')
        for name, _ in figs:
            if name not in plots:
                print(f"Warning: Plot '{name}' not found in saved plots")

    html_content = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Backyard Ecology Study</title>
  <link rel="stylesheet" href="assets/dashboard.css">
</head>
<body>
  <header class="site-header">
    <div class="wrap header-row">
      <h1>Backyard Ecology</h1>
      <nav class="tabs" aria-label="Sections">
        <a href="index.html">Backyard</a>
        <a href="study.html" aria-current="page">Study</a>
      </nav>
    </div>
  </header>
  <main class="wrap study">
    <p class="sub">Figures from the multi-site feeder study, regenerated with each daily update on {datetime.now().strftime('%Y-%m-%d')}. Each figure has a direct link for sharing and a full-screen view for presenting.</p>
    <nav class="toc" aria-label="Contents"><ol>{''.join(toc)}</ol></nav>
    {''.join(body)}
  </main>
  <script>{PAGE_SCRIPT}</script>
</body>
</html>
"""

    output = docs_dir / 'study.html'
    output.write_text(html_content)
    print(f"Study page created: {output}")
    print(f"Found {len(plots)} plots")


if __name__ == "__main__":
    create_simple_dashboard()
