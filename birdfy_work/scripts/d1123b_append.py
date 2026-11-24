"""usage: python3 -I d1123b_append.py OUT.csv < rows.json   (JSON list of dicts)
Appends rows with csv module; writes header if file is new; skips a clip whose file already has rows."""
import csv, json, os, sys
COLS = ["file","individual","species","sex_if_known","left_pecks","right_pecks","peck_range","confidence",
        "peck_times_s","left_time_s","right_time_s","guessed_time_s","time_censored","time_note","seed_check","notes","birdfy_label"]
out = sys.argv[1]
rows = json.load(sys.stdin)
have = set()
if os.path.exists(out):
    with open(out, newline="") as f:
        have = {r["file"] for r in csv.DictReader(f)}
new = not os.path.exists(out) or os.path.getsize(out) == 0
files = {r["file"] for r in rows}
if files & have:
    sys.exit(f"skip: already has rows for {sorted(files & have)}")
with open(out, "a", newline="") as f:
    w = csv.DictWriter(f, fieldnames=COLS)
    if new: w.writeheader()
    for r in rows:
        bad = set(r) - set(COLS)
        if bad: sys.exit(f"unknown cols {bad}")
        w.writerow({c: r.get(c, "") for c in COLS})
print(f"appended {len(rows)} rows for {sorted(files)}")
