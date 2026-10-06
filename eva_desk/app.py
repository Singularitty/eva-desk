"""The daemon: follows Hyprland, decides what each main monitor shows, owns all layer surfaces."""
import json
import os
import sys
import time
import traceback

from . import gtkutil  # noqa: F401  (pins GTK 4 before any gi.repository import)

from gi.repository import Gio, GLib, Gtk

from . import config, ipc
from .hypr import Hypr, class_matches


class App(Gtk.Application):
    def __init__(self, cfg, argv):
        super().__init__(application_id="dev.evadesk.daemon", flags=Gio.ApplicationFlags.NON_UNIQUE)
        self.cfg, self.argv = cfg, argv
        self.started = False

    # ---------------------------------------------------------------- startup
    def do_activate(self):
        if self.started:
            return
        self.started = True
        self.hold()
        cfg = self.cfg
        for attempt in range(40):                      # Hyprland may still be coming up at login
            try:
                self.hypr = Hypr()
                self.hypr.j("version")
                break
            except (OSError, RuntimeError):
                time.sleep(0.25)
        else:
            print("eva-desk: no Hyprland instance found", flush=True)
            self.quit()
            return
        self.stages, self.bars, self.gdk_of = {}, {}, {}
        self.prev, self.urgent_ws = {}, set()
        self.figure_set = set(config.figure_workspaces(cfg))
        self.figure_on = config.figure_enabled()
        self.pending_impact = False
        self.refresh_id = None
        self.minute = None
        self.walls = None
        if cfg["wallpapers"]["enabled"]:
            from .wallpaper import Wallpapers
            self.walls = Wallpapers(cfg)
            self.walls.ensure_daemon()
            mins = int(cfg["wallpapers"]["shuffle_minutes"] or 0)
            if mins > 0:
                GLib.timeout_add_seconds(mins * 60, self._reshuffle)
        self.launcher = None
        if cfg["launcher"]["enabled"]:
            from .launcher import Launcher
            self.launcher = Launcher(self, cfg, self.hypr)
        self.shot = None
        if cfg["shot"]["enabled"]:
            from .shot import Shot
            self.shot = Shot(self, cfg, self.hypr)
        self.volume_state = (None, False)
        self.res_state = None
        self.music_state = None
        self.tray = None
        if cfg["bar"]["enabled"] and cfg["bar"]["tray"]:
            try:
                from .tray import Tray
                self.tray = Tray(self._on_tray)
            except Exception:
                traceback.print_exc()
        if cfg["bar"]["enabled"]:
            from .audio import Volume
            self.volume = Volume(self._on_volume)
            if cfg["bar"]["resources"]:
                from .resources import Sampler
                self.sampler = Sampler()
                self._resources()
                GLib.timeout_add_seconds(max(1, int(cfg["bar"]["resource_seconds"])), self._resources)
            if cfg["bar"]["music"]:
                from .media import NowPlaying
                self.now_playing = NowPlaying(self._on_music, cfg["bar"]["music_players"])
        self.overlays = {}
        ov = cfg["overlays"]
        try:
            from . import overlays as O
            if ov.get("eyecatch"):
                self.overlays["eyecatch"] = O.Eyecatch(self, cfg)
            if ov.get("alarm_band"):
                self.overlays["alarm"] = O.AlarmBand(self, cfg)
            if ov.get("alttab"):
                self.overlays["alttab"] = O.AltTab(self, cfg)
            if ov.get("power"):
                self.overlays["power"] = O.PowerMenu(self, cfg)
            if ov.get("spawn_pulse"):
                self.overlays["pulse"] = O.SpawnPulse(self, cfg)
        except Exception:
            traceback.print_exc()
        self.panels = {}
        self.frames = {}
        self.last_pull = 0.0
        self.ipc = ipc.Server(self.command)
        self.hypr.listen(self._event)
        self.refresh()
        self._clock()
        GLib.timeout_add_seconds(1, self._clock)
        print(f"eva-desk: running (Hyprland {'Lua' if self.hypr.lua else 'legacy'} config)", flush=True)

    # ---------------------------------------------------------------- events
    REFRESH_EVENTS = {"workspace", "workspacev2", "focusedmon", "focusedmonv2", "createworkspacev2",
                      "destroyworkspacev2", "openwindow", "closewindow", "movewindowv2", "fullscreen",
                      "changefloatingmode", "activespecial", "activespecialv2", "activewindowv2", "windowtitlev2",
                      "moveworkspacev2", "renameworkspace", "minimized"}

    def _event(self, name, data):
        if name == "evadesk-disconnected":
            print("eva-desk: Hyprland went away", flush=True)
            self.quit()
        elif name in ("monitoraddedv2", "monitorremovedv2", "monitoradded", "monitorremoved"):
            GLib.timeout_add(700, lambda: (self.schedule(0), False)[1])
        elif name == "urgent":
            self.last_pull = time.monotonic()               # a window asking for attention is not a switch you made
            self._mark_urgent(data)
        elif name in self.REFRESH_EVENTS:
            if name == "openwindow":
                self.last_pull = time.monotonic()
                if "pulse" in getattr(self, "overlays", {}):
                    addr = data.split(",")[0]
                    GLib.timeout_add(60, lambda: (self._spawn_pulse(addr), False)[1])
            self.schedule()
            self._update_frames()

    def schedule(self, delay=25):
        if self.refresh_id is None:
            self.refresh_id = GLib.timeout_add(delay, self._run_refresh)

    def _update_frames(self):
        for f in getattr(self, "frames", {}).values():
            f.update()

    def _run_refresh(self):
        self.refresh_id = None
        try:
            self.refresh()
        except Exception:
            traceback.print_exc()
        return False

    def _spawn_pulse(self, address):
        """A hexagon pulse where a new window landed (main monitors only, never over a game)."""
        try:
            client = next((c for c in self.hypr.j("clients") or [] if c.get("address", "").endswith(address)), None)
            if not client or not client.get("mapped", True) or class_matches(client.get("class", ""), self.cfg["figures"]["ignore_classes"]):
                return
            mons = self.hypr.j("monitors") or []
            mon = next((m for m in mons if m.get("id") == client.get("monitor")), None)
            if not mon or mon["name"] not in self.gdk_of:
                return
            scale = float(mon.get("scale", 1) or 1)
            x, y = client.get("at", (0, 0))
            w, h = client.get("size", (0, 0))
            cx, cy = (x - mon.get("x", 0)) / 1 + w / 2, (y - mon.get("y", 0)) / 1 + h / 2
            self.overlays["pulse"].play(self.gdk_of[mon["name"]], cx / scale, cy / scale, max(w, h) / scale * 0.6)
        except Exception:
            traceback.print_exc()

    def _berserk_check(self, cpu, mem_pct):
        """Sustained load turns the stage berserk (orange) after berserk_seconds; it cools below 80 %."""
        ov = self.cfg["overlays"]
        limit = int(ov.get("berserk", 0) or 0)
        if limit <= 0:
            return
        hot = (cpu or 0) >= limit or (mem_pct or 0) >= limit
        now = time.monotonic()
        if hot:
            self.hot_since = getattr(self, "hot_since", None) or now
        else:
            self.hot_since = None
        want = bool(self.hot_since and now - self.hot_since >= int(ov.get("berserk_seconds", 30)))
        if not hot and max(cpu or 0, mem_pct or 0) < limit - 10:
            want = False
        elif getattr(self, "berserk", False) and hot:
            want = True
        if want != getattr(self, "berserk", False):
            self.berserk = want
            for st in self.stages.values():
                st.set_berserk(want)
            self.prev = {k: {**v, "scene": None} for k, v in self.prev.items()}   # re-show with the entrance
            self.schedule(0)

    def _mark_urgent(self, address):
        for c in self.hypr.j("clients") or []:
            if c.get("address", "").endswith(address):
                self.urgent_ws.add(c["workspace"]["id"])
        self.schedule()

    # ---------------------------------------------------------------- state -> scenes
    def main_monitors(self, mons):
        wanted = self.cfg["general"]["main_monitors"]
        mons = [m for m in mons if not m.get("disabled")]
        if wanted:
            return [m for m in mons if any(w == m["name"] or w in m.get("description", "") for w in wanted)]
        if not mons:
            return []
        return [max(mons, key=lambda m: m["width"] * m["height"])]

    def figure_for(self, ws_id):
        if ws_id and self.figure_on and ws_id in getattr(self, "figure_set", set()):
            return "figure"
        return None

    def set_figure(self, on):
        self.figure_on = bool(on)
        config.set_figure_enabled(self.figure_on)
        if self.hypr.lua:                              # the reserved space comes and goes with him
            self.hypr.eval_lua(f"if EVA_SET_FIGURE then EVA_SET_FIGURE({'true' if self.figure_on else 'false'}) end")
        self.pending_impact = self.figure_on
        GLib.timeout_add(120, lambda: (self.schedule(0), False)[1])   # after Hyprland re-tiled

    def _sync_components(self, mains):
        from .gtkutil import monitors
        gdk = monitors()
        want = {m["name"] for m in mains if m["name"] in gdk}
        for name in list(set(self.stages) | set(self.bars) | set(self.frames)):
            if name not in want or self.gdk_of.get(name) is not gdk.get(name):
                if name in self.stages:
                    self.stages.pop(name).destroy()
                if name in self.bars:
                    self.bars.pop(name).destroy()
                if name in self.frames:
                    self.frames.pop(name).destroy()
                self.prev.pop(name, None)
        for name in want:
            self.gdk_of[name] = gdk[name]
            if name not in self.stages:
                from .stage import Stage
                self.stages[name] = Stage(self, gdk[name], name, self.cfg)
            if name not in self.bars and self.cfg["bar"]["enabled"]:
                from .bar import Bar
                b = Bar(self, gdk[name], name, self.cfg, self.hypr)
                self.bars[name] = b
                b.update(clock=time.strftime("%H:%M"), date=time.strftime("%a %d").upper(),
                         volume=self.volume_state[0], muted=self.volume_state[1], resources=self.res_state,
                         music=self.music_state, tray=self.tray.visible() if self.tray else [])
                b.set_visible(True)
            if name not in self.frames and self.cfg["overlays"]["frame"]:
                from .frame import Frame
                f = Frame(self, self.cfg, gdk[name], name)
                self.frames[name] = f
                f.update()                 # a freshly built frame has no geometry yet: compute it now

    def refresh(self):
        cfg = self.cfg
        mons = self.hypr.j("monitors") or []
        clients = self.hypr.j("clients") or []
        wss = self.hypr.j("workspaces") or []
        active = self.hypr.j("activewindow") or {}
        mains = self.main_monitors(mons)
        self._sync_components(mains)
        ignore = cfg["figures"]["ignore_classes"]
        by_ws = {}
        for c in clients:
            if not c.get("mapped", True) or c.get("hidden"):
                continue
            by_ws.setdefault(c["workspace"]["id"], []).append(c)
        occupied = {w["id"] for w in wss if w.get("windows", 0) > 0}
        for m in mains:
            name = m["name"]
            ws = m.get("activeWorkspace") or {}
            wid, wname = ws.get("id"), ws.get("name", "")
            self.urgent_ws.discard(wid)
            on_ws = by_ws.get(wid, [])
            wins = [c for c in on_ws if not class_matches(c.get("class", ""), ignore)]
            game = any(class_matches(c.get("class", ""), ignore) for c in on_ws if c.get("fullscreen", 0))
            fs = max([int(c.get("fullscreen", 0) or 0) for c in on_ws] or [0])
            figure = self.figure_for(wid)
            sides = [c for c in on_ws if _is_side(c)]
            if sides:
                try:
                    self._check_side(m, sides)
                except (KeyError, TypeError, ValueError, IndexError):
                    pass                                         # a diagnostic, never worth a crash
            if game or fs >= 2:
                scene = None
            elif fs == 1 and cfg["figures"]["herald"]:
                scene = "herald"
            elif figure and wins and not sides:                  # a side window: the figure steps aside
                scene = figure
            else:
                scene = None
            prev = self.prev.get(name, {})
            same_ws = prev.get("ws") == wid
            impact = (scene == "figure" and same_ws and prev.get("scene") != scene
                      and (prev.get("count", 0) == 0 or prev.get("side") or getattr(self, "pending_impact", False)))
            herald_fresh = scene == "herald" and same_ws and prev.get("scene") != "herald"
            stage = self.stages.get(name)
            if stage:
                if not same_ws and figure:
                    stage.prepare(figure)
                stage.show(scene, impact=impact, herald_fresh=herald_fresh)
            if not same_ws:
                if self.walls:
                    self.walls.set_for(name, wid, wname)
                self._hooks(prev.get("ws_name"), wname)
                eye = getattr(self, "overlays", {}).get("eyecatch")
                if (eye and prev and isinstance(wid, int) and wid > 0 and not game and m.get("focused")
                        and time.monotonic() - self.last_pull > 0.4):
                    label = str(cfg["overlays"].get("names", {}).get(str(wid), "") or "")
                    try:
                        eye.play(self.gdk_of.get(name), wid, label)
                    except Exception:
                        traceback.print_exc()
            bar = self.bars.get(name)
            if bar:
                bar.set_visible(wname not in cfg["bar"]["hide_on_workspaces"])
                tags = []
                for n in range(1, int(cfg["bar"]["workspaces"]) + 1):
                    if n == wid:
                        st = "active"
                    elif n in self.urgent_ws:
                        st = "urgent"
                    elif n in occupied:
                        st = "occupied"
                    else:
                        st = "empty"
                    tags.append((n, st))
                title = active.get("title", "") if active and active.get("monitor") == m.get("id") else ""
                bar.update(tags=tags, special=bool((m.get("specialWorkspace") or {}).get("id")), title=title)
            self.prev[name] = {"ws": wid, "ws_name": wname, "count": len(wins), "scene": scene, "side": bool(sides)}
        self.pending_impact = False
        if self.walls:
            main_names = {m["name"] for m in mains}
            for m in mons:
                if m["name"] not in main_names:
                    self.walls.set_static(m["name"], m.get("description", ""))

    def _check_side(self, mon, sides):
        """Log (once per window) when a docked side window is not where the stage column is."""
        seen = self.__dict__.setdefault("_side_checked", set())
        scale = float(mon.get("scale", 1) or 1)
        mw, mh = mon["width"] / scale, mon["height"] / scale
        res = mon.get("reserved") or [0, 0, 0, 0]
        px = round(mw * config.stage_share(self.cfg, mw, mh))
        g = int(self.cfg["hyprland"]["gaps_out"])
        want = (mon.get("x", 0) + mw - px + g, mon.get("y", 0) + res[1] + g, px - 2 * g, mh - res[1] - 2 * g)
        for c in sides:
            key = c.get("address")
            got = (*c.get("at", (0, 0)), *c.get("size", (0, 0)))
            if key not in seen and all(abs(a - b) > 8 for a, b in zip(got[:2], want[:2])):
                print(f"eva-desk: side window at {got}, expected {want}", flush=True)
            seen.add(key)

    def _hooks(self, old, new):
        hooks = self.cfg["hooks"]
        if old and old != new and isinstance(hooks.get(old), dict) and hooks[old].get("leave"):
            self.hypr.exec(hooks[old]["leave"])
        if new and new != old and isinstance(hooks.get(new), dict) and hooks[new].get("enter"):
            self.hypr.exec(hooks[new]["enter"])

    # ---------------------------------------------------------------- periodic
    def _clock(self):
        active = frozenset(b.get("name") for b in self.cfg["bar"].get("buttons", [])
                           if b.get("active_file") and os.path.exists(os.path.expandvars(os.path.expanduser(b["active_file"]))))
        for b in self.bars.values():
            b.update(active=active)
        minute = time.strftime("%H:%M")
        if minute != self.minute:
            self.minute = minute
            for b in self.bars.values():
                b.update(clock=minute, date=time.strftime("%a %d").upper())
        return True

    def _on_volume(self, vol, muted):
        self.volume_state = (vol, muted)
        for b in self.bars.values():
            b.update(volume=vol, muted=muted)

    def _on_tray(self):
        icons = self.tray.visible()
        for b in self.bars.values():
            b.update(tray=icons)

    def _on_music(self, status, title, artist):
        self.music_state = {"status": status, "title": title, "artist": artist} if status else None
        for b in self.bars.values():
            b.update(music=self.music_state)

    def _resources(self):
        from .resources import human
        s = self.sampler.sample()
        used, total = s["mem_used"], s["mem_total"]
        # pre-formatted, so the bar only redraws when a label actually changes
        self.res_state = {"cpu": s["cpu"], "mem": human(used), "mem_pct": round(100 * used / total) if total else 0,
                          "net": s["net"]["kind"], "down": human(s["net"]["down"]),
                          "show": list(self.cfg["bar"]["resources"])}
        for b in self.bars.values():
            b.update(resources=self.res_state)
        game = any(class_matches(c.get("class", ""), self.cfg["figures"]["ignore_classes"]) and c.get("fullscreen", 0)
                   for c in (self.hypr.j("clients") or [])) if self.cfg["overlays"].get("berserk") else False
        if not game:
            self._berserk_check(s["cpu"], self.res_state["mem_pct"])
        return True

    def _reshuffle(self):
        if self.walls:
            self.walls.shuffle()
            self.prev = {k: {**v, "ws": None} for k, v in self.prev.items()}   # re-apply wallpapers
            self.schedule(0)
        return True

    # ---------------------------------------------------------------- control
    def focused_gdk(self):
        for m in self.hypr.j("monitors") or []:
            if m.get("focused"):
                from .gtkutil import monitors
                return monitors().get(m["name"])
        return None

    def open_panel(self, name, gdk):
        p = self.panels.get(name)
        if not p:
            return f"{name} disabled"
        return p.open(gdk)

    def close_panels(self, except_name=None):
        for name, p in list(self.panels.items()):
            if name != except_name:
                p.close()

    def command(self, line):
        parts = line.split()
        cmd, args = (parts[0], parts[1:]) if parts else ("", [])
        stage = next(iter(self.stages.values()), None)
        if cmd == "ping":
            return "pong"
        if cmd == "launcher":
            if not self.launcher:
                return "launcher disabled"
            if args and args[0] == "hide":
                self.launcher.hide()
            else:
                self.launcher.toggle(self.focused_gdk())
            return "ok"
        if cmd == "shot":
            return self.shot.start() if self.shot else "screenshot tool disabled"
        if cmd in ("alttab", "power"):
            o = self.overlays.get(cmd)
            if not o:
                return f"{cmd} disabled"
            if args and args[0] == "hide":
                o.hide()
                return "ok"
            try:
                return o.open(self.focused_gdk())
            except Exception:
                traceback.print_exc()
                return f"{cmd} failed (see the log)"
        if cmd == "panel":
            if args and args[0] == "close":
                self.close_panels()
                return "ok"
            name = args[0] if args else ""
            p = self.panels.get(name)
            if not p:
                return f"{name} disabled"
            try:
                return p.toggle(self.focused_gdk())
            except Exception:
                traceback.print_exc()
                return "panel failed (see the log)"
        if cmd == "eyecatch":
            o = self.overlays.get("eyecatch")
            if not o:
                return "eyecatch disabled"
            wid = int(args[0]) if args else 1
            o.play(self.focused_gdk(), wid, str(self.cfg["overlays"].get("names", {}).get(str(wid), "") or " ".join(args[1:])))
            return "ok"
        if cmd == "alarm":
            o = self.overlays.get("alarm")
            if not o:
                return "alarm band disabled"
            o.show({"app": "eva-desk", "summary": " ".join(args) or "EMERGENCY test", "body": "the band plays once, ACK closes it"})
            return "ok"
        if cmd == "impact" and stage:
            stage.show(args[0] if args else "figure", impact=True)
            GLib.timeout_add(2500, lambda: (self.schedule(0), self.prev.clear(), False)[2])
            return "ok"
        if cmd == "herald" and stage:
            stage.show("herald", herald_fresh=True)
            GLib.timeout_add(3000, lambda: (self.prev.clear(), self.schedule(0), False)[2])
            return "ok"
        if cmd == "figure":
            want = {"on": True, "off": False}.get(args[0] if args else "toggle", not self.figure_on)
            self.set_figure(want)
            return "figure " + ("on" if self.figure_on else "off")
        if cmd == "bar":
            for b in self.bars.values():
                b.set_visible(not args or args[0] != "hide")
            return "ok"
        if cmd == "status":
            return json.dumps({"monitors": list(self.stages), "state": self.prev, "figure": self.figure_on,
                               "wallpapers": self.walls.bin if self.walls else None,
                               "lua": self.hypr.lua})
        if cmd == "reload":
            GLib.timeout_add(50, self._restart)
            return "restarting"
        if cmd == "quit":
            GLib.timeout_add(50, lambda: (self.quit(), False)[1])
            return "bye"
        return f"unknown command: {cmd}"

    def _restart(self):
        os.execv(sys.executable, [sys.executable, "-m", "eva_desk"] + self.argv)


def _is_side(client):
    return any(str(t).startswith("eva-side") for t in (client.get("tags") or []))
