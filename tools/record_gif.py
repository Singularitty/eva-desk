#!/usr/bin/env python3
"""Render docs/demo.gif, a tour of the desk, and docs/hero.png, both monitors at a glance, from the daemon's own
drawing code. Nothing is recorded from a screen, so the result is the same on every machine and can be remade
after any change.

Tour: the desk · the launcher, and the title card while the app opens · a workspace switch · Alt+Tab · a new
track · a critical notification · the power menu · maximise · the screenshot tool · standby, and a key that
folds it away.

The wallpaper is one of standby's pictures, standing in for a wallpaper of your own.
Needs Pillow. usage: tools/record_gif.py [OUT.gif] [--width 960]
"""
import io
import sys
import time
from pathlib import Path

import cairo
from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))
from eva_desk import config  # noqa: E402

args = sys.argv[1:]
out = Path(next((a for a in args if a.endswith(".gif")), ROOT / "docs" / "demo.gif"))
width = int(args[args.index("--width") + 1]) if "--width" in args else 960
cfg = config.load("/nonexistent")
from eva_desk import draw as d, scenes as S, overlays as O, launcher as L, shot as SH  # noqa: E402
from eva_desk.bar import Bar  # noqa: E402
from eva_desk.motion import everything, render  # noqa: E402
from eva_desk.preview import _App  # noqa: E402
from record_motion import stand_in  # noqa: E402

W, H = 1720, 720
BAR = 28
gh = S.Geometry(W, H - BAR, 0)
WIN = (round(W * 0.56), BAR + 12, W - 12, H - 12)       # one window on the right: the wallpaper shows on the left
PIECES = everything()
CTX = render.fixture_ctx()


def bar_surface(tags_active=2, emergency=False):
    surf = cairo.ImageSurface(cairo.FORMAT_ARGB32, W, BAR)
    cr = cairo.Context(surf)
    bar = Bar.__new__(Bar)
    bar.cfg = dict(cfg, bar=dict(cfg["bar"], buttons=[]))
    bar.hits = []
    tags = [(n, "active" if n == tags_active else "urgent" if (emergency and n == 7) else "occupied" if n in (1, 2, 3) else "empty") for n in range(1, 11)]
    res = {"cpu": 97 if emergency else 9, "mem": "19G", "mem_pct": 61, "net": "lan", "down": "2K", "show": ["cpu", "mem", "net"]}
    music = {"status": "Playing", "title": "Walking on a Dream", "artist": "Empire of the Sun"}
    bar.state = {"tags": tags, "special": False, "title": "kitty — ~/Projects/eva-desk", "clock": "22:44", "date": "MON 05",
                 "volume": 68, "muted": False, "active": frozenset(), "tray": [], "music": music, "resources": res}
    bar._draw(None, cr, W, BAR)
    return surf


BARS = {False: bar_surface(), True: bar_surface(emergency=True)}
PICTURE, TEXTURE = stand_in("profile")


def motion(name, t, w=W, h=H, **more):
    """A frame of a motion piece as a cairo surface, clear where it paints nothing."""
    return render.frame(PIECES[name](), t, w, h, {**CTX, "picture": TEXTURE, **more})


WALLPAPER = motion("wallpaper", 7.0, ripples=False, embers=False)        # still in the tour: it has a picture of its own


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
        for i, (text, col) in enumerate((("~/Projects/eva-desk", d.GOLD), ("$ python3 -m unittest discover -s tests", d.BONE2),
                                         ("Ran 418 tests in 11.6s", d.BONE), ("OK", d.GOLD))):
            lay = d.layout(cr, text, d.F_META, 11)
            d.draw_text(cr, lay, x0 + 14, y0 + 12 + 18 * i, col)
    cr.pop_group_to_source()
    cr.paint_with_alpha(alpha)
    cr.restore()


def desk(cr, wallpaper=None):
    cr.set_source_surface(wallpaper or WALLPAPER, 0, 0)
    cr.paint()
    window(cr)


def on_top(surface):
    """Something on the overlay layer: over the bar too."""
    def fn(cr):
        cr.set_source_surface(surface, 0, 0)
        cr.paint()
    return fn


frames, durations = [], []


def frame(draw_fn, ms, bar=True, emergency=False, over=None):
    surf = cairo.ImageSurface(cairo.FORMAT_ARGB32, W, H)
    cr = cairo.Context(surf)
    d.rgba(cr, d.INK)
    cr.paint()
    draw_fn(cr)
    if bar:
        cr.set_source_surface(BARS[emergency], 0, 0)
        cr.paint()
    if over is not None:
        over(cr)
    buf = io.BytesIO()
    surf.write_to_png(buf)
    im = Image.open(buf).convert("RGB")
    frames.append(im.resize((width, round(H * width / W)), Image.LANCZOS))
    durations.append(ms)
    return surf


def hero(path):
    """Both monitors: the main one with a window over its moving wallpaper, the side one with the status wall."""
    surf = cairo.ImageSurface(cairo.FORMAT_ARGB32, W, H)
    cr = cairo.Context(surf)
    desk(cr, motion("wallpaper", 2.0))                   # a ripple on its way out, and the specks
    cr.set_source_surface(BARS[False], 0, 0)
    cr.paint()
    buf = io.BytesIO()
    surf.write_to_png(buf)
    main = Image.open(buf).convert("RGB").resize((1600, 670), Image.LANCZOS)
    full, _ = stand_in("full")
    k = max(1080 / full.width, 1920 / full.height)        # the side monitor's own wallpaper, cropped to it
    full = full.resize((round(full.width * k), round(full.height * k)), Image.LANCZOS)
    left, top = (full.width - 1080) // 2, (full.height - 1920) // 2
    under = full.crop((left, top, left + 1080, top + 1920)).convert("RGBA")
    buf = io.BytesIO()
    motion("wall", 3.0, 1080, 1920).write_to_png(buf)
    side = Image.alpha_composite(under, Image.open(buf).convert("RGBA")).convert("RGB").resize((377, 670), Image.LANCZOS)
    out_image = Image.new("RGB", (1600 + 24 + 377, 670), (6, 3, 12))
    out_image.paste(main, (0, 0))
    out_image.paste(side, (1624, 0))
    out_image.save(path, optimize=True)
    print(f"{path}: {out_image.size[0]}x{out_image.size[1]}, {path.stat().st_size // 1024} KB")


# 1. the desk
desk_still = frame(desk, 1500)

# 2. the launcher: the cut, typing, then Enter: the title card while the app opens
lau = L.Launcher.__new__(L.Launcher)
lau.cfg, lau.counts, lau.blink, lau.item_boxes, lau.shown_at = cfg, {"firefox.desktop": 214}, True, [], 0
results = [("app", _App("Firefox", "Web browser")), ("app", _App("Firefox Private Window", "")), ("app", _App("Files", "")),
           ("web", "fire")]


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
for q in ("f", "fi", "fir", "fire"):
    frame(launcher_at(q), 140, bar=False)
frame(launcher_at("fire"), 900, bar=False)
for i in range(31):                                     # two seconds at fifteen frames a second
    frame(desk, 66, over=on_top(motion("card", i / 15, app="FIREFOX")))
frame(desk, 700)

# 3. a workspace switch
card = cairo.ImageSurface(cairo.FORMAT_ARGB32, W, H)
O.draw_eyecatch(cairo.Context(card), W, H, 3, "PROJECTS", soft=True)


def with_card(alpha):
    def fn(cr):
        desk(cr)
        cr.set_source_surface(card, 0, 0)
        cr.paint_with_alpha(alpha)
    return fn


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
frame(desk, 500)

# 5. a new track: a card in a corner
for i in range(0, 21):                                   # 1.6 s at twelve and a half frames a second
    frame(desk, 80, over=on_top(motion("track", i * 0.08)))
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
frame(with_band(1.0), 1300, emergency=True)
frame(desk, 500)

# 7. the power menu
for sel, armed, ms in ((0, False, 500), (2, False, 300), (4, False, 400), (4, True, 900)):
    frame(lambda cr, s=sel, a=armed: (desk(cr), O.draw_power(cr, W, H, s, a, "7 WINDOWS OPEN · 1 EDITOR")), ms)
frame(desk, 500)

# 8. maximise: the window grows, the backdrop rises behind it
rig = S.HeraldRig()


def maxi(t):
    def fn(cr):
        e = S.ease_out_cubic(t)
        desk(cr)
        cr.save()
        cr.translate(0, BAR)
        if e > 0:
            cr.push_group()
            S.herald_backdrop(cr, gh)
            rig.draw(cr, gh, 1.0)
            cr.pop_group_to_source()
            cr.paint_with_alpha(min(1.0, e * 1.6))
        cr.restore()
        x0, y0, x1, y1 = WIN
        X0 = x0 - (x0 - 12) * e
        window(cr, (X0, y0, x1, y1), alpha=0.84, lines=False)   # windows are a little see-through, as kitty is
        lay = d.layout(cr, "SUPER + RETURN · MAXIMISED", d.F_META, 12, spacing=3)
        d.draw_text(cr, lay, X0 + 14, y0 + 12, d.GOLD)
    return fn


for i in range(0, 9):
    frame(maxi(i / 8), 45)
frame(maxi(1.0), 1300)
frame(desk, 500)

# 9. the screenshot tool
sh = SH.Shot.__new__(SH.Shot)
frozen = desk_still
sh.mons = [{"m": {}, "w": W, "h": H, "scale": 1, "frozen": frozen, "bg": SH.backdrop(frozen, W, H)}]
sh.pointer, sh.sel, sh.flash = (0, 0, 0), None, None
sh.hover = (0, (WIN[0], WIN[1], WIN[2] - WIN[0], WIN[3] - WIN[1]), "kitty")
frame(lambda cr: sh._draw(0, cr, W, H), 900, bar=False)
sh.hover, sh.sel = None, (0, 140, 160, 840, 520)
frame(lambda cr: sh._draw(0, cr, W, H), 700, bar=False)
sh.sel, sh.flash = None, (0, (140, 160, 700, 360), time.monotonic() - 0.10)
frame(lambda cr: sh._draw(0, cr, W, H), 500, bar=False)
frame(desk, 900)

# 10. standby: the eyes breathe, a key, and it folds away
for i in range(12):
    frame(desk, 250, over=on_top(motion("standby", 1.0 + i * 0.25)))
for since in (0.02, 0.06, 0.11, 0.165):
    frame(desk, 50, over=on_top(motion("standby", 4.0, leaving=since)))
frame(desk, 1400)

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
hero(ROOT / "docs" / "hero.png")
