"""Append score rows (JSON list of dicts on stdin) to scores/scores_DATE.csv, skipping clips already present."""
import csv, json, os, sys
COLS = ["file","individual","species","sex_if_known","left_pecks","right_pecks","peck_range","confidence",
        "peck_times_s","left_time_s","right_time_s","guessed_time_s","time_censored","time_note","seed_check",
        "notes","birdfy_label"]
path = sys.argv[1]
rows = json.load(sys.stdin)
done = set()
if os.path.exists(path):
    with open(path, newline="") as f:
        done = {r["file"] for r in csv.DictReader(f)}
new = not os.path.exists(path)
with open(path, "a", newline="") as f:
    w = csv.DictWriter(f, fieldnames=COLS)
    if new: w.writeheader()
    for r in rows:
        if r["file"] in done:
            print("skip (already scored)", r["file"]); continue
        bad = set(r) - set(COLS)
        if bad: raise SystemExit(f"unknown cols {bad}")
        w.writerow({c: r.get(c, "") for c in COLS})
        print("wrote", r["file"], r.get("individual"))
