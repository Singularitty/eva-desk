#!/usr/bin/env python3
"""Render docs/demo.gif from the daemon's own drawing code: the figure's entrance on a workspace, a moment of
stillness, then the workspace card. No screen recording involved, so it is the same on every machine.

usage: tools/record_gif.py [OUT.gif] [--width 960]
"""
import io
import sys
from pathlib import Path

import cairo
from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from eva_desk import config  # noqa: E402

args = sys.argv[1:]
out = Path(next((a for a in args if a.endswith(".gif")), ROOT / "docs" / "demo.gif"))
width = int(args[args.index("--width") + 1]) if "--width" in args else 960
cfg = config.load("/nonexistent")
from eva_desk import draw as d, scenes as S, overlays as O  # noqa: E402
from eva_desk.bar import Bar  # noqa: E402
from eva_desk.config import stage_share  # noqa: E402

W, H = 1720, 720                      # the design space; the gif is scaled down from it
BAR = 28
g = S.Geometry(W, H - BAR, W * stage_share(cfg, W, H))


def bar_surface():
    """The bar from the daemon, drawn at the gif's scale."""
    surf = cairo.ImageSurface(cairo.FORMAT_ARGB32, W, BAR)
    cr = cairo.Context(surf)
    bar = Bar.__new__(Bar)
    bar.cfg = dict(cfg, bar=dict(cfg["bar"], buttons=[]))
    bar.hits = []
    tags = [(n, "active" if n == 2 else "occupied" if n in (1, 3) else "empty") for n in range(1, 11)]
    bar.state = {"tags": tags, "special": False, "title": "kitty — ~/Projects/eva-desk", "clock": "22:44", "date": "MON 05",
                 "volume": 68, "muted": False, "active": frozenset(), "tray": [], "music": None,
                 "resources": {"cpu": 9, "mem": "19G", "mem_pct": 61, "net": "lan", "down": "2K", "show": ["cpu", "mem", "net"]}}
    bar._draw(None, cr, W, BAR)
    return surf


def window(cr, alpha=1.0):
    """A tiled window on the left: lilac rule, purple drop, dark body."""
    x0, y0, x1, y1 = 12, BAR + 12, W - g.stage - 12, H - 12
    cr.save()
    cr.push_group()
    d.rgba(cr, d.CLARET)
    cr.rectangle(x0 + 7, y0 + 7, x1 - x0, y1 - y0)
    cr.fill()
    d.rgba(cr, d.col("ink_deep"))
    cr.rectangle(x0, y0, x1 - x0, y1 - y0)
    cr.fill()
    d.rgba(cr, d.BONE)
    cr.set_line_width(2)
    cr.rectangle(x0, y0, x1 - x0, y1 - y0)
    cr.stroke()
    lay = d.layout(cr, "$ python3 -m unittest discover -s tests", d.F_META, 11)
    d.draw_text(cr, lay, x0 + 14, y0 + 12, d.BONE2)
    lay = d.layout(cr, "Ran 18 tests in 0.214s", d.F_META, 11)
    d.draw_text(cr, lay, x0 + 14, y0 + 30, d.BONE)
    lay = d.layout(cr, "OK", d.F_META, 11)
    d.draw_text(cr, lay, x0 + 14, y0 + 48, d.GOLD)
    cr.pop_group_to_source()
    cr.paint_with_alpha(alpha)
    cr.restore()


bar = bar_surface()
frames, durations = [], []


def frame(draw_fn, ms):
    surf = cairo.ImageSurface(cairo.FORMAT_ARGB32, W, H)
    cr = cairo.Context(surf)
    d.rgba(cr, d.INK)
    cr.paint()
    draw_fn(cr)
    cr.set_source_surface(bar, 0, 0)
    cr.paint()
    buf = io.BytesIO()
    surf.write_to_png(buf)
    im = Image.open(buf).convert("RGB")
    im = im.resize((width, round(H * width / W)), Image.LANCZOS)
    frames.append(im)
    durations.append(ms)


def stage_at(t):
    def fn(cr):
        cr.save()
        cr.translate(0, BAR)
        S.figure_frame(cr, g, t)
        cr.restore()
        window(cr)
    return fn


def still(cr):
    cr.save()
    cr.translate(0, BAR)
    S.figure_scene(cr, g)
    cr.restore()
    window(cr)


# 1. an empty workspace, then the window opens and the figure enters (450 ms)
frame(lambda cr: None, 500)
for i in range(1, 13):
    frame(stage_at(i / 12), 40)
frame(still, 1400)
# 2. a workspace switch: the card holds, then fades (the "soft" style)
card = cairo.ImageSurface(cairo.FORMAT_ARGB32, W, H)
O.draw_eyecatch(cairo.Context(card), W, H, 3, "PROJECTS", soft=True)


def with_card(alpha):
    def fn(cr):
        still(cr)
        cr.set_source_surface(card, 0, 0)
        cr.paint_with_alpha(alpha)
    return fn


frame(with_card(1.0), 110)
for i in range(1, 6):
    frame(with_card(1 - i / 5), 36)
frame(still, 1200)

out.parent.mkdir(parents=True, exist_ok=True)
# one palette for all frames keeps the file small and the colours steady
pal = frames[-1].quantize(colors=128, method=Image.Quantize.MEDIANCUT)
q = [f.quantize(colors=128, palette=pal, dither=Image.Dither.NONE) for f in frames]
q[0].save(out, save_all=True, append_images=q[1:], duration=durations, loop=0, optimize=True)
print(f"{out}: {len(frames)} frames, {out.stat().st_size // 1024} KB")
