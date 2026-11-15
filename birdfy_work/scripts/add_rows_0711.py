"""Append score rows for one clip to scores/scores_2026-11-07.csv (skips if clip already present).
usage: add_rows_0711.py ROWS.json   (a JSON list of dicts keyed by column name)
"""
import csv, json, os, sys

COLS = ["file", "individual", "species", "sex_if_known", "left_pecks", "right_pecks", "peck_range",
        "confidence", "peck_times_s", "left_time_s", "right_time_s", "guessed_time_s", "time_censored",
        "time_note", "seed_check", "notes", "birdfy_label"]
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(HERE, "scores", "scores_2026-11-07.csv")
labels = {r["file"]: r["birdfy_label"] for r in csv.DictReader(open(os.path.join(HERE, "manifest.csv")))}

rows = json.load(open(sys.argv[1]))
done = set()
if os.path.exists(OUT):
    done = {r["file"] for r in csv.DictReader(open(OUT, newline=""))}
new = not os.path.exists(OUT)
with open(OUT, "a", newline="") as fh:
    w = csv.DictWriter(fh, fieldnames=COLS)
    if new:
        w.writeheader()
    for r in rows:
        if r["file"] in done:
            print("skip (already scored):", r["file"]); continue
        r.setdefault("birdfy_label", labels.get(r["file"], ""))
        for c in COLS:
            r.setdefault(c, "")
        w.writerow({c: r[c] for c in COLS})
        print("wrote", r["file"], r["individual"])
