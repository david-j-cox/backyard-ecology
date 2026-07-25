#!/usr/bin/env python3
"""
Standalone PUC data refresh.

Runs the two BirdWeather PUC fetch scripts in parallel:
  1. birdweather_specific_pucs.py - Study site PUC data (30-day lookback)
  2. birdweather.py - County-level BirdWeather data (30-day lookback)

Designed to run on its own schedule (e.g. 1 AM ET) so the heavier
completeness-check work is separated from the dashboard update pipeline.
"""

import logging
import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from typing import Dict, Optional, Tuple

# Per-script wall-clock budget. The scripts normally finish in ~15 minutes; a
# much longer run means the BirdWeather API is degraded and retry backoffs are
# grinding, so fail fast rather than burning a full CI job.
SCRIPT_TIMEOUT_SECS = int(os.environ.get('PUC_SCRIPT_TIMEOUT', '3600'))

# How much of a timed-out script's captured output to surface in the log.
OUTPUT_TAIL_CHARS = 4000


def setup_logging(script_dir: Path) -> Path:
    """Set up logging to both file and console."""
    logs_dir = script_dir.parent / 'logs'
    logs_dir.mkdir(exist_ok=True)

    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    log_file = logs_dir / f'puc_data_refresh_{timestamp}.log'

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


def tail(stream: Optional[object]) -> str:
    """Last OUTPUT_TAIL_CHARS of a captured stream, decoded if needed."""
    if not stream:
        return ''
    if isinstance(stream, bytes):
        stream = stream.decode('utf-8', errors='replace')
    return stream[-OUTPUT_TAIL_CHARS:]


def run_script(
    script_path: Path, script_name: str, script_dir: Path,
    logger: logging.Logger, python_executable: str
) -> Tuple[str, bool, str]:
    """Run a Python script as a subprocess."""
    logger.info(f"Starting {script_name}...")
    start_time = datetime.now()

    try:
        result = subprocess.run(
            [python_executable, str(script_path)],
            cwd=script_dir.parent,
            capture_output=True,
            text=True,
            timeout=SCRIPT_TIMEOUT_SECS
        )

        elapsed = (datetime.now() - start_time).total_seconds()

        if result.returncode == 0:
            logger.info(f"{script_name} completed successfully in {elapsed:.1f}s")
            if result.stdout:
                logger.debug(f"{script_name} stdout:\n{result.stdout}")
            return (script_name, True, result.stdout)
        else:
            logger.error(f"{script_name} failed (rc={result.returncode})")
            if result.stderr:
                logger.error(f"{script_name} stderr:\n{result.stderr}")
            if result.stdout:
                logger.error(f"{script_name} stdout (tail):\n{tail(result.stdout)}")
            return (script_name, False, result.stderr or result.stdout)

    except subprocess.TimeoutExpired as e:
        elapsed = (datetime.now() - start_time).total_seconds()
        msg = f"{script_name} timed out after {elapsed:.1f}s"
        logger.error(msg)

        # subprocess.run kills the child and collects whatever it had written
        # before re-raising. Surface it -- without this the log shows nothing
        # but silence and there is no way to tell how far the script got.
        partial_out = tail(e.stdout)
        partial_err = tail(e.stderr)
        if partial_out:
            logger.error(f"{script_name} stdout before timeout (tail):\n{partial_out}")
        if partial_err:
            logger.error(f"{script_name} stderr before timeout (tail):\n{partial_err}")
        if not partial_out and not partial_err:
            logger.error(f"{script_name} produced no output before timing out")

        return (script_name, False, msg)

    except Exception as e:
        msg = f"Error running {script_name}: {e}"
        logger.error(msg)
        return (script_name, False, msg)


def main():
    script_dir = Path(__file__).parent.resolve()
    log_file = setup_logging(script_dir)
    logger = logging.getLogger(__name__)

    puc_scripts = {
        'birdweather_specific_pucs.py': script_dir / 'birdweather_specific_pucs.py',
        'birdweather.py': script_dir / 'birdweather.py',
    }

    # Verify scripts exist
    for name, path in puc_scripts.items():
        if not path.exists():
            logger.error(f"Script not found: {path}")
            sys.exit(1)

    # Pre-check DuckDB
    db_path = script_dir.parent / "data" / "backyard_ecology.duckdb"
    if not db_path.exists():
        logger.warning(
            f"DuckDB file not found at {db_path}. "
            "DuckDB dual-writes will create it fresh."
        )

    python_executable = sys.executable
    logger.info(f"Using Python: {python_executable}")

    logger.info("=" * 60)
    logger.info("Starting PUC data refresh")
    logger.info("=" * 60)

    overall_start = datetime.now()
    results: Dict[str, Tuple[str, bool, str]] = {}

    with ThreadPoolExecutor(max_workers=len(puc_scripts)) as executor:
        future_to_script = {
            executor.submit(
                run_script, path, name, script_dir, logger, python_executable
            ): name
            for name, path in puc_scripts.items()
        }

        for future in as_completed(future_to_script):
            script_name = future_to_script[future]
            try:
                results[script_name] = future.result()
            except Exception as e:
                logger.error(f"Exception in {script_name}: {e}", exc_info=True)
                results[script_name] = (script_name, False, str(e))

    # Summary
    elapsed = (datetime.now() - overall_start).total_seconds()
    logger.info("=" * 60)
    logger.info("PUC Data Refresh Summary")
    logger.info("=" * 60)

    success_count = sum(1 for _, ok, _ in results.values() if ok)
    failure_count = len(results) - success_count

    for script_name, ok, _ in results.values():
        logger.info(f"  {script_name}: {'SUCCESS' if ok else 'FAILED'}")

    logger.info(f"Total time: {elapsed:.1f}s")
    logger.info(f"Successful: {success_count}/{len(puc_scripts)}")
    logger.info(f"Failed: {failure_count}/{len(puc_scripts)}")

    if failure_count > 0:
        logger.error("One or more PUC scripts failed.")
        sys.exit(1)
    else:
        logger.info("PUC data refresh completed successfully.")
        sys.exit(0)


if __name__ == '__main__':
    main()
