#!/usr/bin/env python3
"""Render docs/demo.gif, a tour of the desk, from the daemon's own drawing code. Nothing is recorded from a
screen, so the result is the same on every machine and can be remade after any change.

Sequence: the figure enters a workspace · the launcher · a workspace switch · Alt+Tab · the power menu and the
cross · a critical notification · maximise · the screenshot tool.

usage: tools/record_gif.py [OUT.gif] [--width 960]
"""
import io
import sys
import time
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
from eva_desk import draw as d, scenes as S, overlays as O, launcher as L, shot as SH  # noqa: E402
from eva_desk.bar import Bar  # noqa: E402
from eva_desk.config import stage_share  # noqa: E402
from eva_desk.preview import _App  # noqa: E402

W, H = 1720, 720
BAR = 28
g = S.Geometry(W, H - BAR, W * stage_share(cfg, W, H))
gh = S.Geometry(W, H - BAR, 0)
WIN = (12, BAR + 12, W - g.stage - 12, H - 12)          # the tiled window's box


def bar_surface(tags_active=2, emergency=False):
    surf = cairo.ImageSurface(cairo.FORMAT_ARGB32, W, BAR)
    cr = cairo.Context(surf)
    bar = Bar.__new__(Bar)
    bar.cfg = dict(cfg, bar=dict(cfg["bar"], buttons=[]))
    bar.hits = []
    tags = [(n, "active" if n == tags_active else "urgent" if (emergency and n == 7) else "occupied" if n in (1, 2, 3) else "empty") for n in range(1, 11)]
    res = {"cpu": 97 if emergency else 9, "mem": "19G", "mem_pct": 61, "net": "lan", "down": "2K", "show": ["cpu", "mem", "net"]}
    bar.state = {"tags": tags, "special": False, "title": "kitty — ~/Projects/eva-desk", "clock": "22:44", "date": "MON 05",
                 "volume": 68, "muted": False, "active": frozenset(), "tray": [], "music": None, "resources": res}
    bar._draw(None, cr, W, BAR)
    return surf


BARS = {False: bar_surface(), True: bar_surface(emergency=True)}


def window(cr, box=WIN, alpha=1.0, lines=True):
    x0, y0, x1, y1 = box
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
    if lines:
        for i, (text, col) in enumerate((("$ python3 -m unittest discover -s tests", d.BONE2), ("Ran 18 tests in 0.214s", d.BONE), ("OK", d.GOLD))):
            lay = d.layout(cr, text, d.F_META, 11)
            d.draw_text(cr, lay, x0 + 14, y0 + 12 + 18 * i, col)
    cr.pop_group_to_source()
    cr.paint_with_alpha(alpha)
    cr.restore()


frames, durations = [], []


def frame(draw_fn, ms, bar=True, emergency=False):
    surf = cairo.ImageSurface(cairo.FORMAT_ARGB32, W, H)
    cr = cairo.Context(surf)
    d.rgba(cr, d.INK)
    cr.paint()
    draw_fn(cr)
    if bar:
        cr.set_source_surface(BARS[emergency], 0, 0)
        cr.paint()
    buf = io.BytesIO()
    surf.write_to_png(buf)
    im = Image.open(buf).convert("RGB")
    frames.append(im.resize((width, round(H * width / W)), Image.LANCZOS))
    durations.append(ms)
    return surf


def stage(cr, t=1.0):
    cr.save()
    cr.translate(0, BAR)
    if t >= 1.0:
        S.figure_scene(cr, g)
    else:
        S.figure_frame(cr, g, t)
    cr.restore()


def desk(cr):
    stage(cr)
    window(cr)


# 1. the figure enters
frame(lambda cr: None, 500)
for i in range(1, 13):
    frame(lambda cr, t=i / 12: (stage(cr, t), window(cr)), 40)
desk_still = frame(desk, 1300)

# 2. the launcher: the cut, then typing
lau = L.Launcher.__new__(L.Launcher)
lau.cfg, lau.counts, lau.blink, lau.item_boxes, lau.shown_at = cfg, {"terminal.desktop": 214}, True, [], 0
results = [("app", _App("Terminal", "GPU terminal")), ("app", _App("Termux-SSH", "")), ("app", _App("Terminal Settings", "")),
           ("app", _App("Files", "")), ("web", "term")]


def launcher_at(q):
    def fn(cr):
        lau.query, lau.sel, lau.results = q, 0, results
        L._background(cr, W, H)
        lau._draw(None, cr, W, H)
    return fn


def cut(inverted):
    def fn(cr):
        p = L._palette()
        d.rgba(cr, L.C(p["slab"]) if inverted else L.C(p["bg"]))
        cr.paint()
        lay = d.layout(cr, "起動", d.F_DISPLAY, 120, weight=d.DISPLAY_WEIGHT)
        tw, th = d.text_size(lay)
        d.draw_text(cr, lay, (W - tw) / 2, (H - th) / 2, L.C(p["bg"]) if inverted else L.C(p["slab"]))
    return fn


frame(cut(False), 60, bar=False)
frame(cut(True), 50, bar=False)
for q in ("t", "te", "ter", "term"):
    frame(launcher_at(q), 140, bar=False)
frame(launcher_at("term"), 1500, bar=False)

# 3. a workspace switch
card = cairo.ImageSurface(cairo.FORMAT_ARGB32, W, H)
O.draw_eyecatch(cairo.Context(card), W, H, 3, "PROJECTS", soft=True)


def with_card(alpha):
    def fn(cr):
        desk(cr)
        cr.set_source_surface(card, 0, 0)
        cr.paint_with_alpha(alpha)
    return fn


frame(desk, 300)
frame(with_card(1.0), 110)
for i in range(1, 6):
    frame(with_card(1 - i / 5), 36)
frame(desk, 700)

# 4. Alt+Tab
cast = [{"app": "kitty", "title": "~/Projects/eva-desk · nvim app.py", "ep": "EP 02 · WS 02"},
        {"app": "firefox", "title": "Hyprland wiki · Lua config", "ep": "EP 01 · WS 01"},
        {"app": "thunar", "title": "~/Pictures", "ep": "EP 03 · WS 03"},
        {"app": "Spotify", "title": "Walking on a Dream", "ep": "EP 07 · WS 07", "urgent": True},
        {"app": "discord", "title": "#general", "ep": "SIDE"}]
for sel, ms in ((1, 500), (2, 420), (3, 900)):
    frame(lambda cr, s=sel: (desk(cr), O.draw_alttab(cr, W, H, cast, s)), ms)
frame(desk, 600)

# 5. the power menu, the cross
for sel, armed, ms in ((0, False, 500), (2, False, 300), (4, False, 400), (4, True, 700)):
    frame(lambda cr, s=sel, a=armed: (desk(cr), O.draw_power(cr, W, H, s, a, "7 WINDOWS OPEN · 1 EDITOR")), ms)


def cross(t):
    def fn(cr):
        desk(cr)
        O.draw_power(cr, W, H, 4, True, "7 WINDOWS OPEN · 1 EDITOR")
        e = S.ease_out_cubic(t)
        beam = max(4.0, 26 * e)
        half = W * 0.5 * e + 8
        cx, cy = W / 2, H * 0.5
        d.rgba(cr, d.GOLD, 0.35 * (1 - t) + 0.1)
        cr.rectangle(cx - beam * 2, 0, beam * 4, H)
        cr.rectangle(cx - half, cy - beam * 2, half * 2, beam * 4)
        cr.fill()
        d.rgba(cr, d.BONE)
        cr.rectangle(cx - beam / 2, 0, beam, H)
        cr.rectangle(cx - half, cy - beam / 2, half * 2, beam)
        cr.fill()
        if t > 0.75:
            d.rgba(cr, d.BONE, (t - 0.75) / 0.25)
            cr.paint()
    return fn


for i in range(1, 7):
    frame(cross(i / 6), 70, bar=False)
frame(lambda cr: (d.rgba(cr, d.BONE), cr.paint()), 350, bar=False)
frame(desk, 500)

# 6. a critical notification: the band drops under the bar
band = cairo.ImageSurface(cairo.FORMAT_ARGB32, W, 70)
O.draw_band(cairo.Context(band), W, 70, {"app": "UPS", "summary": "On battery: 4 minutes left", "body": "Internal power only. Save your work."})


def with_band(k):
    def fn(cr):
        desk(cr)
        cr.save()
        cr.rectangle(0, BAR, W, 70)
        cr.clip()
        cr.set_source_surface(band, 0, BAR - 70 * (1 - k))
        cr.paint()
        cr.restore()
    return fn


for i in range(1, 5):
    frame(with_band(S.ease_out_cubic(i / 4)), 55, emergency=True)
frame(with_band(1.0), 1400, emergency=True)
frame(desk, 500)

# 7. maximise: the window grows, the figure rises behind it
rig = S.HeraldRig()


def maxi(t):
    def fn(cr):
        e = S.ease_out_cubic(t)
        cr.save()
        cr.translate(0, BAR)
        if e > 0:
            cr.push_group()
            S.herald_backdrop(cr, gh)
            rig.draw(cr, gh, 1.0)
            cr.pop_group_to_source()
            cr.paint_with_alpha(min(1.0, e * 1.6))
        if e < 1:
            cr.save()
            cr.push_group()
            S.figure_scene(cr, g)
            cr.pop_group_to_source()
            cr.paint_with_alpha(1 - e)
            cr.restore()
        cr.restore()
        x0, y0, x1, y1 = WIN
        X1 = x1 + (W - 12 - x1) * e
        window(cr, (x0, y0, X1, y1), alpha=0.84, lines=False)   # windows are a little see-through, as kitty is
        lay = d.layout(cr, "SUPER + RETURN · MAXIMISED", d.F_META, 12, spacing=3)
        d.draw_text(cr, lay, x0 + 14, y0 + 12, d.GOLD)
    return fn


for i in range(0, 9):
    frame(maxi(i / 8), 45)
frame(maxi(1.0), 1400)
frame(desk, 500)

# 8. the screenshot tool
sh = SH.Shot.__new__(SH.Shot)
frozen = desk_still
sh.mons = [{"m": {}, "w": W, "h": H, "scale": 1, "frozen": frozen, "bg": SH.backdrop(frozen, W, H)}]
sh.pointer, sh.sel, sh.flash = (0, 0, 0), None, None
sh.hover = (0, (WIN[0], WIN[1], WIN[2] - WIN[0], WIN[3] - WIN[1]), "kitty")
frame(lambda cr: sh._draw(0, cr, W, H), 900, bar=False)
sh.hover, sh.sel = None, (0, 400, 200, 1100, 560)
frame(lambda cr: sh._draw(0, cr, W, H), 700, bar=False)
sh.sel, sh.flash = None, (0, (400, 200, 700, 360), time.monotonic() - 0.10)
frame(lambda cr: sh._draw(0, cr, W, H), 500, bar=False)
frame(desk, 1200)

out.parent.mkdir(parents=True, exist_ok=True)
# one global palette built from a mosaic of every frame, so the orange band and the white-out keep their colours
cols = 6
thumb = (width // 3, round(H * width / W) // 3)
mosaic = Image.new("RGB", (thumb[0] * cols, thumb[1] * ((len(frames) + cols - 1) // cols)))
for i, f in enumerate(frames):
    mosaic.paste(f.resize(thumb, Image.BILINEAR), ((i % cols) * thumb[0], (i // cols) * thumb[1]))
pal = mosaic.quantize(colors=255, method=Image.Quantize.MEDIANCUT)
q = [f.quantize(colors=255, palette=pal, dither=Image.Dither.NONE) for f in frames]
q[0].save(out, save_all=True, append_images=q[1:], duration=durations, loop=0, optimize=True)
print(f"{out}: {len(frames)} frames, {sum(durations) / 1000:.1f} s, {out.stat().st_size // 1024} KB")
