"""Append rows (JSON list of dicts) to scores/scores_2026-11-13.csv, skipping clips already present.
usage: d1113_append.py ROWS.json"""
import csv, json, os, sys
COLS = ["file","individual","species","sex_if_known","left_pecks","right_pecks","peck_range","confidence",
        "peck_times_s","left_time_s","right_time_s","guessed_time_s","time_censored","time_note","seed_check",
        "notes","birdfy_label"]
here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
out = os.path.join(here, "scores", "scores_2026-11-13.csv")
man = {r["file"]: r["birdfy_label"] for r in csv.DictReader(open(os.path.join(here, "manifest.csv")))}
rows = json.load(open(sys.argv[1]))
done = set()
if os.path.exists(out):
    done = {r["file"] for r in csv.DictReader(open(out))}
new = not os.path.exists(out)
with open(out, "a", newline="") as f:
    w = csv.DictWriter(f, fieldnames=COLS)
    if new: w.writeheader()
    for r in rows:
        if r["file"] in done:
            print("skip existing", r["file"]); continue
        r.setdefault("birdfy_label", man[r["file"]])
        for c in COLS: r.setdefault(c, "")
        w.writerow({c: r[c] for c in COLS})
        print("wrote", r["file"], r["individual"])
