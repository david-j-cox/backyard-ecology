"""Merge 2026-11-10 fork part files into scores/scores_2026-11-10.csv in manifest order.
Skips clips already present. Corrects seed_check mealworm mentions for clips from 09:48 on (frame-checked: no mealworms after squirrel bout)."""
import csv, glob
W = "/Users/davidjcox/Documents/campus-worktrees/e13dfb02/birdfy_work"
OUT = f"{W}/scores/scores_2026-11-10.csv"
FIX = ("feeder left (image-right): large striped sunflower, red-skinned peanuts; feeder right (image-left): "
       "small striped/tan seed with spilled striped sunflower, no mealworms visible (mealworms were present at 06:31 "
       "and 09:36 but gone from 09:48 on, after the squirrel visits). Sunflower is striped, not black oil.")
order = [r["file"] for r in csv.DictReader(open(f"{W}/manifest.csv")) if r["date"] == "2026-11-10"]
with open(OUT, newline="") as f:
    rd = csv.DictReader(f); cols = rd.fieldnames; have = {r["file"] for r in rd}
parts = {}
for p in sorted(glob.glob(f"{W}/scores/parts/part*.csv")):
    for r in csv.DictReader(open(p, newline="")):
        parts.setdefault(r["file"], []).append(r)
n = 0
with open(OUT, "a", newline="") as f:
    w = csv.DictWriter(f, fieldnames=cols)
    for fn in order:
        if fn in have or fn not in parts: continue
        for r in parts[fn]:
            if fn[11:17] >= "094838" and "mealworm" in r["seed_check"].lower():
                r["seed_check"] = FIX
            w.writerow(r); n += 1
print("appended", n)
rows = list(csv.DictReader(open(OUT, newline="")))
got = {r["file"] for r in rows}
print("rows", len(rows), "clips", len(got), "missing", [x for x in order if x not in got])
for r in rows:
    if r["left_time_s"] or r["right_time_s"]:
        t = float(r["left_time_s"] or 0) + float(r["right_time_s"] or 0)
        if abs(t * 4 - round(t * 4)) > 1e-6: print("bad time", r["file"], r["individual"], t)
