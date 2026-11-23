"""d1119b: HHMMSS OUT.jpg CROP T1 T2 ... -> one 15 fps row (1.0 s, centred on each Ti) per dip, stacked."""
import sys, subprocess, tempfile, os
from PIL import Image
W = "/Users/davidjcox/Documents/campus-worktrees/6c828482/birdfy_work"
hh, out, crop, ts = sys.argv[1], sys.argv[2], sys.argv[3], [float(t) for t in sys.argv[4:]]
clip = f"{W}/raw_clips/2026-11-19_{hh}.mp4"
ims = []
with tempfile.TemporaryDirectory() as td:
    for i, t in enumerate(ts):
        p = f"{td}/r{i}.jpg"
        s = max(0, t - 0.5)
        subprocess.run(["/usr/local/bin/python3", "-I", f"{W}/scripts/sheet.py", clip, p, "--start", f"{s:.2f}",
                        "--end", f"{s + 1.0:.2f}", "--fps", "15", "--cols", "15", "--width", "130", "--crop", crop],
                       check=True, capture_output=True)
        ims.append(Image.open(p).copy())
w = max(i.width for i in ims); h = sum(i.height for i in ims)
sheet = Image.new("RGB", (w, h), "black"); y = 0
for i in ims:
    sheet.paste(i, (0, y)); y += i.height
sheet.save(out, quality=85); print(out, len(ims), "rows")
