# GitHub Pages Dashboard Setup

This guide will help you set up GitHub Pages to publish your backyard ecology plots as a public dashboard.

## Prerequisites

- GitHub repository (public or private with GitHub Pro)
- Python environment with required packages
- API keys for external data sources (optional)

## Setup Steps

### 1. Enable GitHub Pages

1. Go to your repository on GitHub
2. Click **Settings** → **Pages**
3. Under **Source**, select **GitHub Actions**
4. This will enable automatic deployment when you push to the main branch

### 2. Configure Repository Secrets (Optional)

If you're using external APIs (like weather data), add your API keys as repository secrets:

1. Go to **Settings** → **Secrets and variables** → **Actions**
2. Click **New repository secret**
3. Add secrets like:
   - `WEATHER_API_KEY`: Your OpenWeatherMap API key
   - `BIRDCAST_API_KEY`: If using BirdCast API

### 3. Test Local Generation

Before pushing to GitHub, test the complete workflow locally:

```bash
# Activate your virtual environment
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Test the complete workflow
cd scripts_notebooks
python test_dashboard.py
```

This will:
1. Run your analytics notebook to generate plots
2. Save plots to the dashboard folder
3. Generate the dashboard HTML
4. Show you where to find the results

Alternatively, you can run the steps manually:

```bash
# Step 1: Run analytics notebook
jupyter nbconvert --to notebook --execute analytics.ipynb --output analytics_executed.ipynb

# Step 2: Generate dashboard
python generate_dashboard.py
```

This will create a `docs/` folder with your dashboard files.

### 4. Deploy to GitHub

1. **Commit and push your changes:**
   ```bash
   git add .
   git commit -m "Add GitHub Pages dashboard"
   git push origin main
   ```

2. **Check the Actions tab:**
   - Go to your repository on GitHub
   - Click the **Actions** tab
   - You should see the "Deploy Dashboard to GitHub Pages" workflow running
   - Wait for it to complete (usually 2-3 minutes)

3. **Access your dashboard:**
   - Once the workflow completes, your dashboard will be available at:
   - `https://yourusername.github.io/backyard-ecology/`

### 5. Customize Your Dashboard

#### Update Plot Generation
- Modify `scripts_notebooks/export_plots.py` to change which plots are generated
- Add new plot types by creating new functions in the export script
- Update the dashboard index to include new plots

#### Customize Styling
- Edit the HTML templates in the export script
- Modify the CSS in the dashboard index
- Add your own branding and colors

#### Add More Data Sources
- Extend the data loading functions
- Add new analysis functions
- Update the dashboard to display new metrics

## Dashboard Features

Your dashboard will include:

1. **Species Visit Trends**: Line plots showing daily visits by species
2. **3D Temporal Patterns**: Interactive 3D surface plots of activity patterns
3. **Ecological Diversity**: Shannon H and species richness metrics
4. **Migration Correlation**: Correlation between feeder visits and migration data

## Troubleshooting

### Common Issues

1. **Workflow fails to run:**
   - Check that your `requirements.txt` includes all necessary packages
   - Verify that your Python code runs without errors locally
   - Check the Actions logs for specific error messages

2. **Plots not displaying:**
   - Ensure all required data files are in the repository
   - Check that API keys are properly set as secrets
   - Verify that the export script completes without errors

3. **Dashboard not updating:**
   - The workflow only runs on pushes to the `main` branch
   - Check that GitHub Pages is enabled in repository settings
   - Verify that the workflow completed successfully

### Manual Deployment

If automatic deployment isn't working, you can manually deploy:

```bash
# Generate plots locally
cd scripts_notebooks
python export_plots.py

# Commit the generated files
git add docs/
git commit -m "Update dashboard plots"
git push origin main
```

## Advanced Configuration

### Custom Domain
To use a custom domain (e.g., `yourdomain.com`):

1. Add a `CNAME` file in the `docs/` folder with your domain
2. Update the GitHub Actions workflow to include the CNAME
3. Configure DNS settings with your domain provider

### Scheduled Updates
To automatically update plots with new data:

1. Add a scheduled trigger to the workflow:
   ```yaml
   on:
     schedule:
       - cron: '0 6 * * *'  # Run daily at 6 AM UTC
   ```

2. Set up data fetching in your export script
3. Commit and push the updated workflow

### Private Data
If your data contains sensitive information:

1. Use GitHub's encrypted secrets for API keys
2. Consider using a private repository with GitHub Pro
3. Implement data anonymization in your export script

## Next Steps

1. **Monitor Performance**: Check your dashboard regularly to ensure plots are updating
2. **Add Interactivity**: Consider adding JavaScript for dynamic filtering
3. **Mobile Optimization**: Ensure your dashboard works well on mobile devices
4. **Analytics**: Add Google Analytics or similar to track usage
5. **Documentation**: Create user guides for interpreting the ecological data

## Support

For issues with this setup:
- Check the GitHub Actions logs
- Review the export script for Python errors
- Ensure all dependencies are properly installed
- Verify that your data files are accessible

Your dashboard will be a powerful tool for sharing your backyard ecology research with the world! 🌿🐦
