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
def block(cr, x, y, w, h, fill, shadow=None, shadow_off=(0, 0), border=None, border_w=0, under=None, under_h=0):
    """A title-card block: a plain rectangle with an optional hard shadow, border and underline."""
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


def tint(lay, start, end, color):
    """Colour the bytes `start`..`end` of `lay`'s text in `color` (a role tuple), on top of
    whatever `draw_text` paints the rest in -- two colours on one line, one set of metrics."""
    attr = Pango.attr_foreground_new(*(round(c * 65535) for c in color[:3]))
    attr.start_index, attr.end_index = start, end
    attrs = lay.get_attributes() or Pango.AttrList()
    attrs.insert(attr)
    lay.set_attributes(attrs)
    return lay


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
