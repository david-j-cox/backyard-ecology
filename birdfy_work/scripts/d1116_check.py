"""d1116_check.py: verify scores_2026-11-16.csv against the manifest and 4 fps frame counts."""
import csv, math, subprocess, os, collections
W = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
man = [r for r in csv.DictReader(open(os.path.join(W, "manifest.csv"))) if r["date"] == "2026-11-16"]
rows = list(csv.DictReader(open(os.path.join(W, "scores/scores_2026-11-16.csv"))))
files = {r["file"] for r in rows}
print("manifest clips", len(man), "missing", [m["file"] for m in man if m["file"] not in files])
print("rows", len(rows))
nfr = {}
for m in man:
    pass
for line in open("/tmp/d1116_frames.txt"):
    f, n = line.split(); nfr[f] = int(n)  # actual 4 fps frame counts from ffmpeg
sp = collections.Counter()
for r in rows:
    if r["individual"] == "0":
        print("ind0", r["file"]); continue
    sp[r["species"]] += 1
    L, R, G = float(r["left_time_s"]), float(r["right_time_s"]), float(r["guessed_time_s"] or 0)
    tot = L + R; mx = nfr[r["file"]] * 0.25
    flag = []
    if tot > mx + 1e-9: flag.append(f"over max {mx}")
    if r["time_censored"] == "both" and abs(tot - mx) > 1e-9: flag.append(f"both but {tot} != {mx}")
    if G > tot: flag.append("guessed>total")
    if (L * 4) % 1 or (R * 4) % 1: flag.append("not multiple of .25")
    if "Squirrel" in r["species"] and (r["left_pecks"] or r["right_pecks"] or r["peck_range"]): flag.append("squirrel pecks")
    if "Squirrel" not in r["species"]:
        n = len([t for t in r["peck_times_s"].split(";") if t])
        if n != int(r["left_pecks"]) + int(r["right_pecks"]): flag.append(f"peck times {n} != counts")
    print(r["file"][11:17], r["individual"], r["species"][:22], L, R, "max", mx, r["time_censored"], "; ".join(flag))
print(sp)
