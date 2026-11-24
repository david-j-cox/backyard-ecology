"""Make a time-stamped contact sheet from a Birdfy clip for frame-by-frame scoring.

usage: sheet.py CLIP OUT.jpg [--start S] [--end E] [--fps F] [--cols C] [--width W] [--crop x,y,w,h]

Frames are sampled at F per second between S and E (seconds into the clip),
scaled to W pixels wide, tiled C across, and stamped with their time.
--crop works in source pixels (2304x1296) to zoom on the trays.
Side reminder: image-left tray = FEEDER RIGHT; image-right tray = FEEDER LEFT.
"""
import argparse, subprocess, tempfile, glob, os
from PIL import Image, ImageDraw, ImageFont

ap = argparse.ArgumentParser()
ap.add_argument("clip"); ap.add_argument("out")
ap.add_argument("--start", type=float, default=0); ap.add_argument("--end", type=float, default=None)
ap.add_argument("--fps", type=float, default=2); ap.add_argument("--cols", type=int, default=6)
ap.add_argument("--width", type=int, default=320); ap.add_argument("--crop", default=None)
a = ap.parse_args()

dur = float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of",
                            "csv=p=0", a.clip], capture_output=True, text=True).stdout)
end = min(a.end if a.end is not None else dur, dur)
with tempfile.TemporaryDirectory() as td:
    vf = f"fps={a.fps}"
    if a.crop:
        x, y, w, h = a.crop.split(","); vf = f"crop={w}:{h}:{x}:{y}," + vf
    vf += f",scale={a.width}:-2"
    subprocess.run(["ffmpeg", "-v", "error", "-ss", str(a.start), "-to", str(end), "-i", a.clip,
                    "-vf", vf, f"{td}/f%04d.jpg"], check=True)
    files = sorted(glob.glob(f"{td}/f*.jpg"))
    if not files:
        raise SystemExit("no frames")
    ims = [Image.open(f) for f in files]
    w, h = ims[0].size
    rows = -(-len(ims) // a.cols)
    sheet = Image.new("RGB", (a.cols * w, rows * h), "black")
    d = ImageDraw.Draw(sheet)
    font = ImageFont.load_default(size=max(12, w // 16))
    for i, im in enumerate(ims):
        x, y = (i % a.cols) * w, (i // a.cols) * h
        sheet.paste(im, (x, y))
        t = a.start + i / a.fps
        d.rectangle([x, y, x + w // 4, y + w // 13], fill="black")
        d.text((x + 3, y + 1), f"{t:.2f}s", fill="yellow", font=font)
        d.line([x + w // 2, y + w // 13, x + w // 2, y + h], fill="cyan")  # lens-centre tick
    sheet.save(a.out, quality=85)
    print(f"{a.out}: {len(ims)} frames {a.start:.2f}-{end:.2f}s of {dur:.2f}s, {a.cols}x{rows}")
