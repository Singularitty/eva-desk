"""The daemon: follows Hyprland, decides what each main monitor shows, owns all layer surfaces."""
import json
import os
import sys
import time
import traceback
from pathlib import Path

from . import gtkutil  # noqa: F401  (pins GTK 4 before any gi.repository import)

from gi.repository import Gio, GLib, Gtk

from . import config, ipc
from .hypr import Hypr, class_matches
from .motion import triggers


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
        self.tracks = triggers.TrackWatch(time.monotonic())      # which reports of the player are a new track
        self.lock_watch = triggers.LockWatch()                   # what the session's lock state means for the wake cover
        if cfg["bar"]["enabled"]:
            from .audio import Volume
            self.volume = Volume(self._on_volume)
        if (cfg["bar"]["enabled"] and cfg["bar"]["resources"]) or int(cfg["overlays"].get("berserk", 0) or 0) > 0:
            from .resources import Sampler                   # the bar's tags, and the load that turns the desk berserk
            self.sampler = Sampler()
            self._resources()
            GLib.timeout_add_seconds(max(1, int(cfg["bar"]["resource_seconds"])), self._resources)
        if (cfg["bar"]["enabled"] and cfg["bar"]["music"]) or cfg["motion"]["track"]:
            from .media import NowPlaying                    # the bar's tag, and the track card
            self.now_playing = NowPlaying(self._on_music, cfg["bar"]["music_players"])
            self._later(0, lambda: self.tracks.begin(time.monotonic()))      # its reports flow once the main loop runs
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
        try:
            if ov.get("sound"):
                from .mfd.sound import SoundPanel
                self.panels["sound"] = SoundPanel(self, cfg)
        except Exception:
            traceback.print_exc()
        self.motion = None                               # the sequence players, one per monitor
        try:
            from . import motion
            if motion.available():
                from .motion.player import Players
                self.motion = Players(self)
            else:
                print("eva-desk: motion needs GTK 4.10 or newer", flush=True)
        except Exception:
            traceback.print_exc()
        self.frames, self.frame_gdk = {}, {}
        self.last_pull = 0.0
        self.ipc = ipc.Server(self.command)
        self.hypr.listen(self._event)
        self.refresh()
        try:
            self._boot()
        except Exception:                                # the desk comes up with or without its sequence
            traceback.print_exc()
        self._watch_sleep()
        self._later(2000, self._watch_lock)
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
            if not getattr(self, "boot_done", True):         # the boot is still waiting for a monitor to play on
                self._boot()
        except Exception:
            traceback.print_exc()
        return False

    def _covered(self):
        """A sequence that covers the screen is playing: nothing else is drawn over it."""
        motion = getattr(self, "motion", None)
        return motion is not None and motion.busy

    def _spawn_pulse(self, address):
        """A hexagon pulse where a new window landed (main monitors only, never over a game or a launch sequence)."""
        try:
            if self._covered():                              # the window a launch opens lands under its sequence
                return
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
            if want:
                try:
                    self._announce_berserk(cpu, mem_pct)
                except Exception:                            # the sampler's timer must outlive a sequence that fails
                    traceback.print_exc()

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
        for name in list(set(self.stages) | set(self.bars)):
            if name not in want or self.gdk_of.get(name) is not gdk.get(name):
                if name in self.stages:
                    self.stages.pop(name).destroy()
                if name in self.bars:
                    self.bars.pop(name).destroy()
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
                         volume=self.volume_state[0], muted=self.volume_state[1],
                         tray=self.tray.visible() if self.tray else [], **self._bar_state("music", "resources"))
                b.set_visible(True)
        self._sync_frames(gdk)
        if getattr(self, "motion", None) is not None:
            self.motion.forget(gdk.values())                 # the players of monitors that went away

    def _sync_frames(self, gdk):
        """One window frame per enabled monitor (the side monitor too, not only the mains), keyed
        by monitor name; rebuilt when the monitor behind a name changes."""
        want = set(gdk) if self.cfg["overlays"]["frame"] else set()
        frame_gdk = self.__dict__.setdefault("frame_gdk", {})
        for name in list(self.frames):
            if name not in want or frame_gdk.get(name) is not gdk.get(name):
                self.frames.pop(name).destroy()
                frame_gdk.pop(name, None)
        for name in sorted(want - set(self.frames)):
            from .frame import Frame
            f = Frame(self, self.cfg, gdk[name], name)
            self.frames[name] = f
            frame_gdk[name] = gdk[name]
            f.update()                     # a freshly built frame has no geometry yet: compute it now

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
            reshuffle = bool(prev.get("reshuffle"))          # the shuffle timer: new wallpaper, same workspace
            same_ws = prev.get("ws") == wid or reshuffle
            impact = (scene == "figure" and same_ws and prev.get("scene") != scene
                      and (prev.get("count", 0) == 0 or prev.get("side") or getattr(self, "pending_impact", False)))
            herald_fresh = scene == "herald" and same_ws and prev.get("scene") != "herald"
            stage = self.stages.get(name)
            if stage:
                if not same_ws and figure:
                    stage.prepare(figure)
                stage.show(scene, impact=impact, herald_fresh=herald_fresh)
            if (not same_ws or reshuffle) and self.walls:
                self.walls.set_for(name, wid, wname)
            if not same_ws:
                self._hooks(prev.get("ws_name"), wname)
                eye = getattr(self, "overlays", {}).get("eyecatch")
                if (eye and prev and isinstance(wid, int) and wid > 0 and not game and m.get("focused")
                        and time.monotonic() - self.last_pull > 0.4 and not self._covered()):
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

    def _on_music(self, status, title, artist, now=None):
        self.music_state = {"status": status, "title": title, "artist": artist} if status else None
        for b in self.bars.values():
            b.update(**self._bar_state("music"))
        if getattr(self, "tracks", None) is not None:        # a new track gets a card, once its reports have settled
            self.tracks.feed(status, title, artist, time.monotonic() if now is None else now)
            self._later(450, self._track_settled)

    def _resources(self):
        from .resources import human
        s = self.sampler.sample()
        used, total = s["mem_used"], s["mem_total"]
        # pre-formatted, so the bar only redraws when a label actually changes
        self.res_state = {"cpu": s["cpu"], "mem": human(used), "mem_pct": round(100 * used / total) if total else 0,
                          "net": s["net"]["kind"], "down": human(s["net"]["down"]),
                          "show": list(self.cfg["bar"]["resources"])}
        for b in self.bars.values():
            b.update(**self._bar_state("resources"))
        try:
            game = any(class_matches(c.get("class", ""), self.cfg["figures"]["ignore_classes"]) and c.get("fullscreen", 0)
                       for c in (self.hypr.j("clients") or [])) if self.cfg["overlays"].get("berserk") else False
        except OSError:                                      # Hyprland did not answer: no berserk check this time,
            game = True                                      # and this timer goes on
        if not game:
            self._berserk_check(s["cpu"], self.res_state["mem_pct"])
        return True

    def _bar_state(self, *what):
        """What the bars are told of the player and of the load: only what their own switches ask for. The track
        card and the berserk limit need both sources even when the bar shows neither."""
        bar, state = self.cfg["bar"], {}
        if "music" in what and bar["music"]:
            state["music"] = getattr(self, "music_state", None)
        if "resources" in what and bar["resources"]:
            state["resources"] = getattr(self, "res_state", None)
        return state

    def _reshuffle(self):
        if self.walls:
            self.walls.shuffle()
            self.prev = {k: {**v, "reshuffle": True} for k, v in self.prev.items()}   # re-apply wallpapers, no eye-catch
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

    # ---------------------------------------------------------------- motion: what plays when
    def _later(self, ms, fn):
        """Run fn once, ms from now."""
        GLib.timeout_add(ms, lambda: (fn(), False)[1])

    def _inputs(self, **more):
        """What any motion piece may show: where and when, the bar's height, and whatever the caller adds."""
        ws = (self.hypr.j("activeworkspace") or {}).get("id")
        bar = self.cfg["bar"]
        return {"workspace": ws if isinstance(ws, int) and ws > 0 else None, "clock": time.strftime("%H:%M"),
                "bar": int(bar["height"]) if bar["enabled"] else 0, **more}

    def _play(self, piece, gdk_monitor=None, **inputs):
        """Play a piece on that monitor (the focused one when none is given)."""
        return self.motion.play(piece, gdk_monitor or self.focused_gdk(), self._inputs(**inputs))

    def _mains_gdk(self, skip=()):
        """The Gdk monitors of the main monitors, without the ones named in `skip`."""
        mains = self.main_monitors(self.hypr.j("monitors") or [])
        return [self.gdk_of[m["name"]] for m in mains if m["name"] in self.gdk_of and m["name"] not in skip]

    def _quiet(self):
        """Something that covers the screen or holds the keyboard is up: berserk and the track card stay away."""
        if self._covered() or getattr(getattr(self, "launcher", None), "visible", False):
            return True
        overlays = getattr(self, "overlays", {})
        return any(getattr(overlays.get(name), "visible", False) for name in ("power", "alttab"))

    def _may_announce(self, switch):
        """Whether berserk or the track card may play at all right now."""
        if getattr(self, "motion", None) is None or not self.cfg["motion"][switch] or self._quiet():
            return False
        return not triggers.game_open(self.hypr.j("clients"), self.cfg["figures"]["ignore_classes"])

    def play_launch(self, name, game, gdk_monitor):
        """The launch sequence for a launcher entry: the card for an app, the shaft for a game."""
        if getattr(self, "motion", None) is None or not self.cfg["motion"]["launch"]:
            return False
        from .motion.seq.card import Card
        from .motion.seq.shaft import Shaft
        return self._play(Shaft() if game else Card(), gdk_monitor, app=name)

    def _boot_inputs(self):
        net = (getattr(self, "res_state", None) or {}).get("net") or "lan"
        return triggers.boot_inputs(self.hypr.j("monitors"), self.hypr.j("version"), self.hypr.lua, net)

    BOOT_PATIENCE = 20.0       # seconds the boot waits for a main monitor to play on before it gives the session up

    def _boot(self, marker=None, now=None):
        """The boot sequence on every main monitor, once per Hyprland session. True when it played. `boot_done` says
        whether the matter is settled: it stays open while no main monitor is known (at login the first refresh can
        come before the outputs), and the next refresh tries again."""
        now = time.monotonic() if now is None else now
        self.boot_done = True
        signature = os.environ.get("HYPRLAND_INSTANCE_SIGNATURE", "")
        marker = Path(marker or Path(os.environ.get("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}")) / "eva-desk.boot")
        try:
            seen = marker.read_text()
        except OSError:
            seen = None
        if not triggers.boot_due(seen, signature):
            return False
        targets = []
        if (getattr(self, "motion", None) is not None and self.cfg["motion"]["boot"]
                and not triggers.game_open(self.hypr.j("clients"), self.cfg["figures"]["ignore_classes"])):      # never over a game
            if self._mains_gdk():
                targets = self._mains_gdk(skip=triggers.fullscreen_monitors(self.hypr.j("monitors"), self.hypr.j("clients")))
            else:                                            # nothing to play on yet
                self.boot_until = getattr(self, "boot_until", None) or now + self.BOOT_PATIENCE
                if now < self.boot_until:
                    self.boot_done = False
                    return False
        try:
            marker.write_text(signature + "\n")              # the session is marked whether or not the boot played: switching
        except OSError:                                      # it on later must not play it in the middle of a session
            pass
        if not targets:
            return False
        from .motion.seq.boot import Boot
        inputs = self._boot_inputs()
        return any([self._play(Boot(), gdk, **inputs) for gdk in targets])

    @staticmethod
    def _load(cpu, mem_pct):
        """What is hot, for the berserk block: the higher of the two."""
        cpu, mem = cpu or 0, mem_pct or 0
        return f"CPU {cpu}%" if cpu >= mem else f"RAM {mem}%"

    def _announce_berserk(self, cpu, mem_pct):
        """The berserk sequence on every main monitor that shows no fullscreen window. Returns how many it played on."""
        if not self._may_announce("berserk"):
            return 0
        from .motion.seq.berserk import Berserk
        full = triggers.fullscreen_monitors(self.hypr.j("monitors"), self.hypr.j("clients"))
        inputs = {"load": self._load(cpu, mem_pct), "seconds": int(self.cfg["overlays"].get("berserk_seconds", 30))}
        return sum(bool(self._play(Berserk(), gdk, **inputs)) for gdk in self._mains_gdk(skip=full))

    def _track_settled(self, now=None):
        """A card for the track that has settled, if there is one. A track that settles while something is in the
        way is not announced later."""
        tracks = getattr(self, "tracks", None)
        pair = tracks.settle(time.monotonic() if now is None else now) if tracks is not None else None
        if tracks is not None and tracks.pending:            # a new track, too soon after the last card: ask again
            self._later(1000, self._track_settled)
        if not pair or not self._may_announce("track"):
            return False
        mons = self.hypr.j("monitors") or []
        name = triggers.track_monitor(mons, [m["name"] for m in self.main_monitors(mons)])
        if name not in self.gdk_of or name in triggers.fullscreen_monitors(mons, self.hypr.j("clients")):
            return False
        from .motion.seq.track import Track
        return bool(self._play(Track(), self.gdk_of[name], title=pair[0], artist=pair[1], corner=self.cfg["motion"]["track_corner"]))

    def lock(self):
        """Start the lock screen the way it always was started: [power] lock, run by Hyprland. Never refused and
        never tracked. The wake sequence follows the session's lock state (_watch_lock), not this call."""
        cmd = self.cfg["power"].get("lock", "")
        if not cmd:
            return "no lock command"
        self.hypr.exec(cmd)
        return "ok"

    def _locked(self):
        """Whether Hyprland says the session is locked; None when it does not say."""
        try:
            reply = self.hypr.j("locked")
        except OSError:
            return None
        return bool(reply["locked"]) if isinstance(reply, dict) and "locked" in reply else None

    def _watch_lock(self, now=None):
        """Look whether the session is locked, and look again: every two seconds, twice a second while the cover is
        up. When the session is locked, however that came about, the wake sequence goes up under the lock screen,
        held on its first frame, so that the lock screen fades onto that cover and not onto the desk; when it
        unlocks, the sequence plays. The daemon only watches: it never starts, stops or waits on a locker here.
        Nothing may end this watch or leave the cover up, so every failure takes the cover down and looks again."""
        if getattr(self, "motion", None) is None or not self.cfg["motion"]["wake"]:
            return
        watch = self.lock_watch
        try:
            locked = self._locked()
            verdict = watch.tick(time.monotonic() if now is None else now, locked)
            if verdict in ("cover", "hold") and locked:      # a cover on every main monitor, one that came back included
                from .motion.seq.wake import Wake
                for gdk in self._mains_gdk():
                    if getattr(self.motion.playing(gdk), "name", None) != "wake":
                        self.motion.play(Wake(), gdk, {}, held=True)
            elif verdict == "play":
                self.motion.start()
            elif verdict == "drop":
                self.motion.stop("wake")
        except Exception as e:
            print(f"eva-desk: wake: {e}", flush=True)
            watch.covered = False
            try:
                self.motion.stop("wake")
            except Exception:
                traceback.print_exc()
        finally:
            self._later(500 if watch.covered else 2000, self._watch_lock)

    def _on_sleep(self, sleeping):
        """logind's PrepareForSleep: True before the machine sleeps, False when it is back."""
        if sleeping or getattr(self, "motion", None) is None or not self.cfg["motion"]["wake"]:
            return
        if self.lock_watch.covered or self._locked():        # back onto a lock screen: its closing plays the sequence
            return
        from .motion.seq.wake import Wake
        for gdk in self._mains_gdk():
            self._play(Wake(), gdk)

    def _watch_sleep(self):
        """Hear logind say the machine is back from sleep."""
        if getattr(self, "motion", None) is None or not self.cfg["motion"]["wake"]:
            return
        try:
            bus = Gio.bus_get_sync(Gio.BusType.SYSTEM, None)
            bus.set_exit_on_close(False)                     # the system bus going away must not take the daemon with it
            bus.signal_subscribe("org.freedesktop.login1", "org.freedesktop.login1.Manager", "PrepareForSleep",
                                 "/org/freedesktop/login1", None, Gio.DBusSignalFlags.NONE,
                                 lambda conn, sender, path, iface, signal, params: self._on_sleep(bool(params.unpack()[0])))
            self.system_bus = bus
        except GLib.Error:
            print("eva-desk: no system bus: no wake sequence after sleep", flush=True)

    def _trial(self, name, text):
        """The inputs `eva-ctl play NAME [TEXT]` shows a piece with."""
        if name == "boot":
            return self._boot_inputs()
        if name == "berserk":
            res = getattr(self, "res_state", None)
            return {"load": self._load(res["cpu"], res["mem_pct"]) if res else "CPU 97%",
                    "seconds": int(self.cfg["overlays"].get("berserk_seconds", 30))}
        if name == "track":
            music = getattr(self, "music_state", None) or {}
            return {"title": text or music.get("title") or "TITLE", "artist": music.get("artist") or "ARTIST",
                    "corner": self.cfg["motion"]["track_corner"]}
        return {"app": text or "EVA-DESK"}

    def close_panels(self, except_name=None):
        for name, p in list(getattr(self, "panels", {}).items()):
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
            if not args:
                return "panel: name missing"
            name = args[0]
            p = self.panels.get(name)
            if not p:
                return f"{name} disabled"
            at = None
            if len(args) >= 3 and args[1] == "at":
                try:
                    at = float(args[2])                  # "panel sound at 3300": hang under that x on the bar
                except ValueError:
                    return "panel: bad position"
            try:
                return p.toggle(self.focused_gdk(), at)
            except Exception:
                traceback.print_exc()
                return "panel failed (see the log)"
        if cmd == "play":                                  # try a motion piece: play NAME [TEXT]
            from . import motion
            names = motion.pieces()
            if not args:
                return "play: " + " | ".join(names)
            if args[0] not in names:
                return f"unknown piece: {args[0]} ({', '.join(names)})"
            if getattr(self, "motion", None) is None:
                return "motion is not available"
            self._play(names[args[0]](), **self._trial(args[0], " ".join(args[1:])))
            return "ok"
        if cmd == "lock":                                  # the lock screen, started so that the wake sequence can follow it
            return self.lock()
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
