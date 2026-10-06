"""Offline previews (no windows, no compositor): `eva-desk --render DIR`."""
import time
from pathlib import Path

import cairo

from . import draw as d
from . import scenes as S


class _App:
    """Stand-in for a GIO AppInfo in launcher previews."""

    def __init__(self, name, desc):
        self.n, self.desc = name, desc

    def get_display_name(self):
        return self.n

    def get_name(self):
        return self.n

    def get_description(self):
        return self.desc

    def get_id(self):
        return self.n.lower() + ".desktop"


def render_all(cfg, out, w=3440, h=1440):
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)

    def save(name, width, height, fn):
        surf = cairo.ImageSurface(cairo.FORMAT_ARGB32, int(width), int(height))
        t = time.perf_counter()
        fn(cairo.Context(surf))
        surf.write_to_png(str(out / f"{name}.png"))
        print(f"{name}: {1000 * (time.perf_counter() - t):.0f} ms")

    from .config import stage_share
    gb, gh = S.Geometry(w, h, w * stage_share(cfg, w, h)), S.Geometry(w, h, 0)
    rig = S.HeraldRig()
    save("scene_figure", w, h, lambda cr: S.figure_scene(cr, gb))
    for t in (0.0, 0.1, 0.25, 0.5):
        save(f"figure_entry_{t}", w, h, lambda cr, t=t: S.figure_frame(cr, gb, t))
    for t in (0.0, 0.5, 1.0):
        save(f"herald_{t}", w, h, lambda cr, t=t: (S.herald_backdrop(cr, gh), rig.draw(cr, gh, t)))

    # overlays (nerv look): eye-catch frames, the alarm band, the cast strip, the power menu
    from . import overlays as O
    save("eyecatch", w, h, lambda cr: O.draw_eyecatch(cr, w, h, 3, "PROJECTS"))
    save("eyecatch_inverted", w, h, lambda cr: O.draw_eyecatch(cr, w, h, 3, "PROJECTS", True))
    save("alarm_band", w, 70, lambda cr: O.draw_band(cr, w, 70, {"app": "UPS", "summary": "On battery: 4 minutes left", "body": "Internal power only. Save your work; the desk shuts down at 1 minute."}))
    cast = [{"app": "kitty", "title": "~/Projects/eva-desk · nvim app.py", "ep": "EP 02 · WS 02"},
            {"app": "firefox", "title": "Hyprland wiki · Lua config", "ep": "EP 01 · WS 01"},
            {"app": "Claude", "title": "Hyprland purple/green NGE theme", "ep": "EP 03 · WS 03"},
            {"app": "thunar", "title": "~/Zotero", "ep": "EP 03 · WS 03"},
            {"app": "discord", "title": "#general", "ep": "SIDE"},
            {"app": "Spotify", "title": "Walking on a Dream", "ep": "EP 07 · WS 07", "urgent": True}]
    save("alttab", w, h, lambda cr: O.draw_alttab(cr, w, h, cast, 0))
    save("power", w, h, lambda cr: O.draw_power(cr, w, h, 3, False, "9 WINDOWS OPEN · 2 EDITORS"))
    save("power_armed", w, h, lambda cr: O.draw_power(cr, w, h, 3, True, "9 WINDOWS OPEN · 2 EDITORS"))

    from . import frame
    save("frame", w, h, lambda cr: frame.draw_frame(cr, {"x": 300, "y": 160, "w": 1400, "h": 900, "cls": "kitty", "ws": 2, "floating": False}, cfg["frame"]))

    # the MFD drawing language: a screen with rows, a key row and lamps, and a lone segbar with a peak
    save("mfd_sampler", 1200, 700, lambda cr: _mfd_sampler(cr, 1200, 700))

    # the sound panel, from the audiostate fixture, and its NO SIGNAL screen (an installed copy
    # has no tests/ folder: skip the panel there rather than stop the whole render)
    import json
    from .mfd.sound import SoundModel, draw_sound
    fixture_path = Path(__file__).resolve().parent.parent / "tests" / "fixtures" / "audiostate.json"
    if fixture_path.exists():
        fixture = json.loads(fixture_path.read_text())
        quick = {"dnd": False, "night": True, "power": "balanced"}
        save("sound", 1100, 1300, lambda cr: draw_sound(cr, 0, 0, 1100, 1300, SoundModel(fixture, quick), False))
        save("sound_no_signal", 1100, 1300, lambda cr: draw_sound(cr, 0, 0, 1100, 1300, SoundModel(None, quick), True))
    else:
        print("sound: skipped (no tests/fixtures/audiostate.json in this copy)")

    # bar
    from .bar import Bar
    bar = Bar.__new__(Bar)
    bar.cfg = dict(cfg, bar=dict(cfg["bar"], buttons=cfg["bar"]["buttons"] or [{"name": "magi", "label": "MAGI"}]))
    bar.hits = []
    tags = [(n, "active" if n == 1 else "occupied" if n in (2, 3) else "urgent" if n == 7 else "empty")
            for n in range(1, int(cfg["bar"]["workspaces"]) + 1)]
    res = {"cpu": 12, "mem": "9.8G", "mem_pct": 31, "net": "lan", "down": "1.2M", "show": cfg["bar"]["resources"]}
    bar.state = {"tags": tags, "special": True, "title": "kitty — ~/Projects/eva-desk — nvim app.py",
                 "clock": "16:42", "date": "SAT 03", "volume": 68, "muted": False, "resources": res,
                 "music": {"status": "Playing", "title": "Walking on a Dream", "artist": "Empire of the Sun"},
                 "tray": [("a", None, "Discord"), ("b", None, "Steam"), ("c", None, "Network")]}
    bh = int(cfg["bar"]["height"])
    save("bar", w, bh, lambda cr: (d.rgba(cr, d.WINE_D), cr.paint(), bar._draw(None, cr, w, bh)))
    # the same bar under load: hot CPU (LED tag), offline network
    bar.state = dict(bar.state, resources=dict(res, cpu=97, net="none"), active=frozenset({"magi"}),
                     music={"status": "Paused", "title": "It's a Sin - 2018 Remaster", "artist": "Pet Shop Boys"})
    save("bar_hot", w, bh, lambda cr: (d.rgba(cr, d.WINE_D), cr.paint(), bar._draw(None, cr, w, bh)))

    # screenshot tool: hover a window, drag a region, the impact frame half way
    from . import config as C
    from .shot import Shot, backdrop
    import time as _t
    sh = Shot.__new__(Shot)
    frozen = cairo.ImageSurface(cairo.FORMAT_ARGB32, w, h)      # the frozen screen: the figure scene
    S.figure_scene(cairo.Context(frozen), gb)
    sh.mons = [{"m": {}, "w": w, "h": h, "scale": 1, "frozen": frozen, "bg": backdrop(frozen, w, h)}]
    sh.pointer, sh.sel, sh.flash = (0, 0, 0), None, None
    sh.hover = (0, (300, 160, 1400, 900), "kitty")
    save("shot_hover", w, h, lambda cr: sh._draw(0, cr, w, h))
    sh.hover, sh.sel = None, (0, 1700, 300, 2900, 1050)
    save("shot_drag", w, h, lambda cr: sh._draw(0, cr, w, h))
    sh.sel, sh.flash = None, (0, (1700, 300, 1200, 750), _t.monotonic() - 0.12)
    save("shot_flash", w, h, lambda cr: sh._draw(0, cr, w, h))

    # launcher
    from . import launcher as L
    lau = L.Launcher.__new__(L.Launcher)
    lau.cfg, lau.counts, lau.blink, lau.item_boxes = cfg, {"kitty.desktop": 214}, True, []
    lau.query, lau.sel = "term", 0
    lau.results = [("app", _App("Terminal", "GPU terminal")), ("app", _App("Termux-SSH", "")),
                   ("app", _App("Terminal Settings", "")), ("app", _App("Files", "")), ("web", "term")]
    lau.counts["terminal.desktop"] = 214
    save("launcher", w, h, lambda cr: (L._background(cr, w, h), lau._draw(None, cr, w, h)))


def _mfd_sampler(cr, w, h):
    """One MFD screen: three list rows, a key row and three lamps (off / on / hot), plus a lone
    segbar with a peak -- the sampler for the panel drawing language."""
    from .mfd import widgets as M

    d.rgba(cr, d.col("ink_deep"))
    cr.paint()
    cx, cy, cw, ch = M.screen(cr, 40, 40, w - 80, h - 140, "AUDIO OUTPUT", hot="HOT")

    items = [
        {"label": "AG346UCD", "sub": "HDMI · DEFAULT", "value": 0.68, "peak": None, "muted": False, "colour": None},
        {"label": "USB HEADSET", "sub": "USB · 48 kHz", "value": 0.42, "peak": 0.55, "muted": False, "colour": None},
        {"label": "HDMI MONITOR 2", "sub": "DISCONNECTED", "value": None, "peak": None, "muted": True, "colour": None},
    ]
    M.rows(cr, cx, cy, cw, items, selected=0, row_h=40)

    key_y = cy + ch - 26
    M.keyrow(cr, cx, key_y, ["MUTE", "UP", "DOWN"], active=1)

    lamp_y = key_y
    M.lamp(cr, cx + cw - 3 * 30, lamp_y, 16, False)
    M.lamp(cr, cx + cw - 2 * 30, lamp_y, 16, True)
    M.lamp(cr, cx + cw - 1 * 30, lamp_y, 16, True, hot=True)

    M.segbar(cr, 40, h - 70, w - 80, 14, 0.8, d.GOLD, peak=0.92)
