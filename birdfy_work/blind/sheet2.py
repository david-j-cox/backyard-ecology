"""Like scripts/sheet.py but draws the true x=1152 centre line (cyan, full height, dashed)
and the +/-5% band (x=1037, 1267, magenta ticks) in crop-aware positions.
usage: sheet2.py CLIP OUT --start S --end E --fps F --cols C --width W [--crop x,y,w,h]"""
import argparse, subprocess, tempfile, glob
from PIL import Image, ImageDraw, ImageFont
ap = argparse.ArgumentParser()
ap.add_argument("clip"); ap.add_argument("out")
ap.add_argument("--start", type=float, default=0); ap.add_argument("--end", type=float, default=None)
ap.add_argument("--fps", type=float, default=4); ap.add_argument("--cols", type=int, default=8)
ap.add_argument("--width", type=int, default=360); ap.add_argument("--crop", default=None)
a = ap.parse_args()
dur = float(subprocess.run(["ffprobe","-v","error","-show_entries","format=duration","-of","csv=p=0",a.clip],capture_output=True,text=True).stdout)
end = min(a.end if a.end is not None else dur, dur)
cx, cw = 0, 2304
with tempfile.TemporaryDirectory() as td:
    vf = f"fps={a.fps}"
    if a.crop:
        x,y,w,h = a.crop.split(","); vf = f"crop={w}:{h}:{x}:{y},"+vf; cx, cw = int(x), int(w)
    vf += f",scale={a.width}:-2"
    subprocess.run(["ffmpeg","-v","error","-ss",str(a.start),"-to",str(end),"-i",a.clip,"-vf",vf,f"{td}/f%04d.jpg"],check=True)
    ims = [Image.open(f) for f in sorted(glob.glob(f"{td}/f*.jpg"))]
    w, h = ims[0].size; s = w / cw
    rows = -(-len(ims)//a.cols)
    sheet = Image.new("RGB",(a.cols*w, rows*h),"black"); d = ImageDraw.Draw(sheet)
    font = ImageFont.load_default(size=max(12, w//16))
    for i, im in enumerate(ims):
        X, Y = (i%a.cols)*w, (i//a.cols)*h
        sheet.paste(im,(X,Y))
        lx = X + (1152-cx)*s
        for yy in range(Y, Y+h, 10):
            d.line([lx, yy, lx, yy+5], fill="cyan")
        for bx in (1037, 1267):
            px = X + (bx-cx)*s
            if X <= px < X+w: d.line([px, Y+h-15, px, Y+h], fill="magenta", width=2)
        d.line([X+w-1, Y, X+w-1, Y+h], fill="black")
        t = a.start + i/a.fps
        d.rectangle([X,Y,X+w//4,Y+w//13],fill="black"); d.text((X+3,Y+1),f"{t:.2f}s",fill="yellow",font=font)
    sheet.save(a.out, quality=85)
    print(f"{a.out}: {len(ims)} frames {a.start:.2f}-{end:.2f}s of {dur:.2f}s")
