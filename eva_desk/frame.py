"""The window frame overlay: bone corner brackets, a class/workspace tag and a LOCK readout drawn
around the focused window. Static — it never animates; the only thing that runs at idle is a 200 ms
poll while the framed window is floating (so the brackets track it without a Hyprland event)."""
import traceback

from . import gtkutil  # noqa: F401  (pins GTK 4 before any gi.repository import)

from gi.repository import GLib  # noqa: E402
from gi.repository import Gtk4LayerShell as LS  # noqa: E402

from . import draw as d  # noqa: E402
from .gtkutil import rect  # noqa: E402
from .hypr import class_matches  # noqa: E402
from .overlays import _Overlay  # noqa: E402


# ---------------------------------------------------------------- pure logic (shared with the offline preview)
def geometry(active, monitors, cfg):
    """The focused window's rectangle in its monitor's local pixels, or None when nothing should be
    drawn: no active window, truly fullscreen, a game class, or a window on no known monitor."""
    if not active or active.get("fullscreen", 0) != 0:
        return None
    cls = active.get("class", "")
    if class_matches(cls, cfg["figures"]["ignore_classes"]):
        return None
    mon = next((m for m in monitors if m.get("id") == active.get("monitor")), None)
    if not mon:
        return None
    ax, ay = active.get("at", (0, 0))
    w, h = active.get("size", (0, 0))
    ws = (active.get("workspace") or {}).get("id", 0)
    return mon["name"], {"x": ax - mon.get("x", 0), "y": ay - mon.get("y", 0), "w": w, "h": h,
                         "cls": cls, "ws": ws, "floating": bool(active.get("floating", False))}


def draw_frame(cr, geo, cfg_frame):
    """Brackets, the class/workspace tag and the LOCK readout around `geo`'s rectangle."""
    x, y, w, h = geo["x"], geo["y"], geo["w"], geo["h"]
    if cfg_frame.get("brackets", True):
        _draw_brackets(cr, x, y, w, h)
    if cfg_frame.get("tag", True) and geo.get("ws", 0) > 0:
        _draw_tag(cr, x, y, geo["cls"], geo["ws"])
    if cfg_frame.get("lock", True):
        _draw_lock(cr, x, y, w)


def _draw_brackets(cr, x, y, w, h):
    leg, out = 24, 12
    cr.set_line_width(4)
    d.rgba(cr, d.BONE)
    for cx, cy, sx, sy in ((x - out, y - out, 1, 1), (x + w + out, y - out, -1, 1),
                           (x - out, y + h + out, 1, -1), (x + w + out, y + h + out, -1, -1)):
        cr.move_to(cx + sx * leg, cy)
        cr.line_to(cx, cy)
        cr.line_to(cx, cy + sy * leg)
        cr.stroke()


def _draw_tag(cr, x, y, cls, ws):
    cls_lay = d.layout(cr, cls.upper(), d.F_DISPLAY, 14, weight=d.DISPLAY_WEIGHT)
    ws_lay = d.layout(cr, f"{int(ws):02d}", d.F_DISPLAY, 14, weight=d.DISPLAY_WEIGHT)
    cw, ch = d.text_size(cls_lay)
    ww, wh = d.text_size(ws_lay)
    pad, gap, bh = 10, 10, 22
    bx, by = x + 18, y - 12
    bw = pad + cw + gap + ww + pad
    d.block(cr, bx, by, bw, bh, d.BONE)
    d.draw_text(cr, cls_lay, bx + pad, by + (bh - ch) / 2, d.INK)
    d.draw_text(cr, ws_lay, bx + pad + cw + gap, by + (bh - wh) / 2, d.CLARET)


def _draw_lock(cr, x, y, w):
    lay = d.layout(cr, "LOCK", d.F_META, 11, spacing=3)
    lw, lh = d.text_size(lay)
    pad, inset = 8, 18
    bw, bh = lw + 2 * pad, lh + 2 * pad
    bx, by = x + w - inset - bw, y - bh / 2
    d.block(cr, bx, by, bw, bh, d.INK)
    d.draw_text(cr, lay, bx + pad, by + pad, d.GOLD)


# ---------------------------------------------------------------- the surface
class Frame(_Overlay):
    """A full-monitor overlay, under the panels, that paints a static frame around the focused window."""

    def __init__(self, app, cfg, gdk_monitor, name):
        super().__init__(app, f"eva-frame-{name}", keyboard="none", passthrough=True)
        LS.set_layer(self.win, LS.Layer.TOP)       # the base class puts surfaces on `overlay`; this sits under them
        self.cfg, self.name = cfg, name
        self.geo, self.poll_id = None, None
        self.place(gdk_monitor)
        self.show()                                 # left visible forever: an empty paint costs nothing

    def _busy(self):
        """True while the launcher or a modal overlay (power, alt-tab) is up: the brackets step aside."""
        launcher = getattr(self.app, "launcher", None)
        if launcher is not None and getattr(launcher, "visible", False):
            return True
        overlays = getattr(self.app, "overlays", {})
        return any(getattr(overlays.get(key), "visible", False) for key in ("power", "alttab"))

    def update(self):
        try:
            active = self.app.hypr.j("activewindow") or {}
            mons = self.app.hypr.j("monitors") or []
        except Exception:                           # a socket hiccup is "nothing to draw", never a crash
            traceback.print_exc()
            active, mons = {}, []
        geo = geometry(active, mons, self.cfg)
        new_geo = geo[1] if geo and geo[0] == self.name and not self._busy() else None
        floating = bool(new_geo and new_geo.get("floating"))
        if floating and self.poll_id is None:
            self.poll_id = GLib.timeout_add(200, self._poll)
        elif not floating and self.poll_id is not None:
            GLib.source_remove(self.poll_id)
            self.poll_id = None
        if new_geo != self.geo:
            self.geo = new_geo
            self.queue()

    def _poll(self):
        self.update()
        return GLib.SOURCE_CONTINUE if self.geo and self.geo.get("floating") else GLib.SOURCE_REMOVE

    def queue(self):
        self.view.queue_draw()

    def destroy(self):
        if self.poll_id is not None:
            GLib.source_remove(self.poll_id)
            self.poll_id = None
        super().destroy()

    def _paint(self, snap, w, h):
        if self.geo:
            cr = snap.append_cairo(rect(0, 0, w, h))
            draw_frame(cr, self.geo, self.cfg["frame"])
