"""The top bar (board AE1): skewed workspace tags + window title on the left, clock badge in the
centre, tray icons, now-playing, resource tags (CPU / RAM / network), date / volume / custom buttons / star on the right."""
import subprocess
import time

from . import gtkutil  # noqa: F401  (pins GTK 4 before any gi.repository import)

from gi.repository import GLib, Gtk, Pango

from . import draw as d
from .gtkutil import layer_window


class Bar:
    def __init__(self, app, gdk_monitor, connector, cfg, hypr):
        self.cfg, self.hypr, self.connector = cfg, hypr, connector
        self.tray = getattr(app, "tray", None)
        self.h = int(cfg["bar"]["height"])
        self.win = layer_window(app, gdk_monitor, "top", "eva-bar", anchors=("top", "left", "right"),
                                exclusive=self.h, keyboard="none", passthrough=False, height=self.h)
        self.area = Gtk.DrawingArea()
        self.area.set_content_height(self.h)
        self.area.set_draw_func(self._draw)
        self.win.set_child(self.area)
        click = Gtk.GestureClick()
        click.set_button(0)
        click.connect("pressed", self._click)
        self.area.add_controller(click)
        scroll = Gtk.EventControllerScroll.new(Gtk.EventControllerScrollFlags.VERTICAL)
        scroll.connect("scroll", self._scroll)
        self.area.add_controller(scroll)
        motion = Gtk.EventControllerMotion()
        motion.connect("motion", lambda c, x, y: setattr(self, "pointer_x", x))
        self.area.add_controller(motion)
        self.pointer_x = 0
        self.hits = []
        self.state = {"tags": [], "special": False, "title": "", "clock": "--:--", "date": "", "volume": None, "muted": False,
                      "resources": None, "music": None, "active": frozenset(), "tray": []}

    def update(self, **kw):
        changed = any(self.state.get(k) != v for k, v in kw.items())
        if "clock" in kw and self.state.get("clock") not in (None, "--:--", kw["clock"]) \
                and self.cfg["overlays"].get("minute_flip", True):
            self.flip = (self.state["clock"], kw["clock"], time.monotonic())
            self._flip_tick()
        self.state.update(kw)
        if changed:
            self.area.queue_draw()

    FLIP_MS = 120

    def _flip_tick(self):
        self.area.queue_draw()
        if getattr(self, "flip", None) and (time.monotonic() - self.flip[2]) * 1000 < self.FLIP_MS:
            GLib.timeout_add(16, self._flip_tick)
        else:
            self.flip = None
        return False

    def set_visible(self, on):
        self.win.set_visible(on)

    # ---------------------------------------------------------------- drawing
    _dot_cache = {}

    def _dots(self, u):
        """A repeating halftone tile: one purple dot per 7 px cell, cached per bar scale."""
        import cairo
        key = round(u, 3)
        if key not in self._dot_cache:
            step = max(4, int(round(7 * u)))
            tile = cairo.ImageSurface(cairo.FORMAT_ARGB32, step, step)
            tc = cairo.Context(tile)
            d.rgba(tc, d.CLARET, 0.28)
            tc.arc(step / 2, step / 2, max(0.8, 1.1 * u), 0, 6.2832)
            tc.fill()
            pat = cairo.SurfacePattern(tile)
            pat.set_extend(cairo.EXTEND_REPEAT)
            self._dot_cache[key] = pat
        return self._dot_cache[key]

    def _draw(self, area, cr, w, h):
        u = h / 56
        th = 40 * u
        y = (h - th) / 2 - 2 * u
        self.hits = []
        st = self.state
        ground = float(self.cfg["bar"].get("opacity", 0.8))
        motif = str(self.cfg["bar"].get("motif", "both"))
        if ground > 0:                                   # the bar's own ground, so it reads on any wallpaper
            d.rgba(cr, d.INK, ground)
            cr.rectangle(0, 0, w, h)
            cr.fill()
        if motif in ("dots", "both"):                    # the halftone screen, purple on ink
            cr.save()
            cr.rectangle(0, 0, w, h - 3 * u)
            cr.clip()
            cr.set_source(self._dots(u))
            cr.paint()
            cr.restore()
        if motif in ("hazard", "both"):                  # the stage band along the bottom edge
            d.hazard(cr, 0, h - 3 * u, w, 3 * u, d.CLARET, d.col("ink4"), period=14 * u)
        elif ground > 0:
            d.rgba(cr, d.col("ink4"), min(1.0, ground + 0.06))
            cr.rectangle(0, h - 2 * u, w, 2 * u)
            cr.fill()

        nerv = True
        pad = 24 * u

        def tag(x, label, fill, fg, size=20, under=None, min_w=44, max_w=None, italic=None, mono=False):
            lay = d.layout(cr, label, d.F_META, (size - 4) * u) if mono else d.display(cr, label, size * u, italic=italic)
            tw, tht = d.text_size(lay)
            if max_w and tw + pad > max_w:
                d.ellipsize(lay, max_w - pad)
                tw = max_w - pad
            bw = max(min_w * u, tw + pad)
            d.block(cr, x, y, bw, th, fill, under=under, under_h=4 * u)
            d.draw_text(cr, lay, x + (bw - tw) / 2, y + (th - tht) / 2, fg)
            return bw

        # EMERGENCY (nerv): anything hot or urgent turns the bar into a NERV warning strip
        res = st["resources"] or {}
        hot = (res.get("cpu") is not None and res.get("cpu") >= 90) or (res.get("mem_pct") or 0) >= 90
        emergency = nerv and (hot or any(state == "urgent" for _, state in st["tags"]))
        if emergency:
            d.hazard(cr, 0, 0, w, 6 * u, d.LED, d.INK, period=32 * u)

        # left: workspaces
        x = 16 * u
        for n, state in st["tags"]:
            fill, fg, under = {
                "active": (d.BONE, d.INK, None),
                "occupied": (d.INK if nerv else d.INK, d.BONE, d.CLARET),
                "urgent": (d.LED, d.INK, None),
            }.get(state, (d.INK, d.DIM, None))
            if nerv and state == "empty":
                fill = None
            bw = tag(x, f"{n:02d}" if nerv and isinstance(n, int) else str(n), fill or (0, 0, 0, 0), fg, under=under)
            self.hits.append((x, x + bw, ("ws", n)))
            x += bw + 4 * u
        if st["special"]:
            bw = tag(x, "S", d.GOLD, d.INK)
            x += bw + 4 * u

        # centre: clock badge (claret, bone border, hard black shadow; nerv: a bone title block, orange in an emergency)
        lay = d.layout(cr, st["clock"], d.F_DIGITS, 30 * u, weight=Pango.Weight.HEAVY)
        tw, tht = d.text_size(lay)
        bw, bh = tw + 56 * u, 44 * u
        bx, by = (w - bw) / 2, (h - bh) / 2 - 3 * u
        if True:
            fill, shadow = (d.LED, d.BONE) if emergency else (d.BONE, d.CLARET)
            d.block(cr, bx, by, bw, bh, fill, shadow=shadow, shadow_off=(6 * u, 6 * u))
            flip = getattr(self, "flip", None)
            if flip and (time.monotonic() - flip[2]) * 1000 < self.FLIP_MS:
                # the minute flip: the old digits slide up out of the badge, the new ones in from below
                k = min(1.0, (time.monotonic() - flip[2]) * 1000 / self.FLIP_MS)
                k = k * k * (3 - 2 * k)
                old = d.layout(cr, flip[0], d.F_DIGITS, 30 * u, weight=Pango.Weight.HEAVY)
                cr.save()
                cr.rectangle(bx, by, bw, bh)
                cr.clip()
                d.draw_text(cr, old, bx + (bw - tw) / 2, by + (bh - tht) / 2 - bh * k, d.INK)
                d.draw_text(cr, lay, bx + (bw - tw) / 2, by + (bh - tht) / 2 + bh * (1 - k), d.INK)
                cr.restore()
            else:
                d.draw_text(cr, lay, bx + (bw - tw) / 2, by + (bh - tht) / 2, d.INK)
        self.hits.append((bx, bx + bw, ("clock",)))
        centre_left = bx

        # title tag grows to the right of the workspaces, never into the badge
        if st["title"]:
            tx = x + 6 * u
            max_w = centre_left - 30 * u - tx
            if max_w > 80 * u:
                bw = tag(tx, st["title"].upper(), d.CLARET, d.BONE, size=16, min_w=0, max_w=max_w, italic=False)
                self.hits.append((tx, tx + bw, ("title",)))

        # right: star, volume, date, then the resource tags (laid out from the right edge)
        rx = w - 16 * u
        segs = [("star", "★", d.INK, d.GOLD, None)]
        for btn in self.cfg["bar"].get("buttons", []):
            on = btn.get("name") in st.get("active", ())
            segs.append((btn.get("name", ""), btn.get("label", "?"), d.LED if on else d.INK, d.INK if on else d.GOLD,
                         None if on else d.CLARET))
        if st["volume"] is not None:
            label = "MUTE" if st["muted"] else f"VOL {st['volume']}"
            segs.append(("volume", label, d.CLARET, d.BONE, None))
        if st["date"]:
            segs.append(("date", st["date"], d.BONE, d.INK, None))
        groups = [segs, resource_tags(st["resources"], nerv), music_tags(st.get("music"))]
        first = True
        for gi, group in enumerate(groups):
            if not group:
                continue
            if not first:
                rx -= 12 * u                     # resources and now-playing are their own groups
            first = False
            for name, label, fill, fg, under in group:
                mono = nerv and gi > 0           # MAGI readouts and now playing in the terminal face
                lay = d.layout(cr, label, d.F_META, 16 * u) if mono else d.display(cr, label, 20 * u)
                tw, tht = d.text_size(lay)
                max_tw = 360 * u if name == "music" else None
                if max_tw and tw > max_tw:
                    d.ellipsize(lay, max_tw)
                    tw = max_tw
                bw = max(44 * u, tw + pad)
                rx -= bw
                d.block(cr, rx, y, bw, th, fill, under=under, under_h=4 * u)
                d.draw_text(cr, lay, rx + (bw - tw) / 2, y + (th - tht) / 2, fg)
                self.hits.append((rx, rx + bw, (name,)))
                rx -= 4 * u

        # tray: app icons in one ink tag, leftmost of the right side
        icons = st.get("tray") or []
        if icons:
            rx -= 12 * u
            isz, step = 24 * u, 32 * u
            bw = len(icons) * step + 24 * u
            rx -= bw
            d.block(cr, rx, y, bw, th, d.INK, under=d.CLARET, under_h=4 * u)
            ix = rx + 12 * u + (step - isz) / 2
            for key, surf, title in icons:
                if surf is not None:
                    d.paint_image(cr, surf, ix, y + (th - isz) / 2, isz, isz)
                else:                                     # no icon: the app's initial
                    lay = d.display(cr, (title or "?")[:1].upper(), 18 * u, italic=False)
                    tw, tht = d.text_size(lay)
                    d.draw_text(cr, lay, ix + (isz - tw) / 2, y + (th - tht) / 2, d.BONE)
                self.hits.append((ix - (step - isz) / 2, ix + isz + (step - isz) / 2, ("tray", key)))
                ix += step

    # ---------------------------------------------------------------- input
    def _hit(self, x):
        for x0, x1, what in self.hits:
            pad = 0 if what[0] == "tray" else 6               # tray icons sit edge to edge
            if x0 - pad <= x <= x1 + pad:
                return what
        return None

    def _click(self, gesture, n, x, y):
        what = self._hit(x)
        button = gesture.get_current_button()
        if not what:
            return
        if what[0] == "ws":
            self.hypr.focus_workspace(what[1])
        elif what[0] == "tray" and self.tray:
            if button == 3:
                self.tray.menu(what[1], self.area, x, y)
            elif button == 2:
                self.tray.secondary(what[1], x, y)
            else:
                self.tray.activate(what[1], self.area, x, y)
        elif what[0] == "volume":
            if button == 2:
                _run("wpctl set-mute @DEFAULT_AUDIO_SINK@ toggle")
            elif button == 1 and self.cfg["bar"]["actions"].get("volume"):
                _run(self.cfg["bar"]["actions"]["volume"])
        elif self._button(what[0]):
            btn = self._button(what[0])
            cmd = btn.get("right_action") if button == 3 else btn.get("middle_action") if button == 2 else btn.get("action")
            if cmd:
                _run(cmd)
        elif what[0] == "music" and button == 2:
            _run(f"playerctl -p {self.cfg['bar']['music_players']} play-pause")
        else:
            cmd = self.cfg["bar"]["actions"].get(what[0], "")
            if cmd:
                _run(cmd)

    def _button(self, name):
        return next((b for b in self.cfg["bar"].get("buttons", []) if b.get("name") == name), None)

    def _scroll(self, ctrl, dx, dy):
        what = self._hit(self.pointer_x)
        if what and what[0] == "volume":
            _run(f"wpctl set-volume -l 1 @DEFAULT_AUDIO_SINK@ 5%{'-' if dy > 0 else '+'}")
        else:
            self.hypr.focus_workspace("m+1" if dy > 0 else "m-1")
        return True

    def destroy(self):
        self.win.destroy()


def resource_tags(res, nerv=False):
    """Right-to-left (name, label, fill, fg, underline) tags for the resource readout.

    res: {"cpu": percent|None, "mem": "9.8G", "mem_pct": 31, "net": "lan|wifi|vpn|none", "down": "1.2M",
    "show": ["cpu", "mem", "net"]}; ink tags with a claret underline, LED red when a value runs hot.
    nerv: the three MAGI computers read them out (MAGI·1 CPU 09%)."""
    if not res:
        return []
    tags = {}
    m1, m2, m3 = ("MAGI·1 ", "MAGI·2 ", "MAGI·3 ") if nerv else ("", "", "")
    cpu = res.get("cpu")
    hot = cpu is not None and cpu >= 90
    cpu_label = "CPU --" if cpu is None else (f"CPU {cpu:02d}%" if nerv else f"CPU {cpu}%")
    tags["cpu"] = ("cpu", m1 + cpu_label, d.LED if hot else d.INK, d.INK if hot else d.BONE, None if hot else d.CLARET)
    hot = (res.get("mem_pct") or 0) >= 90
    tags["mem"] = ("mem", m2 + f"RAM {res.get('mem', '--')}", d.LED if hot else d.INK, d.INK if hot else d.BONE,
                   None if hot else d.CLARET)
    kind = res.get("net") or "none"
    if kind == "none":
        tags["net"] = ("net", m3 + "OFFLINE", d.INK, d.DIM, None)
    else:
        name = {"wifi": "WIFI", "vpn": "VPN"}.get(kind, "LAN")
        tags["net"] = ("net", m3 + f"{name} ↓{res.get('down', '0K')}", d.INK, d.BONE, d.CLARET)
    return [tags[k] for k in reversed(res.get("show", ["cpu", "mem", "net"])) if k in tags]


def music_tags(music):
    """The now-playing tag: ▶ / II and the title, gold while playing, dim when paused; none without a player."""
    if not music or not music.get("status"):
        return []
    playing = music["status"] == "Playing"
    label = f"{'▶' if playing else 'II'} {music.get('title', '').upper()}"
    return [("music", label, d.INK, d.GOLD if playing else d.DIM, d.CLARET if playing else None)]


def _run(cmd):
    subprocess.Popen(cmd, shell=True, start_new_session=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
