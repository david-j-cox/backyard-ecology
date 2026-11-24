"""Build a blind IOA packet for David: N random scored clips per day, copied
clips plus a blank score sheet (no first-scorer values shown).

usage: ioa_packet.py OUT_DIR DATE [DATE ...] [--n 10] [--seed 20261124]

Samples only clips the first scorer coded with an animal (individual >= 1).
Writes OUT_DIR/ioa_sample.csv (the key), OUT_DIR/clips/*.mp4 and
OUT_DIR/IOA_scoresheet_FIRST_to_LAST.xlsx (new dates only). Re-running with the same seed gives the same sample;
dates already in ioa_sample.csv are kept as they are.
"""
import argparse, csv, random, shutil
from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill

HERE = Path(__file__).resolve().parent.parent
FIELDS = ["clip", "date", "clip_start", "duration_s", "individual", "species",
          "left_pecks", "right_pecks", "left_time_s", "right_time_s", "notes"]
INSTRUCTIONS = [
    "Score each clip without looking at the first scores.",
    "One row is pre-filled per clip. If more than one animal is on the feeder, copy the row and number them 1, 2, ...",
    "Sides: the image-LEFT tray is FEEDER RIGHT; the image-RIGHT tray is FEEDER LEFT. The divide is the middle of the frame.",
    "left_pecks / right_pecks: bill strikes into feeder-left / feeder-right seed. One peck per distinct strike. Leave blank for squirrels.",
    "left_time_s / right_time_s: seconds the head is over each side while on the feeder (not flying in or out). Rough is fine, e.g. to the nearest second.",
    "species: field ID. notes: anything unclear (head hidden, two birds, etc.).",
]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("out"); ap.add_argument("dates", nargs="+")
    ap.add_argument("--n", type=int, default=10); ap.add_argument("--seed", type=int, default=20261124)
    a = ap.parse_args()
    out = Path(a.out); (out / "clips").mkdir(parents=True, exist_ok=True)
    man = {r["file"]: r for r in csv.DictReader(open(HERE / "manifest.csv"))}
    key_path = out / "ioa_sample.csv"
    key = list(csv.DictReader(open(key_path))) if key_path.exists() else []
    done = {r["date"] for r in key}
    new_dates = [d for d in a.dates if d not in done]
    if not new_dates:
        raise SystemExit("all dates already sampled")
    for d in new_dates:
        rows = list(csv.DictReader(open(HERE / "scores" / f"scores_{d}.csv")))
        animal = sorted({r["file"] for r in rows if r["individual"] not in ("", "0")})
        pick = sorted(random.Random(f"{a.seed}-{d}").sample(animal, min(a.n, len(animal))))
        for f in pick:
            m = man[f]
            key.append({"clip": f, "date": d, "clip_start": m["start"], "duration_s": m["dur_s"]})
            shutil.copy2(HERE / "raw_clips" / f, out / "clips" / f)
    key.sort(key=lambda r: r["clip"])
    with open(key_path, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=["clip", "date", "clip_start", "duration_s"]); w.writeheader(); w.writerows(key)

    wb = Workbook(); ws = wb.active; ws.title = "Scores"
    ws.append(FIELDS)
    for c in ws[1]:
        c.font = Font(bold=True); c.fill = PatternFill("solid", fgColor="DDEBF7")
    for r in [r for r in key if r["date"] in new_dates]:
        ws.append([r["clip"], r["date"], r["clip_start"], float(r["duration_s"]), 1] + [None] * 6)
    for col, wdt in zip("ABCDEFGHIJK", (24, 11, 10, 10, 10, 22, 10, 11, 11, 12, 50)):
        ws.column_dimensions[col].width = wdt
    ws.freeze_panes = "A2"
    ins = wb.create_sheet("Instructions")
    for i, line in enumerate(INSTRUCTIONS, 1):
        ins.cell(i, 1, line).alignment = Alignment(wrap_text=True)
    ins.column_dimensions["A"].width = 110
    sheet = out / f"IOA_scoresheet_{new_dates[0]}_to_{new_dates[-1]}.xlsx"
    if sheet.exists():
        raise SystemExit(f"{sheet} exists; not overwriting a sheet that may hold scores")
    wb.save(sheet)
    print(f"{sum(r['date'] in new_dates for r in key)} clips over {len(new_dates)} days -> {sheet}")


if __name__ == "__main__":
    main()
