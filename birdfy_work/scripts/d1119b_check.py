"""d1119b: check scores_2026-11-19_b.csv against the manifest (second half of 2026-11-19)."""
import csv, collections
W = "/Users/davidjcox/Documents/campus-worktrees/6c828482/birdfy_work"
want = [r["file"] for r in csv.DictReader(open(f"{W}/manifest.csv"))
        if r["date"] == "2026-11-19" and r["file"] >= "2026-11-19_115843.mp4"]
rows = list(csv.DictReader(open(f"{W}/scores/parts/scores_2026-11-19_b.csv")))
hdr = open(f"{W}/scores/scores_2026-11-14.csv").readline().strip().split(",")
assert list(rows[0].keys()) == hdr, "header mismatch"
have = {r["file"] for r in rows}
print("clips wanted", len(want), "missing", sorted(set(want) - have), "extra", sorted(have - set(want)))
print("rows", len(rows))
sp = collections.Counter(r["species"] for r in rows if r["individual"] != "0")
print("species", dict(sp))
bad = 0
for r in rows:
    if r["individual"] == "0":
        continue
    lt, rt, g = float(r["left_time_s"]), float(r["right_time_s"]), float(r["guessed_time_s"])
    tot = lt + rt
    if abs(tot / 0.25 - round(tot / 0.25)) > 1e-9 or g > tot + 1e-9:
        print("time issue", r["file"], r["individual"], lt, rt, g); bad += 1
    if "Squirrel" in r["species"] and (r["left_pecks"] or r["right_pecks"] or r["peck_range"]):
        print("squirrel pecks not blank", r["file"]); bad += 1
    if "Squirrel" not in r["species"]:
        n = len([t for t in r["peck_times_s"].split(";") if t])
        if n != int(r["left_pecks"]) + int(r["right_pecks"]):
            print("peck count mismatch", r["file"], r["individual"], n); bad += 1
        pr = r["peck_range"]
        if "?" in pr or not all(p.isdigit() for p in pr.split("-")):
            print("bad range", r["file"], pr); bad += 1
    print(f'{r["file"]} {r["individual"]} {r["species"]:22s} L{r["left_pecks"]} R{r["right_pecks"]} {r["peck_range"]:5s} {r["confidence"]:6s} lt{lt} rt{rt} g{g} frames={tot/0.25:.0f} cens={r["time_censored"]}')
print("problems", bad)
