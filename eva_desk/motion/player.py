"""The hosts: the layer surfaces a motion piece is shown on.

SequencePlayer plays one sequence at a time on one monitor, on the overlay layer. It never takes the keyboard. A
piece that covers the screen takes the pointer, and a click ends it; a piece that does not is clicked straight
through. Whatever happens, a sequence cannot stay on screen: it ends at its length, on a click, when painting
raises, and one second after its length if nothing else ended it. One that cannot prepare is not shown at all.

AmbientLayer hosts a loop, which has no end: it repaints from a timer, a few times a second, until it is told to
go. Standby is the standby loop on every monitor at once. It is the one host that takes the keyboard, so that
the key that ends it is not typed into a window; anything that goes wrong while it is up ends it.
"""
import time
import traceback

import cairo

from .. import gtkutil  # noqa: F401  (pins GTK 4 before any gi.repository import)

from gi.repository import GLib, Gtk  # noqa: E402

from ..overlays import _Overlay  # noqa: E402
from .amb.standby import LEAVE  # noqa: E402
from .kit import Kit  # noqa: E402
from .triggers import Travel, outranks  # noqa: E402


class SequencePlayer(_Overlay):
    def __init__(self, app):
        super().__init__(app, "eva-motion", keyboard="none", passthrough=False)      # the input region is set per piece
        click = Gtk.GestureClick()
        click.set_button(0)                         # any button: a gesture listens to the left one unless told
        click.connect("pressed", lambda *a: self.skip())
        self.view.add_controller(click)
        self.setup()

    def setup(self):
        """The state of a player with nothing playing."""
        self.piece = self.ctx = self.on_done = None
        self.at = 0.0              # seconds into the running piece
        self.started = None        # the frame clock's time at the first tick
        self.run = 0               # bumped by every play(), so a late timer knows it is stale
        self.broken = False        # the running piece raised: it paints nothing more and ends from the main loop
        self.held = False          # the piece is up on its first frame and has not been started
        self.stamps = {}           # the pictures the running piece had made of its type (kit.stamp); they go with it
        self.tick_id = None
        self.w = self.h = 0
        self.scale = 1

    @property
    def busy(self):
        """A piece that covers the screen is playing."""
        return self.piece is not None and self.piece.covers

    def _kit(self, snap, w, h):
        return Kit(snap, w, h, self.scale, self.stamps)

    def play(self, piece, gdk_monitor, ctx, on_done=None, held=False):
        """Play `piece` on that monitor, in place of whatever was playing. False when it cannot be played:
        there is no monitor, or the piece failed to prepare. A `held` piece is put up on its first frame and waits
        there for start(): no clock runs and no safety counts down, since it may wait for hours under a lock screen."""
        self.finish()
        self.w = self.h = 0                         # place() keeps the last monitor's size when it is given none
        self.place(gdk_monitor)
        if not self.w or not self.h:
            return False
        self.stamps, self.broken = {}, False
        kit = self._kit(Gtk.Snapshot(), self.w / self.scale, self.h / self.scale)       # the frame _paint will be given
        try:
            piece.prepare(kit, ctx)
        except Exception as e:
            print(f"eva-desk: motion: {piece.name or type(piece).__name__}: prepare: {e}", flush=True)
            self.stamps = {}
            return False
        finally:
            kit.close()
        self.piece, self.ctx, self.on_done, self.held = piece, ctx, on_done, held
        self.at, self.started = 0.0, None
        self.run += 1
        if not held:
            self._arm()                             # before it is shown: the safety covers a show() that fails, too
        self.show()
        surface = self.win.get_surface()
        if surface is not None:
            whole = cairo.Region(cairo.RectangleInt(0, 0, int(self.w), int(self.h)))
            surface.set_input_region(whole if piece.covers else cairo.Region())
        if not held:
            self.tick_id = self.view.add_tick_callback(self._tick)
        return True

    def _arm(self):
        """The safety: one second past its length the piece is gone, whatever happened."""
        run = self.run
        if self.piece.length is not None:
            self._after(int((self.piece.length + 1) * 1000), lambda: self.finish() if self.run == run else None)

    def start(self):
        """Set a held piece going from its first frame. Nothing when none is held."""
        if self.piece is not None and self.held:
            self.held = False
            self._arm()
            self.tick_id = self.view.add_tick_callback(self._tick)

    def _after(self, ms, fn):
        GLib.timeout_add(ms, lambda: (fn(), False)[1])

    def _tick(self, widget, clock):
        if self.advance(clock.get_frame_time() / 1e6):
            return GLib.SOURCE_REMOVE
        widget.queue_draw()
        return GLib.SOURCE_CONTINUE

    def advance(self, now):
        """One tick at `now` seconds. True when that ended the piece (or nothing is playing)."""
        if self.piece is None:
            return True
        if self.started is None:
            self.started = now                      # the first tick is t = 0
        self.at = now - self.started
        if self.piece.length is not None and self.at >= self.piece.length:
            self.tick_id = None                     # the tick ends by returning, not by being removed from inside itself
            self.finish()
            return True
        return False

    def skip(self):
        """A click: it ends a piece that covers the screen."""
        if self.busy:
            self.finish()

    def finish(self):
        """Hide, let the piece drop what it built, tell whoever asked. Does nothing when nothing is playing."""
        piece, done = self.piece, self.on_done
        if piece is None:
            return
        self.piece = self.ctx = self.on_done = None        # cleared first: the done callback may play the next piece
        self.stamps, self.held = {}, False
        self.hide()
        try:
            piece.release()
        except Exception as e:
            print(f"eva-desk: motion: {piece.name or type(piece).__name__}: release: {e}", flush=True)
        if done:
            done()

    def _paint(self, snap, w, h):
        piece = self.piece
        if piece is None or self.broken:
            return
        try:
            kit = self._kit(snap, w, h)
            try:
                piece.draw(kit, self.at, self.ctx)
            finally:
                kit.close()
        except Exception as e:                      # a piece that raises must not leave the screen covered
            print(f"eva-desk: motion: {piece.name or type(piece).__name__}: {e}", flush=True)
            self.broken, run = True, self.run       # GTK is in the middle of drawing this window: hiding it has to
            self._after(0, lambda: self.finish() if self.run == run else None)      # wait for the main loop


class Players:
    """One SequencePlayer per monitor, made when a piece first plays there, and the rule for what interrupts what:
    on a monitor, a piece plays only if it outranks what is playing there (triggers.outranks); otherwise it is dropped."""

    def __init__(self, app, make=SequencePlayer):
        self.app, self.make = app, make
        self.by_monitor = {}                        # Gdk monitor -> its player

    @property
    def busy(self):
        """A piece that covers the screen is playing on some monitor."""
        return any(player.busy for player in self.by_monitor.values())

    def play(self, piece, gdk_monitor, ctx, on_done=None, held=False):
        """SequencePlayer.play on that monitor. False as there, and when what plays there outranks the piece."""
        if gdk_monitor is None:
            return False
        player = self.by_monitor.get(gdk_monitor)
        if player is None:
            player = self.by_monitor[gdk_monitor] = self.make(self.app)
        elif player.piece is not None and not outranks(piece, player.piece):
            return False
        return player.play(piece, gdk_monitor, ctx, on_done, held)

    def playing(self, gdk_monitor):
        """The piece that is up on that monitor, held or running; None when there is none."""
        player = self.by_monitor.get(gdk_monitor)
        return player.piece if player is not None else None

    def start(self):
        """Set every held piece going."""
        for player in self.by_monitor.values():
            player.start()

    def stop(self, name=None):
        """End what is playing: everything, or the pieces of that name."""
        for player in list(self.by_monitor.values()):
            if player.piece is not None and name in (None, player.piece.name):
                player.finish()

    def forget(self, alive):
        """Destroy the players of monitors that are not among `alive`."""
        alive = list(alive)
        for monitor in [m for m in self.by_monitor if m not in alive]:
            player = self.by_monitor.pop(monitor)
            player.finish()
            player.destroy()


class AmbientLayer(_Overlay):
    """A loop on one monitor. It repaints from a timer, `fps` times a second, and paints the piece at the time it
    is told: now less the epoch it was given, so that several layers given one epoch show one clock.

    The layer does not own its piece: one piece may be on several layers, and whoever made it releases it."""

    LEAVE_BEAT = 8             # ms between frames while a piece leaves: a fold of a fifth of a second needs more than six
    on_poke = None             # (layer, kind, x, y): a key press, a click or pointer motion, while a piece is up and not leaving
    on_broken = None           # (layer): its piece could not paint or its inputs raised; the layer has hidden itself
    on_hidden = None           # (layer): hide() took a piece down

    def __init__(self, app, namespace, fps=30, keyboard="none", layer="overlay"):
        super().__init__(app, namespace, keyboard=keyboard, passthrough=False, layer=layer)      # the input region is set per piece
        self.fps, self.mode = fps, keyboard
        keys = Gtk.EventControllerKey()
        keys.connect("key-pressed", lambda *a: (self.poke("key"), True)[1])          # a press, never a release; and it goes no further
        self.win.add_controller(keys)
        click = Gtk.GestureClick()
        click.set_button(0)                         # any button
        click.connect("pressed", lambda *a: self.poke("click"))
        self.view.add_controller(click)
        motion = Gtk.EventControllerMotion()
        motion.connect("motion", lambda ctrl, x, y: self.poke("motion", x, y))
        self.view.add_controller(motion)
        self.setup()

    def setup(self):
        """The state of a layer with nothing on it."""
        self.piece = self.inputs = None
        self.ctx = {}
        self.at = 0.0              # seconds into the loop, at the last beat
        self.epoch = 0.0           # when the loop's clock began
        self.left = None           # (when the piece began to leave, how long that takes)
        self.paused_at = None      # when it was paused: its last frame stays up and no timer runs
        self.run = 0               # bumped by every play(), so a late timer knows it is stale
        self.broken = False
        self.stamps = {}
        self.beat_id = self.tick_id = None
        self.w = self.h = 0
        self.scale = 1

    @property
    def up(self):
        """A piece is on it, leaving included."""
        return self.piece is not None

    @property
    def leaving(self):
        return self.left is not None

    @property
    def paused(self):
        return self.paused_at is not None

    # the seams the tests replace
    def _every(self, ms, fn):
        return GLib.timeout_add(ms, lambda: (fn(), True)[1])

    def _cancel(self, source):
        GLib.source_remove(source)

    def _after(self, ms, fn):
        GLib.timeout_add(ms, lambda: (fn(), False)[1])

    def _keyboard(self, mode):
        from gi.repository import Gtk4LayerShell as LS
        LS.set_keyboard_mode(self.win, {"none": LS.KeyboardMode.NONE, "exclusive": LS.KeyboardMode.EXCLUSIVE,
                                        "on_demand": LS.KeyboardMode.ON_DEMAND}[mode])

    def _period(self):
        """Milliseconds between two repaints: the rate it was given, kept between one and 120 a second."""
        try:
            fps = float(self.fps)
        except (TypeError, ValueError):
            fps = 30.0
        return max(8, round(1000 / min(120.0, max(1.0, fps))))

    def _arm(self, ms):
        if self.beat_id is not None:
            self._cancel(self.beat_id)
        self.beat_id = self._every(ms, lambda: self.beat(time.monotonic()))

    def _region(self, whole):
        surface = self.win.get_surface()
        if surface is not None:
            surface.set_input_region(cairo.Region(cairo.RectangleInt(0, 0, int(self.w), int(self.h))) if whole else cairo.Region())

    def play(self, piece, gdk_monitor, inputs, epoch, now=None):
        """Put `piece` on that monitor and keep repainting it. `inputs()` gives what each repaint shows. False, and
        nothing shown, when there is no monitor or the piece cannot prepare."""
        self.hide()
        self.w = self.h = 0                         # place() keeps the last monitor's size when it is given none
        self.place(gdk_monitor)
        if not self.w or not self.h:
            return False
        self.stamps, self.broken = {}, False
        name = piece.name or type(piece).__name__
        kit = Kit(Gtk.Snapshot(), self.w / self.scale, self.h / self.scale, self.scale, self.stamps)
        try:
            piece.prepare(kit, {})
        except Exception as e:
            print(f"eva-desk: motion: {name}: prepare: {e}", flush=True)
            self.stamps = {}
            return False
        finally:
            kit.close()
        try:
            ctx = dict(inputs())
        except Exception as e:
            print(f"eva-desk: motion: {name}: inputs: {e}", flush=True)
            self.stamps = {}
            return False
        self.piece, self.inputs, self.epoch, self.left, self.ctx = piece, inputs, epoch, None, ctx
        self.paused_at = None
        self.at = (epoch if now is None else now) - epoch
        self.run += 1
        try:
            self._keyboard(self.mode)
            self.show()
            self._region(piece.covers)
            self._arm(self._period())
        except Exception as e:                      # it must not be left half up, least of all holding the keyboard
            print(f"eva-desk: motion: {name}: {e}", flush=True)
            self.piece = self.inputs = None         # it never came up: nobody is told that it went
            self.hide()
            return False
        return True

    def beat(self, now):
        """One repaint at `now`. While the piece leaves, its inputs say for how long it has been; then it is hidden."""
        if self.piece is None or self.paused_at is not None:
            return
        try:
            ctx = dict(self.inputs())
        except Exception as e:
            print(f"eva-desk: motion: {self.piece.name or type(self.piece).__name__}: inputs: {e}", flush=True)
            return self._fail()
        if self.left is not None:
            since = now - self.left[0]
            if since >= self.left[1]:
                return self.hide()
            ctx["leaving"] = since
        self.at, self.ctx = now - self.epoch, ctx
        self.view.queue_draw()

    def leave(self, now, seconds):
        """Let the piece paint its way out for `seconds`, then hide. The pointer and the keyboard are given back
        at once. The hiding never waits on a paint: the beat does it, and a timer of its own does it again."""
        if self.piece is None or self.left is not None:
            return
        if self.paused_at is not None:              # nothing is painting it: it cannot fold, so it goes
            return self.hide()
        self.left = (now, seconds)
        self._keyboard("none")
        self._region(False)
        run = self.run
        self._after(int(seconds * 1000) + 150, lambda: self.hide() if self.run == run else None)
        self._arm(self.LEAVE_BEAT)

    def pause(self, now=None):
        """Stop repainting. The last frame stays on screen and no timer runs, so the loop costs nothing."""
        if self.piece is None or self.paused_at is not None or self.left is not None:
            return
        self.paused_at = time.monotonic() if now is None else now
        if self.beat_id is not None:
            self._cancel(self.beat_id)
            self.beat_id = None

    def resume(self, now=None):
        """Go on from the frame it was paused on: the time in between did not pass for the loop."""
        if self.piece is None or self.paused_at is None:
            return
        self.epoch += (time.monotonic() if now is None else now) - self.paused_at
        self.paused_at = None
        self._arm(self._period())

    def redraw(self):
        """Paint again at the same moment with fresh inputs: for what changes while the loop is paused."""
        if self.piece is None:
            return
        try:
            self.ctx = dict(self.inputs())
        except Exception as e:
            print(f"eva-desk: motion: {self.piece.name or type(self.piece).__name__}: inputs: {e}", flush=True)
            return self._fail()
        self.view.queue_draw()

    def hide(self):
        had = self.piece is not None
        if self.beat_id is not None:
            self._cancel(self.beat_id)
            self.beat_id = None
        self.piece = self.inputs = self.left = self.paused_at = None
        self.stamps, self.ctx = {}, {}              # a layer that is kept does not keep what it showed: pictures are large
        try:
            if had or self.win.get_visible():
                super().hide()
        except Exception:                           # the window is hidden first; what follows it must not keep the owner from knowing
            traceback.print_exc()
        if had and self.on_hidden:
            self.on_hidden(self)

    def poke(self, kind, x=0.0, y=0.0):
        if self.piece is not None and self.left is None and self.on_poke:
            self.on_poke(self, kind, x, y)

    def _fail(self):
        self.hide()
        if self.on_broken:
            self.on_broken(self)

    def _paint(self, snap, w, h):
        piece = self.piece
        if piece is None or self.broken:
            return
        try:
            kit = Kit(snap, w, h, self.scale, self.stamps)
            try:
                piece.draw(kit, self.at, self.ctx)
            finally:
                kit.close()
        except Exception as e:                      # a loop that cannot paint must not stay up
            print(f"eva-desk: motion: {piece.name or type(piece).__name__}: {e}", flush=True)
            self.broken, run = True, self.run       # GTK is in the middle of drawing this window: hiding it has to
            self._after(0, lambda: self._fail() if self.run == run else None)        # wait for the main loop


class Standby:
    """The standby loop on every monitor: a layer each, one clock for all of them, and what ends it. A key or a
    click ends it, and so does the pointer once it has really moved (triggers.Travel). The layers hold the
    keyboard while it is up, so whatever fails on one of them ends it on all."""

    def __init__(self, app, fps=30, make=None, clock=time.monotonic):
        self.app, self.clock = app, clock
        self.make = make or (lambda app: AmbientLayer(app, "eva-standby", fps, keyboard="exclusive"))
        self.by_monitor = {}                        # Gdk monitor -> its layer, kept from one run to the next
        self.travel = {}                            # layer -> how far the pointer has gone on it in this run
        self.piece = None
        self.on_end = None                          # called each time it has gone from every monitor

    @property
    def up(self):
        return self.piece is not None

    def layers(self):
        return list(self.by_monitor.values())

    def monitors(self):
        """The monitors it is up on."""
        return [monitor for monitor, layer in self.by_monitor.items() if layer.up]

    def start(self, piece, gdk_monitors, inputs):
        """Put the loop on every one of those monitors. True when it is up, also when it already was (its clock
        is not started again); False when no monitor could show it."""
        if self.piece is not None:
            return True
        now, self.travel = self.clock(), {}
        for monitor in gdk_monitors:
            try:
                layer = self.by_monitor.get(monitor)
                if layer is None:
                    layer = self.make(self.app)
                    layer.on_poke, layer.on_broken, layer.on_hidden = self.poke, self._broken, self._hidden
                    self.by_monitor[monitor] = layer
                if layer.play(piece, monitor, inputs, now):
                    self.travel[layer] = Travel()
            except Exception as e:                  # that monitor goes without; the others are not left half started
                print(f"eva-desk: standby: a monitor could not be covered: {e}", flush=True)
        if not self.travel:
            self._release(piece)
            return False
        self.piece = piece
        return True

    def poke(self, layer, kind, x=0.0, y=0.0):
        """Input on a layer that is up ends it, whatever this object believes about itself."""
        if not layer.up:
            return
        if kind == "motion":
            travel = self.travel.get(layer)
            if travel is None or not travel.moved(x, y, self.clock()):
                return
        self.end()

    def end(self, at_once=False):
        """Fold away on every monitor, or go at once. It goes by what is on the layers, not by what it believes is
        up, and one layer that fails does not keep the others."""
        now = self.clock()
        for layer in self.layers():
            try:
                if layer.up:
                    layer.hide() if at_once else layer.leave(now, LEAVE)
            except Exception:
                traceback.print_exc()
        self._settle()

    def _broken(self, layer):
        self.end(at_once=True)

    def _hidden(self, layer):
        self._settle()

    def _settle(self):
        """Once it has gone from every monitor: let the piece go and tell whoever asked."""
        if self.piece is not None and not any(layer.up for layer in self.layers()):
            piece, self.piece = self.piece, None
            self._release(piece)
            if self.on_end:
                try:
                    self.on_end()
                except Exception:
                    traceback.print_exc()

    def _release(self, piece):
        try:
            piece.release()
        except Exception as e:
            print(f"eva-desk: motion: {piece.name or type(piece).__name__}: release: {e}", flush=True)

    def forget(self, alive):
        """Destroy the layers of monitors that are not among `alive`."""
        alive = list(alive)
        for monitor in [m for m in self.by_monitor if m not in alive]:
            layer = self.by_monitor.pop(monitor)
            self.travel.pop(layer, None)
            layer.hide()
            layer.destroy()
