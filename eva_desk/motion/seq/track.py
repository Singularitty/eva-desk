"""The track card: a new title has started playing. 1.6 seconds in a corner of one monitor; it never takes input.

A gold rule draws out; two ink slabs open from it, the title rising from behind the rule above and the artist
dropping from it below; it holds still, whatever the music does; then the type goes back into the rule and the
rule retracts.
Inputs: ctx["title"] (with none, nothing is painted), ctx["artist"] (may be empty), ctx["corner"].
"""
from ... import draw as d
from .. import Piece
from ..timeline import back_out, clamp, cubic_in, cubic_out, seg

SIDE, FLOOR = 44, 96           # the card keeps this far from the side; its rule is this far above the floor
TITLE, ARTIST = 62, 32         # the two slabs' heights, above and below the rule
TAG = "再生 ・ NOW PLAYING"


def card_width(kit, title, artist):
    """The wider of title and artist plus 52, kept between 320 and 640."""
    return clamp(max(kit.measure(title, 38, face="display"), kit.measure(artist, 13.5, spacing=3)) + 52, 320, 640)


class Track(Piece):
    name, length, covers, still, rank = "track", 1.6, False, 0.8, 0

    def paint(self, kit, t, ctx):
        title, artist = str(ctx.get("title") or ""), str(ctx.get("artist") or "").upper()
        if not title:
            return
        right = ctx.get("corner") == "bottom-right"
        cw = card_width(kit, title, artist)
        x0, ry = (kit.W - SIDE - cw if right else SIDE), kit.H - FLOOR
        below = ARTIST if artist else 0
        up = cubic_out(seg(t, 0.14, 0.34)) * (1 - cubic_in(seg(t, 1.24, 1.42)))      # the slabs open from the rule
        if up > 0:
            kit.block(x0, ry - TITLE * up, cw, (TITLE + below) * up, d.col("ink_deep", 0.95), shadow=d.CLARET, off=7)
            rise = back_out(seg(t, 0.20, 0.48), 1.1) * (1 - cubic_in(seg(t, 1.18, 1.36)))
            with kit.clip(x0, ry - TITLE * up, cw, TITLE * up):                    # the title rises from behind the rule
                kit.text(title, x0 + 22, ry - 18 + (1 - rise) * TITLE, 38, d.BONE, face="display", width=cw - 44)
            if artist:
                drop = cubic_out(seg(t, 0.28, 0.50)) * (1 - cubic_in(seg(t, 1.18, 1.34)))
                with kit.clip(x0, ry, cw, ARTIST * up):                            # the artist drops from it
                    kit.text(artist, x0 + 24, ry + 21 - (1 - drop) * ARTIST, 13.5, d.BONE2, spacing=3, width=cw - 48)
        rule = cw * cubic_out(seg(t, 0, 0.20)) * (1 - cubic_in(seg(t, 1.40, 1.58)))
        kit.rect(x0 + cw - rule if right else x0, ry - 1.5, rule, 3, d.GOLD)
        if 0.08 <= t < 1.42:
            top = ry - TITLE * up - 24
            kit.rect(x0, top, kit.measure(TAG, 11, face="display", spacing=2) + 18, 18, d.GOLD)
            kit.text(TAG, x0 + 9, top + 13.5, 11, d.INK, face="display", spacing=2)
