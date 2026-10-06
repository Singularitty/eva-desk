"""MFD drawing language tests: no compositor, no windows. Run: python3 -m unittest discover -s tests"""
import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.pop("WAYLAND_DISPLAY", None)

from eva_desk import config  # noqa: E402,F401


class Widgets(unittest.TestCase):
    def setUp(self):
        from eva_desk.mfd import widgets
        self.w = widgets

    def test_segments_count_and_bounds(self):
        segs = self.w.segments(1000)
        self.assertEqual(len(segs), 31)
        self.assertLessEqual(segs[-1][0] + segs[-1][1], 1000)
        self.assertAlmostEqual(segs[1][0] - segs[0][0], 32, delta=0.01)

    def test_snap_scale_steps(self):
        s = self.w.snap_scale
        self.assertEqual(s(0.0), 0.02)
        self.assertEqual(s(0.39), 0.02)
        self.assertAlmostEqual(s(0.55), 0.02 + 0.98 * 1 / 4)
        self.assertEqual(s(1.0), 1.0)
        self.assertEqual(s(2.0), 1.0)

    def test_stagger(self):
        self.assertEqual(self.w.stagger(0, 0.5), 0.5)
        self.assertEqual(self.w.stagger(1, 0.0), 0.0)
        self.assertAlmostEqual(self.w.stagger(1, 1.0), (380 - 120) / 380)

    def test_rows_hit_map_and_drawing(self):
        import cairo
        surf = cairo.ImageSurface(cairo.FORMAT_ARGB32, 600, 200)
        items = [{"label": "AG346UCD", "sub": "HDMI · DEFAULT", "value": .68, "peak": None, "muted": False, "colour": None},
                 {"label": "X" * 200, "sub": "", "value": 1.0, "peak": .5, "muted": True, "colour": None}]
        hits = self.w.rows(cairo.Context(surf), 10, 10, 580, items, 0)
        self.assertEqual([h[4] for h in hits if not isinstance(h[4], tuple)], [0, 1])
        self.assertEqual([h[4] for h in hits if isinstance(h[4], tuple)], [("bar", 0), ("bar", 1)])
        self.assertGreater(sum(surf.get_data()), 0)

    def test_screen_returns_content_rect_inside_face(self):
        import cairo
        surf = cairo.ImageSurface(cairo.FORMAT_ARGB32, 400, 300)
        cx, cy, cw, ch = self.w.screen(cairo.Context(surf), 10, 10, 380, 280, "SOUND", hot="HOT")
        self.assertGreater(cx, 10)
        self.assertGreater(cy, 10)
        self.assertGreater(cw, 0)
        self.assertGreater(ch, 0)
        self.assertLess(cx + cw, 10 + 380)
        self.assertLess(cy + ch, 10 + 280)
        self.assertGreater(sum(surf.get_data()), 0)

    def test_lamp_and_keyrow_draw_and_hit_map(self):
        import cairo
        surf = cairo.ImageSurface(cairo.FORMAT_ARGB32, 400, 100)
        cr = cairo.Context(surf)
        self.w.lamp(cr, 10, 10, 16, False)
        self.w.lamp(cr, 40, 10, 16, True)
        self.w.lamp(cr, 70, 10, 16, True, hot=True)
        hits = self.w.keyrow(cr, 10, 40, ["MUTE", "UP", "DOWN"], active=1)
        self.assertEqual([h[4] for h in hits], [0, 1, 2])
        self.assertEqual(hits[0][0], 10)
        self.assertGreater(sum(surf.get_data()), 0)

    def test_screen_tag_and_hot_have_a_gap(self):
        import cairo
        from eva_desk import draw as d
        surf = cairo.ImageSurface(cairo.FORMAT_ARGB32, 10, 10)
        cr = cairo.Context(surf)
        tag_w, tag_h, hot_x = self.w._tag_positions(cr, "AUDIO OUTPUT", "HOT")
        self.assertGreater(tag_h, 0)
        space_w, _ = d.text_size(d.layout(cr, " ", d.F_META, 11, spacing=3))
        self.assertGreaterEqual(hot_x - tag_w, space_w)   # "AUDIO OUTPUT" and "HOT" never run together

    def test_value_readout_clamped_and_right_aligned(self):
        import cairo
        from eva_desk import draw as d
        surf = cairo.ImageSurface(cairo.FORMAT_ARGB32, 10, 10)
        cr = cairo.Context(surf)
        right_edge = 500
        text68, x68 = self.w._value_readout(cr, right_edge, .68)
        text100, x100 = self.w._value_readout(cr, right_edge, 1.0)
        text170, x170 = self.w._value_readout(cr, right_edge, 1.7)
        self.assertEqual((text68, text100, text170), ("68", "100", "100"))   # clamped to 0..100
        w68 = d.text_size(d.layout(cr, text68, d.F_META, 13))[0]
        w100 = d.text_size(d.layout(cr, text100, d.F_META, 13))[0]
        w170 = d.text_size(d.layout(cr, text170, d.F_META, 13))[0]
        # same right edge regardless of the digit count: the bar's clearance never shifts
        self.assertAlmostEqual(x68 + w68, x100 + w100)
        self.assertAlmostEqual(x100 + w100, x170 + w170)


if __name__ == "__main__":
    unittest.main()
