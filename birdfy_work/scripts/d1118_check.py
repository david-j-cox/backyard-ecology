import csv, math
man = [r["file"] for r in csv.DictReader(open("manifest.csv")) if r["date"] == "2026-11-18"]
rows = list(csv.DictReader(open("scores/scores_2026-11-18.csv")))
files = {r["file"] for r in rows}
print("manifest", len(man), "missing", sorted(set(man) - files), "extra", sorted(files - set(man)))
print("rows", len(rows))
from collections import Counter
print(Counter(r["species"] for r in rows if r["individual"] != "0"))
for r in rows:
    if r["individual"] == "0": continue
    L, R, G = float(r["left_time_s"]), float(r["right_time_s"]), float(r["guessed_time_s"])
    if abs((L + R) / 0.25 - round((L + R) / 0.25)) > 1e-9 or G > L + R: print("TIME?", r["file"])
    pt = [x for x in r["peck_times_s"].split(";") if x]
    if "Squirrel" in r["species"]:
        if r["left_pecks"] or r["right_pecks"] or pt: print("SQ PECKS", r["file"])
    elif len(pt) != int(r["left_pecks"]) + int(r["right_pecks"]):
        print("PECK MISMATCH", r["file"], len(pt), r["left_pecks"], r["right_pecks"])
    print(r["file"], r["individual"], r["species"], L, R, G, r["left_pecks"], r["right_pecks"], r["confidence"], r["time_censored"])
