"""MFD drawing language tests: no compositor, no windows. Run: python3 -m unittest discover -s tests"""
import json
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


class Sound(unittest.TestCase):
    def setUp(self):
        from eva_desk.mfd import sound
        self.sound = sound
        self.state = json.loads((Path(__file__).parent / "fixtures" / "audiostate.json").read_text())
        self.m = sound.SoundModel(self.state, {"dnd": False, "night": True, "power": "balanced"})

    def test_sections_and_rows(self):
        self.assertEqual([s["key"] for s in self.m.sections], ["sinks", "sources", "apps", "recs", "quick"])
        first = self.m.sections[0]["rows"][0]
        self.assertEqual(first["kind"], "sink")
        self.assertTrue(0.0 <= first["value"] <= 1.0)

    def test_actions(self):
        self.m.sel = (0, 0)
        row = self.m.sections[0]["rows"][0]
        self.assertEqual(self.m.action("right"), [("set_volume", "sink", row["id"], min(100, round(row["value"] * 100) + 5))])
        self.assertEqual(self.m.action("mute"), [("toggle_mute", "sink", row["id"])])
        self.assertEqual(self.m.action("dnd"), [("quick_toggle", "dnd")])
        self.m.action("next_section"); self.assertEqual(self.m.sel[0], 1)
        self.m.sel = (2, 0)
        self.assertEqual(self.m.action("down"), [])                     # moving returns no calls
        self.assertEqual(self.m.sel, (2, 1))
        app = self.m.sections[2]["rows"][1]                              # the stream "down" moved to
        self.assertEqual(self.m.pick(0), [("move", "sink-input", app["id"], self.m.sections[0]["rows"][0]["target"])])

    def test_levels_update_in_place(self):
        sid = self.m.sections[0]["rows"][0]["id"]
        self.m.levels({f"sink{sid}": {"v": 12, "m": True}})
        self.assertEqual((self.m.sections[0]["rows"][0]["value"], self.m.sections[0]["rows"][0]["muted"]), (0.12, True))

    def test_sound_long_names_render(self):
        import cairo
        self.state["apps"][0]["app"] = "WEBRTC VoiceEngine"
        self.state["apps"][0]["title"] = "Making a CHICAGO STYLE Deep dish pizza?!? #youtube #shorts " * 3
        m = self.sound.SoundModel(self.state, {"dnd": False, "night": False, "power": "balanced"})
        surf = cairo.ImageSurface(cairo.FORMAT_ARGB32, 1100, 1300)
        hits, sections = self.sound.draw_sound(cairo.Context(surf), 0, 0, 1100, 1300, m, False)
        bars = [h for h in hits if isinstance(h[4], tuple)]
        self.assertTrue(all(h[2] - h[0] > 300 for h in bars))            # the bar keeps its width
        self.assertEqual(len(sections), 5)

    def test_sound_no_signal_render(self):
        import cairo
        m = self.sound.SoundModel(None, {"dnd": False, "night": False, "power": "unknown"})
        surf = cairo.ImageSurface(cairo.FORMAT_ARGB32, 1100, 1300)
        hits, sections = self.sound.draw_sound(cairo.Context(surf), 0, 0, 1100, 1300, m, True)
        self.assertEqual(hits, [])
        self.assertGreater(sum(surf.get_data()), 0)

    # ---- beyond the brief: the model's edges and the panel's input routing

    def test_volume_clamps_and_waits_for_levels(self):
        self.m.sel = (1, 1)                                              # the webcam mic, at 100
        self.assertEqual(self.m.action("right"), [("set_volume", "source", 68, 100)])
        self.assertEqual(self.m.action("left"), [("set_volume", "source", 68, 95)])
        self.assertEqual(self.m.sections[1]["rows"][1]["value"], 1.0)   # the levels line reports it
        self.m.levels({"source68": {"v": 95, "m": False}})
        self.assertEqual(self.m.action("left"), [("set_volume", "source", 68, 90)])
        self.m.sel = (0, 0)
        self.m.levels({"sink50": {"v": 3, "m": False}})
        self.assertEqual(self.m.action("left"), [("set_volume", "sink", 50, 0)])

    def test_default_only_for_devices(self):
        self.m.sel = (0, 1)
        self.assertEqual(self.m.action("default"), [("set_default", "sink", self.state["sinks"][1]["name"])])
        self.m.sel = (2, 0)
        self.assertEqual(self.m.action("default"), [])

    def test_move_flows_across_sections_and_skips_empty(self):
        state = dict(self.state, recs=[])
        m = self.sound.SoundModel(state, {"dnd": False, "night": False, "power": "balanced"})
        m.sel = (2, 2)                                                    # last app
        m.move(1)
        self.assertEqual(m.sel, (4, 0))                                   # recs are empty: straight to quick
        m.move_section(-1)
        self.assertEqual(m.sel[0], 2)
        m.sel = (0, 0)
        m.move(-1)
        self.assertEqual(m.sel, (0, 0))                                   # clamped at the top

    def test_no_state_selects_quick(self):
        m = self.sound.SoundModel(None, {"dnd": False, "night": False, "power": "unknown"})
        self.assertEqual(m.sel, (4, 0))
        self.assertEqual(m.action("right"), [])

    def test_levels_for_streams_and_recs(self):
        self.m.levels({"app120": {"v": 40, "m": True}, "rec131": {"v": 150, "m": False}, "sink999": {"v": 1, "m": True}})
        app = next(r for r in self.m.sections[2]["rows"] if r["id"] == 120)
        rec = self.m.sections[3]["rows"][0]
        self.assertEqual((app["value"], app["muted"]), (0.4, True))
        self.assertEqual(rec["value"], 1.0)                              # clamped to 0..1

    def test_pick_on_a_rec_and_out_of_range(self):
        self.m.sel = (3, 0)
        self.assertEqual(self.m.pick(1), [("move", "source-output", 131, self.state["sources"][1]["name"])])
        self.assertEqual(self.m.pick(9), [])
        self.m.sel = (0, 0)
        self.assertEqual(self.m.pick(0), [])                              # devices have no picker

    def test_set_from_bar_selects_and_sets(self):
        self.assertEqual(self.m.set_from_bar(2, 1, 0.333), [("set_volume", "sink-input", 120, 33)])
        self.assertEqual(self.m.sel, (2, 1))
        self.assertEqual(self.m.set_from_bar(2, 1, 1.7), [("set_volume", "sink-input", 120, 100)])

    def test_quick_toggles_update_locally(self):
        self.assertEqual(self.m.action("night"), [("quick_toggle", "night")])
        self.assertFalse(self.m.quick["night"])
        self.assertEqual(self.m.action("power"), [("quick_toggle", "power")])
        self.assertEqual(self.m.quick["power"], "power-saver")            # the script's cycle order

    def test_sound_importable_without_gtk(self):
        import subprocess
        code = ("import sys; sys.path.insert(0, %r); import eva_desk.mfd.sound; "
                "print('gi.repository.Gtk' in sys.modules)") % str(Path(__file__).resolve().parent.parent)
        out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
        self.assertEqual(out.stdout.strip(), "False", out.stderr)


class SoundRouting(unittest.TestCase):
    """SoundControls (SoundPanel minus GTK): keys, clicks and scrolls turn into audio calls."""

    def setUp(self):
        from eva_desk.mfd import sound
        self.sound = sound
        state = json.loads((Path(__file__).parent / "fixtures" / "audiostate.json").read_text())
        self.p = sound.SoundControls.__new__(sound.SoundControls)
        self.p.model = sound.SoundModel(state, {"dnd": False, "night": False, "power": "balanced"})
        self.p.no_signal = False
        self.p.scale = 1
        self.p.invalidate = mock.Mock()
        self.audio = mock.patch.multiple(sound.audio, set_volume=mock.DEFAULT, toggle_mute=mock.DEFAULT,
                                         set_default=mock.DEFAULT, move=mock.DEFAULT, quick_toggle=mock.DEFAULT)
        self.calls = self.audio.start()
        self.addCleanup(self.audio.stop)

    def test_keys(self):
        self.assertTrue(self.p.on_key("Right", 0))
        self.calls["set_volume"].assert_called_once_with("sink", 50, 73)
        self.assertTrue(self.p.on_key("j", 0))
        self.assertEqual(self.p.model.sel, (0, 1))
        self.p.on_key("m", 0)
        self.calls["toggle_mute"].assert_called_once_with("sink", 61)
        self.p.on_key("2", 0)
        self.calls["quick_toggle"].assert_called_once_with("night")
        self.p.on_key("Tab", 0)
        self.assertEqual(self.p.model.sel[0], 1)
        self.assertFalse(self.p.on_key("q", 0))

    def test_picker_by_return_and_digit(self):
        self.p.model.sel = (2, 1)                                         # Firefox, on the Scarlett
        self.p.on_key("Return", 0)
        self.assertEqual(self.p.model.picker, 1)                           # starts on its current device
        self.p.on_key("Left", 0)
        self.p.on_key("Return", 0)
        self.calls["move"].assert_called_once_with("sink-input", 120, self.p.model.sections[0]["rows"][0]["target"])
        self.assertIsNone(self.p.model.picker)
        self.p.on_key("Return", 0)
        self.p.on_key("2", 0)                                              # a digit picks, not a quick toggle
        self.assertEqual(self.calls["move"].call_args.args[2], self.p.model.sections[0]["rows"][1]["target"])
        self.calls["quick_toggle"].assert_not_called()

    def test_clicks_and_scroll(self):
        import cairo
        surf = cairo.ImageSurface(cairo.FORMAT_ARGB32, 1100, 1300)
        self.p.hits, self.p.sections = self.sound.draw_sound(cairo.Context(surf), 0, 0, 1100, 1300, self.p.model, False)
        bar = next(h for h in self.p.hits if isinstance(h[4], tuple) and h[4][0] == "bar" and h[4][1:] == (1, 0))
        self.p.on_click(bar[0] + 0.25 * (bar[2] - bar[0]), (bar[1] + bar[3]) / 2, 1)
        self.calls["set_volume"].assert_called_once_with("source", 55, 25)
        self.assertEqual(self.p.model.sel, (1, 0))
        row = next(h for h in self.p.hits if h[4] == (2, 2))
        self.p.on_click(row[0] + 4, row[1] + 4, 1)
        self.assertEqual(self.p.model.sel, (2, 2))
        self.p.on_scroll(row[0] + 4, row[1] + 4, 1)                       # scroll down: -5
        self.calls["set_volume"].assert_called_with("sink-input", 130, 95)
        dnd = next(h for h in self.p.hits if h[4] == "dnd")
        self.p.on_click(dnd[0] + 1, dnd[1] + 1, 1)
        self.calls["quick_toggle"].assert_called_once_with("dnd")
