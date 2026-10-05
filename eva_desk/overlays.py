"""Overlays of the nerv look: the workspace eye-catch, the EMERGENCY band for critical notifications, the
Alt+Tab cast strip and the Third Impact power menu. Each one is a layer-shell surface on the overlay layer;
the drawing lives in module functions so the offline previews can render the same pictures.

House rule: one cut or one pulse, then stillness. Nothing here loops.
"""
import math
import shlex
import time

from . import gtkutil  # noqa: F401  (pins GTK 4 before any gi.repository import)

from gi.repository import Gdk, Gio, GLib, Gtk  # noqa: E402

from . import draw as d  # noqa: E402
from .gtkutil import layer_window, point, rect, render_texture  # noqa: E402
from .scenes import ease_out_cubic  # noqa: E402


# ---------------------------------------------------------------- drawing (shared with the previews)
def draw_eyecatch(cr, w, h, ws_id, name, inverted=False, soft=False):
    """The episode card: EPISODE small, the number huge, a plate with the workspace name.
    soft: a translucent wash instead of the black card (the quiet version)."""
    s = h / 720
    ink, bone = (d.BONE, d.INK) if inverted else (d.INK, d.BONE)
    d.rgba(cr, d.hexc(d.THEME["colors"]["ink_deep"]) if not inverted else d.BONE, 0.72 if soft else 1.0)
    cr.paint()
    label = d.layout(cr, "EPISODE", d.F_META, 22 * s, spacing=8 * s)
    d.draw_text(cr, label, 150 * s, 120 * s, d.CLARET if inverted else d.RED)
    num = d.layout(cr, f"{int(ws_id):02d}", d.F_DISPLAY, 420 * s, weight=d.DISPLAY_WEIGHT, spacing=-24 * s)
    ink_r, _ = num.get_pixel_extents()
    d.draw_text(cr, num, 136 * s, 110 * s, bone)
    plate_text = f"第{_kanji(ws_id)}話 ・ {name.upper()}" if name else f"第{_kanji(ws_id)}話"
    plate = d.layout(cr, plate_text, d.F_DISPLAY, 44 * s, weight=d.DISPLAY_WEIGHT)
    pw, ph = d.text_size(plate)
    py = min(110 * s + ink_r.y + ink_r.height + 36 * s, h - 14 * s - ph - 40 * s)
    d.block(cr, 150 * s, py, pw + 44 * s, ph + 14 * s, bone)
    d.draw_text(cr, plate, 172 * s, py + 6 * s, ink)
    d.hazard(cr, 0, h - 14 * s, w, 14 * s, d.CLARET, None, period=40 * s)


_KANJI = "零壱弐参四五六七八九十"


def _kanji(n):
    n = int(n)
    if 0 <= n <= 10:
        return _KANJI[n]
    return str(n)


def draw_band(cr, w, h, note):
    """The EMERGENCY band: 緊急, the app and summary, the body, ACK and CLOSE ALL blocks, a hazard rule."""
    band_h = h - 8
    d.rgba(cr, d.LED)
    cr.rectangle(0, 0, w, band_h)
    cr.fill()
    d.hazard(cr, 0, band_h, w, 8, d.LED, d.INK, period=24)
    kan = d.layout(cr, "緊急", d.F_DISPLAY, 34, weight=d.DISPLAY_WEIGHT, spacing=-2)
    kw, kh = d.text_size(kan)
    d.draw_text(cr, kan, 18, (band_h - kh) / 2, d.INK)
    x = 18 + kw + 16
    head = d.layout(cr, f"EMERGENCY · {note.get('app', '').upper()}", d.F_META, 11, spacing=3)
    d.draw_text(cr, head, x, 9, d.INK)
    summ = d.layout(cr, note.get("summary", ""), d.F_DISPLAY, 18, weight=d.DISPLAY_WEIGHT, spacing=-0.5)
    d.ellipsize(summ, w * 0.45)
    d.draw_text(cr, summ, x, 25, d.INK)
    hits = []
    bx = w - 18
    for key, label, fill, fg in (("close_all", "CLOSE ALL", d.BONE, d.INK), ("ack", "ACK", d.INK, d.BONE)):
        lay = d.display(cr, label, 13, italic=False, spacing=1)
        tw, th = d.text_size(lay)
        bwid, bhei = tw + 24, th + 10
        bx -= bwid
        d.block(cr, bx, (band_h - bhei) / 2, bwid, bhei, fill)
        d.draw_text(cr, lay, bx + 12, (band_h - bhei) / 2 + 5, fg)
        hits.append((bx, bx + bwid, key))
        bx -= 6
    body_x = x + w * 0.45 + 24
    body = d.layout(cr, note.get("body", "").replace("\n", " "), d.F_BODY, 13)
    d.ellipsize(body, max(40, bx - 20 - body_x))
    bw, bh = d.text_size(body)
    d.draw_text(cr, body, body_x, (band_h - bh) / 2, d.INK)
    return hits


def draw_alttab(cr, w, h, items, sel):
    """The cast strip: one episode card per window, the selected one lilac and lifted."""
    s = min(w / 1720, h / 720)
    d.rgba(cr, d.hexc(d.THEME["colors"]["ink_deep"]), 0.75)
    cr.paint()
    title = d.layout(cr, "CAST", d.F_DISPLAY, 44 * s, weight=d.DISPLAY_WEIGHT, spacing=-2 * s)
    tw, th = d.text_size(title)
    top = h * 0.22
    d.draw_text(cr, title, 60 * s, top - 90 * s, d.BONE)
    sub = d.layout(cr, f"ALT+TAB · {len(items)} WINDOWS · MOST RECENT FIRST", d.F_META, 13 * s, spacing=4 * s)
    d.draw_text(cr, sub, 60 * s + tw + 18 * s, top - 90 * s + th - 22 * s, d.RED)
    hint = d.layout(cr, "TAB NEXT · SHIFT+TAB BACK · RELEASE ALT TO JUMP · ESC", d.F_META, 12 * s, spacing=3 * s)
    hw, hh = d.text_size(hint)
    d.draw_text(cr, hint, w - 60 * s - hw, top - 90 * s + 8 * s, d.BONE3)
    cw, ch, gap = 240 * s, 260 * s, 18 * s
    big_w, big_h = 300 * s, 300 * s
    # keep the selected card on screen: scroll the strip so it sits within the first ~4 slots
    first = max(0, sel - 3)
    x = 60 * s
    boxes = []
    for i in range(first, len(items)):
        it = items[i]
        selected = i == sel
        wdt, hgt = (big_w, big_h) if selected else (cw, ch)
        if x + wdt > w - 40 * s:
            break
        y = top + (big_h - hgt) - (16 * s if selected else 0)
        if selected:
            d.block(cr, x, y, wdt, hgt, d.BONE, shadow=d.CLARET, shadow_off=(14 * s, 14 * s))
            fg, meta, num = d.INK, d.CLARET, d.CLARET
        else:
            d.block(cr, x, y, wdt, hgt, d.INK, border=d.LED if it.get("urgent") else d.hexc(d.THEME["colors"]["ink5"]), border_w=max(1, s))
            fg, meta, num = d.BONE, d.RED, d.DIM
        ep = d.layout(cr, it.get("ep", ""), d.F_META, 11 * s, spacing=3 * s)
        d.draw_text(cr, ep, x + 20 * s, y + 18 * s, d.LED if it.get("urgent") else meta)
        n = d.layout(cr, f"{i + 1:02d}", d.F_META, 11 * s, spacing=3 * s)
        nw, nh = d.text_size(n)
        d.draw_text(cr, n, x + wdt - 20 * s - nw, y + 18 * s, num)
        app = d.layout(cr, it.get("app", "?").upper(), d.F_DISPLAY, (44 if selected else 32) * s, weight=d.DISPLAY_WEIGHT, spacing=-2 * s)
        d.ellipsize(app, wdt - 40 * s)
        aw, ah = d.text_size(app)
        ty = y + hgt - (84 if selected else 50) * s - ah
        d.draw_text(cr, app, x + 20 * s, ty, fg)
        t = d.layout(cr, it.get("title", ""), d.F_META, 13 * s, spacing=1 * s)
        t.set_width(int((wdt - 40 * s) * 1024))
        t.set_height(int(2 * 18 * s * 1024))
        t.set_ellipsize(3)  # END
        t.set_wrap(2)       # WORD_CHAR
        d.draw_text(cr, t, x + 20 * s, ty + ah + 6 * s, d.hexc(d.THEME["colors"]["wine"]) if selected else d.BONE3)
        if selected:
            d.hazard(cr, x + 20 * s, y + hgt - 22 * s, wdt - 40 * s, 8 * s, d.CLARET, d.BONE, period=20 * s)
        boxes.append(((x, y, x + wdt, y + hgt), i))
        x += wdt + gap
    d.hazard(cr, 0, h - 10 * s, w, 10 * s, d.CLARET, d.INK, period=32 * s)
    return boxes


POWER_ITEMS = [("lock", "LOCK", "封鎖"), ("sleep", "SLEEP", "休眠"), ("logout", "LOG OUT", "退場"),
               ("reboot", "REBOOT", "再起動"), ("shutdown", "SHUT DOWN", "補完")]


def draw_power(cr, w, h, sel, armed, info):
    """THIRD IMPACT?: four monoliths, the chosen one lilac; `armed` = shutdown waiting for its second Enter."""
    s = min(w / 1720, h / 720)
    d.rgba(cr, d.hexc(d.THEME["colors"]["ink_deep"]), 0.92)
    cr.paint()
    cw, gap = 180 * s, 18 * s
    x0 = w * 0.5 - (len(POWER_ITEMS) * cw + (len(POWER_ITEMS) - 1) * gap) / 2
    lab = d.layout(cr, "SUPER + M · POWER", d.F_META, 12 * s, spacing=5 * s)
    top = h * 0.10
    d.draw_text(cr, lab, x0, top, d.RED)
    t1 = d.layout(cr, "THIRD", d.F_DISPLAY, 88 * s, weight=d.DISPLAY_WEIGHT, spacing=-5 * s)
    d.draw_text(cr, t1, x0 - 4 * s, top + 20 * s, d.BONE)
    t2 = d.layout(cr, "IMPACT", d.F_DISPLAY, 88 * s, weight=d.DISPLAY_WEIGHT, spacing=-5 * s)
    tw, th = d.text_size(t2)
    d.draw_text(cr, t2, x0 - 4 * s, top + 20 * s + th * 0.86, d.BONE)
    q = d.layout(cr, "?", d.F_DISPLAY, 88 * s, weight=d.DISPLAY_WEIGHT)
    d.draw_text(cr, q, x0 - 4 * s + tw, top + 20 * s + th * 0.86, d.GOLD)
    ch = 250 * s
    y = top + 20 * s + th * 1.72 + 30 * s
    boxes = []
    for i, (key, label, kanji) in enumerate(POWER_ITEMS):
        x = x0 + i * (cw + gap)
        chosen = i == sel
        if chosen and armed:
            d.block(cr, x, y, cw, ch, d.LED, shadow=d.BONE, shadow_off=(12 * s, 12 * s))
            fg, meta, kfg = d.INK, d.INK, d.INK
        elif chosen:
            d.block(cr, x, y, cw, ch, d.BONE, shadow=d.CLARET, shadow_off=(12 * s, 12 * s))
            fg, meta, kfg = d.INK, d.CLARET, d.CLARET
        else:
            d.block(cr, x, y, cw, ch, d.INK, border=d.hexc(d.THEME["colors"]["ink5"]), border_w=max(1, s))
            fg, meta, kfg = d.BONE, d.RED, d.BONE3
        top = d.layout(cr, f"{i + 1:02d} · " + ("CONFIRM" if chosen and armed else "SELECTED" if chosen else "SOUND ONLY"), d.F_META, 11 * s, spacing=3 * s)
        d.draw_text(cr, top, x + 16 * s, y + 16 * s, meta)
        name = d.layout(cr, label, d.F_DISPLAY, 30 * s, weight=d.DISPLAY_WEIGHT, spacing=-1 * s)
        name.set_width(int((cw - 32 * s) * 1024))
        name.set_wrap(0)
        nw, nh = d.text_size(name)
        k = d.layout(cr, kanji, d.F_DISPLAY, 18 * s, weight=d.DISPLAY_WEIGHT)
        kw, kh = d.text_size(k)
        d.draw_text(cr, name, x + 16 * s, y + ch - 16 * s - kh - 6 * s - nh, fg)
        d.draw_text(cr, k, x + 16 * s, y + ch - 16 * s - kh, kfg)
        boxes.append(((x, y, x + cw, y + ch), i))
    hint = d.layout(cr, "← → CHOOSE · ENTER CONFIRM (TWICE FOR SHUTDOWN) · ESC", d.F_META, 12 * s, spacing=3 * s)
    d.draw_text(cr, hint, x0, y + ch + 36 * s, d.BONE3)
    if info:
        inf = d.layout(cr, info, d.F_META, 12 * s, spacing=3 * s)
        iw, ih = d.text_size(inf)
        d.draw_text(cr, x0 + len(POWER_ITEMS) * (cw + gap) - gap - iw, y + ch + 36 * s, d.GOLD) if False else d.draw_text(cr, inf, x0 + len(POWER_ITEMS) * (cw + gap) - gap - iw, y + ch + 36 * s, d.GOLD)
    d.hazard(cr, 0, h - 10 * s, w, 10 * s, d.CLARET, d.INK, period=32 * s)
    return boxes


# ---------------------------------------------------------------- the surfaces
class _View(Gtk.Widget):
    def __init__(self, painter):
        super().__init__()
        self.painter = painter
        self.set_hexpand(True)
        self.set_vexpand(True)

    def do_snapshot(self, snap):
        self.painter(snap, self.get_width(), self.get_height())


class _Overlay:
    """A full-monitor surface on the overlay layer with a tick animation and a cairo texture cache."""

    def __init__(self, app, namespace, keyboard="none", passthrough=True, anchors=("top", "bottom", "left", "right"),
                 height=None, margins=None):
        self.app = app
        self.win = layer_window(app, None, "overlay", namespace, anchors=anchors, keyboard=keyboard,
                                passthrough=passthrough, height=height, exclusive=-1)
        if margins:
            from gi.repository import Gtk4LayerShell as LS
            for edge, px in margins.items():
                LS.set_margin(self.win, gtkutil.EDGES[edge], int(px))
        self.view = _View(self._paint)
        self.win.set_child(self.view)
        self.w = self.h = 0
        self.scale = 1
        self.anim_start = None
        self.anim_ms = 1
        self.tick_id = None
        self.t = 1.0
        self.on_done = None

    def place(self, gdk_monitor):
        from gi.repository import Gtk4LayerShell as LS
        if gdk_monitor is not None:
            LS.set_monitor(self.win, gdk_monitor)
            geo = gdk_monitor.get_geometry()
            self.scale = max(1, gdk_monitor.get_scale_factor())
            self.w, self.h = geo.width * self.scale, geo.height * self.scale

    @property
    def visible(self):
        return self.win.get_visible()

    def show(self):
        self.win.set_visible(True)
        self.win.present()
        self.view.queue_draw()

    def hide(self):
        self._stop()
        self.win.set_visible(False)

    def animate(self, ms, on_done=None):
        self._stop()
        self.anim_ms, self.anim_start, self.t, self.on_done = max(1, int(ms)), None, 0.0, on_done
        self.tick_id = self.view.add_tick_callback(self._tick)

    def _stop(self):
        if self.tick_id is not None:
            self.view.remove_tick_callback(self.tick_id)
            self.tick_id = None
        self.t = 1.0

    def _tick(self, widget, clock):
        now = clock.get_frame_time() / 1e6
        if self.anim_start is None:
            self.anim_start = now
        self.t = min(1.0, (now - self.anim_start) * 1000 / self.anim_ms)
        widget.queue_draw()
        if self.t >= 1.0:
            self.tick_id = None
            done, self.on_done = self.on_done, None
            if done:
                GLib.idle_add(lambda: (done(), False)[1])
            return GLib.SOURCE_REMOVE
        return GLib.SOURCE_CONTINUE

    def _paint(self, snap, w, h):
        pass

    def destroy(self):
        self._stop()
        self.win.destroy()


class Eyecatch(_Overlay):
    """The episode card cut on a workspace switch: black card, one inverted frame, then it lifts."""

    def __init__(self, app, cfg):
        super().__init__(app, "eva-eyecatch")
        self.cfg = cfg
        self.tex = {}
        self.ws = None

    def play(self, gdk_monitor, ws_id, name):
        self.place(gdk_monitor)
        if not self.w:
            return
        self.ws = (ws_id, name)
        soft = self.cfg["overlays"].get("eyecatch_style", "soft") == "soft"
        key = (ws_id, name, self.w, self.h, soft)
        if key not in self.tex:
            self.tex = {key: (render_texture(self.w, self.h, lambda cr: draw_eyecatch(cr, self.w, self.h, ws_id, name, soft=soft)),
                              None if soft else render_texture(self.w, self.h, lambda cr: draw_eyecatch(cr, self.w, self.h, ws_id, name, True)))}
        self.soft = soft
        self.show()
        ms = int(self.cfg["overlays"].get("eyecatch_ms", 0) or 0) or (240 if soft else 320)
        self.animate(ms, self.hide)

    def _paint(self, snap, w, h):
        texs = next(iter(self.tex.values()), None)
        if not texs:
            return
        t = self.t
        card, inverted = texs
        if getattr(self, "soft", True) or inverted is None:
            # the quiet cut: the card holds briefly, then fades; no inversion, nothing slides
            a = 1.0 if t < 0.45 else max(0.0, 1.0 - (t - 0.45) / 0.55)
            snap.push_opacity(a)
            snap.append_texture(card, rect(0, 0, w, h))
            snap.pop()
            return
        if t < 0.19:
            snap.append_texture(card, rect(0, 0, w, h))
        elif t < 0.375:
            snap.append_texture(inverted, rect(0, 0, w, h))
        else:
            k = (t - 0.375) / 0.625
            e = k * k * (3 - 2 * k)                            # smoothstep: the card lifts off the screen
            snap.save()
            snap.translate(point(0, -h * e))
            snap.append_texture(card, rect(0, 0, w, h))
            snap.restore()


class AlarmBand:
    """A band under the bar for critical notifications (watches org.freedesktop.Notifications.Notify)."""

    HEIGHT = 70

    def __init__(self, app, cfg):
        self.app, self.cfg = app, cfg
        top = int(cfg["bar"]["height"]) if cfg["bar"]["enabled"] else 0
        self.ov = _Overlay(app, "eva-alarm", passthrough=False, anchors=("top", "left", "right"),
                           height=self.HEIGHT, margins={"top": top})
        self.ov._paint = self._paint
        self.note = None
        self.hits = []
        self.tex = None
        click = Gtk.GestureClick()
        click.connect("pressed", self._click)
        self.ov.view.add_controller(click)
        self.hide_id = None
        self.conn = None
        GLib.idle_add(self._watch)

    def _watch(self):
        try:
            addr = Gio.dbus_address_get_for_bus_sync(Gio.BusType.SESSION, None)
            flags = Gio.DBusConnectionFlags.AUTHENTICATION_CLIENT | Gio.DBusConnectionFlags.MESSAGE_BUS_CONNECTION
            self.conn = Gio.DBusConnection.new_for_address_sync(addr, flags, None, None)
            self.conn.call_sync("org.freedesktop.DBus", "/org/freedesktop/DBus", "org.freedesktop.DBus.Monitoring",
                                "BecomeMonitor", GLib.Variant("(asu)", (["interface='org.freedesktop.Notifications',member='Notify',type='method_call'"], 0)),
                                None, Gio.DBusCallFlags.NONE, -1, None)
            self.conn.add_filter(self._filter)
        except GLib.Error as e:
            print("eva-desk: alarm band cannot watch notifications:", e, flush=True)
        return False

    def _filter(self, conn, message, incoming):
        try:
            if incoming and message.get_member() == "Notify" and message.get_interface() == "org.freedesktop.Notifications":
                body = message.get_body()
                if body is not None and body.n_children() >= 7:
                    app_name, _, _, summary, text, _, hints = body.unpack()[:7]
                    urgency = hints.get("urgency", 1) if isinstance(hints, dict) else 1
                    if int(urgency) >= 2:
                        GLib.idle_add(self.show, {"app": str(app_name), "summary": str(summary), "body": str(text)})
        except Exception as e:                                 # a monitor must never raise
            print("eva-desk: alarm band message", e, flush=True)
        return message

    def show(self, note):
        gdk = self.app.focused_gdk()
        self.ov.place(gdk)
        if not self.ov.w:
            return False
        self.note = note
        w, h = self.ov.w, self.HEIGHT * self.ov.scale
        hits = []
        self.tex = render_texture(w, h, lambda cr: hits.extend(draw_band(cr, w, h, note)))
        self.hits = hits
        self.ov.show()
        self.ov.animate(220)
        if self.hide_id:
            GLib.source_remove(self.hide_id)
        self.hide_id = GLib.timeout_add_seconds(int(self.cfg["overlays"].get("alarm_seconds", 120)), self._timeout)
        return False

    def _timeout(self):
        self.hide_id = None
        self.hide()
        return False

    def hide(self):
        self.ov.hide()
        self.note = None

    def _paint(self, snap, w, h):
        if not self.tex:
            return
        e = ease_out_cubic(self.ov.t)
        snap.save()
        snap.translate(point(0, -h * (1 - e)))
        snap.append_texture(self.tex, rect(0, 0, w, h))
        snap.restore()

    def _click(self, gesture, n, x, y):
        x *= self.ov.scale
        for x0, x1, key in self.hits:
            if x0 <= x <= x1:
                if key == "close_all":
                    self.app.hypr.exec("dunstctl close-all")
                self.hide()
                return
        self.hide()


class AltTab(_Overlay):
    """The cast strip: Alt+Tab cycles the windows by focus history; releasing Alt jumps."""

    def __init__(self, app, cfg):
        super().__init__(app, "eva-alttab", keyboard="exclusive", passthrough=False)
        self.cfg = cfg
        self.items, self.sel, self.boxes = [], 0, []
        self.tex = None
        keys = Gtk.EventControllerKey()
        keys.connect("key-pressed", self._key)
        keys.connect("key-released", self._released)
        self.win.add_controller(keys)
        click = Gtk.GestureClick()
        click.connect("pressed", self._click)
        self.view.add_controller(click)
        self.seen_key = False
        self.guard = None

    def open(self, gdk_monitor):
        clients = [c for c in (self.app.hypr.j("clients") or []) if c.get("mapped", True) and not c.get("hidden")]
        clients.sort(key=lambda c: c.get("focusHistoryID", 99))
        self.items = []
        for c in clients:
            ws = c.get("workspace") or {}
            wid = ws.get("id", 0)
            ep = f"EP {wid:02d} · WS {wid:02d}" if isinstance(wid, int) and wid > 0 else (ws.get("name", "").upper() or "SPECIAL")
            self.items.append({"address": c.get("address"), "app": c.get("class", "?"), "title": c.get("title", ""),
                               "ep": ep, "urgent": wid in getattr(self.app, "urgent_ws", set())})
        if not self.items:
            return "no windows"
        self.sel = 1 if len(self.items) > 1 else 0
        self.place(gdk_monitor)
        self._render()
        self.seen_key = False
        self.show()
        if self.guard:
            GLib.source_remove(self.guard)
        self.guard = GLib.timeout_add(900, self._guard)       # Alt was tapped, not held: jump to the previous window
        return "ok"

    def _guard(self):
        self.guard = None
        if self.visible and not self.seen_key:
            self._activate()
        return False

    def _render(self):
        boxes = []
        w, h = self.w, self.h
        self.tex = render_texture(w, h, lambda cr: boxes.extend(draw_alttab(cr, w, h, self.items, self.sel)))
        self.boxes = boxes
        self.view.queue_draw()

    def _paint(self, snap, w, h):
        if self.tex:
            snap.append_texture(self.tex, rect(0, 0, w, h))

    def _move(self, step):
        self.sel = (self.sel + step) % len(self.items)
        self._render()

    def _key(self, ctrl, keyval, keycode, mods):
        self.seen_key = True
        name = Gdk.keyval_name(keyval) or ""
        if name == "Escape":
            self.hide()
        elif name in ("Tab", "Right", "Down", "l"):
            self._move(1)
            if not (mods & Gdk.ModifierType.ALT_MASK) and name == "Tab":
                pass
        elif name in ("ISO_Left_Tab", "Left", "Up", "h"):
            self._move(-1)
        elif name in ("Return", "KP_Enter", "space"):
            self._activate()
        return True

    def _released(self, ctrl, keyval, keycode, mods):
        name = Gdk.keyval_name(keyval) or ""
        if name in ("Alt_L", "Alt_R", "Meta_L", "Meta_R", "Super_L"):
            self._activate()

    def _click(self, gesture, n, x, y):
        x, y = x * self.scale, y * self.scale
        for (x0, y0, x1, y1), i in self.boxes:
            if x0 <= x <= x1 and y0 <= y <= y1:
                self.sel = i
                self._activate()
                return
        self.hide()

    def _activate(self):
        if not self.visible:
            return
        item = self.items[self.sel] if self.items else None
        self.hide()
        if item and item.get("address"):
            self.app.hypr.focus_window(item["address"])


class PowerMenu(_Overlay):
    """THIRD IMPACT?: lock / sleep / reboot / shut down as monoliths; the cross of light plays on confirm."""

    def __init__(self, app, cfg):
        super().__init__(app, "eva-power", keyboard="exclusive", passthrough=False)
        self.cfg = cfg
        self.sel, self.armed, self.boxes = 0, False, []
        self.tex = None
        self.cross = None                                       # (key, ms) while the cross plays
        keys = Gtk.EventControllerKey()
        keys.connect("key-pressed", self._key)
        self.win.add_controller(keys)
        click = Gtk.GestureClick()
        click.connect("pressed", self._click)
        self.view.add_controller(click)

    def open(self, gdk_monitor):
        self.place(gdk_monitor)
        self.sel, self.armed, self.cross = 0, False, None
        self._render()
        self.show()
        return "ok"

    def _info(self):
        clients = [c for c in (self.app.hypr.j("clients") or []) if c.get("mapped", True)]
        editors = [c for c in clients if c.get("class", "").lower() in ("kitty", "nvim", "code", "codium") and "nvim" in c.get("title", "").lower()]
        s = f"{len(clients)} WINDOWS OPEN"
        if editors:
            s += f" · {len(editors)} EDITOR" + ("S" if len(editors) > 1 else "")
        return s

    def _render(self):
        boxes = []
        w, h, sel, armed, info = self.w, self.h, self.sel, self.armed, self._info()
        self.tex = render_texture(w, h, lambda cr: boxes.extend(draw_power(cr, w, h, sel, armed, info)))
        self.boxes = boxes
        self.view.queue_draw()

    def _paint(self, snap, w, h):
        if self.tex:
            snap.append_texture(self.tex, rect(0, 0, w, h))
        if self.cross:
            t = self.t
            e = ease_out_cubic(t)
            beam = max(4.0, 26 * e) * self.scale
            half_w, half_h = w * 0.5 * e + 8, h
            cx, cy = w / 2, h * 0.5
            white = Gdk.RGBA()
            white.parse(d.THEME["colors"]["bone"] and "#" + d.THEME["colors"]["bone"])
            glow = Gdk.RGBA()
            glow.parse("#" + d.THEME["colors"]["gold"])
            glow.alpha = 0.35 * (1 - t) + 0.1
            snap.append_color(glow, rect(cx - beam * 2, 0, beam * 4, half_h))
            snap.append_color(glow, rect(cx - half_w, cy - beam * 2, half_w * 2, beam * 4))
            snap.append_color(white, rect(cx - beam / 2, 0, beam, half_h))
            snap.append_color(white, rect(cx - half_w, cy - beam / 2, half_w * 2, beam))
            if t > 0.75:
                wash = Gdk.RGBA()
                wash.parse("#" + d.THEME["colors"]["bone"])
                wash.alpha = (t - 0.75) / 0.25
                snap.append_color(wash, rect(0, 0, w, h))

    def _move(self, step):
        self.sel = (self.sel + step) % len(POWER_ITEMS)
        self.armed = False
        self._render()

    def _key(self, ctrl, keyval, keycode, mods):
        if self.cross:
            return True
        name = Gdk.keyval_name(keyval) or ""
        if name == "Escape":
            self.hide()
        elif name in ("Right", "Tab", "l", "Down"):
            self._move(1)
        elif name in ("Left", "ISO_Left_Tab", "h", "Up"):
            self._move(-1)
        elif name in ("1", "2", "3", "4", "5"):
            self.sel, self.armed = int(name) - 1, False
            self._render()
        elif name in ("Return", "KP_Enter", "space"):
            self._confirm()
        return True

    def _click(self, gesture, n, x, y):
        if self.cross:
            return
        x, y = x * self.scale, y * self.scale
        for (x0, y0, x1, y1), i in self.boxes:
            if x0 <= x <= x1 and y0 <= y <= y1:
                if self.sel == i:
                    self._confirm()
                else:
                    self.sel, self.armed = i, False
                    self._render()
                return
        self.hide()

    def _confirm(self):
        key = POWER_ITEMS[self.sel][0]
        if key in ("shutdown", "logout") and not self.armed:   # the ones that lose your windows ask twice
            self.armed = True
            self._render()
            return
        cmd = self.cfg["power"].get(key, "")
        ms = 600 if key in ("reboot", "shutdown", "logout") else 250
        self.cross = (key, ms)
        self.animate(ms, lambda: self._run(key, cmd))

    def _run(self, key, cmd):
        self.cross = None
        self.hide()
        if cmd:
            self.app.hypr.exec(cmd)
        elif key == "logout":                                  # no command configured: Hyprland's own exit
            if self.app.hypr.lua:
                self.app.hypr.eval_lua("hl.dispatch(hl.dsp.exit())")
            else:
                self.app.hypr.request("dispatch exit")


class SpawnPulse(_Overlay):
    """One hexagon pulse from the centre of a window that just opened (260 ms), then nothing."""

    def __init__(self, app, cfg):
        super().__init__(app, "eva-pulse")
        self.cfg = cfg
        self.centre, self.size = (0, 0), 0
        self.hex_tex = None

    def play(self, gdk_monitor, cx, cy, size):
        self.place(gdk_monitor)
        if not self.w:
            return
        if self.hex_tex is None:
            def hexagon(cr):
                cr.set_line_width(14)
                d.rgba(cr, d.GOLD)
                for i in range(6):
                    a = math.radians(60 * i - 30)
                    (cr.move_to if i == 0 else cr.line_to)(256 + 240 * math.cos(a), 256 + 240 * math.sin(a))
                cr.close_path()
                cr.stroke()
            self.hex_tex = render_texture(512, 512, hexagon)
        self.centre, self.size = (cx * self.scale, cy * self.scale), size * self.scale
        self.show()
        self.animate(int(self.cfg["overlays"].get("pulse_ms", 260)), self.hide)

    def _paint(self, snap, w, h):
        if not self.hex_tex:
            return
        t = self.t
        e = ease_out_cubic(t)
        r = self.size * (0.12 + 0.95 * e)
        alpha = (1 - t) ** 1.5
        cx, cy = self.centre
        snap.push_opacity(alpha)
        snap.append_texture(self.hex_tex, rect(cx - r, cy - r, 2 * r, 2 * r))
        snap.pop()
