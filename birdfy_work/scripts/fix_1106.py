"""fix_1106.py CSV FILE INDIVIDUAL COL VALUE - edit one cell (2026-11-06 scoring)."""
import csv, sys
p, f, ind, col, val = sys.argv[1:6]
with open(p, newline="") as fh:
    r = csv.DictReader(fh); cols = r.fieldnames; rows = list(r)
n = 0
for row in rows:
    if row["file"] == f and row["individual"] == ind:
        row[col] = val; n += 1
with open(p + ".tmp", "w", newline="") as fh:
    w = csv.DictWriter(fh, fieldnames=cols); w.writeheader(); w.writerows(rows)
import os; os.replace(p + ".tmp", p)
print("changed", n)
