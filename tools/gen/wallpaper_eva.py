#!/usr/bin/env python3
"""wallpaper.py RAW NAME [--portrait] [--keep]: generated poster -> the eva palette.

Maps the picture onto the theme: neutral tones black -> deep violet -> lilac bone, green inks onto an acid green
ramp, purple / magenta inks onto the Unit-01 purple ramp, warm (red / orange / yellow) inks onto NERV orange.
Writes final/wp/NAME.webp (preview) and final/wp/png/NAME.png (3440x1440, or 1080x1920 with --portrait).
"""
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageFilter

HERE = Path(__file__).resolve().parent
src, name = sys.argv[1], sys.argv[2]
keep, portrait = "--keep" in sys.argv, "--portrait" in sys.argv
W, H = (1080, 1920) if portrait else (3440, 1440)

im = Image.open(src).convert("RGB")
target = W / H
w, h = im.size
if w / h > target:
    nw = round(h * target)
    im = im.crop(((w - nw) // 2, 0, (w - nw) // 2 + nw, h))
else:
    nh = round(w / target)
    im = im.crop((0, (h - nh) // 2, w, (h - nh) // 2 + nh))


def ramp(L, stops):
    col = lambda hx: np.array([int(hx[i:i + 2], 16) for i in (1, 3, 5)], float) / 255
    xs, cs = [s[0] for s in stops], np.stack([col(s[1]) for s in stops])
    return np.stack([np.interp(L, xs, cs[:, c]) for c in range(3)], axis=-1)


if not keep:
    x = np.asarray(im).astype(float) / 255
    r, g, b = x[..., 0], x[..., 1], x[..., 2]
    L = x @ np.array([0.2126, 0.7152, 0.0722])
    mx, mn = x.max(axis=2), x.min(axis=2)
    sat = np.where(mx > 0.02, (mx - mn) / np.maximum(mx, 1e-3), 0)
    # how much a pixel belongs to each ink (soft masks, by hue family)
    green = np.clip((g - np.maximum(r, b)) * 3.0, 0, 1)
    purple = np.clip((np.minimum(r, b) * 0.5 + b * 0.5 - g) * 2.6, 0, 1) * np.clip((b - g) * 4, 0, 1)
    warm = np.clip((r - b) * 2.2, 0, 1) * np.clip((r - g) * 1.6, 0, 1)
    tot = np.clip(green + purple + warm, 0, 1)
    k = np.where(tot > 0, 1 / np.maximum(green + purple + warm, 1e-6), 0)
    green, purple, warm = green * k * tot, purple * k * tot, warm * k * tot
    neutral = ramp(L, [(0.00, "#050309"), (0.14, "#0a0612"), (0.36, "#2a1a48"), (0.62, "#9a90b8"), (0.85, "#d9d2ea"), (1.00, "#ebe6f7")])
    greens = ramp(L, [(0.00, "#0a1a06"), (0.22, "#1f5a12"), (0.45, "#4fbf25"), (0.70, "#7dff3f"), (1.00, "#d8ffb0")])
    purples = ramp(L, [(0.00, "#120a22"), (0.22, "#2b1450"), (0.45, "#6a2fb8"), (0.70, "#9a63e8"), (1.00, "#dcc8ff")])
    warms = ramp(L, [(0.00, "#1a0a06"), (0.25, "#7a2a10"), (0.50, "#ff5a1f"), (0.75, "#ff9a55"), (1.00, "#ffd9b8")])
    n = (1 - tot)[..., None]
    out = neutral * n + greens * green[..., None] + purples * purple[..., None] + warms * warm[..., None]
    im = Image.fromarray((np.clip(out, 0, 1) * 255 + 0.5).astype(np.uint8))

(HERE / "final" / "wp" / "png").mkdir(parents=True, exist_ok=True)
big = im.resize((W, H), Image.LANCZOS).filter(ImageFilter.UnsharpMask(radius=2, percent=60, threshold=2))
big.save(HERE / "final" / "wp" / "png" / f"{name}.png", optimize=True)
im.resize((W // 2, H // 2), Image.LANCZOS).save(HERE / "final" / "wp" / f"{name}.webp", "WEBP", quality=80, method=6)
print(f"{name}: ok {W}x{H}")
