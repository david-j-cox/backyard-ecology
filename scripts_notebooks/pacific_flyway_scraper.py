#!/usr/bin/env python3
"""
Pacific Flyway BirdCast Data Scraper
Scrapes migration data from the BirdCast dashboard for all counties along the Pacific Flyway corridor
"""

from datetime import datetime
import sys
import os

# Add the scripts directory to Python path for imports
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import scraper_utils

# Set up logging
logger = scraper_utils.setup_logging('pacific_flyway_scraper.log')

class PacificFlywayBirdCastScraper:
    def __init__(self, urls=None):
        if urls is None:
            # Load URLs from the Pacific Flyway corridor analysis
            urls = self.load_flyway_urls()
        self.urls = urls if isinstance(urls, list) else [urls]
        self.session = scraper_utils.create_session()
        logger.info(f"Initialized scraper with {len(self.urls)} Pacific Flyway counties")

    def load_flyway_urls(self):
        """Load BirdCast URLs from the Pacific Flyway corridor analysis CSV"""
        return scraper_utils.load_flyway_urls_from_csv('pacific_flyway_corridor_counties_with_urls.csv')

    def scrape_data(self):
        """Scrape migration data from all Pacific Flyway counties"""
        return scraper_utils.scrape_data(self.session, self.urls, "Pacific Flyway")

    def save_to_parquet(self, data_list, filename=None):
        """Save data to Parquet file (append with deduplication)"""
        if filename is None:
            filename = f"{scraper_utils.DATA_DIR}/pacific_flyway_corridor.parquet"
        scraper_utils.save_to_parquet(data_list, filename)

    def save_to_json(self, data_list, filename=None):
        """Save data to JSON file (append to list) - DEPRECATED: Use save_to_parquet instead"""
        if filename is None:
            filename = f"{scraper_utils.DATA_DIR}/pacific_flyway_corridor.json"
        scraper_utils.save_to_json(data_list, filename)

def run_flyway_scraper():
    """Run the Pacific Flyway scraper and save data"""
    scraper = PacificFlywayBirdCastScraper()
    data = scraper.scrape_data()

    if data:
        # Save to Parquet (primary format)
        scraper.save_to_parquet(data)

        # Print summary
        scraper_utils.print_scraper_summary(data, "Pacific Flyway BirdCast Data Scraper", "pacific_flyway_corridor.parquet")
    else:
        print("Pacific Flyway BirdCast Data Scraper - FAILED")
        print("No data was collected. Check the logs for details.")
        logger.error("Pacific Flyway scraping failed")

if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--test":
        print("Running test scrape of Pacific Flyway counties...")
    run_flyway_scraper()
