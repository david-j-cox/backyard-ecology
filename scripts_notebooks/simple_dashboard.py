#!/usr/bin/env python3
"""
Simple dashboard generator - just reads saved plots and creates HTML.
No complex workflows needed.
"""

import os
import json
import glob
from datetime import datetime
from pathlib import Path

def create_simple_dashboard():
    """Create a simple HTML dashboard from saved plots."""
    
    # Set up paths
    dashboard_dir = '../docs/dashboard_plots'
    output_dir = '../docs'
    
    # Ensure output directory exists
    Path(output_dir).mkdir(exist_ok=True)
    
    # Load all plot metadata
    plot_files = glob.glob(f"{dashboard_dir}/*.json")
    plots = []
    
    for plot_file in plot_files:
        try:
            with open(plot_file, 'r') as f:
                metadata = json.load(f)
                plots.append(metadata)
        except Exception as e:
            print(f"Warning: Could not load {plot_file}: {e}")
    
    if not plots:
        print("No plots found! Run your analytics notebook first.")
        return
    
    # Sort by creation time
    plots.sort(key=lambda x: x.get('created', ''))
    
    # Create HTML content
    html_content = f"""
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Backyard Ecology Dashboard</title>
    <style>
        body {{
            font-family: Arial, sans-serif;
            margin: 0;
            padding: 20px;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            min-height: 100vh;
        }}
        .container {{
            max-width: 1200px;
            margin: 0 auto;
        }}
        .header {{
            text-align: center;
            color: white;
            margin-bottom: 40px;
        }}
        .header h1 {{
            font-size: 2.5rem;
            margin-bottom: 10px;
        }}
        .plots-grid {{
            display: grid;
            grid-template-columns: repeat(2, 1fr);
            gap: 30px;
            justify-content: center;
        }}
        .plot-card {{
            background: white;
            border-radius: 10px;
            padding: 20px;
            box-shadow: 0 4px 6px rgba(0,0,0,0.1);
            display: flex;
            flex-direction: column;
            height: 100%;
        }}
        .plot-card h3 {{
            margin-top: 0;
            color: #333;
        }}
        .plot-card img {{
            width: 100%;
            height: auto;
            border-radius: 5px;
            flex-grow: 1;
            object-fit: contain;
        }}
        .plot-card iframe {{
            width: 100%;
            height: 400px;
            border: none;
            border-radius: 5px;
        }}
        .metadata {{
            font-size: 0.9rem;
            color: #666;
            margin-top: 10px;
        }}
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>Backyard Ecology Dashboard</h1>
            <p>Last updated: {datetime.now().strftime('%Y-%m-%d %H:%M')}</p>
        </div>
        
        <div class="plots-grid">
"""
    
    # Define the specific plot order and groupings
    plot_order = [
        # Row 1
        'species_visits_by_date', 'migration_relation',
        # Row 2  
        'heatmap_counts', 'heatmap_proportions',
        # Row 3
        'all_birds_bout_analysis', 'individual_species_bout_analysis',
        # Row 4
        'diversity_metrics'
    ]
    
    # Create a lookup dictionary for plots by filename
    plot_lookup = {plot.get('filename', ''): plot for plot in plots}
    
    # Add plots in the specified order
    for filename in plot_order:
        if filename in plot_lookup:
            plot = plot_lookup[filename]
            title = plot.get('title', 'Untitled')
            description = plot.get('description', '')
            plot_type = plot.get('type', 'matplotlib')
            
            if plot_type == 'matplotlib':
                image_path = plot.get('image_path', '')
                # Fix path to include dashboard_plots folder
                if image_path.startswith('images/'):
                    image_path = f"dashboard_plots/{image_path}"
                html_content += f"""
                <div class="plot-card">
                    <h3>{title}</h3>
                    <img src="{image_path}" alt="{title}">
                    <div class="metadata">
                        <strong>Type:</strong> Static Plot<br>
                        <strong>Created:</strong> {plot.get('created', 'Unknown')}
                    </div>
                </div>
                """
            elif plot_type == 'plotly':
                html_path = plot.get('html_path', '')
                html_content += f"""
                <div class="plot-card">
                    <h3>{title}</h3>
                    <iframe src="{html_path}"></iframe>
                    <div class="metadata">
                        <strong>Type:</strong> Interactive Plot<br>
                        <strong>Created:</strong> {plot.get('created', 'Unknown')}
                    </div>
                </div>
                """
        else:
            print(f"Warning: Plot '{filename}' not found in saved plots")
    
    html_content += """
        </div>
    </div>
</body>
</html>
"""
    
    # Write the HTML file
    with open(f"{output_dir}/index.html", 'w') as f:
        f.write(html_content)
    
    print(f"Simple dashboard created: {output_dir}/index.html")
    print(f"Found {len(plots)} plots")

if __name__ == "__main__":
    create_simple_dashboard()
