import csv, collections
W = "/Users/davidjcox/Documents/campus-worktrees/6c828482/birdfy_work"
rows = list(csv.DictReader(open(f"{W}/scores/parts/scores_2026-11-19_a.csv")))
hdr = open(f"{W}/scores/scores_2026-11-14.csv").readline().strip().split(",")
print("header ok:", list(rows[0].keys()) == hdr)
want = sorted(r["file"] for r in csv.DictReader(open(f"{W}/manifest.csv"))
              if r["file"].startswith("2026-11-19") and r["file"] <= "2026-11-19_115734.mp4")
have = {r["file"] for r in rows}
print("clips wanted", len(want), "missing", [f for f in want if f not in have], "extra", sorted(have - set(want)))
print("rows", len(rows))
for r in rows:
    L, R, G = float(r["left_time_s"] or 0), float(r["right_time_s"] or 0), float(r["guessed_time_s"] or 0)
    tot = L + R
    if abs(tot * 4 - round(tot * 4)) > 1e-9 or G > tot + 1e-9: print("TIME?", r["file"], r["individual"], L, R, G)
    sq = "Squirrel" in r["species"]
    if sq and (r["left_pecks"] or r["right_pecks"] or r["peck_times_s"] or r["peck_range"]): print("SQUIRREL PECKS", r["file"])
    if not sq and r["individual"] != "0":
        n = len([x for x in r["peck_times_s"].split(";") if x])
        if n != int(r["left_pecks"]) + int(r["right_pecks"]): print("PECK COUNT", r["file"], r["individual"], n)
    if "\U0001F300" <= max(" ".join(r.values())) : print("non-ascii?", r["file"])
print(collections.Counter(r["species"] for r in rows))
for r in rows: print(r["file"], r["individual"], r["species"], r["left_pecks"], r["right_pecks"], r["left_time_s"], r["right_time_s"], r["guessed_time_s"], r["time_censored"], r["confidence"])
