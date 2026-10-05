#!/usr/bin/env python3
"""wallpaper.py RAW NAME [--keep]: poster wallpaper -> desk palette.

Crops a printed poster margin if the generator added one, maps the three inks onto the desk palette
(black -> ink, red -> wine-crimson, cream -> bone) unless --keep, and writes final/wp/NAME.webp (1720x720,
for the boards) and final/wp/png/NAME.png (3440x1440, for the ultrawide).
"""
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageFilter

HERE = Path(__file__).resolve().parent
src, name = sys.argv[1], sys.argv[2]
keep = "--keep" in sys.argv

im = Image.open(src).convert("RGB")
a = np.asarray(im).astype(float) / 255
h, w, _ = a.shape

# printed margin: a paper-coloured band on all four sides around the artwork
edge = np.concatenate([a[:6].reshape(-1, 3), a[-6:].reshape(-1, 3), a[:, :6].reshape(-1, 3), a[:, -6:].reshape(-1, 3)])
paper = np.median(edge, axis=0)
ink = np.linalg.norm(a - paper, axis=2) > 0.12


def margin(rows, limit):
    for i, frac in enumerate(rows):
        if frac > 0.6:
            return i
    return limit


top = margin(ink.mean(axis=1), h)
bot = margin(ink.mean(axis=1)[::-1], h)
lef = margin(ink.mean(axis=0), w)
rig = margin(ink.mean(axis=0)[::-1], w)
if "--sides" in sys.argv and paper.mean() > 0.75:
    # crop whichever sides carry a printed band, even if not all four do
    cut = [m if 6 <= m <= 0.12 * d else 0 for m, d in ((top, h), (bot, h), (lef, w), (rig, w))]
    top, bot, lef, rig = [c + 4 if c else 0 for c in cut]
    im = im.crop((lef, top, w - rig, h - bot))
    print(f"{name}: cropped sides t{top} b{bot} l{lef} r{rig}")
elif paper.mean() > 0.75 and all(6 <= m <= 0.12 * d for m, d in ((top, h), (bot, h), (lef, w), (rig, w))):
    pad = 4
    im = im.crop((lef + pad, top + pad, w - rig - pad, h - bot - pad))
    print(f"{name}: cropped margin t{top} b{bot} l{lef} r{rig}")

# fill the 21:9 frame (centre crop)
target = 3440 / 1440
w, h = im.size
if w / h > target:
    nw = round(h * target)
    im = im.crop(((w - nw) // 2, 0, (w - nw) // 2 + nw, h))
else:
    nh = round(w / target)
    im = im.crop((0, (h - nh) // 2, w, (h - nh) // 2 + nh))

if not keep:
    x = np.asarray(im).astype(float) / 255
    L = x @ np.array([0.2126, 0.7152, 0.0722])
    red = np.clip((x[..., 0] - np.maximum(x[..., 1], x[..., 2])) * 2.2, 0, 1)    # how "inked red" a pixel is
    stops = [(0.00, "#0c0608"), (0.10, "#14080b"), (0.55, "#2a0f14"), (0.80, "#cfc3ae"), (1.00, "#efe4cf")]
    if "--dark" in sys.argv:
        # night palette: near-black ground, dimmed bone linework
        stops = [(0.00, "#070304"), (0.14, "#0c0608"), (0.36, "#2e2224"), (0.62, "#b4a893"), (0.85, "#e2d6c0"), (1.00, "#efe4cf")]
    col = lambda hx: np.array([int(hx[i:i + 2], 16) for i in (1, 3, 5)], float) / 255
    xs, cs = [s[0] for s in stops], np.stack([col(s[1]) for s in stops])
    neutral = np.stack([np.interp(L, xs, cs[:, c]) for c in range(3)], axis=-1)
    # red ink keeps its own lightness ramp: shadowed red -> wine, full red -> crimson, highlights -> warm coral
    rstops = [(0.00, "#2a0710"), (0.18, "#8e1b33"), (0.32, "#b3192f"), (0.55, "#e0503c"), (1.00, "#f2c9b4")]
    if "--dark" in sys.argv:
        rstops = [(0.00, "#1a0509"), (0.18, "#4a0c1a"), (0.32, "#7a1428"), (0.55, "#a8253a"), (1.00, "#d9a08f")]
        if (red > 0.3).mean() > 0.12:
            # big red fields read as wine at night; only small accents keep their crimson
            red = red * 0.55
    rxs, rcs = [s[0] for s in rstops], np.stack([col(s[1]) for s in rstops])
    reds = np.stack([np.interp(L, rxs, rcs[:, c]) for c in range(3)], axis=-1)
    out = neutral * (1 - red[..., None]) + reds * red[..., None]
    im = Image.fromarray((np.clip(out, 0, 1) * 255 + 0.5).astype(np.uint8))

(HERE / "final" / "wp" / "png").mkdir(parents=True, exist_ok=True)
big = im.resize((3440, 1440), Image.LANCZOS).filter(ImageFilter.UnsharpMask(radius=2, percent=60, threshold=2))
big.save(HERE / "final" / "wp" / "png" / f"{name}.png", optimize=True)
im.resize((1720, 720), Image.LANCZOS).save(HERE / "final" / "wp" / f"{name}.webp", "WEBP", quality=80, method=6)
print(f"{name}: ok")
