"""Compare blind second scores with first scores for the sampled clips.

Writes blind/blind_compare.csv and prints agreement summaries for species,
pecks per side, and side time per side.
"""
import csv, glob, statistics, sys
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
BLIND = HERE / (sys.argv[1] if len(sys.argv) > 1 else "blind")
first = {}
for f in glob.glob(str(HERE / "scores" / "scores_*.csv")):
    for r in csv.DictReader(open(f)):
        if r["individual"] == "1":
            first[r["file"]] = r
blind = {r["file"]: r for r in csv.DictReader(open(BLIND / "blind_scores.csv")) if r["individual"] in ("1", "0")}


def n(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


out, sp_agree = [], 0
for f in sorted(blind):
    a, b = first[f], blind[f]
    row = {"file": f, "first_species": a["species"], "blind_species": b["species"]}
    sp_agree += a["species"].split(" (")[0].lower() == b["species"].split(" (")[0].lower()
    for k in ("left_pecks", "right_pecks", "left_time_s", "right_time_s", "guessed_time_s"):
        row[f"first_{k}"], row[f"blind_{k}"] = a[k], b[k]
    row["blind_peck_range"] = b["peck_range"]
    out.append(row)
with open(BLIND / "blind_compare.csv", "w", newline="") as fh:
    w = csv.DictWriter(fh, fieldnames=list(out[0])); w.writeheader(); w.writerows(out)

print(f"clips compared: {len(out)}; species agree: {sp_agree}/{len(out)}")
for k in ("left_pecks", "right_pecks", "left_time_s", "right_time_s"):
    pairs = [(n(r[f"first_{k}"]), n(r[f"blind_{k}"])) for r in out]
    pairs = [(x, y) for x, y in pairs if x is not None and y is not None]
    if not pairs:
        continue
    diffs = [abs(x - y) for x, y in pairs]
    exact = sum(d == 0 for d in diffs)
    tot_a, tot_b = sum(x for x, _ in pairs), sum(y for _, y in pairs)
    # total-count agreement (smaller/larger), the usual IOA for count data
    tca = statistics.mean([1.0 if max(x, y) == 0 else min(x, y) / max(x, y) for x, y in pairs])
    print(f"{k}: n={len(pairs)} exact={exact} mean|diff|={statistics.mean(diffs):.2f} "
          f"mean total-count IOA={tca:.2f} sums first={tot_a:g} blind={tot_b:g}")
side = [r for r in out if (n(r["first_left_time_s"]) or 0) + (n(r["first_right_time_s"]) or 0) > 0
        and (n(r["blind_left_time_s"]) or 0) + (n(r["blind_right_time_s"]) or 0) > 0]
same_major = sum(((n(r["first_left_time_s"]) or 0) > (n(r["first_right_time_s"]) or 0)) ==
                 ((n(r["blind_left_time_s"]) or 0) > (n(r["blind_right_time_s"]) or 0)) for r in side)
print(f"majority side agrees: {same_major}/{len(side)}")
