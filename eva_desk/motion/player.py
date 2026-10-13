"""The player: one motion piece at a time on one monitor, on the overlay layer.

It never takes the keyboard. A piece that covers the screen takes the pointer, and a click ends it; a piece that
does not is clicked straight through. Whatever happens, a sequence cannot stay on screen: it ends at its length,
on a click, when painting raises, and one second after its length if nothing else ended it. One that cannot
prepare is not shown at all.
"""
import cairo

from .. import gtkutil  # noqa: F401  (pins GTK 4 before any gi.repository import)

from gi.repository import GLib, Gtk  # noqa: E402

from ..overlays import _Overlay  # noqa: E402
from .kit import Kit  # noqa: E402
from .triggers import outranks  # noqa: E402


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
