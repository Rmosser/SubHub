# redact.py <png> x0,y0,x1,y1 [...]   (pixel coords in the window capture) -> fill black in place
import sys
from PIL import Image, ImageDraw
p=sys.argv[1]; im=Image.open(p).convert("RGBA"); d=ImageDraw.Draw(im)
for r in sys.argv[2:]:
    x0,y0,x1,y1=map(int,r.split(",")); d.rectangle([x0,y0,x1,y1],fill=(0,0,0,255))
im.save(p); print("redacted",p,len(sys.argv)-2)
