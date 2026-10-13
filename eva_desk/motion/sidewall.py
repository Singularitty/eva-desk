"""The status wall's host: one layer on the bottom of the monitor the wall belongs on.

It is up while that monitor holds no window; the daemon says when (triggers.wall_monitor, workspace_empty). While
it is up it takes a reading of the CPU, the memory and the network once a second and keeps a minute of each, which
the wall draws a second behind, so that every point of a curve lies between two readings and the curve slides.
While the loops stand still on its monitor it is taken down. Down, it reads nothing and runs no timer.
"""
import math
import time
from pathlib import Path

from .. import gtkutil  # noqa: F401  (pins GTK 4 before any gi.repository import)

from gi.repository import GLib  # noqa: E402

from ..resources import human  # noqa: E402
from .amb.wall import History, WallLoop  # noqa: E402
from .player import AmbientLayer  # noqa: E402

FLOOR = float(1 << 20)       # the network curve is drawn against the most it has seen, and never against less than a megabyte a second


def uptime_text(seconds):
    """Seconds since boot as "04:12", or "3D 02:01" past a day; nothing for what is not a number."""
    try:
        total = max(0, int(float(seconds)))
    except (TypeError, ValueError):
        return ""
    days, rest = divmod(total, 86400)
    clock = f"{rest // 3600:02d}:{rest % 3600 // 60:02d}"
    return f"{days}D {clock}" if days else clock


class SideWall:
    def __init__(self, app, cfg, make=None, clock=time.monotonic, sampler=None, state=None):
        try:
            fps = int(cfg["ambient"].get("fps") or 30)
        except (TypeError, ValueError):
            fps = 30
        self.app, self.clock = app, clock
        self.fps = max(1, min(fps, 15))    # nothing on the wall moves fast: half the other loops' rate is plenty, at half the cost
        self.make = make or (lambda app: AmbientLayer(app, "eva-wall", self.fps, layer="bottom"))
        self.sampler = sampler         # resources.Sampler, made when the wall first comes up: it keeps counters of its own
        self.state = state or dict     # what the daemon knows and the wall shows: the workspaces, the playing track
        self.layer, self.piece = None, WallLoop()
        self.name = None               # the monitor it belongs on
        self.wanted = None             # that monitor, while it holds no window: where the wall should be up
        self.gdk = None                # the monitor it is up on
        self.made_for = None           # the monitor its layer's window was last shown on
        self.paused = set()            # the monitors on which the loops stand still,
        self.everything = False        # or all of them
        self.berserk = False
        self.cpu, self.mem, self.net = History(), History(), History()
        self.latest = None             # the newest reading, for the labels
        self.uptime = ""
        self.said = False              # that the readings failed
        self.sample_id = None

    @property
    def up(self):
        return self.layer is not None and self.layer.up

    # the seams the tests replace
    def _every(self, ms, fn):
        return GLib.timeout_add(ms, lambda: (fn(), True)[1])

    def _cancel(self, source):
        GLib.source_remove(source)

    def read_uptime(self):
        return float(Path("/proc/uptime").read_text().split()[0])

    def _reading(self, on):
        """One reading a second, or none."""
        if self.sample_id is not None:
            self._cancel(self.sample_id)
            self.sample_id = None
        if on:
            self.sample_id = self._every(1000, self.sample)

    def sync(self, name, gdk_monitor):
        """The wall belongs on the monitor `name`, and should be up on `gdk_monitor`, or down when that is None."""
        self.name, self.wanted = name, gdk_monitor
        self._apply()

    def pause(self, names, everything=False):
        """The loops stand still on those monitors (triggers.paused_monitors), or with `everything` on all of
        them. The wall does not keep its last frame then, as the wallpaper does: it is taken down. A clock that
        has stopped still reads as the time, and so do readings."""
        self.paused, self.everything = set(names), bool(everything)
        self._apply()

    def stop(self):
        self.wanted = None
        self._down()

    def _apply(self):
        """Up on the monitor it should be on, unless the loops stand still there; down otherwise."""
        if self.wanted is None or self.everything or self.name in self.paused:
            return self._down()
        if self.up and self.wanted is self.gdk:
            return
        self._down()
        if self.layer is not None and self.wanted is not self.made_for:
            self.layer.destroy()                         # a window goes with its monitor: one that is gone is not shown again
            self.layer = None
        if self.layer is None:
            self.layer = self.make(self.app)
            self.layer.on_broken = lambda layer: self._down()        # it has hidden itself: no reading for nobody
        self.made_for = self.wanted
        self.sample()                                    # a first reading at once: it does not come up empty
        if self.layer.play(self.piece, self.wanted, self.inputs, self.clock()):
            self.gdk = self.wanted
            self._reading(True)

    def _down(self):
        self._reading(False)
        if self.layer is not None:
            self.layer.hide()
        self.gdk = None

    def set_berserk(self, on):
        self.berserk = bool(on)

    def sample(self):
        """One reading into the minute it keeps. A sampler that fails is said once and leaves the wall as it is."""
        now = self.clock()
        try:
            if self.sampler is None:
                from ..resources import Sampler
                self.sampler = Sampler()
            s = self.sampler.sample()
            total = float(s["mem_total"] or 0)
            latest = {"cpu": float(s["cpu"] or 0), "mem_used": s["mem_used"], "mem": 100 * float(s["mem_used"] or 0) / total if total else 0.0,
                      "down": float(s["net"]["down"] or 0), "kind": str(s["net"]["kind"] or "")}
        except Exception as e:
            if not self.said:
                self.said = True
                print(f"eva-desk: wall: no readings: {e}", flush=True)
            return
        self.latest = latest
        if self.cpu.samples and now - self.cpu.samples[-1][0] > 5.0:         # it was down for a while: the minute starts again,
            for history in (self.cpu, self.mem, self.net):                 # rather than a straight line drawn across the gap
                history.samples.clear()
        self.cpu.push(now, latest["cpu"])
        self.mem.push(now, latest["mem"])
        self.net.push(now, latest["down"])
        try:
            self.uptime = uptime_text(self.read_uptime())
        except (OSError, ValueError, IndexError):
            self.uptime = ""

    def inputs(self):
        """What the wall shows now. It is asked at every repaint, so it asks nobody else. The curves move on five
        times a second: in between they are the same, and the wall keeps what it drew."""
        shown = math.floor((self.clock() - 1.0) * 5) / 5
        wall = time.time()
        local = time.localtime(wall)
        peak = max([FLOOR] + [value for _, value in self.net.samples])
        latest = self.latest
        magi = [{"value": self.cpu.at(shown) / 100, "label": f"{round(latest['cpu']):02d}%" if latest else "--",
                 "series": [min(1.0, v / 100) for v in self.cpu.series(shown)]},
                {"value": self.mem.at(shown) / 100, "label": human(latest["mem_used"]) if latest else "--",
                 "series": [min(1.0, v / 100) for v in self.mem.series(shown)]},
                {"value": self.net.at(shown) / peak, "label": "↓" + human(latest["down"]) if latest else "--",
                 "series": [v / peak for v in self.net.series(shown)]}]
        return {"clock": time.strftime("%H:%M", local), "second": min(59.999, local.tm_sec + wall % 1),
                "date": time.strftime("%a %d %b %Y", local).upper(), "uptime": self.uptime, "berserk": self.berserk,
                "net": latest["kind"] if latest else "", "magi": magi, **self.state()}
