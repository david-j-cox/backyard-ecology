#!/usr/bin/env python3
"""
BirdCast Data Scraper
Scrapes migration data from the BirdCast dashboard for multiple counties: Duval County FL, Boulder County CO, Essex County NJ, Contra Costa County CA, and Lee County AL
"""

from datetime import datetime
import sys
import os

# Add the scripts directory to Python path for imports
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import scraper_utils

# Set up logging
logger = scraper_utils.setup_logging('birdcast_scraper.log')

class BirdCastScraper:
    def __init__(self, urls=None):
        # Default regions: Duval County FL, Boulder County CO, Essex County NJ, Contra Costa County CA, Lee County AL
        if urls is None:
            urls = [
                "https://dashboard.birdcast.info/region/US-FL-031",  # Duval County, Florida
                "https://dashboard.birdcast.info/region/US-CO-013",  # Boulder County, Colorado
                "https://dashboard.birdcast.info/region/US-NJ-013",  # Essex County, New Jersey
                "https://dashboard.birdcast.info/region/US-CA-013",  # Contra Costa County, California
                "https://dashboard.birdcast.info/region/US-AL-081",  # Lee County, Alabama
            ]
        self.urls = urls if isinstance(urls, list) else [urls]
        self.session = scraper_utils.create_session()

    def scrape_data(self):
        """Scrape migration data from all configured BirdCast dashboard URLs"""
        return scraper_utils.scrape_data(self.session, self.urls, "BirdCast")

    def save_to_csv(self, data_list, filename=None):
        """Save data to CSV file"""
        if filename is None:
            filename = f"{scraper_utils.DATA_DIR}/birdcast_data.csv"
        scraper_utils.save_to_csv(data_list, filename)

    def save_to_parquet(self, data_list, filename=None):
        """Save data to Parquet file (append with deduplication)"""
        if filename is None:
            filename = f"{scraper_utils.DATA_DIR}/birdcast_data.parquet"
        scraper_utils.save_to_parquet(data_list, filename)

    def save_to_json(self, data_list, filename=None):
        """Save data to JSON file (append to list) - DEPRECATED: Use save_to_parquet instead"""
        if filename is None:
            filename = f"{scraper_utils.DATA_DIR}/birdcast_data.json"
        scraper_utils.save_to_json(data_list, filename)

def run_scraper():
    """Run the scraper and save data"""
    scraper = BirdCastScraper()
    data = scraper.scrape_data()

    if data:
        # Save to Parquet (primary format) and CSV (for compatibility)
        scraper.save_to_parquet(data)
        scraper.save_to_csv(data)
        scraper_utils.save_to_duckdb(data, "birdcast_data")

        # Print summary
        scraper_utils.print_scraper_summary(data, "BirdCast Data Scraper", "birdcast_data.parquet & birdcast_data.csv")
    else:
        print("BirdCast Data Scraper - FAILED")
        print("No data was collected. Check the logs for details.")
        logger.error("Scraping failed")

if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--test":
        print("Running test scrape...")
    run_scraper()
