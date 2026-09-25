"""Process the Doubao-generated dragon logo into repo assets.

Steps: paint out watermark -> background to alpha (un-mix AA edges) ->
crop to bbox -> square pad -> 512 master / 192 splash / multi-size ico.
"""
import io
import sys
from pathlib import Path

from PIL import Image

SRC = Path(sys.argv[1])  # 源图路径由参数传入 (QQ 缓存路径不保证长期存在)
OUT = Path(__file__).resolve().parents[2] / "assets"

img = Image.open(SRC).convert("RGB")
w, h = img.size
print("src", w, h)
px = img.load()

# background = median of corner patches
corners = []
for cx, cy in [(4, 4), (w - 5, 4), (4, h // 2), (w // 2, 4)]:
    for dx in range(3):
        for dy in range(3):
            corners.append(px[cx + dx, cy + dy])
corners.sort(key=lambda c: sum(c))
bg = corners[len(corners) // 2]
print("bg", bg)

# paint out watermark block (bottom-right)
for y in range(int(h * 0.90), h):
    for x in range(int(w * 0.76), w):
        px[x, y] = bg

# alpha from distance to bg, with un-mixing against the dominant fg (logo red)
fg_pixels = [p for p in img.getdata() if sum((p[i] - bg[i]) ** 2 for i in range(3)) > 150 ** 2 * 3 // 3]
fg_pixels.sort(key=lambda c: (c[0], c[1], c[2]))
fg = fg_pixels[len(fg_pixels) // 2]
print("fg", fg, "n_fg", len(fg_pixels))

T0, T1 = 22.0, 110.0
rgba = Image.new("RGBA", (w, h))
rpx = rgba.load()
minx, miny, maxx, maxy = w, h, -1, -1
for y in range(h):
    for x in range(w):
        r, g, b = px[x, y]
        d = (sum((c - bg[i]) ** 2 for i, c in enumerate((r, g, b)))) ** 0.5
        a = 0.0 if d <= T0 else (1.0 if d >= T1 else (d - T0) / (T1 - T0))
        if a > 0.03:
            minx, miny = min(minx, x), min(miny, y)
            maxx, maxy = max(maxx, x), max(maxy, y)
        if a > 0:
            ur, ug, ub = fg
            if a < 1.0:
                ur = min(255, max(0, int((r - bg[0] * (1 - a)) / a)))
                ug = min(255, max(0, int((g - bg[1] * (1 - a)) / a)))
                ub = min(255, max(0, int((b - bg[2] * (1 - a)) / a)))
            rpx[x, y] = (ur, ug, ub, int(round(a * 255)))
        else:
            rpx[x, y] = (0, 0, 0, 0)
print("bbox", minx, miny, maxx, maxy)

crop = rgba.crop((minx, miny, maxx + 1, maxy + 1))
cw, ch = crop.size
side = int(max(cw, ch) * 1.06)
sq = Image.new("RGBA", (side, side), (0, 0, 0, 0))
sq.paste(crop, ((side - cw) // 2, (side - ch) // 2), crop)

master = sq.resize((512, 512), Image.LANCZOS)
master.save(OUT / "logo-dragon.png")
splash = sq.resize((192, 192), Image.LANCZOS)
splash.save(OUT / "logo-dragon-192.png")
sizes = [16, 24, 32, 48, 64, 128, 256]
master.save(OUT / "app_icon.ico", sizes=[(s, s) for s in sizes])
print("assets written:", [p.name for p in sorted(OUT.glob("logo-dragon*"))] + ["app_icon.ico"])
print("splash b64 bytes ~", len(io.BytesIO().__class__(b"").getvalue()) or "")
import base64
buf = io.BytesIO()
splash.save(buf, format="PNG", optimize=True)
print("splash png bytes", buf.tell(), "b64 len", len(base64.b64encode(buf.getvalue())))
