"""The screenshot tool: the screen freezes into a dimmed halftone page and your pick
becomes a manga panel (bone frame, ink outline, hard claret shadow, speed lines), then an impact frame fires.

Drag = a region, click = the window under the cursor, F / Return = the whole monitor, Esc / right click = cancel.
Hold Shift as you finish to open the shot in an editor too. Every shot is copied to the clipboard and saved.
"""
import math
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

import cairo

from . import gtkutil  # noqa: F401  (pins GTK 4 before any gi.repository import)

from gi.repository import Gdk, GLib, Gtk

from . import draw as d
from .gtkutil import layer_window, monitors

FLASH_MS = 340


def shots_dir(cfg):
    folder = cfg.get("folder") or ""
    if folder:
        return Path(folder).expanduser()
    try:
        pics = subprocess.run(["xdg-user-dir", "PICTURES"], capture_output=True, text=True, timeout=2).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        pics = ""
    return Path(pics or Path.home() / "Pictures") / "Screenshots"


def norm(x0, y0, x1, y1):
    return min(x0, x1), min(y0, y1), abs(x1 - x0), abs(y1 - y0)


def clip_rect(r, w, h):
    """(x, y, w, h) clipped to a w x h monitor, or None when nothing is left."""
    x0, y0 = max(0, r[0]), max(0, r[1])
    x1, y1 = min(w, r[0] + r[2]), min(h, r[1] + r[3])
    return (x0, y0, x1 - x0, y1 - y0) if x1 - x0 >= 2 and y1 - y0 >= 2 else None


def window_at(clients, visible_ws, gx, gy):
    """The window under a global point: floating ones first, then the most recently focused."""
    hits = [c for c in clients
            if c.get("mapped", True) and not c.get("hidden") and c.get("workspace", {}).get("id") in visible_ws
            and c["at"][0] <= gx < c["at"][0] + c["size"][0] and c["at"][1] <= gy < c["at"][1] + c["size"][1]]
    hits.sort(key=lambda c: (not c.get("floating"), c.get("focusHistoryID", 99)))
    return hits[0] if hits else None


def backdrop(frozen, w, h):
    """The frozen screen as a dimmed page (ink wash + claret dot screen), rendered once per shot."""
    tile = cairo.ImageSurface(cairo.FORMAT_ARGB32, 9, 9)
    tc = cairo.Context(tile)
    d.rgba(tc, d.CLARET, 0.30)
    tc.arc(4.5, 4.5, 1.5, 0, 2 * math.pi)
    tc.fill()
    dots = cairo.SurfacePattern(tile)
    dots.set_extend(cairo.EXTEND_REPEAT)
    surf = cairo.ImageSurface(cairo.FORMAT_RGB24, w, h)
    cr = cairo.Context(surf)
    cr.scale(w / frozen.get_width(), h / frozen.get_height())
    cr.set_source_surface(frozen, 0, 0)
    cr.paint()
    cr.identity_matrix()
    d.rgba(cr, d.INK, 0.70)
    cr.paint()
    cr.set_source(dots)
    cr.paint()
    return surf


class Shot:
    def __init__(self, app, cfg, hypr):
        self.app, self.cfg, self.hypr = app, cfg, hypr
        self.mons = []
        self.active = False

    # ---------------------------------------------------------------- start / stop
    def start(self):
        if self.active:
            return "busy"
        if not shutil.which("grim"):
            return "grim is not installed"
        self.tmp = Path(tempfile.mkdtemp(prefix="eva-shot-"))
        gdk = monitors()
        mons = [m for m in (self.hypr.j("monitors") or []) if not m.get("disabled") and m["name"] in gdk]
        # freeze every monitor before anything of ours is on screen
        for m in mons:
            out = self.tmp / f"{m['name']}.png"
            if subprocess.run(["grim", "-o", m["name"], str(out)], capture_output=True, timeout=5).returncode:
                self._cleanup()
                return "grim failed"
        clients = self.hypr.j("clients") or []
        self.visible_ws = {m["activeWorkspace"]["id"] for m in mons} | \
                          {m.get("specialWorkspace", {}).get("id") for m in mons if m.get("specialWorkspace", {}).get("id")}
        self.clients = clients
        self.mons = []
        for i, m in enumerate(mons):
            scale = m.get("scale") or 1
            lw, lh = round(m["width"] / scale), round(m["height"] / scale)
            frozen = cairo.ImageSurface.create_from_png(str(self.tmp / f"{m['name']}.png"))
            win = layer_window(self.app, gdk[m["name"]], "overlay", "eva-shot",
                               keyboard="exclusive" if m.get("focused") else "none", passthrough=False)
            area = Gtk.DrawingArea()
            area.set_cursor_from_name("crosshair")
            area.set_draw_func(lambda a, cr, w, h, i=i: self._draw(i, cr, w, h))
            win.set_child(area)
            drag = Gtk.GestureDrag()
            drag.set_button(1)
            drag.connect("drag-begin", lambda g, x, y, i=i: self._begin(i, x, y))
            drag.connect("drag-update", lambda g, dx, dy, i=i: self._update(i, dx, dy))
            drag.connect("drag-end", lambda g, dx, dy, i=i: self._end(i, dx, dy, g))
            area.add_controller(drag)
            right = Gtk.GestureClick()
            right.set_button(3)
            right.connect("pressed", lambda *a: self.cancel())
            area.add_controller(right)
            motion = Gtk.EventControllerMotion()
            motion.connect("motion", lambda c, x, y, i=i: self._hover(i, x, y))
            area.add_controller(motion)
            keys = Gtk.EventControllerKey()
            keys.connect("key-pressed", self._key)
            win.add_controller(keys)
            self.mons.append({"m": m, "w": lw, "h": lh, "scale": scale, "frozen": frozen, "win": win,
                              "area": area, "bg": backdrop(frozen, lw, lh)})
        self.sel = None          # (monitor index, x0, y0, x1, y1) while dragging
        self.hover = None        # (monitor index, rect, title)
        self.pointer = (next((i for i, x in enumerate(self.mons) if x["m"].get("focused")), 0), 0, 0)
        self.flash = None
        self.active = True
        for x in self.mons:
            x["win"].set_visible(True)
            x["win"].present()
        self.idle_id = GLib.timeout_add_seconds(60, lambda: (self.cancel(), False)[1])   # never left holding keys
        return "ok"

    def cancel(self):
        if not self.active:
            return
        for x in self.mons:
            x["win"].destroy()
        self.mons = []
        self.active = False
        if getattr(self, "idle_id", None):
            GLib.source_remove(self.idle_id)
            self.idle_id = None
        self._cleanup()

    def _cleanup(self):
        shutil.rmtree(getattr(self, "tmp", ""), ignore_errors=True) if getattr(self, "tmp", None) else None

    # ---------------------------------------------------------------- input
    def _redraw(self):
        for x in self.mons:
            x["area"].queue_draw()

    def _hover(self, i, x, y):
        self.pointer = (i, x, y)
        if self.sel or self.flash:
            return
        m = self.mons[i]["m"]
        c = window_at(self.clients, self.visible_ws, m["x"] + x, m["y"] + y)
        rect = clip_rect((c["at"][0] - m["x"], c["at"][1] - m["y"], c["size"][0], c["size"][1]),
                         self.mons[i]["w"], self.mons[i]["h"]) if c else None
        hover = (i, rect, c.get("class", "") or c.get("title", "")) if rect else None
        if hover != self.hover:
            self.hover = hover
            self._redraw()

    def _begin(self, i, x, y):
        if not self.flash:
            self.sel = (i, x, y, x, y)

    def _update(self, i, dx, dy):
        if self.sel and not self.flash:
            _, x0, y0, _, _ = self.sel
            self.sel = (i, x0, y0, x0 + dx, y0 + dy)
            self._redraw()

    def _end(self, i, dx, dy, gesture):
        if not self.sel or self.flash:
            return
        _, x0, y0, _, _ = self.sel
        self.sel = None
        shift = bool(gesture.get_current_event_state() & Gdk.ModifierType.SHIFT_MASK)
        if abs(dx) < 4 and abs(dy) < 4:                       # a click: the window under it
            if self.hover and self.hover[0] == i:
                self._fire(i, self.hover[1], shift)
            return
        rect = clip_rect(norm(x0, y0, x0 + dx, y0 + dy), self.mons[i]["w"], self.mons[i]["h"])
        if rect:
            self._fire(i, rect, shift)

    def _key(self, ctrl, keyval, keycode, state):
        name = Gdk.keyval_name(keyval) or ""
        if name == "Escape":
            self.cancel()
        elif name in ("f", "F", "Return", "KP_Enter") and not self.flash:
            i = self.pointer[0]
            self._fire(i, (0, 0, self.mons[i]["w"], self.mons[i]["h"]), bool(state & Gdk.ModifierType.SHIFT_MASK))
        return True

    # ---------------------------------------------------------------- the shot
    def _fire(self, i, rect, edit=False):
        x = self.mons[i]
        s = x["scale"]
        px = [round(v * s) for v in rect]
        out = cairo.ImageSurface(cairo.FORMAT_ARGB32, max(1, px[2]), max(1, px[3]))
        cr = cairo.Context(out)
        cr.set_source_surface(x["frozen"], -px[0], -px[1])
        cr.paint()
        folder = shots_dir(self.cfg["shot"])
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / time.strftime("eva_%Y-%m-%d_%H-%M-%S.png")
        out.write_to_png(str(path))
        if shutil.which("wl-copy"):
            with open(path, "rb") as f:
                subprocess.Popen(["wl-copy", "--type", "image/png"], stdin=f, start_new_session=True,
                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.flash = (i, rect, time.monotonic())
        self.hover = None
        GLib.timeout_add(16, self._flash_tick)
        if shutil.which("notify-send"):
            subprocess.Popen(["notify-send", "-a", "eva-desk", "-i", str(path), "Screenshot",
                              f"Copied to the clipboard · saved as {path.name}"], start_new_session=True,
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        editor = self.cfg["shot"].get("editor") or ""
        if edit and editor:
            self.hypr.exec(editor.replace("{}", str(path)))

    def _flash_tick(self):
        if not self.flash:
            return False
        if (time.monotonic() - self.flash[2]) * 1000 >= FLASH_MS:
            self.cancel()
            return False
        self._redraw()
        return True

    # ---------------------------------------------------------------- drawing
    def _draw(self, i, cr, w, h):
        x = self.mons[i]
        sx, sy = w / x["frozen"].get_width(), h / x["frozen"].get_height()
        cr.set_source_surface(x["bg"], 0, 0)
        cr.paint()

        panel, label, t = None, None, None
        if self.flash and self.flash[0] == i:
            panel, t = self.flash[1], min(1.0, (time.monotonic() - self.flash[2]) * 1000 / FLASH_MS)
        elif self.sel and self.sel[0] == i:
            panel = norm(*self.sel[1:])
            label = f"{round(panel[2] * x['scale'])} × {round(panel[3] * x['scale'])}"
        elif self.hover and self.hover[0] == i and not self.sel:
            panel = self.hover[1]
            label = f"{self.hover[2].upper()}  ·  CLICK"

        if panel and panel[2] > 1 and panel[3] > 1:
            self._panel(cr, x, panel, sx, sy, w, h, label, t)
        if not self.flash and i == self.pointer[0]:
            self._hint(cr, w, h)

    def _panel(self, cr, x, r, sx, sy, w, h, label, t):
        px, py, pw, ph = r
        cx, cy = px + pw / 2, py + ph / 2
        # speed lines outside the panel only
        cr.save()
        cr.rectangle(0, 0, w, h)
        cr.rectangle(px - 6, py - 6, pw + 12, ph + 12)
        cr.set_fill_rule(cairo.FILL_RULE_EVEN_ODD)
        cr.clip()
        # a hazard frame round the panel and a faint A.T. field line behind it
        k = 2.2 if t is not None else 1.0
        d.hazard(cr, px - 18, py - 18, pw + 36, ph + 36, d.CLARET[:3] + (min(1.0, 0.55 * k),), None, period=28)
        d.rgba(cr, d.GOLD, 0.35 * k)
        cr.set_line_width(2)
        cr.rectangle(px - 30, py - 30, pw + 60, ph + 60)
        cr.stroke()
        cr.restore()
        # hard claret shadow, the frozen picture at full brightness, bone frame with an ink outline
        off = 12
        d.rgba(cr, d.CLARET)
        cr.rectangle(px + off, py + off, pw, ph)
        cr.fill()
        cr.save()
        cr.rectangle(px, py, pw, ph)
        cr.clip()
        cr.scale(sx, sy)
        cr.set_source_surface(x["frozen"], 0, 0)
        cr.paint()
        cr.restore()
        cr.set_line_join(cairo.LINE_JOIN_MITER)
        d.rgba(cr, d.INK)
        cr.set_line_width(8)
        cr.rectangle(px - 4, py - 4, pw + 8, ph + 8)
        cr.stroke()
        d.rgba(cr, d.BONE)
        cr.set_line_width(4)
        cr.rectangle(px - 2, py - 2, pw + 4, ph + 4)
        cr.stroke()
        if t is not None:                                     # the impact frame
            d.rgba(cr, d.BONE, 0.75 * (1 - t) ** 2)
            cr.rectangle(px, py, pw, ph)
            cr.fill()
            size = max(36, min(140, min(pw, ph) * 0.28)) * (1.25 - 0.25 * t)
            lay = d.display(cr, "SNAP!", size)
            tw, th = d.text_size(lay)
            alpha = 1 if t < 0.7 else (1 - t) / 0.3
            d.draw_text(cr, lay, cx - tw / 2 + size * 0.06, cy - th / 2 + size * 0.06, d.CLARET[:3] + (alpha,))
            d.draw_text(cr, lay, cx - tw / 2, cy - th / 2, d.BONE[:3] + (alpha,))
            return
        if label:
            lay = d.layout(cr, label, d.F_META, 15, spacing=2)
            tw, th = d.text_size(lay)
            bw, bh = tw + 28, th + 8
            ly = py - bh - 10 if py - bh - 10 > 4 else py + 10
            lx = min(max(4, px - 2), w - bw - 4)
            d.block(cr, lx, ly, bw, bh, d.BONE, shadow=d.CLARET, shadow_off=(4, 4))
            d.draw_text(cr, lay, lx + (bw - tw) / 2, ly + (bh - th) / 2, d.INK)

    def _hint(self, cr, w, h):
        text = "DRAG  ·  CLICK A WINDOW  ·  F WHOLE SCREEN  ·  SHIFT EDIT  ·  ESC"
        lay = d.layout(cr, text, d.F_META, 15, spacing=3)
        tw, th = d.text_size(lay)
        bw, bh = tw + 40, th + 12
        bx, by = (w - bw) / 2, h - bh - 36
        d.block(cr, bx, by, bw, bh, d.INK, shadow=d.CLARET, shadow_off=(10, 10), border=d.BONE, border_w=2)
        d.draw_text(cr, lay, bx + (bw - tw) / 2, by + (bh - th) / 2, d.GOLD)
        # title-card corner: 撮影 (capture) block with the MAGI readout under it
        tag = d.layout(cr, "撮影 · SNAP", d.F_DISPLAY, 28, weight=d.DISPLAY_WEIGHT)
        tw, th = d.text_size(tag)
        d.block(cr, 36, 36, tw + 36, th + 10, d.BONE, shadow=d.CLARET, shadow_off=(8, 8))
        d.draw_text(cr, tag, 36 + 18, 36 + 5, d.INK)
        sub = d.layout(cr, "SCREEN FROZEN · PATTERN BLUE", d.F_META, 13, spacing=3)
        d.draw_text(cr, sub, 36, 36 + th + 10 + 16, d.GOLD)
        d.hazard(cr, 0, h - 14, w, 14, d.CLARET, d.INK, period=40)
