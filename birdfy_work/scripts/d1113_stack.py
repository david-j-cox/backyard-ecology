"""Stack images vertically: d1113_stack.py OUT IN1 IN2 ..."""
import sys
from PIL import Image
ims = [Image.open(f) for f in sys.argv[2:]]
W = max(i.width for i in ims); H = sum(i.height + 6 for i in ims)
o = Image.new("RGB", (W, H), "white"); y = 0
for i in ims: o.paste(i, (0, y)); y += i.height + 6
o.save(sys.argv[1], quality=85); print(sys.argv[1], o.size)
