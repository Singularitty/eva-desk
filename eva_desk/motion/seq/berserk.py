"""Berserk: sustained load has crossed the limit. 1.3 seconds on the edges of the screen; it never takes input.

Two orange hazard strips run in, under the bar from the left and along the floor from the right, and a line grows
along each side; the 暴走 block slams in at the lower left and the load types on under it; everything leaves the
way it came.
Inputs (all optional): ctx["load"], ctx["seconds"], ctx["bar"].
"""
import contextlib
import math

from ... import draw as d
from .. import Piece, bar_height
from ..timeline import back_out, cubic_in, cubic_out, seg, stepped

STRIP = 16                     # the hazard strips' height
X, WIDE, HIGH = 40, 300, 168   # the block; it stands 34 px above the floor strip
SHADOW = 9                     # how far its hard shadow reaches
KANJI = ("暴走", 122)


class Berserk(Piece):
    name, length, covers, still, rank = "berserk", 1.3, False, 0.7, 1

    def prepare(self, kit, ctx):
        kit.stamp(KANJI[0], 0, 0, KANJI[1], d.INK, face="display", spacing=-2, most=1.3)

    def paint(self, kit, t, ctx):
        W, H = kit.W, kit.H
        top = bar_height(kit, ctx) + 3
        out = cubic_in(seg(t, 0.98, 1.28))                  # everything leaves the way it came
        wide = W * cubic_out(seg(t, 0, 0.22)) * (1 - out)
        if wide > 0:                                        # the strips crawl while they are up
            kit.hazard(0, top, wide, STRIP, d.LED, d.INK, period=30, offset=46 * t)
            kit.hazard(W - wide, H - STRIP, wide, STRIP, d.LED, d.INK, period=30, offset=-46 * t)
        long = (H - top) * cubic_out(seg(t, 0.10, 0.32)) * (1 - out)
        kit.rect(0, top, 4, long, d.LED)
        kit.rect(W - 4, H - long, 4, long, d.LED)
        u, closing = seg(t, 0.18, 0.40), stepped(seg(t, 0.95, 1.07), 3)
        if u > 0 and closing < 1:
            self._block(kit, t, ctx, H - STRIP - 34 - HIGH, u, closing)

    def _block(self, kit, t, ctx, y, u, closing):
        cx, cy = X + WIDE / 2, y + HIGH / 2
        tall = (HIGH + SHADOW) * (1 - 0.98 * closing)       # it closes like a panel: cut about its centre, in three steps
        cut = kit.clip(X, y + (HIGH + SHADOW - tall) / 2, WIDE + SHADOW, tall) if closing > 0 else contextlib.nullcontext()
        with cut, kit.opacity(0.5) if u < 0.25 else contextlib.nullcontext():
            with kit.transform(dx=cx, dy=cy, scale=1.3 - 0.3 * back_out(u)):     # it slams in from 130 %, a little past its size and back
                kit.block(X - cx, y - cy, WIDE, HIGH, d.LED, shadow=d.BONE, off=SHADOW * cubic_out(u))
                if u < 1:                                   # still changing size: a stamp
                    kit.stamp(KANJI[0], X + 22 - cx, y + 116 - cy, KANJI[1], d.INK, face="display", spacing=-2, most=1.3)
                else:
                    kit.text(KANJI[0], X + 22 - cx, y + 116 - cy, KANJI[1], d.INK, face="display", spacing=-2)
                seconds = ctx.get("seconds")
                line = f"BERSERK ・ {ctx.get('load') or 'CPU 97%'} ・ {30 if seconds is None else seconds} S"
                kit.text(line[:math.ceil(len(line) * seg(t, 0.40, 0.60))], X + 26 - cx, y + 150 - cy, 12.5, d.INK, spacing=3)
