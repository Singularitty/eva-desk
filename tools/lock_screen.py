#!/usr/bin/env python3
"""Render the lock screen pictures (hyprlock backgrounds): the SEELE council on black, SOUND ONLY.

usage: tools/lock_screen.py OUTDIR [--theme eva]   -> OUTDIR/lock-main.png (3440x1440), OUTDIR/lock-side.png (1080x1920)
hyprlock draws the clock, the readouts and the input on top (see config/hyprlock.conf).
"""
import sys
from pathlib import Path

import cairo

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from eva_desk import config  # noqa: E402

args = sys.argv[1:]
theme = args[args.index("--theme") + 1] if "--theme" in args else "eva"
out = Path([a for a in args if not a.startswith("--") and a != theme][0]).expanduser()
config.activate_theme(theme)
from eva_desk import draw as d  # noqa: E402

HEIGHTS = [230, 258, 284, 308, 330, 346, 360, 346, 330, 308, 284, 258]
NUMBERS = [12, 11, 10, 9, 8, 7, 1, 2, 3, 4, 5, 6]


def council(cr, w, h, cols=12, floor=0.68):
    """Twelve monoliths in a shallow arc, 01 in front with the lilac rule and purple drop."""
    d.rgba(cr, d.hexc("020104"))
    cr.paint()
    s = h / 720
    span = w * 0.87
    mw = 96 * s
    gap = (span - cols * mw) / (cols - 1)
    x0 = (w - span) / 2
    base = h * floor
    for i in range(cols):
        mh = HEIGHTS[i] * s
        x, y = x0 + i * (mw + gap), base - mh
        n = NUMBERS[i]
        front = n == 1
        dist = abs(i - 6)
        alpha = 1.0 - 0.075 * max(0, dist - 2)
        if front:
            d.block(cr, x, y, mw, mh, d.col("ink_deep"), shadow=d.CLARET, shadow_off=(10 * s, 10 * s), border=d.BONE, border_w=2 * s)
        else:
            d.block(cr, x, y, mw, mh, d.col("ink_deep"), border=(d.CLARET if dist <= 2 else d.col("ink5")), border_w=1 * s)
        cr.save()
        cr.push_group()
        lab = d.layout(cr, "SEELE", d.F_META, 11 * s, spacing=2 * s)
        tw, th = d.text_size(lab)
        d.draw_text(cr, lab, x + (mw - tw) / 2, y + 10 * s, d.GOLD if front else d.RED)
        num = d.layout(cr, f"{n:02d}", d.F_DISPLAY, (40 if front else 34) * s, weight=d.DISPLAY_WEIGHT, spacing=-2 * s)
        tw, th = d.text_size(num)
        d.draw_text(cr, num, x + (mw - tw) / 2, y + (mh - th) / 2, d.BONE)
        so = d.layout(cr, "SOUND ONLY", d.F_META, 9 * s, spacing=2 * s)
        tw, th = d.text_size(so)
        d.draw_text(cr, so, x + (mw - tw) / 2, y + mh - 12 * s - th, d.GOLD if front else d.DIM)
        cr.pop_group_to_source()
        cr.paint_with_alpha(alpha)
        cr.restore()
    cr.set_line_width(1)
    d.rgba(cr, d.col("ink4"))
    cr.move_to(0, base)
    cr.line_to(w, base)
    cr.stroke()
    d.hazard(cr, 0, h - 10 * s, w, 10 * s, d.CLARET, d.hexc("020104"), period=32 * s)


def main_screen(w=3440, h=1440):
    surf = cairo.ImageSurface(cairo.FORMAT_ARGB32, w, h)
    council(cairo.Context(surf), w, h)
    return surf


def side_screen(w=1080, h=1920):
    surf = cairo.ImageSurface(cairo.FORMAT_ARGB32, w, h)
    cr = cairo.Context(surf)
    d.rgba(cr, d.hexc("020104"))
    cr.paint()
    s = w / 1080
    # a single monolith, SEELE 01, standing tall; the Eva watches from the field below
    mw, mh = 260 * s, 640 * s
    x, y = (w - mw) / 2, h * 0.16
    d.block(cr, x, y, mw, mh, d.col("ink_deep"), shadow=d.CLARET, shadow_off=(16 * s, 16 * s), border=d.BONE, border_w=3 * s)
    lab = d.layout(cr, "SEELE", d.F_META, 18 * s, spacing=5 * s)
    tw, th = d.text_size(lab)
    d.draw_text(cr, lab, x + (mw - tw) / 2, y + 28 * s, d.GOLD)
    num = d.layout(cr, "01", d.F_DISPLAY, 120 * s, weight=d.DISPLAY_WEIGHT, spacing=-6 * s)
    tw, th = d.text_size(num)
    d.draw_text(cr, num, x + (mw - tw) / 2, y + (mh - th) / 2, d.BONE)
    so = d.layout(cr, "SOUND ONLY", d.F_META, 14 * s, spacing=4 * s)
    tw, th = d.text_size(so)
    d.draw_text(cr, so, x + (mw - tw) / 2, y + mh - 30 * s - th, d.GOLD)
    d.hazard(cr, 0, h - 14 * s, w, 14 * s, d.CLARET, d.hexc("020104"), period=40 * s)
    return surf


out.mkdir(parents=True, exist_ok=True)
main_screen().write_to_png(str(out / "lock-main.png"))
side_screen().write_to_png(str(out / "lock-side.png"))
print("lock screens:", out / "lock-main.png", out / "lock-side.png")
