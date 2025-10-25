#!/usr/bin/env python3
"""
Daily update script - run this every morning to update your dashboard.
"""

import subprocess
import sys
import os
from pathlib import Path

def run_command(command, description):
    """Run a command and handle errors."""
    print(f"{description}...")
    try:
        result = subprocess.run(command, shell=True, check=True, capture_output=True, text=True)
        print(f"{description} completed")
        return True
    except subprocess.CalledProcessError as e:
        print(f"{description} failed: {e.stderr}")
        return False

def main():
    """Run the daily update workflow."""
    print("Daily Backyard Ecology Dashboard Update")
    print("=" * 50)
    
    # Step 1: Run your analytics notebook
    print("\nStep 1: Running analytics notebook...")
    if not run_command("jupyter nbconvert --to notebook --execute analytics.ipynb --output analytics_executed.ipynb", 
                      "Execute analytics notebook"):
        print("Failed to run notebook. Check for errors above.")
        return False
    
    # Step 2: Generate simple dashboard
    print("\nStep 2: Generating dashboard...")
    if not run_command("python simple_dashboard.py", 
                      "Generate dashboard HTML"):
        print("Failed to generate dashboard. Check for errors above.")
        return False
    
    # Step 3: Check if docs folder has content
    docs_dir = Path('../docs')
    if not docs_dir.exists():
        print("Docs directory not found")
        return False
    
    # Count files in docs
    plot_files = list(docs_dir.glob('dashboard_plots/*.json'))
    html_file = docs_dir / 'index.html'
    
    print(f"\nDashboard contents:")
    print(f"   - HTML file: {'Found' if html_file.exists() else 'Missing'}")
    print(f"   - Plot files: {len(plot_files)}")
    
    if html_file.exists() and plot_files:
        print(f"\nDashboard updated successfully!")
        print(f"\nNext steps:")
        print(f"   1. Review the dashboard: file://{html_file.absolute()}")
        print(f"   2. Commit and push to GitHub:")
        print(f"      git add docs/")
        print(f"      git commit -m 'Update dashboard - {subprocess.run('date', capture_output=True, text=True).stdout.strip()}'")
        print(f"      git push origin main")
        print(f"   3. Your dashboard will be live at: https://yourusername.github.io/backyard-ecology/")
        return True
    else:
        print("Dashboard generation failed")
        return False

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
