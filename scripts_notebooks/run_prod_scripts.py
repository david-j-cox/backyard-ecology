#!/usr/bin/env python3
"""
Run production scripts in parallel.

This script orchestrates the execution of:
1. weather.py - Fetches weather data from OpenWeather API
2. merge_sites_data.py - Downloads and merges data from Google Sheets

Both scripts run in parallel to reduce total execution time.
"""

import logging
import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from typing import Dict, Tuple, Optional


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
    log_file = logs_dir / f'run_prod_scripts_{timestamp}.log'
    
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


def run_script(script_path: Path, script_name: str, script_dir: Path, logger: logging.Logger, python_executable: str) -> Tuple[str, bool, str]:
    """
    Run a Python script as a subprocess.
    
    Args:
        script_path: Full path to the script to run
        script_name: Name of the script for logging
        script_dir: Directory where scripts are located (working directory)
        logger: Logger instance
        python_executable: Python executable to use
        
    Returns:
        Tuple of (script_name, success: bool, output: str)
    """
    logger.info(f"Starting {script_name}...")
    start_time = datetime.now()
    
    try:
        # Run the script as a subprocess
        result = subprocess.run(
            [python_executable, str(script_path)],
            cwd=script_dir.parent,  # Run from project root
            capture_output=True,
            text=True,
            timeout=3600  # 1 hour timeout
        )
        
        elapsed = (datetime.now() - start_time).total_seconds()
        
        if result.returncode == 0:
            logger.info(f"{script_name} completed successfully in {elapsed:.1f} seconds")
            if result.stdout:
                logger.debug(f"{script_name} stdout:\n{result.stdout}")
            return (script_name, True, result.stdout)
        else:
            error_msg = f"{script_name} failed with return code {result.returncode}"
            logger.error(f"{error_msg}")
            if result.stderr:
                logger.error(f"{script_name} stderr:\n{result.stderr}")
            if result.stdout:
                logger.debug(f"{script_name} stdout:\n{result.stdout}")
            return (script_name, False, result.stderr or result.stdout)
            
    except subprocess.TimeoutExpired:
        elapsed = (datetime.now() - start_time).total_seconds()
        error_msg = f"{script_name} timed out after {elapsed:.1f} seconds"
        logger.error(f"✗ {error_msg}")
        return (script_name, False, error_msg)
        
    except Exception as e:
        elapsed = (datetime.now() - start_time).total_seconds()
        error_msg = f"Error running {script_name}: {e}"
        logger.error(f"{error_msg}")
        return (script_name, False, error_msg)


def get_python_executable() -> str:
    """
    Determine which Python executable to use.
    Checks for environment variable override, then tests current Python,
    falls back to system Python if venv is corrupted.
    """
    # Check for environment variable override
    python_override = os.environ.get('PYTHON_EXECUTABLE')
    if python_override:
        return python_override
    
    # Test current Python executable
    current_python = sys.executable
    
    # Quick test: try importing pandas (common dependency)
    try:
        import subprocess
        result = subprocess.run(
            [current_python, '-c', 'import pandas; print("OK")'],
            capture_output=True,
            timeout=5
        )
        if result.returncode == 0:
            return current_python
    except Exception:
        pass
    
    # Fallback to common system Python locations
    system_pythons = [
        '/opt/anaconda3/bin/python',
        '/usr/local/bin/python3',
        '/usr/bin/python3',
        'python3'  # Last resort - use PATH
    ]
    
    for python_path in system_pythons:
        try:
            result = subprocess.run(
                [python_path, '-c', 'import pandas; print("OK")'],
                capture_output=True,
                timeout=5
            )
            if result.returncode == 0:
                return python_path
        except Exception:
            continue
    
    # If all else fails, return current (will likely fail but at least we tried)
    return current_python


def main():
    """Main function to orchestrate parallel script execution."""
    # Get script directory for relative paths
    script_dir = Path(__file__).parent.resolve()
    
    # Set up logging
    log_file = setup_logging(script_dir)
    logger = logging.getLogger(__name__)
    
    try:
        logger.info("=" * 60)
        logger.info("Starting production scripts execution")
        logger.info("=" * 60)
        
        # Determine which Python to use
        python_executable = get_python_executable()
        logger.info(f"Using Python executable: {python_executable}")
        
        if python_executable != sys.executable:
            logger.info(f"  (Switched from {sys.executable} due to environment issues)")
        
        # Define scripts to run
        scripts = {
            'weather.py': script_dir / 'weather.py',
            'merge_sites_data.py': script_dir / 'merge_sites_data.py',
            # 'birdweather_specific_pucs.py': script_dir / 'birdweather_specific_pucs.py', 
            # 'birdweather.py': script_dir / 'birdweather.py'
        }
        
        # Verify scripts exist
        for name, path in scripts.items():
            if not path.exists():
                logger.error(f"Script not found: {path}")
                sys.exit(1)
        
        logger.info(f"Running {len(scripts)} scripts in parallel...")
        overall_start_time = datetime.now()
        
        # Run scripts in parallel using ThreadPoolExecutor
        # (I/O bound operations, so threading is appropriate)
        results: Dict[str, Tuple[str, bool, str]] = {}
        
        with ThreadPoolExecutor(max_workers=len(scripts)) as executor:
            # Submit all scripts
            future_to_script = {
                executor.submit(
                    run_script,
                    path,
                    name,
                    script_dir,
                    logger,
                    python_executable
                ): name
                for name, path in scripts.items()
            }
            
            # Collect results as they complete
            for future in as_completed(future_to_script):
                script_name = future_to_script[future]
                try:
                    result = future.result()
                    results[script_name] = result
                except Exception as e:
                    logger.error(f"Exception in {script_name}: {e}", exc_info=True)
                    results[script_name] = (script_name, False, str(e))
        
        # Summary
        overall_elapsed = (datetime.now() - overall_start_time).total_seconds()
        logger.info("=" * 60)
        logger.info("Execution Summary")
        logger.info("=" * 60)
        
        success_count = sum(1 for _, success, _ in results.values() if success)
        failure_count = len(results) - success_count
        
        for script_name, success, output in results.values():
            status = "SUCCESS" if success else "✗ FAILED"
            logger.info(f"{script_name}: {status}")
        
        logger.info(f"\nTotal execution time: {overall_elapsed:.1f} seconds")
        logger.info(f"Successful: {success_count}/{len(scripts)}")
        logger.info(f"Failed: {failure_count}/{len(scripts)}")
        
        # Exit with error code if any script failed
        if failure_count > 0:
            logger.error("One or more scripts failed. Check logs for details.")
            sys.exit(1)
        else:
            logger.info("All scripts completed successfully!")
            sys.exit(0)
            
    except KeyboardInterrupt:
        logger.warning("Execution interrupted by user")
        sys.exit(130)
    except Exception as e:
        logger.error(f"Unexpected error: {e}", exc_info=True)
        sys.exit(1)


if __name__ == '__main__':
    main()
