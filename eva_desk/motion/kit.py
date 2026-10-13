"""The drawing kit of the motion pieces: shapes, type, clips and transforms over one GTK snapshot.

A piece works in design px. The kit scales them so that a frame is 720 high on anything as wide as 16:9
(1720x720 on a 21:9 monitor) and taller on a narrower monitor; `W` and `H` are the frame the piece lays out from.
Colours are the rgba tuples of draw.py (`d.BONE`, `d.col("ink4")`).

Everything here is something the GPU draws by itself: rectangles, borders, glyphs, pictures and gradients, moved
by transforms, cut by masks and laid on by blends. Nothing is rasterised on the CPU frame after frame, which rules
two things out:

- Path nodes. GTK rasterises a path each time it changes, and in a piece everything changes every frame; and
  cairo, which draws the offline frames, asserts on some nested path clips. A shape that is not a rectangle is
  a turned or sheared one (`lines`, `para`).
- Glyphs under a scale that changes. GTK keeps a glyph by its exact size on screen, so type that grows or
  shrinks is rasterised again for every frame. Such type is a `stamp`: set once as a picture, then scaled.
"""
import contextlib
import math

import cairo

from .. import gtkutil  # (pins GTK 4 before any gi.repository import)

import gi  # noqa: E402

gi.require_version("Gsk", "4.0")
from gi.repository import Gdk, GLib, Graphene, Gsk, Gtk, Pango  # noqa: E402

from .. import draw as d  # noqa: E402
from .timeline import clamp  # noqa: E402

STAMP_SIDE = 2048      # a stamp's picture is never wider or taller than this many px; past that it is scaled up
PLAIN = {"common", "inherited", "latin", "greek", "cyrillic", "armenian", "georgian", "han", "hiragana", "katakana",
         "hangul", "bopomofo"}       # scripts whose letters stand apart and run left to right: a name in them can be cut

_layouts = {}          # (string, family, weight, size, spacing) -> Pango layout
_letters = {}          # the same key -> what letters() found
_colours = {}          # (rgba tuple, alpha) -> Gdk.RGBA
_stamps = {}           # the stamps of kits that were given no store of their own (the offline renderer's)
_UNIT = Graphene.Rect().init(0, 0, 1, 1)


def design(w, h):
    """(s, W, H) for a w x h surface: the scale, and the frame in design px."""
    s = min(h / 720, w / 1280)
    return s, w / s, h / s


def _rgba(colour, alpha=1.0):
    alpha = round(alpha, 3)                          # the key is what is drawn: a frame must not depend on the frames before it
    key = (colour, alpha)
    c = _colours.get(key)
    if c is None:
        if len(_colours) > 2048:
            _colours.clear()
        c = _colours[key] = Gdk.RGBA()
        c.red, c.green, c.blue, c.alpha = colour[0], colour[1], colour[2], colour[3] * alpha
    return c


def _rect(x, y, w, h):
    return Graphene.Rect().init(x, y, w, h)


def _point(x, y):
    return Graphene.Point().init(x, y)


def _face(face):
    return (d.F_DISPLAY, d.DISPLAY_WEIGHT) if face == "display" else (d.F_META, 400)


def _layout(string, face, size, spacing, width=None):
    key = (string, *_face(face), size, spacing, width)
    lay = _layouts.get(key)
    if lay is None:
        if len(_layouts) > 512:                      # a running counter makes a new string every frame
            _layouts.clear()
        lay = _layouts[key] = d.plain_layout(string, key[1], size, weight=key[2], spacing=spacing)
        if width is not None:                        # cut to a width: Pango puts the ellipsis where the script wants it
            lay.set_width(int(width * Pango.SCALE))
            lay.set_ellipsize(Pango.EllipsizeMode.END)
    return lay


def _picture(store, key, box, fine, draw):
    """(texture, x, y, w, h): what `draw(cr)` paints inside the design-px box (x, y, w, h), set once as a picture,
    `fine` px to the design px and never more than STAMP_SIDE px on a side."""
    x, y, w, h = box
    fine = min(fine, STAMP_SIDE / max(w, h))
    pw, ph = (max(1, min(STAMP_SIDE, math.ceil(side * fine))) for side in (w, h))
    key = (*key, pw, ph)
    made = store.get(key)
    if made is None:
        if len(store) > 64:
            store.clear()
        surf = cairo.ImageSurface(cairo.FORMAT_ARGB32, pw, ph)
        cr = cairo.Context(surf)
        cr.scale(pw / w, ph / h)
        cr.translate(-x, -y)
        draw(cr)
        made = store[key] = (gtkutil.texture(surf), x, y, w, h)
    return made


def _stamp(store, string, face, size, spacing, colour, fine):
    """_picture() of `string`; the box lies about its layout's corner."""
    lay = _layout(string, face, size, spacing)
    ink = lay.get_pixel_extents()[0]
    box = (ink.x - 1, ink.y - 1, ink.width + 2, ink.height + 2)           # a clear px all round: its edge is filtered when it is scaled
    return _picture(store, (string, *_face(face), size, spacing, colour), box, fine, lambda cr: d.draw_text(cr, lay, 0, 0, colour))


def hex_cells(x0, y0, x1, y1, r, ox=0.0, oy=0.0):
    """(cx, cy, col, row) of the pointy-top cells of radius r that cover the box and one ring more; (ox, oy) shifts the lattice."""
    dx, dy, out = math.sqrt(3) * r, 1.5 * r, []
    for row in range(math.floor((y0 - oy) / dy) - 1, math.ceil((y1 - oy) / dy) + 2):
        shift = dx / 2 if row & 1 else 0.0           # every other row sits half a cell over
        for col in range(math.floor((x0 - ox - shift) / dx) - 1, math.ceil((x1 - ox - shift) / dx) + 2):
            out.append((ox + col * dx + shift, oy + row * dy, col, row))
    return out


def screen_box(x, y, w, h):
    """(x, y, w, h): the box a Kit.screen() of that size leaves for what it shows, under its tag."""
    return x + 13, y + 28, w - 26, h - 38


def cover_box(tw, th, x, y, w, h, zoom=1.0, fx=0.5, fy=0.5):
    """(ix, iy, iw, ih): where a tw x th picture lies when it fills the box (x, y, w, h) at `zoom`. What overhangs
    is split by (fx, fy): 0 keeps the picture's left or top edge on the box's, 1 its right or bottom one."""
    k = max(w / tw, h / th) * zoom
    iw, ih = tw * k, th * k
    return x + (w - iw) * fx, y + (h - ih) * fy, iw, ih


class Kit:
    def __init__(self, snap, w, h, density=1.0, stamps=None):
        """A kit over `snap` for a w x h frame. `density` is how many px the monitor has to one unit of w and h;
        `stamps` is where the pictures of type are kept (whoever owns it decides when they go)."""
        self.snap = snap
        self.s, self.W, self.H = design(w, h)
        self.density = density
        self.stamps = _stamps if stamps is None else stamps
        snap.save()
        snap.scale(self.s, self.s)

    def close(self):
        """Undo the scale. Whoever made the kit calls this once the piece has painted."""
        self.snap.restore()

    # ---------------------------------------------------------------- shapes
    def rect(self, x, y, w, h, colour, alpha=1.0):
        if w > 0 and h > 0:
            self.snap.append_color(_rgba(colour, alpha), _rect(x, y, w, h))

    def _border(self, x, y, w, h, widths, colour, alpha):
        outline = Gsk.RoundedRect()
        outline.init_from_rect(_rect(x, y, w, h), 0)
        c = _rgba(colour, alpha)
        self.snap.append_border(outline, widths, [c, c, c, c])

    def stroke_rect(self, x, y, w, h, colour, width, alpha=1.0):
        """The outline of a rectangle, the stroke centred on its edge."""
        self._border(x - width / 2, y - width / 2, w + width, h + width, [width] * 4, colour, alpha)

    def band(self, outer, inner, colour, alpha=1.0):
        """What lies between two rectangles (x, y, w, h), the inner one inside the outer."""
        (ox, oy, ow, oh), (ix, iy, iw, ih) = outer, inner
        self._border(ox, oy, ow, oh, [iy - oy, ox + ow - ix - iw, oy + oh - iy - ih, ix - ox], colour, alpha)      # top, right, bottom, left

    def para(self, p0, p1, p3, colour, alpha=1.0):
        """A parallelogram with corners p0, p1, p1 + p3 - p0, p3: a sheared rectangle."""
        ux, uy, vx, vy = p1[0] - p0[0], p1[1] - p0[1], p3[0] - p0[0], p3[1] - p0[1]
        if abs(ux * vy - uy * vx) < 1e-9:
            return
        length, turn = math.hypot(ux, uy), math.atan2(uy, ux)
        c, s = math.cos(turn), math.sin(turn)
        sx, sy = vx * c + vy * s, vy * c - vx * s            # the second side, seen with the first one lying along x
        self.snap.save()                                     # turn, shear, scale: a raw matrix would not count as 2D,
        self.snap.translate(_point(p0[0], p0[1]))            # and GTK cannot draw those offline
        if turn:
            self.snap.rotate(math.degrees(turn))
        if abs(sx) > 1e-9:
            self.snap.transform(Gsk.Transform.new().skew(math.degrees(math.atan(sx / sy)), 0))
        self.snap.scale(length, sy)
        self.snap.append_color(_rgba(colour, alpha), _UNIT)
        self.snap.restore()

    def lines(self, segments, colour, width, alpha=1.0):
        """Segments [(x0, y0, x1, y1), ...] of one colour and width, each a turned rectangle."""
        c = _rgba(colour, alpha)
        for x0, y0, x1, y1 in segments:
            length = math.hypot(x1 - x0, y1 - y0)
            if length <= 0:
                continue
            self.snap.save()
            self.snap.translate(_point(x0, y0))
            self.snap.rotate(math.degrees(math.atan2(y1 - y0, x1 - x0)))
            self.snap.append_color(c, _rect(0, -width / 2, length, width))
            self.snap.restore()

    def hazard(self, x, y, w, h, a, b=None, period=28.0, offset=0.0, alpha=1.0):
        """Diagonal warning stripes inside the box, as draw.hazard paints them; `offset` slides them to the right."""
        if w <= 0 or h <= 0:
            return
        with self.clip(x, y, w, h):
            if b is not None:
                self.rect(x, y, w, h, b, alpha)
            half = period / 2
            k = x - h - period + offset % period
            while k < x + w + h:
                self.para((k, y + h), (k + half, y + h), (k + h, y), a, alpha)
                k += period

    def segbar(self, x, y, w, h, value, colour, n, off=None):
        """A bar of n segments, the first `value` of them lit."""
        off = d.col("ink4") if off is None else off
        pitch, lit = w / n, round(clamp(value) * n)
        for i in range(n):
            self.rect(x + i * pitch, y, pitch * 0.72, h, colour if i < lit else off)

    def block(self, x, y, w, h, colour, shadow=None, off=7.0, alpha=1.0):
        """A slab over its hard shadow, the shadow `off` px to the right and down."""
        if shadow is not None:
            self.rect(x + off, y + off, w, h, shadow, alpha)
        self.rect(x, y, w, h, colour, alpha)

    def brackets(self, x0, y0, x1, y1, leg, colour, width=2.0, alpha=1.0):
        """The four corners of a box, each two legs, the stroke centred on the box's edge."""
        half = width / 2
        for x, y, sx, sy in ((x0, y0, 1, 1), (x1, y0, -1, 1), (x0, y1, 1, -1), (x1, y1, -1, -1)):
            self.rect(min(x - sx * half, x + sx * leg), y - half, leg + half, width, colour, alpha)             # along the edge, the corner included
            self.rect(x - half, min(y + sy * half, y + sy * leg), width, leg - half, colour, alpha)             # and away from it

    def lamp(self, x, y, size, colour):
        """A square lamp and its halo."""
        self.rect(x - 3, y - 3, size + 6, size + 6, colour, 0.22)
        self.rect(x, y, size, size, colour)

    def hexagon(self, cx, cy, r, colour, alpha=1.0, width=2.0, fill=0.0):
        """A pointy-top outline of radius r, and inside it the colour at `fill` of the line's strength. A hexagon is
        neither a rectangle nor a sheared one, so it is a picture, set once."""
        if alpha <= 0:
            return
        a, b = r * math.cos(math.pi / 6) + width + 1, r + width + 1          # half the picture: the outline, its line and a clear px

        def draw(cr):
            for i in range(6):
                turn = math.pi / 6 + i * math.pi / 3
                cr.line_to(r * math.cos(turn), r * math.sin(turn))
            cr.close_path()
            if fill > 0:
                d.rgba(cr, colour, colour[3] * fill)
                cr.fill_preserve()
            d.rgba(cr, colour)
            cr.set_line_width(width)
            cr.stroke()
        texture, x, y, w, h = _picture(self.stamps, ("hexagon", r, width, fill, colour), (-a, -b, 2 * a, 2 * b), self.s * self.density, draw)
        with self.opacity(alpha) if alpha < 1 else contextlib.nullcontext():
            self.snap.append_texture(texture, _rect(cx + x, cy + y, w, h))

    def ring(self, cx, cy, r, colour, width=2.0, alpha=1.0):
        """A pointy-top hexagon outline of any radius, as six lines: for one whose size changes with every frame,
        where hexagon() would set a new picture each time."""
        if r <= 0 or alpha <= 0:
            return
        pts = [(cx + r * math.cos(math.pi / 6 + i * math.pi / 3), cy + r * math.sin(math.pi / 6 + i * math.pi / 3)) for i in range(6)]
        self.lines([(*pts[i], *pts[(i + 1) % 6]) for i in range(6)], colour, width, alpha)

    def screen(self, x, y, w, h, tag="", hot=""):
        """A screen of the MFD panels: a bezel and its outline, a dark face under scanlines, its tag and, a little
        past it, a word in gold. Returns (x, y, w, h), the box that is left for what the screen shows."""
        self.rect(x, y, w, h, d.col("ink3"))
        self._border(x, y, w, h, [1.0] * 4, d.col("ink4"), 1.0)
        self.rect(x + 5, y + 5, w - 10, h - 10, d.col("ink_deep"))
        self.scanlines(x + 5, y + 5, w - 10, h - 10)
        if tag:
            width = self.text(tag, x + 13, y + 20, 9.5, d.BONE3, spacing=2)
            if hot:
                self.text(hot, x + 13 + width + 8, y + 20, 9.5, d.GOLD, spacing=2)
        return screen_box(x, y, w, h)

    def spark(self, x, y, w, h, values, colour):
        """The history of a reading as a line, the newest at the right, over a faint fill. `values` run from 0 to 1,
        newest first. A line through many points is many short ones, and its fill is a column under each."""
        heights = [clamp(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else 0.0 for v in values or []]
        if len(heights) < 2 or w <= 0 or h <= 4:
            return
        step = w / (len(heights) - 1)
        points = [(x + w - i * step, y + h - 2 - v * (h - 4)) for i, v in enumerate(heights)]
        with self.clip(x, y, w, h):
            for (x1, y1), (x0, y0) in zip(points, points[1:]):
                top = (y0 + y1) / 2
                self.rect(x0, top, step, y + h - top, colour, 0.13)
            self.lines([(x0, y0, x1, y1) for (x1, y1), (x0, y0) in zip(points, points[1:])], colour, 1.5)

    def keep(self, slot, key, draw):
        """What `draw()` paints, kept as one node for as long as `key` stays the same: for the parts of a loop that
        are still while others move. They are then not built again for every frame, and a node that is the same
        from one frame to the next tells GTK that nothing changed there. `slot` names the place; it holds one
        node, whatever it has shown before."""
        held = self.stamps.get(("node", slot))
        if held is None or held[0] != key:
            outer, self.snap = self.snap, Gtk.Snapshot()
            try:
                draw()
                node = self.snap.to_node()
            finally:
                self.snap = outer
            held = self.stamps[("node", slot)] = (key, node)
        if held[1] is not None:
            self.snap.append_node(held[1])

    def sprite(self, texture, x, y, w, h, alpha=1.0):
        """A picture stretched over a box."""
        if alpha > 0 and w > 0 and h > 0:
            with self.opacity(alpha) if alpha < 1 else contextlib.nullcontext():
                self.snap.append_texture(texture, _rect(x, y, w, h))

    def cover(self, texture, x, y, w, h, zoom=1.0, fx=0.5, fy=0.5, alpha=1.0):
        """A picture filling the box and cut to it, laid as cover_box() says. Returns that, so that a point of the
        picture can be found on screen."""
        lay = cover_box(texture.get_width(), texture.get_height(), x, y, w, h, zoom, fx, fy)
        if alpha > 0 and w > 0 and h > 0:
            with self.clip(x, y, w, h), self.opacity(alpha) if alpha < 1 else contextlib.nullcontext():
                self.snap.append_texture(texture, _rect(*lay))
        return lay

    def radial(self, x, y, r, colour, alpha):
        """A glow: `alpha` at the centre, nothing at r."""
        if r <= 0 or alpha <= 0:
            return
        inner, outer = Gsk.ColorStop(), Gsk.ColorStop()
        inner.offset, inner.color = 0.0, _rgba(colour, alpha)
        outer.offset, outer.color = 1.0, _rgba(colour, 0.0)
        self.snap.append_radial_gradient(_rect(x - r, y - r, 2 * r, 2 * r), _point(x, y), r, r, 0.0, 1.0, [inner, outer])

    # ---------------------------------------------------------------- type
    def measure(self, string, size, face="meta", spacing=0.0, width=None):
        return _layout(string, face, size, spacing, width).get_pixel_extents()[1].width

    def text(self, string, x, y, size, colour, face="meta", spacing=0.0, align="left", alpha=1.0, width=None):
        """Type as glyphs: for type that keeps its size while it shows (it may move). `y` is the baseline;
        returns the width. With `width`, type that is wider is cut to it with an ellipsis."""
        lay = _layout(string, face, size, spacing, width)
        width = lay.get_pixel_extents()[1].width
        if string and alpha > 0:
            left = x - (width if align == "right" else width / 2 if align == "center" else 0)
            self.snap.save()
            self.snap.translate(_point(left, y - lay.get_baseline() / Pango.SCALE))
            self.snap.append_layout(lay, _rgba(colour, alpha))
            self.snap.restore()
        return width

    def stamp(self, string, x, y, size, colour, face="meta", spacing=0.0, align="left", alpha=1.0, most=1.0):
        """Type that changes size while it shows: text(), but set once as a picture that the GPU then scales.
        `most` is the largest scale it is drawn under, which is how fine the picture is made."""
        lay = _layout(string, face, size, spacing)
        width = lay.get_pixel_extents()[1].width
        if string and alpha > 0:
            texture, bx, by, bw, bh = _stamp(self.stamps, string, face, size, spacing, colour, self.s * self.density * most)
            left = x - (width if align == "right" else width / 2 if align == "center" else 0)
            with self.opacity(alpha) if alpha < 1 else contextlib.nullcontext():
                self.snap.append_texture(texture, _rect(left + bx, y - lay.get_baseline() / Pango.SCALE + by, bw, bh))
        return width

    def letters(self, string, size, face="meta", spacing=0.0):
        """`string` cut where a caret can stand: letters, each with its marks, a ligature or an emoji whole.
        None when cutting would change how it reads: a script that joins its letters, or runs right to left."""
        key = (string, *_face(face), size, spacing)
        if key not in _letters:
            if len(_letters) > 256:
                _letters.clear()
            _letters[key] = None
            if all(getattr(GLib.unichar_get_script(ch), "value_nick", "") in PLAIN for ch in string):
                cuts, it = set(), _layout(string, face, size, spacing).get_iter()
                while True:
                    cuts.add(it.get_index())
                    if not it.next_cluster():
                        break
                raw = string.encode()
                cuts = sorted(cuts) + [len(raw)]
                _letters[key] = [raw[a:b].decode() for a, b in zip(cuts, cuts[1:]) if b > a]
        found = _letters[key]
        return None if found is None else list(found)

    # ---------------------------------------------------------------- scopes: `with kit.clip(...):`
    @contextlib.contextmanager
    def clip(self, x, y, w, h):
        self.snap.push_clip(_rect(x, y, max(0, w), max(0, h)))
        try:
            yield
        finally:
            self.snap.pop()

    @contextlib.contextmanager
    def tile(self, x, y, w, h, tw, th):
        """What is painted inside, in the cell (x, y, tw, th), repeats over the box (x, y, w, h)."""
        self.snap.push_repeat(_rect(x, y, max(0, w), max(0, h)), _rect(x, y, tw, th))
        try:
            yield
        finally:
            self.snap.pop()

    def scanlines(self, x, y, w, h, alpha=0.04):
        """A bone line of 1 px every third px."""
        with self.tile(x, y, w, h, w, 3):
            self.rect(x, y, w, 1, d.BONE, alpha)

    @contextlib.contextmanager
    def _cut(self, draw_mask):
        """What is painted inside shows everywhere but where `draw_mask` paints."""
        self.snap.push_mask(Gsk.MaskMode.INVERTED_ALPHA)
        draw_mask()
        self.snap.pop()                              # the mask is recorded; what follows is the picture it cuts
        try:
            yield
        finally:
            self.snap.pop()

    def clip_out(self, x, y, w, h):
        """Everything but this rectangle (a mask, so it also works turned)."""
        return self._cut(lambda: self.rect(x, y, w, h, d.INK))

    def clip_out_para(self, p0, p1, p3):
        """Everything but this parallelogram (corners as in para())."""
        return self._cut(lambda: self.para(p0, p1, p3, d.INK))

    @contextlib.contextmanager
    def screen_blend(self, ground):
        """What is painted inside is screened onto what `ground()` paints: black adds nothing, light adds light. A
        blend cannot see what lies under it, so the ground is painted again inside it."""
        self.snap.push_blend(Gsk.BlendMode.SCREEN)
        ground()
        self.snap.pop()                              # the ground is recorded; what follows goes on top of it
        try:
            yield
        finally:
            self.snap.pop()

    @contextlib.contextmanager
    def soft_band(self, cx, half, y0, y1):
        """What is painted inside shows only in an upright band: whole at cx, nothing at cx - half and cx + half."""
        self.snap.push_mask(Gsk.MaskMode.ALPHA)
        if half > 0 and y1 > y0:
            stops = []
            for offset, strength in ((0.0, 0.0), (0.5, 1.0), (1.0, 0.0)):
                stop = Gsk.ColorStop()
                stop.offset, stop.color = offset, _rgba((1.0, 1.0, 1.0, 1.0), strength)
                stops.append(stop)
            self.snap.append_linear_gradient(_rect(cx - half, y0, 2 * half, y1 - y0), _point(cx - half, y0), _point(cx + half, y0), stops)
        self.snap.pop()                              # the mask is recorded; what follows is what it lets through
        try:
            yield
        finally:
            self.snap.pop()

    @contextlib.contextmanager
    def opacity(self, alpha):
        self.snap.push_opacity(clamp(alpha))
        try:
            yield
        finally:
            self.snap.pop()

    @contextlib.contextmanager
    def transform(self, dx=0.0, dy=0.0, rotate=0.0, scale=1.0):
        """Move the origin, then turn about it (radians), then scale about it."""
        self.snap.save()
        self.snap.translate(_point(dx, dy))
        if rotate:
            self.snap.rotate(math.degrees(rotate))
        if scale != 1.0:
            self.snap.scale(scale, scale)
        try:
            yield
        finally:
            self.snap.restore()
