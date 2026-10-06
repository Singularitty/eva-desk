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
        st = self.w.stagger
        self.assertEqual(st(0, 0.0, 5), 0)
        self.assertEqual(st(0, 0.6, 5), 1)
        self.assertEqual(st(4, 0.4, 5), 0)                 # the last section starts at 40 %
        self.assertEqual(st(4, 1.0, 5), 1)                 # ...and is fully open at the end
        self.assertAlmostEqual(st(2, 0.5, 5), (0.5 - 0.2) / 0.6)
        for t in (0.0, 0.3, 0.6, 0.9):
            self.assertAlmostEqual(st(0, t, 1), max(0.0, min(1.0, t / 0.6)))

    def test_every_section_opens_by_the_end(self):
        for n in (1, 2, 5, 9):
            self.assertEqual([self.w.stagger(i, 1.0, n) for i in range(n)], [1] * n)

    def test_selected_block_clears_the_sub_line(self):
        bx, by, bw, bh = self.w.selected_block(10, 20, 80, 17)
        self.assertLessEqual(by + bh, self.w.sub_y(20, 17))
        self.assertLess(by, 20)                            # still frames the label

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

    def test_screen_tag_and_hot_share_one_line_with_a_gap(self):
        import cairo
        from eva_desk import draw as d
        surf = cairo.ImageSurface(cairo.FORMAT_ARGB32, 10, 10)
        cr = cairo.Context(surf)
        for tag in ("AUDIO OUTPUT", "出力 · OUTPUT · SINKS"):                # the kanji pull in a CJK fallback
            lay, start = self.w.tag_layout(cr, tag, "· ACTIVE")
            self.assertEqual(lay.get_line_count(), 1)                         # one line: one baseline, one height
            self.assertEqual(lay.get_text()[len(tag)], " ")
            tag_end = lay.index_to_pos(len(tag.encode())).x                   # where the tag's last glyph ends
            hot_x = lay.index_to_pos(start).x
            space_w = d.text_size(d.layout(cr, " ", d.F_META, 11, spacing=3))[0] * 1024
            self.assertGreaterEqual(hot_x - tag_end, space_w * 0.9)           # "OUTPUT" and "ACTIVE" never run together
            gold = [a for a in lay.get_attributes().get_attributes() if a.klass.type == d.Pango.AttrType.FOREGROUND]
            self.assertEqual([(a.start_index, a.end_index) for a in gold], [(start, len(lay.get_text().encode()))])
        lay, start = self.w.tag_layout(cr, "SOUND")
        self.assertIsNone(start)
        self.assertEqual(lay.get_text(), "SOUND")

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


class FakeWin:
    def __init__(self, visible=False):
        self.visible = visible

    def get_visible(self):
        return self.visible

    def get_surface(self):
        return None


class FakeModal:
    """A launcher / power / alt-tab stand-in: `visible` and a recording `hide()`."""

    def __init__(self, visible):
        self.visible, self.hidden = visible, 0

    def hide(self):
        self.visible = False
        self.hidden += 1


def live_panel(app=None, w=3440, h=1440, name="sound"):
    """A real Panel (built with `__new__`, no GTK) wired to a fake app, so `open()`, `close()`
    and `_click()` run their real code; `show`/`hide` flip the fake window, `animate` and the
    subclass hooks are mocks."""
    from eva_desk.mfd.panel import Panel
    p = Panel.__new__(Panel)
    p.app = app or FakeApp()
    p.app.panels[name] = p
    p.cfg = config.load("/nonexistent")
    p.name, p.anchor, p.pwidth, p.pheight = name, "left", 1100, 1300
    p.w, p.h, p.scale = w, h, 1
    p.px = p.py = p.pw = p.ph = 0
    p.win = FakeWin(False)
    p._closing, p.t, p._close_from = False, 1.0, 1.0
    p._base = p._base_tex = None
    p.animate = mock.Mock()
    p.on_open, p.on_close = mock.Mock(), mock.Mock()
    p.on_click = mock.Mock()
    p.show = mock.Mock(side_effect=lambda: setattr(p.win, "visible", True))
    p.hide = mock.Mock(side_effect=lambda: setattr(p.win, "visible", False))
    return p


class PanelModal(unittest.TestCase):
    def test_open_without_a_monitor_shows_nothing(self):
        p = live_panel(w=0, h=0)
        self.assertEqual(p.open(None), "no monitor")
        p.show.assert_not_called()
        p.animate.assert_not_called()
        p.on_open.assert_not_called()

    def test_open_twice_runs_on_open_once(self):
        p = live_panel()
        self.assertEqual(p.open(None), "ok")
        self.assertEqual(p.open(None), "ok")                 # already open: no second listener
        p.on_open.assert_called_once()
        p.show.assert_called_once()

    def test_reopen_while_closing_pairs_the_hooks(self):
        p = live_panel()
        p.open(None)
        p.close()
        self.assertTrue(p._closing)
        p.open(None)                                         # cancels the close snap
        self.assertEqual((p.on_open.call_count, p.on_close.call_count), (2, 1))
        self.assertFalse(p._closing)

    def test_open_steps_the_launcher_and_modal_overlays_aside(self):
        app = FakeApp()
        app.launcher = FakeModal(True)
        app.overlays = {"power": FakeModal(True), "alttab": FakeModal(False), "alarm": FakeModal(True)}
        p = live_panel(app)
        p.open(None)
        self.assertEqual(app.launcher.hidden, 1)
        self.assertEqual(app.overlays["power"].hidden, 1)
        self.assertEqual(app.overlays["alttab"].hidden, 0)   # was not up: left alone
        self.assertEqual(app.overlays["alarm"].hidden, 0)    # not modal: the band stays

    def test_open_closes_the_other_panels(self):
        app = FakeApp()
        a, b = live_panel(app, name="a"), live_panel(app, name="b")
        a.open(None)
        b.open(None)
        self.assertTrue(a._closing)                          # a's close snap runs
        a.animate.assert_called_with(190, on_done=a._finish_close)

    def test_click_outside_the_rectangle_closes(self):
        p = live_panel()
        p.open(None)
        gesture = mock.Mock()
        gesture.get_current_button.return_value = 1
        p._click(gesture, 1, p.px + 5, p.py + 5)             # inside: the panel handles it
        p.on_click.assert_called_once_with(5, 5, 1)
        self.assertFalse(p._closing)
        p._click(gesture, 1, p.px + p.pw + 40, p.py + 5)     # outside (to its right): closes
        self.assertTrue(p._closing)
        self.assertEqual(p.on_click.call_count, 1)

    def test_input_region_is_the_whole_monitor(self):
        import cairo
        p = live_panel(w=6880, h=2880)
        p.scale = 2
        surf = mock.Mock()
        p.win.get_surface = lambda: surf
        p.place(None)
        region = surf.set_input_region.call_args.args[0]
        self.assertEqual(region.get_extents(), cairo.RectangleInt(0, 0, 3440, 1440))   # logical px


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

    def test_screens_are_content_sized_and_stacked(self):
        import cairo
        surf = cairo.ImageSurface(cairo.FORMAT_ARGB32, 1100, 1300)
        cr = cairo.Context(surf)
        hits, sections = self.sound.draw_sound(cr, 0, 0, 1100, 1300, self.m, False)
        extra = self.sound._screen_extra(cr)
        self.assertLessEqual(sections[0][1], extra + 2 * self.sound.ROW_H + self.sound.GAP)   # two sinks
        for (y0, h0), (y1, _) in zip(sections, sections[1:]):
            self.assertAlmostEqual(y0 + h0, y1)                                             # stacked, no holes
        self.assertAlmostEqual(sections[-1][0] + sections[-1][1], 1300)                     # the snap covers the rest
        rows = {(si, ri) for si in range(4) for ri in range(len(self.m.sections[si]["rows"]))}
        self.assertEqual(rows - {h[4] for h in hits}, set())                               # every row fits its screen

    def test_screens_shrink_when_crowded(self):
        import cairo
        state = dict(self.state, apps=[dict(self.state["apps"][0], index=200 + i) for i in range(40)])
        m = self.sound.SoundModel(state, {"dnd": False, "night": False, "power": "balanced"})
        m.sel = (2, 39)
        surf = cairo.ImageSurface(cairo.FORMAT_ARGB32, 1100, 900)
        hits, sections = self.sound.draw_sound(cairo.Context(surf), 0, 0, 1100, 900, m, False)
        self.assertLessEqual(sections[-1][0] + sections[-1][1], 900 + 1)
        self.assertIn((2, 39), [h[4] for h in hits])                                        # the selection stays in view

    def test_held_steps_accumulate_until_levels_report(self):
        self.m.sel = (0, 0)                                              # the monitor, at 68
        self.assertEqual(self.m.action("right"), [("set_volume", "sink", 50, 73)])
        self.assertEqual(self.m.action("right"), [("set_volume", "sink", 50, 78)])
        self.m.levels({"sink50": {"v": 70, "m": False}})                 # the report clears the pending step
        self.assertEqual(self.m.action("right"), [("set_volume", "sink", 50, 75)])
        self.assertEqual(self.m.set_from_bar(0, 0, 0.2), [("set_volume", "sink", 50, 20)])
        self.assertEqual(self.m.action("left"), [("set_volume", "sink", 50, 15)])

    def _struct(self, state=None):
        """`audiostate --struct`: the layout without volume or mute."""
        st = json.loads(json.dumps(state or self.state))
        for key in ("sinks", "sources", "apps", "recs"):
            for row in st[key]:
                row.pop("volume", None)
                row.pop("muted", None)
        return st

    def test_struct_rebuild_keeps_volumes_and_mutes(self):
        self.m.levels({"sink50": {"v": 41, "m": True}, "app120": {"v": 12, "m": False}})
        st = self._struct()
        st["sinks"].append(dict(st["sinks"][0], id=99, name="new-sink", default=False))
        st["sources"].append(dict(self.state["sources"][0], id=98, name="new-src", default=False, volume=40))
        m = self.m.rebuild(st)
        sinks = {r["id"]: r for r in m.sections[0]["rows"]}
        self.assertEqual((sinks[50]["value"], sinks[50]["muted"]), (0.41, True))
        self.assertEqual(sinks[61]["value"], 0.55)
        self.assertEqual(sinks[99]["value"], 0.0)                        # new, and the struct line had none
        self.assertEqual(m.sections[1]["rows"][-1]["value"], 0.4)        # new, the line carried one
        self.assertEqual(next(r for r in m.sections[2]["rows"] if r["id"] == 120)["value"], 0.12)
        self.assertEqual(m.quick, self.m.quick)

    def test_struct_rebuild_keeps_selection_and_picker_by_identity(self):
        self.m.sel = (2, 1)                                              # Firefox
        self.m.open_picker()
        self.assertEqual(self.m.picker, 1)                               # on the Scarlett
        st = self._struct()
        st["apps"].insert(0, dict(st["apps"][0], index=101, app="Alpha"))
        st["sinks"].insert(0, dict(st["sinks"][0], id=49, name="other-sink", default=False))
        m = self.m.rebuild(st)
        self.assertEqual(m.sel, (2, 2))
        self.assertEqual(m.row()["id"], 120)
        self.assertEqual(m.targets()[m.picker]["target"], self.state["sinks"][1]["name"])   # still the Scarlett
        st = self._struct()
        del st["apps"][1]                                                # Firefox leaves
        m = self.m.rebuild(st)
        self.assertEqual(m.sel, (2, 1))                                  # falls back to the clamped index
        self.assertIsNone(m.picker)

    def test_sound_no_signal_render(self):
        import cairo
        m = self.sound.SoundModel(None, {"dnd": False, "night": False, "power": "unknown"})
        surf = cairo.ImageSurface(cairo.FORMAT_ARGB32, 1100, 1300)
        hits, sections = self.sound.draw_sound(cairo.Context(surf), 0, 0, 1100, 1300, m, True)
        self.assertEqual(hits, [])
        self.assertGreater(sum(surf.get_data()), 0)

    # ---- beyond the brief: the model's edges and the panel's input routing

    def test_volume_clamps_at_both_ends(self):
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

    def test_struct_line_keeps_values(self):
        st = json.loads((Path(__file__).parent / "fixtures" / "audiostate.json").read_text())
        for row in st["sinks"]:
            row.pop("volume"); row.pop("muted")
        self.p._on_struct(st)
        self.assertEqual(self.p.model.sections[0]["rows"][0]["value"], 0.68)
        self.p.on_key("Right", 0)
        self.calls["set_volume"].assert_called_once_with("sink", 50, 73)

    def test_scroll_onto_another_row_closes_the_picker(self):
        import cairo
        surf = cairo.ImageSurface(cairo.FORMAT_ARGB32, 1100, 1300)
        self.p.model.sel = (2, 1)
        self.p.model.open_picker()
        self.assertIsNotNone(self.p.model.picker)
        self.p.hits, self.p.sections = self.sound.draw_sound(cairo.Context(surf), 0, 0, 1100, 1300, self.p.model, False)
        own = next(h for h in self.p.hits if h[4] == (2, 1))
        self.p.on_scroll(own[0] + 4, own[1] + 4, 0)                       # same row: the picker stays
        self.assertIsNotNone(self.p.model.picker)
        row = next(h for h in self.p.hits if h[4] == (2, 2))
        self.p.on_scroll(row[0] + 4, row[1] + 4, 1)
        self.assertEqual(self.p.model.sel, (2, 2))
        self.assertIsNone(self.p.model.picker)                            # it belonged to the old row

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


if __name__ == "__main__":
    unittest.main()
