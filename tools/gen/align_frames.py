#!/usr/bin/env python3
"""align_frames.py OUTNAME A.png B.png C.png: put pose frames of one figure on a shared canvas.

Each frame is scaled so head-top-to-feet height matches and placed with the same feet line and body
centre, so swapping frames only moves the arms. Writes final/png/OUTNAME<i>.png, final/OUTNAME<i>.webp
and final/OUTNAME.json with the canvas size and body landmarks (canvas pixels).
"""
import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image

HERE = Path(__file__).resolve().parent
BODY = 1000          # head-top-to-feet height on the shared canvas
name, srcs = sys.argv[1], sys.argv[2:]


def landmarks(a):
    m = a > 128
    rows = np.flatnonzero(m.any(axis=1))
    top, feet = rows[0], rows[-1]
    h = feet - top
    band = m[top + int(h * 0.40): top + int(h * 0.75)]          # torso and hips: arms excluded
    cx = float(np.median(np.nonzero(band)[1]))
    half = max(6, int(m.shape[1] * 0.05))
    col = m[:, int(cx) - half: int(cx) + half]
    head = int(np.flatnonzero(col.any(axis=1))[0])
    return head, int(feet), cx


frames = []
for p in srcs:
    im = Image.open(p).convert("RGBA")
    head, feet, cx = landmarks(np.asarray(im)[..., 3])
    s = BODY / (feet - head)
    im = im.resize((round(im.width * s), round(im.height * s)), Image.LANCZOS)
    frames.append((im, head * s, feet * s, cx * s))

# shared canvas: union of all frames placed with feet and centre aligned
left = max(cx for _, _, _, cx in frames)
right = max(im.width - cx for im, _, _, cx in frames)
up = max(feet for _, _, feet, _ in frames)
down = max(im.height - feet for im, _, feet, _ in frames)
W, H = int(left + right) + 8, int(up + down) + 8
CX, FEET = int(left) + 4, int(up) + 4

meta = {"w": W, "h": H, "cx": CX, "feet": FEET, "head": FEET - BODY, "frames": []}
for i, (im, head, feet, cx) in enumerate(frames, 1):
    c = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    c.alpha_composite(im, (int(round(CX - cx)), int(round(FEET - feet))))
    png = HERE / "final" / "png" / f"{name}{i}.png"
    png.parent.mkdir(parents=True, exist_ok=True)
    c.save(png, optimize=True)
    m = np.asarray(c)[..., 3] > 128
    ys, xs = np.nonzero(m)
    meta.setdefault("bbox", []).append([int(xs.min()), int(ys.min()), int(xs.max()), int(ys.max())])
    k = 900 / H
    c.resize((round(W * k), 900), Image.LANCZOS).save(HERE / "final" / f"{name}{i}.webp", "WEBP", quality=86, method=6)
    meta["frames"].append(png.name)
(HERE / "final" / f"{name}.json").write_text(json.dumps(meta))
print(json.dumps(meta))
