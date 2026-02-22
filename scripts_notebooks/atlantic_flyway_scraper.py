#!/usr/bin/env python3
"""
Atlantic Flyway BirdCast Data Scraper
Scrapes migration data from the BirdCast dashboard for all counties along the Atlantic Flyway corridor
"""

from datetime import datetime
import sys
import os

# Add the scripts directory to Python path for imports
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import scraper_utils

# Set up logging
logger = scraper_utils.setup_logging('atlantic_flyway_scraper.log')

class AtlanticFlywayBirdCastScraper:
    def __init__(self, urls=None):
        if urls is None:
            # Load URLs from the Atlantic Flyway corridor analysis
            urls = self.load_flyway_urls()
        self.urls = urls if isinstance(urls, list) else [urls]
        self.session = scraper_utils.create_session()
        logger.info(f"Initialized scraper with {len(self.urls)} Atlantic Flyway counties")

    def load_flyway_urls(self):
        """Load BirdCast URLs from the Atlantic Flyway corridor analysis CSV"""
        return scraper_utils.load_flyway_urls_from_csv('atlantic_flyway_corridor_counties_with_urls.csv')

    def scrape_data(self):
        """Scrape migration data from all Atlantic Flyway counties"""
        return scraper_utils.scrape_data(self.session, self.urls, "Atlantic Flyway")

    def save_to_parquet(self, data_list, filename=None):
        """Save data to Parquet file (append with deduplication)"""
        if filename is None:
            filename = f"{scraper_utils.DATA_DIR}/atlantic_flyway_corridor.parquet"
        scraper_utils.save_to_parquet(data_list, filename)

    def save_to_json(self, data_list, filename=None):
        """Save data to JSON file (append to list) - DEPRECATED: Use save_to_parquet instead"""
        if filename is None:
            filename = f"{scraper_utils.DATA_DIR}/atlantic_flyway_corridor.json"
        scraper_utils.save_to_json(data_list, filename)

def run_flyway_scraper():
    """Run the Atlantic Flyway scraper and save data"""
    scraper = AtlanticFlywayBirdCastScraper()
    data = scraper.scrape_data()

    if data:
        # Save to Parquet (primary format)
        scraper.save_to_parquet(data)

        # Print summary
        scraper_utils.print_scraper_summary(data, "Atlantic Flyway BirdCast Data Scraper", "atlantic_flyway_corridor.parquet")
    else:
        print("Atlantic Flyway BirdCast Data Scraper - FAILED")
        print("No data was collected. Check the logs for details.")
        logger.error("Atlantic Flyway scraping failed")

if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--test":
        print("Running test scrape of Atlantic Flyway counties...")
    run_flyway_scraper()
