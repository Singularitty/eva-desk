"""The Persona-style launcher (board AC2, "paper"): ransom-note query, a staircase of results with the
selected one huge at the top, and a card for the selection."""
import json
import math
import re
import shlex
import subprocess
import time
import urllib.parse

import cairo

from . import gtkutil  # noqa: F401  (pins GTK 4 before any gi.repository import)
from gi.repository import Pango, Gdk, Gio, GLib, Gtk

from . import draw as d
from .config import STATE_DIR
from .gtkutil import layer_window, rect, render_texture

def _palette():
    """The launcher colourway of the active theme, resolved to hex (roles -> colours, font roles -> faces)."""
    t = d.THEME
    c, f = t["colors"], t["fonts"]
    L = t["launcher"]
    cc = lambda r: c.get(r, r)
    ff = lambda r: f.get(r, r)
    return {
        "bg": cc(L["bg"]), "slab": cc(L["slab"]),
        "cur": cc(L["cur"]), "top": tuple(cc(x) for x in L["top"]),
        "items": [cc(x) for x in L["items"]],
        "card": tuple(cc(x) for x in L["card"]), "cshadow": cc(L["cshadow"]),
        "btn": [(cc(bg), cc(fg)) for bg, fg in L["btn"]],
    }


def C(h, a=1.0):
    return d.hexc(h, a)


class Launcher:
    def __init__(self, app, cfg, hypr):
        self.cfg, self.hypr, self.app = cfg, hypr, app
        self.win = layer_window(app, None, "overlay", "eva-launcher", keyboard="exclusive", passthrough=False)
        self.overlay = Gtk.Overlay()
        self.bg = Gtk.Picture()
        self.bg.set_can_shrink(True)
        self.bg.set_content_fit(Gtk.ContentFit.FILL)
        self.overlay.set_child(self.bg)
        self.area = Gtk.DrawingArea()
        self.area.set_draw_func(self._draw)
        self.overlay.add_overlay(self.area)
        self.win.set_child(self.overlay)
        keys = Gtk.EventControllerKey()
        keys.connect("key-pressed", self._key)
        self.win.add_controller(keys)
        click = Gtk.GestureClick()
        click.connect("pressed", self._click)
        self.area.add_controller(click)
        self.query, self.sel, self.results = "", 0, []
        self.apps, self.apps_at = [], 0
        self.bg_size = None
        self.item_boxes = []
        self.counts_file = STATE_DIR / "launches.json"
        try:
            self.counts = json.loads(self.counts_file.read_text())
        except (OSError, ValueError):
            self.counts = {}
        self.blink = True
        self.blink_id = None
        self.idle_id = None

    # ---------------------------------------------------------------- show / hide
    @property
    def visible(self):
        return self.win.get_visible()

    def toggle(self, gdk_monitor=None):
        self.hide() if self.visible else self.show(gdk_monitor)

    def show(self, gdk_monitor=None):
        from gi.repository import Gtk4LayerShell as LS
        if gdk_monitor is not None:
            LS.set_monitor(self.win, gdk_monitor)
            geo = gdk_monitor.get_geometry()
            self._ensure_bg(geo.width, geo.height, max(1, gdk_monitor.get_scale_factor()))
        if time.time() - self.apps_at > 30:
            self.apps = [a for a in Gio.AppInfo.get_all() if a.should_show()]
            self.apps_at = time.time()
        self.query, self.sel = "", 0
        self._filter()
        self.shown_at = time.monotonic() if self.cfg["overlays"].get("launcher_cut", True) else 0
        self.win.set_visible(True)
        self.win.present()
        if self.blink_id is None:
            self.blink_id = GLib.timeout_add(530, self._blink)
        self._arm_idle()

    def hide(self):
        self.win.set_visible(False)
        self.bg.set_paintable(None)
        self.bg_size = None
        for attr in ("blink_id", "idle_id"):
            if getattr(self, attr, None) is not None:
                GLib.source_remove(getattr(self, attr))
                setattr(self, attr, None)

    def _arm_idle(self):
        """Safety: the launcher holds the keyboard while open, so it never stays open unattended."""
        if getattr(self, "idle_id", None) is not None:
            GLib.source_remove(self.idle_id)
        self.idle_id = GLib.timeout_add_seconds(60, self._idle_timeout)

    def _idle_timeout(self):
        self.idle_id = None
        self.hide()
        return False

    def _blink(self):
        self.blink = not self.blink
        self.area.queue_draw()
        return True

    # ---------------------------------------------------------------- results
    def _filter(self):
        q = self.query.strip().lower()
        scored = []
        for a in self.apps:
            name = (a.get_display_name() or a.get_name() or "").strip()
            if not name:
                continue
            extra = " ".join(filter(None, [a.get_executable() or "", a.get_description() or "",
                                           getattr(a, "get_generic_name", lambda: "")() or ""])).lower()
            s = _score(q, name.lower(), extra)
            if s is None:
                continue
            s += min(self.counts.get(a.get_id() or name, 0), 60) * 0.6
            scored.append((s, name.lower(), a))
        scored.sort(key=lambda t: (-t[0], t[1]))
        self.results = [("app", a) for _, _, a in scored[:40]]
        if q.startswith(">") and len(q) > 1:
            self.results.insert(0, ("cmd", self.query.strip()[1:].strip()))
        if q:
            self.results.append(("web", self.query.strip()))
        self.sel = max(0, min(self.sel, len(self.results) - 1))
        self.area.queue_draw()

    def _label(self, item):
        kind, v = item
        if kind == "app":
            return (v.get_display_name() or v.get_name()).upper()
        if kind == "cmd":
            return f"RUN · {v}".upper()
        return f'SEARCH THE WEB FOR "{v}"'.upper()

    def _launch(self, item):
        kind, v = item
        ctx = Gdk.Display.get_default().get_app_launch_context()
        try:
            if kind == "app":
                key = v.get_id() or v.get_name()
                self.counts[key] = self.counts.get(key, 0) + 1
                self._save_counts()
                if v.get_id():
                    # through Hyprland, like a keybind: own stdio, window rules apply, not our child
                    self.hypr.exec("gtk-launch " + shlex.quote(v.get_id()))
                else:
                    v.launch([], ctx)
            elif kind == "cmd":
                self.hypr.exec(v)
            else:
                url = self.cfg["launcher"]["search_url"].replace("{}", urllib.parse.quote(v))
                self.hypr.exec("xdg-open " + shlex.quote(url))
        except GLib.Error as e:
            print("eva-desk: launch failed:", e, flush=True)
        self.hide()

    def _save_counts(self):
        try:
            self.counts_file.parent.mkdir(parents=True, exist_ok=True)
            self.counts_file.write_text(json.dumps(self.counts))
        except OSError:
            pass

    # ---------------------------------------------------------------- input
    def _key(self, ctrl, keyval, keycode, mods):
        self._arm_idle()
        name = Gdk.keyval_name(keyval) or ""
        ctrl_down = bool(mods & Gdk.ModifierType.CONTROL_MASK)
        if name == "Escape":
            self.hide()
        elif name in ("Return", "KP_Enter"):
            if self.results:
                self._launch(self.results[self.sel])
        elif name in ("Down", "Tab"):
            self.sel = min(self.sel + 1, max(0, len(self.results) - 1))
            self.area.queue_draw()
        elif name in ("Up", "ISO_Left_Tab"):
            self.sel = max(self.sel - 1, 0)
            self.area.queue_draw()
        elif name == "BackSpace":
            self.query = re.sub(r"\S*\s*$", "", self.query) if ctrl_down else self.query[:-1]
            self.sel = 0
            self._filter()
        elif ctrl_down and name.lower() == "u":
            self.query, self.sel = "", 0
            self._filter()
        else:
            ch = chr(Gdk.keyval_to_unicode(keyval)) if Gdk.keyval_to_unicode(keyval) else ""
            if ch and ch.isprintable() and not ctrl_down:
                self.query += ch
                self.sel = 0
                self._filter()
            else:
                return False
        return True

    def _click(self, gesture, n, x, y):
        for (x0, y0, x1, y1), idx in self.item_boxes:
            if x0 <= x <= x1 and y0 <= y <= y1:
                self._launch(self.results[idx])
                return
        self.hide()

    # ---------------------------------------------------------------- drawing
    def _ensure_bg(self, w, h, scale):
        if self.bg_size == (w, h, scale):
            return
        self.bg_size = (w, h, scale)
        tex = render_texture(w * scale, h * scale, lambda cr: _background(cr, w * scale, h * scale))
        self.bg.set_paintable(tex)

    # ---------------------------------------------------------------- drawing: an episode title card
    def _item_text(self, item):
        kind, v = item
        if kind == "app":
            title = v.get_display_name() or v.get_name()
            desc = v.get_description() or ""
            n = self.counts.get(v.get_id() or v.get_name(), 0)
            return title, desc, (f"opened {n} times" if n else "never opened"), (v.get_id() or "")
        if kind == "cmd":
            return "run", v, "shell command", ""
        return "search", v, "web search", self.cfg["launcher"]["search_url"].split("/")[2]

    def _draw(self, area, cr, w, h):
        s = h / 720
        p = _palette()
        self.item_boxes = []
        cut = time.monotonic() - getattr(self, "shown_at", 0)
        if cut < 0.08:                                   # the cut: 起動 on black, one inverted frame, then the card
            inverted = cut >= 0.04
            d.rgba(cr, C(p["slab"]) if inverted else C(p["bg"]))
            cr.paint()
            lay = d.layout(cr, "起動", d.F_DISPLAY, 120 * s, weight=d.DISPLAY_WEIGHT)
            tw, th = d.text_size(lay)
            d.draw_text(cr, lay, (w - tw) / 2, (h - th) / 2, C(p["bg"]) if inverted else C(p["slab"]))
            GLib.timeout_add(20, lambda: (self.area.queue_draw(), False)[1])
            return
        # vertical strip, left: 新世紀 in a bone column
        sx, sy, sw, sh = 36 * s, 40 * s, 64 * s, 640 * s
        d.block(cr, sx, sy, sw, sh, C(p["slab"]))
        chars = "新世紀"
        glyphs = [d.layout(cr, ch, d.F_DISPLAY, 40 * s, weight=d.DISPLAY_WEIGHT) for ch in chars]
        total = sum(d.text_size(g)[1] for g in glyphs) + 6 * s * (len(glyphs) - 1)
        gy = sy + (sh - total) / 2
        for g in glyphs:
            tw, th = d.text_size(g)
            d.draw_text(cr, g, sx + (sw - tw) / 2, gy, C(p["bg"]))
            gy += th + 6 * s
        # frame counter, top right
        n = len(self.results)
        lay = d.layout(cr, f"LAUNCHER · {n:02d} RESULTS", d.F_META, 14 * s, spacing=3 * s)
        tw, th = d.text_size(lay)
        d.draw_text(cr, lay, w - 48 * s - tw, 40 * s, d.GOLD)
        lay = d.layout(cr, "ENTER OPEN · TAB NEXT · ESC BACK", d.F_META, 14 * s, spacing=3 * s)
        tw, th2 = d.text_size(lay)
        d.draw_text(cr, lay, w - 48 * s - tw, 40 * s + th + 4 * s, d.GOLD)
        # the query as the episode title
        qx = 150 * s
        lay = d.layout(cr, f"EPISODE {max(1, self.sel + 1):02d}", d.F_META, 16 * s, spacing=6 * s)
        d.draw_text(cr, lay, qx, 72 * s, d.RED)
        q = (self.query[-18:] if self.query else "").upper()
        lay = d.layout(cr, q, d.F_DISPLAY, 168 * s, weight=d.DISPLAY_WEIGHT, spacing=-8 * s)
        tw, th = d.text_size(lay)
        d.draw_text(cr, lay, qx - 8 * s, 92 * s, C(p["top"][0]))
        if self.blink:
            caret = d.layout(cr, "_", d.F_DISPLAY, 168 * s, weight=d.DISPLAY_WEIGHT)
            d.draw_text(cr, caret, qx - 8 * s + tw, 92 * s, C(p["cur"]))
        plate = d.layout(cr, f"起動 · {n:02d}", d.F_DISPLAY, 34 * s, weight=d.DISPLAY_WEIGHT)
        tw, th = d.text_size(plate)
        d.block(cr, qx, 300 * s, tw + 36 * s, th + 8 * s, C(p["slab"]))
        d.draw_text(cr, plate, qx + 18 * s, 302 * s, C(p["bg"]))
        # the cast list: candidates, the selection in a bone block on top
        visible = self.results[self.sel:self.sel + 5]
        ly = 384 * s
        for row, item in enumerate(visible):
            title, desc, meta, ident = self._item_text(item)
            label = self._label(item).upper()
            num = d.layout(cr, f"{self.sel + row + 1:02d}", d.F_META, 14 * s, spacing=2 * s)
            nw, nh = d.text_size(num)
            if row == 0:
                lay = d.layout(cr, label, d.F_DISPLAY, 44 * s, weight=d.DISPLAY_WEIGHT, spacing=-2 * s)
                d.ellipsize(lay, 560 * s)
                tw, th = d.text_size(lay)
                sub = d.layout(cr, (desc[:28].upper() + (" · " + meta.upper() if meta else "")), d.F_META, 13 * s, spacing=2 * s)
                d.ellipsize(sub, 300 * s)
                sw2, sh2 = d.text_size(sub)
                bw = max(520 * s, 18 * s + nw + 18 * s + tw + 40 * s + sw2 + 18 * s)
                bh = th + 12 * s
                d.block(cr, qx, ly, bw, bh, C(p["top"][0]))
                d.draw_text(cr, num, qx + 18 * s, ly + (bh - nh) / 2, d.CLARET)
                d.draw_text(cr, lay, qx + 18 * s + nw + 18 * s, ly + 4 * s, C(p["top"][1]))
                d.draw_text(cr, sub, qx + bw - 18 * s - sw2, ly + (bh - sh2) / 2, d.CLARET)
                self.item_boxes.append(((qx, ly, qx + bw, ly + bh), self.sel + row))
                ly += bh + 10 * s
            else:
                size = 34 if row < 4 else 26
                lay = d.layout(cr, label, d.F_DISPLAY, size * s, weight=d.DISPLAY_WEIGHT, spacing=-1 * s)
                d.ellipsize(lay, 700 * s)
                tw, th = d.text_size(lay)
                col = C(p["items"][min(row - 1, 3)])
                d.draw_text(cr, num, qx + 18 * s, ly + (th - nh) / 2, C(p["items"][3]))
                d.draw_text(cr, lay, qx + 18 * s + nw + 18 * s, ly, col)
                self.item_boxes.append(((qx, ly, qx + 18 * s + nw + 18 * s + tw, ly + th), self.sel + row))
                ly += th + 10 * s
        # the selected card as a monolith
        if visible:
            self._monolith(cr, w, h, s, visible[0])
        # bottom hazard band
        d.hazard(cr, 0, h - 14 * s, w, 14 * s, d.CLARET, C(p["bg"]), period=40 * s)

    def _monolith(self, cr, w, h, s, item):
        p = _palette()
        title, desc, meta, ident = self._item_text(item)
        cw, chh = 420 * s, 500 * s
        cx, cy = w - 48 * s - cw, 150 * s
        d.block(cr, cx, cy, cw, chh, C(p["card"][0]), shadow=C(p["cshadow"]), shadow_off=(14 * s, 14 * s), border=C(p["card"][2]), border_w=2 * s)
        px = cx + 36 * s
        lay = d.layout(cr, "SELECTED · SOUND ONLY", d.F_META, 13 * s, spacing=5 * s)
        d.draw_text(cr, lay, px, cy + 34 * s, C(p["card"][1]))
        # the title shrinks to fit the monolith (two lines at most) before it ellipsizes
        for size in (64, 54, 46, 40):
            lay = d.layout(cr, title, d.F_TITLE, size * s, weight=d.DISPLAY_WEIGHT, spacing=-2 * s)
            tw, th = d.text_size(lay)
            if tw <= cw - 72 * s:
                break
        else:
            lay.set_width(int((cw - 72 * s) * Pango.SCALE))
            lay.set_wrap(Pango.WrapMode.WORD_CHAR)
            lay.set_height(-2)
            lay.set_ellipsize(Pango.EllipsizeMode.END)
            tw, th = d.text_size(lay)
        d.draw_text(cr, lay, px, cy + 60 * s, C(p["card"][2]))
        ty = cy + 60 * s + th + 14 * s
        for line in (desc, meta, ident):
            if not line:
                continue
            lay = d.layout(cr, line, d.F_META, 15 * s, spacing=1 * s)
            d.ellipsize(lay, cw - 72 * s)
            lw, lh = d.text_size(lay)
            d.draw_text(cr, lay, px, ty, C(p["card"][3]))
            ty += lh + 2 * s
        # hazard rule and the key blocks
        by = cy + chh - 36 * s - 40 * s
        d.hazard(cr, px, by - 24 * s, cw - 72 * s, 10 * s, C(p["cshadow"]), C(p["card"][0]), period=24 * s)
        bx = px
        for (bg, fg), label in zip(p["btn"], ("ENTER · OPEN", "TAB · NEXT", "ESC")):
            lay = d.display(cr, label, 18 * s, italic=False, spacing=1 * s)
            tw, th = d.text_size(lay)
            bw, bh = tw + 32 * s, th + 14 * s
            d.block(cr, bx, by, bw, bh, C(bg))
            d.draw_text(cr, lay, bx + 16 * s, by + 7 * s, C(fg))
            bx += bw + 8 * s

    def destroy(self):
        self.hide()
        self.win.destroy()


def _background(cr, w, h):
    """A black room: the title card is the whole picture."""
    d.rgba(cr, C(_palette()["bg"]))
    cr.paint()


def _score(q, name, extra):
    if not q or q.startswith(">"):
        return 0.0
    if name.startswith(q):
        return 100.0
    if any(w.startswith(q) for w in name.split()):
        return 85.0
    if q in name:
        return 70.0
    it = iter(name)
    if all(ch in it for ch in q):
        return 40.0
    if q in extra:
        return 25.0
    return None
