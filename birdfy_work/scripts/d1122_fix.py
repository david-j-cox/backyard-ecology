"""usage: python3 -I d1122_fix.py CSV FILE INDIVIDUAL < patch.json  -> update fields of one row in place"""
import csv, json, sys
path, fn, ind = sys.argv[1], sys.argv[2], sys.argv[3]
patch = json.load(sys.stdin)
rows = list(csv.DictReader(open(path, newline="")))
cols = list(rows[0].keys()); n = 0
for r in rows:
    if r["file"] == fn and r["individual"] == ind:
        r.update({k: str(v) for k, v in patch.items()}); n += 1
assert n == 1, n
with open(path, "w", newline="") as f:
    w = csv.DictWriter(f, fieldnames=cols); w.writeheader(); w.writerows(rows)
print("patched", fn, ind, list(patch))
