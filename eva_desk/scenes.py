"""Scene drawing, independent of windows: everything here paints into a cairo context of size w x h.

Scenes sit behind windows (stage layer); flashes sit above everything for a few frames.
Geometry follows the approved boards (1720x720 design space mapped onto the monitor).
"""
import json
import math

from . import draw as d
from .config import asset_path


class Geometry:
    def __init__(self, w, h, stage_px):
        """stage_px: width kept free at the right edge for this workspace's figure (0 = none)."""
        self.w, self.h, self.stage = w, h, stage_px

    # figure: centred in the reserved stage, standing on the bottom edge
    def figure(self):
        surf = d.image("figures/unit01.png")
        bh = self.h * 0.89
        bw = bh * surf.get_width() / surf.get_height()
        cx = self.w - self.stage / 2
        x, y = cx - bw / 2, self.h - bh
        return surf, x, y, bw, bh, cx, self.h - bh * 0.62

# ---------------------------------------------------------------- the figure's entrance (smooth, stage only)
def ease_out_cubic(t):
    return 1 - (1 - t) ** 3


def ease_out_back(t, s=1.25):
    t -= 1
    return t * t * ((s + 1) * t + s) + 1


def figure_entry(t):
    """State of the figure's entrance at t in [0, 1] (1 = at rest). Shared by the live stage (GPU) and
    the offline previews, so both animate the same way."""
    t = max(0.0, min(1.0, t))
    e = ease_out_cubic(t)
    land = ease_out_back(min(1.0, t / 0.85))
    return {
        "back_alpha": ease_out_cubic(min(1.0, t / 0.45)),   # speed lines fade in...
        "back_scale": 1.05 - 0.05 * e,                      # ...settling from a slight zoom
        "fig_alpha": ease_out_cubic(min(1.0, t / 0.3)),
        "fig_scale": 1.08 - 0.08 * land,                    # lands with a small overshoot, from his feet
        "fig_dx": 0.035 * (1 - land),                       # slides in from the right (x screen height)
        "echo": 1.0 + 2.2 * (1 - e),                        # red trail starts wide, settles back
        "glow": 0.5 * (1 - e) ** 2,                         # soft bloom behind him, fading out
    }


def _at_field(cr, g, cx, cy, band=True, hot=False):
    """nerv backdrop: ink ground, a honeycomb A.T. field over the stage with the contact cell at (cx, cy),
    a purple stage band along the floor. hot (berserk): the cells and the band go NERV orange."""
    d.rgba(cr, d.INK)
    cr.paint()
    r = g.h * 0.11
    cr.save()
    cr.rectangle(g.w - g.stage if g.stage else 0, 0, g.stage or g.w, g.h)
    cr.clip()
    cr.translate(g.w - g.stage if g.stage else 0, 0)
    if hot:
        d.hex_field(cr, g.stage or g.w, g.h, cx - (g.w - g.stage if g.stage else 0), cy, r, line=d.LED, fill=d.LED, accent=d.CORAL)
    else:
        d.hex_field(cr, g.stage or g.w, g.h, cx - (g.w - g.stage if g.stage else 0), cy, r)
    cr.restore()
    if band:
        bh = g.h * 0.036
        d.hazard(cr, g.w - g.stage if g.stage else 0, g.h - bh, g.stage or g.w, bh, d.LED if hot else d.CLARET, d.INK, period=g.h * 0.039)


def figure_back(cr, g, hot=False):
    """The backdrop without the figure: the A.T. field (orange when berserk)."""
    surf, x, y, bw, bh, cx, cy = g.figure()
    _at_field(cr, g, cx, cy, hot=hot)


def glow(cr, size):
    """Soft bone bloom (a square texture, drawn scaled behind the figure)."""
    import cairo
    r = size / 2
    grad = cairo.RadialGradient(r, r, 0, r, r, r)
    b = d.BONE
    grad.add_color_stop_rgba(0, b[0], b[1], b[2], 0.95)
    grad.add_color_stop_rgba(0.35, b[0], b[1], b[2], 0.45)
    grad.add_color_stop_rgba(1, b[0], b[1], b[2], 0)
    cr.set_source(grad)
    cr.paint()


def figure_frame(cr, g, t):
    """cairo version of the entrance at t (previews); the stage does the same on the GPU."""
    import cairo
    p = figure_entry(t)
    surf, x, y, bw, bh, cx, cy = g.figure()
    back = cairo.ImageSurface(cairo.FORMAT_ARGB32, int(g.w), int(g.h))
    figure_back(cairo.Context(back), g)
    cr.save()
    cr.translate(cx, cy)
    cr.scale(p["back_scale"], p["back_scale"])
    cr.translate(-cx, -cy)
    cr.set_source_surface(back, 0, 0)
    cr.paint_with_alpha(p["back_alpha"])
    cr.restore()
    if p["glow"] > 0.001:
        gs = g.h * 1.1
        gsurf = cairo.ImageSurface(cairo.FORMAT_ARGB32, 256, 256)
        glow(cairo.Context(gsurf), 256)
        d.paint_image(cr, gsurf, cx - gs / 2, cy - gs / 2, gs, gs, p["glow"])
    s, dx = p["fig_scale"], p["fig_dx"] * g.h
    fw, fh = bw * s, bh * s
    fx, fy = cx - fw / 2 + dx, g.h - fh
    echo = 18 * g.h / 720 * p["echo"]
    cr.push_group()
    d.silhouette(cr, surf, fx, fy, fw, fh, echo=echo)
    cr.pop_group_to_source()
    cr.paint_with_alpha(p["fig_alpha"])


# ---------------------------------------------------------------- stage scenes
def figure_scene(cr, g):
    """The figure at rest on its backdrop, with the echo trail."""
    surf, x, y, bw, bh, cx, cy = g.figure()
    figure_back(cr, g)
    d.silhouette(cr, surf, x, y, bw, bh, echo=18 * g.h / 720)


# ---------------------------------------------------------------- herald
class HeraldRig:
    """Body + two arms jointed at the shoulders; theta 0 = arms hanging, 90 = out, 180 = straight up."""

    def __init__(self):
        self.rig = json.loads((asset_path("herald/rig.json")).read_text())
        self.body = d.image("herald/body.png")
        self.arm_l = d.image("herald/arm_l.png")
        self.arm_r = d.image("herald/arm_r.png")

    def place(self, g):
        """Scale and offset: a giant behind the window, head just under the bar (board AA geometry)."""
        r = self.rig
        k = (g.h * 1.6) / (r["feet"] - r["head"])
        ox = g.w / 2 - r["cx"] * k
        oy = g.h * 0.089 - r["head"] * k
        return k, ox, oy

    def theta(self, t):
        r = self.rig
        return r["theta_from"] + (r["theta_to"] - r["theta_from"]) * max(0.0, min(1.0, t))

    def pieces(self, th):
        r = self.rig
        # cairo: positive angle = clockwise on screen; raising the left arm is anticlockwise
        return ((self.body, None, 0.0), (self.arm_l, r["pivot_l"], th - r["theta0_l"]),
                (self.arm_r, r["pivot_r"], -(th - r["theta0_r"])))

    def mask(self, g, t):
        """The whole figure at sweep position t as one A8 surface (so echoes have no seams)."""
        import cairo
        k, ox, oy = self.place(g)
        m = cairo.ImageSurface(cairo.FORMAT_A8, int(g.w), int(g.h))
        mc = cairo.Context(m)
        for surf, piv, ang in self.pieces(self.theta(t)):
            _piece(mc, surf, piv, ang, k, ox, oy)
        return m

    def draw(self, cr, g, t, echo=True):
        d.silhouette_mask(cr, self.mask(g, t), echo=18 * g.h / 720 if echo else 0)


def _piece(mc, surf, piv, ang, k, ox, oy):
    import cairo
    mc.save()
    mc.translate(ox, oy)
    mc.scale(k, k)
    if piv:
        mc.translate(piv[0], piv[1])
        mc.rotate(math.radians(ang))
        mc.translate(-piv[0], -piv[1])
    mc.set_source_rgba(0, 0, 0, 1)
    pat = cairo.SurfacePattern(surf)
    pat.set_filter(cairo.FILTER_BILINEAR)
    mc.mask(pat)
    mc.restore()


class HeraldAnim:
    """Frame renderer for the sweep: backdrop and body are cached, each frame only redraws the
    region the arms move through (pass it to queue_draw_area)."""

    def __init__(self, rig, g):
        import cairo
        self.rig, self.g = rig, g
        self.k, self.ox, self.oy = rig.place(g)
        self.echo = 18 * g.h / 720
        w, h = int(g.w), int(g.h)
        self.back = cairo.ImageSurface(cairo.FORMAT_ARGB32, w, h)
        herald_backdrop(cairo.Context(self.back), g)
        self.body = cairo.ImageSurface(cairo.FORMAT_A8, w, h)
        _piece(cairo.Context(self.body), rig.body, None, 0, self.k, self.ox, self.oy)
        self.mask = cairo.ImageSurface(cairo.FORMAT_A8, w, h)
        self.th = None

    def arms_box(self, th):
        """Screen bbox of both arms at angle th, grown by the echo trail."""
        xs, ys = [], []
        for surf, piv, ang in self.rig_pieces(th)[1:]:
            a = math.radians(ang)
            for cx, cy in ((0, 0), (surf.get_width(), 0), (0, surf.get_height()), (surf.get_width(), surf.get_height())):
                dx, dy = cx - piv[0], cy - piv[1]
                rx = piv[0] + dx * math.cos(a) - dy * math.sin(a)
                ry = piv[1] + dx * math.sin(a) + dy * math.cos(a)
                xs.append(self.ox + rx * self.k)
                ys.append(self.oy + ry * self.k)
        pad = 2 * self.echo + 4
        return min(xs) - pad, min(ys) - pad, max(xs) + pad, max(ys) + pad

    def rig_pieces(self, th):
        return self.rig.pieces(th)

    def set_theta(self, th):
        """Update the figure mask; returns the dirty rectangle (x, y, w, h) in screen pixels."""
        import cairo
        box = self.arms_box(th)
        if self.th is not None:
            ob = self.arms_box(self.th)
            box = (min(box[0], ob[0]), min(box[1], ob[1]), max(box[2], ob[2]), max(box[3], ob[3]))
            x0, y0 = max(0, int(box[0])), max(0, int(box[1]))
            x1, y1 = min(int(self.g.w), int(box[2]) + 1), min(int(self.g.h), int(box[3]) + 1)
        else:
            x0, y0, x1, y1 = 0, 0, int(self.g.w), int(self.g.h)
        mc = cairo.Context(self.mask)
        mc.rectangle(x0, y0, x1 - x0, y1 - y0)
        mc.clip()
        mc.set_operator(cairo.OPERATOR_SOURCE)
        mc.set_source_surface(self.body, 0, 0)
        mc.paint()
        mc.set_operator(cairo.OPERATOR_OVER)
        for surf, piv, ang in self.rig_pieces(th)[1:]:
            _piece(mc, surf, piv, ang, self.k, self.ox, self.oy)
        self.th = th
        return x0, y0, x1 - x0, y1 - y0

    def paint(self, cr):
        cr.set_source_surface(self.back, 0, 0)
        cr.paint()
        d.silhouette_mask(cr, self.mask, echo=self.echo)


def herald_backdrop(cr, g, hot=False):
    """The A.T. field across the whole screen, behind a maximised window."""
    _at_field(cr, g, g.w / 2, g.h * 0.5, band=False, hot=hot)


