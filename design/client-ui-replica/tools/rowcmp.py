"""rowcmp.py <ref.png> <render.png> x_pt  — 竖向色段对比 + 文字墨迹逐行对比"""
import sys
from PIL import Image
S=1.5
ref=Image.open(sys.argv[1]).convert('RGB').crop((8,38,611,1349))
rep=Image.open(sys.argv[2]).convert('RGB')
X=float(sys.argv[3]) if len(sys.argv)>3 else 200
def bands(im,x,tol=5):
    out=[];prev=None;start=0
    for yy in range(im.height):
        c=im.getpixel((int(x*S),yy))
        if prev is not None and sum(abs(a-b) for a,b in zip(c,prev))>tol:
            out.append((round(start/S,1),round(yy/S,1),prev));start=yy
        prev=c
    out.append((round(start/S,1),round(yy/S,1),prev))
    return [o for o in out if o[1]-o[0]>=0.6]
a=bands(ref,X);b=bands(rep,X)
print('REF');[print('  ',o) for o in a if o[1]-o[0]>=1]
print('REP');[print('  ',o) for o in b if o[1]-o[0]>=1]
def textlines(im,x0,x1):
    rows=[]
    for yy in range(im.height):
        dark=any(sum(im.getpixel((x,yy)))<450 for x in range(int(x0*S),int(x1*S),1))
        rows.append(dark)
    out=[];s=None
    for i,d in enumerate(rows):
        if d and s is None: s=i
        if not d and s is not None: out.append((round(s/S,1),round(i/S,1)));s=None
    return [o for o in out if o[1]-o[0]>2]
ta=textlines(ref,30,200);tb=textlines(rep,30,200)
print('TEXT ref',ta);print('TEXT rep',tb)
