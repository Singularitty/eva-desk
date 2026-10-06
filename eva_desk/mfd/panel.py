"""The panel base class: an MFD screen docked to one edge (or the centre) of the monitor, on a
full-monitor pass-through surface that only catches input inside its own rectangle. One panel is
open at a time -- opening any panel closes the others (`app.open_panel` / `app.close_panels`).

The CRT snap plays on open (380 ms) and in reverse on close (190 ms): each section the subclass's
`draw()` records in `self.sections` scales in about its own top edge (`widgets.snap_scale` of
`widgets.stagger`). At idle nothing animates -- the drawn content is cached until `invalidate()`.
"""
import cairo

from .. import gtkutil  # noqa: F401  (pins GTK 4 before any gi.repository import)

from gi.repository import Gdk, Gtk  # noqa: E402

from .. import overlays as O  # noqa: E402
from ..gtkutil import rect, render_texture, texture  # noqa: E402
from . import widgets as W  # noqa: E402


def panel_rect(anchor, mw, mh, pw, ph, bar_h, margin=12):
    """The panel's (x, y, w, h) in surface pixels for `anchor` within a `mw`x`mh` monitor, with
    `bar_h` kept free at the top. `left`/`right`/`bottom` sit flush at `margin` from their edge;
    `top` centres horizontally (flush under the bar); `center` centres in both axes below the bar."""
    top_y = bar_h + margin
    if anchor == "left":
        return margin, top_y, pw, ph
    if anchor == "right":
        return mw - margin - pw, top_y, pw, ph
    if anchor == "top":
        return (mw - pw) // 2, top_y, pw, ph
    if anchor == "bottom":
        return margin, mh - margin - ph, pw, ph
    if anchor == "center":
        return (mw - pw) // 2, bar_h + (mh - bar_h - ph) // 2, pw, ph
    raise ValueError(f"panel: unknown anchor {anchor!r}")


def _progress(t, closing):
    """The snap's effective 0..1 progress from the overlay's own clock `t` (always 0..1 forward):
    forward while opening, in reverse while closing -- 1.0 at t=0, 0.0 at t=1 when closing."""
    return (1.0 - t) if closing else t


class Panel(O._Overlay):
    """An anchored MFD panel. Subclasses implement `draw()` (and whichever of `on_open`,
    `on_close`, `on_key`, `on_click`, `on_scroll` they need) and are driven through `open()`,
    `close()`, `toggle()` and `invalidate()`."""

    MARGIN = 12

    def __init__(self, app, cfg, name, width, height, anchor):
        super().__init__(app, f"eva-panel-{name}", keyboard="exclusive", passthrough=False)
        self.cfg, self.anchor, self.name = cfg, anchor, name
        self.pwidth, self.pheight = width, height
        self.px = self.py = self.pw = self.ph = 0
        self.sections, self.hits = [], []
        self._base = None
        self._base_tex = None
        self._closing = False
        self._close_from = 1.0
        self.pointer = (0, 0)

        keys = Gtk.EventControllerKey()
        keys.connect("key-pressed", self._key)
        self.win.add_controller(keys)
        click = Gtk.GestureClick()
        click.set_button(0)
        click.connect("pressed", self._click)
        self.view.add_controller(click)
        scroll = Gtk.EventControllerScroll.new(Gtk.EventControllerScrollFlags.VERTICAL)
        scroll.connect("scroll", self._scroll)
        self.view.add_controller(scroll)
        motion = Gtk.EventControllerMotion()
        motion.connect("motion", self._motion)
        self.view.add_controller(motion)
        self.win.connect("realize", lambda w: self._set_region())

    # ------------------------------------------------------------ placement / input region
    def place(self, gdk_monitor):
        super().place(gdk_monitor)
        if not self.w:
            return
        bar_h = int(self.cfg["bar"]["height"]) * self.scale if self.cfg["bar"]["enabled"] else 0
        margin = self.MARGIN * self.scale
        self.px, self.py, self.pw, self.ph = panel_rect(
            self.anchor, self.w, self.h, self.pwidth * self.scale, self.pheight * self.scale, bar_h, margin)
        self._set_region()

    def show(self):
        super().show()
        self._set_region()

    def _set_region(self):
        surf = self.win.get_surface()
        if surf is None:
            return
        surf.set_input_region(cairo.Region(cairo.RectangleInt(int(self.px), int(self.py), int(self.pw), int(self.ph))))

    def release(self):
        super().release()
        self._base = None
        self._base_tex = None

    # ------------------------------------------------------------ open / close / toggle
    def open(self, gdk_monitor):
        if self._closing:
            # the close snap was still playing: it never got to call on_close(), so pair it
            # up now before the new on_open() -- the two must always alternate.
            self._closing = False
            self.on_close()
        self.place(gdk_monitor)
        self.app.close_panels(except_name=self.name)
        self.on_open()
        self.show()
        self.animate(380)
        return "ok"

    def close(self):
        if not self.visible or self._closing:
            return                                       # already closed, or already closing
        # if the open snap was still playing, reverse from wherever it had got to, not from
        # a fully-open frame it never actually reached
        self._close_from = self.t if self.t < 1.0 else 1.0
        self._closing = True
        self.animate(190, on_done=self._finish_close)

    def _finish_close(self):
        if not self._closing:
            return                                       # a reopen already cancelled this close
        self._closing = False
        self.on_close()
        self.hide()

    def toggle(self, gdk_monitor):
        if self.visible:
            self.close()
        else:
            self.open(gdk_monitor)
        return "ok"

    # ------------------------------------------------------------ subclass hooks
    def on_open(self):
        pass

    def on_close(self):
        pass

    def draw(self, cr, w, h):
        """Paint the panel's content into (0, 0, w, h) and return its hit map. Subclasses set
        `self.sections` ([(y, h), ...]) for the open/close snap to scale about."""
        return []

    def on_key(self, name, mods):
        return False

    def on_click(self, x, y, button):
        pass

    def on_scroll(self, x, y, dy):
        pass

    def invalidate(self):
        """Drop the cached content so the next paint re-runs `draw()`."""
        self._base = None
        self._base_tex = None
        self.view.queue_draw()

    # ------------------------------------------------------------ drawing / the crt snap
    def _ensure_base(self):
        if self._base is not None or not self.pw or not self.ph:
            return
        surf = cairo.ImageSurface(cairo.FORMAT_ARGB32, int(self.pw), int(self.ph))
        self.hits = self.draw(cairo.Context(surf), self.pw, self.ph) or []
        self._base = surf

    def _paint(self, snap, w, h):
        self._ensure_base()
        if self._base is None:
            return
        p = _progress(self.t, self._closing)
        if self._closing:
            p *= self._close_from                        # continuity: reverse from where open had got to
        if p <= 0.0:
            return                                        # fully closed: the final close tick draws nothing
        if p >= 1.0:
            if self._base_tex is None:
                self._base_tex = texture(self._base)
            tex = self._base_tex
        else:
            tex = render_texture(self.pw, self.ph, lambda cr: self._snap_frame(cr, p))
        snap.append_texture(tex, rect(self.px, self.py, self.pw, self.ph))

    def _snap_frame(self, cr, p):
        if not self.sections:
            cr.set_source_surface(self._base, 0, 0)
            cr.paint()
            return
        for i, (y, h) in enumerate(self.sections):
            s = W.snap_scale(W.stagger(i, p))
            cr.save()
            cr.rectangle(0, y, self.pw, h)
            cr.clip()
            cr.translate(0, y)
            cr.scale(1, s)
            cr.translate(0, -y)
            cr.set_source_surface(self._base, 0, 0)
            cr.paint()
            cr.restore()

    # ------------------------------------------------------------ input
    def _key(self, ctrl, keyval, keycode, mods):
        name = Gdk.keyval_name(keyval) or ""
        if name == "Escape":
            self.app.close_panels()
            return True
        return bool(self.on_key(name, mods))

    def _motion(self, ctrl, x, y):
        self.pointer = (x, y)

    def _to_panel(self, x, y):
        return x * self.scale - self.px, y * self.scale - self.py

    def _click(self, gesture, n, x, y):
        px, py = self._to_panel(x, y)
        self.on_click(px, py, gesture.get_current_button())

    def _scroll(self, ctrl, dx, dy):
        px, py = self._to_panel(*self.pointer)
        self.on_scroll(px, py, dy)
        return True
