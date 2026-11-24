"""Checks scores/parts/scores_2026-11-23_a.csv against the manifest (first-half clips)."""
import csv, collections, subprocess
W = "/Users/davidjcox/Documents/campus-worktrees/6c828482/birdfy_work"
man = [r[0] for r in csv.reader(open(W + "/manifest.csv")) if r and r[0].startswith("2026-11-23_") and r[0] <= "2026-11-23_135150.mp4"]
rows = list(csv.DictReader(open(W + "/scores/parts/scores_2026-11-23_a.csv")))
hdr = next(csv.reader(open(W + "/scores/scores_2026-11-14.csv")))
assert list(rows[0].keys()) == hdr, "header mismatch"
files = {r["file"] for r in rows}
print("manifest clips:", len(man), "scored:", len(files), "missing:", sorted(set(man) - files), "extra:", sorted(files - set(man)))
print("rows:", len(rows))
for r in rows:
    f = r["file"]; p = []
    dur = float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", W + "/raw_clips/" + f], capture_output=True, text=True).stdout)
    L, R, G = float(r["left_time_s"]), float(r["right_time_s"]), float(r["guessed_time_s"])
    if ((L + R) / 0.25) % 1: p.append("time not multiple of 0.25")
    if L + R > dur + 0.25: p.append(f"time {L+R} > dur {dur}")
    if G > L + R: p.append("guessed > total")
    if "Squirrel" in r["species"] and any(r[k] for k in ("left_pecks", "right_pecks", "peck_range", "peck_times_s")): p.append("squirrel pecks not blank")
    if "Squirrel" not in r["species"]:
        n = len([t for t in r["peck_times_s"].split(";") if t])
        if n != int(r["left_pecks"]) + int(r["right_pecks"]): p.append(f"peck_times {n} != pecks")
        if "?" in r["peck_range"]: p.append("? in range")
        lo, hi = map(int, r["peck_range"].split("-"))
        if not lo <= n <= hi: p.append("count outside range")
    if p: print("PROBLEM", f, r["individual"], p)
print(collections.Counter(r["species"] for r in rows))
