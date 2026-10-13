"""Motion: timeline, kit, renderer, player and the launch sequences. No compositor, no windows."""
import contextlib
import io
import math
import os
import shutil
import subprocess
import sys
import tempfile
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
        self.assertEqual(sorted(motion.pieces()), ["card", "shaft"])
        self.assertEqual({n: p().name for n, p in motion.pieces().items()}, {"card": "card", "shaft": "shaft"})

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
                node = render.build(piece, piece.length * (i + 0.5) / 120, 1720, 720, CTX)
                sizes |= glyph_sizes(node) if node is not None else set()
            self.assertLessEqual(len(sizes), 8, (name, sorted(sizes)))

    def test_prepare_makes_the_stamps_before_the_first_frame(self):
        from eva_desk import gtkutil  # noqa: F401
        from gi.repository import Gtk
        from eva_desk.motion import pieces
        from eva_desk.motion.kit import Kit
        for name, cls in pieces().items():
            piece, store = cls(), {}
            kit = Kit(Gtk.Snapshot(), 1720, 720, 1, store)
            piece.prepare(kit, CTX)
            kit.close()
            made = len(store)
            self.assertGreater(made, 0, name)
            for i in range(60):
                kit = Kit(Gtk.Snapshot(), 1720, 720, 1, store)
                piece.draw(kit, piece.length * (i + 0.5) / 60, CTX)
                kit.close()
            self.assertEqual(len(store), made, name)                          # no frame had to make one

    def test_stills_for_the_standing_render(self):
        from eva_desk import preview
        with tempfile.TemporaryDirectory() as tmp:
            out = preview.motion_stills(tmp, 640, 360)
            self.assertEqual(sorted(p.name for p in out), ["motion_card.png", "motion_shaft.png"])

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


class FakeView:
    def queue_draw(self):
        pass

    def add_tick_callback(self, fn):
        return 1

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


class PlayerTest(unittest.TestCase):
    def setUp(self):
        from eva_desk import gtkutil  # noqa: F401
        from gi.repository import Gtk4LayerShell as LS
        patch = mock.patch.object(LS, "set_monitor")      # place() names the monitor to the compositor; there is none here
        patch.start()
        self.addCleanup(patch.stop)

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

    def play(self, piece, mon, ctx, on_done=None):
        self.calls.append((piece, mon, ctx))
        return True


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
        self.assertEqual(app.command("play nope"), "unknown piece: nope (card, shaft)")
        self.assertEqual(app.command("play"), "play: card | shaft")
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
