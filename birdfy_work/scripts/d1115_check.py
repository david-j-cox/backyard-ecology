"""d1115: check scores_2026-11-15.csv against the manifest and protocol rules."""
import csv, collections
W = "/Users/davidjcox/Documents/campus-worktrees/6c828482/birdfy_work"
man = [r["file"] for r in csv.DictReader(open(f"{W}/manifest.csv")) if r["date"] == "2026-11-15"]
rows = list(csv.DictReader(open(f"{W}/scores/scores_2026-11-15.csv", newline="")))
files = {r["file"] for r in rows}
print("manifest clips", len(man), "scored clips", len(files), "rows", len(rows))
print("missing", sorted(set(man) - files), "extra", sorted(files - set(man)))
sp = collections.Counter()
for r in rows:
    if r["individual"] == "0":
        sp["(no animal)"] += 1; continue
    sp[r["species"]] += 1
    L, R, G = float(r["left_time_s"]), float(r["right_time_s"]), float(r["guessed_time_s"])
    tot = L + R
    if abs(tot * 4 - round(tot * 4)) > 1e-9 or G > tot + 1e-9:
        print("TIME PROBLEM", r["file"], r["individual"], L, R, G)
    if "Squirrel" in r["species"] and (r["left_pecks"] or r["right_pecks"] or r["peck_range"] or r["peck_times_s"]):
        print("SQUIRREL PECKS NOT BLANK", r["file"])
    if "Squirrel" not in r["species"]:
        n = len([t for t in r["peck_times_s"].split(";") if t])
        if n != int(r["left_pecks"]) + int(r["right_pecks"]):
            print("PECK COUNT MISMATCH", r["file"], r["individual"], n, r["left_pecks"], r["right_pecks"])
    print(f'{r["file"]} {r["individual"]} {r["species"][:22]:22} L{L:6.2f} R{R:6.2f} G{G:6.2f} frames={tot*4:.0f} pk={r["left_pecks"]}/{r["right_pecks"]} {r["confidence"]} {r["time_censored"]}')
print(dict(sp))
