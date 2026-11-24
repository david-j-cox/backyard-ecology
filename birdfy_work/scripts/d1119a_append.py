"""usage: python3 -I d1119a_append.py ROWS.json  -- append rows (list of dicts) to scores_2026-11-19_a.csv,
skipping files that already have rows."""
import csv, json, sys, os
W = "/Users/davidjcox/Documents/campus-worktrees/6c828482/birdfy_work"
OUT = f"{W}/scores/parts/scores_2026-11-19_a.csv"
COLS = "file,individual,species,sex_if_known,left_pecks,right_pecks,peck_range,confidence,peck_times_s,left_time_s,right_time_s,guessed_time_s,time_censored,time_note,seed_check,notes,birdfy_label".split(",")
lab = {r["file"]: r["birdfy_label"] for r in csv.DictReader(open(f"{W}/manifest.csv"))}
rows = json.load(open(sys.argv[1]))
have = set()
if os.path.exists(OUT):
    have = {r["file"] for r in csv.DictReader(open(OUT))}
new = not os.path.exists(OUT)
with open(OUT, "a", newline="") as f:
    w = csv.DictWriter(f, fieldnames=COLS)
    if new: w.writeheader()
    n = 0
    for r in rows:
        if r["file"] in have: print("skip", r["file"]); continue
        r.setdefault("birdfy_label", lab[r["file"]])
        w.writerow({k: r.get(k, "") for k in COLS}); n += 1
print("appended", n)
