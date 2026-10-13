"""Wake: back from the lock screen or from sleep. 1.1 seconds, covering every main monitor.

On ink, one line draws out from the centre and splits into two waves that close on each other while the sync ratio
runs up; they lock into one bone line and a plate; then the cover folds to a line in three steps and the line closes.
Its first frame is ink with the hazard strip on the floor: that is what waits under the lock screen until it opens.
No inputs.
"""
import math

from ... import draw as d
from .. import Piece
from ..timeline import cubic_in, cubic_out, lerp, seg, smooth, stepped, twos

MARGIN = 64            # the graph and its type keep this far from the sides
WAVE = 430             # the waves' length
STEP = 12              # a wave is drawn as straight pieces this long


class Wake(Piece):
    name, length, covers, still = "wake", 1.1, True, 0.4

    def paint(self, kit, t, ctx):
        if t >= 1.08:
            return
        W, H = kit.W, kit.H
        fold = stepped(seg(t, 0.85, 0.97), 3)               # the cover folds to a line, and the line closes on the centre
        hh, ww = H * (1 - 0.98 * fold), W * (1 - cubic_in(seg(t, 0.97, 1.08)))
        with kit.clip((W - ww) / 2, (H - hh) / 2, ww, hh):
            if fold >= 1:
                kit.rect(0, 0, W, H, d.BONE)
            else:
                self._cover(kit, t, W, H)

    def _cover(self, kit, t, W, H):
        cy, locked, span = H / 2, t >= 0.62, W - 2 * MARGIN
        kit.rect(0, 0, W, H, d.INK)
        kit.scanlines(0, 0, W, H, 0.025)
        frame = seg(t, 0.06, 0.16)
        if frame > 0:                                       # the graph's frame
            ink5 = d.col("ink5")
            kit.rect(MARGIN, cy - 100, span, 1, ink5, frame)
            kit.rect(MARGIN, cy + 100, span, 1, ink5, frame)
            with kit.tile(MARGIN, cy - 100, span + 1, 200, 86, 200):
                kit.rect(MARGIN, cy - 100, 1, 200, ink5, frame)
            for label, y in (("+1.0", cy - 88), (" 0.0", cy + 4), ("-1.0", cy + 96)):
                kit.text(label, 26, y, 9.5, d.BONE3, alpha=frame)
        if 0.12 <= t < 0.62:                                # two waves close on each other
            e = smooth(seg(t, 0.12, 0.62))
            amp, k = 80 * (1 - 0.88 * e), 2 * math.pi / WAVE
            xs = [min(W - MARGIN, MARGIN + STEP * i) for i in range(math.ceil(span / STEP) + 1)]
            for colour, a, phase in ((d.RED, 0.9, 0.95 * math.pi * (1 - e)), (d.GOLD, 1.0, 0.0)):
                ys = [cy + amp * a * math.sin(k * x - 10 * t + phase) for x in xs]
                kit.lines([(xs[i], ys[i], xs[i + 1], ys[i + 1]) for i in range(len(xs) - 1)], colour, 3)
        elif locked:                                        # locked: one bone line
            kit.rect(MARGIN, cy - 2, span, 4, d.BONE)
        else:                                               # before: the line draws out from the centre
            lw = span * cubic_out(seg(t, 0, 0.12))
            kit.rect(W / 2 - lw / 2, cy - 1.5, lw, 3, d.GOLD)
        if t >= 0.08:
            kit.text("PILOT RE-ENTRY ・ SYNC RATIO", 66, 96, 13, d.GOLD, spacing=4)
            kit.text("同期", 60, 216, 116, d.BONE, face="display")
            ratio = 100.0 if locked else lerp(41.3, 99.9, cubic_out(seg(twos(t), 0.12, 0.62)))
            pw = kit.text("%", W - MARGIN, 216, 44, d.GOLD if locked else d.BONE2, face="display", align="right")
            kit.text(f"{ratio:.1f}", W - MARGIN - pw - 8, 216, 116, d.GOLD if locked else d.BONE, face="display", align="right")
        if locked:
            plate = "同期完了 ・ SYNCHRONISED"
            pw, opened = kit.measure(plate, 30, face="display", spacing=1) + 44, stepped(seg(t, 0.62, 0.72), 3)
            kit.rect(MARGIN, cy + 134, pw * opened, 50, d.BONE)
            if opened >= 1:
                kit.text(plate, 86, cy + 170, 30, d.INK, face="display", spacing=1)
                kit.lamp(80 + pw, cy + 152, 14, d.GOLD)
        kit.hazard(0, H - 14, W, 14, d.CLARET, period=40)
