"""Build manifest.csv for downloaded Birdfy clips and reconcile against card labels.

Each clip file is named YYYY-MM-DD_HHMMSS.mp4 (start time, America/New_York),
derived from the mp4 creation_time minus duration. Card times come from
labels_YYYY-MM-DD.txt ("h:mm am|labels"), copied from the Birdfy events page.
Cards and files are paired in time order; each pair must be within -60..+120 s.
"""
import csv, hashlib, json, subprocess, sys
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
CLIPS = HERE / "raw_clips"

def probe(p):
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                          "-of", "json", str(p)], capture_output=True, text=True).stdout
    return float(json.loads(out)["format"]["duration"])

def sha(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()

def main(days):
    rows, problems = [], []
    for day in days:
        cards = []
        for line in (HERE / f"labels_{day}.txt").read_text().splitlines():
            t, lab = line.split("|", 1)
            dt = datetime.strptime(f"{day} {t.strip().upper()}", "%Y-%m-%d %I:%M %p")
            cards.append([dt, lab.strip(), None])
        files = sorted(CLIPS.glob(f"{day}_*.mp4"))
        cards.sort(key=lambda c: c[0])
        if len(files) != len(cards):
            problems.append(f"{day}: {len(cards)} cards but {len(files)} files")
        for f, c in zip(files, cards):
            start = datetime.strptime(f.stem[:17], "%Y-%m-%d_%H%M%S")
            gap = (start - c[0]).total_seconds()
            if not -60 <= gap <= 120:
                problems.append(f"{f.name}: paired card {c[0]:%H:%M} off by {gap:.0f}s")
            rows.append({"file": f.name, "date": day, "start": f"{start:%H:%M:%S}",
                         "card_time": f"{c[0]:%H:%M}", "birdfy_label": c[1],
                         "dur_s": round(probe(f), 3), "bytes": f.stat().st_size,
                         "sha256": sha(f)})
        print(f"{day}: {len(cards)} cards, {len(files)} files")
    with open(HERE / "manifest.csv", "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0]))
        w.writeheader(); w.writerows(rows)
    print("problems:", problems or "none")
    return 1 if problems else 0

if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
