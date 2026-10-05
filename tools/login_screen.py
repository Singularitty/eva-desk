#!/usr/bin/env python3
"""Render the ReGreet login background (eva): the A.T. field with Unit-01 on the right, the 新世紀 strip, the NERV
title card and the 起動 · 搭乗者認証 plate. ReGreet draws the form (styled by greeter/regreet-eva.css) on top.

usage: tools/login_screen.py OUT.png [--theme eva] [--size 3440x1440]
"""
import math
import sys
from pathlib import Path

import cairo

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from eva_desk import config  # noqa: E402

args = sys.argv[1:]
theme = args[args.index("--theme") + 1] if "--theme" in args else "eva"
out = Path([a for a in args if a.endswith(".png")][0]).expanduser()
if "--size" in args:
    W, H = (int(v) for v in args[args.index("--size") + 1].split("x"))
else:
    W, H = 3440, 1440
    try:                                                   # the largest monitor's size, when Hyprland is around
        import json, subprocess
        mons = json.loads(subprocess.run(["hyprctl", "-j", "monitors"], capture_output=True, text=True, timeout=3).stdout)
        m = max(mons, key=lambda m: m["width"] * m["height"])
        sc = float(m.get("scale", 1) or 1)
        W, H = int(m["width"] / sc), int(m["height"] / sc)
        if int(m.get("transform", 0)) % 2 == 1:
            W, H = H, W
    except Exception:
        pass
config.activate_theme(theme)
from eva_desk import draw as d  # noqa: E402

surf = cairo.ImageSurface(cairo.FORMAT_ARGB32, W, H)
cr = cairo.Context(surf)
s = H / 720
d.rgba(cr, d.col("ink_deep"))
cr.paint()
# the field and the Eva on the right third
stage = W * 0.36
cr.save()
cr.rectangle(W - stage, 0, stage, H)
cr.clip()
cr.translate(W - stage, 0)
d.hex_field(cr, stage, H, stage * 0.5, H * 0.45, H * 0.11)
cr.restore()
fig = d.image("figures/boxer.png")
fh = H * 0.80
fw = fh * fig.get_width() / fig.get_height()
fx, fy = W - stage + (stage - fw) / 2, H - fh
d.silhouette(cr, fig, fx, fy, fw, fh, echo=14 * s)
d.hazard(cr, W - stage - 60 * s, H - 24 * s, stage + 60 * s, 24 * s, d.CLARET, d.col("ink_deep"), period=28 * s)
# the vertical strip
sx, sy, sw, sh = 40 * s, 40 * s, 64 * s, 640 * s
d.block(cr, sx, sy, sw, sh, d.BONE)
glyphs = [d.layout(cr, ch, d.F_DISPLAY, 40 * s, weight=d.DISPLAY_WEIGHT) for ch in "新世紀"]
total = sum(d.text_size(g)[1] for g in glyphs) + 6 * s * 2
gy = sy + (sh - total) / 2
for g in glyphs:
    tw, th = d.text_size(g)
    d.draw_text(cr, g, sx + (sw - tw) / 2, gy, d.col("ink_deep"))
    gy += th + 6 * s
# header: EPISODE 00, NERV, the plate
lab = d.layout(cr, "EPISODE 00 · PILOT IDENTIFICATION", d.F_META, 14 * s, spacing=6 * s)
d.draw_text(cr, lab, 150 * s, 56 * s, d.RED)
nerv = d.layout(cr, "NERV", d.F_DISPLAY, 120 * s, weight=d.DISPLAY_WEIGHT, spacing=-6 * s)
tw, th = d.text_size(nerv)
d.draw_text(cr, nerv, 146 * s, 70 * s, d.BONE)
plate = d.layout(cr, "起動 · 搭乗者認証", d.F_DISPLAY, 28 * s, weight=d.DISPLAY_WEIGHT)
pw, ph = d.text_size(plate)
py = 70 * s + th * 0.86
d.block(cr, 150 * s, py, pw + 32 * s, ph + 8 * s, d.BONE)
d.draw_text(cr, plate, 166 * s, py + 2 * s, d.col("ink_deep"))
# MAGI readout top right
r1 = d.layout(cr, "ARCH · HYPRLAND · MAGI NOMINAL", d.F_META, 13 * s, spacing=3 * s)
rw, rh = d.text_size(r1)
d.draw_text(cr, r1, W - 48 * s - rw, 48 * s, d.GOLD)
out.parent.mkdir(parents=True, exist_ok=True)
surf.write_to_png(str(out))
print("login background:", out)
