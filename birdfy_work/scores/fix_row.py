"""usage: fix_row.py CSV FILE INDIVIDUAL FIELD VALUE  (rewrite one cell)"""
import csv, sys, os
p, fn, ind, field, val = sys.argv[1:6]
rows = list(csv.DictReader(open(p, newline="")))
cols = list(rows[0].keys())
n = 0
for r in rows:
    if r["file"] == fn and r["individual"] == ind:
        r[field] = val; n += 1
tmp = p + ".tmp"
with open(tmp, "w", newline="") as f:
    w = csv.DictWriter(f, fieldnames=cols); w.writeheader(); w.writerows(rows)
os.replace(tmp, p); print("updated", n)
