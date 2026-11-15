"""usage: python3 -I add.py ROW.json  (a JSON list of row dicts) -> appends to blind_scores.csv"""
import csv, json, sys, os
COLS = ["file","individual","species","sex_if_known","left_pecks","right_pecks","peck_range","confidence",
        "peck_times_s","left_time_s","right_time_s","guessed_time_s","time_censored","time_note","seed_check","notes","birdfy_label"]
out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "blind_scores.csv")
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
            print("skip (already scored)", r["file"]); continue
        bad = set(r) - set(COLS)
        if bad: raise SystemExit(f"bad keys {bad}")
        w.writerow({c: r.get(c, "") for c in COLS})
        print("added", r["file"], r.get("individual"))
