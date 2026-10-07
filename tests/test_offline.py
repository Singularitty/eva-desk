"""Offline tests: no compositor, no windows. Run: python3 -m unittest discover -s tests"""
import contextlib
import copy
import io
import os
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.pop("WAYLAND_DISPLAY", None)

from eva_desk import config  # noqa: E402


class FakeHypr:
    lua = True

    def __init__(self):
        self.state = {}
        self.execs = []

    def j(self, what):
        return copy.deepcopy(self.state.get(what))

    def exec(self, cmd):
        self.execs.append(cmd)


class FakeStage:
    def __init__(self):
        self.calls = []

    def show(self, scene, impact=False, herald_fresh=False):
        self.calls.append((scene, impact, herald_fresh))

    def prepare(self, figure):
        pass


class FakeBar:
    def __init__(self):
        self.state, self.visible = {}, True

    def update(self, **kw):
        self.state.update(kw)

    def set_visible(self, on):
        self.visible = on


def mon(ws_id, ws_name=None, special=0):
    return [{"id": 0, "name": "DP-3", "description": "AOC AG346UCD", "width": 3440, "height": 1440,
             "activeWorkspace": {"id": ws_id, "name": ws_name or str(ws_id)}, "specialWorkspace": {"id": special},
             "focused": True}]


def win(ws, cls="kitty", fs=0, addr="0x1", tags=()):
    return {"address": addr, "mapped": True, "hidden": False, "workspace": {"id": ws, "name": str(ws)},
            "class": cls, "title": f"{cls} title", "fullscreen": fs, "monitor": 0, "tags": list(tags)}


class Logic(unittest.TestCase):
    def setUp(self):
        from eva_desk import gtkutil  # noqa: F401  (pins GTK 4 versions)
        from eva_desk.app import App
        self.cfg = config.load("/nonexistent")
        self.cfg["wallpapers"]["enabled"] = False
        self.cfg["figures"]["figure"] = 1
        app = App.__new__(App)
        app.cfg = self.cfg
        app.hypr = FakeHypr()
        app.stages, app.bars, app.gdk_of = {"DP-3": FakeStage()}, {"DP-3": FakeBar()}, {}
        app.prev, app.urgent_ws, app.walls = {}, set(), None
        app._sync_components = lambda mains: None
        app.figure_set, app.figure_on, app.pending_impact = set(config.figure_workspaces(self.cfg)), True, False
        self.app = app

    def step(self, ws, clients, ws_name=None):
        self.app.hypr.state = {"monitors": mon(ws, ws_name), "clients": clients,
                               "workspaces": [{"id": c["workspace"]["id"], "windows": 1} for c in clients],
                               "activewindow": clients[-1] if clients else {}}
        self.app.refresh()
        return self.app.stages["DP-3"].calls[-1]

    def test_story(self):
        self.assertEqual(self.step(1, []), (None, False, False))                       # empty figure ws
        self.assertEqual(self.step(1, [win(1)]), ("figure", True, False))               # first window: impact
        self.assertEqual(self.step(1, [win(1), win(1, addr="0x2")]), ("figure", False, False))
        self.assertEqual(self.step(1, [win(1, fs=1)]), ("herald", False, True))        # maximise: sweep
        self.assertEqual(self.step(1, [win(1, fs=1)]), ("herald", False, False))       # stays, no replay
        self.assertEqual(self.step(1, [win(1)]), ("figure", False, False))              # restore, no impact
        self.assertEqual(self.step(1, []), (None, False, False))                       # last window closed
        self.assertEqual(self.step(2, [win(2, fs=2)]), (None, False, False))           # true fullscreen
        self.assertEqual(self.step(3, [win(3)]), (None, False, False))                 # ordinary ws
        self.assertEqual(self.step(3, [win(3, fs=1)]), ("herald", False, True))        # herald anywhere
        self.assertEqual(self.step(1, [win(1, cls="steam_app_42", fs=2)]), (None, False, False))  # game

    def test_command_panel_toggle(self):
        calls = []
        class P:
            name = "sound"
            def toggle(self, gdk): calls.append(("toggle", gdk)); return "ok"
            def close(self): calls.append("close")
        self.app.panels, self.app.launcher, self.app.overlays = {"sound": P()}, None, {}
        self.app.focused_gdk = lambda: None
        self.assertEqual(self.app.command("panel sound"), "ok")
        self.assertEqual(self.app.command("panel close"), "ok")
        self.assertEqual(self.app.command("panel music"), "music disabled")
        self.assertEqual(calls, [("toggle", None), "close"])

    def _live_panel(self):
        """A real Panel (no GTK: built with `__new__`) registered in the app, already open."""
        from eva_desk.mfd.panel import Panel
        p = Panel.__new__(Panel)
        p.app, p.cfg, p.name, p.anchor = self.app, self.cfg, "sound", "left"
        p.pwidth, p.pheight, p.w, p.h, p.scale = 1100, 1300, 3440, 1440, 1
        p.px = p.py = p.pw = p.ph = 0
        p._closing, p.t, p._close_from = False, 1.0, 1.0
        p.win = type("W", (), {"visible": False, "get_visible": lambda self: self.visible,
                               "get_surface": lambda self: None})()
        p.animate, p.on_open, p.on_close = mock.Mock(), mock.Mock(), mock.Mock()
        p.show = lambda: setattr(p.win, "visible", True)
        self.app.panels = {"sound": p}
        self.app.overlays = getattr(self.app, "overlays", {})
        self.app.focused_gdk = lambda: None
        self.assertEqual(p.open(None), "ok")
        return p

    def _launcher(self):
        from eva_desk import launcher as L
        lau = L.Launcher.__new__(L.Launcher)
        lau.app, lau.cfg, lau.hypr = self.app, self.cfg, self.app.hypr
        lau.win = mock.Mock()
        lau.win.get_visible.return_value = False
        lau.area = mock.Mock()
        lau.apps, lau.apps_at, lau.counts = [], time.time(), {}
        lau.query, lau.sel, lau.results = "", 0, []
        lau.blink_id, lau.idle_id = 1, None                    # a blink already armed: no new timer
        lau._arm_idle = mock.Mock()
        return lau

    def test_launcher_power_and_alttab_close_the_panel(self):
        from eva_desk import overlays as O
        self.app.launcher = self._launcher()
        p = self._live_panel()
        self.assertEqual(self.app.command("launcher"), "ok")
        self.assertTrue(p._closing)                             # the launcher took over: the panel snaps shut
        p.animate.assert_called_with(190, on_done=p._finish_close)
        for cls, key in ((O.PowerMenu, "power"), (O.AltTab, "alttab")):
            o = cls.__new__(cls)
            o.app, o.cfg, o.guard = self.app, self.cfg, None
            o.place, o._render, o.show = mock.Mock(), mock.Mock(), mock.Mock()
            o.win = mock.Mock()
            o.win.get_visible.return_value = False
            self.app.overlays = {key: o}
            self.app.hypr.state = {"clients": [win(1), win(2, addr="0x2")]}
            p = self._live_panel()
            self.app.overlays = {key: o}
            with mock.patch("eva_desk.overlays.GLib.timeout_add", return_value=3):
                self.assertEqual(self.app.command(key), "ok")
            self.assertTrue(p._closing, key)

    def test_frames_on_every_monitor(self):
        built = []

        class FakeFrame:
            def __init__(self, app, cfg, gdk_monitor, name):
                self.gdk, self.name, self.updates, self.destroyed = gdk_monitor, name, 0, False
                built.append(self)

            def update(self):
                self.updates += 1

            def destroy(self):
                self.destroyed = True

        main, side = object(), object()
        self.app.stages, self.app.bars, self.app.frames = {}, {}, {}
        with mock.patch("eva_desk.gtkutil.monitors", return_value={"DP-3": main, "HDMI-A-1": side}), \
                mock.patch("eva_desk.frame.Frame", FakeFrame):
            self.app._sync_components = type(self.app)._sync_components.__get__(self.app)
            self.app._sync_components([])                      # no mains at all: frames still go everywhere
            self.assertEqual(sorted(self.app.frames), [m["name"] for m in MONS])
            self.assertEqual([f.updates for f in built], [1, 1])
            self.app._sync_frames({"DP-3": main, "HDMI-A-1": side})
            self.assertEqual(len(built), 2)                    # one frame per monitor, not rebuilt
            self.app._sync_frames({"DP-3": main})              # the side monitor went away
            self.assertEqual(sorted(self.app.frames), ["DP-3"])
            self.assertTrue(next(f for f in built if f.name == "HDMI-A-1").destroyed)
            other = object()
            self.app._sync_frames({"DP-3": other})             # a new monitor behind the same name
            self.assertIs(self.app.frames["DP-3"].gdk, other)
            self.cfg["overlays"]["frame"] = False
            self.app._sync_frames({"DP-3": other})
            self.assertEqual(self.app.frames, {})

    def test_bar_volume_clicks(self):
        from eva_desk import bar as B
        b = B.Bar.__new__(B.Bar)
        b.cfg = self.cfg
        b.hits = [(0, 50, ("volume",))]
        b.tray = None
        calls = []
        b.app = mock.Mock(command=lambda line: calls.append(line) or "ok")
        gesture = mock.Mock()
        with mock.patch.object(B, "_run") as run:
            gesture.get_current_button.return_value = 1
            b._click(gesture, 1, 10, 5)
            self.assertEqual(calls, ["panel sound"])              # straight into the daemon, no shell
            run.assert_not_called()
            gesture.get_current_button.return_value = 2
            b._click(gesture, 1, 10, 5)
            run.assert_called_with("wpctl set-mute @DEFAULT_AUDIO_SINK@ toggle")
            gesture.get_current_button.return_value = 3
            b._click(gesture, 1, 10, 5)
            self.assertEqual(run.call_count, 1)                           # right click does nothing
        self.assertTrue(self.cfg["overlays"]["sound"])

    def test_figure_everywhere_and_toggle(self):
        self.cfg["figures"].update(figure="all")
        self.app.figure_set = set(config.figure_workspaces(self.cfg))
        self.assertEqual(sorted(self.app.figure_set), list(range(1, 11)))
        self.step(3, [])
        self.assertEqual(self.step(3, [win(3)]), ("figure", True, False))               # any workspace
        self.assertEqual(self.step(7, [win(7)]), ("figure", False, False))              # switching: no impact
        self.app.figure_on = False                                                     # eva-ctl figure off
        self.assertEqual(self.step(7, [win(7)]), (None, False, False))
        self.app.figure_on, self.app.pending_impact = True, True                       # ... and back on
        self.assertEqual(self.step(7, [win(7)]), ("figure", True, False))               # comes back swinging
        self.assertEqual(self.step(7, [win(7)]), ("figure", False, False))
        self.assertEqual(self.step(7, [win(7, fs=1)]), ("herald", False, True))        # herald unaffected
        self.assertEqual(self.step(-1338, [win(-1338)], ws_name="scratch"), (None, False, False))  # named ws: no figure

    def test_side_window(self):
        self.cfg["figures"].update(figure="all")
        self.app.figure_set = set(config.figure_workspaces(self.cfg))
        self.step(4, [])
        self.assertEqual(self.step(4, [win(4)]), ("figure", True, False))
        side = win(4, addr="0x2", cls="discord", tags=["eva-side"])
        self.assertEqual(self.step(4, [win(4), side]), (None, False, False))          # figure steps aside
        self.assertEqual(self.step(4, [win(4), win(4, addr="0x2")]), ("figure", True, False))   # undocked: back in
        self.assertEqual(self.step(4, [side]), (None, False, False))                   # only the side window
        self.assertEqual(self.step(4, [win(4, fs=1), side]), ("herald", False, True))  # maximise still heralds

    def test_bar_dispatches_eva_ctl_actions_in_process(self):
        from eva_desk import bar as B
        calls, runs = [], []
        self.app.command = lambda line: calls.append(line) or "ok"
        b = B.Bar.__new__(B.Bar)
        b.app, b.cfg = self.app, self.cfg
        with mock.patch.object(B, "_run", lambda cmd: runs.append(cmd)):
            b.dispatch("eva-ctl panel sound")
            b.dispatch("  eva-ctl figure toggle ")
            b.dispatch("wpctl set-mute @DEFAULT_AUDIO_SINK@ toggle")
        self.assertEqual(calls, ["panel sound", "figure toggle"])
        self.assertEqual(runs, ["wpctl set-mute @DEFAULT_AUDIO_SINK@ toggle"])

    def test_run_puts_the_daemon_bin_dirs_on_path(self):
        from eva_desk import bar as B
        seen = {}
        with mock.patch.object(B.subprocess, "Popen", lambda *a, **k: seen.update(k)):
            B._run("true")
        self.assertTrue(seen["env"]["PATH"].startswith(str(Path(B.__file__).resolve().parents[1] / "bin") + ":"))
        self.assertIn(str(Path.home() / ".local" / "bin"), seen["env"]["PATH"])

    def test_bar_tags_and_title(self):
        self.step(2, [win(1), win(2)])
        bar = self.app.bars["DP-3"].state
        self.assertEqual(bar["tags"][:3], [(1, "occupied"), (2, "active"), (3, "empty")])
        self.assertEqual(bar["title"], "kitty title")

    def test_resources_feed_the_bar(self):
        from eva_desk.resources import Sampler
        self.app.sampler = Sampler()                      # the real /proc, read-only
        self.assertTrue(self.app._resources())            # keeps its GLib timeout alive
        res = self.app.bars["DP-3"].state["resources"]
        self.assertEqual(res["show"], ["cpu", "mem", "net"])
        self.assertIn(res["net"], ("lan", "wifi", "vpn", "none"))
        self.assertRegex(res["mem"], r"^\d+(\.\d)?[KMGT]$")

    def test_hooks_and_hidden_bar(self):
        self.cfg["hooks"] = {"scratch": {"enter": "eww open scratch", "leave": "eww close scratch"}}
        self.cfg["bar"]["hide_on_workspaces"] = ["scratch"]
        self.step(1, [])
        self.step(-99, [], ws_name="scratch")
        self.assertFalse(self.app.bars["DP-3"].visible)
        self.step(1, [])
        self.assertTrue(self.app.bars["DP-3"].visible)
        self.assertEqual(self.app.hypr.execs, ["eww open scratch", "eww close scratch"])

    def test_frame_polls_floating(self):
        from eva_desk import frame
        f = frame.Frame.__new__(frame.Frame)
        f.app, f.cfg, f.poll_id, f.geo = self.app, self.cfg, None, None
        f.name = "DP-3"
        calls = []
        f.queue = lambda: calls.append(1)
        self.app.hypr.state = {"monitors": MONS, "activewindow": {"at": [100, 900], "size": [400, 300], "monitor": 0, "floating": True, "fullscreen": 0, "class": "mpv", "workspace": {"id": 1}}}
        with mock.patch("eva_desk.frame.GLib.timeout_add", return_value=7) as ta:
            f.update()
        ta.assert_called_once()                      # floating: a 200 ms poll is armed
        self.assertEqual(ta.call_args[0][0], 200)
        self.assertEqual(calls, [1])                  # fresh geometry: queued once
        f.update()                                    # same geometry again: no redundant redraw
        self.assertEqual(calls, [1])
        self.app.hypr.state["activewindow"]["floating"] = False
        with mock.patch("eva_desk.frame.GLib.source_remove") as sr:
            f.update()
        sr.assert_called_once_with(7)                # tiled again: the poll is dropped
        self.assertEqual(calls, [1, 1])               # geometry changed: redrawn


MONS = [{"id": 0, "name": "DP-3", "x": 0, "y": 746, "width": 3440, "height": 1440, "scale": 1},
        {"id": 1, "name": "HDMI-A-1", "x": 3440, "y": 583, "width": 1920, "height": 1080, "scale": 1}]


class FrameGeometry(unittest.TestCase):
    def setUp(self):
        from eva_desk import frame
        self.frame, self.cfg = frame, config.load("/nonexistent")

    def test_frame_geometry_main_monitor(self):
        act = {"at": [12, 814], "size": [3416, 1360], "monitor": 0, "floating": False, "fullscreen": 0, "class": "kitty", "workspace": {"id": 4}}
        self.assertEqual(self.frame.geometry(act, MONS, self.cfg),
                         ("DP-3", {"x": 12, "y": 68, "w": 3416, "h": 1360, "cls": "kitty", "ws": 4, "floating": False}))

    def test_frame_geometry_side_monitor(self):
        act = {"at": [3450, 600], "size": [1900, 1040], "monitor": 1, "floating": True, "fullscreen": 0, "class": "firefox", "workspace": {"id": 7}}
        name, geo = self.frame.geometry(act, MONS, self.cfg)
        self.assertEqual((name, geo["x"], geo["y"], geo["floating"]), ("HDMI-A-1", 10, 17, True))

    def test_frame_hidden_for_fullscreen_games_and_nothing(self):
        act = {"at": [0, 0], "size": [1, 1], "monitor": 0, "floating": False, "fullscreen": 1, "class": "kitty", "workspace": {"id": 1}}
        self.assertIsNone(self.frame.geometry(act, MONS, self.cfg))
        self.assertIsNone(self.frame.geometry(dict(act, fullscreen=0, **{"class": "steam_app_42"}), MONS, self.cfg))
        self.assertIsNone(self.frame.geometry({}, MONS, self.cfg))
        self.assertIsNone(self.frame.geometry(dict(act, fullscreen=0, monitor=9), MONS, self.cfg))

    def test_frame_draws_offline(self):
        import cairo
        surf = cairo.ImageSurface(cairo.FORMAT_ARGB32, 800, 500)
        self.frame.draw_frame(cairo.Context(surf), {"x": 100, "y": 80, "w": 600, "h": 360, "cls": "kitty", "ws": 2, "floating": False}, self.cfg["frame"])
        self.assertGreater(sum(surf.get_data()), 0)       # something was painted

    def test_frame_brackets_stay_on_screen_and_under_the_bar(self):
        geo = {"x": 12, "y": 68, "w": 3416, "h": 1360, "cls": "kitty", "ws": 4, "floating": False}
        bounds = (0, 56, 3440, 1440)
        rects = self.frame.bracket_rects(geo, bounds)
        self.assertEqual(len(rects), 8)
        for x, y, w, h in rects:
            self.assertGreaterEqual(x, 2)
            self.assertGreaterEqual(y, 56 + 2)
            self.assertLessEqual(x + w, 3440 - 2)
            self.assertLessEqual(y + h, 1440 - 2)
        free = {"x": 300, "y": 160, "w": 1400, "h": 900, "cls": "kitty", "ws": 2, "floating": False}
        self.assertEqual(self.frame.bracket_rects(free, bounds), self.frame.bracket_rects(free))   # room: untouched
        self.assertEqual(self.frame.bracket_rects(free)[0], (300 - 12 - 2, 160 - 12 - 2, 24 + 2, 4))

    def test_frame_paints_nothing_on_the_bar_or_the_edges(self):
        import cairo
        geo = {"x": 12, "y": 68, "w": 3416, "h": 1360, "cls": "kitty", "ws": 4, "floating": False}
        surf = cairo.ImageSurface(cairo.FORMAT_ARGB32, 3440, 1440)
        self.frame.draw_frame(cairo.Context(surf), geo, self.cfg["frame"], bounds=(0, 56, 3440, 1440))
        surf.flush()
        data, stride = bytes(surf.get_data()), surf.get_stride()
        self.assertFalse(any(data[:58 * stride]))                       # the bar and 2 px below it: clean
        self.assertTrue(any(data[58 * stride:90 * stride]))             # the tag, LOCK and top brackets moved down
        for row in range(1440):
            line = data[row * stride:(row + 1) * stride]
            self.assertFalse(any(line[:8]) or any(line[-8:]), row)      # 2 px clear at the left and right
        self.assertFalse(any(data[1438 * stride:]))                     # and at the bottom

    def test_frame_bar_height_only_where_there_is_a_bar(self):
        f = self.frame.Frame.__new__(self.frame.Frame)
        f.cfg, f.name = self.cfg, "HDMI-A-1"
        f.app = type("A", (), {"bars": {"DP-3": object()}})()
        self.assertEqual(f.bar_height(), 0)                             # the side monitor has no bar
        f.name = "DP-3"
        self.assertEqual(f.bar_height(), int(self.cfg["bar"]["height"]))

    def test_frame_destroy_drops_poll(self):
        f = self.frame.Frame.__new__(self.frame.Frame)
        f.poll_id, f.tick_id, f.t = 7, None, 1.0
        f.win = type("W", (), {"destroy": lambda self: None})()
        f.view = type("V", (), {"remove_tick_callback": lambda self, tid: None})()
        with mock.patch("eva_desk.frame.GLib.source_remove") as sr:
            f.destroy()
        sr.assert_called_once_with(7)                 # an armed poll never outlives a destroyed frame


class Wallpapers(unittest.TestCase):
    def test_choice(self):
        from eva_desk.wallpaper import Wallpapers as W
        cfg = config.load("/nonexistent")
        cfg["wallpapers"]["named"] = {"scratch": "#000000"}
        cfg["wallpapers"]["pool"] = ["~/x/two.png", "~/x/three.png"]
        cfg["wallpapers"]["workspaces"] = {"1": "~/x/one.png"}
        w = W(cfg)
        self.assertEqual(w.choice(1, "1"), "~/x/one.png")
        self.assertIn(w.choice(2, "2"), cfg["wallpapers"]["pool"])
        self.assertEqual(w.choice(-99, "scratch"), "#000000")
        self.assertIn(w.choice(5, "5"), cfg["wallpapers"]["pool"])
        self.assertEqual(config.asset("#0a0612"), "#0a0612")
        self.assertTrue(config.asset("~/x/one.png").endswith("/x/one.png"))


class Launcher(unittest.TestCase):
    def test_matching_real_apps(self):
        from gi.repository import Gio
        from eva_desk import launcher as L
        apps = [a for a in Gio.AppInfo.get_all() if a.should_show()]
        self.assertTrue(apps, "no desktop entries found")
        lau = L.Launcher.__new__(L.Launcher)
        lau.apps, lau.counts, lau.query, lau.sel = apps, {}, "kit", 0
        lau.area = type("A", (), {"queue_draw": lambda self: None})()
        lau._filter()
        names = [a.get_display_name().lower() for k, a in lau.results if k == "app"]
        self.assertTrue(names and names[0].startswith("kit"), names[:5])
        self.assertEqual(lau.results[-1], ("web", "kit"))
        lau.query = "> notify-send hi"
        lau._filter()
        self.assertEqual(lau.results[0], ("cmd", "notify-send hi"))


class Ipc(unittest.TestCase):
    def test_roundtrip(self):
        from gi.repository import GLib
        from eva_desk import ipc
        ipc.SOCK = Path(os.environ.get("XDG_RUNTIME_DIR", "/tmp")) / "eva-desk-test.sock"
        loop = GLib.MainLoop()
        server = ipc.Server(lambda line: "pong" if line == "ping" else f"echo {line}")
        t = threading.Thread(target=loop.run, daemon=True)
        t.start()
        time.sleep(0.1)
        try:
            self.assertEqual(ipc.send("ping"), "pong")
            self.assertEqual(ipc.send("impact figure"), "echo impact figure")
        finally:
            loop.quit()
            server.service.stop()
            ipc.SOCK.unlink(missing_ok=True)


class Settings(unittest.TestCase):
    def test_lua_settings(self):
        cfg = config.load("/nonexistent")
        old = config.CONFIG_DIR
        config.CONFIG_DIR = Path(os.environ.get("XDG_RUNTIME_DIR", "/tmp")) / "eva-desk-test-conf"
        try:
            out = config.write_lua_settings(cfg, 3440).read_text()
            self.assertIn("stage_px = 1032", out)
            self.assertIn('launcher_bind = "SUPER + Space"', out)
            self.assertIn('maximize_binds = {"SUPER + RETURN"}', out)
            cfg["hyprland"]["maximize_bind"] = ["ALT + RETURN", "SUPER + RETURN"]
            out = config.write_lua_settings(cfg, 3440).read_text()
            self.assertIn('maximize_binds = {"ALT + RETURN", "SUPER + RETURN"}', out)
        finally:
            config.CONFIG_DIR = old


class TrayBits(unittest.TestCase):
    def test_registration_and_icons(self):
        from gi.repository import GLib
        from eva_desk.tray import menu_model, pixmap_surface, split_item
        self.assertEqual(split_item("/StatusNotifierItem", ":1.42"), (":1.42", "/StatusNotifierItem"))
        self.assertEqual(split_item("org.kde.StatusNotifierItem-7-1", ":1.9"),
                         ("org.kde.StatusNotifierItem-7-1", "/StatusNotifierItem"))
        self.assertEqual(split_item(":1.5/org/ayatana/NotificationItem/x", ""), (":1.5", "/org/ayatana/NotificationItem/x"))
        small, big = (16, 16, bytes([255, 1, 2, 3]) * 256), (32, 32, bytes([255, 1, 2, 3]) * 1024)
        self.assertEqual(pixmap_surface([small, big], size=24).get_width(), 32)   # closest to the size asked
        self.assertIsNone(pixmap_surface([]))
        v = lambda x: GLib.Variant("s", x)
        layout = (0, {}, [(1, {"label": "_Open"}, []), (2, {"type": "separator"}, []),
                          (3, {"label": "More", "children-display": "submenu"}, [(4, {"label": "Inner"}, [])]),
                          (5, {"label": "Hidden", "visible": False}, [])])
        m = menu_model(layout)
        self.assertEqual(m.get_n_items(), 2)                                   # two sections
        second = m.get_item_link(1, "section")
        self.assertEqual(second.get_n_items(), 1)                              # hidden item dropped
        self.assertIsNotNone(second.get_item_link(0, "submenu"))
        del v


class ShotLogic(unittest.TestCase):
    def test_selection_and_window_pick(self):
        from eva_desk import gtkutil  # noqa: F401  (pins GTK 4 versions)
        from eva_desk.shot import clip_rect, norm, window_at
        self.assertEqual(norm(50, 80, 10, 20), (10, 20, 40, 60))                 # dragged up-left
        self.assertEqual(clip_rect((-20, 10, 100, 50), 3440, 1440), (0, 10, 80, 50))
        self.assertIsNone(clip_rect((3500, 10, 100, 50), 3440, 1440))           # off the monitor
        tiled = {"at": [0, 0], "size": [1000, 800], "workspace": {"id": 1}, "floating": False, "focusHistoryID": 0}
        floating = {"at": [100, 100], "size": [300, 300], "workspace": {"id": 1}, "floating": True, "focusHistoryID": 3}
        hidden_ws = {"at": [0, 0], "size": [3440, 1440], "workspace": {"id": 5}, "floating": True, "focusHistoryID": 1}
        self.assertIs(window_at([tiled, floating, hidden_ws], {1}, 150, 150), floating)   # floating on top
        self.assertIs(window_at([tiled, floating, hidden_ws], {1}, 900, 700), tiled)
        self.assertIsNone(window_at([tiled], {1}, 2000, 1000))


class Resources(unittest.TestCase):
    def test_human(self):
        from eva_desk.resources import human
        self.assertEqual([human(x) for x in (0, 500 * 1024, 1.25 * 2 ** 20, 12 * 2 ** 20, 9.8 * 2 ** 30)],
                         ["0K", "500K", "1.2M", "12M", "9.8G"])

    def test_sampler(self):
        import tempfile
        from eva_desk.resources import Sampler
        with tempfile.TemporaryDirectory() as root:
            r = Path(root)
            (r / "proc/net").mkdir(parents=True)
            (r / "sys/class/net/wlp3s0/wireless").mkdir(parents=True)
            (r / "proc/meminfo").write_text("MemTotal:       32000000 kB\nMemFree:  1000 kB\nMemAvailable:   22000000 kB\n")
            route = (r / "proc/net/route")
            route.write_text("Iface\tDestination\tGateway \tFlags\tRefCnt\tUse\tMetric\tMask\n"
                             "wlp3s0\t0001A8C0\t00000000\t0001\t0\t0\t600\t00FFFFFF\n"
                             "wlp3s0\t00000000\t0101A8C0\t0003\t0\t0\t600\t00000000\n")

            def tick(idle, total, rx, tx):
                (r / "proc/stat").write_text(f"cpu  {total - idle} 0 0 {idle} 0 0 0 0 0 0\ncpu0 1 0 0 1 0 0 0 0 0 0\n")
                (r / "proc/net/dev").write_text("Inter-|   Receive\n face |bytes    packets\n"
                                                "    lo: 100 1 0 0 0 0 0 0 100 1 0 0 0 0 0 0\n"
                                                f"wlp3s0: {rx} 10 0 0 0 0 0 0 {tx} 10 0 0 0 0 0 0\n")
            s = Sampler(root)
            tick(1000, 2000, 0, 0)
            first = s.sample(now=10.0)
            self.assertIsNone(first["cpu"])                                      # needs two samples
            self.assertEqual(first["net"], {"iface": "wlp3s0", "kind": "wifi", "down": 0, "up": 0})
            self.assertEqual((first["mem_used"], first["mem_total"]), (10000000 * 1024, 32000000 * 1024))
            tick(1250, 3000, 2 * 2 ** 20, 2 ** 20)                               # 250 of 1000 jiffies idle, 2 MiB in 2 s
            second = s.sample(now=12.0)
            self.assertEqual(second["cpu"], 75)
            self.assertEqual((second["net"]["down"], second["net"]["up"]), (2 ** 20, 2 ** 19))
            route.write_text("Iface\tDestination\tGateway\n")
            self.assertEqual(s.sample(now=14.0)["net"]["kind"], "none")         # no default route: offline

    def test_music_tag(self):
        from eva_desk import gtkutil  # noqa: F401  (pins GTK 4 versions)
        from eva_desk import draw as d
        from eva_desk.bar import music_tags
        from eva_desk.media import parse
        self.assertEqual(parse("Playing\tIt's a Sin\tPet Shop Boys"), ("Playing", "It's a Sin", "Pet Shop Boys"))
        self.assertEqual(parse(""), ("", "", ""))                       # player went away
        self.assertEqual(parse("Stopped\tx\ty"), ("", "", ""))
        self.assertEqual(music_tags({"status": "Playing", "title": "Sin"})[0][1:4], ("▶ SIN", d.INK, d.GOLD))
        self.assertEqual(music_tags({"status": "Paused", "title": "Sin"})[0][1], "II SIN")
        self.assertEqual(music_tags(None), [])

    def test_bar_tags(self):
        import cairo
        from eva_desk import gtkutil  # noqa: F401  (pins GTK 4 versions)
        from eva_desk import draw as d
        from eva_desk.bar import Bar, resource_tags
        res = {"cpu": 12, "mem": "9.8G", "mem_pct": 31, "net": "wifi", "down": "1.2M", "show": ["cpu", "mem", "net"]}
        self.assertEqual([t[1] for t in resource_tags(res)], ["WIFI ↓1.2M", "RAM 9.8G", "CPU 12%"])   # right to left
        hot = resource_tags(dict(res, cpu=95, net="none", show=["cpu", "net"]))
        self.assertEqual([t[:3] for t in hot], [("net", "OFFLINE", d.INK), ("cpu", "CPU 95%", d.LED)])
        self.assertEqual(resource_tags(None), [])
        bar = Bar.__new__(Bar)
        bar.cfg, bar.hits = config.load("/nonexistent"), []
        bar.state = {"tags": [(1, "active")], "special": False, "title": "", "clock": "16:42", "date": "SUN 04",
                     "volume": 68, "muted": False, "resources": res}
        surf = cairo.ImageSurface(cairo.FORMAT_ARGB32, 3440, 56)
        bar._draw(None, cairo.Context(surf), 3440, 56)
        names = [what[0] for x0, x1, what in sorted(bar.hits)]
        self.assertEqual(names[-6:], ["cpu", "mem", "net", "date", "volume", "star"])   # clickable, in order
        bar.cfg["bar"]["buttons"] = [{"name": "magi", "label": "MAGI", "action": "x"}]
        bar._draw(None, cairo.Context(surf), 3440, 56)
        names = [what[0] for x0, x1, what in sorted(bar.hits)]
        self.assertEqual(names[-4:], ["date", "volume", "magi", "star"])
        self.assertIsNotNone(bar._button("magi"))


if __name__ == "__main__":
    unittest.main()


class Themes(unittest.TestCase):
    def test_palette_switch_and_assets(self):
        from eva_desk import draw as d, themes
        try:
            config.activate_theme("eva")
            self.assertEqual(d.THEME["title"], "Evangelion")
            self.assertTrue(str(config.asset_path("figures/unit01.png")).endswith("figures/unit01.png"))
            self.assertEqual(d.CLARET, d.hexc("6a2fb8"))
            self.assertEqual(d.F_DISPLAY, "Shippori Mincho B1")
            self.assertTrue(str(config.theme_dir()).endswith("assets/themes/eva"))
            self.assertTrue(str(config.asset_path("figures/unit01.png")).endswith("figures/unit01.png"))
            styles, inactive = themes.hypr_styles(d.THEME)
            self.assertEqual(styles["card"]["shadow"]["color"], "rgb(6a2fb8)")
            self.assertIn("$v-gold: #7dff3f;", themes.eww_scss(d.THEME))
            other = themes.get("eva")
            other["colors"]["claret"], other["colors"]["bone"], other["fonts"]["display"] = "8e1b33", "efe4cf", "Anton"
            text = 'frame_color = "#efe4cf"  box-shadow: 0 0 #8e1b33; rgba(8e1b3380) Anton'
            self.assertEqual(themes.retheme(text, other, d.THEME),
                             'frame_color = "#ebe6f7"  box-shadow: 0 0 #6a2fb8; rgba(6a2fb880) Shippori Mincho B1')
        finally:
            config.activate_theme("eva")
        self.assertEqual(d.CLARET, d.hexc("6a2fb8"))

    def test_theme_overrides_and_lua(self):
        import tempfile
        with tempfile.NamedTemporaryFile("w", suffix=".toml", delete=False) as f:
            f.write('[theme]\nname = "eva"\n[themes.eva.wallpapers]\npool = ["x"]\n')
        try:
            cfg = config.load(f.name)
            self.assertEqual(cfg["wallpapers"]["pool"], ["x"])
            old = config.CONFIG_DIR
            config.CONFIG_DIR = Path(os.environ.get("XDG_RUNTIME_DIR", "/tmp")) / "eva-desk-test-conf"
            try:
                out = config.write_lua_settings(cfg, 3440).read_text()
                self.assertIn('theme = "eva"', out)
                self.assertIn('gtk_theme = "Eva-Dark"', out)
                self.assertIn('halo = { size = 4, colors = { "rgb(7dff3f)"', out)
                self.assertIn('inactive_border = "rgba(1c0d36aa)"', out)
            finally:
                config.CONFIG_DIR = old
        finally:
            os.unlink(f.name)
            config.load("/nonexistent")


class ToggleRemoved(unittest.TestCase):
    def test_default_has_no_toggle_bind(self):
        cfg = config.load("/nonexistent")
        self.assertNotIn("figure_toggle_bind", cfg["hyprland"])

    def test_settings_lua_has_no_toggle_line(self):
        cfg = config.load("/nonexistent")
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(config, "CONFIG_DIR", Path(tmp)):
            out = config.write_lua_settings(cfg)
            self.assertNotIn("figure_toggle_bind", out.read_text())

    def test_old_toml_key_is_ignored_with_a_note(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "eva.toml"
            p.write_text('[hyprland]\nfigure_toggle_bind = "SUPER + SHIFT + B"\n')
            with contextlib.redirect_stdout(io.StringIO()) as out:
                cfg = config.load(str(p))
            self.assertNotIn("figure_toggle_bind", cfg["hyprland"])
            self.assertIn("figure_toggle_bind", out.getvalue())
