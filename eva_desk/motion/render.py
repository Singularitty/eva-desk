"""The offline renderer: a motion piece as frames, with no display. `eva-desk --render-motion DIR`.

A frame is built the way the player builds it, as a GTK snapshot, and then drawn through cairo
(`node.draw`), which GTK can do without a compositor. So what these files show is what the desk will show.
"""
import math
import shutil
import subprocess
import time
from pathlib import Path

import cairo

from .. import gtkutil  # (pins GTK 4 before any gi.repository import)

from gi.repository import Gtk  # noqa: E402

from .. import draw as d  # noqa: E402
from . import everything  # noqa: E402
from .kit import Kit  # noqa: E402

CELL = 860             # a frame on a contact sheet is at most this wide


_stand_in = None


def stand_in():
    """A picture for the wallpaper's offline frames: nobody's wallpaper, only something whose motion shows."""
    global _stand_in
    if _stand_in is None:
        def paint(cr):
            fall = cairo.LinearGradient(0, 0, 0, 720)
            fall.add_color_stop_rgb(0, *d.col("wine")[:3])
            fall.add_color_stop_rgb(1, *d.INK[:3])
            cr.set_source(fall)
            cr.paint()
            d.rgba(cr, d.BONE, 0.10)
            for x in range(0, 1720, 86):                                   # a grid, so that a push-in and a pan can be seen
                cr.rectangle(x, 0, 2, 720)
            for y in range(0, 720, 86):
                cr.rectangle(0, y, 1720, 2)
            cr.fill()
            d.rgba(cr, d.CLARET, 0.55)
            cr.rectangle(1118, 172, 344, 258)
            cr.fill()
        _stand_in = gtkutil.render_texture(1720, 720, paint)
    return _stand_in


def fixture_ctx():
    """The inputs every offline render uses, so two runs give the same frames."""
    return {"picture": stand_in(), "drift": 0.08, "lap": 30.0, "ripples": True, "embers": True,       # the wallpaper
            "app": "FIREFOX", "workspace": 2, "clock": "22:44",
            "outputs": ["3440×1440", "1080×1920"], "hyprland": "0.56", "lua": True, "net": "lan",       # boot
            "load": "CPU 97%", "seconds": 30,                                                          # berserk
            "title": "Walking on a Dream", "artist": "Empire of the Sun", "corner": "bottom-left",     # the track card
            "second": 37.0, "date": "TUE 13 OCT",                                                      # the loops' clock
            "readings": ["MAGI·1 CPU 07%", "MAGI·2 RAM 9.8G", "MAGI·3 LAN ↓340K"],
            "uptime": "04:12", "net": "lan", "music": {"status": "Playing", "title": "Walking on a Dream", "artist": "Empire of the Sun"},
            "magi": [{"value": 0.07, "label": "07%", "series": [0.07 + 0.3 * abs(math.sin(i / 7)) for i in range(61)]},       # the wall
                     {"value": 0.52, "label": "9.8G", "series": [0.5 + 0.02 * math.sin(i / 9) for i in range(61)]},
                     {"value": 0.30, "label": "↓340K", "series": [abs(math.sin(i / 3)) ** 3 for i in range(61)]}],
            "workspaces": [(n, "active" if n == 2 else "occupied" if n in (1, 3, 7) else "empty") for n in range(1, 11)]}


def parse_size(text):
    """"1720x720" -> (1720, 720)."""
    w, sep, h = str(text).partition("x")
    if not sep or not w.isdigit() or not h.isdigit() or int(w) < 1 or int(h) < 1:
        raise ValueError(f"not a size, expected WxH: {text!r}")
    return int(w), int(h)


def build(piece, t, w, h, ctx):
    """One frame at `t` seconds as the node tree GTK would draw; None when the piece paints nothing."""
    snap = Gtk.Snapshot()
    kit = Kit(snap, w, h)
    try:
        piece.draw(kit, t, ctx)
    finally:
        kit.close()
    return snap.to_node()


def frame(piece, t, w, h, ctx):
    """One frame at `t` seconds as an ARGB32 surface of w x h device px, clear where the piece paints nothing."""
    surf = cairo.ImageSurface(cairo.FORMAT_ARGB32, int(w), int(h))
    node = build(piece, t, w, h, ctx)
    if node is not None:
        node.draw(cairo.Context(surf))
    surf.flush()
    return surf


def over_desk(surf):
    """A frame over a stand-in desk (flat wine), so that what the piece leaves clear reads as the desk."""
    out = cairo.ImageSurface(cairo.FORMAT_ARGB32, surf.get_width(), surf.get_height())
    cr = cairo.Context(out)
    d.rgba(cr, d.col("wine"))
    cr.paint()
    cr.set_source_surface(surf, 0, 0)
    cr.paint()
    out.flush()
    return out


def _seconds(piece):
    """How much of a piece to show: a sequence's length, a loop's lap."""
    return piece.length or getattr(piece, "lap", 20.0)


def sheet(piece, w, h, ctx, cols=4, rows=3):
    """A contact sheet: cols * rows evenly spaced frames, each rendered at w x h and set no wider than CELL."""
    n, seconds = cols * rows, _seconds(piece)
    cw = min(w, CELL)
    ch = round(h * cw / w)
    out = cairo.ImageSurface(cairo.FORMAT_ARGB32, cols * cw, rows * ch)
    cr = cairo.Context(out)
    for i in range(n):
        cr.save()
        cr.translate((i % cols) * cw, (i // cols) * ch)
        cr.scale(cw / w, ch / h)
        cr.set_source_surface(over_desk(frame(piece, seconds * (i + 0.5) / n, w, h, ctx)), 0, 0)
        cr.paint()
        cr.restore()
    out.flush()
    return out


def build_ms(piece, w, h, ctx, n=40):
    """Mean time to build one frame's node tree, in ms: the Python side of a live frame."""
    seconds, start = _seconds(piece), time.perf_counter()
    for i in range(n):
        build(piece, seconds * (i + 0.5) / n, w, h, ctx)
    return 1000 * (time.perf_counter() - start) / n


def write(name, piece, out_dir, w, h, fps, ctx):
    """NAME.png, a contact sheet, and with ffmpeg on PATH NAME.mp4. Returns the files written."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    made = [out_dir / f"{name}.png"]
    sheet(piece, w, h, ctx).write_to_png(str(made[0]))
    if not shutil.which("ffmpeg"):
        return made
    mp4, ew, eh = out_dir / f"{name}.mp4", w - w % 2, h - h % 2           # yuv420p wants even sides
    proc = subprocess.Popen(["ffmpeg", "-loglevel", "error", "-y", "-f", "rawvideo", "-pix_fmt", "bgra", "-s", f"{ew}x{eh}",
                             "-r", str(fps), "-i", "-", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "18", str(mp4)],
                            stdin=subprocess.PIPE)
    try:
        for i in range(round(_seconds(piece) * fps) + 1):                 # one frame past the end: a sequence ends on the desk
            proc.stdin.write(bytes(over_desk(frame(piece, i / fps, ew, eh, ctx)).get_data()))
    except BrokenPipeError:                                               # ffmpeg gave up; its own message says why
        pass
    finally:
        proc.stdin.close()
        proc.wait()
    if proc.returncode == 0:
        made.append(mp4)
    return made


def render_motion(out, only=None, size=(1720, 720), fps=30):
    """Every piece (or the one named) as a contact sheet and an mp4 in `out`; a loop for one lap. KeyError for an
    unknown name."""
    known = everything()
    if only is not None and only not in known:
        raise KeyError(only)
    w, h = size
    ctx, made = fixture_ctx(), []
    for name, cls in known.items():
        if only not in (None, name):
            continue
        piece = cls()
        files = write(name, piece, out, w, h, fps, ctx)
        start = time.perf_counter()
        frame(piece, piece.still, w, h, ctx)
        draw = 1000 * (time.perf_counter() - start)
        print(f"{name}: {', '.join(p.name for p in files)} at {w}x{h}; a frame takes {draw:.0f} ms to draw offline, "
              f"{build_ms(piece, w, h, ctx):.2f} ms to build live")
        made += files
    return made
