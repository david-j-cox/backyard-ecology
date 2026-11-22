"""Build paste-ready TSVs for the Google Sheet's Jacksonville tabs from an assembled batch.

usage: sheet_rows.py BATCH.xlsx SHEET_EXPORT.xlsx OUT_DIR

BATCH.xlsx is assemble.py's birdfy_rows_*.xlsx ("Birdfy rows" sheet).
SHEET_EXPORT.xlsx is a fresh xlsx export of the Google Sheet; its Jacksonville
raw tab supplies the history for the time-gap columns.

The Sheet stores values, not formulas (rules verified on the Nov 5-14 rows):
  IVI (mins)      minutes since the previous row, across days
  species column  minutes since that species' previous row, only on that
                  species' own row; species with no column get nothing
  Daily Summaries one row per date x species in first-appearance order:
                  Feeder Visits, Left/Right Pecks = day's peck sum + 1,
                  pecks blank for squirrels
Writes raw_rows.tsv and daily_rows.tsv (no header) plus a summary line.
"""
import sys
from pathlib import Path

import pandas as pd

RAW_TAB = "Jacksonville, FL 32259 Raw Data"
DAILY_TAB = "Jacksonville, FL 32259 Daily Su"


def fmt_num(v):
    if v is None or pd.isna(v):
        return ""
    f = float(v)
    return str(int(f)) if f.is_integer() else f"{f:g}"


def main(batch, export, out_dir):
    out = Path(out_dir); out.mkdir(parents=True, exist_ok=True)
    new = pd.read_excel(batch, sheet_name="Birdfy rows")
    hist = pd.read_excel(export, sheet_name=RAW_TAB)
    cols = list(hist.columns)
    species_cols = cols[cols.index("RightTime_s") + 1:]

    def stamp(df):
        t = pd.to_datetime(df["Time"].astype(str), format="mixed")
        return pd.to_datetime(df["Date"]).dt.normalize() + (t - t.dt.normalize())

    hist["stamp"] = stamp(hist)
    new["stamp"] = stamp(new)
    new = new.sort_values("stamp", kind="stable").reset_index(drop=True)
    if new["stamp"].iloc[0] <= hist["stamp"].max():
        raise SystemExit("batch starts before the Sheet's last row; refusing to append")

    last_any = hist["stamp"].max()
    last_sp = {b: hist.loc[hist.Bird == b, "stamp"].max() for b in species_cols}
    lines = []
    for _, r in new.iterrows():
        mins = lambda prev: round((r.stamp - prev).total_seconds() / 60)
        ivi = mins(last_any)
        sp_vals = []
        for b in species_cols:
            if b == r.Bird and pd.notna(last_sp.get(b)):
                sp_vals.append(str(mins(last_sp[b])))
            else:
                sp_vals.append("")
        if r.Bird in species_cols:
            last_sp[r.Bird] = r.stamp
        last_any = r.stamp
        lines.append("\t".join([
            f"{r.stamp.month}/{r.stamp.day}/{r.stamp:%y}", r.Bird, r.stamp.strftime("%-I:%M %p"),
            fmt_num(r.LeftPecks), fmt_num(r.RightPecks), r.LeftSeed, r.RightSeed,
            str(ivi), fmt_num(r.LeftTime_s), fmt_num(r.RightTime_s), *sp_vals]))
    (out / "raw_rows.tsv").write_text("\n".join(lines) + "\n")

    daily = []
    for d, grp in new.groupby(new.stamp.dt.normalize(), sort=True):
        for b in dict.fromkeys(grp.Bird):
            s = grp[grp.Bird == b]
            sq = "squirrel" in b.lower()
            lp = "" if sq else fmt_num(s.LeftPecks.sum() + 1)
            rp = "" if sq else fmt_num(s.RightPecks.sum() + 1)
            daily.append("\t".join([f"{d.month}/{d.day}/{d.year}", b, str(len(s)), lp, rp]))
    (out / "daily_rows.tsv").write_text("\n".join(daily) + "\n")
    no_col = sorted(set(new.Bird) - set(species_cols) - {b for b in new.Bird if "squirrel" in b.lower()})
    print(f"raw rows {len(lines)}, daily rows {len(daily)}; species with no Sheet column: {no_col}")


if __name__ == "__main__":
    main(*sys.argv[1:4])
