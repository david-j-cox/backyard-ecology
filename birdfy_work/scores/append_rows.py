"""Append scored rows (JSON list of dicts on stdin) to scores/scores_2026-11-05.csv; skip if clip present."""
import csv, json, sys, os
COLS = ["file","individual","species","sex_if_known","left_pecks","right_pecks","peck_range","confidence",
        "peck_times_s","left_time_s","right_time_s","guessed_time_s","time_censored","time_note","seed_check","notes","birdfy_label"]
out = sys.argv[1]
rows = json.load(sys.stdin)
labels = {}
with open(os.path.join(os.path.dirname(out), "..", "manifest.csv"), newline="") as f:
    for r in csv.DictReader(f):
        labels[r["file"]] = r["birdfy_label"]
done = set()
if os.path.exists(out):
    with open(out, newline="") as f:
        done = {r["file"] for r in csv.DictReader(f)}
new = not os.path.exists(out)
with open(out, "a", newline="") as f:
    w = csv.DictWriter(f, fieldnames=COLS)
    if new: w.writeheader()
    for r in rows:
        if r["file"] in done:
            print("skip", r["file"]); continue
        r.setdefault("birdfy_label", labels.get(r["file"], ""))
        for c in COLS: r.setdefault(c, "")
        w.writerow(r)
    print("wrote", len(rows))
