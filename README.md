# Backyard Ecology: Bird Visit Analysis

A data analysis project for tracking and visualizing bird feeder visits in backyard ecosystems. This project combines automated data collection with advanced analytics to understand bird behavior patterns, migration timing, and ecological diversity.

## Project Overview

This project analyzes bird feeder visit data collected from multiple sites, focusing on:
- **Temporal patterns** of bird visits throughout the day and across seasons
- **Species diversity** metrics including Shannon H, species richness, and beta diversity
- **Migration correlation** with BirdCast migration data
- **Static dashboard** published automatically to GitHub Pages
- **Visualization** of complex ecological data through high-quality static plots and heatmaps

## Data Sources

- **Primary Data**: `multi_site_data.xlsx` - Bird feeder visit records with timestamps
- **Migration Data**: BirdCast API integration for migration timing correlation
- **Weather Data**: OpenWeatherMap API for environmental context

## Setup Instructions

### Prerequisites
- Python 3.8+
- Jupyter Notebook
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

4. **Launch Jupyter Notebook**
   ```bash
   jupyter notebook
   ```

## Project Structure

```
backyard-ecology/
├── README.md                    # This file
├── requirements.txt             # Python dependencies
├── GITHUB_PAGES_SETUP.md       # Dashboard setup guide
├── data/
│   ├── multi_site_data.xlsx    # Primary bird visit data
│   └── haikubox.csv            # HaikuBox data
├── docs/                       # Generated dashboard (GitHub Pages)
│   ├── index.html              # Main dashboard
│   └── dashboard_plots/        # Saved plots and metadata
├── scripts_notebooks/
│   ├── analytics.ipynb         # Main analysis notebook
│   ├── daily_update.py         # Daily workflow script
│   ├── simple_dashboard.py     # Dashboard generator
│   ├── haikubox.py             # HaikuBox data processing
│   ├── haikubox.ipynb          # HaikuBox analysis
│   ├── birdweather.py          # Weather data processing
│   └── weather.py              # Weather utilities
└── .github/workflows/
    └── deploy-dashboard.yml    # GitHub Pages deployment
```

## Current Analyses

### 1. Temporal Analysis (`analytics.ipynb`)
- **3D Surface Plots**: Date vs. Time of Day vs. Observation Count
- **Heatmaps**: Daily and proportional activity patterns
- **Line Plots**: Species-specific visit trends with custom bird colors

### 2. Diversity Metrics
- **Alpha Diversity**: Shannon H index for daily species diversity
- **Species Richness**: Count of unique species per day
- **Beta Diversity**: Sørensen dissimilarity for species turnover
- **Rolling Analysis**: 3-day moving window for smoother trends

### 3. Migration Correlation
- **BirdCast Integration**: Correlation with migration timing data
- **Dual-axis Plots**: Feeder visits vs. migration intensity

## Configuration

### Time Binning
- **Active Hours**: 6 AM - 8 PM
- **Bin Size**: 30 minutes
- **Customizable** in the config section

### API Keys
- **Weather API**: OpenWeatherMap (configure in `analytics.ipynb`)
- **Location**: Jacksonville, FL (30.09°N, 81.61°W)

## Dashboard Workflow

### Daily Update Process

1. **Run Analysis**: Execute `analytics.ipynb` to generate plots
2. **Generate Dashboard**: Run `python daily_update.py` to create HTML dashboard
3. **Deploy**: Commit and push to GitHub for automatic deployment

```bash
# Daily workflow
cd scripts_notebooks
python daily_update.py
git add docs/
git commit -m "Update dashboard - $(date)"
git push origin main
```

### Live Dashboard

The dashboard is automatically published to GitHub Pages and available at:
`https://yourusername.github.io/backyard-ecology/`

## Data Processing Pipeline

1. **Raw Data Ingestion**: Excel files → Pandas DataFrames
2. **Time Binning**: Continuous timestamps → Discrete time periods
3. **Species Aggregation**: Individual visits → Daily summaries
4. **Diversity Calculation**: Visit counts → Ecological metrics
5. **Plot Generation**: Processed data → Saved plots with metadata
6. **Dashboard Creation**: Saved plots → Static HTML dashboard
7. **Automatic Deployment**: GitHub Pages → Live public dashboard

## Development

### Branch Structure
- `main`: Production-ready code
- `dev`: Development and experimental features

### Contributing
1. Create feature branch from `dev`
2. Make changes and test thoroughly
3. Submit pull request to `dev` branch
4. After review, merge to `main`

## License
This project is open source. Please cite appropriately if used in research.

## Contact

**David Cox**  
GitHub: [@david-j-cox](https://github.com/david-j-cox)

---

*Happy birding!*
