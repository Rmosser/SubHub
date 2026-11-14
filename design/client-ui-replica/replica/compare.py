"""Render a replica page with headless Chrome at 402x874 @1.5x and compare with the reference capture.
Usage: ./.venv/bin/python design/client-ui-replica/replica/compare.py shadowrocket-config-edit
Writes replica/out/<name>-render.png, -overlay.png (50% blend), -diff.png (abs diff x4), and prints scores."""
import json, pathlib, subprocess, sys, re
from PIL import Image, ImageChops, ImageStat, ImageFilter
ROOT = pathlib.Path(__file__).resolve().parent
name = sys.argv[1]
out = ROOT / "out"; out.mkdir(exist_ok=True)
data = (ROOT / f"data/{name}.js").read_text()
ref_rel = json.loads(re.sub(r"^window.REPLICA=|;\s*$", "", data.strip()))["reference"]
ref = Image.open((ROOT / ref_rel).resolve()).convert("RGB").crop((8, 38, 611, 1349))
render = out / f"{name}-render.png"
chrome = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
subprocess.run([chrome, "--headless=new", "--disable-gpu", "--hide-scrollbars", "--force-device-scale-factor=1.5",
                "--window-size=402,874", f"--screenshot={render}", (ROOT / f"{name}.html").as_uri()],
               check=True, capture_output=True)
img = Image.open(render).convert("RGB")
if img.size != ref.size:
    img = img.resize(ref.size, Image.LANCZOS)
    img.save(render)
Image.blend(ref, img, 0.5).save(out / f"{name}-overlay.png")
diff = ImageChops.difference(ref, img)
diff.point(lambda v: min(255, v * 4)).save(out / f"{name}-diff.png")
side = Image.new("RGB", (ref.width * 3 + 20, ref.height), "white")
side.paste(ref, (0, 0)); side.paste(img, (ref.width + 10, 0)); side.paste(diff.point(lambda v: min(255, v * 4)), (ref.width * 2 + 20, 0))
side.save(out / f"{name}-side.png")
# 镜像截图是视频流，文字边缘比 Chrome 渲染软；两边各做 1.2 px 高斯模糊后再比一次，排除抗锯齿差异，只看几何与颜色
diff_blur = ImageChops.difference(ref.filter(ImageFilter.GaussianBlur(1.2)), img.filter(ImageFilter.GaussianBlur(1.2)))
def score(box=None, src=None):
    src = src or diff
    d = src.crop(box) if box else src
    g = d.convert("L")
    st = ImageStat.Stat(g)
    hist = g.histogram(); tot = sum(hist)
    within = sum(hist[:16]) / tot
    return round(st.mean[0], 2), round(within * 100, 1)
S = 1.5
full = score()
body = score((0, int(115 * S), ref.width, int(790 * S)))   # list area, excludes status/nav/tab bar
bl = score((0, int(115 * S), ref.width, int(790 * S)), diff_blur)
print(json.dumps({"name": name, "mean_abs_diff_full": full[0], "pct_px_within_16_full": full[1],
                  "mean_abs_diff_list": body[0], "pct_px_within_16_list": body[1],
                  "list_blur1.2_mean": bl[0], "list_blur1.2_within16": bl[1]}, ensure_ascii=False))
