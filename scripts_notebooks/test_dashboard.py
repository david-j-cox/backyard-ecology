#!/usr/bin/env python3
"""
Test script to run the complete dashboard workflow locally.
"""

import os
import subprocess
import sys
from pathlib import Path

def run_command(command, description):
    """Run a command and handle errors."""
    print(f"\n{description}...")
    try:
        result = subprocess.run(command, shell=True, check=True, capture_output=True, text=True)
        print(f"{description} completed successfully")
        if result.stdout:
            print(f"Output: {result.stdout}")
        return True
    except subprocess.CalledProcessError as e:
        print(f"{description} failed")
        print(f"Error: {e.stderr}")
        return False

def main():
    """Test the complete dashboard workflow."""
    print("Testing Backyard Ecology Dashboard Workflow")
    print("=" * 50)
    
    # Check if we're in the right directory
    if not os.path.exists('analytics.ipynb'):
        print("analytics.ipynb not found. Run this script from the scripts_notebooks directory.")
        return False
    
    # Step 1: Run the analytics notebook
    print("\nStep 1: Running analytics notebook...")
    if not run_command("jupyter nbconvert --to notebook --execute analytics.ipynb --output analytics_test.ipynb", 
                      "Execute analytics notebook"):
        return False
    
    # Step 2: Generate dashboard
    print("\nStep 2: Generating dashboard...")
    if not run_command("python generate_dashboard.py", 
                      "Generate dashboard HTML"):
        return False
    
    # Step 3: Check outputs
    print("\nStep 3: Checking outputs...")
    
    # Check if dashboard plots were created
    dashboard_dir = Path('../docs/dashboard_plots')
    if dashboard_dir.exists():
        plot_files = list(dashboard_dir.glob('*.json'))
        print(f"Found {len(plot_files)} plot metadata files")
        for plot_file in plot_files:
            print(f"   - {plot_file.name}")
    else:
        print("Dashboard plots directory not found")
        return False
    
    # Check if dashboard HTML was created
    dashboard_html = Path('../docs/index.html')
    if dashboard_html.exists():
        print(f"Dashboard HTML created: {dashboard_html}")
        print(f"   Size: {dashboard_html.stat().st_size} bytes")
    else:
        print("Dashboard HTML not found")
        return False
    
    # Step 4: Open dashboard (optional)
    print("\nDashboard workflow completed successfully!")
    print(f"\nDashboard files:")
    print(f"   - HTML: {dashboard_html.absolute()}")
    print(f"   - Plots: {dashboard_dir.absolute()}")
    
    print(f"\nTo view the dashboard:")
    print(f"   Open: file://{dashboard_html.absolute()}")
    
    return True

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
