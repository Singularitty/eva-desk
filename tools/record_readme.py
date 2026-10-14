#!/usr/bin/env python3
"""Render every picture in the README, into docs/readme/, from eva-desk's own drawing code. Nothing is recorded
from a screen, so the result is the same on every machine and can be remade after any change.

  desk.png        both monitors: a window over the moving wallpaper, and the status wall
  tour.gif        the launcher and the title card, a workspace switch, Alt+Tab, a new track, a critical
                  notification, the power menu, the screenshot tool, standby
  launch.gif      the two launch sequences: the card for an app, the shaft for a game
  sequences.png   boot, wake, berserk and the track card
  standby.png     the four shots of standby
  wallpaper.gif   the moving wallpaper, at real speed
  wall.png        the status wall on a wide monitor
  launcher.png  bar.png  alttab.png  power.png  workspace.png  screenshot.png  sound.png  lock.png

The wallpapers are standby's pictures, standing in for wallpapers of your own. Needs Pillow.
usage: tools/record_readme.py
"""
import io
import json
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import cairo
from PIL import Image, ImageChops

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from eva_desk import config  # noqa: E402

cfg = config.load("/nonexistent")
from eva_desk import gtkutil  # noqa: E402,F401  (pins GTK 4 before any gi.repository import)
from gi.repository import Gdk  # noqa: E402

from eva_desk import draw as d, launcher as L, overlays as O, shot as SH  # noqa: E402
from eva_desk.bar import Bar  # noqa: E402
from eva_desk.mfd.sound import SoundModel, content_height, draw_sound  # noqa: E402
from eva_desk.motion import everything, render  # noqa: E402
from eva_desk.preview import _App  # noqa: E402

OUT = ROOT / "docs" / "readme"
W, H = 1720, 720                  # a 3440x1440 monitor at half size: the frame the pieces lay out from
BAR = 28
WIDE = 1280                       # how wide the stills are
GIF = 960                         # how wide the animations are
WIN = (round(W * 0.56), BAR + 12, W - 12, H - 12)      # one window on the right: the wallpaper shows on the left
PIECES = everything()
CTX = render.fixture_ctx()


# ---------------------------------------------------------------- pictures and frames
def image(surface):
    buf = io.BytesIO()
    surface.write_to_png(buf)
    return Image.open(buf).convert("RGBA")


def scaled(im, width):
    return im.resize((width, round(width * im.height / im.width)), Image.LANCZOS)


def save(im, name):
    path = OUT / name
    im.convert("RGB").save(path, optimize=True)
    print(f"{path.relative_to(ROOT)}: {im.width}x{im.height}, {path.stat().st_size // 1024} KB")


def gif(name, frames, durations, colours=255, dither=False):
    """One looping GIF on one palette, made from a mosaic of every frame, so that a colour a frame has keeps it."""
    path = OUT / name
    thumb = (frames[0].width // 3, frames[0].height // 3)
    cols = 6
    mosaic = Image.new("RGB", (thumb[0] * cols, thumb[1] * ((len(frames) + cols - 1) // cols)))
    for i, f in enumerate(frames):
        mosaic.paste(f.convert("RGB").resize(thumb, Image.BILINEAR), ((i % cols) * thumb[0], (i // cols) * thumb[1]))
    palette = mosaic.quantize(colors=colours, method=Image.Quantize.MEDIANCUT)
    mode = Image.Dither.FLOYDSTEINBERG if dither else Image.Dither.NONE
    q = [f.convert("RGB").quantize(palette=palette, dither=mode) for f in frames]
    if isinstance(durations, (int, float)):
        durations = [durations] * len(frames)
    q[0].save(path, save_all=True, append_images=q[1:], duration=list(durations), loop=0, optimize=True)
    print(f"{path.relative_to(ROOT)}: {len(frames)} frames, {sum(durations) / 1000:.1f} s, {path.stat().st_size // 1024} KB")


def grid(name, cells, cols=2):
    """Frames in a grid as wide as the other stills, with a thin ink gutter between them."""
    cw = (WIDE - (cols - 1) * 4) // cols
    ch = round(cw * H / W)
    rows = (len(cells) + cols - 1) // cols
    out = Image.new("RGB", (WIDE, rows * ch + (rows - 1) * 4), (6, 3, 12))
    for i, cell in enumerate(cells):
        out.paste(cell.convert("RGB").resize((cw, ch), Image.LANCZOS), ((i % cols) * (cw + 4), (i // cols) * (ch + 4)))
    save(out, name)


def stand_in(name):
    """One of standby's pictures with its two layers put back together: (picture, texture)."""
    body = Image.open(ROOT / f"assets/motion/{name}_body.jpg").convert("RGB")
    eye = Image.open(ROOT / f"assets/motion/{name}_eye.jpg").convert("RGB")
    picture = ImageChops.screen(body, eye)
    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
        picture.save(f.name)
        texture = Gdk.Texture.new_from_filename(f.name)
    Path(f.name).unlink()
    return picture, texture


PICTURE, TEXTURE = stand_in("profile")


def motion(name, t, w=W, h=H, **more):
    """A frame of a motion piece as a cairo surface, clear where it paints nothing."""
    return render.frame(PIECES[name](), t, w, h, {**CTX, "picture": TEXTURE, **more})


# ---------------------------------------------------------------- the desk
def bar_surface(width=W, height=BAR, hot=False):
    surf = cairo.ImageSurface(cairo.FORMAT_ARGB32, width, height)
    cr = cairo.Context(surf)
    bar = Bar.__new__(Bar)
    bar.cfg = dict(cfg, bar=dict(cfg["bar"], buttons=[]))
    bar.hits = []
    tags = [(n, "active" if n == 2 else "urgent" if (hot and n == 7) else "occupied" if n in (1, 2, 3) else "empty") for n in range(1, 11)]
    res = {"cpu": 97 if hot else 9, "mem": "9.8G", "mem_pct": 31, "net": "lan", "down": "340K", "show": ["cpu", "mem", "net"]}
    music = {"status": "Paused" if hot else "Playing", "title": "Walking on a Dream", "artist": "Empire of the Sun"}
    bar.state = {"tags": tags, "special": False, "title": "kitty — ~/Projects/eva-desk", "clock": "22:44", "date": "MON 05",
                 "volume": 68, "muted": False, "active": frozenset(), "tray": [], "music": music, "resources": res}
    d.rgba(cr, d.INK)
    cr.paint()
    bar._draw(None, cr, width, height)
    return surf


BARS = {False: bar_surface(), True: bar_surface(hot=True)}
WALLPAPER = motion("wallpaper", 7.0, ripples=False, embers=False)


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


def shot(draw_fn=desk, bar=True, hot=False, over=None):
    """One frame of the main monitor: what draw_fn paints, the bar over it, and what lies on the overlay layer."""
    surf = cairo.ImageSurface(cairo.FORMAT_ARGB32, W, H)
    cr = cairo.Context(surf)
    d.rgba(cr, d.INK)
    cr.paint()
    draw_fn(cr)
    if bar:
        cr.set_source_surface(BARS[hot], 0, 0)
        cr.paint()
    if over is not None:
        cr.set_source_surface(over, 0, 0)
        cr.paint()
    return image(surf)


DESK = shot()


# ---------------------------------------------------------------- what the desk shows
CAST = [{"app": "kitty", "title": "~/Projects/eva-desk · nvim app.py", "ep": "EP 02 · WS 02"},
        {"app": "firefox", "title": "Hyprland wiki · Lua config", "ep": "EP 01 · WS 01"},
        {"app": "thunar", "title": "~/Pictures", "ep": "EP 03 · WS 03"},
        {"app": "Spotify", "title": "Walking on a Dream", "ep": "EP 07 · WS 07", "urgent": True},
        {"app": "discord", "title": "#general", "ep": "SIDE"}]
NOTE = {"app": "UPS", "summary": "On battery: 4 minutes left", "body": "Internal power only. Save your work."}

lau = L.Launcher.__new__(L.Launcher)
lau.cfg, lau.counts, lau.blink, lau.item_boxes, lau.shown_at = cfg, {"firefox.desktop": 214}, True, [], 0
RESULTS = [("app", _App("Firefox", "Web browser")), ("app", _App("Firefox Private Window", "")), ("app", _App("Files", "")),
           ("web", "fire")]


def launcher_at(q):
    def fn(cr):
        lau.query, lau.sel, lau.results = q, 0, RESULTS
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


EYECATCH = cairo.ImageSurface(cairo.FORMAT_ARGB32, W, H)
O.draw_eyecatch(cairo.Context(EYECATCH), W, H, 3, "PROJECTS", soft=True)
BAND = cairo.ImageSurface(cairo.FORMAT_ARGB32, W, 70)
O.draw_band(cairo.Context(BAND), W, 70, NOTE)


def with_card(alpha):
    def fn(cr):
        desk(cr)
        cr.set_source_surface(EYECATCH, 0, 0)
        cr.paint_with_alpha(alpha)
    return fn


def with_band(k):
    def fn(cr):
        desk(cr)
        cr.save()
        cr.rectangle(0, BAR, W, 70)
        cr.clip()
        cr.set_source_surface(BAND, 0, BAR - 70 * (1 - k))
        cr.paint()
        cr.restore()
    return fn


def screenshot_tool(state):
    sh = SH.Shot.__new__(SH.Shot)
    frozen = cairo.ImageSurface(cairo.FORMAT_ARGB32, W, H)
    fcr = cairo.Context(frozen)
    desk(fcr)
    fcr.set_source_surface(BARS[False], 0, 0)
    fcr.paint()
    sh.mons = [{"m": {}, "w": W, "h": H, "scale": 1, "frozen": frozen, "bg": SH.backdrop(frozen, W, H)}]
    sh.pointer, sh.sel, sh.flash, sh.hover = (0, 0, 0), None, None, None
    if state == "hover":
        sh.hover = (0, (WIN[0], WIN[1], WIN[2] - WIN[0], WIN[3] - WIN[1]), "kitty")
    elif state == "drag":
        sh.sel = (0, 420, 110, 1140, 560)
    else:
        sh.flash = (0, (140, 160, 700, 360), time.monotonic() - 0.10)
    return lambda cr: sh._draw(0, cr, W, H)


# ---------------------------------------------------------------- the pictures
def desk_picture():
    """Both monitors: the main one with a window over its moving wallpaper, the side one with the status wall."""
    main = shot(lambda cr: desk(cr, motion("wallpaper", 2.0))).resize((1600, 670), Image.LANCZOS)        # a ripple on its way out
    full, _ = stand_in("full")
    k = max(1080 / full.width, 1920 / full.height)        # the side monitor's own wallpaper, cropped to it
    full = full.resize((round(full.width * k), round(full.height * k)), Image.LANCZOS)
    left, top = (full.width - 1080) // 2, (full.height - 1920) // 2
    under = full.crop((left, top, left + 1080, top + 1920)).convert("RGBA")
    side = Image.alpha_composite(under, image(motion("wall", 3.0, 1080, 1920))).resize((377, 670), Image.LANCZOS)
    out = Image.new("RGB", (1600 + 24 + 377, 670), (6, 3, 12))
    out.paste(main.convert("RGB"), (0, 0))
    out.paste(side.convert("RGB"), (1624, 0))
    save(out, "desk.png")


def tour():
    frames, durations = [], []

    def add(im, ms):
        frames.append(scaled(im, GIF))
        durations.append(ms)
    add(DESK, 1500)
    add(shot(cut(False), bar=False), 60)
    add(shot(cut(True), bar=False), 50)
    for q in ("f", "fi", "fir", "fire"):
        add(shot(launcher_at(q), bar=False), 140)
    add(shot(launcher_at("fire"), bar=False), 900)
    for i in range(31):                                   # the title card, two seconds at fifteen frames a second
        add(shot(over=motion("card", i / 15, app="FIREFOX")), 66)
    add(DESK, 700)
    add(shot(with_card(1.0)), 110)
    for i in range(1, 6):
        add(shot(with_card(1 - i / 5)), 36)
    add(DESK, 700)
    for sel, ms in ((1, 500), (2, 420), (3, 900)):
        add(shot(lambda cr, s=sel: (desk(cr), O.draw_alttab(cr, W, H, CAST, s))), ms)
    add(DESK, 500)
    for i in range(21):                                   # a new track: the card in a corner
        add(shot(over=motion("track", i * 0.08)), 80)
    add(DESK, 500)
    for i in range(1, 5):
        add(shot(with_band(1 - (1 - i / 4) ** 3), hot=True), 55)
    add(shot(with_band(1.0), hot=True), 1300)
    add(DESK, 500)
    for sel, armed, ms in ((0, False, 500), (2, False, 300), (4, False, 400), (4, True, 900)):
        add(shot(lambda cr, s=sel, a=armed: (desk(cr), O.draw_power(cr, W, H, s, a, "7 WINDOWS OPEN · 1 EDITOR"))), ms)
    add(DESK, 500)
    for state, ms in (("hover", 900), ("drag", 700), ("flash", 500)):
        add(shot(screenshot_tool(state), bar=False), ms)
    add(DESK, 900)
    for i in range(12):                                   # standby: the eyes breathe, a key, it folds away
        add(shot(over=motion("standby", 1.0 + i * 0.25)), 250)
    for since in (0.02, 0.06, 0.11, 0.165):
        add(shot(over=motion("standby", 4.0, leaving=since)), 50)
    add(DESK, 1400)
    gif("tour.gif", frames, durations)


def motion_pictures():
    frames = [scaled(DESK, GIF)] * 6                      # the launch: the card for an app, a beat of desk, the shaft for a game
    for name, app in (("card", "FIREFOX"), ("shaft", "HADES")):
        piece = PIECES[name]()
        frames += [scaled(shot(over=motion(name, i / 15, app=app)), GIF) for i in range(round(piece.length * 15) + 1)]
        frames += [scaled(DESK, GIF)] * 6
    gif("launch.gif", frames, 66, colours=160)
    grid("sequences.png", [shot(over=motion(name, PIECES[name]().still)) for name in ("boot", "wake", "berserk", "track")])
    grid("standby.png", [image(motion("standby", t)) for t in (4.0, 16.5, 38.0, 49.0)])
    gif("wallpaper.gif", [scaled(image(motion("wallpaper", 0.5 + i / 8)), GIF) for i in range(48)], 125, colours=128, dither=True)
    under = PICTURE.convert("RGBA").resize((W, H), Image.LANCZOS)
    save(scaled(Image.alpha_composite(under, image(motion("wall", 3.0))), WIDE), "wall.png")


def stills():
    save(scaled(shot(launcher_at("fire"), bar=False), WIDE), "launcher.png")
    calm, hot = image(bar_surface(W, 56)), image(bar_surface(W, 56, hot=True))
    both = Image.new("RGBA", (W, 56 * 2 + 4), (6, 3, 12, 255))
    both.paste(calm, (0, 0))
    both.paste(hot, (0, 60))
    save(scaled(both, WIDE), "bar.png")
    save(scaled(shot(lambda cr: (desk(cr), O.draw_alttab(cr, W, H, CAST, 1))), WIDE), "alttab.png")
    save(scaled(shot(lambda cr: (desk(cr), O.draw_power(cr, W, H, 2, False, "7 WINDOWS OPEN · 1 EDITOR"))), WIDE), "power.png")
    save(scaled(shot(with_card(1.0)), WIDE), "workspace.png")
    save(scaled(shot(screenshot_tool("drag"), bar=False), WIDE), "screenshot.png")
    fixture = json.loads((ROOT / "tests" / "fixtures" / "audiostate.json").read_text())
    model = SoundModel(fixture, {"dnd": False, "night": True, "power": "balanced"})
    ph = content_height(model)

    def with_sound(cr):
        desk(cr)
        cr.save()
        cr.translate(W - 640 - 24, BAR + 4)             # the drop-down hangs under the bar, near its VOL tag
        draw_sound(cr, 0, 0, 640, ph, model, False)
        cr.restore()
    save(scaled(shot(with_sound), WIDE), "sound.png")
    with tempfile.TemporaryDirectory() as tmp:
        subprocess.run([sys.executable, str(ROOT / "tools" / "lock_screen.py"), tmp], check=True, capture_output=True)
        save(scaled(Image.open(Path(tmp) / "lock-main.png").convert("RGBA"), WIDE), "lock.png")


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    desk_picture()
    tour()
    motion_pictures()
    stills()


if __name__ == "__main__":
    main()
