"""usage: python3 -I d1121b_fix.py CSV < fixes.json  (list of {"file":..,"individual":..,"set":{col:val}})"""
import csv, json, sys
p = sys.argv[1]
fixes = json.load(sys.stdin)
with open(p, newline="") as f:
    rd = csv.DictReader(f); cols = rd.fieldnames; rows = list(rd)
for fx in fixes:
    hit = [r for r in rows if r["file"] == fx["file"] and r["individual"] == str(fx["individual"])]
    if len(hit) != 1: sys.exit(f"no unique row for {fx['file']} {fx['individual']}")
    for k, v in fx["set"].items():
        if k not in cols: sys.exit(f"bad col {k}")
        hit[0][k] = v
with open(p, "w", newline="") as f:
    w = csv.DictWriter(f, fieldnames=cols); w.writeheader(); w.writerows(rows)
print(f"fixed {len(fixes)} rows")
