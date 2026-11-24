"""usage: b2_append.py ROWS.json  -- append rows (list of dicts) to blind_scores.csv, skipping files already present."""
import csv, json, os, sys
COLS = ["file","individual","species","sex_if_known","left_pecks","right_pecks","peck_range","confidence",
        "peck_times_s","left_time_s","right_time_s","guessed_time_s","time_censored","time_note","seed_check","notes","birdfy_label"]
out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "blind_scores.csv")
rows = json.load(open(sys.argv[1]))
done = set()
if os.path.exists(out):
    done = {r["file"] for r in csv.DictReader(open(out, newline=""))}
new = not os.path.exists(out)
with open(out, "a", newline="") as f:
    w = csv.DictWriter(f, fieldnames=COLS)
    if new: w.writeheader()
    files = {r["file"] for r in rows}
    for fn in files & done: print("skip (already scored):", fn)
    for r in rows:
        if r["file"] in done: continue
        assert set(r) <= set(COLS), set(r) - set(COLS)
        w.writerow({c: r.get(c, "") for c in COLS})
        print("wrote", r["file"], r.get("individual"))
