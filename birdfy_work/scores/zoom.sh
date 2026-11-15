#!/bin/zsh
# usage: zoom.sh CLIPID CROP "s e" "s e" ...  -> sheets/2026-11-05/CLIPID_zall.jpg (stacked 15 fps windows)
C=$1; CR=$2; shift 2; i=0; fl=()
for w in "$@"; do set -- ${=w}; i=$((i+1)); /usr/local/bin/python3 -I scripts/sheet.py raw_clips/2026-11-05_$C.mp4 sheets/2026-11-05/${C}_z$i.jpg --start $1 --end $2 --fps 15 --cols 12 --width 200 --crop $CR >/dev/null; fl+=(sheets/2026-11-05/${C}_z$i.jpg); done
/usr/local/bin/python3 -I -c "
import sys
from PIL import Image
ims=[Image.open(f) for f in sys.argv[2:]]
W=max(i.width for i in ims);H=sum(i.height for i in ims)+4*len(ims)
s=Image.new('RGB',(W,H),'white');y=0
for i in ims: s.paste(i,(0,y)); y+=i.height+4
s.save(sys.argv[1],quality=85); print(sys.argv[1], s.size)" sheets/2026-11-05/${C}_zall.jpg $fl
