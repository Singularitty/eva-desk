#!/usr/bin/env python3
"""herald_frames.py [N]: smooth arm sweep for the black herald silhouette.

Takes the aligned arms-out frame (final/png/herald2.png), cuts each arm off at the shoulder and rotates
it about the shoulder joint from hanging (15 deg) to a raised V (155 deg); the body stays identical in
every frame. Writes final/png/herald_fNN.png and one sprite sheet final/herald_sprite.webp (frames left
to right, 900px tall) plus final/herald_sprite.json.
"""
import json
import math
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

HERE = Path(__file__).resolve().parent
N = int(sys.argv[1]) if len(sys.argv) > 1 else 15
INK = (12, 6, 8)

a = np.asarray(Image.open(HERE / "final/png/herald2.png"))[..., 3]
H, W = a.shape
TOP, BOT = 296, 428                                   # arm band rows, from the row scan of the arms-out frame
PIV_L, PIV_R, R = (380, 390), (628, 390), 36          # shoulder joints; R = half the arm thickness at the root
yy, xx = np.mgrid[0:H, 0:W]
d_l = np.hypot(xx - PIV_L[0], yy - PIV_L[1])
d_r = np.hypot(xx - PIV_R[0], yy - PIV_R[1])
# arm = band pixels outboard of the joint, cut along a circle round the pivot so the root stays concentric
# with the body's joint disc at every angle; rows just below the band only hold arm edge remnants
band_l = ((yy >= TOP) & (yy < BOT) & (xx < PIV_L[0])) | ((yy >= BOT) & (yy < BOT + 18) & (xx < 362))
band_r = ((yy >= TOP) & (yy < BOT) & (xx > PIV_R[0])) | ((yy >= BOT) & (yy < BOT + 18) & (xx > 646))
m_l = band_l & (d_l > R - 2)
m_r = band_r & (d_r > R - 2)
arm_l = Image.fromarray(np.where(m_l, a, 0).astype(np.uint8))
arm_r = Image.fromarray(np.where(m_r, a, 0).astype(np.uint8))
body = np.where(m_l | m_r, 0, a)
PIV_L_ROT, PIV_R_ROT = PIV_L, PIV_R


def theta_of(mask, piv, side):
    ys, xs = np.nonzero(mask & (a > 128))
    i = np.argmin(xs) if side < 0 else np.argmax(xs)
    dx, dy = abs(xs[i] - piv[0]), piv[1] - ys[i]
    return 90 + math.degrees(math.atan2(dy, dx))      # 0 = hanging, 90 = horizontal, 180 = straight up


T0_L, T0_R = theta_of(m_l, PIV_L, -1), theta_of(m_r, PIV_R, 1)
caps = ((d_l <= R) | (d_r <= R)).astype(np.uint8) * 255   # joint discs, part of the body
thetas = [15 + (155 - 15) * i / (N - 1) for i in range(N)]
frames = []
for i, th in enumerate(thetas, 1):
    # PIL rotates counter-clockwise on screen: raising the left arm is clockwise, the right arm counter-clockwise
    l = np.asarray(arm_l.rotate(-(th - T0_L), resample=Image.BICUBIC, center=PIV_L))
    r = np.asarray(arm_r.rotate(th - T0_R, resample=Image.BICUBIC, center=PIV_R))
    m = np.maximum.reduce([body, l, r, caps])
    img = Image.new("RGBA", (W, H), INK + (0,))
    img.putalpha(Image.fromarray(m.astype(np.uint8)))
    img.save(HERE / "final" / "png" / f"herald_f{i:02d}.png", optimize=True)
    frames.append(img)

fh = 900
fw = round(W * fh / H)
sheet = Image.new("RGBA", (fw * N, fh), INK + (0,))
for i, f in enumerate(frames):
    sheet.alpha_composite(f.resize((fw, fh), Image.LANCZOS), (i * fw, 0))
sheet.save(HERE / "final" / "herald_sprite.webp", "WEBP", quality=88, method=6)
(HERE / "final" / "herald_sprite.json").write_text(json.dumps({"n": N, "fw": fw, "fh": fh, "thetas": thetas}))
print(f"theta0 L={T0_L:.1f} R={T0_R:.1f}; {N} frames; sprite {sheet.size} {(HERE / 'final' / 'herald_sprite.webp').stat().st_size // 1024}K")
