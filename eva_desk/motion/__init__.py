"""Motion: sequences that play once when something happens, and slow loops for when nothing does.

A piece paints one frame at a time into a GTK snapshot through the kit (kit.py). The player (player.py) hosts a
piece on a layer surface; the renderer (render.py) draws the same snapshot through cairo with no display, so
the frames the tests look at come from the code that runs on the desk.
"""


class Piece:
    """One motion piece. It is a function of time and of the inputs in `ctx`: it never reads the clock or the
    system itself, so the same call paints the same frame every time."""

    name = ""        # the registry key
    length = None    # seconds; None = a loop
    covers = True    # takes the pointer while it plays; a click skips it
    still = 0.0      # the moment `eva-desk --render` shows

    def prepare(self, kit, ctx):
        """Build what is expensive before the first frame: pictures, and the stamps of type that changes size
        (kit.stamp keeps them; calling it here makes them early). A piece must also paint without this."""

    def paint(self, kit, t, ctx):
        raise NotImplementedError

    def release(self):
        """Drop what prepare() built."""

    def draw(self, kit, t, ctx):
        """paint(), unless a sequence is before its start or at or past its end."""
        if self.length is not None and not 0 <= t < self.length:
            return
        self.paint(kit, t, ctx)


def available():
    """Whether this GTK can draw the pieces: they cut holes with mask nodes, which came with GTK 4.10."""
    from .. import gtkutil  # noqa: F401  (pins GTK 4 before any gi.repository import)
    from gi.repository import Gtk
    return hasattr(Gtk.Snapshot, "push_mask")


def pieces():
    """Every piece by name. Imported here, when asked, so that importing the package stays cheap."""
    from .seq.card import Card
    from .seq.shaft import Shaft
    return {"card": Card, "shaft": Shaft}
