#!/usr/bin/env python3
"""sil.py in.png out.png [--max-h 1300] [--flip] [--t0 0.55 --t1 0.80]: a dark figure on a white page -> RGBA mask.

Alpha from darkness (lightness below t0 = solid, above t1 = page), keeps the largest connected figure (plus any
big piece touching it), fills pinholes, trims to the figure. The colour is irrelevant: the desk paints it as a
silhouette (ink) with an echo, so only the alpha matters.
"""
import argparse
import numpy as np
from PIL import Image
from scipy import ndimage as ndi

ap = argparse.ArgumentParser()
ap.add_argument("src"); ap.add_argument("dst")
ap.add_argument("--t0", type=float, default=0.55); ap.add_argument("--t1", type=float, default=0.80)
ap.add_argument("--max-h", type=int, default=1300); ap.add_argument("--flip", action="store_true")
a = ap.parse_args()
img = np.asarray(Image.open(a.src).convert("RGB"), float) / 255
L = img.max(axis=2) * 0.5 + img.mean(axis=2) * 0.5
alpha = 1 - np.clip((L - a.t0) / (a.t1 - a.t0), 0, 1)
hard = alpha > 0.5
lab, n = ndi.label(hard)
sizes = ndi.sum(hard, lab, range(1, n + 1))
big = int(np.argmax(sizes)) + 1
keep = np.isin(lab, [i + 1 for i in np.flatnonzero(sizes >= sizes.max() * 0.02)])
keep = ndi.binary_dilation(keep, iterations=3)
holes = ndi.binary_fill_holes(hard & keep) & ~hard
hl, hn = ndi.label(holes)
if hn:
    hs = ndi.sum(holes, hl, range(1, hn + 1))
    small = np.isin(hl, 1 + np.flatnonzero(hs < hard.size * 0.0003))
    alpha = np.where(small, 1.0, alpha)
alpha = alpha * keep
ys, xs = np.nonzero(alpha > 0.02)
pad = 6
y0, y1 = max(ys.min() - pad, 0), min(ys.max() + pad + 1, img.shape[0])
x0, x1 = max(xs.min() - pad, 0), min(xs.max() + pad + 1, img.shape[1])
out = np.zeros((y1 - y0, x1 - x0, 4))
out[..., :3] = (10 / 255, 6 / 255, 18 / 255)
out[..., 3] = alpha[y0:y1, x0:x1]
im = Image.fromarray((out * 255 + 0.5).astype(np.uint8), "RGBA")
if a.flip:
    im = im.transpose(Image.FLIP_LEFT_RIGHT)
if im.height > a.max_h:
    im = im.resize((round(im.width * a.max_h / im.height), a.max_h), Image.LANCZOS)
im.save(a.dst, optimize=True)
print(f"{a.dst}: {im.width}x{im.height}, figure {100 * (alpha > 0.5).mean():.1f}% of the page")
