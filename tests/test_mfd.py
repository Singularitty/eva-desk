"""MFD drawing language tests: no compositor, no windows. Run: python3 -m unittest discover -s tests"""
import os
import sys
import unittest
from pathlib import Path
from unittest import mock

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


class FakePanel:
    """Records opens/closes; `open` plays the real exclusivity move a Panel.open() would."""

    def __init__(self, app, name):
        self.app, self.name = app, name
        self.opened, self.closed = 0, 0

    def open(self, gdk):
        self.app.close_panels(except_name=self.name)
        self.opened += 1
        return "ok"

    def close(self):
        self.closed += 1


def FakeApp():
    from eva_desk.app import App
    app = App.__new__(App)
    app.panels = {}
    return app


class PanelBase(unittest.TestCase):
    def test_panel_rect_anchors(self):
        from eva_desk.mfd import panel
        cfg = config.load("/nonexistent")
        r = panel.panel_rect("left", 3440, 1440, 1100, 1300, cfg["bar"]["height"], margin=12)
        self.assertEqual(r, (12, 56 + 12, 1100, 1300))
        r = panel.panel_rect("bottom", 3440, 1440, 3416, 320, 56, 12)
        self.assertEqual(r, (12, 1440 - 12 - 320, 3416, 320))
        r = panel.panel_rect("bottom", 3440, 1440, 1000, 300, 56, 12)
        self.assertEqual(r, (12, 1440 - 12 - 300, 1000, 300))   # flush left, not centred
        r = panel.panel_rect("center", 3440, 1440, 1000, 600, 56, 12)
        self.assertEqual(r, (1220, 56 + (1440 - 56 - 600) // 2, 1000, 600))

    def test_panel_exclusive(self):
        app = FakeApp()
        a, b = FakePanel(app, "a"), FakePanel(app, "b")
        app.panels = {"a": a, "b": b}
        self.assertEqual(app.open_panel("a", None), "ok")
        self.assertEqual(app.open_panel("b", None), "ok")
        self.assertEqual((a.opened, a.closed, b.opened), (1, 1, 1))
        self.assertEqual(app.open_panel("zzz", None), "zzz disabled")


class FakeSurface:
    def __init__(self, visible):
        self._visible = visible

    def get_visible(self):
        return self._visible


def bare_panel(visible=True, closing=False, t=1.0):
    """A Panel built with `__new__` (no GTK objects touched) with just enough state for the
    close()/_finish_close() lifecycle guards; `animate`/`on_close`/`hide` are mocks."""
    from eva_desk.mfd.panel import Panel
    p = Panel.__new__(Panel)
    p.win = FakeSurface(visible)
    p._closing, p.t, p._close_from = closing, t, 1.0
    p.animate = mock.Mock()
    p.on_close = mock.Mock()
    p.hide = mock.Mock()
    return p


class PanelLifecycle(unittest.TestCase):
    def test_close_on_hidden_panel_is_a_noop(self):
        p = bare_panel(visible=False, closing=False)
        p.close()
        p.animate.assert_not_called()
        self.assertFalse(p._closing)

    def test_second_close_while_closing_does_not_restart(self):
        p = bare_panel(visible=True, closing=False, t=1.0)
        p.close()                                        # starts the close snap
        p.close()                                        # already closing: must be a no-op
        p.animate.assert_called_once()

    def test_finish_close_is_a_noop_when_not_closing(self):
        p = bare_panel(visible=True, closing=False)
        p._finish_close()
        p.on_close.assert_not_called()
        p.hide.assert_not_called()

    def test_finish_close_runs_when_closing(self):
        p = bare_panel(visible=True, closing=True)
        p._finish_close()
        p.on_close.assert_called_once()
        p.hide.assert_called_once()
        self.assertFalse(p._closing)


class Progress(unittest.TestCase):
    def test_progress_rule(self):
        from eva_desk.mfd.panel import _progress
        self.assertEqual(_progress(1.0, True), 0.0)
        self.assertAlmostEqual(_progress(0.3, True), 0.7)
        self.assertEqual(_progress(0.3, False), 0.3)


if __name__ == "__main__":
    unittest.main()
