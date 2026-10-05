"""Offline tests: no compositor, no windows. Run: python3 -m unittest discover -s tests"""
import copy
import os
import sys
import threading
import time
import unittest
from pathlib import Path

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
        self.cfg["figures"]["knight"] = 2          # the optional knight, to cover its path too
        self.cfg["figures"]["boxer"] = 1
        app = App.__new__(App)
        app.cfg = self.cfg
        app.hypr = FakeHypr()
        app.stages, app.bars, app.gdk_of = {"DP-3": FakeStage()}, {"DP-3": FakeBar()}, {}
        app.prev, app.urgent_ws, app.walls = {}, set(), None
        app._sync_components = lambda mains: None
        app.boxer_set, app.boxer_on, app.pending_impact = set(config.boxer_workspaces(self.cfg)), True, False
        self.app = app

    def step(self, ws, clients, ws_name=None):
        self.app.hypr.state = {"monitors": mon(ws, ws_name), "clients": clients,
                               "workspaces": [{"id": c["workspace"]["id"], "windows": 1} for c in clients],
                               "activewindow": clients[-1] if clients else {}}
        self.app.refresh()
        return self.app.stages["DP-3"].calls[-1]

    def test_story(self):
        self.assertEqual(self.step(1, []), (None, False, False))                       # empty boxer ws
        self.assertEqual(self.step(1, [win(1)]), ("boxer", True, False))               # first window: impact
        self.assertEqual(self.step(1, [win(1), win(1, addr="0x2")]), ("boxer", False, False))
        self.assertEqual(self.step(1, [win(1, fs=1)]), ("herald", False, True))        # maximise: sweep
        self.assertEqual(self.step(1, [win(1, fs=1)]), ("herald", False, False))       # stays, no replay
        self.assertEqual(self.step(1, [win(1)]), ("boxer", False, False))              # restore, no impact
        self.assertEqual(self.step(1, []), (None, False, False))                       # last window closed
        self.assertEqual(self.step(2, [win(2)]), ("knight", False, False))             # switch: no impact
        self.assertEqual(self.step(2, [win(2, fs=2)]), (None, False, False))           # true fullscreen
        self.assertEqual(self.step(3, [win(3)]), (None, False, False))                 # ordinary ws
        self.assertEqual(self.step(3, [win(3, fs=1)]), ("herald", False, True))        # herald anywhere
        self.assertEqual(self.step(1, [win(1, cls="steam_app_42", fs=2)]), (None, False, False))  # game

    def test_boxer_everywhere_and_toggle(self):
        self.cfg["figures"].update(boxer="all", knight=0)
        self.app.boxer_set = set(config.boxer_workspaces(self.cfg))
        self.assertEqual(sorted(self.app.boxer_set), list(range(1, 11)))
        self.step(3, [])
        self.assertEqual(self.step(3, [win(3)]), ("boxer", True, False))               # any workspace
        self.assertEqual(self.step(7, [win(7)]), ("boxer", False, False))              # switching: no impact
        self.app.boxer_on = False                                                     # Super+Shift+B off
        self.assertEqual(self.step(7, [win(7)]), (None, False, False))
        self.app.boxer_on, self.app.pending_impact = True, True                       # ... and back on
        self.assertEqual(self.step(7, [win(7)]), ("boxer", True, False))               # comes back swinging
        self.assertEqual(self.step(7, [win(7)]), ("boxer", False, False))
        self.assertEqual(self.step(7, [win(7, fs=1)]), ("herald", False, True))        # herald unaffected
        self.assertEqual(self.step(-1338, [win(-1338)], ws_name="scratch"), (None, False, False))  # named ws: no boxer

    def test_side_window(self):
        self.cfg["figures"].update(boxer="all", knight=0)
        self.app.boxer_set = set(config.boxer_workspaces(self.cfg))
        self.step(4, [])
        self.assertEqual(self.step(4, [win(4)]), ("boxer", True, False))
        side = win(4, addr="0x2", cls="discord", tags=["eva-side"])
        self.assertEqual(self.step(4, [win(4), side]), (None, False, False))          # boxer steps aside
        self.assertEqual(self.step(4, [win(4), win(4, addr="0x2")]), ("boxer", True, False))   # undocked: back in
        self.assertEqual(self.step(4, [side]), (None, False, False))                   # only the side window
        self.assertEqual(self.step(4, [win(4, fs=1), side]), ("herald", False, True))  # maximise still heralds

    def test_no_knight(self):
        self.cfg["figures"]["knight"] = 0
        self.step(2, [])
        self.assertEqual(self.step(2, [win(2)]), (None, False, False))
        self.assertEqual(self.step(2, [win(2, fs=1)]), ("herald", False, True))

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


class Wallpapers(unittest.TestCase):
    def test_choice(self):
        from eva_desk.wallpaper import Wallpapers as W
        cfg = config.load("/nonexistent")
        cfg["wallpapers"]["named"] = {"scratch": "#000000"}
        w = W(cfg)
        self.assertEqual(w.choice(1, "1"), "ring")
        self.assertIn(w.choice(2, "2"), cfg["wallpapers"]["pool"])
        self.assertEqual(w.choice(-99, "scratch"), "#000000")
        self.assertIn(w.choice(5, "5"), cfg["wallpapers"]["pool"])
        self.assertTrue(config.asset("ring").endswith("assets/wallpapers/ring.webp"))
        self.assertTrue(Path(config.asset("ring")).exists())


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
            self.assertEqual(ipc.send("impact boxer"), "echo impact boxer")
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
            self.assertIn("boxer_stage_px = 1032", out)
            self.assertIn("knight_stage_px = 1445", out)
            self.assertIn('launcher_bind = "SUPER + Space"', out)
            self.assertIn('maximize_binds = {"SUPER + RETURN"}', out)
            self.assertIn("knight = 0", out)
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
            self.assertEqual(d.CLARET, d.hexc("6a2fb8"))
            self.assertEqual(d.F_DISPLAY, "Shippori Mincho B1")
            self.assertTrue(str(config.theme_dir()).endswith("assets/themes/eva"))
            self.assertTrue(str(config.asset_path("figures/boxer.png")).endswith("figures/boxer.png"))
            styles, inactive = themes.hypr_styles(d.THEME)
            self.assertEqual(styles["card"]["shadow"]["color"], "rgb(6a2fb8)")
            self.assertIn("$v-gold: #7dff3f;", themes.eww_scss(d.THEME))
            text = 'frame_color = "#efe4cf"  box-shadow: 0 0 #8e1b33; rgba(8e1b3380) Anton'
            self.assertEqual(themes.retheme(text, themes.get("vibe"), d.THEME),
                             'frame_color = "#ebe6f7"  box-shadow: 0 0 #6a2fb8; rgba(6a2fb880) Shippori Mincho B1')
        finally:
            config.activate_theme("vibe")
        self.assertEqual(d.CLARET, d.hexc("8e1b33"))

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
