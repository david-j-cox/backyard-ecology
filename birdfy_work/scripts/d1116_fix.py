"""d1116_fix.py OUT.csv FILE INDIVIDUAL COL=VALUE [COL=VALUE ...] -> edit one row in place (csv module)."""
import csv, sys
out, f, ind = sys.argv[1], sys.argv[2], sys.argv[3]
rows = list(csv.DictReader(open(out, newline="")))
cols = list(rows[0].keys())
n = 0
for r in rows:
    if r["file"] == f and r["individual"] == ind:
        for kv in sys.argv[4:]:
            k, v = kv.split("=", 1)
            assert k in cols, k
            r[k] = v
        n += 1
assert n == 1, n
with open(out, "w", newline="") as fh:
    w = csv.DictWriter(fh, fieldnames=cols); w.writeheader(); w.writerows(rows)
print("fixed", f, ind)
