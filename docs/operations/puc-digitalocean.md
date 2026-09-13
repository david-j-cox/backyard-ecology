# PUC Data Refresh on DigitalOcean

The PUC data refresh is a persistent data job. It should run on a Linux VM with
local disk, not on GitHub Actions. GitHub remains the code host; the VM owns the
large working data files in `data/`.

## Droplet

Recommended starting point:

- Ubuntu 24.04 LTS
- 8 GB RAM / 4 vCPU / 160 GB SSD
- SSH-key login only
- DigitalOcean backups enabled

## Initial Setup

Run as `root` on the droplet:

```bash
apt-get update
apt-get install -y git python3.12 python3.12-venv python3-pip curl ca-certificates

adduser --system --group --no-create-home --home /opt/backyard-ecology backyard
mkdir -p /etc/backyard-ecology /opt/backyard-ecology
chown -R backyard:backyard /opt/backyard-ecology

sudo -u backyard git clone https://github.com/david-j-cox/backyard-ecology.git /opt/backyard-ecology
sudo -u backyard python3.12 -m venv /opt/backyard-ecology/.venv
sudo -u backyard /opt/backyard-ecology/.venv/bin/pip install --upgrade pip
sudo -u backyard /opt/backyard-ecology/.venv/bin/pip install -r /opt/backyard-ecology/requirements.txt
```

Create `/opt/backyard-ecology/.env` owned by `backyard:backyard`:

```bash
WEATHER_API_KEY=...
JAX_BIRDWX_API_KEY=...
ESSEX_BIRDWX_API_KEY=...
```

Create `/etc/backyard-ecology/puc-refresh.env`:

```bash
REPO_DIR=/opt/backyard-ecology
VENV_DIR=/opt/backyard-ecology/.venv
LOOKBACK_DAYS=45
LOG_DIR=/opt/backyard-ecology/logs
LOCK_FILE=/opt/backyard-ecology/.puc-refresh.lock
TZ=America/New_York

# Optional. Example:
# BACKUP_CMD=rclone sync /opt/backyard-ecology/data remote:backyard-ecology/data
BACKUP_CMD=
```

Install the timer:

```bash
chmod 0755 /opt/backyard-ecology/ops/run_puc_refresh.sh
cp /opt/backyard-ecology/ops/systemd/backyard-puc-refresh.service /etc/systemd/system/
cp /opt/backyard-ecology/ops/systemd/backyard-puc-refresh.timer /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now backyard-puc-refresh.timer
```

Check status:

```bash
systemctl list-timers backyard-puc-refresh.timer
systemctl status backyard-puc-refresh.service
journalctl -u backyard-puc-refresh.service -n 200 --no-pager
```

## One-Time Backfill

Copy the current production data files into `/opt/backyard-ecology/data/`
before the first backfill:

```bash
rsync -av data/county_level_birdweather.parquet data/backyard_ecology.duckdb data/study_site_puc_data.csv root@DROPLET_IP:/opt/backyard-ecology/data/
ssh root@DROPLET_IP 'chown backyard:backyard /opt/backyard-ecology/data/county_level_birdweather.parquet /opt/backyard-ecology/data/backyard_ecology.duckdb /opt/backyard-ecology/data/study_site_puc_data.csv'
```

Then run the missed-date backfill manually as the `backyard` user. Adjust dates
to the failure window being repaired.

```bash
sudo -u backyard bash -lc '
cd /opt/backyard-ecology
source .venv/bin/activate
python scripts_notebooks/birdweather_specific_pucs.py --from 2026-08-23 --to 2026-09-12 --lookback 45
python scripts_notebooks/birdweather.py --from 2026-08-23 --to 2026-09-12 --lookback 45
'
```

The scripts replace each station/day or county/day rather than appending blindly,
so the backfill is safe to rerun. Existing data is preserved when a fetch fails.

## GitHub Actions

`.github/workflows/puc-data-refresh.yml` is intentionally manual-only. Do not
re-add a schedule unless the large data files move back into an Actions-friendly
storage and runtime model.

For one-time station-only repairs that need existing GitHub Actions secrets,
use the manual `PUC Station Catch-up` workflow. It avoids the county-level
BirdWeather job and only runs `birdweather_specific_pucs.py` for the station and
date range supplied at dispatch time.
