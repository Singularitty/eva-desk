"""Motion: timeline, kit, renderer, player and the launch sequences. No compositor, no windows."""
import contextlib
import io
import math
import os
import shutil
import subprocess
import sys
import tempfile
import time
import types
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ.pop("WAYLAND_DISPLAY", None)

from eva_desk import config  # noqa: E402

config.load("/nonexistent")                     # the default theme, whatever this machine's eva.toml says
CTX = {"app": "FIREFOX", "workspace": 2, "clock": "22:44"}
BONE, GOLD, INK = (0xf7, 0xe6, 0xeb), (0x3f, 0xff, 0x7d), (0x12, 0x06, 0x0a)     # as cairo stores them: blue, green, red
PINK = (0xb4, 0x69, 0xff)                       # what GTK paints offline in place of a node it cannot draw


def px(surf, x, y):
    """(blue, green, red, alpha) of one pixel of an ARGB32 surface."""
    i = int(y) * surf.get_stride() + int(x) * 4
    return tuple(surf.get_data()[i:i + 4])


def alpha(surf, x, y):
    return px(surf, x, y)[3]


def same(a, b):
    """Whether two frames are the same picture (compared here, so a failure does not print megabytes)."""
    return bytes(a.get_data()) == bytes(b.get_data())


def pink(surf, step=17):
    """How many sampled pixels are GTK's cannot-draw-this pink."""
    w, h = surf.get_width(), surf.get_height()
    return sum(px(surf, x, y)[:3] == PINK for y in range(1, h, step) for x in range(1, w, step))


def grid(surf, cols=12, rows=6):
    """The alpha at the middle of every cell of a cols x rows grid."""
    w, h = surf.get_width(), surf.get_height()
    return [alpha(surf, (c + 0.5) * w / cols, (r + 0.5) * h / rows) for r in range(rows) for c in range(cols)]


def near(p, colour, tol=3):
    """Whether a pixel is that colour, give or take what scaling a picture does to it."""
    return p[3] >= 255 - tol and all(abs(a - b) <= tol for a, b in zip(p[:3], colour))


def box(surf):
    """(x0, y0, x1, y1) around everything a frame paints at more than half strength; None for an empty frame."""
    w, h = surf.get_width(), surf.get_height()
    a = bytes(surf.get_data())[3::4]
    xs = [x for x in range(w) if max(a[x::w]) > 127]
    ys = [y for y in range(h) if max(a[y * w:(y + 1) * w]) > 127]
    return (xs[0], ys[0], xs[-1], ys[-1]) if xs else None


def nodes(node, scale=1.0):
    """Every node of a frame's tree, each with the scale it is drawn under."""
    from gi.repository import Gsk
    T, kind = Gsk.RenderNodeType, node.get_node_type()
    yield node, scale
    if kind == T.TRANSFORM_NODE:
        m = node.get_transform().to_matrix()
        scale *= math.hypot(m.get_value(0, 0), m.get_value(0, 1))
    if kind == T.CONTAINER_NODE:
        kids = [node.get_child(i) for i in range(node.get_n_children())]
    elif kind == T.MASK_NODE:
        kids = [node.get_source(), node.get_mask()]
    elif kind == T.BLEND_NODE:
        kids = [node.get_bottom_child(), node.get_top_child()]
    else:
        kids = [node.get_child()] if hasattr(node, "get_child") else []
    for kid in kids:
        yield from nodes(kid, scale)


def glyph_sizes(node):
    """The size on screen, in points, of every run of glyphs in a frame: its font's size times the scale it is under."""
    from gi.repository import Gsk, Pango
    return {round(n.get_font().describe().get_size() / Pango.SCALE * s, 2) for n, s in nodes(node)
            if n.get_node_type() == Gsk.RenderNodeType.TEXT_NODE}


def texture_widths(node):
    from gi.repository import Gsk
    return [n.get_texture().get_width() for n, _ in nodes(node) if n.get_node_type() == Gsk.RenderNodeType.TEXTURE_NODE]


class Timeline(unittest.TestCase):
    def setUp(self):
        from eva_desk.motion import timeline
        self.T = timeline

    def test_seg(self):
        T = self.T
        self.assertEqual(T.seg(0.5, 1, 2), 0.0)
        self.assertEqual(T.seg(3, 1, 2), 1.0)
        self.assertAlmostEqual(T.seg(1.5, 1, 2), 0.5)

    def test_easings_run_from_0_to_1_without_falling(self):
        T = self.T
        for f in (T.cubic_out, T.cubic_in, T.smooth, T.quint_out, T.expo_in):
            self.assertAlmostEqual(f(0.0), 0.0, places=6)
            self.assertAlmostEqual(f(1.0), 1.0, places=6)
            ys = [f(i / 100) for i in range(101)]
            self.assertEqual(ys, sorted(ys), f.__name__)

    def test_exact_values(self):
        T = self.T
        self.assertAlmostEqual(T.cubic_out(0.5), 0.875)
        self.assertAlmostEqual(T.cubic_in(0.5), 0.125)
        self.assertAlmostEqual(T.smooth(0.25), 0.15625)
        self.assertAlmostEqual(T.quint_out(0.5), 0.96875)
        self.assertAlmostEqual(T.expo_in(0.5), 2 ** -5)
        self.assertAlmostEqual(T.back_out(1.0), 1.0)
        self.assertGreater(max(T.back_out(i / 100) for i in range(101)), 1.0)      # it overshoots
        self.assertAlmostEqual(T.lerp(10, 20, 0.25), 12.5)
        self.assertEqual(T.clamp(-1), 0.0)
        self.assertEqual(T.clamp(7, 0, 5), 5)

    def test_stepped_twos_and_crt(self):
        T = self.T
        self.assertEqual([T.stepped(u, 3) for u in (0, 0.01, 0.34, 0.67, 1)], [0, 1 / 3, 2 / 3, 1, 1])
        self.assertAlmostEqual(T.twos(0.20), 2 / 12)
        self.assertAlmostEqual(T.twos(0.2501), 3 / 12)
        self.assertEqual(T.crt(0), 0)
        self.assertAlmostEqual(T.crt(0.2), 0.02)
        self.assertAlmostEqual(T.crt(0.41), 0.02 + 0.98 * 0.25)
        self.assertEqual(T.crt(1), 1)

    def test_noise_is_repeatable(self):
        T = self.T
        vals = [T.noise(i, 7) for i in range(200)]
        self.assertTrue(all(0 <= v < 1 for v in vals))
        self.assertEqual(vals, [T.noise(i, 7) for i in range(200)])
        self.assertGreater(len({round(v, 3) for v in vals}), 150)


class KitTest(unittest.TestCase):
    def frame(self, fn, w=1720, h=720):
        from eva_desk.motion import Piece, render

        class P(Piece):
            length = 1.0

            def paint(self, kit, t, ctx):
                fn(kit)
        return render.frame(P(), 0.0, w, h, {})

    def test_design_frame(self):
        from eva_desk.motion.kit import design
        self.assertEqual(design(3440, 1440), (2.0, 1720.0, 720.0))
        self.assertEqual(design(1920, 1080), (1.5, 1280.0, 720.0))
        s, W, H = design(1080, 1920)
        self.assertAlmostEqual(s, 0.84375)
        self.assertAlmostEqual(W, 1280.0)
        self.assertAlmostEqual(H, 1920 / 0.84375)

    def test_rect_lands_where_asked_at_any_monitor_size(self):
        from eva_desk import draw as d
        f = self.frame(lambda k: k.rect(100, 100, 200, 100, d.BONE))
        self.assertEqual(px(f, 150, 150), BONE + (255,))
        self.assertEqual(alpha(f, 90, 150), 0)
        f = self.frame(lambda k: k.rect(100, 100, 200, 100, d.BONE), 3440, 1440)
        self.assertEqual(alpha(f, 300, 300), 255)             # design (150, 150) at twice the size
        self.assertEqual(alpha(f, 150, 150), 0)

    def test_clips(self):
        from eva_desk import draw as d

        def inside(k):
            with k.clip(0, 0, 120, 720):
                k.rect(100, 100, 200, 100, d.BONE)
        f = self.frame(inside)
        self.assertEqual((alpha(f, 110, 150), alpha(f, 150, 150)), (255, 0))

        def hole(k):
            with k.clip_out(760, 260, 200, 200):
                k.rect(0, 0, k.W, k.H, d.INK)
        f = self.frame(hole)
        self.assertEqual((alpha(f, 860, 360), alpha(f, 20, 20)), (0, 255))

        def slanted_gap(k):                                                   # everything but a leaning band
            with k.clip_out_para((400, 0), (600, 0), (300, 720)):
                k.rect(0, 0, k.W, k.H, d.INK)
        f = self.frame(slanted_gap)
        self.assertEqual((alpha(f, 500, 10), alpha(f, 350, 700)), (0, 0))          # inside the band, top and bottom
        self.assertEqual((alpha(f, 700, 360), alpha(f, 100, 360)), (255, 255))

    def test_transform_and_opacity(self):
        from eva_desk import draw as d

        def fn(k):
            with k.transform(dx=860, dy=360, scale=0.5):
                with k.opacity(0.5):
                    k.rect(-100, -100, 200, 200, d.BONE)
        f = self.frame(fn)
        self.assertTrue(120 <= alpha(f, 860, 360) <= 135)
        self.assertEqual(alpha(f, 860 + 60, 360), 0)          # half size: it ends 50 px out

    def test_text(self):
        from eva_desk import draw as d
        got = {}

        def fn(k):
            got["w"] = k.measure("FIREFOX", 92, face="display")
            got["drawn"] = k.text("FIREFOX", 400, 300, 92, d.BONE, face="display")
            k.text("M", 1000, 300, 92, d.BONE, face="display", align="right")
        f = self.frame(fn)
        self.assertGreater(got["w"], 250)
        self.assertEqual(got["w"], got["drawn"])
        ink = d.plain_layout("FIREFOX", d.F_DISPLAY, 92, weight=d.DISPLAY_WEIGHT).get_pixel_extents()[0]      # in whatever font this machine sets it
        lit = [x for x in range(380, 408 + ink.x + ink.width) if any(alpha(f, x, y) for y in range(220, 310))]
        self.assertTrue(lit and abs(lit[0] - 400 - ink.x) <= 2 and abs(lit[-1] - 400 - ink.x - ink.width) <= 2,
                        (lit[:1], lit[-1:], ink.x, ink.width))                                         # starts at x
        self.assertFalse(any(alpha(f, x, y) for x in range(1004, 1040) for y in range(220, 310, 3)))     # right-aligned: ends at x
        self.assertFalse(any(alpha(f, x, 330) for x in range(380, 900)))                                # y was the baseline

    def test_a_stamp_is_the_same_type_as_text_but_a_picture(self):
        from eva_desk import draw as d
        from eva_desk.motion import Piece, render
        got = {}
        text = self.frame(lambda k: got.update(text=k.text("発進", 300, 400, 200, d.BONE, face="display")))
        stamp = self.frame(lambda k: got.update(stamp=k.stamp("発進", 300, 400, 200, d.BONE, face="display")))
        self.assertEqual(got["text"], got["stamp"])                           # the same width
        self.assertTrue(all(abs(a - b) <= 1 for a, b in zip(box(text), box(stamp))), (box(text), box(stamp)))     # in the same place
        x0, y0, x1, y1 = box(text)

        def half(k):
            with k.transform(dx=900, dy=400, scale=0.5):
                k.stamp("発進", 0, 0, 200, d.BONE, face="display", align="center")
        hx0, hy0, hx1, hy1 = box(self.frame(half))
        self.assertLess(abs((hx1 - hx0) - (x1 - x0) / 2), 2.5)                # it follows a scale
        self.assertLess(abs((hx0 + hx1) / 2 - 900 - ((x0 + x1) / 2 - 300 - got["text"] / 2) / 2), 2)      # and its alignment
        faint = self.frame(lambda k: k.stamp("発進", 300, 400, 200, d.BONE, face="display", alpha=0.5))
        self.assertTrue(120 <= max(bytes(faint.get_data())[3::4]) <= 135)

        class P(Piece):
            length = 1.0

            def __init__(self, how):
                self.how = how

            def paint(self, kit, t, ctx):
                getattr(kit, self.how)("発進", 300, 400, 200, d.BONE, face="display")
        self.assertEqual(glyph_sizes(render.build(P("text"), 0, 1720, 720, {})), {150.0})       # 200 px is 150 pt
        self.assertEqual(glyph_sizes(render.build(P("stamp"), 0, 1720, 720, {})), set())        # no glyphs: nothing to set again

    def test_a_stamp_is_as_fine_as_it_is_shown_and_never_wider_than_2048(self):
        from eva_desk import draw as d, gtkutil  # noqa: F401
        from gi.repository import Gtk
        from eva_desk.motion.kit import Kit

        def width(density, most, store):
            snap = Gtk.Snapshot()
            kit = Kit(snap, 1720, 720, density, store)
            kit.stamp("発進", 0, 500, 430, d.BONE, face="display", most=most)
            kit.close()
            return texture_widths(snap.to_node())[0]
        store = {}
        one, two = width(1, 1, store), width(2, 1, store)
        self.assertGreater(one, 250)
        self.assertLess(abs(two - 2 * one), 3)                                # a monitor with two px to the point: twice as fine
        self.assertEqual(width(2, 4, store), 2048)
        self.assertEqual(len(store), 3)
        self.assertEqual((width(1, 1, store), len(store)), (one, 3))          # kept, not made again

    def test_letters(self):
        got = {}

        def fn(k):
            for s in ("FIREFOX", "éa", "火狐 🦊", "مرحبا", "אב", "AB אב", ""):
                got[s] = k.letters(s, 170, face="display")
        self.frame(fn)
        self.assertEqual(got["FIREFOX"], list("FIREFOX"))
        self.assertEqual(got["éa"], ["é", "a"])                   # a mark stays on its letter
        self.assertEqual(got["火狐 🦊"], ["火", "狐", " ", "🦊"])
        for joined in ("مرحبا", "אב", "AB אב"):                               # cut into letters these would read wrong
            self.assertIsNone(got[joined], joined)
        self.assertEqual(got[""], [])

    def test_a_colour_draws_the_same_whatever_was_drawn_before_it(self):
        a, b = (0.31, 0.22, 0.13, 1.0), (0.32, 0.22, 0.13, 1.0)               # two colours nothing else here uses
        after = self.frame(lambda k: (k.rect(0, 0, 50, 50, a, 0.4996), k.rect(100, 0, 50, 50, a, 0.5004)))
        alone = self.frame(lambda k: k.rect(100, 0, 50, 50, b, 0.5004))
        self.assertEqual(alpha(after, 120, 20), alpha(alone, 120, 20))

    def test_hazard_segbar_lines_poly_radial(self):
        from eva_desk import draw as d
        a = self.frame(lambda k: k.hazard(0, 0, 400, 40, d.CLARET, d.INK, period=30))
        b = self.frame(lambda k: k.hazard(0, 0, 400, 40, d.CLARET, d.INK, period=30, offset=15))
        self.assertEqual((alpha(a, 200, 20), alpha(a, 200, 60)), (255, 0))            # filled, and inside its box
        self.assertFalse(same(a, b))                   # the offset moves the stripes
        f = self.frame(lambda k: k.segbar(100, 100, 260, 10, 0.5, d.GOLD, 26))
        self.assertEqual(px(f, 102, 105)[:3], GOLD)                                     # the first segment is lit
        self.assertNotEqual(px(f, 355, 105)[:3], GOLD)                                  # the last is not
        self.assertEqual(alpha(f, 355, 105), 255)                                       # but it is drawn
        f = self.frame(lambda k: (k.lines([(0, 100, 400, 100), (100, 400, 200, 500)], d.BONE, 6), k.para((500, 0), (600, 0), (450, 100), d.BONE),
                                  k.stroke_rect(700, 100, 100, 100, d.BONE, 4), k.radial(1200, 360, 100, d.GOLD, 0.5)))
        self.assertEqual((alpha(f, 200, 100), alpha(f, 200, 110)), (255, 0))
        self.assertEqual((alpha(f, 150, 450), alpha(f, 190, 420)), (255, 0))            # the diagonal one, and beside it
        self.assertEqual((alpha(f, 525, 10), alpha(f, 610, 50), alpha(f, 470, 10)), (255, 0, 0))    # the parallelogram leans left
        self.assertEqual(px(f, 525, 10)[:3], BONE)                                      # and it is drawn, not replaced by GTK's pink
        self.assertEqual(pink(f), 0)
        self.assertEqual((alpha(f, 700, 150), alpha(f, 750, 150)), (255, 0))
        self.assertGreater(alpha(f, 1200, 360), 100)
        self.assertEqual(alpha(f, 1320, 360), 0)

    def test_a_sequence_paints_nothing_outside_its_length(self):
        from eva_desk import draw as d
        from eva_desk.motion import Piece, render

        class P(Piece):
            length = 1.0

            def paint(self, kit, t, ctx):
                kit.rect(0, 0, kit.W, kit.H, d.INK)
        self.assertEqual(set(grid(render.frame(P(), 0.5, 320, 180, {}))), {255})
        for t in (-0.1, 1.0, 3.0):
            self.assertEqual(set(grid(render.frame(P(), t, 320, 180, {}))), {0}, t)

    def test_same_frame_twice(self):
        from eva_desk import draw as d
        fn = lambda k: (k.rect(0, 0, 300, 300, d.CLARET), k.text("発進", 100, 200, 120, d.BONE, face="display"))
        self.assertTrue(same(self.frame(fn), self.frame(fn)))

    def test_band_between_two_rectangles(self):
        from eva_desk import draw as d
        f = self.frame(lambda k: k.band((100, 100, 400, 300), (200, 200, 100, 100), d.BONE))
        self.assertEqual((alpha(f, 150, 150), alpha(f, 250, 250), alpha(f, 50, 50)), (255, 0, 0))

    def test_whole_pixel_bands_inside_a_hole_do_not_abort_the_renderer(self):
        # the shaft's first frame: bay bands on whole pixels inside the exit's hole. Drawn as paths, cairo aborted on it
        from eva_desk import draw as d

        def fn(k):
            with k.transform(dx=860, dy=360):
                with k.clip_out(-14.33, -6, 28.67, 12):
                    k.band((-215, -90, 430, 180), (-172, -72, 344, 144), d.col("ink4"), 0.5)
                    k.band((-860, -360, 1720, 720), (-430, -180, 860, 360), d.col("ink4"), 0.5)
        f = self.frame(fn)
        self.assertEqual(alpha(f, 860, 360), 0)
        self.assertGreater(alpha(f, 860 - 200, 360), 100)

    def test_tile_repeats_what_is_painted_in_one_cell(self):
        from eva_desk import draw as d

        def dots(k):
            with k.tile(100, 100, 80, 2, 8, 2):                   # ten dots, 8 px apart
                k.rect(100, 100, 2, 2, d.BONE)
        f = self.frame(dots)
        self.assertEqual([alpha(f, x, 101) > 0 for x in (101, 105, 109, 173, 177, 181)], [True, False, True, True, False, False])
        f = self.frame(lambda k: k.scanlines(0, 0, 400, 300, 0.5))
        self.assertEqual([alpha(f, 50, y) > 0 for y in range(6)], [True, False, False, True, False, False])
        self.assertEqual((alpha(f, 399, 0) > 0, alpha(f, 401, 0), alpha(f, 50, 300)), (True, 0, 0))
        self.assertEqual(pink(f), 0)

    def test_hexagon_is_a_picture_of_an_outline(self):
        from eva_desk import draw as d
        from eva_desk.motion import Piece, render

        class P(Piece):
            length = 1.0

            def __init__(self, fill):
                self.fill = fill

            def paint(self, kit, t, ctx):
                kit.hexagon(400, 300, 58, d.CLARET, width=2, fill=self.fill)
                kit.hexagon(600, 300, 58, d.CLARET, alpha=0.5, width=2, fill=self.fill)

        def lit(f, x, y):                                          # the strongest of the pixels around a point
            return max(alpha(f, x + dx, y + dy) for dx in (-1, 0, 1) for dy in (-1, 0, 1))
        f = render.frame(P(0.0), 0, 1720, 720, {})
        self.assertGreater(lit(f, 400, 242), 150)                  # a point at the top: 58 above the centre
        self.assertGreater(lit(f, 450, 300), 150)                  # a flat side: 58 * cos 30 = 50.2 out
        self.assertEqual((alpha(f, 400, 300), alpha(f, 470, 300)), (0, 0))     # hollow, and nothing outside
        self.assertTrue(60 < lit(f, 650, 300) < 140)               # the second one at half strength
        g = render.frame(P(0.4), 0, 1720, 720, {})
        self.assertTrue(80 < alpha(g, 400, 300) < 125)             # filled at 0.4 of its line
        widths = texture_widths(render.build(P(0.0), 0, 1720, 720, {}))
        self.assertEqual((len(widths), len(set(widths))), (2, 1))  # pictures of one picture: no path for GTK to rasterise every frame

    def test_hex_cells_cover_a_box(self):
        from eva_desk.motion.kit import hex_cells
        cells = hex_cells(0, 0, 1000, 500, 58)
        dx, dy, rows = math.sqrt(3) * 58, 1.5 * 58, {}
        for cx, cy, col, row in cells:
            rows.setdefault(row, []).append(cx)
            self.assertAlmostEqual(cy, row * dy)
        self.assertAlmostEqual(rows[0][1] - rows[0][0], dx)                    # neighbours are one cell apart
        self.assertAlmostEqual((rows[1][0] - rows[0][0]) % dx, dx / 2)         # every other row sits half a cell over
        self.assertTrue(min(c[0] for c in cells) <= 0 and max(c[0] for c in cells) >= 1000)     # past every edge of the box
        self.assertTrue(min(c[1] for c in cells) <= 0 and max(c[1] for c in cells) >= 500)
        self.assertEqual(len(cells), len(set(cells)))
        self.assertAlmostEqual(hex_cells(0, 0, 10, 10, 58, ox=7, oy=5)[0][1] % dy, 5)           # the lattice can be shifted

    def test_lamp_brackets_and_block(self):
        from eva_desk import draw as d
        f = self.frame(lambda k: (k.lamp(100, 100, 10, d.GOLD), k.brackets(300, 100, 500, 300, 30, d.BONE, 4),
                                  k.block(600, 100, 200, 100, d.LED, shadow=d.BONE, off=8)))
        self.assertEqual(px(f, 105, 105), GOLD + (255,))                       # the lamp
        self.assertTrue(20 < alpha(f, 98, 105) < 90)                           # its halo, 3 px out
        self.assertEqual(alpha(f, 95, 105), 0)
        self.assertEqual((alpha(f, 310, 101), alpha(f, 301, 120), alpha(f, 340, 101), alpha(f, 400, 200)), (255, 255, 0, 0))     # a corner: two legs of 30
        self.assertEqual((alpha(f, 490, 299), alpha(f, 499, 280)), (255, 255))                                                 # and the opposite one
        self.assertEqual((px(f, 804, 150)[:3], px(f, 700, 204)[:3]), (BONE, BONE))                                             # the hard shadow, right and under
        self.assertNotEqual(px(f, 700, 150)[:3], BONE)

    def test_type_can_be_cut_to_a_width(self):
        from eva_desk import draw as d
        long, got = "A VERY LONG TITLE THAT CANNOT FIT IN THE CARD AT ALL", {}

        def fn(k):
            got["full"] = k.measure(long, 38, face="display")
            got["cut"] = k.measure(long, 38, face="display", width=300)
            got["short"] = (k.measure("EVA", 38, face="display"), k.measure("EVA", 38, face="display", width=300))
            got["drawn"] = k.text(long, 100, 300, 38, d.BONE, face="display", width=300)
            k.text("مرحبا بالعالم " * 6, 100, 500, 38, d.BONE, face="display", width=300)
        f = self.frame(fn)
        self.assertGreater(got["full"], 600)
        self.assertTrue(200 < got["cut"] <= 300)
        self.assertEqual(got["short"][0], got["short"][1])                     # what fits is left alone
        self.assertEqual(got["drawn"], got["cut"])
        for rows in (range(250, 320, 3), range(450, 520, 3)):                  # nothing past the width, in either script
            self.assertFalse(any(alpha(f, x, y) for x in range(404, 900, 3) for y in rows))

    def test_plain_layout_and_available(self):
        from eva_desk import draw as d, motion
        ink, logical = d.plain_layout("EVA", d.F_META, 20, spacing=2).get_pixel_extents()
        self.assertGreater(logical.width, 30)
        self.assertTrue(motion.available())

    def halves(self):
        """A 4x2 picture: its left half bone, its right half gold."""
        from eva_desk import draw as d, gtkutil

        def paint(cr):
            d.rgba(cr, d.BONE)
            cr.rectangle(0, 0, 2, 2)
            cr.fill()
            d.rgba(cr, d.GOLD)
            cr.rectangle(2, 0, 2, 2)
            cr.fill()
        return gtkutil.render_texture(4, 2, paint)

    def test_where_a_picture_lies_when_it_fills_a_box(self):
        from eva_desk.motion.kit import cover_box
        self.assertEqual(cover_box(4, 2, 100, 100, 200, 200), (0.0, 100.0, 400.0, 200.0))           # as high as the box, the sides overhang evenly
        self.assertEqual(cover_box(4, 2, 100, 100, 200, 200, fx=0.0), (100.0, 100.0, 400.0, 200.0))
        self.assertEqual(cover_box(4, 2, 100, 100, 200, 200, fx=1.0), (-100.0, 100.0, 400.0, 200.0))
        self.assertEqual(cover_box(4, 2, 0, 0, 400, 100, zoom=2.0, fy=1.0), (-200.0, -300.0, 800.0, 400.0))
        ix, iy, iw, ih = cover_box(1792, 768, 0, 0, 1720, 720)
        self.assertAlmostEqual(iw, 1720.0)
        self.assertAlmostEqual(ih, 768 * 1720 / 1792)

    def test_cover_fills_the_box_and_nothing_else(self):
        tex = self.halves()
        f = self.frame(lambda k: k.cover(tex, 100, 100, 200, 200, fx=0.0))
        self.assertTrue(near(px(f, 150, 150), BONE) and near(px(f, 240, 290), BONE))               # the left half of the picture (sampled clear of
        self.assertEqual((alpha(f, 95, 150), alpha(f, 305, 150), alpha(f, 150, 95), alpha(f, 150, 305)), (0, 0, 0, 0))     # its middle, where 4 px
        f = self.frame(lambda k: k.cover(tex, 100, 100, 200, 200, fx=1.0))                                                 # scaled to 400 run together)
        self.assertTrue(near(px(f, 150, 150), GOLD))
        f = self.frame(lambda k: k.cover(tex, 100, 100, 200, 200, fx=0.0, alpha=0.5))
        self.assertAlmostEqual(alpha(f, 150, 150), 128, delta=2)
        self.assertEqual(pink(f), 0)
        got = []
        self.frame(lambda k: got.append(k.cover(tex, 100, 100, 200, 200, fx=1.0)))
        self.assertEqual(got, [(-100.0, 100.0, 400.0, 200.0)])                 # it says where the picture went

    def test_a_screen_blend_leaves_the_ground_where_the_picture_is_black(self):
        from eva_desk import draw as d

        def paint(k):
            with k.screen_blend(lambda: k.rect(0, 0, 400, 300, d.INK)):
                k.rect(0, 0, 400, 300, (0, 0, 0, 1))                       # a picture that is black,
                k.rect(100, 100, 100, 100, d.BONE)                         # but for one bone square
        f = self.frame(paint)
        self.assertTrue(near(px(f, 50, 50), INK, tol=1))
        self.assertTrue(near(px(f, 150, 150), BONE, tol=8))
        self.assertEqual((alpha(f, 410, 50), pink(f)), (0, 0))

    def test_a_soft_band(self):
        from eva_desk import draw as d

        def paint(k):
            with k.soft_band(400, 100, 0, 720):
                k.rect(0, 0, 1720, 720, d.BONE)
        f = self.frame(paint)
        self.assertGreaterEqual(alpha(f, 400, 300), 250)
        self.assertAlmostEqual(alpha(f, 350, 300), 128, delta=14)
        self.assertAlmostEqual(alpha(f, 450, 300), 128, delta=14)
        self.assertEqual((alpha(f, 295, 300), alpha(f, 505, 300), pink(f)), (0, 0, 0))

    def test_a_ring_is_six_lines_of_any_size_and_no_picture(self):
        from eva_desk import draw as d
        from eva_desk.motion import Piece, render

        class P(Piece):
            length = 1.0

            def paint(self, kit, t, ctx):
                kit.ring(300, 300, 100, d.GOLD, 4)
        f = render.frame(P(), 0.0, 1720, 720, {})
        self.assertGreater(alpha(f, 386, 300), 200)            # the right edge stands upright at cx + r cos 30
        self.assertGreater(alpha(f, 343, 375), 200)            # the middle of the edge that runs down to the bottom corner
        self.assertEqual((alpha(f, 300, 300), alpha(f, 420, 300)), (0, 0))
        self.assertEqual(texture_widths(render.build(P(), 0.0, 1720, 720, {})), [])


class CardTest(unittest.TestCase):
    def setUp(self):
        from eva_desk.motion import render
        from eva_desk.motion.seq.card import Card
        self.render, self.card = render, Card()

    def at(self, t, w=1720, h=720, **ctx):
        return self.render.frame(self.card, t, w, h, dict(CTX, **ctx))

    def test_identity(self):
        self.assertEqual((self.card.name, self.card.length, self.card.covers), ("card", 2.0, True))

    def test_plates_cover_the_desk_from_026_to_162(self):
        for t in (0.26, 0.9, 1.3, 1.61):
            self.assertEqual(set(grid(self.at(t))), {255}, t)
        f = self.at(0.26)
        self.assertEqual((px(f, 8, 8)[:3], px(f, 1712, 712)[:3]), (INK, INK))      # both plates, in ink

    def test_nothing_the_offline_renderer_cannot_draw(self):
        for t in (0.05, 0.2, 0.5, 0.9, 1.2, 1.5, 1.8):
            self.assertEqual(pink(self.at(t)), 0, t)

    def test_clear_at_both_ends(self):
        self.assertEqual(alpha(self.at(0.0), 860, 360), 0)
        self.assertEqual(set(grid(self.at(2.0))), {0})

    def test_the_seam_leans(self):
        from eva_desk.motion.seq import card
        left, right = card.plates(1720, 720, 1.0)
        self.assertEqual((left[1], left[2]), ((955, 0), (765, 720)))          # 190 px over the height, about the centre
        self.assertEqual((right[1], right[2]), (left[1], left[2]))            # met
        left, right = card.plates(1720, 720, 0.0)
        self.assertLess(left[1][0], 0)                                        # both off the screen
        self.assertGreater(right[2][0], 1720)

    def test_never_a_bright_screen(self):
        f = self.at(0.6)                                                      # the slab at its widest
        points = [(x, y) for y in range(10, 720, 20) for x in range(10, 1720, 20)]
        self.assertLess(sum(px(f, x, y)[:3] == BONE for x, y in points) / len(points), 0.5)

    def test_the_name_is_the_apps(self):
        self.assertTrue(same(self.at(0.5), self.at(0.5, app="KITTY")))        # not shown yet
        self.assertFalse(same(self.at(1.15), self.at(1.15, app="KITTY")))

    def test_a_long_name_is_set_smaller(self):
        from eva_desk.motion import Piece
        from eva_desk.motion.seq import card
        long, got = "LIBREOFFICE CALC SPREADSHEET EDITOR", {}

        class P(Piece):
            length = 1.0

            def paint(self, kit, t, ctx):
                got["short"], got["long"] = card.name_size(kit, "FIREFOX"), card.name_size(kit, long)
                got["width"] = card.name_width(kit, long, got["long"])
        self.render.frame(P(), 0, 1720, 720, {})
        self.assertEqual(got["short"], 170)
        self.assertLess(got["long"], 170)
        self.assertLessEqual(got["width"], 1720 - 128)

    def test_odd_names_and_missing_inputs(self):
        for app in ("", None, "火狐 🦊", "A" * 80):
            for t in (0.9, 1.2):
                self.at(t, app=app)
        self.render.frame(self.card, 1.2, 1720, 720, {})                      # no inputs at all

    def test_other_monitor_shapes(self):
        for w, h in ((3440, 1440), (1080, 1920), (640, 360)):
            self.assertEqual(set(grid(self.at(1.0, w, h))), {255}, (w, h))

    def test_no_hairline_where_the_plates_meet(self):
        f = self.at(0.9)                                                      # met: the desk must not show through the seam
        for y in range(3, 720, 7):
            x = round(955 - 190 * y / 720)
            self.assertEqual([alpha(f, x + dx, y) for dx in (-2, -1, 0, 1, 2)], [255] * 5, y)

    def test_a_hazard_edge_rides_each_seam_while_the_plates_move(self):
        from eva_desk import draw as d
        from eva_desk.motion import timeline as T
        from eva_desk.motion.seq import card
        claret = tuple(round(255 * c) for c in d.CLARET[2::-1])
        f = self.at(0.05)
        left, right = card.plates(1720, 720, T.quint_out(T.seg(0.05, 0, 0.26)))
        for plate, side in ((left, -1), (right, 1)):
            top, floor = plate[1][0], plate[2][0]
            near_seam, deep = [], []                                          # 3 px and 13 px into the plate, row by row
            for y in range(20, 700, 3):
                x = top + (floor - top) * y / 720
                near_seam.append(px(f, x + 3 * side, y)[:3] == claret)
                deep.append(px(f, x + 13 * side, y)[:3] == claret)
            self.assertTrue(any(near_seam) and not all(near_seam), side)      # stripes
            out_of_step = sum(a != b for a, b in zip(near_seam, deep))        # on the diagonal: across the edge they shift
            self.assertGreater(out_of_step, len(deep) / 4, side)
        met = self.at(0.9)
        self.assertFalse(any(px(met, x, y)[:3] == claret for y in range(4, 720, 8) for x in range(700, 1020)))    # gone once they have met

    def test_the_kanji_come_from_outside_a_tall_frame_too(self):
        for w, h in ((1720, 720), (1080, 1920)):
            f = self.at(0.13, w, h)                                           # what lives on the plates shows from 0.12; the kanji set off at 0.14
            self.assertFalse(any(px(f, x, y)[:3] == BONE for y in range(2, h, 9) for x in range(2, w, 9)), (w, h))

    def test_a_name_whose_letters_join_is_set_whole(self):
        from eva_desk import draw as d
        from eva_desk.motion import Piece
        from eva_desk.motion.seq import card
        name = "مرحبا بالعالم"

        class Whole(Piece):                                                   # the name alone, as one run of type, where the card holds it
            length = 2.0

            def paint(self, kit, t, ctx):
                kit.rect(0, 0, kit.W, kit.H, d.INK)
                kit.text(name, card.INSET, 0.60 * kit.H - 16, card.name_size(kit, name), d.BONE, face="display")
        got, want = self.at(1.2, app=name), self.render.frame(Whole(), 1.2, 1720, 720, {})
        rows = slice(got.get_stride() * 250, got.get_stride() * 400)          # the rows the name stands in, and nothing else does
        self.assertTrue(bytes(got.get_data())[rows] == bytes(want.get_data())[rows])
        self.assertIn(BONE + (255,), {px(want, x, 330) for x in range(64, 1000)})

    def test_same_frame_twice(self):
        self.assertTrue(same(self.at(1.234), self.at(1.234)))


class ShaftTest(unittest.TestCase):
    def setUp(self):
        from eva_desk.motion import render
        from eva_desk.motion.seq.shaft import Shaft
        self.render, self.shaft = render, Shaft()

    def at(self, t, w=1720, h=720, **ctx):
        return self.render.frame(self.shaft, t, w, h, dict(CTX, **ctx))

    def test_identity(self):
        self.assertEqual((self.shaft.name, self.shaft.length, self.shaft.covers), ("shaft", 2.0, True))

    def test_travel(self):
        from eva_desk.motion.seq import shaft
        self.assertEqual(shaft.travel(0.0), 0.0)
        self.assertAlmostEqual(shaft.travel(1.0), 59.0)
        ds = [shaft.travel(i / 200) for i in range(201)]
        self.assertEqual(ds, sorted(ds))
        self.assertLess(shaft.travel(0.25), 2.0)                              # slow off the locks
        self.assertAlmostEqual(shaft.travel(0.5), 59 * 0.125 / (0.125 + 0.5 ** 1.7))
        self.assertGreater(shaft.travel(0.9), 57.0)                           # nearly there: it is braking

    def test_the_exit_grows_into_the_screen(self):
        from eva_desk.motion.seq import shaft
        self.assertEqual(shaft.exit_half(0.0, 1720, 720), (860 / 60, 360 / 60))
        hw, hh = shaft.exit_half(2.0, 1720, 720)
        self.assertAlmostEqual(hw, 860)
        self.assertAlmostEqual(hh, 360)
        ws = [shaft.exit_half(i / 50, 1720, 720)[0] for i in range(101)]
        self.assertEqual(ws, sorted(ws))

    def test_the_far_end_is_the_desk(self):
        f = self.at(1.0)
        self.assertEqual((alpha(f, 860, 360), alpha(f, 12, 12)), (0, 255))    # the hole, the shaft
        f = self.at(1.98)
        self.assertEqual((alpha(f, 860, 360), alpha(f, 300, 200)), (0, 0))    # nearly all of the screen now
        self.assertEqual(set(grid(self.at(2.0))), {0})

    def test_nothing_the_offline_renderer_cannot_draw(self):
        for t in (0.0, 0.3, 0.6, 1.0, 1.4, 1.7, 1.95):
            self.assertEqual(pink(self.at(t)), 0, t)

    def test_gates_count_down(self):
        from eva_desk.motion.seq import shaft
        self.assertEqual([shaft.gate_number(k) for k in (10, 20, 30, 40, 50)], [5, 4, 3, 2, 1])
        self.assertIsNone(shaft.gate_number(60))
        self.assertIsNone(shaft.gate_number(15))

    def test_the_instruments_carry_the_name_and_leave(self):
        self.assertFalse(same(self.at(0.6), self.at(0.6, app="KITTY")))
        self.assertTrue(same(self.at(1.85), self.at(1.85, app="KITTY")))      # gone by 1.80

    def test_never_a_bright_screen(self):
        points = [(x, y) for y in range(10, 720, 20) for x in range(10, 1720, 20)]
        for t in (0.0, 0.3, 0.55, 1.0, 1.4, 1.7, 1.95):
            f = self.at(t)
            bright = sum(1 for x, y in points if alpha(f, x, y) and min(px(f, x, y)[:3]) > 200)
            self.assertLess(bright / len(points), 0.2, t)

    def test_odd_names_and_shapes(self):
        for app in ("", None, "火狐 🦊", "A" * 80):
            self.at(0.6, app=app)
        self.render.frame(self.shaft, 0.6, 1720, 720, {})
        for w, h in ((3440, 1440), (1080, 1920), (640, 360)):
            f = self.at(1.0, w, h)
            self.assertEqual((alpha(f, w // 2, h // 2), alpha(f, 4, 4)), (0, 255), (w, h))

    def test_launch_sits_centred_under_its_rule(self):
        from eva_desk.motion import Piece
        from eva_desk.motion.seq import shaft

        class Sign(Piece):                                                    # the sign alone, at full size
            length = 1.0

            def paint(self, kit, t, ctx):
                with kit.transform(dx=860, dy=100):
                    shaft.sign(kit)
        f = self.render.frame(Sign(), 0, 1720, 720, {})
        rule = [x for x in range(1720) if near(px(f, x, 300), GOLD)]          # the rule: 196 to 204 under the origin
        word = [x for x in range(1720) if any(near(px(f, x, y), GOLD) for y in range(320, 366))]      # LAUNCH stands on 262
        self.assertEqual((rule[0], rule[-1]), (430, 1289))
        self.assertGreater(word[-1] - word[0], 200)
        self.assertLess(abs((word[0] + word[-1]) / 2 - (rule[0] + rule[-1]) / 2), 2)

    def test_same_frame_twice(self):
        self.assertTrue(same(self.at(1.234), self.at(1.234)))


class RenderTest(unittest.TestCase):
    def test_registry(self):
        from eva_desk import motion
        self.assertEqual(list(motion.pieces()), ["card", "shaft", "boot", "wake", "berserk", "track"])
        self.assertEqual({n: p().name for n, p in motion.pieces().items()}, {n: n for n in motion.pieces()})

    def test_parse_size(self):
        from eva_desk.motion import render
        self.assertEqual(render.parse_size("1720x720"), (1720, 720))
        for bad in ("", "1720", "0x720", "axb", "1720x720x3"):
            with self.assertRaises(ValueError, msg=bad):
                render.parse_size(bad)

    def test_sheet_and_files(self):
        from eva_desk.motion import pieces, render
        s = render.sheet(pieces()["card"](), 320, 180, render.fixture_ctx(), cols=4, rows=2)
        self.assertEqual((s.get_width(), s.get_height()), (1280, 360))
        self.assertEqual(alpha(s, 10, 10), 255)                               # frames sit on a stand-in desk, not on nothing
        with tempfile.TemporaryDirectory() as tmp, mock.patch("shutil.which", return_value=None), \
                contextlib.redirect_stdout(io.StringIO()):
            out = render.render_motion(tmp, only="card", size=(320, 180), fps=10)
            self.assertEqual([p.name for p in out], ["card.png"])
            self.assertGreater((Path(tmp) / "card.png").stat().st_size, 2000)
            with self.assertRaises(KeyError):
                render.render_motion(tmp, only="nope")

    @unittest.skipUnless(shutil.which("ffmpeg"), "ffmpeg is not installed")
    def test_mp4(self):
        from eva_desk.motion import render
        with tempfile.TemporaryDirectory() as tmp, contextlib.redirect_stdout(io.StringIO()):
            out = render.render_motion(tmp, only="shaft", size=(321, 181), fps=10)       # odd sizes are made even
            self.assertEqual(sorted(p.name for p in out), ["shaft.mp4", "shaft.png"])
            self.assertGreater((Path(tmp) / "shaft.mp4").stat().st_size, 1000)

    def test_build_time_is_measured(self):
        from eva_desk.motion import pieces, render
        self.assertGreater(render.build_ms(pieces()["shaft"](), 1720, 720, render.fixture_ctx(), n=5), 0)

    def test_type_is_not_set_again_for_every_frame(self):
        # GTK keeps the glyphs it has drawn by their exact size on screen. Type under a scale that changes is a
        # new size every frame, rasterised on the CPU every frame: a whole sequence must get by with a handful of sizes
        from eva_desk.motion import pieces, render
        for name, cls in pieces().items():
            piece, sizes = cls(), set()
            for i in range(120):
                node = render.build(piece, piece.length * (i + 0.5) / 120, 1720, 720, render.fixture_ctx())
                sizes |= glyph_sizes(node) if node is not None else set()
            self.assertTrue(0 < len(sizes) <= 8, (name, sorted(sizes)))       # every piece sets some type, with all its inputs given

    def test_prepare_makes_the_stamps_before_the_first_frame(self):
        from eva_desk import gtkutil  # noqa: F401
        from gi.repository import Gtk
        from eva_desk.motion import pieces, render
        from eva_desk.motion.kit import Kit
        for name, cls in pieces().items():
            piece, store, ctx = cls(), {}, render.fixture_ctx()
            kit = Kit(Gtk.Snapshot(), 1720, 720, 1, store)
            piece.prepare(kit, ctx)
            kit.close()
            made = len(store)
            self.assertEqual(made > 0, name in ("card", "shaft", "boot", "berserk"), name)       # the pieces whose type changes size, or that tile hexagons
            for i in range(60):
                kit = Kit(Gtk.Snapshot(), 1720, 720, 1, store)
                piece.draw(kit, piece.length * (i + 0.5) / 60, ctx)
                kit.close()
            self.assertEqual(len(store), made, name)                          # no frame had to make one

    def test_stills_for_the_standing_render(self):
        from eva_desk import motion, preview
        with tempfile.TemporaryDirectory() as tmp:
            out = preview.motion_stills(tmp, 640, 360)
            self.assertEqual(sorted(p.name for p in out), sorted(f"motion_{n}.png" for n in motion.everything()))

    def test_a_loop_is_rendered_for_one_lap(self):
        from eva_desk.motion import render
        with tempfile.TemporaryDirectory() as tmp, mock.patch("shutil.which", return_value=None), \
                contextlib.redirect_stdout(io.StringIO()):
            out = render.render_motion(tmp, only="standby", size=(320, 180), fps=10)
            self.assertEqual([p.name for p in out], ["standby.png"])
        self.assertEqual(sorted(render.fixture_ctx()["readings"]), ["MAGI·1 CPU 07%", "MAGI·2 RAM 9.8G", "MAGI·3 LAN ↓340K"])

    def test_command_line(self):
        env = dict(os.environ, WAYLAND_DISPLAY="eva-none", PYTHONPATH=str(ROOT))
        with tempfile.TemporaryDirectory() as tmp:
            r = subprocess.run([sys.executable, "-m", "eva_desk", "--render-motion", tmp, "--only", "card", "--size", "320x180", "--fps", "10"],
                               cwd=ROOT, env=env, capture_output=True, text=True, timeout=180)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertTrue((Path(tmp) / "card.png").exists())
            self.assertIn("card", r.stdout)
            r = subprocess.run([sys.executable, "-m", "eva_desk", "--render-motion", tmp, "--only", "nope"],
                               cwd=ROOT, env=env, capture_output=True, text=True, timeout=60)
            self.assertEqual(r.returncode, 2)
            self.assertIn("card, shaft", r.stdout + r.stderr)


class BootTest(unittest.TestCase):
    def setUp(self):
        from eva_desk.motion import render
        from eva_desk.motion.seq.boot import Boot
        self.render, self.boot = render, Boot()

    def at(self, t, w=1720, h=720, **ctx):
        return self.render.frame(self.boot, t, w, h, dict(self.render.fixture_ctx(), **ctx))

    def test_identity(self):
        self.assertEqual((self.boot.name, self.boot.length, self.boot.covers), ("boot", 2.6, True))

    def test_it_covers_the_desk_until_the_gate_opens(self):
        for t in (0.0, 0.5, 1.2, 1.94):
            self.assertEqual(set(grid(self.at(t))), {255}, t)

    def test_the_lines_carry_what_is_read_live(self):
        from eva_desk.motion.seq import boot
        got = boot.lines({"outputs": ["3440×1440", "1080×1920"], "hyprland": "0.56", "lua": True, "net": "wifi"})
        self.assertEqual(len(got), 6)
        self.assertEqual(got[0], ("EVA-DESK ・ 起動シーケンス", None))
        self.assertEqual(got[3], ("MAGI-3  CASPER     WIFI", "OK"))
        self.assertEqual(got[4], ("OUTPUT  3440×1440 ・ 1080×1920", "2 UP"))
        self.assertEqual(got[5], ("HYPRLAND 0.56 ・ LUA", "LINKED"))
        bare = boot.lines({})
        self.assertEqual((bare[3], bare[4], bare[5]), (("MAGI-3  CASPER     LAN", "OK"), ("OUTPUT  NONE", "0 UP"), ("HYPRLAND  ・ LUA", "LINKED")))
        self.assertEqual(boot.lines({"net": "none", "lua": False, "outputs": ["a", "b", "c", "d"]})[3:],
                         [("MAGI-3  CASPER     NONE", "DOWN"), ("OUTPUT  a ・ b ・ c", "4 UP"), ("HYPRLAND  ・ LEGACY", "LINKED")])

    def test_the_field_and_the_bar_run_on_twos(self):
        self.assertTrue(same(self.at(0.84), self.at(0.90)))                    # the same twelfth of a second: the same picture
        self.assertFalse(same(self.at(0.90), self.at(0.93)))

    def test_the_gate_opens_along_the_seam(self):
        from eva_desk import draw as d
        claret = tuple(round(255 * c) for c in d.CLARET[2::-1])
        self.assertEqual(px(self.at(1.96), 860, 446)[:3], BONE)                # the seam is marked for a moment
        f = self.at(2.15)                                                      # half open
        self.assertEqual((alpha(f, 860, 100), alpha(f, 860, 400), alpha(f, 860, 660)), (255, 0, 255))
        for y in (210, 596):                                                   # a hazard edge on each part, along the cut
            self.assertTrue(any(px(f, x, y)[:3] == claret for x in range(0, 1720, 3)), y)

    def test_it_ends_on_the_desk_under_brackets_and_a_tag(self):
        f = self.at(2.5)
        self.assertEqual(alpha(f, 860, 360), 0)
        self.assertEqual(px(f, 20, 38), BONE + (255,))                         # a bracket at the top left, under the bar
        self.assertEqual(px(f, 1690, 60)[:3], GOLD)                            # the tag, in its padding
        self.assertEqual((alpha(self.at(2.59), 20, 38), alpha(self.at(2.59), 1690, 60)), (0, 0))      # they hold to 2.58
        self.assertEqual(set(grid(self.at(2.6))), {0})

    def test_the_gate_draws_each_cell_once(self):
        from gi.repository import Gsk

        def count(t, kind):
            return sum(n.get_node_type() == kind for n, _ in nodes(self.render.build(self.boot, t, 1720, 720, self.render.fixture_ctx())))
        whole, split = count(1.9, Gsk.RenderNodeType.TEXTURE_NODE), count(2.1, Gsk.RenderNodeType.TEXTURE_NODE)
        self.assertGreater(whole, 100)
        self.assertLessEqual(split, whole + 30)                                # the two parts share only the cells on the seam
        self.assertLessEqual(count(1.9, Gsk.RenderNodeType.OPACITY_NODE), 2)   # no cell under an opacity of its own: its strength is in its picture

    def test_never_a_bright_screen(self):
        points = [(x, y) for y in range(10, 720, 20) for x in range(10, 1720, 20)]
        for t in (0.3, 1.0, 1.5, 1.9, 2.2):
            f = self.at(t)
            bright = sum(1 for x, y in points if alpha(f, x, y) and min(px(f, x, y)[:3]) > 200)
            self.assertLess(bright / len(points), 0.2, t)

    def test_nothing_the_offline_renderer_cannot_draw(self):
        for t in (0.1, 0.6, 1.0, 1.3, 1.6, 2.1, 2.4):
            self.assertEqual(pink(self.at(t)), 0, t)

    def test_other_monitor_shapes_and_missing_inputs(self):
        for w, h in ((3440, 1440), (1080, 1920), (640, 360)):
            self.assertEqual(set(grid(self.at(1.0, w, h))), {255}, (w, h))
        tall = self.at(1.9, 1080, 1920)                                        # the gate opens through the digits on any frame
        self.assertTrue(any(px(tall, x, round(0.62 * 1920))[:3] == BONE for x in range(0, 1080, 2)))
        self.at(1.0, outputs=[], hyprland="", net="none", bar=0)
        self.render.frame(self.boot, 1.0, 1720, 720, {})

    def test_same_frame_twice(self):
        self.assertTrue(same(self.at(1.234), self.at(1.234)))


class WakeTest(unittest.TestCase):
    def setUp(self):
        from eva_desk.motion import render
        from eva_desk.motion.seq.wake import Wake
        self.render, self.wake = render, Wake()

    def at(self, t, w=1720, h=720):
        return self.render.frame(self.wake, t, w, h, self.render.fixture_ctx())

    def test_identity(self):
        self.assertEqual((self.wake.name, self.wake.length, self.wake.covers), ("wake", 1.1, True))

    def test_it_covers_the_desk_from_its_first_frame(self):
        for t in (0.0, 0.3, 0.7, 0.84):                                        # held under a lock screen, it is frame 0 that shows
            self.assertEqual(set(grid(self.at(t))), {255}, t)

    def test_two_waves_close_on_each_other(self):
        def rows(t):                                                           # how many rows of the graph the gold wave reaches
            f = self.at(t)
            return sum(any(near(px(f, x, y), GOLD) for x in range(64, 1656, 4)) for y in range(250, 470))
        early, late = rows(0.2), rows(0.55)
        self.assertGreater(late, 0)
        self.assertGreater(early, 3 * late)

    def test_they_lock_into_one_bone_line_and_a_plate(self):
        f = self.at(0.7)
        self.assertEqual(px(f, 860, 360)[:3], BONE)
        self.assertEqual(px(f, 70, 500)[:3], BONE)                             # the plate, in its padding
        self.assertNotEqual(px(self.at(0.6), 70, 500)[:3], BONE)

    def test_the_cover_folds_to_a_line_and_the_line_closes(self):
        f = self.at(0.86)                                                      # the first of three steps
        self.assertEqual((alpha(f, 860, 50), alpha(f, 860, 360), alpha(f, 860, 680)), (0, 255, 0))
        f = self.at(1.0)                                                       # a bone line across the middle
        self.assertEqual((px(f, 860, 360), alpha(f, 860, 300)), (BONE + (255,), 0))
        f = self.at(1.06)                                                      # closing on the centre
        self.assertEqual((alpha(f, 200, 360), alpha(f, 860, 360)), (0, 255))
        for t in (1.08, 1.09, 1.1):
            self.assertEqual(set(grid(self.at(t))), {0}, t)

    def test_never_a_bright_screen(self):
        points = [(x, y) for y in range(10, 720, 20) for x in range(10, 1720, 20)]
        for t in (0.1, 0.4, 0.7, 0.9, 1.0):
            f = self.at(t)
            bright = sum(1 for x, y in points if alpha(f, x, y) and min(px(f, x, y)[:3]) > 200)
            self.assertLess(bright / len(points), 0.2, t)

    def test_nothing_the_offline_renderer_cannot_draw(self):
        for t in (0.0, 0.1, 0.3, 0.6, 0.7, 0.9, 1.0):
            self.assertEqual(pink(self.at(t)), 0, t)

    def test_other_monitor_shapes(self):
        for w, h in ((3440, 1440), (1080, 1920), (640, 360)):
            self.assertEqual(set(grid(self.at(0.5, w, h))), {255}, (w, h))
            self.assertEqual(set(grid(self.at(1.09, w, h))), {0}, (w, h))
        self.render.frame(self.wake, 0.5, 1720, 720, {})

    def test_same_frame_twice(self):
        self.assertTrue(same(self.at(0.4321), self.at(0.4321)))


class BerserkTest(unittest.TestCase):
    def setUp(self):
        from eva_desk import draw as d
        from eva_desk.motion import render
        from eva_desk.motion.seq.berserk import Berserk
        self.render, self.berserk = render, Berserk()
        self.led = tuple(round(255 * c) for c in d.LED[2::-1])

    def at(self, t, w=1720, h=720, **ctx):
        return self.render.frame(self.berserk, t, w, h, dict(self.render.fixture_ctx(), **ctx))

    def test_identity(self):
        b = self.berserk
        self.assertEqual((b.name, b.length, b.covers, b.rank), ("berserk", 1.3, False, 1))

    def test_the_edges_only(self):
        for t in (0.1, 0.3, 0.6, 0.9, 1.1, 1.25):
            f = self.at(t)
            self.assertEqual((alpha(f, 860, 360), alpha(f, 860, 200), alpha(f, 1200, 500)), (0, 0, 0), t)

    def test_strips_run_in_from_opposite_sides(self):
        f = self.at(0.05)
        self.assertEqual((alpha(f, 100, 39), alpha(f, 1600, 39)), (255, 0))    # under the bar, from the left
        self.assertEqual((alpha(f, 1600, 712), alpha(f, 100, 712)), (255, 0))  # along the floor, from the right
        f = self.at(0.6)
        for y in (39, 712):
            row = [px(f, x, y) for x in range(0, 1720, 2)]
            self.assertTrue(all(p[3] == 255 for p in row), y)
            self.assertTrue({self.led, INK} <= {p[:3] for p in row}, y)        # orange on ink
        self.assertEqual((px(f, 1, 300)[:3], px(f, 1718, 400)[:3]), (self.led, self.led))       # and a line down each side
        self.assertFalse(same(self.at(0.6), self.at(0.7)))                     # the strips crawl while they are up

    def test_the_block_slams_in_at_the_lower_left(self):
        f = self.at(0.7)
        self.assertEqual(px(f, 330, 510)[:3], self.led)                        # the slab, clear of its type
        self.assertEqual((px(f, 344, 600)[:3], px(f, 200, 674)[:3]), (BONE, BONE))               # its hard shadow, right and under
        self.assertEqual(alpha(self.at(0.15), 200, 600), 0)                    # not before 0.18
        self.assertEqual(alpha(self.at(1.1), 200, 600), 0)                     # and closed again by 1.07

    def test_the_line_says_what_is_hot(self):
        self.assertFalse(same(self.at(0.8), self.at(0.8, load="RAM 91%")))
        self.assertFalse(same(self.at(0.8), self.at(0.8, seconds=5)))
        self.assertFalse(same(self.at(0.8), self.at(0.8, seconds=0)))          # a limit of no seconds reads 0 S, not the default
        self.assertTrue(same(self.at(0.3), self.at(0.3, load="RAM 91%")))      # it types on from 0.40

    def test_the_top_strip_sits_under_the_bar(self):
        self.assertEqual(alpha(self.at(0.6), 860, 10), 0)                      # no bar named: 28 design px of it
        self.assertEqual(alpha(self.at(0.6, bar=0), 860, 10), 255)             # no bar: at the top of the screen
        self.assertEqual(alpha(self.at(0.6, 3440, 1440, bar=56), 1720, 78), 255)                 # 56 px of bar on the wide monitor

    def test_it_leaves_the_way_it_came(self):
        for t in (1.29, 1.3):
            self.assertEqual(set(grid(self.at(t))), {0}, t)

    def test_nothing_the_offline_renderer_cannot_draw(self):
        for t in (0.05, 0.2, 0.3, 0.5, 0.8, 1.0, 1.2):
            self.assertEqual(pink(self.at(t)), 0, t)

    def test_other_monitor_shapes_and_missing_inputs(self):
        for w, h in ((3440, 1440), (1080, 1920), (640, 360)):
            f = self.at(0.6, w, h)
            self.assertEqual((alpha(f, w // 2, h // 2), alpha(f, w // 2, h - 3)), (0, 255), (w, h))
        self.render.frame(self.berserk, 0.6, 1720, 720, {})
        self.at(0.6, load="", seconds=None)

    def test_same_frame_twice(self):
        self.assertTrue(same(self.at(0.777), self.at(0.777)))


class TrackTest(unittest.TestCase):
    def setUp(self):
        from eva_desk.motion import render
        from eva_desk.motion.seq.track import Track
        self.render, self.track = render, Track()

    def at(self, t, w=1720, h=720, **ctx):
        return self.render.frame(self.track, t, w, h, dict(self.render.fixture_ctx(), **ctx))

    def test_identity(self):
        k = self.track
        self.assertEqual((k.name, k.length, k.covers, k.rank), ("track", 1.6, False, 0))

    def test_a_card_in_the_lower_left_corner(self):
        x0, y0, x1, y1 = box(self.at(0.8))
        self.assertEqual((x0, y0, y1), (44, 538, 662))                         # the tag's top; the shadow's foot
        self.assertTrue(320 <= x1 - 50 <= 640)                                 # the slab, and 7 px of shadow
        self.assertEqual(alpha(self.at(0.8), 860, 360), 0)
        self.assertEqual(box(self.at(0.8, corner="bottom-right"))[2], 1682)    # or the lower right, 44 px from the side

    def test_the_card_is_as_wide_as_its_type_within_limits(self):
        self.assertEqual(box(self.at(0.8, title="A", artist="B"))[2], 370)     # never under 320
        f = self.at(0.8, title="X" * 300, artist="Y" * 300)
        self.assertEqual(box(f)[2], 690)                                       # never over 640
        self.assertFalse(any(px(f, x, y)[:3] == BONE for x in range(664, 684) for y in range(570, 620)))     # cut inside its padding, not run off the edge

    def test_no_artist_no_lower_slab(self):
        self.assertEqual(box(self.at(0.8, artist=""))[3], 630)                 # the title slab's own shadow, and nothing under it

    def test_it_holds_still(self):
        self.assertTrue(same(self.at(0.6), self.at(1.1)))                      # nothing reacts to the music
        self.assertFalse(same(self.at(0.8), self.at(0.8, title="Other")))
        self.assertFalse(same(self.at(0.8), self.at(0.8, artist="Other")))

    def test_it_comes_out_of_a_rule_and_goes_back_into_it(self):
        for t in (0.05, 1.5):
            x0, y0, x1, y1 = box(self.at(t))
            self.assertLessEqual(y1 - y0, 3, t)                                # only the rule
        self.assertEqual(set(grid(self.at(1.6))), {0})

    def test_odd_titles(self):
        for title in ("مرحبا بالعالم", "🦊🦊🦊", "火狐", "X" * 300):
            for t in (0.3, 0.8, 1.3):
                self.at(t, title=title, artist=title)
        self.assertIsNone(box(self.at(0.8, title="")))                         # nothing to announce: nothing painted
        self.render.frame(self.track, 0.8, 1720, 720, {})

    def test_nothing_the_offline_renderer_cannot_draw(self):
        for t in (0.05, 0.2, 0.4, 0.8, 1.3, 1.5):
            self.assertEqual(pink(self.at(t)), 0, t)

    def test_other_monitor_shapes(self):
        self.assertEqual(box(self.at(0.8, 3440, 1440))[0], 88)
        for w, h in ((1080, 1920), (640, 360)):
            x0, y0, x1, y1 = box(self.at(0.8, w, h))
            self.assertTrue(0 < x0 and x1 < w and h / 2 < y0 and y1 < h, (w, h))

    def test_same_frame_twice(self):
        self.assertTrue(same(self.at(0.3333), self.at(0.3333)))


class TriggersTest(unittest.TestCase):
    def setUp(self):
        from eva_desk.motion import triggers
        self.T = triggers

    def test_boot_once_per_hyprland_session(self):
        T = self.T
        self.assertTrue(T.boot_due(None, "abc"))
        self.assertTrue(T.boot_due("another\n", "abc"))
        self.assertFalse(T.boot_due("abc\n", "abc"))
        self.assertFalse(T.boot_due(None, ""))                                 # not under Hyprland: nothing to boot into

    def test_boot_inputs(self):
        T = self.T
        mons = [{"width": 3440, "height": 1440}, {"width": 1080, "height": 1920, "disabled": True}, {"width": 1920, "height": 1080}]
        self.assertEqual(T.boot_inputs(mons, {"version": "0.56.0"}, True, "wifi"),
                         {"outputs": ["3440×1440", "1920×1080"], "hyprland": "0.56", "lua": True, "net": "wifi"})
        self.assertEqual(T.boot_inputs([], {"tag": "v0.57.1-12-gabc"}, False, None)["hyprland"], "0.57")
        self.assertEqual(T.boot_inputs(None, None, True, "lan"), {"outputs": [], "hyprland": "", "lua": True, "net": "lan"})
        self.assertEqual(T.boot_inputs([], {"version": "git"}, True, "lan")["hyprland"], "git")

    def test_a_game_is_open_wherever_its_window_is(self):
        T, pats = self.T, ["^steam_app_", "^gamescope$"]
        self.assertFalse(T.game_open([{"class": "kitty"}], pats))
        self.assertTrue(T.game_open([{"class": "kitty"}, {"class": "steam_app_42", "hidden": True, "workspace": {"id": 9}}], pats))
        self.assertFalse(T.game_open([], pats))
        self.assertFalse(T.game_open(None, pats))

    def test_fullscreen_monitors(self):
        T = self.T
        mons = [{"id": 0, "name": "DP-1", "activeWorkspace": {"id": 1}, "specialWorkspace": {"id": 0}},
                {"id": 1, "name": "DP-2", "activeWorkspace": {"id": 5}, "specialWorkspace": {"id": -98}}]

        def win(ws, fs, **more):
            return dict({"workspace": {"id": ws}, "fullscreen": fs, "mapped": True}, **more)
        self.assertEqual(T.fullscreen_monitors(mons, [win(1, 2)]), {"DP-1"})
        self.assertEqual(T.fullscreen_monitors(mons, [win(1, 1)]), set())      # maximised is not fullscreen
        self.assertEqual(T.fullscreen_monitors(mons, [win(2, 2)]), set())      # on a workspace that is not showing
        self.assertEqual(T.fullscreen_monitors(mons, [win(1, 2, hidden=True)]), set())
        self.assertEqual(T.fullscreen_monitors(mons, [win(-98, 2), win(1, 0)]), {"DP-2"})        # on the open special workspace
        self.assertEqual(T.fullscreen_monitors(None, None), set())

    def test_track_monitor(self):
        T = self.T
        mons = [{"name": "DP-1", "focused": False}, {"name": "DP-2", "focused": True}]
        self.assertEqual(T.track_monitor(mons, ["DP-1"]), "DP-1")              # the focused one is not a main monitor
        self.assertEqual(T.track_monitor(mons, ["DP-1", "DP-2"]), "DP-2")
        self.assertEqual(T.track_monitor(mons, ["GONE", "DP-1"]), "DP-1")
        self.assertIsNone(T.track_monitor(mons, []))
        self.assertIsNone(T.track_monitor(None, ["DP-1"]))

    def test_what_may_take_the_place_of_what(self):
        T = self.T

        def piece(covers, rank=0):
            return types.SimpleNamespace(covers=covers, rank=rank)
        card, berserk, track = piece(True), piece(False, 1), piece(False, 0)
        for new, old, may in ((card, card, True), (card, berserk, True), (card, track, True), (berserk, track, True),
                              (berserk, berserk, True), (track, track, True), (track, berserk, False),
                              (berserk, card, False), (track, card, False)):
            self.assertEqual(T.outranks(new, old), may)

    def test_track_changes(self):
        w = self.T.TrackWatch(100.0)
        w.feed("Playing", "A", "X", 100.2)                                     # what was playing when the daemon came up
        self.assertIsNone(w.settle(101.0))                                     # is noted, not announced
        w.feed("Playing", "B", "", 110.0)                                      # a new title; its artist arrives a moment later
        w.feed("Playing", "B", "Y", 110.1)
        self.assertIsNone(w.settle(110.3))                                     # not settled yet
        self.assertEqual(w.settle(110.6), ("B", "Y"))
        self.assertIsNone(w.settle(111.0))                                     # once
        w.feed("Paused", "B", "Y", 120.0)
        w.feed("Playing", "B", "Y", 125.0)
        self.assertIsNone(w.settle(126.0))                                     # the same track, resumed
        w.feed("Paused", "C", "Z", 130.0)
        self.assertIsNone(w.settle(131.0))                                     # a new title, but nothing plays
        w.feed("Playing", "C", "Z", 140.0)
        self.assertEqual(w.settle(140.5), ("C", "Z"))
        w.feed("", "", "", 150.0)                                              # the player went away and came back on the same track
        w.feed("Playing", "C", "Z", 155.0)
        self.assertIsNone(w.settle(156.0))
        late = self.T.TrackWatch(0.0)
        self.assertIsNone(late.settle(30.0))                                   # nothing reported yet
        late.feed("Playing", "A", "X", 60.0)                                   # nothing was playing at the start: the first track is announced
        self.assertEqual(late.settle(60.5), ("A", "X"))

    def test_a_card_is_not_repeated_or_rushed(self):
        w = self.T.TrackWatch(0.0)
        w.begin(5.0)                                                           # the player's reports start here, not when the daemon did
        w.feed("Playing", "A", "X", 6.0)
        self.assertIsNone(w.settle(7.0))                                       # so this is still the track that was already playing
        w.feed("Playing", "D", "", 200.0)
        self.assertEqual(w.settle(200.5), ("D", ""))
        w.feed("Playing", "D", "Z", 200.6)                                     # its artist arrives late: the same track, no second card
        self.assertIsNone(w.settle(201.1))
        self.assertFalse(w.pending)
        w.feed("Playing", "E", "Z", 203.0)                                     # the next track, three seconds after a card
        self.assertIsNone(w.settle(203.5))
        self.assertTrue(w.pending)                                             # it waits for the gap, and the caller asks again
        self.assertIsNone(w.settle(209.0))
        self.assertEqual(w.settle(210.6), ("E", "Z"))                          # ten seconds after the last card
        self.assertFalse(w.pending)
        w.feed("Playing", "D", "Z", 230.0)                                     # another player cut in, and now the earlier track is back
        self.assertIsNone(w.settle(230.5))                                     # announced two minutes ago or less: not again
        self.assertFalse(w.pending)
        w.feed("Playing", "E", "Z", 231.0)
        self.assertIsNone(w.settle(231.5))                                     # nor the one before it
        w.feed("Playing", "D", "Z", 400.0)                                     # much later it is news again
        self.assertEqual(w.settle(400.5), ("D", "Z"))

    def test_the_lock_screen(self):
        w = self.T.LockWatch()
        self.assertFalse(w.covered)
        self.assertEqual([w.tick(1.0, False), w.tick(3.0, None)], ["idle", "idle"])        # not locked, or Hyprland did not say
        self.assertEqual(w.tick(5.0, True), "cover")                           # locked: the cover goes up under the lock screen
        self.assertEqual([w.tick(5.5, True), w.tick(6.0, True)], ["hold", "hold"])
        self.assertEqual(w.tick(900.0, False), "play")                         # unlocked
        self.assertFalse(w.covered)
        self.assertEqual(w.tick(902.0, False), "idle")
        self.assertEqual(w.tick(1000.0, True), "cover")
        self.assertEqual([w.tick(1000.5, None), w.tick(1001.5, None)], ["hold", "hold"])     # Hyprland does not answer: the cover waits a little
        self.assertEqual(w.tick(1002.0, True), "hold")                         # it answered again
        self.assertEqual([w.tick(1002.5, None), w.tick(1004.4, None)], ["hold", "hold"])
        self.assertEqual(w.tick(1004.6, None), "drop")                         # two seconds without an answer: the cover may not stay
        self.assertFalse(w.covered)
        self.assertEqual(w.tick(1005.0, None), "idle")


class FakeSurface:
    region = None

    def set_input_region(self, region):
        self.region = region


class FakeWin:
    destroyed = False

    def __init__(self):
        self.visible, self.surface = False, FakeSurface()

    def set_visible(self, on):
        self.visible = on

    def get_visible(self):
        return self.visible

    def present(self):
        pass

    def get_surface(self):
        return self.surface

    def destroy(self):
        self.visible, self.destroyed = False, True


class FakeView:
    ticks = 0

    def queue_draw(self):
        pass

    def add_tick_callback(self, fn):
        self.ticks += 1
        return self.ticks

    def remove_tick_callback(self, tick):
        pass


class FakeMonitor:
    def __init__(self, w=1720, h=720, scale=1):
        self.geo, self.scale = types.SimpleNamespace(width=w, height=h), scale

    def get_geometry(self):
        return self.geo

    def get_scale_factor(self):
        return self.scale


MON = FakeMonitor()
MON2 = FakeMonitor(1080, 1920)


def dummy(covers=True, boom=None):
    """A piece that paints nothing; `boom` makes its "paint" or its "prepare" raise."""
    from eva_desk.motion import Piece

    class Dummy(Piece):
        length = 2.0
        released = 0

        def __init__(self):
            self.kits = []

        def prepare(self, kit, ctx):
            self.kits.append(kit)
            if boom == "prepare":
                raise RuntimeError("boom")

        def paint(self, kit, t, ctx):
            self.kits.append(kit)
            if boom == "paint":
                raise RuntimeError("boom")

        def release(self):
            self.released += 1
    piece = Dummy()
    piece.covers = covers
    return piece


def player():
    """A SequencePlayer with no window behind it; everything else, place() included, is the real thing."""
    from eva_desk.motion.player import SequencePlayer
    p = SequencePlayer.__new__(SequencePlayer)
    p.app, p.win, p.view = object(), FakeWin(), FakeView()
    p.setup()
    p.timers = []
    p._after = lambda ms, fn: p.timers.append((ms, fn))
    return p


class NoCompositor(unittest.TestCase):
    def setUp(self):
        from eva_desk import gtkutil  # noqa: F401
        from gi.repository import Gtk4LayerShell as LS
        patch = mock.patch.object(LS, "set_monitor")      # place() names the monitor to the compositor; there is none here
        patch.start()
        self.addCleanup(patch.stop)


class PlayerTest(NoCompositor):

    def test_plays_to_the_end_once(self):
        p, done, piece = player(), [], dummy()
        self.assertTrue(p.play(piece, MON, {"app": "X"}, on_done=lambda: done.append(1)))
        self.assertTrue(p.win.visible and p.busy)
        self.assertFalse(p.advance(10.0))                 # the first tick is t = 0
        self.assertFalse(p.advance(11.5))
        self.assertAlmostEqual(p.at, 1.5)
        self.assertTrue(p.advance(12.0))                  # t = length: over
        self.assertFalse(p.win.visible or p.busy)
        self.assertEqual((done, piece.released), ([1], 1))
        p.finish()
        self.assertEqual((done, piece.released), ([1], 1))

    def test_a_click_skips_only_what_covers(self):
        p = player()
        p.play(dummy(covers=True), MON, {})
        p.skip()
        self.assertFalse(p.win.visible)
        p.play(dummy(covers=False), MON, {})
        p.skip()
        self.assertTrue(p.win.visible)
        self.assertFalse(p.busy)                          # on screen, but it covers nothing

    def test_the_pointer_goes_through_what_does_not_cover(self):
        p = player()
        p.play(dummy(covers=True), MON, {})
        self.assertFalse(p.win.surface.region.is_empty())
        p.finish()
        p.play(dummy(covers=False), MON, {})
        self.assertTrue(p.win.surface.region.is_empty())

    def test_a_new_piece_replaces_the_running_one(self):
        p, log, a, b = player(), [], dummy(), dummy()
        p.play(a, MON, {}, on_done=lambda: log.append("a"))
        p.play(b, MON, {}, on_done=lambda: log.append("b"))
        self.assertEqual((log, a.released), (["a"], 1))
        self.assertTrue(p.win.visible)
        p.advance(0.0)
        p.advance(2.0)
        self.assertEqual((log, b.released), (["a", "b"], 1))

    def test_no_monitor_no_show(self):
        p = player()
        self.assertFalse(p.play(dummy(), None, {}))
        self.assertFalse(p.win.visible or p.busy)
        self.assertEqual(p.timers, [])
        self.assertTrue(p.play(dummy(), MON, {}))         # and the same once it has played on a monitor
        p.finish()
        timers = len(p.timers)
        self.assertFalse(p.play(dummy(), None, {}))
        self.assertFalse(p.win.visible or p.busy)
        self.assertEqual(len(p.timers), timers)

    def test_a_piece_that_raises_ends_the_sequence(self):
        from gi.repository import Gtk
        p, done = player(), []
        p.play(dummy(boom="paint"), MON, {}, on_done=lambda: done.append(1))
        with contextlib.redirect_stdout(io.StringIO()) as out:
            p._paint(Gtk.Snapshot(), 1720, 720)
            self.assertTrue(p.win.visible)                # GTK is in the middle of that frame: the window goes from the main loop
            self.assertEqual(done, [])
            again = Gtk.Snapshot()
            p._paint(again, 1720, 720)                    # and until it has gone, nothing more is painted
            self.assertIsNone(again.to_node())
            ms, later = p.timers[-1]
            later()
        self.assertEqual(ms, 0)
        self.assertFalse(p.win.visible or p.busy)
        self.assertEqual(done, [1])
        self.assertEqual(out.getvalue().count("eva-desk: motion"), 1)

    def test_a_piece_that_raised_does_not_end_the_next_one(self):
        from gi.repository import Gtk
        p = player()
        p.play(dummy(boom="paint"), MON, {})
        with contextlib.redirect_stdout(io.StringIO()):
            p._paint(Gtk.Snapshot(), 1720, 720)
        later, good = p.timers[-1][1], dummy()
        p.play(good, MON, {})                             # the next piece starts before the main loop got to end the first
        later()
        self.assertTrue(p.win.visible and p.busy)
        p._paint(Gtk.Snapshot(), 1720, 720)
        self.assertEqual(len(good.kits), 2)               # and it is painted: prepare, then this frame

    def test_a_piece_that_cannot_prepare_does_not_play(self):
        p, done = player(), []
        with contextlib.redirect_stdout(io.StringIO()) as out:
            self.assertFalse(p.play(dummy(boom="prepare"), MON, {}, on_done=lambda: done.append(1)))
        self.assertFalse(p.win.visible or p.busy)
        self.assertEqual((p.timers, done), ([], []))
        self.assertIn("eva-desk: motion", out.getvalue())

    def test_the_kit_for_prepare_is_closed(self):
        from eva_desk.motion.kit import Kit
        p, piece = player(), dummy()
        with mock.patch.object(Kit, "close", autospec=True, side_effect=Kit.close) as close:      # watched, and still done
            p.play(piece, MON, {})
        close.assert_called_once_with(piece.kits[0])

    def test_prepare_and_paint_get_the_same_frame(self):
        from gi.repository import Gtk
        p, piece = player(), dummy()
        p.play(piece, FakeMonitor(1720, 720, scale=2), {})          # 3440x1440 px, two px to the point
        p._paint(Gtk.Snapshot(), 1720, 720)                         # GTK paints in points
        before, during = piece.kits
        self.assertEqual((before.s, before.W, before.H, before.density), (during.s, during.W, during.H, during.density))
        self.assertEqual((before.s, before.density), (1.0, 2))

    def test_what_a_piece_stamped_goes_with_it(self):
        from eva_desk import draw as d
        from gi.repository import Gtk
        p, piece = player(), dummy()
        piece.paint = lambda kit, t, ctx: kit.stamp("発", 0, 300, 100, d.BONE, face="display")
        p.play(piece, MON, {})
        p._paint(Gtk.Snapshot(), 1720, 720)
        self.assertEqual(len(p.stamps), 1)                # megabytes of picture: kept while it plays
        p.finish()
        self.assertEqual(p.stamps, {})

    def test_the_safety_timeout_only_ends_its_own_run(self):
        p = player()
        p.play(dummy(), MON, {})
        ms, late = p.timers[-1]
        self.assertEqual(ms, 3000)                        # length + 1 s
        p.finish()
        p.play(dummy(), MON, {})
        late()                                            # the first run's timer fires late
        self.assertTrue(p.win.visible)
        p.timers[-1][1]()
        self.assertFalse(p.win.visible)

    def test_the_safety_is_set_before_anything_is_shown(self):
        p, real = player(), FakeWin.set_visible

        def set_visible(on):                              # showing the window fails half way
            real(p.win, on)
            if on:
                raise RuntimeError("no surface")
        p.win.set_visible = set_visible
        with self.assertRaises(RuntimeError):
            p.play(dummy(), MON, {})
        self.assertTrue(p.win.visible and p.busy)         # it is up, and nothing ticks
        self.assertEqual([ms for ms, _ in p.timers], [3000])
        p.timers[-1][1]()                                 # so the safety is what takes it down
        self.assertFalse(p.win.visible or p.busy)

    def test_any_mouse_button_skips(self):
        from gi.repository import Gtk
        from eva_desk.motion import player as P
        added = []

        def bare(self, app, namespace, **how):            # the overlay without its window
            self.view = types.SimpleNamespace(add_controller=added.append)
        with mock.patch.object(P._Overlay, "__init__", bare):
            P.SequencePlayer(object())
        (click,) = added
        self.assertIsInstance(click, Gtk.GestureClick)
        self.assertEqual(click.get_button(), 0)           # 0 is any button; a gesture listens to the left one unless told

    def test_a_held_piece_waits_on_its_first_frame(self):
        from gi.repository import Gtk
        p, done = player(), []
        self.assertTrue(p.play(dummy(), MON, {}, on_done=lambda: done.append(1), held=True))
        self.assertTrue(p.win.visible and p.busy and p.held)
        self.assertEqual((p.timers, p.view.ticks), ([], 0))                    # no clock runs and no safety counts down: it may wait for hours
        p._paint(Gtk.Snapshot(), 1720, 720)
        self.assertEqual(p.at, 0.0)
        p.start()
        self.assertEqual(([ms for ms, _ in p.timers], p.view.ticks, p.held), ([3000], 1, False))
        p.start()                                                              # again: nothing more
        self.assertEqual((len(p.timers), p.view.ticks), (1, 1))
        p.advance(5.0)
        p.advance(7.0)
        self.assertEqual(done, [1])

    def test_a_click_ends_a_held_piece_too(self):
        p = player()
        p.play(dummy(), MON, {}, held=True)
        p.skip()
        self.assertFalse(p.win.visible or p.busy or p.held)
        p.start()                                                              # the locker exits later: nothing is left to start
        self.assertEqual((p.timers, p.view.ticks), ([], 0))


class PlayersTest(NoCompositor):
    def players(self):
        from eva_desk.motion.player import Players
        return Players(object(), make=lambda app: player())

    def test_a_player_for_every_monitor(self):
        ps, side = self.players(), FakeMonitor(1080, 1920)
        self.assertFalse(ps.busy)
        self.assertTrue(ps.play(dummy(), MON, {}))
        self.assertTrue(ps.play(dummy(), side, {}))
        self.assertEqual(set(ps.by_monitor), {MON, side})
        self.assertTrue(all(p.win.visible for p in ps.by_monitor.values()) and ps.busy)
        self.assertTrue(ps.play(dummy(), MON, {}))                             # the same monitor again: the same player
        self.assertEqual(len(ps.by_monitor), 2)
        self.assertFalse(ps.play(dummy(), None, {}))
        ps.stop()
        self.assertFalse(ps.busy or any(p.win.visible for p in ps.by_monitor.values()))

    def test_what_outranks_what_on_one_monitor(self):
        ps, berserk, track, card = self.players(), dummy(covers=False), dummy(covers=False), dummy()
        berserk.rank = 1
        self.assertTrue(ps.play(berserk, MON, {}))
        self.assertFalse(ps.play(track, MON, {}))                              # the track card is dropped: berserk outranks it
        self.assertIs(ps.by_monitor[MON].piece, berserk)
        self.assertFalse(ps.busy)                                              # nothing covers yet
        self.assertTrue(ps.play(card, MON, {}))                                # what covers takes the place of anything
        self.assertEqual((berserk.released, ps.busy), (1, True))
        self.assertFalse(ps.play(dummy(covers=False), MON, {}))
        self.assertTrue(ps.play(track, FakeMonitor(), {}))                     # another monitor is its own matter

    def test_held_pieces_start_together_and_stop_by_name(self):
        ps, side, a, b = self.players(), FakeMonitor(1080, 1920), dummy(), dummy()
        a.name = b.name = "wake"
        ps.play(a, MON, {}, held=True)
        ps.play(b, side, {}, held=True)
        self.assertTrue(all(p.held for p in ps.by_monitor.values()))
        ps.start()
        self.assertFalse(any(p.held for p in ps.by_monitor.values()))
        ps.stop("card")                                                        # another name: nothing ends
        self.assertTrue(ps.busy)
        ps.stop("wake")
        self.assertEqual((ps.busy, a.released, b.released), (False, 1, 1))

    def test_a_monitor_that_went_away_is_forgotten(self):
        ps, side, gone = self.players(), FakeMonitor(1080, 1920), []
        ps.play(dummy(), MON, {})
        ps.play(dummy(), side, {})
        ps.by_monitor[side].destroy = lambda: gone.append(side)
        ps.forget([MON])
        self.assertEqual((set(ps.by_monitor), gone), ({MON}, [side]))


class FakeHypr:
    lua = True
    fail = None                                 # an exception that every request raises

    def __init__(self):
        self.state, self.execs, self.asked = {}, [], []

    def j(self, what):
        self.asked.append(what)
        if self.fail is not None:
            raise self.fail
        return self.state.get(what)

    def exec(self, cmd):
        self.execs.append(cmd)


class FakeAppInfo:
    def __init__(self, name, categories, app_id="x.desktop"):
        self.name, self.categories, self.app_id = name, categories, app_id

    def get_display_name(self):
        return self.name

    def get_name(self):
        return self.name

    def get_categories(self):
        return self.categories

    def get_id(self):
        return self.app_id


class FakePlayer:
    busy = False

    def __init__(self):
        self.calls = []

    def play(self, piece, mon, ctx, on_done=None, held=False):
        self.calls.append((piece, mon, ctx))
        return True

    def forget(self, alive):
        pass


class LaunchWiring(unittest.TestCase):
    def test_launch_info(self):
        from eva_desk.launcher import launch_info
        self.assertEqual(launch_info(("app", FakeAppInfo("Firefox", "Network;WebBrowser;"))), ("FIREFOX", False))
        self.assertEqual(launch_info(("app", FakeAppInfo("Hades", "Game;ActionGame;"))), ("HADES", True))
        self.assertEqual(launch_info(("app", FakeAppInfo("Gamescope Settings", "Settings;GameTool;"))), ("GAMESCOPE SETTINGS", False))   # a whole category, not a substring
        self.assertEqual(launch_info(("app", FakeAppInfo("Thing", None))), ("THING", False))
        self.assertEqual(launch_info(("app", FakeAppInfo("", ""))), ("APP", False))
        self.assertEqual(launch_info(("cmd", "notify-send hi")), ("NOTIFY-SEND", False))
        self.assertEqual(launch_info(("cmd", "  ")), ("RUN", False))
        self.assertEqual(launch_info(("web", "unit 01")), ("SEARCH", False))

    def launcher(self):
        from eva_desk import launcher as L
        lau = L.Launcher.__new__(L.Launcher)
        lau.cfg, lau.hypr, lau.counts, lau.gdk_monitor, lau.played = config.load("/nonexistent"), FakeHypr(), {}, "MON", []
        lau.app = type("A", (), {"play_launch": lambda s, name, game, mon: lau.played.append((name, game, mon))})()
        lau._save_counts = lau.hide = lau._arm_idle = lambda: None
        return lau

    def test_enter_plays_and_shift_enter_does_not(self):
        from eva_desk import gtkutil  # noqa: F401
        from gi.repository import Gdk
        lau = self.launcher()
        lau.results, lau.sel = [("cmd", "true")], 0
        lau._key(None, Gdk.KEY_Return, 0, Gdk.ModifierType(0))
        self.assertEqual((lau.hypr.execs, lau.played), (["true"], [("TRUE", False, "MON")]))
        lau._key(None, Gdk.KEY_Return, 0, Gdk.ModifierType.SHIFT_MASK)
        self.assertEqual((lau.hypr.execs, lau.played), (["true", "true"], [("TRUE", False, "MON")]))

    def test_a_game_entry_is_flagged(self):
        lau = self.launcher()
        lau._launch(("app", FakeAppInfo("Hades", "Game;", "hades.desktop")))
        self.assertEqual((lau.played, lau.hypr.execs), ([("HADES", True, "MON")], ["gtk-launch hades.desktop"]))

    def test_without_a_player_it_still_launches(self):
        lau = self.launcher()
        lau.app = object()
        lau._launch(("cmd", "true"))
        self.assertEqual(lau.hypr.execs, ["true"])

    def app(self):
        from eva_desk.app import App
        app = App.__new__(App)
        app.cfg, app.hypr, app.motion, app.stages = config.load("/nonexistent"), FakeHypr(), FakePlayer(), {}
        app.hypr.state = {"activeworkspace": {"id": 2}}
        app.focused_gdk = lambda: "FOCUSED"
        return app

    def test_the_default_is_on(self):
        self.assertIs(config.load("/nonexistent")["motion"]["launch"], True)

    def test_play_launch_picks_the_piece(self):
        from eva_desk.motion.seq.card import Card
        from eva_desk.motion.seq.shaft import Shaft
        app = self.app()
        self.assertTrue(app.play_launch("FIREFOX", False, "MON"))
        self.assertTrue(app.play_launch("HADES", True, None))
        (p1, m1, c1), (p2, m2, c2) = app.motion.calls
        self.assertIsInstance(p1, Card)
        self.assertIsInstance(p2, Shaft)
        self.assertEqual((m1, m2), ("MON", "FOCUSED"))
        self.assertEqual((c1["app"], c1["workspace"]), ("FIREFOX", 2))
        self.assertRegex(c1["clock"], r"^\d\d:\d\d$")

    def test_switched_off_or_unavailable(self):
        app = self.app()
        app.cfg["motion"]["launch"] = False
        self.assertFalse(app.play_launch("X", False, "MON"))
        self.assertEqual(app.motion.calls, [])
        app.motion = None
        app.cfg["motion"]["launch"] = True
        self.assertFalse(app.play_launch("X", False, "MON"))

    def test_the_play_command(self):
        app = self.app()
        self.assertEqual(app.command("play card"), "ok")
        self.assertEqual(app.command("play shaft STEAM"), "ok")
        self.assertEqual(app.motion.calls[1][2]["app"], "STEAM")
        from eva_desk import motion
        names = list(motion.pieces())
        self.assertEqual(app.command("play nope"), f"unknown piece: nope ({', '.join(names)})")
        self.assertEqual(app.command("play"), "play: " + " | ".join(names))
        app.motion = None
        self.assertEqual(app.command("play card"), "motion is not available")

    def test_hyprland_plays_no_animation_of_its_own_over_it(self):
        self.assertIn("|pulse|motion|", (ROOT / "hypr" / "eva.lua").read_text())

    def test_a_new_window_gets_no_pulse_under_a_sequence_that_covers(self):
        # the window a launch opens lands under the card; its pulse would be drawn on top of it
        app, plays = self.app(), []
        app.overlays = {"pulse": type("Pulse", (), {"play": lambda s, *a: plays.append(a)})()}
        app.gdk_of = {"DP-1": "GDK"}
        app.hypr.state.update(clients=[{"address": "0xabc", "class": "kitty", "monitor": 0, "at": (100, 100), "size": (800, 600)}],
                              monitors=[{"id": 0, "name": "DP-1", "scale": 1, "x": 0, "y": 0}])
        app.motion.busy = True
        app._spawn_pulse("abc")
        self.assertEqual(plays, [])
        app.motion.busy = False
        app._spawn_pulse("abc")
        self.assertEqual(plays, [("GDK", 500.0, 400.0, 480.0)])
        app.motion = None                                                     # and with no player at all it is as before
        app._spawn_pulse("abc")
        self.assertEqual(len(plays), 2)


class FakePlayers:
    busy = False

    def __init__(self):
        self.calls, self.started, self.stopped, self.up = [], 0, [], {}

    def play(self, piece, mon, ctx, on_done=None, held=False):
        self.calls.append((type(piece).__name__, mon, ctx, held))
        self.up[mon] = piece
        return True

    def playing(self, mon):
        return self.up.get(mon)

    def start(self):
        self.started += 1

    def stop(self, name=None):
        self.stopped.append(name)
        self.up = {mon: piece for mon, piece in self.up.items() if name not in (None, piece.name)}

    def forget(self, alive):
        pass


def events_app(**motion):
    """An App with no windows: two monitors, DP-1 (the main one, focused) and DP-2."""
    from eva_desk.app import App
    from eva_desk.motion import triggers
    app = App.__new__(App)
    app.cfg = config.load("/nonexistent")
    app.cfg["motion"].update(motion)
    app.hypr, app.motion = FakeHypr(), FakePlayers()
    app.stages, app.bars, app.overlays, app.prev, app.launcher = {}, {}, {}, {}, None
    app.gdk_of = {"DP-1": "GDK-1", "DP-2": "GDK-2"}
    app.hypr.state = {"monitors": [{"id": 0, "name": "DP-1", "width": 3440, "height": 1440, "focused": True, "activeWorkspace": {"id": 1}},
                                   {"id": 1, "name": "DP-2", "width": 1080, "height": 1920, "focused": False, "activeWorkspace": {"id": 5}}],
                      "clients": [], "activeworkspace": {"id": 1}, "version": {"version": "0.56.0"}}
    app.res_state = app.music_state = None
    app.tracks = triggers.TrackWatch(0.0)
    app.later = []
    app._later = lambda ms, fn: app.later.append((ms, fn))
    app.schedule = lambda *a: None
    app.focused_gdk = lambda: "FOCUSED"
    return app


class EventsWiring(unittest.TestCase):
    def test_the_defaults_are_on(self):
        self.assertEqual(config.load("/nonexistent")["motion"],
                         {"launch": True, "boot": True, "wake": True, "berserk": True, "track": True, "track_corner": "bottom-left"})

    def test_boot_plays_once_per_session(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(os.environ, {"HYPRLAND_INSTANCE_SIGNATURE": "sig-1"}):
            marker, app = Path(tmp) / "eva-desk.boot", events_app()
            self.assertTrue(app._boot(marker))
            (name, mon, ctx, held), = app.motion.calls                         # the main monitor only
            self.assertEqual((name, mon, held), ("Boot", "GDK-1", False))
            self.assertEqual((ctx["outputs"], ctx["hyprland"], ctx["bar"]), (["3440×1440", "1080×1920"], "0.56", 56))
            self.assertEqual(marker.read_text().strip(), "sig-1")
            self.assertFalse(app._boot(marker))                                # eva-ctl reload: not again
            self.assertEqual(len(app.motion.calls), 1)
            with mock.patch.dict(os.environ, {"HYPRLAND_INSTANCE_SIGNATURE": "sig-2"}):           # the next session
                off = events_app(boot=False)
                self.assertFalse(off._boot(marker))                            # switched off: nothing plays,
                self.assertEqual((off.motion.calls, marker.read_text().strip()), ([], "sig-2"))   # but the session is marked
                none = events_app()
                none.motion = None
                marker.unlink()
                self.assertFalse(none._boot(marker))
                self.assertTrue(marker.exists() and none.boot_done)

    def test_boot_waits_for_a_monitor_to_play_on(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(os.environ, {"HYPRLAND_INSTANCE_SIGNATURE": "sig-1"}):
            marker, app = Path(tmp) / "eva-desk.boot", events_app()
            app.gdk_of = {}                                                    # at login the first refresh can come before any monitor is known
            self.assertFalse(app._boot(marker, now=1.0))
            self.assertFalse(marker.exists() or app.boot_done)                 # not marked: it tries again at the next refresh
            app.gdk_of = {"DP-1": "GDK-1"}
            self.assertTrue(app._boot(marker, now=2.0))
            self.assertTrue(marker.exists() and app.boot_done)
            marker.unlink()
            late = events_app()
            late.gdk_of = {}
            self.assertFalse(late._boot(marker, now=1.0))
            self.assertFalse(late._boot(marker, now=30.0))                     # twenty seconds on and still none: it gives up for this session
            self.assertTrue(marker.exists() and late.boot_done)
            self.assertEqual(late.motion.calls, [])

    def test_no_boot_over_a_game_or_a_fullscreen_window(self):
        game = {"class": "steam_app_42", "workspace": {"id": 9}, "fullscreen": 0, "mapped": True}
        full = {"class": "mpv", "workspace": {"id": 1}, "fullscreen": 2, "mapped": True}
        for client in (game, full):
            with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(os.environ, {"HYPRLAND_INSTANCE_SIGNATURE": "sig-1"}):
                marker, app = Path(tmp) / "eva-desk.boot", events_app()
                app.hypr.state["clients"] = [client]
                self.assertFalse(app._boot(marker, now=1.0))
                self.assertEqual((app.motion.calls, marker.exists(), app.boot_done), ([], True, True), client["class"])

    def test_the_bar_is_not_handed_what_its_switches_turned_off(self):
        class Bar:
            def __init__(self):
                self.got = {}

            def update(self, **state):
                self.got.update(state)
        sampler = types.SimpleNamespace(sample=lambda: {"cpu": 99, "mem_used": 1 << 30, "mem_total": 2 << 30, "net": {"kind": "lan", "down": 0}})
        app = events_app()
        app.cfg["bar"].update(music=False, resources=[])                       # the track card and the berserk limit still need both sources
        bar, app.sampler = Bar(), sampler
        app.bars["DP-1"] = bar
        app._on_music("Playing", "A", "X", now=50.0)
        self.assertTrue(app._resources())
        self.assertEqual(bar.got, {})                                          # but a bar that shows neither is told neither
        self.assertEqual((app.music_state["title"], app.res_state["cpu"]), ("A", 99))
        on = events_app()
        bar, on.sampler = Bar(), sampler
        on.bars["DP-1"] = bar
        on._on_music("Playing", "A", "X", now=50.0)
        on._resources()
        self.assertEqual((bar.got["music"]["title"], bar.got["resources"]["cpu"]), ("A", 99))

    def test_the_sampler_outlives_a_request_that_fails(self):
        app = events_app()
        app.sampler = types.SimpleNamespace(sample=lambda: {"cpu": 5, "mem_used": 1, "mem_total": 2, "net": {"kind": "lan", "down": 0}})

        def down(what):
            raise OSError("Hyprland does not answer")
        app.hypr.j = down
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertTrue(app._resources())                                  # the timer goes on

    def test_a_track_that_waits_for_the_gap_is_asked_for_again(self):
        app = events_app()
        app._on_music("Playing", "A", "X", now=50.0)
        self.assertTrue(app._track_settled(50.5))
        app._on_music("Playing", "B", "Y", now=52.0)
        asked = len(app.later)
        self.assertFalse(app._track_settled(52.5))                             # too soon after the last card
        self.assertEqual([ms for ms, _ in app.later[asked:]], [1000])          # so it asks again in a second
        self.assertTrue(app._track_settled(60.6))
        self.assertEqual([c[2]["title"] for c in app.motion.calls], ["A", "B"])

    def test_berserk_announces_itself_when_it_starts(self):
        app = events_app()
        app.cfg["overlays"].update(berserk=90, berserk_seconds=0)
        app._berserk_check(97, 40)
        (name, mon, ctx, held), = app.motion.calls
        self.assertEqual((name, mon, held, ctx["load"], ctx["seconds"]), ("Berserk", "GDK-1", False, "CPU 97%", 0))
        app._berserk_check(98, 40)                                             # still hot: it said so already
        self.assertEqual(len(app.motion.calls), 1)
        app._berserk_check(10, 10)                                             # cooled
        app._berserk_check(20, 95)                                             # and hot again, on memory this time
        self.assertEqual([c[2]["load"] for c in app.motion.calls], ["CPU 97%", "RAM 95%"])

    def test_berserk_and_the_track_card_stay_out_of_the_way(self):
        game = {"class": "steam_app_42", "workspace": {"id": 9}, "fullscreen": 0, "mapped": True}
        full = {"class": "mpv", "workspace": {"id": 1}, "fullscreen": 2, "mapped": True}

        def blocked(change):
            app = events_app()
            change(app)
            app.tracks.feed("Playing", "B", "Y", 50.0)
            return (app._announce_berserk(97, 40), app._track_settled(50.5), app.motion.calls if app.motion else [])
        self.assertEqual(blocked(lambda a: None)[:2], (1, True))               # nothing in the way: both play
        for change in (lambda a: a.hypr.state.update(clients=[game]),          # a game is open, on a workspace that is not showing
                       lambda a: a.hypr.state.update(clients=[full]),          # a fullscreen window on that monitor
                       lambda a: setattr(a.motion, "busy", True),              # a sequence that covers is playing
                       lambda a: setattr(a, "launcher", types.SimpleNamespace(visible=True)),
                       lambda a: a.overlays.update(power=types.SimpleNamespace(visible=True)),
                       lambda a: a.overlays.update(alttab=types.SimpleNamespace(visible=True)),
                       lambda a: a.cfg["motion"].update(berserk=False, track=False),
                       lambda a: setattr(a, "gdk_of", {}),
                       lambda a: setattr(a, "motion", None)):
            self.assertEqual(blocked(change), (0, False, []))

    def test_a_new_track_gets_a_card(self):
        app = events_app(track_corner="bottom-right")
        app.hypr.state["monitors"][0]["focused"], app.hypr.state["monitors"][1]["focused"] = False, True     # the side monitor has the focus
        app._on_music("Playing", "B", "", now=50.0)
        app._on_music("Playing", "B", "Y", now=50.1)
        self.assertEqual([ms for ms, _ in app.later], [450, 450])
        self.assertEqual(app.music_state, {"status": "Playing", "title": "B", "artist": "Y"})
        self.assertFalse(app._track_settled(50.3))                             # not settled yet
        self.assertTrue(app._track_settled(50.6))
        (name, mon, ctx, held), = app.motion.calls
        self.assertEqual((name, mon, held), ("Track", "GDK-1", False))         # on the main monitor all the same
        self.assertEqual((ctx["title"], ctx["artist"], ctx["corner"]), ("B", "Y", "bottom-right"))
        self.assertFalse(app._track_settled(51.0))                             # once

    def test_play_tries_any_of_the_six(self):
        app = events_app()
        for name in ("card", "shaft", "boot", "wake", "berserk", "track"):
            self.assertEqual(app.command(f"play {name}"), "ok", name)
        self.assertEqual([c[0] for c in app.motion.calls], ["Card", "Shaft", "Boot", "Wake", "Berserk", "Track"])
        self.assertTrue(all(c[1] == "FOCUSED" for c in app.motion.calls))
        self.assertEqual(app.motion.calls[4][2]["load"], "CPU 97%")            # nothing sampled yet
        self.assertEqual((app.motion.calls[5][2]["title"], app.motion.calls[5][2]["artist"]), ("TITLE", "ARTIST"))
        app.music_state = {"status": "Playing", "title": "Now", "artist": "Them"}
        app.command("play track")
        app.command("play track My own words")
        self.assertEqual([c[2]["title"] for c in app.motion.calls[6:]], ["Now", "My own words"])


def lock_app(**motion):
    """events_app(), with Hyprland saying the session is not locked."""
    from eva_desk.motion import triggers
    app = events_app(**motion)
    app.lock_watch = triggers.LockWatch()
    app.hypr.state["locked"] = {"locked": False}
    return app


class LockWiring(unittest.TestCase):
    def test_lock_always_starts_the_locker(self):
        app = lock_app()
        self.assertEqual((app.lock(), app.lock()), ("ok", "ok"))               # asked twice, started twice: the daemon never refuses a lock
        self.assertEqual(app.hypr.execs, ["hyprlock", "hyprlock"])
        for bare in (lock_app(wake=False), lock_app()):                        # with the sequence off, or with no player at all
            if bare.cfg["motion"]["wake"]:
                bare.motion = None
            self.assertEqual((bare.lock(), bare.hypr.execs), ("ok", ["hyprlock"]))
        none = lock_app()
        none.cfg["power"]["lock"] = ""
        self.assertEqual((none.lock(), none.hypr.execs), ("no lock command", []))

    def test_the_cover_goes_up_under_the_lock_screen_and_plays_when_it_closes(self):
        app = lock_app()
        app._watch_lock(100.0)                                                 # not locked: nothing, and it looks again in two seconds
        self.assertEqual((app.motion.calls, [ms for ms, _ in app.later]), ([], [2000]))
        app.hypr.state["locked"] = {"locked": True}                            # locked, by whatever started the lock screen
        app._watch_lock(102.0)
        (name, mon, ctx, held), = app.motion.calls
        self.assertEqual((name, mon, held), ("Wake", "GDK-1", True))           # the main monitor, held on its first frame
        self.assertEqual(app.later[-1][0], 500)                                # and it looks more often now, to catch the unlock
        app._watch_lock(102.5)
        app._watch_lock(3000.0)                                                # locked for a long while: the one cover stays
        self.assertEqual((len(app.motion.calls), app.motion.started, app.motion.stopped), (1, 0, []))
        app.hypr.state["locked"] = {"locked": False}                           # unlocked
        app._watch_lock(3600.0)
        self.assertEqual((app.motion.started, app.motion.stopped, app.later[-1][0]), (1, [], 2000))
        app._watch_lock(3602.0)
        self.assertEqual((len(app.motion.calls), app.motion.started), (1, 1))  # once

    def test_a_cover_is_put_back_when_its_monitor_comes_back(self):
        app = lock_app()
        app.hypr.state["locked"] = {"locked": True}
        app._watch_lock(10.0)
        app.motion.up.clear()                                                  # the output went away, and its player with it
        app.gdk_of["DP-1"] = "GDK-1-AGAIN"
        app._watch_lock(10.5)
        self.assertEqual([(c[0], c[1], c[3]) for c in app.motion.calls], [("Wake", "GDK-1", True), ("Wake", "GDK-1-AGAIN", True)])

    def test_the_watch_cannot_die_and_the_cover_cannot_stay(self):
        app = lock_app()
        app.hypr.state["locked"] = {"locked": True}
        app._watch_lock(10.0)

        def down(what):
            raise OSError("Hyprland does not answer")
        app.hypr.j = down
        with contextlib.redirect_stdout(io.StringIO()):
            app._watch_lock(10.5)                                              # a failed request: it looks again, and the cover waits
            self.assertEqual((app.motion.stopped, app.later[-1][0]), ([], 500))
            app._watch_lock(13.0)                                              # still no answer after two seconds: the cover goes
        self.assertEqual((app.motion.stopped, app.later[-1][0]), (["wake"], 2000))
        broken = lock_app()
        broken.hypr.state["locked"] = {"locked": True}
        broken.motion.play = mock.Mock(side_effect=RuntimeError("no surface"))
        with contextlib.redirect_stdout(io.StringIO()) as out:
            broken._watch_lock(10.0)                                           # putting the cover up fails: nothing is left up, and it looks again
        self.assertEqual((broken.motion.stopped, len(broken.later)), (["wake"], 1))
        self.assertIn("eva-desk: wake", out.getvalue())

    def test_no_watch_without_the_sequence(self):
        for app in (lock_app(wake=False), lock_app()):
            if app.cfg["motion"]["wake"]:
                app.motion = None
            app.hypr.state["locked"] = {"locked": True}
            app._watch_lock(1.0)
            self.assertEqual(app.later, [])
        self.assertEqual(lock_app(wake=False).motion.calls, [])

    def test_the_power_menu_and_eva_ctl_lock_go_through_it(self):
        from eva_desk import overlays as O
        app = lock_app()
        self.assertEqual(app.command("lock"), "ok")
        menu = O.PowerMenu.__new__(O.PowerMenu)
        menu.app, menu.cross, menu.hide = app, None, lambda: None
        menu._run("lock", "hyprlock")
        self.assertEqual(app.hypr.execs, ["hyprlock", "hyprlock"])
        menu._run("sleep", "systemctl suspend")                                # the other keys are as they were
        self.assertEqual(app.hypr.execs[-1], "systemctl suspend")
        bare = O.PowerMenu.__new__(O.PowerMenu)                                # an app with no lock(): the command, as before
        bare.app, bare.cross, bare.hide = types.SimpleNamespace(hypr=FakeHypr()), None, lambda: None
        bare._run("lock", "hyprlock")
        self.assertEqual(bare.app.hypr.execs, ["hyprlock"])

    def test_eva_ctl_lock_locks_without_the_daemon(self):
        with tempfile.TemporaryDirectory() as tmp:
            done = Path(tmp) / "locked"
            (Path(tmp) / "eva-desk").mkdir()
            (Path(tmp) / "eva-desk" / "eva.toml").write_text(f'[power]\nlock = "touch {done}"\n')
            env = dict(os.environ, XDG_RUNTIME_DIR=tmp, XDG_CONFIG_HOME=tmp, XDG_STATE_HOME=tmp)      # no daemon listens here
            r = subprocess.run([sys.executable, str(ROOT / "bin" / "eva-ctl"), "lock"], env=env, capture_output=True, text=True, timeout=60)
            self.assertEqual(r.returncode, 0, r.stderr)
            for _ in range(100):
                if done.exists():
                    break
                time.sleep(0.05)
            self.assertTrue(done.exists())                                     # the lock command ran all the same
            r = subprocess.run([sys.executable, str(ROOT / "bin" / "eva-ctl"), "status"], env=env, capture_output=True, text=True, timeout=60)
            self.assertEqual(r.returncode, 1)                                  # the other commands still say the daemon is not running

    def test_resume_from_sleep(self):
        app = lock_app()
        app._on_sleep(True)                                                    # going to sleep: nothing
        self.assertEqual(app.motion.calls, [])
        app._on_sleep(False)
        (name, mon, ctx, held), = app.motion.calls
        self.assertEqual((name, mon, held), ("Wake", "GDK-1", False))
        locked = lock_app()
        locked.hypr.state["locked"] = {"locked": True}
        locked._on_sleep(False)                                                # back onto a lock screen: its closing plays the sequence
        self.assertEqual(locked.motion.calls, [])
        off = lock_app(wake=False)
        off._on_sleep(False)
        self.assertEqual(off.motion.calls, [])
        bare = lock_app()
        bare.motion = None                                                     # no player: nothing to do, and nothing raised
        bare._on_sleep(False)

    def test_hearing_logind(self):
        app, bus = lock_app(), mock.Mock()
        with mock.patch("gi.repository.Gio.bus_get_sync", return_value=bus):
            app._watch_sleep()
        bus.set_exit_on_close.assert_called_once_with(False)                   # the system bus going away must not take the daemon with it
        self.assertEqual(bus.signal_subscribe.call_args[0][:4],
                         ("org.freedesktop.login1", "org.freedesktop.login1.Manager", "PrepareForSleep", "/org/freedesktop/login1"))
        off, quiet = lock_app(wake=False), mock.Mock()
        with mock.patch("gi.repository.Gio.bus_get_sync", return_value=quiet):
            off._watch_sleep()                                                 # nothing to play after sleep: nothing to hear
        quiet.signal_subscribe.assert_not_called()


class LockWithRealPlayers(NoCompositor):
    def test_lock_cover_monitor_replaced_unlock(self):
        from eva_desk.motion.player import Players
        app, main, again = lock_app(), FakeMonitor(3440, 1440), FakeMonitor(3440, 1440)
        app.motion = Players(app, make=lambda a: player())
        app.gdk_of = {"DP-1": main, "DP-2": FakeMonitor(1080, 1920)}
        app.hypr.state["locked"] = {"locked": True}
        app._watch_lock(10.0)
        cover = app.motion.by_monitor[main]
        self.assertTrue(cover.held and cover.win.visible and cover.piece.name == "wake")
        self.assertEqual((set(app.motion.by_monitor), cover.timers), ({main}, []))                # the main monitor only; no safety runs while it waits
        app.gdk_of["DP-1"] = again                                             # the output dropped and came back as a new monitor
        app.motion.forget([again])
        self.assertFalse(cover.win.visible)
        app._watch_lock(10.5)
        cover = app.motion.by_monitor[again]
        self.assertTrue(cover.held and cover.piece.name == "wake")
        app.hypr.state["locked"] = {"locked": False}
        app._watch_lock(11.0)                                                  # unlocked: it plays, with its safety
        self.assertEqual((cover.held, [ms for ms, _ in cover.timers]), (False, [2100]))
        cover.advance(0.0)
        cover.advance(1.2)
        self.assertFalse(app.motion.busy or cover.win.visible)


# ---------------------------------------------------------------- standby
def _installed(*names):
    import importlib.util
    return all(importlib.util.find_spec(n) is not None for n in names)


@unittest.skipUnless(_installed("numpy", "scipy", "PIL"), "tools/gen/prep_art.py needs numpy, scipy and Pillow")
class ArtTest(unittest.TestCase):
    def prep(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location("prep_art", ROOT / "tools" / "gen" / "prep_art.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod

    def picture(self, eyes, lights=()):
        """A dark grey 320x200 frame with a pale figure, green eyes at `eyes` and duller green lights at `lights`."""
        import numpy as np
        im = np.full((200, 320, 3), 0.05)
        im[30:190, 120:220] = (0.16, 0.12, 0.2)                # the figure
        for (x, y) in eyes:
            im[y - 2:y + 3, x - 5:x + 6] = (0.2, 1.0, 0.3)
        for (x, y) in lights:
            im[y - 6:y + 7, x - 6:x + 7] = (0.3, 0.75, 0.35)
        return im

    def test_the_layers_add_back_to_the_picture_and_the_eye_is_found(self):
        import numpy as np
        prep = self.prep()
        im = prep.black_floor(self.picture([(170, 60)]))
        self.assertLess(im[5, 5].max(), 0.001)                 # the ground is true black now
        body, eye, eyes = prep.split(im, "profile")
        self.assertLess(np.abs(body + eye - im).max(), 1e-9)
        self.assertEqual(len(eyes), 1)
        self.assertAlmostEqual(eyes[0][0], 170 / 320, delta=0.01)
        self.assertAlmostEqual(eyes[0][1], 60 / 200, delta=0.01)
        self.assertEqual(eye[150, 40].max(), 0)                # the eye layer is the eye and nothing else
        self.assertLess(body[60, 170, 1], 0.1)                 # and the body has lost its glow

    def test_a_front_view_has_two_eyes_and_a_whole_figure_looks_in_the_head(self):
        prep = self.prep()
        _, _, eyes = prep.split(prep.black_floor(self.picture([(152, 60), (188, 60)])), "front")
        self.assertEqual([round(x * 320) for x, _ in eyes], [152, 188])
        _, _, eyes = prep.split(prep.black_floor(self.picture([(152, 60), (188, 60)])), "profile")
        self.assertEqual(len(eyes), 1)                         # a side view has the one
        _, _, eyes = prep.split(prep.black_floor(self.picture([(170, 50)], lights=[(170, 120)])), "full")
        self.assertEqual(len(eyes), 1)
        self.assertAlmostEqual(eyes[0][1], 50 / 200, delta=0.02)          # the chest light is larger and lower; it is not the eye

    def test_a_picture_with_no_eye(self):
        import numpy as np
        prep = self.prep()
        im = prep.black_floor(self.picture([]))
        body, eye, eyes = prep.split(im, "front")
        self.assertEqual((eyes, float(eye.max())), ([], 0.0))
        self.assertLess(np.abs(body - im).max(), 1e-9)


class ArtFiles(unittest.TestCase):
    def test_the_pictures_the_desk_ships(self):
        import json
        from eva_desk import gtkutil  # noqa: F401
        from gi.repository import Gdk
        art = json.loads((ROOT / "assets/motion/art.json").read_text())
        self.assertEqual(sorted(art), ["front", "full", "profile"])
        self.assertEqual([len(art[n]["eyes"]) for n in ("profile", "front", "full")], [1, 2, 1])
        for name, a in art.items():
            for layer in ("body", "eye"):
                tex = Gdk.Texture.new_from_filename(str(ROOT / f"assets/motion/{name}_{layer}.jpg"))
                self.assertEqual((tex.get_width(), tex.get_height()), (a["w"], a["h"]), name)
            self.assertTrue(all(0 < x < 1 and 0 < y < 1 for x, y in a["eyes"]), name)
        self.assertLess(sum(p.stat().st_size for p in (ROOT / "assets/motion").iterdir()), 1_500_000)


class StandbyTest(unittest.TestCase):
    def setUp(self):
        import json
        from eva_desk.motion import render
        from eva_desk.motion.amb import standby
        self.S, self.render, self.FIX = standby, render, render.fixture_ctx()
        self.ART = json.loads((ROOT / "assets/motion/art.json").read_text())

    def loop(self):
        """A loop that finds no pictures: the field alone."""
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        loop = self.S.StandbyLoop(folder=tmp.name)
        with contextlib.redirect_stdout(io.StringIO()):
            loop.shots()                                       # it says once what it could not find
        return loop

    def real(self):
        return self.S.StandbyLoop()

    def test_the_pure_parts(self):
        S = self.S
        four = list(S.ORDER)
        self.assertEqual([S.shot_at(t, four)[0] for t in (0, 14.99, 15, 44.99, 45, 60, 75)],
                         ["profile", "profile", "field", "tilt", "stare", "profile", "field"])
        self.assertEqual(S.shot_at(52.5, four), ("stare", 0.5, 3))
        self.assertEqual(S.shot_at(52.5, ["field"]), ("field", 0.5, 0))
        self.assertAlmostEqual(S.breathe(0), 0.70)
        self.assertAlmostEqual(max(S.breathe(i / 50) for i in range(300)), 1.0, places=3)
        self.assertAlmostEqual(min(S.breathe(i / 50) for i in range(300)), 0.40, places=3)
        for t, where in ((0, -0.3), (4.5, 0.5), (9, -0.3), (8.99, 1.2982)):
            self.assertAlmostEqual(S.passing(t), where, places=3)
        self.assertEqual((S.tilt(0.0), S.tilt(0.04), S.tilt(0.74), S.tilt(1.0)), (1.0, 1.0, 0.0, 0.0))
        self.assertEqual(S.fold(0.0), (1.0, 1.0, False))
        self.assertAlmostEqual(S.fold(0.02)[1], 1 - 0.98 / 3)
        self.assertAlmostEqual(S.fold(0.06)[1], 1 - 0.98 * 2 / 3)
        self.assertEqual(S.fold(0.10)[0], 1.0)
        self.assertAlmostEqual(S.fold(0.10)[1], 0.02)
        self.assertTrue(S.fold(0.10)[2])
        self.assertAlmostEqual(S.fold(0.165)[0], 0.875)
        self.assertEqual(S.fold(0.19)[0], 0.0)

    def test_the_registry_keeps_loops_apart(self):
        from eva_desk import motion
        self.assertEqual(list(motion.loops())[0], "standby")
        self.assertFalse(set(motion.loops()) & set(motion.pieces()))           # eva-ctl play must never be handed a piece with no end
        self.assertTrue(all(cls().length is None for cls in motion.loops().values()))
        self.assertEqual(list(motion.everything()), list(motion.pieces()) + list(motion.loops()))
        self.assertEqual((motion.loops()["standby"]().length, self.loop().shots()), (None, ["field"]))

    def test_the_field(self):
        render, FIX = self.render, self.FIX
        f = render.frame(self.loop(), 3.0, 1720, 720, FIX)
        self.assertEqual(set(grid(f)), {255})                  # the whole frame is covered
        self.assertTrue(near(px(f, 860, 20), INK) and near(px(f, 860, 700), INK))        # the bars
        self.assertEqual(pink(f), 0)
        node = render.build(self.loop(), 3.0, 1720, 720, FIX)
        self.assertTrue({180.0, 150.0} <= glyph_sizes(node), glyph_sizes(node))          # the clock (240 px) and 待機 (200 px), in points
        self.assertFalse(same(f, render.frame(self.loop(), 4.0, 1720, 720, FIX)))        # it moves

    def test_on_a_narrower_frame_the_field_keeps_its_type_apart(self):
        def lit(f, s, x0, x1, y0, y1):                         # bright pixels in a box given in design px
            return sum(max(px(f, x * s, y * s)[:3]) > 150 for x in range(x0, x1, 6) for y in range(y0, y1, 6))
        f = self.render.frame(self.loop(), 3.0, 1920, 1080, self.FIX)            # 16:9: a frame 1280 wide
        self.assertEqual(lit(f, 1.5, 520, 600, 250, 440), 0)                     # between 待機 and the clock
        self.assertGreater(lit(f, 1.5, 700, 1170, 250, 440), 50)                 # the clock is there, smaller
        s = 1080 / 1280
        f = self.render.frame(self.loop(), 3.0, 1080, 1920, self.FIX)            # upright: the clock goes under 待機
        mid = round(1920 / s / 2)
        self.assertGreater(lit(f, s, 104, 500, mid - 300, mid - 130), 50)        # 待機
        self.assertEqual(lit(f, s, 520, 1270, mid - 300, mid - 100), 0)          # nothing beside it
        self.assertGreater(lit(f, s, 104, 760, mid, mid + 200), 50)              # the clock, below

    def test_the_clock_shows_what_it_is_given(self):
        render, FIX = self.render, self.FIX
        a = render.frame(self.loop(), 3.0, 1720, 720, {**FIX, "second": 10})
        b = render.frame(self.loop(), 3.0, 1720, 720, {**FIX, "second": 50})
        c = render.frame(self.loop(), 3.0, 1720, 720, {**FIX, "clock": "09:05"})
        self.assertFalse(same(a, b) or same(a, c))

    def test_nothing_is_made_after_the_first_frame(self):
        from eva_desk import gtkutil  # noqa: F401
        from gi.repository import Gtk
        from eva_desk.motion.kit import Kit
        for loop, times in ((self.loop(), (2.0, 2.5, 9.0, 13.9)),             # the ring grows through all of these
                            (self.real(), (1.0, 8.0, 14.0)), (self.real(), (31.0, 38.0, 44.0)), (self.real(), (46.0, 52.0, 59.0))):
            store, sizes = {}, []
            for t in times:
                kit = Kit(Gtk.Snapshot(), 1720, 720, 1.0, store)
                loop.paint(kit, t, self.FIX)
                kit.close()
                sizes.append(len(store))
            self.assertEqual(len(set(sizes)), 1, (times, sizes))

    def test_the_type_keeps_its_size(self):
        loop, sizes = self.real(), set()
        for i in range(120):                                   # a whole lap: the cameras move, the type does not grow with them
            sizes |= glyph_sizes(self.render.build(loop, 60 * (i + 0.5) / 120, 1720, 720, self.FIX))
        self.assertLessEqual(len(sizes), 16, sorted(sizes))

    def test_it_folds_away(self):
        render, FIX, loop = self.render, self.FIX, self.loop()
        f = render.frame(loop, 3.0, 1720, 720, {**FIX, "leaving": 0.02})
        self.assertEqual((alpha(f, 860, 100), alpha(f, 860, 360), alpha(f, 860, 620)), (0, 255, 0))      # two thirds of the height are left
        f = render.frame(loop, 3.0, 1720, 720, {**FIX, "leaving": 0.10})
        self.assertTrue(near(px(f, 860, 360), BONE) and near(px(f, 20, 360), BONE))                      # the line, the whole width
        self.assertEqual((alpha(f, 860, 340), alpha(f, 860, 380)), (0, 0))
        f = render.frame(loop, 3.0, 1720, 720, {**FIX, "leaving": 0.165})
        self.assertEqual((alpha(f, 60, 360), alpha(f, 860, 360)), (0, 255))                              # the line closes from both ends
        self.assertIsNone(box(render.frame(loop, 3.0, 1720, 720, {**FIX, "leaving": 0.19})))
        self.assertIsNone(box(render.frame(loop, 3.0, 1720, 720, {**FIX, "leaving": 5.0})))
        f = render.frame(loop, 3.0, 1720, 720, {**FIX, "leaving": 0.0})                                  # the first frame of the exit is still whole
        self.assertEqual(set(grid(f)), {255})

    def test_it_paints_with_nothing_and_with_odd_inputs(self):
        for ctx in ({}, {"second": 59.99}, {"second": 75}, {"second": -1}, {"second": "soon"}, {"clock": "9:05", "readings": []},
                    {"readings": ["X" * 400]}, {"date": "مرحبا"}, {"clock": None, "date": None, "readings": None}):
            for w, h in ((1720, 720), (1920, 1080), (1080, 1920)):
                f = self.render.frame(self.loop(), 3.0, w, h, ctx)
                self.assertEqual((set(grid(f)), pink(f)), ({255}, 0), (ctx, w, h))

    def test_a_week_in(self):
        t = 7 * 86400 + 3.0
        f = self.render.frame(self.loop(), t, 1720, 720, self.FIX)
        self.assertEqual((set(grid(f)), pink(f)), ({255}, 0))
        self.assertTrue(same(f, self.render.frame(self.loop(), t, 1720, 720, self.FIX)))

    # ------------------------------------------------------------ the three pictures
    def test_the_four_shots(self):
        render, FIX, loop = self.render, self.FIX, self.real()
        self.assertEqual(loop.shots(), ["profile", "field", "tilt", "stare"])
        sizes = {1.0: 150, 16.0: 240, 31.0: 220, 46.0: 104}                        # the clock moves place and size every shot
        for t, clock in sizes.items():
            node = render.build(loop, t, 1720, 720, FIX)
            self.assertIn(clock * 0.75, glyph_sizes(node), t)                      # px to points
            widths = set(texture_widths(node))
            self.assertEqual(1792 in widths, t in (1.0, 46.0), t)
            self.assertEqual(896 in widths, t == 31.0, t)
            f = render.frame(loop, t, 1720, 720, FIX)
            self.assertEqual((set(grid(f)), pink(f)), ({255}, 0), t)
            self.assertTrue(near(px(f, 860, 20), INK) and near(px(f, 860, 700), INK), t)       # the bars lie over the picture

    def test_the_picture_is_nearly_all_black(self):
        f = self.render.frame(self.real(), 1.0, 1720, 720, {})
        data, lit, n = bytes(f.get_data()), 0, 0
        for i in range(0, len(data), 4 * 97):
            lit += max(data[i:i + 3]) > 60
            n += 1
        self.assertLess(lit / n, 0.25)
        self.assertGreater(lit, 20)                                                # but the Eva is there

    def test_the_eyes_breathe(self):
        from eva_desk.motion.kit import cover_box
        loop, a = self.real(), self.ART["profile"]
        ex, ey = a["eyes"][0]

        def eye(t):                                            # the green at the eye; the camera pushes in on it, so it stays put
            ix, iy, iw, ih = cover_box(a["w"], a["h"], 0, 0, 1720, 720, 1 + 0.07 * t / 15, ex, ey)
            return px(self.render.frame(loop, t, 1720, 720, self.FIX), ix + ex * iw, iy + ey * ih)[1]
        self.assertGreater(eye(1.5), eye(4.5) + 30)            # breathe is 1.0 at 1.5 s and 0.4 at 4.5 s

    def test_the_light_passes(self):
        loop = self.real()

        def blue(t, x0, x1):                                   # how much bluer than the ink the head is: the armour and its rim
            data, stride = bytes(self.render.frame(loop, t, 1720, 720, self.FIX).get_data()), 1720 * 4
            return sum(max(0, data[y * stride + x * 4] - INK[0]) for y in range(60, 660, 7) for x in range(x0, x1, 7))
        ex = self.ART["profile"]["eyes"][0][0]
        x0, x1 = int(1720 * ex) - 200, int(1720 * ex) + 200    # the head
        lit = 9 * (ex + 0.3) / 1.6                             # when the band's middle is on the eye
        dark = lit + 6                                         # one breath later, so the eye glows the same, and the light is off the head
        self.assertGreater(blue(lit, x0, x1), 1.3 * blue(dark, x0, x1))

    def test_a_picture_that_is_missing_or_broken_drops_its_shot(self):
        src = ROOT / "assets/motion"
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            for p in src.iterdir():
                shutil.copy(p, tmp / p.name)
            (tmp / "full_eye.jpg").unlink()
            (tmp / "front_body.jpg").write_bytes(b"not a picture")
            with contextlib.redirect_stdout(io.StringIO()) as out:
                loop = self.S.StandbyLoop(folder=tmp)
                self.assertEqual(loop.shots(), ["profile", "field"])
                self.assertEqual(loop.shots(), ["profile", "field"])
                loop.release()
                self.assertEqual(loop.shots(), ["profile", "field"])                 # loaded again, and not said again
                f = self.render.frame(loop, 31.0, 1720, 720, self.FIX)               # what would have been the tilt
            self.assertEqual(out.getvalue().count("eva-desk: standby:"), 2, out.getvalue())      # each said once
            self.assertEqual((set(grid(f)), pink(f)), ({255}, 0))
            self.assertEqual(self.S.shot_at(31.0, loop.shots())[0], "profile")       # two shots: a lap is thirty seconds
            (tmp / "art.json").write_text("{")
            with contextlib.redirect_stdout(io.StringIO()) as out:
                self.assertEqual(self.S.StandbyLoop(folder=tmp).shots(), ["field"])
            self.assertEqual(len(out.getvalue().splitlines()), 1)
            (tmp / "art.json").write_text('{"profile": {"w": 1792, "h": 768}, "front": 3, "full": {"eyes": "no"}}')
            (tmp / "front_body.jpg").write_bytes((src / "front_body.jpg").read_bytes())
            with contextlib.redirect_stdout(io.StringIO()):
                loop = self.S.StandbyLoop(folder=tmp)
                self.assertEqual(loop.shots(), ["profile", "field"])                 # an entry with no eyes is fine; nonsense is not
                self.assertEqual(pink(self.render.frame(loop, 1.0, 1720, 720, {})), 0)

    def test_every_shot_at_every_size(self):
        loop = self.real()
        for w, h in ((3440, 1440), (1920, 1080), (1080, 1920)):
            for t in (1.0, 16.0, 31.0, 46.0):
                f = self.render.frame(loop, t, w, h, self.FIX)
                self.assertEqual((set(grid(f)), pink(f)), ({255}, 0), (w, h, t))
                self.assertTrue(same(f, self.render.frame(loop, t, w, h, self.FIX)), (w, h, t))

    def test_on_a_tall_frame_the_clock_stands_clear_of_the_picture(self):
        s = 1080 / 1280                                        # px to the design px on a 1080x1920 frame
        H = 1920 / s
        band = 0.38 * (H - 0.5625 * 1280)
        node = self.render.build(self.real(), 1.0, 1080, 1920, self.FIX)
        self.assertIn(round(150 * 0.75 * s, 2), glyph_sizes(node))                 # the profile's clock, in points
        f = self.render.frame(self.real(), 1.0, 1080, 1920, {})
        self.assertTrue(near(px(f, 540, (band - 60) * s), INK))                    # over the band there is only ink

    def test_release_drops_the_pictures_and_it_paints_again(self):
        loop = self.real()
        self.render.frame(loop, 1.0, 1720, 720, self.FIX)
        loop.release()
        self.assertIsNone(loop.art)
        self.assertEqual(loop.shots(), ["profile", "field", "tilt", "stare"])
        self.assertEqual(pink(self.render.frame(loop, 1.0, 1720, 720, self.FIX)), 0)


class StandbyTriggers(unittest.TestCase):
    def setUp(self):
        from eva_desk.motion import triggers
        self.T = triggers

    def test_what_blocks_standby(self):
        T = self.T
        mons = [{"id": 0, "name": "DP-1", "activeWorkspace": {"id": 1}}, {"id": 1, "name": "DP-2", "activeWorkspace": {"id": 5}}]
        game = {"class": "steam_app_1145360", "workspace": {"id": 9}, "monitor": 0, "fullscreen": 0}      # on a workspace nobody is looking at
        full = {"class": "mpv", "workspace": {"id": 5}, "monitor": 1, "fullscreen": 2}                    # on the other monitor
        term = {"class": "kitty", "workspace": {"id": 1}, "monitor": 0, "fullscreen": 0}
        pats = ["^steam_app_", "^gamescope$"]
        self.assertEqual(T.standby_blocked(mons, [term], pats, False), "")
        self.assertEqual(T.standby_blocked(mons, [term, game], pats, False), "game")
        self.assertEqual(T.standby_blocked(mons, [term, full], pats, False), "fullscreen")
        self.assertEqual(T.standby_blocked(mons, [term, game, full], pats, True), "locked")
        self.assertEqual(T.standby_blocked(mons, [term], pats, None), "")
        self.assertEqual(T.standby_blocked(None, None, pats, None), "")

    def test_travel(self):
        tr = self.T.Travel()
        self.assertFalse(tr.moved(500, 500, 0.0))              # the layer came up under a resting pointer
        self.assertFalse(tr.moved(504, 503, 0.1))              # 5 px
        self.assertFalse(tr.moved(506, 505, 0.2))              # 7.8 px
        self.assertTrue(tr.moved(507, 506, 0.3))               # 9.2 px
        tr = self.T.Travel()                                   # a mouse on a desk that shakes: a pixel every few seconds
        self.assertFalse(any(tr.moved(500 + i, 500, 3.0 * i) for i in range(40)))
        tr = self.T.Travel()                                   # a slow hand is still a hand
        self.assertTrue(any(tr.moved(500 + i, 500, 0.2 * i) for i in range(12)))

    def test_readings(self):
        T = self.T
        res = {"cpu": 7, "mem": "9.8G", "mem_pct": 31, "net": "lan", "down": "340K", "show": []}
        self.assertEqual(T.readings(res), ["MAGI·1 CPU 07%", "MAGI·2 RAM 9.8G", "MAGI·3 LAN ↓340K"])
        self.assertEqual(T.readings({**res, "cpu": 100, "net": "wifi"})[::2], ["MAGI·1 CPU 100%", "MAGI·3 WIFI ↓340K"])
        self.assertEqual(T.readings({**res, "cpu": 41.6, "net": ""})[::2], ["MAGI·1 CPU 42%", "MAGI·3 NET ↓340K"])
        self.assertEqual((T.readings(None), T.readings({})), ([], []))


def ambient(fps=30, keyboard="exclusive"):
    """An AmbientLayer with no window behind it; its timers and its keyboard mode are lists to read."""
    from eva_desk.motion.player import AmbientLayer
    a = AmbientLayer.__new__(AmbientLayer)
    a.app, a.win, a.view = object(), FakeWin(), FakeView()
    a.fps, a.mode = fps, keyboard
    a.setup()
    a.timers, a.cancelled, a.afters, a.keyboard = [], [], [], []
    a._every = lambda ms, fn: a.timers.append((ms, fn)) or len(a.timers)
    a._cancel = a.cancelled.append
    a._after = lambda ms, fn: a.afters.append((ms, fn))
    a._keyboard = a.keyboard.append
    return a


def screens():
    """(a Standby whose layers are ambient() and whose clock is its `now`, a piece to show)."""
    from eva_desk.motion.player import Standby
    s = Standby(object(), make=lambda app: ambient(), clock=lambda: s.now)
    s.now = 0.0
    return s, dummy()


class AmbientTest(NoCompositor):
    def test_it_repaints_from_a_timer_at_the_time_it_is_told(self):
        a, piece, asked = ambient(fps=30), dummy(), []
        self.assertTrue(a.play(piece, MON, lambda: asked.append(1) or {"clock": "22:44"}, 100.0))
        self.assertTrue(a.win.visible and a.up)
        self.assertEqual(([ms for ms, _ in a.timers], a.keyboard), ([33], ["exclusive"]))
        self.assertFalse(a.win.surface.region.is_empty())      # it takes the pointer
        self.assertEqual((a.at, a.ctx, len(asked)), (0.0, {"clock": "22:44"}, 1))        # the first frame has its inputs
        a.beat(107.5)
        self.assertEqual((a.at, a.ctx, len(asked)), (7.5, {"clock": "22:44"}, 2))
        a.hide()
        self.assertEqual((a.win.visible, a.up, a.cancelled, piece.released), (False, False, [1], 0))     # the piece is not the layer's to release
        a.beat(108.0)                                          # a beat that was already on its way
        self.assertEqual(len(asked), 2)

    def test_no_monitor_and_a_piece_that_cannot_prepare(self):
        a = ambient()
        self.assertFalse(a.play(dummy(), None, dict, 0.0))
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertFalse(a.play(dummy(boom="prepare"), MON, dict, 0.0))
        self.assertEqual((a.win.visible, a.up, a.timers), (False, False, []))

    def test_leaving(self):
        a, seen, hidden = ambient(), [], []
        a.play(dummy(), MON, dict, 0.0)
        a.on_poke = lambda layer, kind, x, y: seen.append(kind)
        a.on_hidden = hidden.append
        a.poke("key")
        a.leave(50.0, 0.19)
        self.assertTrue(a.leaving and a.up)
        self.assertTrue(a.win.surface.region.is_empty())       # the pointer goes through from now on
        self.assertEqual(a.keyboard[-1], "none")
        self.assertEqual(a.timers[-1][0], 8)
        a.poke("key")                                          # what comes now is not for it
        self.assertEqual(seen, ["key"])
        a.beat(50.1)
        self.assertAlmostEqual(a.ctx["leaving"], 0.1)
        self.assertTrue(a.win.visible)
        a.leave(50.15, 0.19)                                   # a second leave does not start the fold again
        a.beat(50.2)
        self.assertFalse(a.win.visible or a.up or a.leaving)
        self.assertEqual(hidden, [a])

    def test_a_leave_ends_even_if_the_timer_never_runs(self):
        a = ambient()
        a.play(dummy(), MON, dict, 0.0)
        a.leave(50.0, 0.19)
        ms, fn = a.afters[-1]
        self.assertEqual(ms, 340)
        fn()
        self.assertFalse(a.win.visible)
        a.play(dummy(), MON, dict, 0.0)                        # and a late one from an old run does not hide the next
        fn()
        self.assertTrue(a.win.visible)
        self.assertEqual(a.keyboard[-1], "exclusive")
        self.assertFalse(a.win.surface.region.is_empty())

    def test_a_piece_that_raises_is_taken_down(self):
        from eva_desk import gtkutil  # noqa: F401
        from gi.repository import Gtk
        a, broke = ambient(), []
        a.on_broken = broke.append
        a.play(dummy(boom="paint"), MON, dict, 0.0)
        with contextlib.redirect_stdout(io.StringIO()) as out:
            a._paint(Gtk.Snapshot(), 1720, 720)
            a._paint(Gtk.Snapshot(), 1720, 720)                # nothing more is painted
        self.assertEqual(out.getvalue().count("boom"), 1)
        self.assertTrue(a.win.visible)                         # GTK is in the middle of drawing that window
        for ms, fn in a.afters:
            fn()
        self.assertEqual((a.win.visible, broke), (False, [a]))

    def test_inputs_that_raise_take_it_down_too(self):
        a, broke = ambient(), []
        a.on_broken = broke.append
        a.play(dummy(), MON, dict, 0.0)
        a.inputs = lambda: 1 / 0
        with contextlib.redirect_stdout(io.StringIO()):
            a.beat(1.0)
        self.assertEqual((a.win.visible, a.up, broke), (False, False, [a]))

    def test_it_paints_the_piece_at_its_time(self):
        from eva_desk import gtkutil  # noqa: F401
        from gi.repository import Gtk
        a, piece = ambient(), dummy()
        piece.length = None                                    # a loop
        a.play(piece, MON, lambda: {"clock": "22:44"}, 0.0)
        a.beat(3.0)
        piece.kits.clear()
        seen = []
        piece.paint = lambda kit, t, ctx: seen.append((t, ctx, kit.W, kit.H))
        a._paint(Gtk.Snapshot(), 1720, 720)
        self.assertEqual(seen, [(3.0, {"clock": "22:44"}, 1720.0, 720.0)])


class StandbyScreens(NoCompositor):
    def test_one_clock_on_every_monitor(self):
        s, piece = screens()
        s.now = 100.0
        self.assertTrue(s.start(piece, [MON, MON2], dict))
        self.assertEqual((s.up, s.monitors()), (True, [MON, MON2]))
        self.assertEqual({layer.epoch for layer in s.layers()}, {100.0})
        self.assertEqual({layer.keyboard[-1] for layer in s.layers()}, {"exclusive"})
        s.now = 130.0
        self.assertTrue(s.start(piece, [MON, MON2], dict))     # already up: the clock is not restarted
        self.assertEqual({layer.epoch for layer in s.layers()}, {100.0})

    def test_what_ends_it(self):
        s, piece = screens()
        ended = []
        s.on_end = lambda: ended.append(1)
        s.start(piece, [MON, MON2], dict)
        one, two = s.layers()
        s.now = 10.0
        s.poke(one, "motion", 500, 500)                        # the pointer was resting there
        s.poke(two, "motion", 40, 40)
        s.now = 10.2
        s.poke(one, "motion", 503, 503)
        self.assertTrue(s.up and not one.leaving)
        s.poke(one, "motion", 520, 500)                        # that is a hand
        self.assertTrue(one.leaving and two.leaving)           # everywhere at once
        self.assertEqual((ended, piece.released), ([], 0))     # it is still folding
        for layer in (one, two):
            layer.beat(10.2 + 0.2)
        self.assertEqual((s.up, ended, piece.released), (False, [1], 1))
        for kind in ("key", "click"):
            s.start(piece, [MON, MON2], dict)
            s.poke(s.layers()[1], kind)
            self.assertTrue(all(layer.leaving for layer in s.layers()), kind)
            s.end(at_once=True)                                # at once, also in the middle of a fold
            self.assertFalse(s.up)
        self.assertEqual((len(ended), piece.released), (3, 3))
        s.end()
        s.end(at_once=True)                                    # ending what is not up does nothing
        self.assertEqual(len(ended), 3)

    def test_the_pointer_rests_anew_on_each_run(self):
        s, piece = screens()
        s.start(piece, [MON], dict)
        one, = s.layers()
        s.poke(one, "motion", 500, 500)
        s.end(at_once=True)
        s.now = 0.5
        s.start(piece, [MON], dict)
        s.poke(one, "motion", 900, 900)                        # where it rests now: the first report of this run
        self.assertTrue(s.up and not one.leaving)

    def test_it_starts_where_it_can(self):
        s, piece = screens()
        self.assertFalse(s.start(piece, [], dict))
        self.assertEqual(piece.released, 1)
        with contextlib.redirect_stdout(io.StringIO()):
            bad = dummy(boom="prepare")
            self.assertFalse(s.start(bad, [MON, MON2], dict))
        self.assertEqual((s.up, bad.released), (False, 1))

    def test_a_layer_that_cannot_paint_ends_it_everywhere(self):
        from eva_desk import gtkutil  # noqa: F401
        from gi.repository import Gtk
        s, _ = screens()
        piece, ended = dummy(boom="paint"), []
        s.on_end = lambda: ended.append(1)
        s.start(piece, [MON, MON2], dict)
        one, two = s.layers()
        with contextlib.redirect_stdout(io.StringIO()):
            one._paint(Gtk.Snapshot(), 1720, 720)
        for ms, fn in one.afters:
            fn()
        self.assertFalse(s.up or one.win.visible or two.win.visible)
        self.assertEqual((piece.released, ended), (1, [1]))

    def test_a_piece_that_cannot_release_still_ends(self):
        s, piece = screens()
        piece.release = lambda: 1 / 0
        s.start(piece, [MON], dict)
        with contextlib.redirect_stdout(io.StringIO()):
            s.end(at_once=True)
        self.assertFalse(s.up)

    def test_forget(self):
        s, piece = screens()
        s.start(piece, [MON, MON2], dict)
        gone = s.layers()[1]
        s.forget([MON])                                        # its monitor went away while it was up
        self.assertEqual((len(s.layers()), gone.win.visible, s.up, s.monitors()), (1, False, True, [MON]))
        s.end(at_once=True)
        s.forget([])
        self.assertEqual(s.layers(), [])


class FakeStandby:
    def __init__(self):
        self.starts, self.ends, self.up, self.on = [], [], False, []

    def start(self, piece, monitors, inputs):
        if not self.up:
            self.starts.append((piece, list(monitors), inputs))
            self.on = list(monitors)
        self.up = True
        return bool(self.on)

    def end(self, at_once=False):
        if self.up:
            self.ends.append(at_once)
        self.up = False

    def monitors(self):
        return self.on if self.up else []

    def forget(self, alive):
        pass


class FakePanel:
    visible = True

    def __init__(self):
        self.hidden = self.closed = 0

    def hide(self):
        self.hidden += 1

    def close(self):
        self.closed += 1


def standby_app(**standby):
    """lock_app(), with a standby that only notes what it is told."""
    app = lock_app()
    app.cfg["standby"].update(standby)
    app.standby, app.idle, app.panels = FakeStandby(), None, {}
    return app


class StandbyWiring(unittest.TestCase):
    def setUp(self):
        self.monitors = {"DP-1": "GDK-1", "DP-2": "GDK-2"}                     # what GTK knows: every monitor, not only the main one
        self.stale = []                                                        # never the real one: it reads this machine's state folder and signals
        for target, fake in (("eva_desk.gtkutil.monitors", lambda: dict(self.monitors)),
                             ("eva_desk.sources.idle.end_stale", lambda folder, **kw: self.stale.append(folder))):
            patch = mock.patch(target, fake, create=True)
            patch.start()
            self.addCleanup(patch.stop)

    def test_the_defaults(self):
        cfg = config.load("/nonexistent")
        self.assertEqual(cfg["standby"], {"enabled": True, "minutes": 5, "idle": "hypridle"})
        self.assertEqual(cfg["ambient"]["fps"], 30)
        self.assertIn("|pulse|motion|standby|", (ROOT / "hypr" / "eva.lua").read_text())
        self.assertIn("eva-ctl standby", (ROOT / "bin" / "eva-ctl").read_text())
        example = (ROOT / "config" / "eva.example.toml").read_text()
        self.assertTrue("[standby]" in example and "[ambient]" in example)

    def test_standby_on(self):
        app = standby_app()
        self.assertEqual(app.command("standby"), "ok")
        (piece, mons, inputs), = app.standby.starts
        self.assertEqual((type(piece).__name__, sorted(mons)), ("StandbyLoop", ["GDK-1", "GDK-2"]))        # every monitor, not only the main one
        self.assertEqual(app.motion.stopped, [None])           # a sequence that was playing has gone
        ctx = inputs()
        self.assertEqual(sorted(ctx), ["clock", "date", "readings", "second"])
        self.assertTrue(0 <= ctx["second"] < 60)
        self.assertEqual(app.command("standby on"), "ok")      # already up
        self.assertEqual(len(app.standby.starts), 1)
        self.assertEqual(app.command("standby off"), "ok")
        self.assertEqual(app.standby.ends, [False])            # with the fold
        self.assertEqual(app.command("standby off"), "ok")     # not up: nothing to do
        self.assertEqual(app.command("standby maybe"), "standby: on | off")
        self.assertEqual(app.command("play standby"), "standby is a loop: eva-ctl standby on")

    def test_the_inputs_ask_hyprland_nothing(self):
        app = standby_app()
        app.res_state = {"cpu": 7, "mem": "9.8G", "mem_pct": 31, "net": "lan", "down": "340K", "show": []}
        app.command("standby")
        app.hypr.asked.clear()
        ctx = app.standby.starts[0][2]()
        self.assertEqual((app.hypr.asked, ctx["readings"][0]), ([], "MAGI·1 CPU 07%"))

    def test_when_it_does_not_start(self):
        game = {"class": "steam_app_1", "workspace": {"id": 9}, "monitor": 0, "fullscreen": 0}
        full = {"class": "mpv", "workspace": {"id": 5}, "monitor": 1, "fullscreen": 2}
        for state, answer in (({"clients": [game]}, "not now: a game is open"), ({"clients": [full]}, "not now: a window is fullscreen"),
                              ({"locked": {"locked": True}}, "not now: the session is locked")):
            app = standby_app()
            app.hypr.state.update(state)
            self.assertEqual((app.command("standby on"), app.standby.starts), (answer, []))
        app = standby_app()
        app.hypr.fail = OSError("gone")
        self.assertEqual(app.command("standby on"), "not now: Hyprland does not answer")
        app = standby_app()
        self.monitors.clear()
        self.assertEqual(app.command("standby on"), "no monitor")
        app = standby_app(enabled=False)
        app.standby = None
        self.assertEqual(app.command("standby on"), "standby is off ([standby] enabled)")
        self.assertEqual(app.command("standby off"), "ok")
        app = standby_app()
        app.motion = app.standby = None
        self.assertEqual(app.command("standby on"), "motion is not available")

    def test_it_closes_what_holds_the_keyboard(self):
        app = standby_app()
        app.launcher, app.overlays = FakePanel(), {"power": FakePanel(), "alttab": FakePanel()}
        app.panels = {"sound": FakePanel()}
        app.command("standby on")
        self.assertEqual([p.hidden for p in (app.launcher, app.overlays["power"], app.overlays["alttab"])], [1, 1, 1])
        self.assertEqual(app.panels["sound"].closed, 1)

    def test_what_blocks_a_start_also_ends_it(self):
        app = standby_app()
        app._standby_check()                                   # not up: nothing to look at
        self.assertEqual(app.hypr.asked, [])
        app.command("standby on")
        app._standby_check()
        self.assertEqual(app.standby.ends, [])
        app.hypr.state["clients"] = [{"class": "gamescope", "workspace": {"id": 3}, "monitor": 0, "fullscreen": 0}]
        app._standby_check()
        self.assertEqual(app.standby.ends, [True])             # at once

    def test_a_monitor_that_goes_away_ends_it(self):
        app = standby_app()
        app.command("standby on")
        self.monitors.pop("DP-2")
        app._standby_check()
        self.assertEqual(app.standby.ends, [True])
        app.command("standby on")
        self.monitors["DP-3"] = "GDK-3"                        # or one that comes: it would be left uncovered
        app._standby_check()
        self.assertEqual(app.standby.ends, [True, True])

    def test_locking_sleeping_and_a_critical_notification(self):
        app = standby_app()
        app.command("standby on")
        app.lock()
        self.assertEqual((app.standby.ends, app.hypr.execs), ([True], ["hyprlock"]))        # standby goes first, then the lock screen comes
        app.standby.up = True
        app._on_sleep(True)
        app.standby.up = True
        app.hypr.state["locked"] = {"locked": True}
        app.cfg["motion"]["wake"] = False                      # the watch looks for standby's sake too
        app._watch_lock(now=0.0)
        self.assertEqual(app.standby.ends, [True, True, True])
        self.assertEqual(len(app.later), 1)                    # and it looks again
        app.standby.up, band = True, []
        app.overlays = {"alarm": types.SimpleNamespace(show=band.append)}
        app._on_critical({"summary": "disk"})
        self.assertEqual((app.standby.ends[-1], band), (False, [{"summary": "disk"}]))
        app.standby.up, app.overlays = True, {}
        app._on_critical({"summary": "disk"})                  # with no band it still ends standby
        self.assertEqual(len(app.standby.ends), 5)

    def test_the_watch_rests_when_nothing_needs_it(self):
        app = standby_app()
        app.standby = None
        app.cfg["motion"]["wake"] = False
        app._watch_lock(now=0.0)
        self.assertEqual((app.later, app.hypr.asked), ([], []))

    def test_nothing_else_plays_over_it(self):
        app = standby_app()
        self.assertFalse(app._quiet() or app._covered())
        app.command("standby on")
        self.assertTrue(app._quiet() and app._covered())

    def test_the_idle_child_follows_the_settings(self):
        made = []

        def fake(minutes, ctl, folder):
            made.append((minutes, ctl, folder))
            return types.SimpleNamespace(start=lambda: True)
        for standby, want in (({}, [5]), ({"minutes": 0}, []), ({"minutes": "soon"}, []), ({"idle": "none"}, []),
                              ({"enabled": False}, []), ({"minutes": 12}, [12])):
            app = standby_app(**standby)
            made.clear()
            self.stale.clear()
            with mock.patch("eva_desk.sources.idle.Idle", fake):
                app._start_idle()
            self.assertEqual([m[0] for m in made], want, standby)
            self.assertEqual(self.stale, [] if want else [config.STATE_DIR], standby)      # with no child of its own it still ends one left behind
        self.assertTrue(made[0][1].endswith("bin/eva-ctl"))
        self.assertEqual(made[0][2], config.STATE_DIR)

    def test_a_reload_stops_the_idle_child_first(self):
        app, order = standby_app(), []
        app.idle = types.SimpleNamespace(stop=lambda: order.append("stop"))
        app.argv = []
        app.command("standby on")
        with mock.patch("os.execv", lambda *a: order.append("exec")):
            app._restart()
        self.assertEqual(order, ["stop", "exec"])
        app._stop_children()                                   # twice is fine
        app.idle = types.SimpleNamespace(stop=lambda: 1 / 0)   # and one that will not stop does not stop the daemon from going
        with contextlib.redirect_stderr(io.StringIO()):
            app._stop_children()

    def test_the_idle_child_going_is_said_once(self):
        app = standby_app()
        app.idle, app.minute = types.SimpleNamespace(gone=lambda: True), None
        with contextlib.redirect_stdout(io.StringIO()) as out:
            app._clock()
        self.assertIn("hypridle has exited", out.getvalue())

    def test_critical_notifications_are_heard_without_the_band(self):
        from eva_desk import overlays as O
        heard = []
        watch = O.NotifyWatch.__new__(O.NotifyWatch)
        watch.on_critical = heard.append

        def message(urgency, member="Notify"):
            body = types.SimpleNamespace(n_children=lambda: 8, unpack=lambda: ("mail", 0, "", "Disk", "full", [], {"urgency": urgency}, -1))
            return types.SimpleNamespace(get_member=lambda: member, get_interface=lambda: "org.freedesktop.Notifications", get_body=lambda: body)
        with mock.patch.object(O.GLib, "idle_add", lambda fn, *a: fn(*a)):
            for m in (message(2), message(1), message(2, "CloseNotification")):
                self.assertIs(watch._filter(None, m, True), m)                 # a monitor passes every message on
            watch._filter(None, message(2), False)                             # one of its own, going out
            with contextlib.redirect_stdout(io.StringIO()):
                watch._filter(None, types.SimpleNamespace(get_member=lambda: 1 / 0), True)   # and one it cannot read: said, not raised
        self.assertEqual(heard, [{"app": "mail", "summary": "Disk", "body": "full"}])
        watch.on_critical = lambda note: 1 / 0                                 # whoever listens may fail; the watch goes on
        with mock.patch.object(O.GLib, "idle_add", lambda fn, *a: fn(*a)), contextlib.redirect_stderr(io.StringIO()):
            watch._filter(None, message(2), True)


class StandbyHardening(NoCompositor):
    """What the first review of standby found: it must end, whatever else fails around it."""

    def setUp(self):
        super().setUp()
        self.monitors = {"DP-1": MON, "DP-2": MON2}
        for target, fake in (("eva_desk.gtkutil.monitors", lambda: dict(self.monitors)), ("eva_desk.sources.idle.end_stale", lambda *a, **kw: None)):
            patch = mock.patch(target, fake)
            patch.start()
            self.addCleanup(patch.stop)

    def real_app(self):
        """standby_app(), with the real Standby on layers that have no window."""
        from eva_desk.motion.player import Standby
        app = standby_app()
        app.standby = Standby(app, make=lambda a: ambient())
        return app

    def test_a_reading_that_is_not_there_yet(self):
        from eva_desk.motion import triggers as T
        res = {"cpu": None, "mem": "9.8G", "mem_pct": 31, "net": "lan", "down": "340K", "show": []}        # the sampler's first answer has no CPU share
        self.assertEqual(T.readings(res)[0], "MAGI·1 CPU 00%")
        self.assertEqual(T.readings({"cpu": "x", "mem": None, "net": None, "down": None}), ["MAGI·1 CPU 00%", "MAGI·2 RAM ", "MAGI·3 NET ↓"])
        app = self.real_app()
        app.res_state = res
        self.assertEqual(app.command("standby on"), "ok")      # right after the daemon started
        self.assertTrue(app.standby.up and all(layer.win.visible for layer in app.standby.layers()))
        for layer in app.standby.layers():
            layer.beat(time.monotonic())
        self.assertTrue(app.standby.up)
        app.command("standby off")
        app.standby.end(at_once=True)

    def test_a_start_that_fails_says_so(self):
        app = standby_app()
        app.standby.start = lambda *a: False
        self.assertEqual(app.command("standby on"), "could not start (see the log)")

    def test_one_loop_for_the_daemons_life(self):
        app = standby_app()
        app.command("standby on")
        app.command("standby off")
        app.command("standby on")
        (first, _, _), (second, _, _) = app.standby.starts
        self.assertIs(first, second)                           # so that what it could not find is said once, not at every start

    def test_hiding_tells_its_owner_whatever_else_fails(self):
        a, hidden = ambient(), []
        a.on_hidden = hidden.append
        a.play(dummy(), MON, dict, 0.0)
        a.app = types.SimpleNamespace(_update_frames=lambda: 1 / 0)
        with contextlib.redirect_stderr(io.StringIO()):
            a.hide()                                           # it does not raise,
        self.assertEqual((a.win.visible, a.up, hidden), (False, False, [a]))       # and the owner knows

    def test_a_layer_that_cannot_come_up_is_not_up(self):
        a = ambient()
        a._keyboard = lambda mode: 1 / 0
        with contextlib.redirect_stdout(io.StringIO()) as out:
            self.assertFalse(a.play(dummy(), MON, dict, 0.0))
        self.assertFalse(a.up or a.win.visible)
        self.assertIn("eva-desk: motion:", out.getvalue())
        a = ambient()
        with contextlib.redirect_stdout(io.StringIO()) as out:
            self.assertFalse(a.play(dummy(), MON, lambda: 1 / 0, 0.0))
        self.assertIn("inputs:", out.getvalue())               # said as what it is, not as a piece that could not prepare

    def test_the_rate_is_kept_sane(self):
        for fps, ms in ((30, 33), (1000, 8), (0, 1000), (-5, 1000), ("fast", 33), (None, 33)):
            a = ambient(fps=fps)
            a.play(dummy(), MON, dict, 0.0)
            self.assertEqual(a.timers[0][0], ms, fps)
        app = standby_app()
        for given, want in ((30, 30), ("60", 60), ("fast", 30), (None, 30), (0, 1), (5000, 120)):
            app.cfg["ambient"]["fps"] = given
            self.assertEqual(app._ambient_fps(), want, given)

    def test_it_starts_on_what_it_can_and_never_half(self):
        from eva_desk.motion.player import Standby
        made = []

        def make(app):
            made.append(1)
            if len(made) == 1:
                raise RuntimeError("no surface")
            return ambient()
        s, piece = Standby(object(), make=make), dummy()
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertTrue(s.start(piece, [MON, MON2], dict))             # one monitor could not have a layer; the other has it
        self.assertEqual(s.monitors(), [MON2])
        s.end(at_once=True)
        s = Standby(object(), make=lambda app: 1 / 0)
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertFalse(s.start(piece, [MON, MON2], dict))
        self.assertFalse(s.up)                                 # and nothing is left thinking it is up
        self.assertEqual(piece.released, 2)

    def test_whatever_is_up_can_be_ended(self):
        s, piece = screens()
        s.start(piece, [MON, MON2], dict)
        one, two = s.layers()
        s.piece = None                                         # the books are wrong: a layer is up and standby thinks it is not
        s.poke(one, "key")
        self.assertTrue(one.leaving and two.leaving)
        s.end(at_once=True)
        self.assertFalse(one.win.visible or two.win.visible or s.up)
        s.start(piece, [MON, MON2], dict)
        one.hide = lambda: 1 / 0                               # one layer cannot be hidden: the other still goes
        with contextlib.redirect_stderr(io.StringIO()):
            s.end(at_once=True)
        self.assertFalse(two.win.visible)
        del one.hide
        one.on_hidden = None                                   # and a layer that goes without saying so is still noticed
        s.end(at_once=True)
        self.assertFalse(s.up)

    def test_the_lock_screen_comes_whatever_standby_does(self):
        app = standby_app()
        app.standby = types.SimpleNamespace(up=True, end=lambda at_once=False: 1 / 0)
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(app.lock(), "ok")
        self.assertEqual(app.hypr.execs, ["hyprlock"])

    def test_a_band_that_fails_does_not_keep_standby_up(self):
        app = standby_app()
        app.command("standby on")
        app.overlays = {"alarm": types.SimpleNamespace(show=lambda note: 1 / 0)}
        with contextlib.redirect_stderr(io.StringIO()):
            app._on_critical({"summary": "disk"})
        self.assertEqual(app.standby.ends, [False])

    def test_the_check_runs_even_when_the_refresh_fails(self):
        app = standby_app()
        app.command("standby on")
        app.hypr.state["clients"] = [{"class": "gamescope", "workspace": {"id": 3}, "monitor": 0, "fullscreen": 0}]
        app.refresh = lambda: 1 / 0
        app.refresh_id = 7
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertFalse(app._run_refresh())
        self.assertEqual(app.standby.ends, [True])

    def test_the_pictures_come_from_one_folder(self):
        from eva_desk.motion.amb import standby as S
        with tempfile.TemporaryDirectory() as tmp:
            theme = Path(tmp)
            (theme / "motion").mkdir()
            shutil.copy(ROOT / "assets/motion/full_body.jpg", theme / "motion" / "profile_body.jpg")       # a theme with one stray file
            with mock.patch.object(config, "theme_dir", lambda: theme):
                loop = S.StandbyLoop()
                self.assertEqual(loop.shots(), ["profile", "field", "tilt", "stare"])
                self.assertEqual(loop.art["profile"][0].get_width(), 1792)             # the desk's own, whole: not a mix of the two
                for p in (ROOT / "assets/motion").iterdir():
                    shutil.copy(p, theme / "motion" / p.name)
                shutil.copy(ROOT / "assets/motion/full_body.jpg", theme / "motion" / "profile_body.jpg")
                shutil.copy(ROOT / "assets/motion/full_eye.jpg", theme / "motion" / "profile_eye.jpg")
                loop = S.StandbyLoop()
                loop.shots()
                self.assertEqual(loop.art["profile"][0].get_width(), 896)              # a theme that brings its own gets its own


# ---------------------------------------------------------------- the living wallpaper
def loop_piece():
    piece = dummy(covers=False)
    piece.length = None
    return piece


class AmbientPause(NoCompositor):
    def test_pause_keeps_the_frame_and_stops_the_timer(self):
        a = ambient()
        a.play(loop_piece(), MON, dict, 100.0)
        a.beat(104.0)
        a.pause(105.0)
        self.assertTrue(a.paused and a.win.visible and a.up)
        self.assertEqual(a.cancelled, [1])
        a.beat(110.0)                                          # a beat that was already on its way changes nothing
        self.assertEqual(a.at, 4.0)
        a.pause(111.0)                                         # twice is once
        a.resume(125.0)
        self.assertFalse(a.paused)
        self.assertEqual([ms for ms, _ in a.timers], [33, 33])
        a.beat(126.0)
        self.assertEqual(a.at, 6.0)                            # the twenty seconds it was paused never happened
        a.resume(127.0)                                        # not paused: nothing
        self.assertEqual(len(a.timers), 2)

    def test_it_can_be_drawn_again_while_paused(self):
        a, asked = ambient(), []
        a.play(loop_piece(), MON, lambda: asked.append(1) or {"n": len(asked)}, 0.0)
        a.beat(3.0)
        a.pause(3.0)
        a.redraw()
        self.assertEqual((a.at, a.ctx), (3.0, {"n": 3}))       # new inputs, the same moment
        a.hide()
        a.redraw()                                             # nothing on it: nothing happens
        self.assertEqual(len(asked), 3)

    def test_a_pause_does_not_outlive_its_piece(self):
        a = ambient()
        a.play(loop_piece(), MON, dict, 0.0)
        a.pause(1.0)
        a.hide()
        self.assertFalse(a.paused)
        a.resume(2.0)
        self.assertEqual(len(a.timers), 1)
        a.play(loop_piece(), MON, dict, 5.0)
        self.assertFalse(a.paused)
        a.pause(6.0)
        a.leave(7.0, 0.19)                                     # a paused piece that must go goes at once
        self.assertFalse(a.up or a.win.visible)

    def test_a_piece_that_does_not_cover_takes_no_input(self):
        a = ambient()
        a.play(loop_piece(), MON, dict, 0.0)
        self.assertTrue(a.win.surface.region.is_empty())

    def test_the_layer_it_sits_on(self):
        from eva_desk import overlays as O
        made = []

        def window(app, monitor, layer, namespace, **kw):
            made.append((layer, namespace, kw.get("keyboard")))
            return types.SimpleNamespace(set_child=lambda view: None)
        with mock.patch.object(O, "layer_window", window), mock.patch.object(O, "_View", lambda painter: FakeView()):
            O._Overlay(object(), "eva-x")
            O._Overlay(object(), "eva-wallpaper", layer="background")
        self.assertEqual(made, [("overlay", "eva-x", "none"), ("background", "eva-wallpaper", "none")])


class PauseRules(unittest.TestCase):
    def test_what_pauses_the_loops(self):
        from eva_desk.motion import triggers as T
        mons = [{"id": 0, "name": "DP-1", "activeWorkspace": {"id": 1}}, {"id": 1, "name": "DP-2", "activeWorkspace": {"id": 5}}]
        pats, both = ["^steam_app_", "^gamescope$"], {"DP-1", "DP-2"}
        term = {"class": "kitty", "workspace": {"id": 1}, "monitor": 0, "fullscreen": 0}
        full = {"class": "mpv", "workspace": {"id": 5}, "monitor": 1, "fullscreen": 2}
        maxed = {"class": "firefox", "workspace": {"id": 1}, "monitor": 0, "fullscreen": 1}
        hidden_game = {"class": "steam_app_1145360", "workspace": {"id": 9}, "monitor": 0, "fullscreen": 0}
        other_game = {"class": "gamescope", "workspace": {"id": 5}, "monitor": 1, "fullscreen": 2}
        for clients, flags, want in (
                ([term], {}, set()),
                ([term, maxed], {}, set()),                     # maximised is not fullscreen
                ([term, full], {}, {"DP-2"}),                   # a fullscreen window pauses its own monitor
                ([term, hidden_game], {}, both),                # a game on a workspace nobody is looking at pauses everything
                ([term, other_game], {}, both),                 # and so does one on the other monitor
                ([term], {"locked": True}, both),
                ([term], {"locked": None}, set()),              # Hyprland did not say: not locked
                ([term], {"asleep": True}, both),
                ([term], {"off": True}, both),                  # eva-ctl ambient off
                ([term], {"standby": True}, both)):             # standby covers them
            self.assertEqual(T.paused_monitors(mons, clients, pats, **flags), want, (clients, flags))
        self.assertEqual(T.paused_monitors(None, None, pats), set())
        self.assertEqual(T.paused_monitors(None, None, pats, off=True), set())    # nothing to pause


class WallpaperTest(unittest.TestCase):
    def setUp(self):
        from eva_desk import draw as d, gtkutil
        from eva_desk.motion import render
        from eva_desk.motion.amb import wallpaper
        self.Wp, self.render, self.d, self.gtkutil = wallpaper, render, d, gtkutil

    def flat(self, colour, w=344, h=144):
        def paint(cr):
            self.d.rgba(cr, colour)
            cr.paint()
        return self.gtkutil.render_texture(w, h, paint)

    def ctx(self, **more):
        return {"picture": self.flat(self.d.BONE), "drift": 0.08, "lap": 30.0, "ripples": False, "embers": False, **more}

    def frame(self, t, w=1720, h=720, **more):
        return self.render.frame(self.Wp.WallpaperLoop(), t, w, h, self.ctx(**more))

    def test_the_camera(self):
        Wp = self.Wp
        self.assertEqual(Wp.camera(0.0, 0.08, 30.0)[0], 1.035)
        self.assertAlmostEqual(Wp.camera(15.0, 0.08, 30.0)[0], 1.115)          # pushed in by the drift, half a lap in
        self.assertAlmostEqual(Wp.camera(30.0, 0.08, 30.0)[0], 1.035)
        zooms = [Wp.camera(t / 10, 0.08, 30.0) for t in range(0, 1200)]
        self.assertTrue(all(1.035 <= z <= 1.1151 and abs(dx) <= 0.015 and abs(dy) <= 0.015 for z, dx, dy in zooms))
        self.assertGreater(max(dx for _, dx, _ in zooms), 0.014)               # the pan really reaches a hundredth and a half
        self.assertEqual(Wp.camera(7.0, 0.0, 30.0), (1.0, 0.0, 0.0))           # no drift: a still picture
        self.assertEqual(Wp.camera(7.0, 0.08, 0.0), (1.0, 0.0, 0.0))           # and no lap is no motion, not a division by nothing

    def test_the_picture_always_covers_the_frame(self):
        Wp = self.Wp
        for (tw, th), (W, H) in (((344, 144), (1720, 720)), ((1920, 1080), (1720, 720)), ((1080, 1920), (1720, 720)), ((3440, 1440), (1280, 2275.6))):
            for i in range(400):                               # more than three laps of every period
                x, y, w, h = Wp.place(tw, th, W, H, i * 0.37, 0.08, 30.0)
                self.assertTrue(x <= 0 and y <= 0 and x + w >= W and y + h >= H, (tw, th, W, H, i, x, y, w, h))
        for t in (0.0, 9.0, 21.0):
            for w, h in ((1720, 720), (1080, 1920)):
                f = self.frame(t, w, h)
                self.assertEqual(set(grid(f)), {255}, (t, w, h))
                self.assertEqual((alpha(f, 0, 0), alpha(f, w - 1, h - 1), pink(f)), (255, 255, 0))

    def test_it_moves_and_never_jumps(self):
        Wp = self.Wp
        boxes = [Wp.place(3440, 1440, 1720, 720, i / 30, 0.08, 30.0) for i in range(30 * 40)]
        step = max(max(abs(a - b) for a, b in zip(one, two)) for one, two in zip(boxes, boxes[1:]))
        self.assertLess(step, 1.2)                             # design px from one frame to the next, at thirty a second
        self.assertGreater(max(b[2] for b in boxes) - min(b[2] for b in boxes), 100)       # and over a lap it is plain to see

    def test_a_new_picture_fades_in_over_the_old_one(self):
        d = self.d
        old, new = self.flat(d.BONE), self.flat(d.GOLD)
        self.assertTrue(near(px(self.frame(3.0, picture=new, previous=old, fade=0.0), 860, 360), BONE))
        self.assertTrue(near(px(self.frame(3.0, picture=new, previous=old, fade=1.0), 860, 360), GOLD))
        mid = px(self.frame(3.0, picture=new, previous=old, fade=0.5), 860, 360)
        self.assertTrue(BONE[0] > mid[0] > GOLD[0] and mid[3] == 255, mid)     # blue: between the two
        f = self.frame(3.0, picture=new, previous=None, fade=0.5)              # nothing to fade from: it fades in over the desk
        self.assertAlmostEqual(alpha(f, 860, 360), 128, delta=3)
        ground = self.d.hexc("#204060")                                        # or over the colour that was there before it
        f = self.frame(3.0, picture=new, previous=None, fade=0.0, ground=ground)
        self.assertEqual(px(f, 860, 360), (0x60, 0x40, 0x20, 255))
        f = self.frame(3.0, picture=new, previous=None, fade=0.5, ground=ground)
        self.assertEqual(alpha(f, 860, 360), 255)
        f = self.frame(3.0, picture=new, previous=None, fade=1.0, ground=ground)
        self.assertTrue(near(px(f, 860, 360), GOLD))

    def test_a_colour_is_a_plain_fill_that_does_not_move(self):
        d = self.d
        ctx = {"colour": d.hexc("#204060"), "ripples": True, "embers": True, "drift": 0.08, "lap": 30.0}
        a = self.render.frame(self.Wp.WallpaperLoop(), 2.0, 1720, 720, ctx)
        b = self.render.frame(self.Wp.WallpaperLoop(), 13.0, 1720, 720, ctx)
        self.assertTrue(same(a, b))
        self.assertEqual(px(a, 5, 5), (0x60, 0x40, 0x20, 255))

    def test_nothing_to_show_paints_nothing(self):
        for ctx in ({}, {"ripples": True, "embers": True}, {"picture": None, "previous": None}):
            self.assertIsNone(box(self.render.frame(self.Wp.WallpaperLoop(), 2.0, 1720, 720, ctx)))

    def test_ripples(self):
        Wp, d = self.Wp, self.d
        self.assertEqual(Wp.rings(2.0), [(0, 2.0)])
        self.assertEqual(Wp.rings(5.0), [])                    # the first has faded (4.2 s), the next starts at 5.5
        self.assertEqual([k for k, _ in Wp.rings(6.0)], [1])
        self.assertEqual([k for k, _ in Wp.rings(5.5 * 400 + 1.0)], [400])
        for k in range(50):
            cx, cy = Wp.ring_centre(k, 1720, 720)
            self.assertTrue(0.12 * 1720 <= cx <= 0.88 * 1720 and 0.15 * 720 <= cy <= 0.85 * 720)
        plain, rippled = self.frame(2.0), self.frame(2.0, ripples=True)
        self.assertFalse(same(plain, rippled))
        self.assertFalse(same(rippled, self.frame(2.0, ripples=True, berserk=True)))       # orange when the desk is berserk
        self.assertTrue(same(self.frame(5.2), self.frame(5.2, ripples=True)))              # between two rings there is none
        self.assertEqual(pink(rippled), 0)

    def test_embers(self):
        Wp = self.Wp
        now, later = Wp.embers(10.0, 1720, 720, 0.0), Wp.embers(11.0, 1720, 720, 0.0)
        self.assertEqual(len(now), 70)
        self.assertTrue(all(1.0 <= size <= 2.8 and 0 <= a <= 0.65 and -110 <= y <= 740 for x, y, size, a, kind in now))
        self.assertTrue(8 <= sum(kind == "gold" for *_, kind in now) <= 22)
        rising = sum(b[1] < a[1] for a, b in zip(now, later))
        self.assertGreaterEqual(rising, 66)                    # all of them, but for the few that went round
        self.assertTrue(all(9 <= a[1] - b[1] <= 25.01 for a, b in zip(now, later) if b[1] < a[1]))
        self.assertFalse(same(self.frame(10.0), self.frame(10.0, embers=True)))
        hot = Wp.embers(10.0, 1720, 720, 0.0, berserk=True)
        self.assertEqual({kind for *_, kind in hot}, {"led"})

    def test_nothing_is_made_after_the_first_frame(self):
        from eva_desk import gtkutil  # noqa: F401
        from gi.repository import Gtk
        from eva_desk.motion.kit import Kit
        loop, store, sizes, ctx = self.Wp.WallpaperLoop(), {}, [], self.ctx(ripples=True, embers=True)
        for t in (1.0, 2.0, 3.0, 6.5, 8.0):
            kit = Kit(Gtk.Snapshot(), 1720, 720, 1.0, store)
            loop.paint(kit, t, ctx)
            kit.close()
            sizes.append(len(store))
        self.assertEqual(len(set(sizes)), 1, sizes)

    def test_odd_inputs(self):
        for more in ({"drift": "far"}, {"lap": None}, {"fade": 7}, {"fade": -1}, {"fade": "x"}, {"picture": None, "previous": self.flat(self.d.GOLD)},
                     {"colour": "red"}, {"berserk": 1}):
            f = self.frame(2.0, ripples=True, embers=True, **more)
            self.assertEqual(pink(f), 0, more)

    def test_the_renderer_shows_it_on_a_stand_in_picture(self):
        from eva_desk import motion
        self.assertEqual(list(motion.loops())[:2], ["standby", "wallpaper"])
        loop = motion.loops()["wallpaper"]()
        self.assertEqual((loop.name, loop.length, loop.covers, loop.lap), ("wallpaper", None, False, 30.0))
        f = self.render.frame(loop, 3.0, 1720, 720, self.render.fixture_ctx())
        self.assertEqual(set(grid(f)), {255})
        self.assertFalse(same(f, self.render.frame(loop, 9.0, 1720, 720, self.render.fixture_ctx())))


def living(pictures=None, **ambient_cfg):
    """A Living whose layers are ambient(), whose clock is its `now` and whose decoder hands out `files`."""
    from eva_desk.motion.living import Living
    cfg = config.load("/nonexistent")
    cfg["ambient"].update(ambient_cfg)
    host = Living(object(), cfg, make=lambda app: ambient(keyboard="none"), clock=lambda: host.now,
                  decode=lambda path, done: (host.asked.append(path), done(*host.files.get(path, (None, "no such file")))))
    host.now, host.files, host.asked = 0.0, pictures or {}, []
    return host


class LivingTest(NoCompositor):
    def setUp(self):
        super().setUp()
        from eva_desk import draw as d, gtkutil

        def flat(colour):
            return gtkutil.render_texture(8, 4, lambda cr: (d.rgba(cr, colour), cr.paint()))
        self.A, self.B = flat(d.BONE), flat(d.GOLD)
        self.files = {"/a.jpg": (self.A, None), "/b.jpg": (self.B, None)}

    def test_the_first_picture_goes_up_whole(self):
        host = living(self.files)
        self.assertTrue(host.show("DP-1", MON, "/a.jpg"))
        screen = host.screens["DP-1"]
        layer = screen.layer
        self.assertTrue(layer.up and layer.win.visible and not layer.paused)
        self.assertEqual(([ms for ms, _ in layer.timers], layer.keyboard), ([33], ["none"]))
        self.assertTrue(layer.win.surface.region.is_empty())  # clicks go through to the desk
        ctx = layer.inputs()
        self.assertEqual((ctx["picture"], ctx["previous"], ctx["ground"], ctx["colour"]), (self.A, None, None, None))
        self.assertEqual(ctx["fade"], 1.0)                     # nothing of its own to fade from: what lies under it is not the desk's to show
        self.assertEqual((ctx["drift"], ctx["lap"], ctx["ripples"], ctx["embers"], ctx["berserk"]), (0.08, 30.0, True, True, False))
        self.assertTrue(host.shows("DP-1") and not host.shows("DP-2"))

    def test_a_picture_after_a_colour_fades_in_over_that_colour(self):
        host = living(self.files)
        host.show("DP-1", MON, "#204060")
        layer, blue = host.screens["DP-1"].layer, (0x20 / 255, 0x40 / 255, 0x60 / 255, 1.0)
        host.now = 4.0
        host.show("DP-1", MON, "/a.jpg")
        ctx = layer.inputs()
        self.assertEqual((ctx["picture"], ctx["previous"], ctx["ground"], ctx["fade"], ctx["colour"]), (self.A, None, blue, 0.0, None))
        self.assertFalse(layer.paused)
        host.now = 4.45
        self.assertAlmostEqual(layer.inputs()["fade"], 0.5)
        host.now = 6.0
        ctx = layer.inputs()
        self.assertEqual((ctx["fade"], ctx["ground"]), (1.0, None))

    def test_the_next_one_fades_in_over_it(self):
        host = living(self.files)
        host.show("DP-1", MON, "/a.jpg")
        layer = host.screens["DP-1"].layer
        host.now = 10.0
        self.assertTrue(host.show("DP-1", MON, "/b.jpg"))
        ctx = layer.inputs()
        self.assertEqual((ctx["picture"], ctx["previous"], ctx["fade"]), (self.B, self.A, 0.0))
        self.assertEqual(len(layer.timers), 1)                 # the same layer goes on; nothing was started again
        host.now = 10.9
        self.assertEqual(layer.inputs()["fade"], 1.0)
        self.assertIsNone(layer.inputs()["previous"])          # the old picture is let go once it is covered
        self.assertTrue(host.show("DP-1", MON, "/b.jpg"))      # the same picture again: nothing to do
        self.assertEqual(host.asked, ["/a.jpg", "/b.jpg"])

    def test_no_fade_when_the_duration_is_nothing(self):
        host = living(self.files)
        host.fade = 0.0
        host.show("DP-1", MON, "/a.jpg")
        self.assertEqual(host.screens["DP-1"].layer.inputs()["fade"], 1.0)

    def test_a_picture_that_cannot_be_read(self):
        host, failed = living(self.files), []
        host.on_failed = lambda name, target: failed.append((name, target))
        host.show("DP-1", MON, "/a.jpg")
        with contextlib.redirect_stdout(io.StringIO()) as out:
            host.show("DP-1", MON, "/broken.webp")
            host.show("DP-1", MON, "/a.jpg")
            host.show("DP-1", MON, "/broken.webp")
        self.assertEqual(failed, [("DP-1", "/broken.webp")] * 2)
        self.assertEqual(out.getvalue().count("/broken.webp"), 1)                  # said once
        self.assertFalse(host.shows("DP-1") or host.screens["DP-1"].layer.win.visible)      # the monitor is given back each time

    def test_a_colour_is_a_still_fill(self):
        host = living(self.files)
        self.assertTrue(host.show("DP-1", MON, "#204060"))
        layer = host.screens["DP-1"].layer
        self.assertTrue(layer.up and layer.paused)             # nothing moves: no timer
        self.assertEqual(layer.ctx["colour"], (0x20 / 255, 0x40 / 255, 0x60 / 255, 1.0))
        host.pause(set())
        self.assertTrue(layer.paused)                          # resuming the loops does not start a timer for a colour
        host.show("DP-1", MON, "/a.jpg")
        self.assertFalse(layer.paused)
        self.assertEqual((layer.inputs()["colour"], layer.inputs()["picture"]), (None, self.A))
        with contextlib.redirect_stdout(io.StringIO()) as out:
            for bad in ("#nope", "#abc", "#1234567", "#", "#nope"):
                self.assertTrue(host.show("DP-1", MON, bad))   # not a colour: what is up stays up, rather than a blank monitor
            self.assertTrue(layer.up and layer.inputs()["picture"] is self.A)
            self.assertFalse(host.show("DP-2", MON2, "#nope")) # with nothing up there, the caller may try something else
        self.assertEqual(out.getvalue().count("#nope"), 1)     # said once

    def test_a_decode_that_comes_late_is_dropped(self):
        host, waiting = living(self.files), []
        host.decode = lambda path, done: waiting.append((path, done))
        host.show("DP-1", MON, "/a.jpg")
        host.show("DP-1", MON, "/b.jpg")                       # the workspace changed again before the first was read
        self.assertFalse(host.shows("DP-1"))
        waiting[0][1](self.A, None)
        self.assertFalse(host.shows("DP-1"))
        waiting[1][1](self.B, None)
        ctx = host.screens["DP-1"].layer.inputs()
        self.assertEqual((ctx["picture"], ctx["previous"]), (self.B, None))
        host.forget([])
        waiting[1][1](self.B, None)                            # and one for a monitor that is gone
        self.assertEqual(host.screens, {})

    def test_pausing(self):
        host = living(self.files)
        host.show("DP-1", MON, "/a.jpg")
        host.show("DP-2", MON2, "/a.jpg")
        one, two = host.screens["DP-1"].layer, host.screens["DP-2"].layer
        host.now = 5.0
        host.pause({"DP-2", "DP-9"})
        self.assertEqual((one.paused, two.paused), (False, True))
        host.show("DP-2", MON2, "/b.jpg")                      # the workspace changes while it stands still
        self.assertEqual((two.ctx["picture"], two.ctx["previous"], two.ctx["fade"]), (self.B, None, 1.0))      # swapped, not faded
        self.assertTrue(two.paused)
        host.pause({"DP-1", "DP-2"})
        host.pause(set())
        self.assertEqual((one.paused, two.paused), (False, False))
        host.pause({"DP-1"})
        host.show("DP-1", MON, "/b.jpg")
        host.forget(["DP-1"])
        self.assertEqual(list(host.screens), ["DP-1"])
        self.assertFalse(two.win.visible)

    def test_a_monitor_that_starts_out_paused(self):
        host = living(self.files)
        host.pause({"DP-1"})
        host.show("DP-1", MON, "/a.jpg")
        layer = host.screens["DP-1"].layer
        self.assertTrue(layer.up and layer.paused)
        self.assertEqual(layer.ctx["fade"], 1.0)               # whole at once: nothing is running to fade it in

    def test_berserk(self):
        host = living(self.files)
        host.show("DP-1", MON, "/a.jpg")
        host.pause({"DP-1"})
        host.set_berserk(True)
        self.assertTrue(host.screens["DP-1"].layer.ctx["berserk"])                 # drawn again, though it stands still

    def test_settings(self):
        host = living(self.files, drift=0, lap=90, ripples=False, embers=False, fps=10)
        host.show("DP-1", MON, "/a.jpg")
        ctx = host.screens["DP-1"].layer.inputs()
        self.assertEqual((ctx["drift"], ctx["lap"], ctx["ripples"], ctx["embers"]), (0.0, 90.0, False, False))
        host = living(self.files, drift="far", lap="long")
        self.assertEqual((host.drift, host.lap), (0.08, 30.0))

    def test_no_monitor_and_stopping(self):
        host = living(self.files)
        self.assertFalse(host.show("DP-1", None, "/a.jpg"))
        host.show("DP-1", MON, "/a.jpg")
        host.stop()
        self.assertFalse(host.shows("DP-1") or host.screens["DP-1"].layer.win.visible)
        self.assertTrue(host.show("DP-1", MON, "/a.jpg"))      # and it can come back
        self.assertTrue(host.shows("DP-1"))

    def test_a_monitor_that_was_replugged(self):
        host = living(self.files)
        host.show("DP-1", MON, "/a.jpg")
        again = FakeMonitor(3440, 1440)
        self.assertTrue(host.show("DP-1", again, "/a.jpg"))    # the same name and picture, another monitor behind it
        self.assertEqual((host.screens["DP-1"].layer.w, host.asked), (3440, ["/a.jpg", "/a.jpg"]))


class FakeLiving:
    def __init__(self):
        self.shown, self.pauses, self.berserk, self.forgot, self.answer = [], [], [], [], True

    def show(self, name, gdk, target):
        self.shown.append((name, gdk, target))
        return self.answer

    def pause(self, names, everything=False):
        self.pauses.append(ALL if everything else set(names))

    def set_berserk(self, on):
        self.berserk.append(on)

    def forget(self, alive):
        self.forgot.append(set(alive))


def living_app(**ambient_cfg):
    """standby_app(), with a living wallpaper that only notes what it is told."""
    app = standby_app()
    app.cfg["ambient"].update(ambient_cfg)
    app.living, app.walls = FakeLiving(), None
    return app


BOTH = {"DP-1", "DP-2"}
ALL = "every monitor, whatever its name"        # what a fake host notes when it is told to stand still everywhere


def wallpapers(awww=True, **settings):
    """The real Wallpapers over a pool of two pictures, with awww installed or not."""
    from eva_desk.wallpaper import Wallpapers
    cfg = config.load("/nonexistent")
    cfg["wallpapers"].update(pool=["/pics/a.jpg", "/pics/b.jpg"], **settings)
    with mock.patch("shutil.which", side_effect=lambda b: "/usr/bin/awww" if awww and b == "awww" else None):
        walls = Wallpapers(cfg)
    walls.pool = list(cfg["wallpapers"]["pool"])               # as written, not shuffled
    return walls


class LivingWiring(unittest.TestCase):
    def setUp(self):
        self.monitors = {"DP-1": "GDK-1", "DP-2": "GDK-2"}
        patch = mock.patch("eva_desk.gtkutil.monitors", lambda: dict(self.monitors))
        patch.start()
        self.addCleanup(patch.stop)

    def test_the_defaults(self):
        amb = config.load("/nonexistent")["ambient"]
        self.assertEqual({k: amb[k] for k in ("fps", "wallpaper", "drift", "lap", "ripples", "embers")},
                         {"fps": 30, "wallpaper": True, "drift": 8, "lap": 30, "ripples": True, "embers": True})
        self.assertIn("|standby|wallpaper|wall|", (ROOT / "hypr" / "eva.lua").read_text())
        self.assertIn("eva-ctl ambient", (ROOT / "bin" / "eva-ctl").read_text())
        self.assertIn("\nwallpaper = true", (ROOT / "config" / "eva.example.toml").read_text())

    def walls(self, awww=True, **settings):
        return wallpapers(awww, **settings)

    def test_the_wallpaper_is_handed_over(self):
        walls, taken = self.walls(awww=False), []              # no awww at all: the daemon's own wallpaper needs none
        walls.living = lambda monitor, target: taken.append((monitor, target)) or True
        with mock.patch("subprocess.Popen") as popen:
            walls.set_for("DP-1", 1, "")
            walls.set_for("DP-1", 1, "")                       # the same again: nothing
            walls.set_for("DP-1", 2, "")
            walls.forget("DP-1")                               # the monitor was replugged: what it shows is not known any more
            walls.set_for("DP-1", 2, "")
        self.assertEqual(taken, [("DP-1", "/pics/a.jpg"), ("DP-1", "/pics/b.jpg"), ("DP-1", "/pics/b.jpg")])
        popen.assert_not_called()

    def test_what_is_not_taken_goes_to_awww(self):
        walls = self.walls()
        walls.living = lambda monitor, target: False
        with mock.patch("subprocess.Popen") as popen:
            walls.set_for("DP-1", 1, "")
            self.assertEqual(popen.call_args[0][0][:4], ["awww", "img", "-o", "DP-1"])
            walls.direct("DP-1", "#204060")
            self.assertEqual(popen.call_args[0][0], ["awww", "clear", "-o", "DP-1", "204060"])
        walls = self.walls(awww=False)                         # neither: nothing is run, nothing raises
        walls.living = lambda monitor, target: False
        with mock.patch("subprocess.Popen") as popen:
            walls.set_for("DP-1", 1, "")
            walls.direct("DP-1", "/pics/a.jpg")
        popen.assert_not_called()
        walls = self.walls(awww=False, enabled=False)          # wallpapers switched off: not even handed over
        walls.living = lambda monitor, target: 1 / 0
        walls.set_for("DP-1", 1, "")

    def test_the_daemon_hands_it_to_its_own_layer(self):
        app = living_app()
        self.assertTrue(app._living_show("DP-1", "/pics/a.jpg"))
        self.assertEqual(app.living.shown, [("DP-1", "GDK-1", "/pics/a.jpg")])
        self.assertFalse(app._living_show("HDMI-9", "/pics/a.jpg"))                # not a monitor it knows
        app.living.answer = False
        self.assertFalse(app._living_show("DP-1", "/pics/b.jpg"))
        app.living = None
        self.assertFalse(app._living_show("DP-1", "/pics/a.jpg"))

    def test_a_picture_it_cannot_read_goes_to_awww(self):
        app, sent = living_app(), []
        app.walls = types.SimpleNamespace(direct=lambda name, target: sent.append((name, target)))
        app._living_failed("DP-1", "/pics/broken.webp")
        self.assertEqual(sent, [("DP-1", "/pics/broken.webp")])
        app.walls = None
        app._living_failed("DP-1", "/pics/broken.webp")

    def test_when_the_loops_stand_still(self):
        app = living_app()
        app._ambient_sync()
        self.assertEqual(app.living.pauses, [set()])
        app.hypr.state["clients"] = [{"class": "mpv", "workspace": {"id": 5}, "monitor": 1, "fullscreen": 2}]
        app._ambient_sync()
        self.assertEqual(app.living.pauses[-1], {"DP-2"})
        app.hypr.state["clients"] = [{"class": "steam_app_7", "workspace": {"id": 9}, "monitor": 0, "fullscreen": 0}]
        app._ambient_sync()
        self.assertEqual(app.living.pauses[-1], BOTH)
        app.hypr.state["clients"] = []
        for flag in ("asleep", "ambient_off", "session_locked"):
            setattr(app, flag, True)
            app.hypr.asked.clear()
            app._ambient_sync()
            self.assertEqual((app.living.pauses[-1], app.hypr.asked), (ALL, []), flag)      # everywhere, and Hyprland need not say where
            setattr(app, flag, False)
        app._ambient_sync()
        self.assertEqual(app.living.pauses[-1], set())
        n = len(app.living.pauses)
        app.hypr.fail = OSError("gone")                        # Hyprland does not answer: they stay as they are
        app._ambient_sync()
        self.assertEqual(len(app.living.pauses), n)
        app.living = None                                      # no loops: nothing to ask Hyprland about
        app.hypr.asked.clear()
        app._ambient_sync()
        self.assertEqual(app.hypr.asked, [])

    def test_the_command(self):
        app = living_app()
        self.assertEqual(app.command("ambient"), "ambient on")
        self.assertEqual(app.command("ambient off"), "ambient off")
        self.assertEqual(app.living.pauses[-1], ALL)
        self.assertEqual(app.command("ambient"), "ambient off")
        self.assertEqual(app.command("ambient on"), "ambient on")
        self.assertEqual(app.living.pauses[-1], set())
        self.assertEqual(app.command("ambient sideways"), "ambient: on | off")

    def test_lock_sleep_and_standby_stop_them(self):
        app = living_app()
        app.hypr.state["locked"] = {"locked": True}
        app.cfg["motion"]["wake"] = False
        app.standby = None                                     # the watch also looks for the loops' sake
        app._watch_lock(now=0.0)
        self.assertEqual((app.living.pauses[-1], len(app.later)), (ALL, 1))
        n = len(app.living.pauses)
        app.hypr.state["locked"] = None                        # Hyprland did not say: it is still locked, as far as anyone knows
        app._watch_lock(now=1.0)
        self.assertEqual((len(app.living.pauses), app.session_locked), (n, True))
        app.hypr.state["locked"] = {"locked": False}
        app._watch_lock(now=2.0)
        self.assertEqual(app.living.pauses[-1], set())
        n = len(app.living.pauses)
        app._watch_lock(now=4.0)                               # nothing changed: nothing is told
        self.assertEqual(len(app.living.pauses), n)
        app._on_sleep(True)
        self.assertEqual(app.living.pauses[-1], ALL)
        app._on_sleep(False)
        self.assertEqual(app.living.pauses[-1], set())
        app = living_app()
        app.command("standby on")
        self.assertEqual(app.living.pauses[-1], ALL)           # nobody sees them under standby
        app.standby.end()
        app._standby_ended()
        self.assertEqual(app.living.pauses[-1], set())

    def test_berserk_reaches_the_wallpaper(self):
        app = living_app()
        app.cfg["overlays"].update(berserk=90, berserk_seconds=0)
        app._berserk_check(99, 10)
        app._berserk_check(10, 10)
        self.assertEqual(app.living.berserk, [True, False])


class LoopsHardening(NoCompositor):
    """What the review of the wallpaper found: the desk keeps its wallpaper, and the loops stand still when told."""

    def setUp(self):
        super().setUp()
        from eva_desk import draw as d, gtkutil
        self.A = gtkutil.render_texture(8, 4, lambda cr: (d.rgba(cr, d.BONE), cr.paint()))
        self.files = {"/pics/a.jpg": (self.A, None)}           # b.jpg cannot be read
        self.monitors = {"DP-1": MON, "DP-2": MON2}
        patch = mock.patch("eva_desk.gtkutil.monitors", lambda: dict(self.monitors))
        patch.start()
        self.addCleanup(patch.stop)

    def test_a_replugged_monitor_gets_a_new_layer(self):
        host = living(self.files)
        host.show("DP-1", MON, "/pics/a.jpg")
        old, again = host.screens["DP-1"].layer, FakeMonitor(3440, 1440)
        self.assertTrue(host.show("DP-1", again, "/pics/a.jpg"))               # its window went with the monitor: never shown again
        new = host.screens["DP-1"].layer
        self.assertTrue(new is not old and old.win.destroyed and new.up and not old.up)
        self.assertEqual(new.w, 3440)

    def test_a_layer_that_breaks_gives_the_monitor_back(self):
        host, failed = living(self.files), []
        host.on_failed = lambda name, target: failed.append((name, target))
        host.show("DP-1", MON, "/pics/a.jpg")
        host.screens["DP-1"].layer._fail()
        self.assertEqual((failed, host.shows("DP-1")), ([("DP-1", "/pics/a.jpg")], False))
        self.assertTrue(host.show("DP-1", MON, "/pics/a.jpg"))                 # and it may be tried again
        self.assertEqual((host.shows("DP-1"), host.asked), (True, ["/pics/a.jpg"] * 2))

    def test_the_desk_always_has_its_wallpaper(self):
        app, walls, host = living_app(), wallpapers(), living(self.files)
        app.living, app.walls, walls.living, host.on_failed = host, walls, app._living_show, app._living_failed
        app.gdk_of = {"DP-1": "a monitor from before it was replugged"}        # not where the layer's monitor comes from
        with mock.patch("subprocess.Popen") as popen, contextlib.redirect_stdout(io.StringIO()):
            walls.set_for("DP-1", 1, "")
            self.assertTrue(host.shows("DP-1") and host.screens["DP-1"].gdk is MON)
            popen.assert_not_called()
            walls.set_for("DP-1", 2, "")                                       # one it cannot read: awww shows it
            self.assertFalse(host.shows("DP-1"))
            self.assertEqual(popen.call_args[0][0][-1], "/pics/b.jpg")
            walls.set_for("DP-1", 1, "")
            self.assertTrue(host.shows("DP-1"))
            host.screens["DP-1"].layer._fail()                                 # the layer breaks: awww shows what it showed
            self.assertEqual((host.shows("DP-1"), popen.call_args[0][0][-1]), (False, "/pics/a.jpg"))
            walls.living = lambda monitor, target: 1 / 0                       # and a hand-over that raises is a hand-over refused
            with contextlib.redirect_stderr(io.StringIO()):
                walls.set_for("DP-1", 2, "")
            self.assertEqual((popen.call_count, popen.call_args[0][0][-1]), (3, "/pics/b.jpg"))

    def test_hiding_lets_go_of_what_was_shown(self):
        a = ambient()
        a.play(dummy(), MON, lambda: {"picture": self.A}, 0.0)
        a.hide()
        self.assertEqual(a.ctx, {})                            # a layer that is kept does not keep twenty megabytes with it

    def test_reading_a_picture(self):
        from gi.repository import GLib
        from eva_desk.motion import living as L
        got = {}
        good, folder = str(ROOT / "assets/motion/profile_eye.jpg"), str(ROOT / "assets")
        for path in (good, "/nowhere/at/all.jpg", folder, "", None, "a\0b"):
            L.decode(path, lambda texture, why, path=path: got.setdefault(path, []).append((texture, why)))
        import warnings
        end = time.monotonic() + 5
        with warnings.catch_warnings():                        # PyGObject's own, about asyncio, when a main loop is turned by hand
            warnings.simplefilter("ignore", DeprecationWarning)
            while len(got) < 6 and time.monotonic() < end:     # the answers come back through the main loop
                GLib.MainContext.default().iteration(False)
                time.sleep(0.005)
        self.assertEqual(sorted(map(str, got)), sorted(map(str, (good, "/nowhere/at/all.jpg", folder, "", None, "a\0b"))))
        self.assertTrue(all(len(answers) == 1 for answers in got.values()))               # each exactly once
        self.assertEqual(got[good][0][0].get_width(), 1792)
        for path in ("/nowhere/at/all.jpg", folder, "", None, "a\0b"):
            texture, why = got[path][0]
            self.assertTrue(texture is None and why, path)     # whatever went wrong, it is an answer and not a silence

    def test_odd_settings(self):
        from eva_desk.motion.amb import wallpaper as Wp
        self.assertEqual((living(self.files, drift=float("inf")).drift, living(self.files, drift=float("nan")).drift), (0.08, 0.08))
        self.assertEqual((living(self.files, drift=5000).drift, living(self.files, lap=float("inf")).lap), (1.0, 30.0))
        for drift, lap in ((float("inf"), 30.0), (float("nan"), 30.0), (0.08, float("nan")), (0.08, float("inf"))):
            self.assertEqual(Wp.camera(7.0, drift, lap), (1.0, 0.0, 0.0), (drift, lap))

    def test_a_sync_that_cannot_ask_hyprland_tries_again(self):
        app = living_app()
        app.hypr.fail = OSError("busy")
        app._ambient_sync()
        self.assertEqual(([ms for ms, _ in app.later], app.living.pauses), ([1000], []))
        app._ambient_sync()                                    # one retry is owed, not one for every failure
        self.assertEqual(len(app.later), 1)
        app.hypr.fail = None
        app.hypr.state["clients"] = [{"class": "gamescope", "workspace": {"id": 3}, "monitor": 0, "fullscreen": 0}]
        app.later.pop()[1]()
        self.assertEqual(app.living.pauses, [BOTH])
        app.hypr.fail = OSError("busy")                        # and what needs no asking is not held up by it
        self.assertEqual(app.command("ambient off"), "ambient off")
        self.assertEqual(app.living.pauses[-1], ALL)

    def test_the_sync_after_a_refresh(self):
        app = living_app()
        game = {"class": "gamescope", "workspace": {"id": 3}, "monitor": 0, "fullscreen": 0}
        app.hypr.asked.clear()
        app._ambient_sync((app.hypr.state["monitors"], [game]))                # what the refresh already asked for
        self.assertEqual((app.living.pauses[-1], app.hypr.asked), (BOTH, []))
        app.refresh = lambda: 1 / 0                            # a refresh that fails: the sync still runs, and asks for itself
        app.refresh_id = 3
        app.hypr.state["clients"] = []
        with contextlib.redirect_stderr(io.StringIO()):
            app._run_refresh()
        self.assertEqual(app.living.pauses[-1], set())

    def test_everywhere_means_monitors_that_come_later_too(self):
        host = living(self.files)
        host.pause(set(), everything=True)
        host.show("DP-1", MON, "/pics/a.jpg")
        self.assertTrue(host.screens["DP-1"].layer.paused)
        host.pause(set())
        self.assertFalse(host.screens["DP-1"].layer.paused)


# ---------------------------------------------------------------- the status wall
WALL_CTX = {"clock": "22:44", "second": 37.0, "date": "TUE 13 OCT 2026", "uptime": "04:12", "berserk": False,
            "magi": [{"value": 0.07, "label": "07%", "series": [0.07 + 0.3 * abs(math.sin(i / 7)) for i in range(61)]},
                     {"value": 0.52, "label": "9.8G", "series": [0.5 + 0.02 * math.sin(i / 9) for i in range(61)]},
                     {"value": 0.30, "label": "↓340K", "series": [abs(math.sin(i / 3)) ** 3 for i in range(61)]}],
            "net": "lan", "workspaces": [(n, "active" if n == 2 else "occupied" if n in (1, 3, 7) else "empty") for n in range(1, 11)],
            "music": {"status": "Playing", "title": "Walking on a Dream", "artist": "Empire of the Sun"}}


class WallKit(unittest.TestCase):
    frame = KitTest.frame

    def test_a_screen_is_a_bezel_a_face_and_a_tag(self):
        from eva_desk import draw as d
        got = []
        f = self.frame(lambda k: got.append(k.screen(100, 100, 400, 200, "MAGI-1", "CPU")))
        self.assertEqual(got, [(113, 128, 374, 162)])          # the box left for the content
        deep = tuple(round(c * 255) for c in d.col("ink_deep")[:3])[::-1]
        bezel = tuple(round(c * 255) for c in d.col("ink3")[:3])[::-1]
        self.assertTrue(near(px(f, 103, 200), bezel, tol=2) and near(px(f, 300, 290), deep, tol=14))       # the face, under its scanlines
        self.assertEqual((alpha(f, 98, 200), alpha(f, 300, 302), pink(f)), (0, 0, 0))
        self.assertTrue(any(max(px(f, x, y)[:3]) > 120 for x in range(113, 260) for y in range(108, 124)))  # the tag is set

    def test_a_sparkline(self):
        from eva_desk import draw as d
        from eva_desk.motion import Piece, render

        class P(Piece):
            length = 1.0

            def paint(self, kit, t, ctx):
                kit.spark(100, 100, 300, 100, ctx["values"], d.GOLD)
        f = render.frame(P(), 0.0, 1720, 720, {"values": [1.0] * 30 + [0.0] * 31})         # newest first: high on the right, low on the left
        self.assertGreater(alpha(f, 390, 102), 150)            # the line runs along the top at the right
        self.assertGreater(alpha(f, 390, 150), 15)             # and is filled faintly under it
        self.assertLess(alpha(f, 390, 150), 80)
        self.assertEqual(alpha(f, 110, 150), 0)                # nothing under a reading of nothing,
        self.assertGreater(alpha(f, 110, 197), 150)            # whose line lies on the floor
        self.assertEqual((alpha(f, 95, 150), alpha(f, 405, 150), alpha(f, 250, 95), alpha(f, 250, 205)), (0, 0, 0, 0))
        self.assertEqual(texture_widths(render.build(P(), 0.0, 1720, 720, {"values": [0.5] * 61})), [])
        for values in ([], [0.5], [2.0, -1.0, "x", None] * 5):
            self.assertEqual(pink(render.frame(P(), 0.0, 1720, 720, {"values": values})), 0)


    def test_what_is_still_is_kept_as_one_node(self):
        from eva_desk import draw as d, gtkutil  # noqa: F401
        from gi.repository import Gtk
        from eva_desk.motion.kit import Kit
        store, drawn = {}, []

        def build(key, dx=0.0, draw=None):
            snap = Gtk.Snapshot()
            kit = Kit(snap, 1720, 720, 1.0, store)
            with kit.transform(dx):
                kit.keep("slab", key, draw or (lambda: (drawn.append(key), kit.rect(100, 100, 50, 50, d.BONE))))
            kit.close()
            return snap.to_node()

        def painted(node, x, y):
            import cairo
            surf = cairo.ImageSurface(cairo.FORMAT_ARGB32, 400, 300)
            if node is not None:
                node.draw(cairo.Context(surf))
            surf.flush()
            return alpha(surf, x, y)
        first = build(("a",))
        self.assertEqual((painted(first, 120, 120), painted(first, 220, 120)), (255, 0))
        build(("a",))
        moved = build(("a",), dx=100.0)                        # the same node, wherever it is put
        self.assertEqual((drawn, painted(moved, 120, 120), painted(moved, 220, 120)), ([("a",)], 0, 255))
        build(("b",))                                          # what it shows changed: drawn again, once
        build(("b",))
        self.assertEqual(drawn, [("a",), ("b",)])
        self.assertEqual(len(store), 1)                        # one place for it, whatever it has shown
        self.assertIsNone(build(("c",), draw=lambda: None))    # nothing drawn is nothing kept, and no error


class WallTest(unittest.TestCase):
    def setUp(self):
        from eva_desk.motion import render
        from eva_desk.motion.amb import wall
        self.W, self.render = wall, render

    def test_only_what_moves_is_built_again(self):
        from eva_desk import gtkutil  # noqa: F401
        from gi.repository import Gtk
        from eva_desk.motion.kit import Kit
        loop, store, counts = self.W.WallLoop(), {}, []
        for t in (1.0, 1.05, 1.1):
            snap = Gtk.Snapshot()
            kit = Kit(snap, 1080, 1920, 1.0, store)
            calls = []
            kit.text = (lambda real: lambda *a, **kw: (calls.append(a[0]), real(*a, **kw))[1])(kit.text)
            loop.paint(kit, t, WALL_CTX)
            kit.close()
            counts.append(len(calls))
        self.assertGreater(counts[0], 20)                      # the first frame sets all the type
        self.assertEqual(counts[1:], [0, 0])                   # the next ones set none: it is kept

    def frame(self, t=3.0, w=1080, h=1920, **more):
        return self.render.frame(self.W.WallLoop(), t, w, h, {**WALL_CTX, **more})

    def test_a_minute_of_readings_read_back_at_any_moment(self):
        H = self.W.History
        h = H()
        self.assertEqual((h.at(5.0), h.series(5.0)), (0.0, [0.0] * 61))        # nothing yet: a flat line
        for second in range(100):
            h.push(float(second), second / 100)
        self.assertAlmostEqual(h.at(50.0), 0.50)
        self.assertAlmostEqual(h.at(50.25), 0.5025)            # between two samples: on the line between them
        self.assertEqual((h.at(200.0), h.at(99.0)), (0.99, 0.99))             # past the newest: held
        self.assertAlmostEqual(h.at(0.0), h.at(-50.0))         # before the oldest it still has: held too
        self.assertLessEqual(len(h.samples), 70)               # it keeps a minute, not everything
        series = h.series(99.0)
        self.assertEqual(len(series), 61)
        self.assertAlmostEqual(series[0], 0.99)                # newest first
        self.assertAlmostEqual(series[10], 0.89)
        a, b = h.series(98.0), h.series(98.1)
        self.assertTrue(all(0 < y - x < 0.002 for x, y in zip(a[:50], b[:50])))                  # it slides, it does not step
        h.push(100.0, "x")                                     # a reading that is not a number counts as none
        self.assertEqual(h.at(100.0), 0.0)

    def test_where_the_screens_go(self):
        W = self.W
        scale, columns = W.layout(1280, 1920 / 0.84375)        # the upright monitor: one column, the mock-up's own shape
        self.assertAlmostEqual(scale, 1280 / 540)
        self.assertEqual([[name for name, _ in col] for col in columns], [["time", "magi", "harmonics", "workspaces", "audio"]])
        for W_, H_, n in ((1720, 720, 2), (1280, 720, 2), (1600, 1200, 2), (2400, 720, 3)):          # as many columns as make the screens largest
            scale, columns = W.layout(W_, H_)
            self.assertEqual(len(columns), n, (W_, H_))
            self.assertEqual(sorted(name for col in columns for name, _ in col), ["audio", "harmonics", "magi", "time", "workspaces"])
            self.assertLessEqual(len(columns) * 540 * scale, W_ + 0.01)
            self.assertLessEqual(max(sum(h for _, h in col) for col in columns) * scale + 82 * scale, H_ + 0.01)       # with its header and both strips

    def test_it_paints_the_wall(self):
        f = self.frame()
        self.assertEqual(pink(f), 0)
        self.assertTrue(all(120 <= a <= 255 for a in grid(f)))                 # ink at 62 % everywhere, whole where a screen is
        self.assertAlmostEqual(alpha(f, 4, 960), 158, delta=3)                 # the margin: the wallpaper shows through
        self.assertEqual(alpha(f, 540, 400), 255)                              # the TIME screen
        self.assertTrue(same(f, self.frame()))
        self.assertFalse(same(f, self.frame(t=3.5)))                           # the hazard strips crawl, the waves move
        node = self.render.build(self.W.WallLoop(), 3.0, 1080, 1920, WALL_CTX)
        self.assertIn(round(128 * 0.75 * 2, 2), glyph_sizes(node))             # the clock at 128, twice the mock-up's size on this monitor

    def test_what_it_shows_follows_its_inputs(self):
        base = self.frame()
        for more in ({"clock": "09:05"}, {"second": 5.0}, {"uptime": "1D 02:00"}, {"berserk": True}, {"music": None},
                     {"music": {"status": "Paused", "title": "Walking on a Dream", "artist": "Empire of the Sun"}},
                     {"workspaces": [(n, "empty") for n in range(1, 11)]},
                     {"magi": [dict(m, value=0.95) for m in WALL_CTX["magi"]]}):
            self.assertFalse(same(base, self.frame(**more)), more)

    def test_every_size_and_odd_inputs(self):
        for w, h in ((1080, 1920), (3440, 1440), (1920, 1080), (1600, 1200)):
            f = self.frame(w=w, h=h)
            self.assertEqual(pink(f), 0, (w, h))
            self.assertTrue(same(f, self.frame(w=w, h=h)), (w, h))
        loop = self.W.WallLoop()
        for ctx in ({}, {"magi": []}, {"magi": [{}, {"value": "x", "series": None}, {"value": 7, "label": "L" * 90, "series": [9] * 3}]},
                    {"workspaces": [("x", None)] * 30}, {"music": {"title": "T" * 400, "artist": "مرحبا"}}, {"music": {}},
                    {"second": 99, "clock": None, "date": None, "uptime": None}):
            self.assertEqual(pink(self.render.frame(loop, 3.0, 1080, 1920, ctx)), 0, ctx)
        t = 7 * 86400 + 3.0
        self.assertEqual(pink(self.frame(t=t)), 0)

    def test_nothing_is_made_per_frame_and_the_type_keeps_its_size(self):
        from eva_desk import gtkutil  # noqa: F401
        from gi.repository import Gtk
        from eva_desk.motion.kit import Kit
        loop, store, sizes, glyphs = self.W.WallLoop(), {}, [], set()
        for t in (1.0, 2.0, 7.5, 13.0):
            kit = Kit(Gtk.Snapshot(), 1080, 1920, 1.0, store)
            loop.paint(kit, t, WALL_CTX)
            kit.close()
            sizes.append(len(store))
            glyphs |= glyph_sizes(self.render.build(loop, t, 1080, 1920, WALL_CTX))
        self.assertEqual(len(set(sizes)), 1, sizes)
        self.assertLessEqual(len(glyphs), 14, sorted(glyphs))
        self.assertEqual(texture_widths(self.render.build(loop, 3.0, 1080, 1920, WALL_CTX)), [])           # all of it is rectangles and type

    def test_the_registry_and_the_renderer(self):
        from eva_desk import motion
        self.assertEqual(list(motion.loops()), ["standby", "wallpaper", "wall"])
        loop = motion.loops()["wall"]()
        self.assertEqual((loop.name, loop.length, loop.covers), ("wall", None, False))
        f = self.render.frame(loop, 3.0, 1080, 1920, self.render.fixture_ctx())
        self.assertEqual(alpha(f, 540, 400), 255)


class WallRules(unittest.TestCase):
    def test_which_monitor_and_when(self):
        from eva_desk.motion import triggers as T
        mons = [{"id": 0, "name": "DP-1", "description": "Big Co ULTRAWIDE", "activeWorkspace": {"id": 1}},
                {"id": 1, "name": "DP-2", "description": "Small Co UPRIGHT 24", "activeWorkspace": {"id": 5}},
                {"id": 2, "name": "HDMI-A-1", "description": "Tele Vision", "activeWorkspace": {"id": 8}}]
        self.assertEqual(T.wall_monitor(mons, ["DP-1"], ""), "DP-2")           # the first that is not a main one
        self.assertEqual(T.wall_monitor(mons, ["DP-1"], "HDMI-A-1"), "HDMI-A-1")
        self.assertEqual(T.wall_monitor(mons, ["DP-1"], "Tele"), "HDMI-A-1")   # part of its description
        self.assertEqual(T.wall_monitor(mons, ["DP-1"], "DP-1"), None)         # never on a main monitor
        self.assertEqual(T.wall_monitor(mons, ["DP-1"], "nothing like it"), None)
        self.assertEqual(T.wall_monitor(mons, ["DP-1", "DP-2", "HDMI-A-1"], ""), None)
        self.assertEqual(T.wall_monitor(mons + [{"name": "DP-9", "disabled": True}], ["DP-1", "DP-2", "HDMI-A-1"], ""), None)
        self.assertEqual(T.wall_monitor(None, [], ""), None)
        term = {"class": "kitty", "workspace": {"id": 5}, "mapped": True}
        self.assertTrue(T.workspace_empty(mons[1], []))
        self.assertTrue(T.workspace_empty(mons[1], [{"class": "kitty", "workspace": {"id": 1}}]))          # a window somewhere else
        self.assertFalse(T.workspace_empty(mons[1], [term]))
        self.assertTrue(T.workspace_empty(mons[1], [dict(term, mapped=False)]))
        self.assertTrue(T.workspace_empty(mons[1], [dict(term, hidden=True)]))
        special = dict(mons[1], specialWorkspace={"id": -98, "name": "special:pad"})
        self.assertFalse(T.workspace_empty(special, [{"class": "kitty", "workspace": {"id": -98}}]))       # an open scratchpad counts
        self.assertTrue(T.workspace_empty(None, [term]) is False)


class FakeSampler:
    def __init__(self):
        self.next, self.calls = {"cpu": 7, "mem_used": 9.8 * 2 ** 30, "mem_total": 32 * 2 ** 30, "net": {"kind": "lan", "down": 340 * 1024}}, 0

    def sample(self, now=None):
        self.calls += 1
        if isinstance(self.next, Exception):
            raise self.next
        return self.next


def sidewall(**ambient_cfg):
    """A SideWall whose layer is ambient(), whose clock is its `now`, and whose timers are a list."""
    from eva_desk.motion.sidewall import SideWall
    cfg = config.load("/nonexistent")
    cfg["ambient"].update(ambient_cfg)
    wall = SideWall(object(), cfg, make=lambda app: ambient(keyboard="none"), clock=lambda: wall.now, sampler=FakeSampler(),
                    state=lambda: {"workspaces": [(1, "active")], "music": None})
    wall.now, wall.timers, wall.cancelled = 0.0, [], []
    wall._every = lambda ms, fn: wall.timers.append((ms, fn)) or len(wall.timers)
    wall._cancel = wall.cancelled.append
    wall.read_uptime = lambda: 4 * 3600 + 12 * 60 + 5.0
    return wall


class SideWallTest(NoCompositor):
    def test_it_is_up_while_it_is_given_a_monitor(self):
        wall = sidewall()
        self.assertFalse(wall.up)
        wall.sync("DP-2", MON2)
        self.assertTrue(wall.up and wall.layer.win.visible and wall.layer.win.surface.region.is_empty())
        self.assertEqual((wall.layer.piece.name, [ms for ms, _ in wall.timers], wall.sampler.calls), ("wall", [1000], 1))        # a reading at once, then one a second
        wall.sync("DP-2", MON2)                                # the same again: nothing
        self.assertEqual((len(wall.timers), len(wall.layer.timers)), (1, 1))
        wall.sync("DP-2", None)                                # a window opened there
        self.assertFalse(wall.up or wall.layer.win.visible)
        self.assertEqual(wall.cancelled, [1])                  # no reading while nobody sees it
        wall.sync("DP-2", MON2)
        again = FakeMonitor(1080, 1920)
        wall.sync("HDMI-A-1", again)                           # it moved to another monitor
        self.assertTrue(wall.up and wall.name == "HDMI-A-1")
        wall.stop()
        self.assertFalse(wall.up)

    def test_what_it_shows(self):
        wall = sidewall()
        wall.sync("DP-2", MON2)
        for second in range(1, 6):
            wall.now = float(second)
            wall.sampler.next = {"cpu": 10 * second, "mem_used": 16 * 2 ** 30, "mem_total": 32 * 2 ** 30, "net": {"kind": "wifi", "down": 2 ** 20 * second}}
            wall.sample()
        wall.now = 5.5
        ctx = wall.layer.inputs()
        self.assertEqual(sorted(ctx), ["berserk", "clock", "date", "magi", "music", "net", "second", "uptime", "workspaces"])
        self.assertEqual((ctx["uptime"], ctx["net"], ctx["workspaces"], ctx["music"], ctx["berserk"]), ("04:12", "wifi", [(1, "active")], None, False))
        cpu, mem, net = ctx["magi"]
        self.assertEqual((cpu["label"], mem["label"], net["label"]), ("50%", "16G", "↓5.0M"))               # the labels are the newest reading
        self.assertAlmostEqual(cpu["value"], 0.44)             # the curves run a second behind (in steps of a fifth), between two readings
        self.assertAlmostEqual(cpu["series"][1], 0.34)
        self.assertAlmostEqual(mem["value"], 0.5)
        self.assertAlmostEqual(net["value"], 4.4 / 5)          # against the most it has seen
        self.assertEqual(len(net["series"]), 61)
        self.assertTrue(all(0 <= v <= 1 for m in ctx["magi"] for v in m["series"]))

    def test_a_trickle_is_not_drawn_as_a_flood(self):
        wall = sidewall()
        wall.sync("DP-2", MON2)
        wall.now = 3.0
        self.assertLess(wall.layer.inputs()["magi"][2]["value"], 0.4)          # 340 K a second against a megabyte at least

    def test_it_is_taken_down_while_the_loops_stand_still(self):
        wall = sidewall()                                      # a clock that has stopped still reads as the time: no wall is better
        wall.sync("DP-2", MON2)
        wall.pause({"DP-1"})
        self.assertTrue(wall.up)
        wall.pause({"DP-1", "DP-2"})
        self.assertFalse(wall.up or wall.layer.win.visible)
        self.assertEqual(wall.cancelled, [1])                  # and no reading
        wall.sync("DP-2", MON2)                                # the desk says it belongs there: not while it stands still
        self.assertFalse(wall.up)
        wall.pause(set())
        self.assertTrue(wall.up and wall.layer.win.visible)
        self.assertEqual([ms for ms, _ in wall.timers][-1], 1000)
        wall.pause(set(), everything=True)
        self.assertFalse(wall.up)
        wall.sync("DP-2", None)                                # a window opened there meanwhile
        wall.pause(set())
        self.assertFalse(wall.up)
        wall.set_berserk(True)
        self.assertTrue(wall.inputs()["berserk"])

    def test_a_monitor_that_came_back_gets_a_new_layer(self):
        wall = sidewall()
        wall.sync("DP-2", MON2)
        first = wall.layer
        wall.sync("DP-2", None)
        wall.sync("DP-2", MON2)                                # a window came and went: the same monitor, the same layer
        self.assertIs(wall.layer, first)
        wall.sync("DP-2", None)
        back = FakeMonitor(1080, 1920)
        wall.sync("DP-2", back)                                # the monitor was off and on: its window went with it
        self.assertTrue(wall.layer is not first and first.win.destroyed and wall.up)

    def test_a_layer_that_breaks_stops_the_reading(self):
        wall = sidewall()
        wall.sync("DP-2", MON2)
        wall.layer._fail()
        self.assertEqual((wall.up, wall.cancelled), (False, [1]))
        wall.sync("DP-2", MON2)                                # and the next refresh puts it up again
        self.assertTrue(wall.up)

    def test_after_a_gap_the_minute_starts_again(self):
        wall = sidewall()
        wall.sync("DP-2", MON2)
        for second in (1.0, 2.0, 3.0):
            wall.now = second
            wall.sample()
        self.assertEqual(len(wall.cpu.samples), 4)
        wall.now = 300.0                                       # it was down for five minutes
        wall.sample()
        self.assertEqual([len(h.samples) for h in (wall.cpu, wall.mem, wall.net)], [1, 1, 1])      # no ramp drawn across the gap

    def test_a_sampler_that_fails(self):
        wall = sidewall()
        wall.sampler.next = OSError("no /proc")
        with contextlib.redirect_stdout(io.StringIO()) as out:
            wall.sync("DP-2", MON2)
            wall.sample()
        self.assertEqual(len(out.getvalue().splitlines()), 1)                  # said once
        self.assertEqual(wall.layer.inputs()["magi"][0]["label"], "--")
        self.assertTrue(wall.up)

    def test_it_runs_slower_than_the_other_loops_and_its_curves_step_five_times_a_second(self):
        self.assertEqual((sidewall(fps=60).fps, sidewall(fps=30).fps, sidewall(fps=10).fps), (15, 15, 10))
        wall = sidewall()
        wall.sync("DP-2", MON2)
        for second in range(1, 4):
            wall.now = float(second)
            wall.sampler.next = {"cpu": 10 * second, "mem_used": 16 * 2 ** 30, "mem_total": 32 * 2 ** 30, "net": {"kind": "lan", "down": 0}}
            wall.sample()
        wall.now = 3.41
        a = wall.inputs()["magi"][0]["series"]
        wall.now = 3.59
        self.assertEqual(a, wall.inputs()["magi"][0]["series"])                # the same fifth of a second: the same curve, so it is kept
        wall.now = 3.61
        self.assertNotEqual(a, wall.inputs()["magi"][0]["series"])

    def test_uptime(self):
        from eva_desk.motion.sidewall import uptime_text
        self.assertEqual([uptime_text(s) for s in (0, 59, 3600 * 4 + 12 * 60, 86400 * 3 + 3600 * 2 + 60, None, "x")],
                         ["00:00", "00:00", "04:12", "3D 02:01", "", ""])


class WallWiring(unittest.TestCase):
    def setUp(self):
        self.monitors = {"DP-1": "GDK-1", "DP-2": "GDK-2"}
        patch = mock.patch("eva_desk.gtkutil.monitors", lambda: dict(self.monitors))
        patch.start()
        self.addCleanup(patch.stop)

    def app(self):
        app = living_app()
        app.wall = types.SimpleNamespace(syncs=[], pauses=[], hot=[])
        app.wall.sync = lambda name, gdk: app.wall.syncs.append((name, gdk))
        app.wall.pause = lambda names, everything=False: app.wall.pauses.append(ALL if everything else set(names))
        app.wall.set_berserk = app.wall.hot.append
        return app

    def test_the_defaults(self):
        amb = config.load("/nonexistent")["ambient"]
        self.assertEqual((amb["wall"], amb["wall_monitor"]), (True, ""))
        self.assertIn("\nwall = true", (ROOT / "config" / "eva.example.toml").read_text())

    def test_it_goes_on_the_other_monitor_while_that_is_empty(self):
        app = self.app()
        mons, mains = app.hypr.state["monitors"], [app.hypr.state["monitors"][0]]
        wss = [{"id": 1, "windows": 2}, {"id": 5, "windows": 0}, {"id": 7, "windows": 1}]
        app._wall_sync(mons, [], wss, mains)
        self.assertEqual(app.wall.syncs, [("DP-2", "GDK-2")])
        self.assertEqual(app._wall_state()["workspaces"][:2], [(1, "active"), (2, "empty")])
        self.assertEqual(app._wall_state()["workspaces"][6], (7, "occupied"))
        self.assertEqual(len(app._wall_state()["workspaces"]), 10)
        app._wall_sync(mons, [{"class": "kitty", "workspace": {"id": 5}}], wss, mains)
        self.assertEqual(app.wall.syncs[-1], ("DP-2", None))   # a window is there now
        app.cfg["ambient"]["wall_monitor"] = "nothing like it"
        app._wall_sync(mons, [], wss, mains)
        self.assertEqual(app.wall.syncs[-1], (None, None))
        app.cfg["ambient"]["wall_monitor"] = ""
        self.monitors.pop("DP-2")                              # Hyprland knows it, GTK not yet
        app._wall_sync(mons, [], wss, mains)
        self.assertEqual(app.wall.syncs[-1], ("DP-2", None))
        app.wall = None
        app._wall_sync(mons, [], wss, mains)

    def test_what_it_is_told(self):
        app = self.app()
        app.music_state = {"status": "Playing", "title": "T", "artist": "A"}
        self.assertEqual(app._wall_state(), {"workspaces": [], "music": app.music_state})
        app._ambient_sync()
        self.assertEqual((app.wall.pauses, app.living.pauses), ([set()], [set()]))
        app.command("ambient off")
        self.assertEqual(app.wall.pauses[-1], ALL)
        app.cfg["overlays"].update(berserk=90, berserk_seconds=0)
        app._berserk_check(99, 10)
        self.assertEqual(app.wall.hot, [True])
        app.living = app.standby = None                        # the wall alone still has the lock watched
        self.assertTrue(app._has_loops())
