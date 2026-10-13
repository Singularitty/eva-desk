"""The living wallpaper's host: a layer on the background of each main monitor, and the pictures it is handed.

The daemon gives it a wallpaper per monitor (a picture file, or a colour) where it used to hand that to awww. A
picture is decoded off the main loop, then fades in over the one before. A picture that cannot be read, and a
layer that breaks, give the monitor back: the layer is hidden and whoever asked is told, so that awww can show
the wallpaper instead. What lies under the layer is awww's last picture, which is not the desk's any more, so the
layer never shows through: the first picture goes up whole, and one that follows a colour fades in over it.

A layer stands still when it is paused (triggers.paused_monitors says when): its last frame stays up and no timer
runs. A wallpaper that changes meanwhile is swapped in whole. A window goes with its monitor, so a monitor that
comes back gets a new layer; the old one is never shown again.
"""
import math
import re
import threading
import time

from .. import gtkutil  # noqa: F401  (pins GTK 4 before any gi.repository import)

from gi.repository import Gdk, GLib  # noqa: E402

from .. import draw as d  # noqa: E402
from .amb.wallpaper import WallpaperLoop  # noqa: E402
from .player import AmbientLayer  # noqa: E402

COLOUR = re.compile(r"#[0-9a-fA-F]{6}")


def _number(value, default):
    try:
        value = float(value)
    except (TypeError, ValueError):
        return default
    return value if math.isfinite(value) else default


def decode(path, done):
    """Read a picture on a thread of its own and hand `done(texture, None)` or `done(None, why)` to the main loop.
    Whatever goes wrong is an answer: a request that never comes back would leave a monitor waiting for good."""
    def work():
        try:
            result = (Gdk.Texture.new_from_filename(path), None)
        except Exception as e:
            result = (None, getattr(e, "message", None) or str(e) or type(e).__name__)
        GLib.idle_add(lambda: (done(*result), False)[1])
    threading.Thread(target=work, daemon=True).start()


class _Screen:
    """One monitor's wallpaper."""

    def __init__(self, layer):
        self.layer, self.piece = layer, WallpaperLoop()
        self.gdk = None
        self.target = None         # what it shows: a path, or "#rrggbb"
        self.wanted = None         # what is being decoded for it
        self.picture = self.previous = self.colour = None
        self.ground = None         # the colour it showed before the picture that is fading in
        self.since = None          # when the picture came, while it is still fading in

    def clear(self):
        self.target = self.wanted = self.picture = self.previous = self.colour = self.ground = self.since = None


class Living:
    def __init__(self, app, cfg, make=None, clock=time.monotonic, decode=decode):
        amb = cfg["ambient"]
        self.app, self.clock, self.decode = app, clock, decode
        self.drift = min(100.0, max(0.0, _number(amb.get("drift"), 8.0))) / 100
        self.lap = max(0.0, _number(amb.get("lap"), 30.0))
        self.ripples, self.embers = bool(amb.get("ripples", True)), bool(amb.get("embers", True))
        self.fade = max(0.0, _number(cfg["wallpapers"].get("duration"), 0.9))
        fps = _number(amb.get("fps"), 30)
        self.make = make or (lambda app: AmbientLayer(app, "eva-wallpaper", fps, layer="background"))
        self.screens = {}          # monitor name -> _Screen
        self.paused = set()        # the monitors that stand still,
        self.everything = False    # or all of them, whatever their names and whenever they come
        self.berserk = False
        self.said = set()          # the pictures and colours that were already said to be no good
        self.on_failed = None      # (name, target): that picture cannot be shown there; the monitor was given back

    def shows(self, name):
        """Whether that monitor's wallpaper is up here."""
        screen = self.screens.get(name)
        return screen is not None and screen.layer.up

    def _still(self, name):
        return self.everything or name in self.paused

    def _say(self, target, why):
        if target not in self.said:
            self.said.add(target)
            print(f"eva-desk: wallpaper: {target}: {why}", flush=True)

    def _screen(self, name):
        screen = _Screen(self.make(self.app))
        screen.layer.on_broken = lambda layer: self._broke(name, layer)
        return screen

    def show(self, name, gdk_monitor, target):
        """Take a wallpaper for that monitor: a picture file, or "#rrggbb". True when it is taken: it is up, or
        will be once it is read (on_failed says if it could not be). False when it cannot be this host's."""
        if gdk_monitor is None:
            return False
        screen = self.screens.get(name)
        if screen is not None and screen.gdk is not None and screen.gdk is not gdk_monitor:
            screen.layer.hide()                            # the same name, another monitor behind it: the window went with
            screen.layer.destroy()                         # the old one, and a window that is gone is not shown again
            screen = None
        if screen is None:
            screen = self.screens[name] = self._screen(name)
        screen.gdk = gdk_monitor
        if target == screen.target and screen.layer.up:
            screen.wanted = None
            return True
        if str(target).startswith("#"):
            if not COLOUR.fullmatch(target):
                self._say(target, "not a colour (#rrggbb)")
                return screen.layer.up                     # what is up stays up; with nothing up, the caller may try awww
            screen.clear()
            screen.target, screen.colour = target, tuple(d.hexc(target))
            return self._put(name, screen, tell=False)
        screen.wanted = target
        self.decode(target, lambda texture, why: self._arrived(name, target, texture, why))
        return True

    def _arrived(self, name, target, texture, why):
        screen = self.screens.get(name)
        if screen is None or screen.wanted != target:  # the monitor went, or it wants another picture by now
            return
        screen.wanted = None
        if texture is None:
            self._say(target, why)
            return self._give_back(name, screen, target)
        fades = screen.layer.up and not self._still(name) and self.fade > 0       # over what this layer shows; never over what lies under it
        screen.previous = screen.picture if fades and screen.colour is None else None
        screen.ground = screen.colour if fades else None
        screen.picture, screen.colour, screen.target = texture, None, target
        screen.since = self.clock() if screen.previous is not None or screen.ground is not None else None
        self._put(name, screen)

    def _broke(self, name, layer):
        """The layer could not paint and has hidden itself: awww is told what it showed."""
        screen = self.screens.get(name)
        if screen is not None and screen.layer is layer:
            self._give_back(name, screen, screen.target)

    def _give_back(self, name, screen, target, tell=True):
        screen.layer.hide()
        screen.clear()
        if tell and target and self.on_failed:
            self.on_failed(name, target)

    def _put(self, name, screen, tell=True):
        """Show what the screen holds: start its layer, or have a running one draw the change."""
        layer, now = screen.layer, self.clock()
        if not layer.up and not layer.play(screen.piece, screen.gdk, lambda: self._inputs(screen), now):
            self._give_back(name, screen, screen.target, tell)
            return False
        if self._still(name) or screen.colour is not None:           # a colour does not move: no timer for it
            layer.pause(now)
            layer.redraw()
        else:
            layer.resume(now)
        return True

    def _inputs(self, screen):
        fade = 1.0
        if screen.since is not None:
            fade = min(1.0, (self.clock() - screen.since) / self.fade) if self.fade > 0 else 1.0
            if fade >= 1.0:                                # covered: what was under it can go
                screen.since = screen.previous = screen.ground = None
        else:
            screen.previous = screen.ground = None
        return {"picture": screen.picture, "previous": screen.previous, "ground": screen.ground, "fade": fade, "colour": screen.colour,
                "berserk": self.berserk, "drift": self.drift, "lap": self.lap, "ripples": self.ripples, "embers": self.embers}

    def pause(self, names, everything=False):
        """Those monitors stand still, or with `everything` all of them, also the ones that come later; every
        other one runs."""
        self.paused, self.everything, now = set(names), bool(everything), self.clock()
        for name, screen in self.screens.items():
            if not screen.layer.up:
                continue
            if self._still(name):
                if not screen.layer.paused:
                    screen.since = None                    # what was fading in is whole when it stops
                    screen.layer.pause(now)
                    screen.layer.redraw()
            elif screen.colour is None:
                screen.layer.resume(now)

    def set_berserk(self, on):
        if bool(on) != self.berserk:
            self.berserk = bool(on)
            for screen in self.screens.values():
                if screen.layer.paused:
                    screen.layer.redraw()

    def stop(self):
        """Take every wallpaper down (the layers are kept for the next one)."""
        for screen in self.screens.values():
            screen.layer.hide()
            screen.clear()

    def forget(self, alive):
        """Destroy the layers of monitors whose names are not among `alive`."""
        alive = set(alive)
        for name in [n for n in self.screens if n not in alive]:
            screen = self.screens.pop(name)
            screen.layer.hide()
            screen.layer.destroy()
