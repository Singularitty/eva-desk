#!/usr/bin/env python3
"""rig.py figure.png OUTDIR [--scale 2]: a frontal figure with both arms out (RGBA, from sil.py) -> herald rig.

Finds the shoulder band automatically: the rows where the figure is much wider than its torso. The arms are
the band pixels outboard of the shoulder joints, cut along a circle round each joint so the root stays
concentric as it rotates (see herald_frames.py). Writes body.png, arm_l.png, arm_r.png (potrace-cleaned at
--scale) and rig.json for vibe-desk's HeraldRig.
"""
import json
import math
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np
from PIL import Image

src, out = Path(sys.argv[1]), Path(sys.argv[2])
scale = int(sys.argv[sys.argv.index("--scale") + 1]) if "--scale" in sys.argv else 2
out.mkdir(parents=True, exist_ok=True)
INK = (10, 6, 18)

a = np.asarray(Image.open(src).convert("RGBA"))[..., 3]
H, W = a.shape
solid = a > 128
rows = np.flatnonzero(solid.any(axis=1))
head, feet = int(rows.min()), int(rows.max())
cols = np.flatnonzero(solid.any(axis=0))
cx = int((cols.min() + cols.max()) / 2)
# width profile: the torso width is the typical width of the lower half; the band is where it is much wider
left = np.array([np.flatnonzero(r).min() if r.any() else W for r in solid])
right = np.array([np.flatnonzero(r).max() if r.any() else -1 for r in solid])
width = np.where(right >= left, right - left + 1, 0)
lower = width[(head + feet) // 2: feet]
torso = float(np.median(lower[lower > 0]))
band = np.flatnonzero(width > torso * 2.2)          # arms out: far wider than any shoulder pylon
band = band[(band > head) & (band < (head + feet) // 2 + (feet - head) * 0.1)]
# the band may include shoulder pylons / head: keep the longest run of rows
runs, start = [], band[0]
for i in range(1, len(band) + 1):
    if i == len(band) or band[i] != band[i - 1] + 1:
        runs.append((start, band[i - 1]))
        if i < len(band):
            start = band[i]
TOP, BOT = max(runs, key=lambda r: r[1] - r[0])
BOT += 1
# the torso edges inside the band: where the horizontal run through the band centre leaves the trunk
mid = (TOP + BOT) // 2
# joint disc radius ~ a quarter of the band height; the torso edges are the trunk just under the armpits
R = max(12, int((BOT - TOP) * 0.28))
def central_run(y):
    """Extents of the solid run through the figure's centre line on row y (ignores hanging side parts)."""
    xs = np.flatnonzero(solid[y])
    br = np.flatnonzero(np.diff(xs) > 1)
    starts, ends = np.r_[xs[0], xs[br + 1]], np.r_[xs[br], xs[-1]]
    i = np.argmin(np.abs((starts + ends) / 2 - cx))
    return starts[i], ends[i]


runs_under = [central_run(y) for y in range(BOT + 6, min(BOT + 30, feet))]
tl, tr = int(np.median([r[0] for r in runs_under])), int(np.median([r[1] for r in runs_under]))
PIV_L, PIV_R = (tl + R // 3, mid), (tr - R // 3, mid)
yy, xx = np.mgrid[0:H, 0:W]
d_l = np.hypot(xx - PIV_L[0], yy - PIV_L[1])
d_r = np.hypot(xx - PIV_R[0], yy - PIV_R[1])
band_l = (yy >= TOP - 4) & (yy < BOT + 4) & (xx < PIV_L[0])
band_r = (yy >= TOP - 4) & (yy < BOT + 4) & (xx > PIV_R[0])
m_l = band_l & (d_l > R - 2)
m_r = band_r & (d_r > R - 2)
body = np.where(m_l | m_r, 0, a)
body = np.maximum(body, ((d_l <= R) | (d_r <= R)).astype(np.uint8) * 255 * solid[mid, :][None, :].any())


def theta(mask, piv, side):
    ys, xs = np.nonzero(mask & solid)
    i = np.argmin(xs) if side < 0 else np.argmax(xs)
    return 90 + math.degrees(math.atan2(piv[1] - ys[i], abs(xs[i] - piv[0])))


def vectorize(alpha, name):
    h, w = alpha.shape
    with tempfile.TemporaryDirectory() as td:
        pbm, svg, png = Path(td) / "m.pbm", Path(td) / "m.svg", Path(td) / "m.png"
        bits = np.packbits((alpha >= 128).astype(np.uint8), axis=1)
        pbm.write_bytes(f"P4\n{w} {h}\n".encode() + bits.tobytes())
        subprocess.run(["potrace", "-s", "--turdsize", "6", "--alphamax", "1.0", "--opttolerance", "0.2", "-o", str(svg), str(pbm)], check=True)
        subprocess.run(["rsvg-convert", "-w", str(w * scale), "-h", str(h * scale), "-o", str(png), str(svg)], check=True)
        cov = np.asarray(Image.open(png).convert("RGBA"))[..., 3]
    img = Image.new("RGBA", cov.shape[::-1], INK + (0,))
    img.putalpha(Image.fromarray(cov))
    img.save(out / name, optimize=True)


vectorize(body.astype(np.uint8), "body.png")
vectorize(np.where(m_l, a, 0).astype(np.uint8), "arm_l.png")
vectorize(np.where(m_r, a, 0).astype(np.uint8), "arm_r.png")
rig = {"w": int(W * scale), "h": int(H * scale), "pivot_l": [int(PIV_L[0] * scale), int(PIV_L[1] * scale)], "pivot_r": [int(PIV_R[0] * scale), int(PIV_R[1] * scale)],
       "theta0_l": theta(m_l, PIV_L, -1), "theta0_r": theta(m_r, PIV_R, 1), "head": int(head * scale), "feet": int(feet * scale),
       "cx": int(cx * scale), "theta_from": 15, "theta_to": 155}
(out / "rig.json").write_text(json.dumps(rig, indent=1))
print(f"band rows {TOP}-{BOT}, torso {torso:.0f}px, R {R}, pivots {PIV_L} {PIV_R}, theta0 {rig['theta0_l']:.0f}/{rig['theta0_r']:.0f}")
