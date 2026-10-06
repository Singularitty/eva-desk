"""The MFD drawing language: bezelled dark screens, segment bars, lamps, key caps and list rows,
shared by every panel (sound, music, OSD, notifications...). Pure cairo -- every function takes a
cairo context first and nothing here touches a GTK window or widget.

House rule for the whole desk: no flashing, no colour changes on a beat. A lit lamp is steady.
"""
import math

import cairo

from .. import draw as d

BEZEL_W = 6
OUTLINE_W = 2
PAD = 10


def screen(cr, x, y, w, h, tag, hot=""):
    """A bezelled MFD screen: `ink3` bezel with a 2 px `ink4` outline, `ink_deep` face, scanlines,
    the `tag` readout (with `hot` appended in gold). Returns the content rect inside the tag line."""
    d.block(cr, x, y, w, h, d.col("ink3"), border=d.col("ink4"), border_w=OUTLINE_W)
    fx, fy = x + BEZEL_W, y + BEZEL_W
    fw, fh = w - 2 * BEZEL_W, h - 2 * BEZEL_W
    cr.rectangle(fx, fy, fw, fh)
    d.rgba(cr, d.col("ink_deep"))
    cr.fill()
    _scanlines(cr, fx, fy, fw, fh)

    tag_lay = d.layout(cr, tag, d.F_META, 11, spacing=3)
    tag_w, tag_h = d.text_size(tag_lay)
    tx, ty = fx + PAD, fy + PAD
    d.draw_text(cr, tag_lay, tx, ty, d.col("dim"))
    if hot:
        hot_lay = d.layout(cr, hot, d.F_META, 11, spacing=3)
        d.draw_text(cr, hot_lay, tx + tag_w, ty, d.GOLD)

    cx, cy = fx + PAD, fy + PAD + tag_h
    cw, ch = fw - 2 * PAD, fh - 2 * PAD - tag_h
    return cx, cy, cw, ch


_scan_cache = {}


def _scanline_pattern():
    """A cached 1x4 px tile (bone on the first row, transparent below) repeated over the face."""
    bone = d.col("bone")
    pat = _scan_cache.get(bone)
    if pat is None:
        tile = cairo.ImageSurface(cairo.FORMAT_ARGB32, 1, 4)
        tc = cairo.Context(tile)
        d.rgba(tc, bone)
        tc.rectangle(0, 0, 1, 1)
        tc.fill()
        pat = cairo.SurfacePattern(tile)
        pat.set_extend(cairo.EXTEND_REPEAT)
        _scan_cache.clear()
        _scan_cache[bone] = pat
    return pat


def _scanlines(cr, fx, fy, fw, fh):
    cr.save()
    cr.rectangle(fx, fy, fw, fh)
    cr.clip()
    cr.set_source(_scanline_pattern())
    cr.paint_with_alpha(0.045)
    cr.restore()


def segments(w, pitch=0.032, duty=0.75):
    """The (x_offset, width) of each LED segment across a bar of width `w`."""
    step = pitch * w
    seg_w = duty * step
    n = int(w / step) if step else 0
    return [(i * step, seg_w) for i in range(n)]


def segbar(cr, x, y, w, h, value, colour, peak=None):
    """A segmented LED bar: `value` (0..1) of `segments(w)` lit in `colour`, the rest in `ink3`;
    `peak` (0..1), when given, draws one segment in `bone`."""
    segs = segments(w)
    n = len(segs)
    lit = max(0, min(n, round(value * n)))
    peak_idx = max(0, min(n - 1, round(peak * n))) if peak is not None and n else None
    for i, (ox, sw) in enumerate(segs):
        if i == peak_idx:
            d.rgba(cr, d.BONE)
        elif i < lit:
            d.rgba(cr, colour)
        else:
            d.rgba(cr, d.col("ink3"))
        cr.rectangle(x + ox, y, sw, h)
        cr.fill()


def lamp(cr, x, y, size, on, hot=False):
    """A square lamp: `ink3` off, `gold` on with a 6 px glow, `led` hot -- steady, never blinking."""
    if hot:
        colour = glow = d.LED
    elif on:
        colour = glow = d.GOLD
    else:
        colour, glow = d.col("ink3"), None
    if glow:
        for ring, a in ((6, 0.18), (3, 0.32)):
            d.rgba(cr, glow, a)
            cr.rectangle(x - ring, y - ring, size + 2 * ring, size + 2 * ring)
            cr.fill()
    d.rgba(cr, colour)
    cr.rectangle(x, y, size, size)
    cr.fill()


def keyrow(cr, x, y, keys, active=-1, key_w=36, key_h=26, gap=6):
    """A row of key caps: `ink3` with an `ink4` outline, the active one `bone` with `ink` text.
    Returns hit rectangles (x0, y0, x1, y1, index)."""
    hits = []
    kx = x
    for i, label in enumerate(keys):
        selected = i == active
        fill = d.BONE if selected else d.col("ink3")
        fg = d.INK if selected else d.col("bone")
        d.block(cr, kx, y, key_w, key_h, fill, border=d.col("ink4"), border_w=1)
        lay = d.layout(cr, label, d.F_META, 12)
        tw, th = d.text_size(lay)
        d.draw_text(cr, lay, kx + (key_w - tw) / 2, y + (key_h - th) / 2, fg)
        hits.append((kx, y, kx + key_w, y + key_h, i))
        kx += key_w + gap
    return hits


def rows(cr, x, y, w, items, selected, row_h=34):
    """A list of MFD rows: label + sub, a `segbar` from 38% of `w` to `w - 48`, the value as `NN`
    in gold at the right. The selected row's label is inverted (`bone` block, `ink` text).
    Returns hit rectangles (x0, y0, x1, y1, index) and (x0, y0, x1, y1, ("bar", index)) for the bars."""
    hits = []
    pad = 12
    bar_x0, bar_x1 = x + 0.38 * w, x + w - 48
    bar_w = max(0.0, bar_x1 - bar_x0)
    for i, it in enumerate(items):
        ry = y + i * row_h
        hits.append((x, ry, x + w, ry + row_h, i))

        lay = d.layout(cr, it.get("label", ""), d.F_META, 13)
        d.ellipsize(lay, w * 0.36)
        lw, lh = d.text_size(lay)
        label_y = ry + 5
        if i == selected:
            bx, by = x + pad - 6, label_y - 4
            bw, bh = lw + 12, lh + 8
            d.block(cr, bx, by, bw, bh, d.BONE)
            d.draw_text(cr, lay, x + pad, label_y, d.INK)
        else:
            d.draw_text(cr, lay, x + pad, label_y, d.col("dim") if it.get("muted") else d.BONE)

        sub = d.layout(cr, it.get("sub", ""), d.F_META, 10, spacing=2)
        d.draw_text(cr, sub, x + pad, label_y + lh + 2, d.col("dim"))

        value = it.get("value")
        if value is not None:
            colour = it.get("colour") or d.GOLD
            bar_h = 8
            bar_y = ry + (row_h - bar_h) / 2
            segbar(cr, bar_x0, bar_y, bar_w, bar_h, value, colour, peak=it.get("peak"))
            hits.append((bar_x0, bar_y, bar_x0 + bar_w, bar_y + bar_h, ("bar", i)))

            vlay = d.layout(cr, f"{round(value * 100):02d}", d.F_META, 13)
            vw, vh = d.text_size(vlay)
            d.draw_text(cr, vlay, x + w - 8 - vw, ry + (row_h - vh) / 2, d.GOLD)
    return hits


def snap_scale(t):
    """The CRT open curve: 0.02 until t=0.4, then four discrete steps up to 1.0 at t>=1."""
    if t < 0.4:
        return 0.02
    if t >= 1.0:
        return 1.0
    k = math.ceil(round((t - 0.4) / 0.6 * 4, 9))
    return 0.02 + 0.98 * k / 4


def stagger(i, t, total_ms=380, step_ms=120):
    """The i-th section's own 0..1 progress given the panel's overall `t`, staggered by `step_ms`."""
    v = (t * total_ms - i * step_ms) / total_ms
    return max(0.0, min(1.0, v))
