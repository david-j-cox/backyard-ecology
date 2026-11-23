"""d1117: check scores_2026-11-17.csv against manifest and time/peck rules."""
import csv, collections
W = "/Users/davidjcox/Documents/campus-worktrees/6c828482/birdfy_work"
man = [r["file"] for r in csv.DictReader(open(f"{W}/manifest.csv", newline="")) if r["date"] == "2026-11-17"]
rows = list(csv.DictReader(open(f"{W}/scores/scores_2026-11-17.csv", newline="")))
have = {r["file"] for r in rows}
print("manifest", len(man), "scored files", len(have), "rows", len(rows))
print("missing", sorted(set(man) - have), "extra", sorted(have - set(man)))
tally = collections.Counter()
for r in rows:
    tally[r["species"] or "(none)"] += 1
    if r["individual"] == "0":
        continue
    L, R, G = float(r["left_time_s"]), float(r["right_time_s"]), float(r["guessed_time_s"])
    tot = L + R
    if abs(tot / 0.25 - round(tot / 0.25)) > 1e-9 or G > tot + 1e-9:
        print("TIME PROBLEM", r["file"], r["individual"], L, R, G)
    if "Squirrel" in r["species"] and (r["left_pecks"] or r["right_pecks"] or r["peck_range"] or r["peck_times_s"]):
        print("SQUIRREL PECKS NOT BLANK", r["file"])
    if "Squirrel" not in r["species"]:
        n = len([t for t in r["peck_times_s"].split(";") if t])
        if n != int(r["left_pecks"]) + int(r["right_pecks"]):
            print("PECK COUNT MISMATCH", r["file"], r["individual"], n, r["left_pecks"], r["right_pecks"])
    print(f'{r["file"]} #{r["individual"]} {r["species"]:24s} L={L} R={R} on-frames={tot/0.25:.0f} G={G} cens={r["time_censored"]} conf={r["confidence"]}')
print(dict(tally))
