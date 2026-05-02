#!/usr/bin/env python3
"""
Merge sites data from Google Sheets Excel export.

This script downloads the latest Excel file from Google Sheets, then processes
and merges data from multiple sheets into consolidated CSV files.

Outputs:
- data/phase_change_data.csv
- data/raw_data_all_locations.csv
- data/daily_summaries_all_locations.csv
"""

import logging
import sys
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd
import requests
from dotenv import load_dotenv

# Set pandas display options
pd.set_option('display.max_columns', None)

# Google Sheets URL
GOOGLE_SHEETS_URL = "https://docs.google.com/spreadsheets/d/1n3R-RCKLKrk5cxk1zamKZg0GSu4fRbroY5VAnf9tpbk/export?format=xlsx"


def setup_logging(script_dir: Path) -> Path:
    """
    Set up logging to both file and console.
    
    Args:
        script_dir: Directory where the script is located
        
    Returns:
        Path to the log file
    """
    # Create logs directory if it doesn't exist
    logs_dir = script_dir.parent / 'logs'
    logs_dir.mkdir(exist_ok=True)
    
    # Create log file with timestamp
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    log_file = logs_dir / f'merge_sites_data_{timestamp}.log'
    
    # Configure logging
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S',
        handlers=[
            logging.FileHandler(log_file),
            logging.StreamHandler(sys.stdout)
        ]
    )
    
    logger = logging.getLogger(__name__)
    logger.info(f"Logging initialized. Log file: {log_file}")
    
    return log_file


def download_excel_file(google_sheets_url: str, output_path: Path, logger: logging.Logger) -> None:
    """
    Download Excel file from Google Sheets.
    
    Args:
        google_sheets_url: URL to download the Excel file from
        output_path: Path where the file should be saved
        logger: Logger instance
        
    Raises:
        requests.exceptions.HTTPError: If download fails
        ValueError: If received HTML instead of Excel file
        PermissionError: If access is denied
    """
    # Ensure the directory exists
    output_path.parent.mkdir(parents=True, exist_ok=True)
    
    logger.info(f"Downloading Excel file from Google Sheets...")
    logger.debug(f"URL: {google_sheets_url}")
    logger.debug(f"Output path: {output_path}")
    
    try:
        response = requests.get(google_sheets_url, timeout=30)
        response.raise_for_status()
        
        # Check if we got HTML instead of Excel (common when permissions are wrong)
        content_type = response.headers.get('content-type', '')
        if content_type.startswith('text/html'):
            error_msg = (
                "Received HTML instead of Excel file. This usually means:\n"
                "1. The sheet is not shared with 'Anyone with the link', OR\n"
                "2. The sheet needs to be published to the web (File > Share > Publish to web)\n"
                "Please check the sharing settings."
            )
            logger.error(error_msg)
            raise ValueError(error_msg)
        
        # Save to file
        with open(output_path, 'wb') as f:
            f.write(response.content)
        
        file_size = output_path.stat().st_size
        logger.info(f"File successfully downloaded and saved to {output_path} ({file_size:,} bytes)")
        
    except requests.exceptions.HTTPError as e:
        if e.response.status_code == 403:
            error_msg = (
                f"Access denied (403). Please ensure the Google Sheet is shared with 'Anyone with the link'.\n"
                f"Current URL: {google_sheets_url}"
            )
            logger.error(error_msg)
            raise PermissionError(error_msg) from e
        else:
            logger.error(f"HTTP error downloading file: {e}")
            raise
    except requests.exceptions.RequestException as e:
        logger.error(f"Error downloading file: {e}")
        raise
    except Exception as e:
        logger.error(f"Unexpected error downloading file: {e}")
        raise


def process_phase_changes(excel_file: pd.ExcelFile, output_dir: Path, logger: logging.Logger) -> None:
    """Process and save phase change data."""
    logger.info("Processing phase change data...")
    
    phase_change_data = pd.read_excel(excel_file, sheet_name='PhaseChanges')
    output_path = output_dir / 'phase_change_data.csv'
    phase_change_data.to_csv(output_path, index=False)
    
    logger.info(f"Phase change data saved: {phase_change_data.shape}")


def merge_jacksonville_data(gsheet_df: pd.DataFrame, multi_site_df: pd.DataFrame, sheet_name: str, logger: logging.Logger) -> pd.DataFrame:
    """
    Merge data from multi_site_data.xlsx into Google Sheet data for Jacksonville tabs.
    
    Args:
        gsheet_df: DataFrame from downloaded Google Sheet
        multi_site_df: DataFrame from multi_site_data.xlsx
        sheet_name: Name of the sheet being processed
        logger: Logger instance
        
    Returns:
        Merged DataFrame
    """
    logger.info(f"Merging data for {sheet_name}...")
    logger.debug(f"  Google Sheet rows: {len(gsheet_df)}")
    logger.debug(f"  Multi-site data rows: {len(multi_site_df)}")
    
    # Concatenate the dataframes
    merged_df = pd.concat([gsheet_df, multi_site_df], ignore_index=True)
    
    # Remove duplicates if any (based on key columns)
    # This assumes Date, Bird, Time are unique identifiers
    key_columns = ['Date', 'Bird', 'Time'] if 'Time' in merged_df.columns else ['Date', 'Bird']
    if key_columns:
        before_dedup = len(merged_df)
        merged_df = merged_df.drop_duplicates(subset=key_columns, keep='first')
        after_dedup = len(merged_df)
        if before_dedup != after_dedup:
            logger.info(f"  Removed {before_dedup - after_dedup} duplicate rows")
    
    logger.info(f"  Merged total rows: {len(merged_df)}")
    return merged_df


def process_raw_data(excel_file: pd.ExcelFile, raw_data_sheets: list, multi_site_excel: pd.ExcelFile, output_dir: Path, logger: logging.Logger) -> None:
    """Process and merge raw data from multiple sheets."""
    logger.info(f"Processing {len(raw_data_sheets)} raw data sheets...")
    
    raw_data_frames = []
    for sheet_name in raw_data_sheets:
        df = pd.read_excel(excel_file, sheet_name=sheet_name)
        df['source_sheet'] = sheet_name.lower().replace(" raw data", "").replace(" ", "_").replace(",", "")
        
        # Check if this is a Jacksonville sheet and if we have matching data in multi_site_data.xlsx
        if "jacksonville" in sheet_name.lower() and multi_site_excel is not None:
            multi_site_sheets = multi_site_excel.sheet_names
            # Find matching sheet in multi_site_data.xlsx (case-insensitive)
            matching_sheet = None
            for ms_sheet in multi_site_sheets:
                if "jacksonville" in ms_sheet.lower() and "raw" in ms_sheet.lower():
                    matching_sheet = ms_sheet
                    break
            
            if matching_sheet:
                logger.info(f"Found matching Jacksonville raw data sheet in multi_site_data.xlsx: {matching_sheet}")
                multi_site_df = pd.read_excel(multi_site_excel, sheet_name=matching_sheet)
                # Ensure source_sheet column matches
                multi_site_df['source_sheet'] = sheet_name.lower().replace(" raw data", "").replace(" ", "_").replace(",", "")
                # Merge the data
                df = merge_jacksonville_data(df, multi_site_df, sheet_name, logger)
            else:
                logger.debug(f"No matching Jacksonville raw data sheet found in multi_site_data.xlsx for {sheet_name}")
        
        raw_data_frames.append(df)
        logger.debug(f"  {sheet_name}: {len(df)} rows")
    
    raw_data = pd.concat(raw_data_frames, ignore_index=True)
    raw_data = raw_data[['Date', 'Bird', 'Time', 'LeftPecks', 'RightPecks', 'LeftSeed', 'RightSeed', 'source_sheet', 'Notes', 'CoolDown']]
    
    output_path = output_dir / 'raw_data_all_locations.csv'
    raw_data.to_csv(output_path, index=False)
    
    logger.info(f"Raw data saved: {raw_data.shape}")


def process_daily_summaries(excel_file: pd.ExcelFile, daily_summaries_sheets: list, multi_site_excel: pd.ExcelFile, output_dir: Path, logger: logging.Logger) -> None:
    """Process and merge daily summaries from multiple sheets."""
    logger.info(f"Processing {len(daily_summaries_sheets)} daily summary sheets...")
    
    daily_summaries_frames = []
    for sheet_name in daily_summaries_sheets:
        logger.debug(f"Processing sheet: {sheet_name}")
        df = pd.read_excel(excel_file, sheet_name=sheet_name)
        df['source_sheet'] = sheet_name
        
        # Check if this is a Jacksonville sheet and if we have matching data in multi_site_data.xlsx
        if "jacksonville" in sheet_name.lower() and multi_site_excel is not None:
            multi_site_sheets = multi_site_excel.sheet_names
            # Find matching sheet in multi_site_data.xlsx (case-insensitive)
            matching_sheet = None
            for ms_sheet in multi_site_sheets:
                if "jacksonville" in ms_sheet.lower() and "daily" in ms_sheet.lower():
                    matching_sheet = ms_sheet
                    break
            
            if matching_sheet:
                logger.info(f"Found matching Jacksonville daily summary sheet in multi_site_data.xlsx: {matching_sheet}")
                multi_site_df = pd.read_excel(multi_site_excel, sheet_name=matching_sheet)
                # Ensure source_sheet column matches
                multi_site_df['source_sheet'] = sheet_name
                # Merge the data
                df = merge_jacksonville_data(df, multi_site_df, sheet_name, logger)
            else:
                logger.debug(f"No matching Jacksonville daily summary sheet found in multi_site_data.xlsx for {sheet_name}")
        
        # Handle Auburn sheet - wide format with Phase column
        if "auburn" in sheet_name.lower() and "daily" in sheet_name.lower():
            # Drop Phase column if it exists
            if 'Phase' in df.columns:
                df = df.drop(columns=['Phase'])
            
            # Identify bird columns (exclude Date, Day, All birds, source_sheet)
            bird_columns = [col for col in df.columns if col not in ['Date', 'Day', 'All birds', 'source_sheet']]
            
            # Melt from wide to long format
            df_melted = df.melt(id_vars=['Date', 'source_sheet'], 
                            value_vars=bird_columns, 
                            var_name='Bird', 
                            value_name='Feeder Visits')
            
            # Drop rows where bird count is 0
            df_melted = df_melted[df_melted['Feeder Visits'] != 0].reset_index(drop=True)
            
            # Remove any rows with 'Grand Total' or other non-date values
            df_melted = df_melted[df_melted['Date'] != 'Grand Total'].reset_index(drop=True)
            
            df = df_melted.copy()
        
        elif "south" in sheet_name.lower():
            bird_columns = [col for col in df.columns if col not in ['Date', 'source_sheet', 'Feeder Visits', 'Total Visits', 'Total']]
            df_melted = df.melt(id_vars=['Date', 'source_sheet'], 
                            value_vars=bird_columns, 
                            var_name='Bird', 
                            value_name='Visits')
            df_melted.rename(columns={'Visits': 'Feeder Visits'}, inplace=True)
            df_melted = df_melted[df_melted['Date'] != 'Grand Total'].reset_index(drop=True)
            df = df_melted.copy()
        
        daily_summaries_frames.append(df)
        logger.debug(f"  {sheet_name}: {len(df)} rows after processing")
    
    daily_sums = pd.concat(daily_summaries_frames, ignore_index=True)
    daily_sums = daily_sums[['Date', 'source_sheet', 'Bird', 'Feeder Visits']]
    
    output_path = output_dir / 'daily_summaries_all_locations.csv'
    daily_sums.to_csv(output_path, index=False)
    
    logger.info(f"Daily summaries saved: {daily_sums.shape}")


def main():
    """Main function to orchestrate the data merging process."""
    # Get script directory for relative paths
    script_dir = Path(__file__).parent.resolve()
    output_dir = script_dir.parent / 'data'
    excel_file_path = output_dir / 'raw_data_from_gsheet' / 'RawData.xlsx'
    
    # Set up logging
    log_file = setup_logging(script_dir)
    logger = logging.getLogger(__name__)
    
    try:
        logger.info("Starting data merging process")
        
        # Load environment variables
        load_dotenv()
        
        # Download Excel file from Google Sheets
        download_excel_file(GOOGLE_SHEETS_URL, excel_file_path, logger)
        
        # Load Excel file
        logger.info(f"Loading Excel file: {excel_file_path}")
        excel_file = pd.ExcelFile(excel_file_path)
        all_sheet_names = excel_file.sheet_names
        logger.info(f"Found {len(all_sheet_names)} sheets: {', '.join(all_sheet_names)}")
        
        # Load multi_site_data.xlsx if it exists
        multi_site_file_path = output_dir / 'multi_site_data.xlsx'
        multi_site_excel = None
        if multi_site_file_path.exists():
            logger.info(f"Loading multi_site_data.xlsx from {multi_site_file_path}")
            multi_site_excel = pd.ExcelFile(multi_site_file_path)
            multi_site_sheet_names = multi_site_excel.sheet_names
            logger.info(f"Found {len(multi_site_sheet_names)} sheets in multi_site_data.xlsx: {', '.join(multi_site_sheet_names)}")
        else:
            logger.warning(f"multi_site_data.xlsx not found at {multi_site_file_path}. Skipping merge step.")
        
        # Identify sheet types
        raw_data_sheets = [sheet for sheet in all_sheet_names if 'raw' in sheet.lower()]
        daily_summaries_sheets = [sheet for sheet in all_sheet_names if 'daily' in sheet.lower()]
        
        logger.info(f"Raw data sheets: {len(raw_data_sheets)}")
        logger.info(f"Daily summary sheets: {len(daily_summaries_sheets)}")
        
        # Process each data type
        process_phase_changes(excel_file, output_dir, logger)
        process_raw_data(excel_file, raw_data_sheets, multi_site_excel, output_dir, logger)
        process_daily_summaries(excel_file, daily_summaries_sheets, multi_site_excel, output_dir, logger)
        
        # Dual-write: load CSVs into DuckDB
        write_to_duckdb(output_dir, logger)

        logger.info("Data merging process completed successfully")

    except Exception as e:
        logger.error(f"Error processing data: {e}", exc_info=True)
        sys.exit(1)


def write_to_duckdb(output_dir: Path, logger: logging.Logger) -> None:
    """
    Bulk-load the just-written CSVs into DuckDB (INSERT OR REPLACE).
    Wrapped in try/except so CSV path still works if DuckDB fails.
    """
    try:
        from db import get_connection, init_schema

        with get_connection() as con:
            init_schema(con)

            mappings = [
                ("phase_change_data.csv", "phase_changes"),
                ("raw_data_all_locations.csv", "raw_data"),
                ("daily_summaries_all_locations.csv", "daily_summaries"),
            ]

            for filename, table_name in mappings:
                csv_path = output_dir / filename
                if not csv_path.exists():
                    logger.warning(f"[DuckDB] {filename} not found, skipping")
                    continue

                df = pd.read_csv(csv_path, dtype=str)
                df = df.where(df.notna(), None)
                if df.empty:
                    continue

                # Drop rows missing any PK column. The Google Sheets carry
                # placeholder days with no bird visits (Bird/Time blank) that
                # violate the PK NOT NULL constraint and would roll back the
                # whole transaction otherwise.
                pk_cols = [
                    row[0] for row in con.execute(
                        "SELECT column_name FROM information_schema.key_column_usage "
                        "WHERE table_name = ?",
                        [table_name],
                    ).fetchall()
                ]
                pk_cols = [c for c in pk_cols if c in df.columns]
                if pk_cols:
                    before = len(df)
                    df = df.dropna(subset=pk_cols)
                    dropped = before - len(df)
                    if dropped:
                        logger.info(f"[DuckDB] {table_name}: dropped {dropped} rows missing PK columns")
                if df.empty:
                    continue

                con.execute(f'INSERT OR REPLACE INTO {table_name} SELECT * FROM df')
                count = con.execute(f"SELECT COUNT(*) FROM {table_name}").fetchone()[0]
                logger.info(f"[DuckDB] {table_name}: {count:,} total rows")

    except Exception as e:
        logger.warning(f"[DuckDB WARNING] Failed to write merge data to DuckDB: {e}")


if __name__ == '__main__':
    main()
