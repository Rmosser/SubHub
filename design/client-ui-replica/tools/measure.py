"""Measure iOS list geometry from a mirror capture. 1.5 px/pt, screen origin (8,38)."""
import sys
from PIL import Image
S=1.5; OX=8; OY=38
def load(p): return Image.open(p).convert('RGB')
def pt(v,o=0): return round((v-o)/S,1)
def hexc(c): return '#%02X%02X%02X'%c
def runs(im,x,y0=0,y1=None,tol=6):
    H=im.size[1]; y1=y1 or H
    out=[];start=y0;cur=im.getpixel((x,y0))
    for y in range(y0+1,y1):
        c=im.getpixel((x,y))
        if max(abs(a-b) for a,b in zip(c,cur))>tol:
            out.append((start,y-1,cur)); start=y; cur=c
    out.append((start,y1-1,cur)); return out
def hruns(im,y,tol=6):
    W=im.size[0];out=[];start=0;cur=im.getpixel((0,y))
    for x in range(1,W):
        c=im.getpixel((x,y))
        if max(abs(a-b) for a,b in zip(c,cur))>tol:
            out.append((start,x-1,cur)); start=x; cur=c
    out.append((start,W-1,cur)); return out
def radius(im,card_top,card_left,bg,tol=6):
    """walk down from card top at card_left column until pixel != bg"""
    for dy in range(0,60):
        c=im.getpixel((card_left,card_top+dy))
        if max(abs(a-b) for a,b in zip(c,bg))>tol: return dy
    return None
if __name__=='__main__':
    p=sys.argv[1]; xs=[int(a) for a in sys.argv[2].split(',')] if len(sys.argv)>2 else [OX+int(30*S)]
    im=load(p)
    for x in xs:
        print('== column x=%d (%.1fpt)'%(x,pt(x,OX)))
        for a,b,c in runs(im,x,OY):
            h=b-a+1
            if h>=2: print('  y %4d-%4d  %5.1fpt..%5.1fpt  h=%5.1fpt  %s'%(a,b,pt(a,OY),pt(b+1,OY),h/S,hexc(c)))

def ink(im,box,bg,thr=60):
    """bbox (px) of pixels differing from bg by > thr inside box=(x0,y0,x1,y1)"""
    x0,y0,x1,y1=box; xs=[];ys=[]
    px=im.load()
    for y in range(y0,y1):
        for x in range(x0,x1):
            c=px[x,y]
            if sum(abs(a-b) for a,b in zip(c,bg))>thr: xs.append(x); ys.append(y)
    if not xs: return None
    return (min(xs),min(ys),max(xs)+1,max(ys)+1)
def darkest(im,box):
    x0,y0,x1,y1=box; px=im.load(); best=None
    for y in range(y0,y1):
        for x in range(x0,x1):
            c=px[x,y]
            if best is None or sum(c)<sum(best): best=c
    return best
def seps(im,x,y0,y1,cell,tol=3):
    """y px where colour at x differs from cell colour by >tol for 1-3px runs"""
    out=[];y=y0
    while y<y1:
        c=im.getpixel((x,y))
        if max(abs(a-b) for a,b in zip(c,cell))>tol:
            s=y
            while y<y1 and max(abs(a-b) for a,b in zip(im.getpixel((x,y)),cell))>tol: y+=1
            out.append((s,y-1))
        y+=1
    return out
