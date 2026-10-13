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
            self.assertEqual(sorted(p.name for p in out), sorted(f"motion_{n}.png" for n in motion.pieces()))

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
        self.visible = False


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

    def __init__(self):
        self.state, self.execs = {}, []

    def j(self, what):
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
        self.assertIn("|pulse|motion|panel-", (ROOT / "hypr" / "eva.lua").read_text())

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
