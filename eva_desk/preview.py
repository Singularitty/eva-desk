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
    gb, gk, gh = S.Geometry(w, h, w * stage_share(cfg, w, h)), S.Geometry(w, h, w * stage_share(cfg, w, h, "knight_stage")), S.Geometry(w, h, 0)
    castle = d.pixbuf_surface(str(d.asset_path("figures/castle.jpg")))
    rig = S.HeraldRig()
    save("scene_boxer", w, h, lambda cr: S.boxer_scene(cr, gb))
    save("scene_knight", w, h, lambda cr: S.knight_scene(cr, gk, castle))
    for t in (0.0, 0.1, 0.25, 0.5):
        save(f"boxer_entry_{t}", w, h, lambda cr, t=t: S.boxer_frame(cr, gb, t))
    save("flash_knight", w, h, lambda cr: S.knight_flash(cr, gk))
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
    frozen = d.pixbuf_surface(C.asset("rooftop"))
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
