"""Sheet of chosen single frames: d1113_pick.py HHMMSS OUT_TAG crop width cols t1 t2 ..."""
import sys, subprocess, tempfile, os
from PIL import Image, ImageDraw, ImageFont
W = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
clip, tag, crop, wd, cols = sys.argv[1:6]; ts = [float(t) for t in sys.argv[6:]]
wd = int(wd); cols = int(cols); x, y, w, h = [int(v) for v in crop.split(",")]
src = f"{W}/raw_clips/2026-11-13_{clip}.mp4"; ims = []
with tempfile.TemporaryDirectory(dir=f"{W}/sheets/2026-11-13") as td:
    for i, t in enumerate(ts):
        o = f"{td}/p{i}.jpg"
        subprocess.run(["ffmpeg","-v","error","-ss",str(t),"-i",src,"-frames:v","1","-vf",f"crop={w}:{h}:{x}:{y},scale={wd}:-2",o],check=True)
        ims.append(Image.open(o).copy())
fw, fh = ims[0].size; rows = -(-len(ims)//cols)
sh = Image.new("RGB",(cols*fw, rows*fh)); d = ImageDraw.Draw(sh); font = ImageFont.load_default(size=max(14, fw//18))
cx = round((1152-x)/w*fw) if x <= 1152 <= x+w else None
for i,(im,t) in enumerate(zip(ims,ts)):
    px, py = (i%cols)*fw, (i//cols)*fh; sh.paste(im,(px,py))
    d.rectangle([px,py,px+fw//5,py+fw//14],fill="black"); d.text((px+3,py+1),f"{t:.2f}s",fill="yellow",font=font)
    if cx is not None: d.line([px+cx,py,px+cx,py+fh],fill="cyan",width=1)
out = f"{W}/sheets/2026-11-13/{clip}_p_{tag}.jpg"; sh.save(out, quality=85); print(out, len(ims))
