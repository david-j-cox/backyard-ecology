import csv
W="/Users/davidjcox/Documents/campus-worktrees/6c828482/birdfy_work"
man=[r["file"] for r in csv.DictReader(open(W+"/manifest.csv")) if r["date"]=="2026-11-20"]
rows=list(csv.DictReader(open(W+"/scores/scores_2026-11-20.csv")))
hdr=open(W+"/scores/scores_2026-11-14.csv").readline().strip()
print("header ok", open(W+"/scores/scores_2026-11-20.csv").readline().strip()==hdr)
files={r["file"] for r in rows}
print("manifest",len(man),"missing",[f for f in man if f not in files],"extra",files-set(man))
print("rows",len(rows))
from collections import Counter
print(Counter(r["species"] for r in rows))
for r in rows:
    p=[]
    lt,rt,g=float(r["left_time_s"]),float(r["right_time_s"]),float(r["guessed_time_s"])
    if ((lt+rt)*4)%1: p.append("time not multiple of .25")
    if g>lt+rt: p.append("guessed>total")
    if "Squirrel" in r["species"]:
        if r["left_pecks"] or r["right_pecks"] or r["peck_range"] or r["peck_times_s"]: p.append("squirrel pecks")
    else:
        n=len([x for x in r["peck_times_s"].split(";") if x])
        if n!=int(r["left_pecks"])+int(r["right_pecks"]): p.append("peck count mismatch")
        a,b=map(int,r["peck_range"].split("-"))
        if not a<=n<=b: p.append("count outside range")
    print(r["file"],r["individual"],lt+rt,(lt+rt)*4,"frames",p or "ok")
