"""Assemble scored Birdfy clips into the batch file and an updated workbook copy.

usage: assemble.py START END [--workbook SRC.xlsx] [--out-dir DIR]

Reads scores/scores_*.csv and manifest.csv for dates START..END and writes, in DIR:
  birdfy_rows_START_to_END.xlsx   sheets: Birdfy rows, Check, Clip notes
  backyard_ecology_multi_site_data_UPDATED.xlsx   (only with --workbook)

Workbook update: inserts LeftTime_s and RightTime_s as columns I:J of RawData
(after IVI, before the species columns), shifts the species formulas' own-column
references by two, and appends the new rows with the same IVI and species
formulas the sheet already uses. DailySummaries gets one row per date x species
with the same COUNTIFS/SUMIFS formulas as recent rows.
Nothing is written outside DIR.
"""
import argparse, csv, glob, re, sys
from collections import OrderedDict
from datetime import datetime, date, time
from pathlib import Path

import openpyxl
from openpyxl.utils import get_column_letter, column_index_from_string
from openpyxl.worksheet.formula import ArrayFormula

HERE = Path(__file__).resolve().parent.parent
# Seeds as in the last batch, confirmed by David on 2026-11-15. The safflower in
# the feeder-right tray looks like small striped/tan seed on this camera.
LEFT_SEED = "Peanuts, Sunflower"
RIGHT_SEED = "Safflower, Mealworm"
MAMMALS = ("squirrel",)


def species_name(raw):
    """Strip '(probable)' style qualifiers; keep the qualifier for notes."""
    s = raw.strip()
    if s.lower().startswith("unidentified"):
        return "Unidentified bird", "unidentified"
    m = re.match(r"^(.*?)\s*\((probable|possible)\)\s*$", s, re.I)
    if m:
        return m.group(1).strip(), m.group(2).lower()
    return s, ""


def num(v):
    v = (v or "").strip()
    if v == "":
        return None
    try:
        f = float(v)
        return int(f) if f.is_integer() else f
    except ValueError:
        return None


def load(start, end):
    man = {r["file"]: r for r in csv.DictReader(open(HERE / "manifest.csv"))}
    rows = []
    for f in sorted(glob.glob(str(HERE / "scores" / "scores_*.csv"))):
        d = Path(f).stem.replace("scores_", "")
        if not (start <= d <= end):
            continue
        for r in csv.DictReader(open(f)):
            r["_man"] = man[r["file"]]
            rows.append(r)
    want = {k for k, v in man.items() if start <= v["date"] <= end}
    have = {r["file"] for r in rows}
    if want - have:
        sys.exit(f"missing scores for {len(want - have)} clips, e.g. {sorted(want - have)[:5]}")
    rows.sort(key=lambda r: (r["_man"]["date"], r["_man"]["card_time"], r["file"], int(r["individual"] or 0)))
    return rows


def build_batch(rows):
    data, check, notes, sq_guess = [], [], [], []
    for r in rows:
        m = r["_man"]
        d = datetime.strptime(m["date"], "%Y-%m-%d")
        t = datetime.strptime(m["card_time"], "%H:%M").time()
        if (r["individual"] or "0").strip() == "0":
            check.append([d, t, f"No row (no animal): {r['notes']}"])
            notes.append(r)
            continue
        sp, qual = species_name(r["species"])
        mammal = any(k in sp.lower() for k in MAMMALS)
        lp, rp = (None, None) if mammal else (num(r["left_pecks"]), num(r["right_pecks"]))
        lt, rt, g = num(r["left_time_s"]) or 0, num(r["right_time_s"]) or 0, num(r["guessed_time_s"]) or 0
        bits = []
        if qual:
            bits.append(f"ID {qual}")
        if g:
            bits.append(f"{g:g} s of side time guessed")
        if r["time_censored"]:
            bits.append({"start": "already on feeder at clip start", "end": "still on feeder at clip end",
                         "both": "on feeder for whole clip"}.get(r["time_censored"], r["time_censored"])
                        + " (time is a lower bound)")
        if r["confidence"] == "low" and not mammal:
            bits.append(f"low-confidence pecks, range {r['peck_range'] or '?'}")
        data.append([d, sp, t, lp, rp, LEFT_SEED, RIGHT_SEED, lt, rt, "; ".join(bits)])
        notes.append(r)
        tot = lt + rt
        wide = False
        for lo, hi in re.findall(r"(\d+)\s*-\s*(\d+)", r["peck_range"] or ""):
            if int(hi) - int(lo) >= 8:
                wide = True
        if mammal and tot and g / tot > 0.5:
            sq_guess.append(f"{m['date'][5:]} {m['card_time']}")
        if qual or (not mammal and tot and g / tot > 0.5) or (wide and not mammal):
            check.append([d, t, f"{sp}: {r['confidence']} confidence (L {r['left_pecks'] or '-'}, R {r['right_pecks'] or '-'}"
                          f"{', range ' + r['peck_range'] if r['peck_range'] else ''}; side time L {lt:g} s, R {rt:g} s, "
                          f"guessed {g:g} s). {r['notes']}"])
    if sq_guess:
        check.insert(0, [None, None, f"Squirrel side times are mostly guessed in {len(sq_guess)} rows (head hidden while the squirrel "
                         "sits on or against the lens; side taken from body position). Treat their left/right split as rough: " + ", ".join(sq_guess)])
    return data, check, notes


def write_batch(path, data, check, notes):
    wb = openpyxl.Workbook()
    ws = wb.active; ws.title = "Birdfy rows"
    ws.append(["Date", "Bird", "Time", "LeftPecks", "RightPecks", "LeftSeed", "RightSeed",
               "LeftTime_s", "RightTime_s", "Notes"])
    for row in data:
        ws.append(row)
    for c in ws["A"][1:]:
        c.number_format = "yyyy-mm-dd"
    for c in ws["C"][1:]:
        c.number_format = "hh:mm:ss"
    ck = wb.create_sheet("Check")
    ck.append(["Date", "Time", "What to check"])
    ck.append([None, None, "Squirrel rows have blank pecks by design (pecks are never recorded for squirrels); they do have side time."])
    ck.append([None, None, f"LeftSeed/RightSeed: {LEFT_SEED} / {RIGHT_SEED}, as in the last batch (confirmed by David 2026-11-15). "
                           "In Clip notes, scorers describe the safflower as 'small striped/tan seed' and some wrote 'no safflower seen'; "
                           "that is a scorer misreading, and the seed columns are correct."])
    ck.append([None, None, "LeftTime_s/RightTime_s: seconds the head was over feeder left (image-right) / feeder right (image-left), "
                           "sampled at 4 fps. Hidden-head time is a best guess (see Notes). Clips stop at about 30 s, so long visits are lower bounds."])
    for row in check:
        ck.append(row)
    cn = wb.create_sheet("Clip notes")
    cols = ["file", "individual", "species", "sex_if_known", "left_pecks", "right_pecks", "peck_range", "confidence",
            "peck_times_s", "left_time_s", "right_time_s", "guessed_time_s", "time_censored", "time_note",
            "seed_check", "notes", "birdfy_label"]
    cn.append(cols)
    for r in notes:
        cn.append([num(r[c]) if c in ("individual", "left_pecks", "right_pecks", "left_time_s", "right_time_s", "guessed_time_s")
                   else r[c] for c in cols])
    bc = HERE / "blind" / "blind_compare.csv"
    if bc.exists():
        final = {r["file"]: r for r in notes if (r["individual"] or "") == "1"}
        bs = wb.create_sheet("Blind check")
        bs.append(["file", "first species", "blind species", "final species",
                   "first L", "first R", "blind L", "blind R", "blind range", "final L", "final R",
                   "first L time", "first R time", "blind L time", "blind R time"])
        for r in csv.DictReader(open(bc)):
            f = final.get(r["file"], {})
            bs.append([r["file"], r["first_species"], r["blind_species"], f.get("species", ""),
                       num(r["first_left_pecks"]), num(r["first_right_pecks"]), num(r["blind_left_pecks"]),
                       num(r["blind_right_pecks"]), r["blind_peck_range"], num(f.get("left_pecks")), num(f.get("right_pecks")),
                       num(r["first_left_time_s"]), num(r["first_right_time_s"]),
                       num(r["blind_left_time_s"]), num(r["blind_right_time_s"])])
    wb.save(path)


SHIFT_RE = re.compile(r"(?<![A-Z$])(\$?)([A-Z]{1,3})(\$?)(\d+)")


def shift_formula(text, at_col, by):
    """Shift column letters >= at_col by `by` in A1 references (not in strings)."""
    out, instr = [], False
    for part in re.split(r'("[^"]*")', text):
        if part.startswith('"'):
            out.append(part); continue
        def rep(m):
            col = column_index_from_string(m.group(2))
            if col >= at_col:
                col += by
            return f"{m.group(1)}{get_column_letter(col)}{m.group(3)}{m.group(4)}"
        out.append(SHIFT_RE.sub(rep, part))
    return "".join(out)


def update_workbook(src, dst, data):
    wb = openpyxl.load_workbook(src)
    ws = wb["RawData"]
    hdr = [c.value for c in ws[1]]
    assert hdr[7] == "IVI (mins)" and hdr[8] == "Northern Cardinal", hdr[:9]
    first_sp, n_sp = 9, len(hdr) - 8           # species start at column I (9)
    # 1. shift existing species formulas, then insert the two columns
    for row in ws.iter_rows(min_row=2, min_col=first_sp, max_col=ws.max_column):
        for c in row:
            v = c.value
            if isinstance(v, ArrayFormula):
                c.value = ArrayFormula(shift_formula(v.ref, first_sp, 2), shift_formula(v.text, first_sp, 2))
            elif isinstance(v, str) and v.startswith("="):
                c.value = shift_formula(v, first_sp, 2)
    ws.insert_cols(first_sp, 2)
    ws.cell(1, first_sp, "LeftTime_s"); ws.cell(1, first_sp + 1, "RightTime_s")
    # 2. append new rows with the sheet's own formulas
    last = ws.max_row
    while last > 1 and ws.cell(last, 1).value is None:
        last -= 1
    for k, row in enumerate(data):
        i = last + 1 + k
        d, sp, t, lp, rp, ls, rs, lt, rt, _ = row
        for j, v in enumerate([d, sp, t, lp, rp, ls, rs], start=1):
            ws.cell(i, j, v)
        ws.cell(i, 1).number_format = ws.cell(last, 1).number_format
        ws.cell(i, 3).number_format = ws.cell(last, 3).number_format
        ws.cell(i, 8, f'=IFERROR((($A{i}+$C{i}) - ($A{i-1}+$C{i-1}))*24*60, "")')
        ws.cell(i, 9, lt); ws.cell(i, 10, rt)
        for s in range(n_sp):
            col = first_sp + 2 + s; L = get_column_letter(col)
            ref = f"{L}{i}"
            ws.cell(i, col).value = ArrayFormula(ref, f'=IFERROR(IF($B{i}={L}$1, ($A{i}+$C{i}) - MAX(IF($B$2:$B{i-1}=$B{i}, $A$2:$A{i-1}+$C$2:$C{i-1})), "")*24*60, "")')
    # 3. DailySummaries: one row per date x species, same formulas as recent rows
    ds = wb["DailySummaries"]
    dlast = ds.max_row
    while dlast > 1 and ds.cell(dlast, 1).value is None:
        dlast -= 1
    pairs = list(OrderedDict.fromkeys((row[0], row[1]) for row in data))
    for k, (d, sp) in enumerate(pairs):
        i = dlast + 1 + k
        ds.cell(i, 1, d).number_format = ds.cell(dlast, 1).number_format
        ds.cell(i, 2, sp)
        ds.cell(i, 3, f"=COUNTIFS(RawData!$B:$B, $B{i}, RawData!$A:$A, DailySummaries!$A{i})")
    wb.save(dst)
    return last, len(data), len(pairs)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("start"); ap.add_argument("end")
    ap.add_argument("--workbook"); ap.add_argument("--out-dir", default=str(HERE / "out"))
    a = ap.parse_args()
    out = Path(a.out_dir); out.mkdir(exist_ok=True)
    rows = load(a.start, a.end)
    data, check, notes = build_batch(rows)
    bp = out / f"birdfy_rows_{a.start}_to_{a.end}.xlsx"
    write_batch(bp, data, check, notes)
    print(f"{bp.name}: {len(data)} data rows, {len(check)} check items, {len(notes)} clip notes")
    if a.workbook:
        dst = out / "backyard_ecology_multi_site_data_UPDATED.xlsx"
        last, n, p = update_workbook(a.workbook, dst, data)
        print(f"{dst.name}: RawData had {last} rows incl. header, appended {n}; DailySummaries +{p}")


if __name__ == "__main__":
    main()
