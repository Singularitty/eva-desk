"""Shared cairo drawing: palette, skewed tags, speed lines, silhouettes with echoes, text."""
import math

import cairo
import gi

gi.require_version("Pango", "1.0")
gi.require_version("PangoCairo", "1.0")
from gi.repository import Pango, PangoCairo  # noqa: E402

from . import config  # noqa: E402
from .config import ASSETS, asset_path  # noqa: E402


def hexc(h, a=1.0):
    h = h.lstrip("#")
    return (int(h[0:2], 16) / 255, int(h[2:4], 16) / 255, int(h[4:6], 16) / 255, a)


_surfaces = {}          # loaded PNG assets, by name (cleared when the theme changes)


# ---------------------------------------------------------------- the active theme's palette and fonts
# Module globals so every drawer can say d.CLARET; apply_theme() rebinds them (config.load() calls it).
THEME = None
INK = WINE = WINE_D = CLARET = CLARET_HI = RED = GOLD = GOLD_L = BONE = BONE2 = BONE3 = PAPER = LED = CORAL = DIM = EMBER = ECHO = None
F_DISPLAY = F_TITLE = F_DIGITS = F_BODY = F_META = F_ACCENT = None
DISPLAY_WEIGHT, DISPLAY_ITALIC = 400, True


def col(role, a=1.0):
    """A theme colour by role name ("claret"), as an rgba tuple."""
    return hexc(THEME["colors"][role], a)


def apply_theme(theme):
    """Bind the palette and fonts of `theme` (a dict from themes.py) to this module."""
    global THEME, INK, WINE, WINE_D, CLARET, CLARET_HI, RED, GOLD, GOLD_L, BONE, BONE2, BONE3, PAPER, LED, CORAL, DIM, EMBER, ECHO
    global F_DISPLAY, F_TITLE, F_DIGITS, F_BODY, F_META, F_ACCENT, DISPLAY_WEIGHT, DISPLAY_ITALIC
    THEME = theme
    c = theme["colors"]
    INK, WINE, WINE_D, CLARET, CLARET_HI = hexc(c["ink"]), hexc(c["wine"]), hexc(c["wine_d"]), hexc(c["claret"]), hexc(c["claret_hi"])
    RED, GOLD, GOLD_L, BONE, BONE2, BONE3 = hexc(c["red"]), hexc(c["gold"]), hexc(c["gold_hi"]), hexc(c["bone"]), hexc(c["bone2"]), hexc(c["bone3"])
    PAPER, LED, CORAL, DIM, EMBER = hexc(c["paper"]), hexc(c["led"]), hexc(c["coral"]), hexc(c["dim"]), hexc(c["ember"])
    ECHO = hexc(c.get("echo", c["claret"]))
    f = theme["fonts"]
    F_DISPLAY, F_TITLE, F_DIGITS, F_BODY, F_META, F_ACCENT = f["display"], f["title"], f["digits"], f["body"], f["meta"], f["accent"]
    DISPLAY_WEIGHT, DISPLAY_ITALIC = int(f["display_weight"]), bool(f["display_italic"])
    _surfaces.clear()


apply_theme(config.current_theme())
config.on_theme(apply_theme)

SKEW = math.tan(math.radians(14))


def rgba(cr, c, alpha=None):
    cr.set_source_rgba(c[0], c[1], c[2], c[3] if alpha is None else alpha)



def image(name):
    """Load a PNG from assets/ (the active theme's copy first) once."""
    if name not in _surfaces:
        _surfaces[name] = cairo.ImageSurface.create_from_png(str(asset_path(name)))
    return _surfaces[name]


def pixbuf_surface(path):
    """Any image GdkPixbuf can read (jpg/png/...) as a cairo surface; works next to GTK 3 or 4."""
    if path in _surfaces:
        return _surfaces[path]
    import io
    gi.require_version("GdkPixbuf", "2.0")
    from gi.repository import GdkPixbuf
    pb = GdkPixbuf.Pixbuf.new_from_file(path)
    ok, buf = pb.save_to_bufferv("png", [], [])
    surf = cairo.ImageSurface.create_from_png(io.BytesIO(buf))
    _surfaces[path] = surf
    return surf


def forget(name):
    _surfaces.pop(name, None)


# ---------------------------------------------------------------- shapes
def parallelogram(cr, x, y, w, h, skew=SKEW):
    """A box whose top edge is shifted right by h*skew (CSS skewX(-14deg) look)."""
    s = h * skew / 2
    cr.move_to(x + s, y)
    cr.line_to(x + w + s, y)
    cr.line_to(x + w - s, y + h)
    cr.line_to(x - s, y + h)
    cr.close_path()


def skew_box(cr, x, y, w, h, fill, shadow=None, shadow_off=(0, 0), border=None, border_w=0, under=None, under_h=0):
    if shadow:
        parallelogram(cr, x + shadow_off[0], y + shadow_off[1], w, h)
        rgba(cr, shadow)
        cr.fill()
    parallelogram(cr, x, y, w, h)
    rgba(cr, fill)
    cr.fill_preserve()
    if border:
        rgba(cr, border)
        cr.set_line_width(border_w)
        cr.set_line_join(cairo.LINE_JOIN_MITER)
        cr.stroke()
    else:
        cr.new_path()
    if under:
        cr.save()
        parallelogram(cr, x, y, w, h)
        cr.clip()
        cr.rectangle(x - h, y + h - under_h, w + 2 * h, under_h)
        rgba(cr, under)
        cr.fill()
        cr.restore()


def look():
    """"card" (skewed tags, speed lines) or "nerv" (title-card blocks, hex fields, hazard stripes)."""
    return THEME.get("look", "card")


def block(cr, x, y, w, h, fill, shadow=None, shadow_off=(0, 0), border=None, border_w=0, under=None, under_h=0):
    """A title-card block: a plain rectangle with the same options as skew_box (the nerv look)."""
    if shadow:
        cr.rectangle(x + shadow_off[0], y + shadow_off[1], w, h)
        rgba(cr, shadow)
        cr.fill()
    cr.rectangle(x, y, w, h)
    rgba(cr, fill)
    cr.fill_preserve()
    if border:
        rgba(cr, border)
        cr.set_line_width(border_w)
        cr.set_line_join(cairo.LINE_JOIN_MITER)
        cr.stroke()
    else:
        cr.new_path()
    if under:
        cr.rectangle(x, y + h - under_h, w, under_h)
        rgba(cr, under)
        cr.fill()


def tag_box(cr, x, y, w, h, fill, **kw):
    """skew_box in the card look, block in the nerv look."""
    (block if look() == "nerv" else skew_box)(cr, x, y, w, h, fill, **kw)


def hazard(cr, x, y, w, h, a, b=None, period=28.0):
    """Diagonal warning stripes (135 degrees) inside the box: `a` stripes over a `b` ground (None = untouched)."""
    cr.save()
    cr.rectangle(x, y, w, h)
    cr.clip()
    if b is not None:
        rgba(cr, b)
        cr.paint()
    rgba(cr, a)
    half = period / 2
    k = x - h
    while k < x + w + h:
        cr.move_to(k, y + h)
        cr.line_to(k + half, y + h)
        cr.line_to(k + half + h, y)
        cr.line_to(k + h, y)
        cr.close_path()
        k += period
    cr.fill()
    cr.restore()


def _hex(cr, cx, cy, r):
    for i in range(6):
        a = math.radians(60 * i - 30)
        (cr.move_to if i == 0 else cr.line_to)(cx + r * math.cos(a), cy + r * math.sin(a))
    cr.close_path()


def hex_field(cr, w, h, cx, cy, r, line=None, fill=None, accent=None, rings=True):
    """An A.T. field: a honeycomb over w x h, a few cells filled, the cell under (cx, cy) outlined in the accent,
    two faint rings around it. Deterministic, so the stage and the previews agree."""
    line = CLARET if line is None else line
    fill = CLARET if fill is None else fill
    accent = GOLD if accent is None else accent
    dx, dy = r * math.sqrt(3), r * 1.5
    cells = []
    row = 0
    y = -r
    while y < h + r:
        x0 = -dx if row % 2 else -dx / 2
        x = x0
        while x < w + dx:
            cells.append((x, y))
            x += dx
        y += dy
        row += 1
    rgba(cr, fill, 0.35)
    for i, (x, y) in enumerate(cells):
        if (i * 7919) % 11 == 0:
            _hex(cr, x, y, r - 1)
            cr.fill()
    rgba(cr, line, 0.75)
    cr.set_line_width(max(1.0, r / 45))
    for x, y in cells:
        _hex(cr, x, y, r - 1)
    cr.stroke()
    near = min(cells, key=lambda c: (c[0] - cx) ** 2 + (c[1] - cy) ** 2)
    rgba(cr, accent, 0.9)
    cr.set_line_width(max(2.0, r / 22))
    _hex(cr, near[0], near[1], r - 1)
    cr.stroke()
    if rings:
        cr.set_line_width(1.0)
        for k, a in ((2.2, 0.5), (3.1, 0.25)):
            rgba(cr, accent, a)
            cr.arc(cx, cy, r * k, 0, 2 * math.pi)
            cr.stroke()


def speed_lines(cr, cx, cy, radius, a=None, b=None, fill_b=True):
    """The impact-frame rays: per 10 degrees a 1.3 deg ray, gap, a 0.4 deg ray, gap (bone on ink by default)."""
    a = BONE if a is None else a
    b = INK if b is None and fill_b else b
    if fill_b and b is not None:
        rgba(cr, b)
        cr.arc(cx, cy, radius, 0, 2 * math.pi)
        cr.fill()
    rgba(cr, a)
    for k in range(36):
        base = math.radians(k * 10)
        for start, width in ((0.0, 1.3), (5.0, 0.4)):
            t0, t1 = base + math.radians(start), base + math.radians(start + width)
            cr.move_to(cx, cy)
            cr.line_to(cx + radius * math.cos(t0), cy + radius * math.sin(t0))
            cr.line_to(cx + radius * math.cos(t1), cy + radius * math.sin(t1))
            cr.close_path()
    cr.fill()


def tint(cr, w, h, color, alpha, op=cairo.OPERATOR_MULTIPLY):
    cr.save()
    cr.set_operator(op)
    rgba(cr, color, alpha)
    cr.rectangle(0, 0, w, h)
    cr.fill()
    cr.restore()


def mask_image(cr, surf, x, y, w, h, color, alpha=1.0):
    """Paint `color` through the alpha of `surf` scaled into the box (x, y, w, h)."""
    cr.save()
    cr.translate(x, y)
    cr.scale(w / surf.get_width(), h / surf.get_height())
    rgba(cr, color, color[3] * alpha)
    pat = cairo.SurfacePattern(surf)
    pat.set_filter(cairo.FILTER_GOOD)
    cr.mask(pat)
    cr.restore()


def paint_image(cr, surf, x, y, w, h, alpha=1.0):
    cr.save()
    cr.translate(x, y)
    cr.scale(w / surf.get_width(), h / surf.get_height())
    cr.set_source_surface(surf, 0, 0)
    cr.get_source().set_filter(cairo.FILTER_GOOD)
    cr.paint_with_alpha(alpha)
    cr.restore()


def cover(cr, surf, w, h):
    """Paint `surf` scaled to cover a w x h area, centred."""
    sw, sh = surf.get_width(), surf.get_height()
    k = max(w / sw, h / sh)
    paint_image(cr, surf, (w - sw * k) / 2, (h - sh * k) / 2, sw * k, sh * k)


def silhouette(cr, surf, x, y, w, h, echo=18.0, color=None, echo_color=None):
    color = INK if color is None else color
    echo_color = ECHO if echo_color is None else echo_color
    """Black figure with the red echo trail to the right (the X2 treatment: claret at +echo,
    claret 45% at +2*echo, like two chained CSS drop-shadows)."""
    if echo:
        mask_image(cr, surf, x + 2 * echo, y, w, h, echo_color, 0.45)
        mask_image(cr, surf, x + echo, y, w, h, echo_color, 1.0)
    mask_image(cr, surf, x, y, w, h, color)


def silhouette_mask(cr, mask, echo=18.0, color=None, echo_color=None):
    color = INK if color is None else color
    echo_color = ECHO if echo_color is None else echo_color
    """Same as silhouette() for a pre-composited full-size A8 mask surface."""
    if echo:
        rgba(cr, echo_color, 0.45)
        cr.mask_surface(mask, 2 * echo, 0)
        rgba(cr, echo_color, 1.0)
        cr.mask_surface(mask, echo, 0)
    rgba(cr, color)
    cr.mask_surface(mask, 0, 0)


def ember(cr, x, y, r, alpha=1.0):
    e, hi = EMBER, hexc(THEME["colors"]["ember_hi"])
    g = cairo.RadialGradient(x, y, 0, x, y, r * 3.2)
    g.add_color_stop_rgba(0, e[0], e[1], e[2], 0.9 * alpha)
    g.add_color_stop_rgba(0.3, e[0], e[1], e[2], 0.35 * alpha)
    g.add_color_stop_rgba(1, e[0], e[1], e[2], 0)
    cr.set_source(g)
    cr.arc(x, y, r * 3.2, 0, 2 * math.pi)
    cr.fill()
    cr.set_source_rgba(hi[0], hi[1], hi[2], alpha)
    cr.arc(x, y, r, 0, 2 * math.pi)
    cr.fill()


def sun(cr, cx, cy, r):
    g = cairo.RadialGradient(cx, cy, 0, cx, cy, r)
    c = THEME["colors"]
    roles = THEME.get("sun", ["bone_hi", "gold_hi", "gold_glow", "coral"])
    for stop, role in zip((0, 0.34, 0.58, 0.68), roles):
        k = hexc(c[role])
        g.add_color_stop_rgba(stop, k[0], k[1], k[2], 1)
    k = hexc(c[roles[-1]])
    g.add_color_stop_rgba(0.71, k[0], k[1], k[2], 0)
    g.add_color_stop_rgba(1, k[0], k[1], k[2], 0)
    cr.set_source(g)
    cr.arc(cx, cy, r, 0, 2 * math.pi)
    cr.fill()


# ---------------------------------------------------------------- text
def layout(cr, text, family, size, weight=Pango.Weight.NORMAL, italic=False, spacing=0):
    lay = PangoCairo.create_layout(cr)
    fd = Pango.FontDescription()
    fd.set_family(family)
    fd.set_absolute_size(size * Pango.SCALE)
    fd.set_weight(Pango.Weight(int(weight)) if not isinstance(weight, Pango.Weight) else weight)
    if italic:
        fd.set_style(Pango.Style.ITALIC)
    lay.set_font_description(fd)
    if spacing:
        attrs = Pango.AttrList()
        attrs.insert(Pango.attr_letter_spacing_new(int(spacing * Pango.SCALE)))
        lay.set_attributes(attrs)
    lay.set_text(text, -1)
    return lay


def display(cr, text, size, italic=None, spacing=0):
    """A layout in the theme's display face (the tags, labels and shouts); italic follows the theme unless given."""
    return layout(cr, text, F_DISPLAY, size, weight=DISPLAY_WEIGHT, italic=DISPLAY_ITALIC if italic is None else italic,
                  spacing=spacing)


def text_size(lay):
    ink, logical = lay.get_pixel_extents()
    return logical.width, logical.height


def draw_text(cr, lay, x, y, color):
    rgba(cr, color)
    cr.move_to(x, y)
    PangoCairo.show_layout(cr, lay)


def ellipsize(lay, max_w):
    lay.set_width(int(max_w * Pango.SCALE))
    lay.set_ellipsize(Pango.EllipsizeMode.END)
    return lay
