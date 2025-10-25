#!/usr/bin/env python3
"""
Generate dashboard HTML from saved plots.
This script reads the saved plots and creates a beautiful dashboard.
"""

import os
import json
import glob
from datetime import datetime
from pathlib import Path

def load_plot_metadata(dashboard_dir):
    """Load all plot metadata from the dashboard directory."""
    plot_files = glob.glob(f"{dashboard_dir}/*.json")
    plots = []
    
    for plot_file in plot_files:
        try:
            with open(plot_file, 'r') as f:
                metadata = json.load(f)
                plots.append(metadata)
        except Exception as e:
            print(f"Warning: Could not load {plot_file}: {e}")
    
    # Sort by creation time
    plots.sort(key=lambda x: x.get('created', ''))
    return plots

def create_dashboard_html(plots, output_dir):
    """Create the main dashboard HTML file."""
    
    # Group plots by type
    matplotlib_plots = [p for p in plots if p.get('type') == 'matplotlib']
    plotly_plots = [p for p in plots if p.get('type') == 'plotly']
    
    html_content = f"""
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Backyard Ecology Dashboard</title>
    <style>
        * {{
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }}
        
        body {{
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            line-height: 1.6;
            color: #333;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            min-height: 100vh;
        }}
        
        .container {{
            max-width: 1400px;
            margin: 0 auto;
            padding: 20px;
        }}
        
        .header {{
            text-align: center;
            color: white;
            margin-bottom: 40px;
        }}
        
        .header h1 {{
            font-size: 3rem;
            margin-bottom: 10px;
            text-shadow: 2px 2px 4px rgba(0,0,0,0.3);
        }}
        
        .header p {{
            font-size: 1.2rem;
            opacity: 0.9;
        }}
        
        .last-updated {{
            font-size: 0.9rem;
            margin-top: 10px;
            opacity: 0.8;
        }}
        
        .plots-section {{
            margin-bottom: 50px;
        }}
        
        .section-title {{
            color: white;
            font-size: 2rem;
            margin-bottom: 20px;
            text-align: center;
            text-shadow: 1px 1px 2px rgba(0,0,0,0.3);
        }}
        
        .plots-grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(500px, 1fr));
            gap: 30px;
            margin-bottom: 40px;
        }}
        
        .plot-card {{
            background: white;
            border-radius: 12px;
            box-shadow: 0 8px 32px rgba(0,0,0,0.1);
            overflow: hidden;
            transition: transform 0.3s ease, box-shadow 0.3s ease;
        }}
        
        .plot-card:hover {{
            transform: translateY(-5px);
            box-shadow: 0 12px 40px rgba(0,0,0,0.15);
        }}
        
        .plot-header {{
            padding: 20px;
            background: linear-gradient(135deg, #4facfe 0%, #00f2fe 100%);
            color: white;
        }}
        
        .plot-header h3 {{
            margin: 0;
            font-size: 1.4rem;
        }}
        
        .plot-header p {{
            margin: 10px 0 0 0;
            opacity: 0.9;
            font-size: 0.95rem;
        }}
        
        .plot-content {{
            padding: 20px;
        }}
        
        .plot-image {{
            width: 100%;
            height: auto;
            border-radius: 8px;
            box-shadow: 0 4px 8px rgba(0,0,0,0.1);
        }}
        
        .plot-iframe {{
            width: 100%;
            height: 500px;
            border: none;
            border-radius: 8px;
            box-shadow: 0 4px 8px rgba(0,0,0,0.1);
        }}
        
        .plot-metadata {{
            margin-top: 15px;
            padding: 15px;
            background: #f8f9fa;
            border-radius: 8px;
            font-size: 0.9rem;
            color: #666;
        }}
        
        .footer {{
            text-align: center;
            color: white;
            margin-top: 40px;
            opacity: 0.8;
        }}
        
        @media (max-width: 768px) {{
            .plots-grid {{
                grid-template-columns: 1fr;
            }}
            
            .header h1 {{
                font-size: 2rem;
            }}
            
            .section-title {{
                font-size: 1.5rem;
            }}
        }}
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>🐦 Backyard Ecology Dashboard</h1>
            <p>Real-time analysis of bird feeder visits and ecological patterns</p>
            <p class="last-updated">Last updated: {datetime.now().strftime('%Y-%m-%d %H:%M UTC')}</p>
        </div>
        
        {create_plots_section('Static Visualizations', matplotlib_plots, 'matplotlib')}
        {create_plots_section('Interactive Visualizations', plotly_plots, 'plotly')}
        
        <div class="footer">
            <p>Backyard Ecology Project | Data-driven bird behavior analysis</p>
            <p>Generated from {len(plots)} plots</p>
        </div>
    </div>
</body>
</html>
"""
    
    # Write the HTML file
    with open(f"{output_dir}/index.html", 'w') as f:
        f.write(html_content)
    
    print(f"Dashboard created at {output_dir}/index.html")

def create_plots_section(title, plots, plot_type):
    """Create HTML section for a group of plots."""
    if not plots:
        return ""
    
    plots_html = ""
    for plot in plots:
        if plot_type == 'matplotlib':
            plots_html += create_matplotlib_plot_html(plot)
        elif plot_type == 'plotly':
            plots_html += create_plotly_plot_html(plot)
    
    return f"""
    <div class="plots-section">
        <h2 class="section-title">{title}</h2>
        <div class="plots-grid">
            {plots_html}
        </div>
    </div>
    """

def create_matplotlib_plot_html(plot):
    """Create HTML for a matplotlib plot."""
    return f"""
    <div class="plot-card">
        <div class="plot-header">
            <h3>{plot.get('title', 'Untitled Plot')}</h3>
            <p>{plot.get('description', '')}</p>
        </div>
        <div class="plot-content">
            <img src="{plot.get('image_path', '')}" alt="{plot.get('title', '')}" class="plot-image">
            <div class="plot-metadata">
                <strong>Type:</strong> Static Visualization<br>
                <strong>Created:</strong> {plot.get('created', 'Unknown')}<br>
                <strong>File:</strong> {plot.get('filename', 'Unknown')}
            </div>
        </div>
    </div>
    """

def create_plotly_plot_html(plot):
    """Create HTML for a plotly plot."""
    return f"""
    <div class="plot-card">
        <div class="plot-header">
            <h3>{plot.get('title', 'Untitled Plot')}</h3>
            <p>{plot.get('description', '')}</p>
        </div>
        <div class="plot-content">
            <iframe src="{plot.get('html_path', '')}" class="plot-iframe"></iframe>
            <div class="plot-metadata">
                <strong>Type:</strong> Interactive Visualization<br>
                <strong>Created:</strong> {plot.get('created', 'Unknown')}<br>
                <strong>File:</strong> {plot.get('filename', 'Unknown')}
            </div>
        </div>
    </div>
    """

def main():
    """Main function to generate dashboard."""
    print("Generating dashboard from saved plots...")
    
    # Set up paths
    dashboard_dir = '../docs/dashboard_plots'
    output_dir = '../docs'
    
    # Ensure output directory exists
    Path(output_dir).mkdir(exist_ok=True)
    
    # Load plot metadata
    plots = load_plot_metadata(dashboard_dir)
    
    if not plots:
        print("No plots found in dashboard directory. Run analytics.ipynb first!")
        return
    
    print(f"Found {len(plots)} plots:")
    for plot in plots:
        print(f"  - {plot.get('title', 'Untitled')} ({plot.get('type', 'unknown')})")
    
    # Create dashboard HTML
    create_dashboard_html(plots, output_dir)
    
    print(f"\n✅ Dashboard generated successfully!")
    print(f"📁 Dashboard location: {output_dir}/index.html")
    print(f"🌐 Open in browser: file://{os.path.abspath(output_dir)}/index.html")

if __name__ == "__main__":
    main()
