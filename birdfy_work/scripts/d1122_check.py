import csv, collections
rows = list(csv.DictReader(open("scores/scores_2026-11-22.csv", newline="")))
hdr = open("scores/scores_2026-11-14.csv").readline().strip().split(",")
assert list(rows[0].keys()) == hdr, "header mismatch"
want = [r["file"] for r in csv.DictReader(open("manifest.csv")) if r["date"] == "2026-11-22"]
have = {r["file"] for r in rows}
print("manifest clips", len(want), "missing", sorted(set(want) - have), "extra", sorted(have - set(want)))
for r in rows:
    t = float(r["left_time_s"] or 0) + float(r["right_time_s"] or 0)
    if (t * 4) % 1: print("not multiple of .25", r["file"], r["individual"])
    if float(r["guessed_time_s"] or 0) > t: print("guessed > total", r["file"], r["individual"])
    mam = "Squirrel" in r["species"]
    if mam and (r["left_pecks"] or r["right_pecks"] or r["peck_range"]): print("mammal pecks", r["file"])
    if not mam and r["individual"] != "0":
        n = len([x for x in r["peck_times_s"].split(";") if x])
        if n != int(r["left_pecks"]) + int(r["right_pecks"]): print("peck count mismatch", r["file"], r["individual"], n)
        lo, hi = map(int, r["peck_range"].split("-"))
        tot = int(r["left_pecks"]) + int(r["right_pecks"])
        if not lo <= tot <= hi: print("total outside range", r["file"], r["individual"])
print("rows", len(rows))
print(collections.Counter(r["species"] for r in rows))
print("low conf:", [(r["file"][11:17], r["individual"]) for r in rows if r["confidence"] == "low"])
