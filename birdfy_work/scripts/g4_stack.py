"""g4_stack.py OUT.jpg IN1.jpg IN2.jpg ... -> stack sheets vertically (for viewing several zooms at once)"""
import sys
from PIL import Image
ims=[Image.open(p) for p in sys.argv[2:]]
W=max(i.width for i in ims); H=sum(i.height for i in ims)
o=Image.new("RGB",(W,H),"black"); y=0
for i in ims: o.paste(i,(0,y)); y+=i.height
o.save(sys.argv[1],quality=85); print(sys.argv[1],W,H)
