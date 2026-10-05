#!/usr/bin/env python3
"""contact.py OUT.png IMG... [--h 420] [--bg #3b0a14]: tile images in a row with their file stems."""
import argparse
from pathlib import Path

from PIL import Image, ImageDraw

ap = argparse.ArgumentParser()
ap.add_argument("out")
ap.add_argument("imgs", nargs="+")
ap.add_argument("--h", type=int, default=420)
ap.add_argument("--bg", default="#3b0a14")
a = ap.parse_args()

tiles = []
for p in a.imgs:
    im = Image.open(p).convert("RGBA")
    im = im.resize((round(im.width * a.h / im.height), a.h), Image.LANCZOS)
    t = Image.new("RGBA", (im.width, a.h + 22), a.bg)
    t.alpha_composite(im, (0, 22))
    ImageDraw.Draw(t).text((6, 4), Path(p).stem, fill="#efe4cf")
    tiles.append(t)
W = sum(t.width for t in tiles) + 6 * (len(tiles) - 1)
sheet = Image.new("RGBA", (W, a.h + 22), "#0c0608")
x = 0
for t in tiles:
    sheet.alpha_composite(t, (x, 0))
    x += t.width + 6
sheet.convert("RGB").save(a.out)
print(a.out, sheet.size)
