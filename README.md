# Backyard Ecology: Bird Visit Analysis

A data analysis project for tracking and visualizing bird feeder visits in backyard ecosystems. This project combines automated data collection with advanced analytics to understand bird behavior patterns, migration timing, and ecological diversity. A daily GitHub Actions pipeline runs the dashboard update, while the heavier BirdWeather PUC refresh runs on a persistent Linux VM.

## Project Overview

This project analyzes bird feeder visit data collected from multiple sites, focusing on:
- **Temporal patterns** of bird visits throughout the day and across seasons
- **Species diversity** metrics including Shannon H, species richness, and beta diversity
- **Migration correlation** with BirdCast migration data
- **Weather correlation** with Open-Meteo weather and the PUC's own temperature/humidity sensors
- **Automated daily dashboard pipeline** via GitHub Actions — fetches lightweight data, runs analytics, generates dashboard, and deploys to GitHub Pages
- **Nightly PUC refresh** on a persistent Linux VM — updates large BirdWeather PUC data files outside GitHub Actions
- **Dashboard** published automatically to GitHub Pages: an interactive backyard view and a study page for presenting figures

## Data Sources

- **Primary Data**: Google Sheets — bird feeder visit records with timestamps (downloaded automatically by the pipeline)
- **BirdWeather PUC Audio Data**: Species detections from BirdWeather stations at each study site
- **Migration Data**: BirdCast API integration for migration timing correlation
- **Weather Data**: Open-Meteo (no API key) for hourly temperature, wind, and precipitation; OpenWeatherMap history through Feb 2026
- **Backyard Sensors**: The PUC's on-board temperature, humidity, pressure, air quality, and sound level readings, stored as hourly means

## Setup Instructions

> **Note:** Daily dashboard updates are fully automated via GitHub Actions. Local setup is only needed if you want to develop or modify the codebase.

### Prerequisites
- Python 3.12+
- Git

### Installation

1. **Clone the repository**
   ```bash
   git clone https://github.com/david-j-cox/backyard-ecology.git
   cd backyard-ecology
   ```

2. **Create virtual environment**
   ```bash
   python -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   ```

3. **Install dependencies**
   ```bash
   pip install -r requirements.txt
   ```

4. **Create a `.env` file** in the project root with your API keys:
   ```
   WEATHER_API_KEY=<your-openweathermap-key>
   JAX_BIRDWX_API_KEY=<your-jacksonville-birdweather-key>
   ESSEX_BIRDWX_API_KEY=<your-essex-birdweather-key>
   ```

## Project Structure

```
backyard-ecology/
├── README.md                              # This file
├── requirements.txt                       # Python dependencies
├── .env                                   # API keys (not committed)
├── scripts_notebooks/
│   ├── run_prod_scripts.py                # Orchestrates the full pipeline
│   ├── all_sites_all_analytics.py         # Cross-site analytics
│   ├── one_site_analytics.py              # Single-site analytics
│   ├── weather.py                         # OpenWeather fetch (retired; shared CSV schema)
│   ├── open_meteo_weather.py              # Daily weather fill from Open-Meteo
│   ├── puc_environment.py                 # PUC sensor history as hourly means
│   ├── merge_sites_data.py                # Merges multi-site Google Sheets data
│   ├── birdweather.py                     # BirdWeather API utilities
│   ├── birdweather_specific_pucs.py       # BirdWeather PUC station data
│   ├── dashboard_update.py                # Generates docs/study.html from saved plots
│   ├── export_dashboard_data.py           # Writes docs/data/dashboard.json for the backyard view
│   └── export_analyses.py                 # Writes docs/data/analyses.json for the study analyses
├── data/
│   ├── raw_data_from_gsheet/              # Raw data downloaded from Google Sheets
│   ├── multi_site_data.xlsx               # Merged bird visit data
│   ├── raw_data_all_locations.csv         # Combined raw data across sites
│   ├── daily_summaries_all_locations.csv  # Daily summary statistics
│   ├── hourly_weather.csv                 # Hourly weather observations
│   ├── sunrise_sunset.csv                 # Sunrise/sunset times
│   ├── puc_environment_hourly.csv         # PUC sensor readings, hourly means
│   ├── study_site_puc_data.csv            # BirdWeather PUC detections
│   └── phase_change_data.csv              # Phase-change analysis data
├── docs/                                  # Generated dashboard (GitHub Pages)
│   ├── index.html                         # Interactive backyard view (static page)
│   ├── study.html                         # Study figures, generated daily
│   ├── assets/                            # Dashboard CSS and JavaScript
│   ├── data/dashboard.json                # Daily summaries for the backyard view
│   ├── data/analyses.json                 # Visit-level data and momentum fits for the study analyses
│   └── dashboard_plots/                   # Plot JSON files and images
└── .github/workflows/
    ├── update-dashboard.yml               # Daily automated pipeline
    └── static.yml                         # GitHub Pages deployment config
```

## Current Analyses

### 1. Temporal Analysis
- **3D Surface Plots**: Date vs. Time of Day vs. Observation Count
- **Heatmaps**: Daily and proportional activity patterns (with sunrise/sunset overlays)
- **Line Plots**: Species-specific visit trends with custom bird colors

### 2. Diversity Metrics
- **Alpha Diversity**: Shannon H index for daily species diversity
- **Species Richness**: Count of unique species per day
- **Beta Diversity**: Sørensen dissimilarity for species turnover
- **Rolling Analysis**: 3-day moving window for smoother trends

### 3. Migration Correlation
- **BirdCast Integration**: Correlation with migration timing data
- **Dual-axis Plots**: Feeder visits vs. migration intensity

### 4. Weather Correlation
- **Temperature & Wind**: Heatmaps of visit counts and proportions by weather conditions
- **Correlation Matrix**: Diversity metrics vs. weather variables

## Configuration

### API Keys
Three API keys are required (set as GitHub Secrets for the Action, or in `.env` for local development):
- **WEATHER_API_KEY**: OpenWeatherMap API key
- **JAX_BIRDWX_API_KEY**: BirdWeather API key for the Jacksonville, FL station
- **ESSEX_BIRDWX_API_KEY**: BirdWeather API key for the Essex, NJ station

### Study Sites
- **Jacksonville, FL** (30.09°N, 81.61°W)
- **Essex, NJ** (40.78°N, 74.28°W)

### Time Binning
- **Active Hours**: 6 AM – 8 PM
- **Bin Size**: 30 minutes

## Dashboard Workflow

### Automated Daily Updates

The dashboard is updated automatically every day — no manual steps needed beyond data entry:

1. **Enter data** in the Google Sheets spreadsheet
2. **GitHub Action runs daily at 6:30 AM ET** (cron: `30 11 * * *` UTC)
3. The Action executes a 3-phase pipeline:
   - **Phase 1 — Fetch data**: Downloads Google Sheets data, migration/flyway data, Open-Meteo weather, and PUC sensor history. Large BirdWeather PUC refreshes run separately on the Linux VM described in `docs/operations/puc-digitalocean.md`.
   - **Phase 2 — Run analytics**: Executes `all_sites_all_analytics.py` and `one_site_analytics.py`
   - **Phase 3 — Generate dashboard**: Runs `dashboard_update.py` (study page), `export_dashboard_data.py` (backyard view data), and `export_analyses.py` (study analyses data)
4. The Action **commits** updated data and dashboard files to `main` and **deploys** to GitHub Pages

You can also trigger the pipeline manually from the **Actions** tab using the `workflow_dispatch` trigger.

### Live Dashboard

The dashboard is published to GitHub Pages at:
`https://david-j-cox.github.io/backyard-ecology/`

### Development Workflow

For code changes (new analytics, bug fixes, refactoring):

1. Work on the `dev` branch (or a feature branch off `dev`)
2. Open a pull request from `dev` → `main`
3. After merge, the next Action run will use the updated code

## Data Processing Pipeline

1. **Google Sheets Download** → Raw Excel in `data/raw_data_from_gsheet/`
2. **Site Merging** (`merge_sites_data.py`) → Unified `multi_site_data.xlsx` and CSVs
3. **Weather Fetch** (`open_meteo_weather.py`, `puc_environment.py`) → `hourly_weather.csv`, `sunrise_sunset.csv`, `puc_environment_hourly.csv`
4. **BirdWeather PUC Fetch** (`birdweather_specific_pucs.py`, `birdweather.py`) → `study_site_puc_data.csv`, `county_level_birdweather.parquet` via the nightly Linux VM job
5. **Analytics** (`all_sites_all_analytics.py`, `one_site_analytics.py`) → Plot JSON/images in `docs/dashboard_plots/`
6. **Dashboard Generation** (`dashboard_update.py`, `export_dashboard_data.py`) → `docs/study.html`, `docs/data/dashboard.json` (read by `docs/index.html`)
7. **Deployment** → GitHub Pages via `actions/deploy-pages`

## Development

### Branch Structure
- `main`: Production branch — the GitHub Action commits generated data and dashboard files here
- `dev`: Development branch for code changes only

### Contributing
1. Create a feature branch from `dev`
2. Make changes and test locally
3. Submit a pull request to `dev`
4. After review, merge to `main`

> **Important:** Never commit generated output files (data CSVs, plot JSON, `docs/`) to `dev`. Those files are produced exclusively by the GitHub Action on `main`.

## License
This project is open source. Please cite appropriately if used in research.

## Contact

**David Cox**
GitHub: [@david-j-cox](https://github.com/david-j-cox)

---

*Happy birding!*
