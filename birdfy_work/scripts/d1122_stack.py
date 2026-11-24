"""usage: python3 -I d1122_stack.py OUT.jpg IN1.jpg IN2.jpg ... -> stack sheets vertically with a 6 px gap"""
import sys
from PIL import Image
ims = [Image.open(p) for p in sys.argv[2:]]
w = max(i.width for i in ims); h = sum(i.height for i in ims) + 6 * (len(ims) - 1)
out = Image.new("RGB", (w, h), (255, 255, 0)); y = 0
for i in ims:
    out.paste(i, (0, y)); y += i.height + 6
out.save(sys.argv[1], quality=85); print(sys.argv[1], out.size)
