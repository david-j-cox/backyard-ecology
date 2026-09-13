#!/usr/bin/env bash
set -euo pipefail

REPO_DIR="${REPO_DIR:-/opt/backyard-ecology}"
VENV_DIR="${VENV_DIR:-$REPO_DIR/.venv}"
LOCK_FILE="${LOCK_FILE:-$REPO_DIR/.puc-refresh.lock}"
LOG_DIR="${LOG_DIR:-$REPO_DIR/logs}"
LOOKBACK_DAYS="${LOOKBACK_DAYS:-45}"
TZ="${TZ:-America/New_York}"
PYTHON="${PYTHON:-$VENV_DIR/bin/python}"
PIP="${PIP:-$VENV_DIR/bin/pip}"
BACKUP_CMD="${BACKUP_CMD:-}"
export TZ

mkdir -p "$LOG_DIR"

run_date="$(date -u +%Y%m%dT%H%M%SZ)"
log_file="$LOG_DIR/puc_vm_refresh_${run_date}.log"

exec 9>"$LOCK_FILE"
if ! flock -n 9; then
  echo "Another PUC refresh is already running; exiting." | tee -a "$log_file"
  exit 0
fi

{
  echo "[$(date -Is)] Starting PUC refresh"
  echo "Repository: $REPO_DIR"
  echo "Lookback days: $LOOKBACK_DAYS"

  cd "$REPO_DIR"

  if [ ! -x "$PYTHON" ]; then
    python3 -m venv "$VENV_DIR"
  fi

  if [ -d .git ]; then
    git fetch origin main
    git checkout main
    git pull --ff-only origin main
  fi

  "$PIP" install -r requirements.txt

  from_date="$("$PYTHON" - <<PY
from datetime import date, timedelta
print((date.today() - timedelta(days=int("$LOOKBACK_DAYS"))).isoformat())
PY
)"
  to_date="$(date +%F)"

  echo "Nightly window: $from_date to $to_date"

  "$PYTHON" scripts_notebooks/birdweather_specific_pucs.py \
    --from "$from_date" \
    --to "$to_date" \
    --lookback "$LOOKBACK_DAYS"

  "$PYTHON" scripts_notebooks/birdweather.py \
    --from "$from_date" \
    --to "$to_date" \
    --lookback "$LOOKBACK_DAYS"

  if [ -n "$BACKUP_CMD" ]; then
    echo "Running backup command"
    bash -lc "$BACKUP_CMD"
  else
    echo "BACKUP_CMD is not set; skipping external backup sync"
  fi

  echo "[$(date -Is)] PUC refresh completed"
} 2>&1 | tee -a "$log_file"
