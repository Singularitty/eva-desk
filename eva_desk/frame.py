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


LEG, OUT, LINE = 24, 12, 4          # bracket leg length, distance outside the window, stroke width
EDGE = 2                            # the painted frame keeps this far inside its bounds


def corners(geo, bounds=None):
    """The four bracket corners as (cx, cy, sx, sy): the corner point on the stroke's centre line
    and the direction its legs run. They sit OUT px outside `geo`'s rectangle; with `bounds`
    = (x0, y0, x1, y1) (the monitor less the bar) each corner is pulled in so the whole stroke
    stays EDGE px inside -- an edge-touching window's brackets never fall off-screen or onto the bar."""
    x, y, w, h = geo["x"], geo["y"], geo["w"], geo["h"]
    left, top, right, bottom = x - OUT, y - OUT, x + w + OUT, y + h + OUT
    if bounds is not None:
        inset = EDGE + LINE / 2
        x0, y0, x1, y1 = bounds[0] + inset, bounds[1] + inset, bounds[2] - inset, bounds[3] - inset
        left, right = min(max(left, x0), x1), max(min(right, x1), x0)
        top, bottom = min(max(top, y0), y1), max(min(bottom, y1), y0)
    return ((left, top, 1, 1), (right, top, -1, 1), (left, bottom, 1, -1), (right, bottom, -1, -1))


def bracket_rects(geo, bounds=None):
    """The painted area of every bracket leg as (x, y, w, h): two per corner, the horizontal leg
    (which carries the square corner) and the vertical one. Exactly what `draw_frame` fills."""
    half = LINE / 2
    out = []
    for cx, cy, sx, sy in corners(geo, bounds):
        hx0, hx1 = sorted((cx - sx * half, cx + sx * LEG))
        vy0, vy1 = sorted((cy + sy * half, cy + sy * LEG))
        out.append((hx0, cy - half, hx1 - hx0, LINE))
        out.append((cx - half, vy0, LINE, vy1 - vy0))
    return out


def draw_frame(cr, geo, cfg_frame, bounds=None):
    """Brackets, the class/workspace tag and the LOCK readout around `geo`'s rectangle, kept
    inside `bounds` (x0, y0, x1, y1) when given (see `corners`). The tag and LOCK ride on the
    top edge, so when the top corners are pulled down below the bar they move down with them."""
    (left, top, _, _), (right, _, _, _) = corners(geo, bounds)[:2]
    floor = bounds[1] + EDGE if bounds is not None else float("-inf")
    if cfg_frame.get("brackets", True):
        _draw_brackets(cr, bracket_rects(geo, bounds))
    if cfg_frame.get("tag", True) and geo.get("ws", 0) > 0:
        _draw_tag(cr, left + OUT, top + OUT, geo["cls"], geo["ws"], floor)
    if cfg_frame.get("lock", True):
        _draw_lock(cr, right - OUT, top + OUT, floor)


def _draw_brackets(cr, rects):
    d.rgba(cr, d.BONE)
    for x, y, w, h in rects:
        cr.rectangle(x, y, w, h)
    cr.fill()


def _draw_tag(cr, x, y, cls, ws, floor):
    """The tag block, its left edge 18 px in from the window's left edge `x`, centred-ish on the
    top edge `y` (in the border line); never above `floor`."""
    cls_lay = d.layout(cr, cls.upper(), d.F_DISPLAY, 14, weight=d.DISPLAY_WEIGHT)
    ws_lay = d.layout(cr, f"{int(ws):02d}", d.F_DISPLAY, 14, weight=d.DISPLAY_WEIGHT)
    cw, ch = d.text_size(cls_lay)
    ww, wh = d.text_size(ws_lay)
    pad, gap, bh = 10, 10, 22
    bx, by = x + 18, max(y - 12, floor)
    bw = pad + cw + gap + ww + pad
    d.block(cr, bx, by, bw, bh, d.BONE)
    d.draw_text(cr, cls_lay, bx + pad, by + (bh - ch) / 2, d.INK)
    d.draw_text(cr, ws_lay, bx + pad + cw + gap, by + (bh - wh) / 2, d.CLARET)


def _draw_lock(cr, x, y, floor):
    """The LOCK block, its right edge 18 px in from the window's right edge `x`, centred on the
    top edge `y`; never above `floor`."""
    lay = d.layout(cr, "LOCK", d.F_META, 11, spacing=3)
    lw, lh = d.text_size(lay)
    pad, inset = 8, 18
    bw, bh = lw + 2 * pad, lh + 2 * pad
    bx, by = x - inset - bw, max(y - bh / 2, floor)
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

    def bar_height(self):
        """The bar's height on this monitor (logical px), or 0 when it has no bar."""
        if not self.cfg["bar"]["enabled"] or self.name not in getattr(self.app, "bars", {}):
            return 0
        return int(self.cfg["bar"]["height"])

    def _paint(self, snap, w, h):
        if self.geo:
            cr = snap.append_cairo(rect(0, 0, w, h))
            draw_frame(cr, self.geo, self.cfg["frame"], bounds=(0, self.bar_height(), w, h))
