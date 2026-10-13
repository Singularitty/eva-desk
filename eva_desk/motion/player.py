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

    def play(self, piece, gdk_monitor, ctx, on_done=None):
        """Play `piece` on that monitor, in place of whatever was playing. False when it cannot be played:
        there is no monitor, or the piece failed to prepare."""
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
        self.piece, self.ctx, self.on_done = piece, ctx, on_done
        self.at, self.started = 0.0, None
        self.run += 1
        run = self.run
        if piece.length is not None:               # the safety: one second past its length it is gone, whatever happened,
            self._after(int((piece.length + 1) * 1000), lambda: self.finish() if self.run == run else None)     # showing it included
        self.show()
        surface = self.win.get_surface()
        if surface is not None:
            whole = cairo.Region(cairo.RectangleInt(0, 0, int(self.w), int(self.h)))
            surface.set_input_region(whole if piece.covers else cairo.Region())
        self.tick_id = self.view.add_tick_callback(self._tick)
        return True

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
        self.stamps = {}
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
