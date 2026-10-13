"""Boot: the desk comes up like MAGI starting. Once per Hyprland session, on every main monitor; 2.6 seconds.

Check lines type on over ink while a bar fills along the floor and the A.T. field assembles on the right; episode
zero takes the title; then the gate: the picture splits along a line through the digits and the two parts leave,
the desk underneath. Brackets settle on the screen's edge and ALL GREEN holds for a moment.
Inputs (all optional): ctx["outputs"], ctx["hyprland"], ctx["lua"], ctx["net"], ctx["bar"].
"""
import contextlib
import math

from ... import draw as d
from .. import Piece, bar_height
from ..kit import hex_cells
from ..timeline import back_out, cubic_out, noise, seg, smooth, stepped, twos

SEAM = 0.62            # the gate opens along this share of the height
CELL = 58              # the field's cells
FILL = 0.22 / 0.6      # one cell in six is filled, at this share of its line's strength
STRENGTH = (0.24, 0.6) # a cell arrives in two steps: a dim outline, then its full one


def lines(ctx):
    """The six check lines, each with its status (None for the header)."""
    outputs = [str(o) for o in ctx.get("outputs") or []]
    net = str(ctx.get("net") or "lan").upper()
    return [("EVA-DESK ・ 起動シーケンス", None),
            ("MAGI-1  MELCHIOR   CPU", "OK"),
            ("MAGI-2  BALTHASAR  RAM", "OK"),
            (f"MAGI-3  CASPER     {net}", "DOWN" if net == "NONE" else "OK"),
            ("OUTPUT  " + (" ・ ".join(outputs[:3]) or "NONE"), f"{len(outputs)} UP"),
            (f"HYPRLAND {ctx.get('hyprland') or ''} ・ {'LUA' if ctx.get('lua', True) else 'LEGACY'}", "LINKED")]


class Boot(Piece):
    name, length, covers, still = "boot", 2.6, True, 1.6

    def __init__(self):
        self.cells = {}                                     # (W, H) -> the field's cells, with what does not change from frame to frame

    def prepare(self, kit, ctx):
        for strength in STRENGTH:                           # the four pictures the field is made of
            for fill in (0.0, FILL):
                kit.hexagon(0, 0, CELL - 3, d.col("claret", strength), fill=fill)

    def paint(self, kit, t, ctx):
        W, H = kit.W, kit.H
        seam, bar = round(SEAM * H), bar_height(kit, ctx)
        opened = smooth(seg(t, 1.95, 2.35))
        if opened <= 0:
            self._card(kit, t, ctx, W, H, seam)
        elif opened < 1:                                    # the gate: the card in two parts, cut at the seam, each on its way out
            up, down = (seam + 14) * opened, (H - seam + 14) * opened
            for part, top, height, dy in (("upper", -up, seam, -up), ("lower", seam + down, H - seam, down)):
                with kit.clip(0, top, W, height):
                    with kit.transform(dy=dy):
                        self._card(kit, t, ctx, W, H, seam, part)
            kit.hazard(0, seam - up - 12, W, 12, d.CLARET, d.INK, period=30)
            kit.hazard(0, seam + down, W, 12, d.CLARET, d.INK, period=30)
        if 1.95 <= t < 1.99:                                # the seam is marked as it opens
            kit.rect(0, seam - 2, W, 4, d.BONE)
        if 2.30 <= t < 2.58:
            with kit.transform(dx=W / 2, dy=H / 2, scale=1.05 - 0.05 * back_out(seg(t, 2.30, 2.48))):
                kit.brackets(10 - W / 2, bar + 10 - H / 2, W / 2 - 10, H / 2 - 10, 34, d.BONE, 3)
            tag = "全系統正常 ・ ALL GREEN"
            tw, shown = kit.measure(tag, 17, face="display", spacing=1) + 28, stepped(seg(t, 2.36, 2.44), 3)
            if shown > 0:
                kit.rect(W - 24 - tw * shown, bar + 18, tw * shown, 30, d.GOLD)
                if shown >= 1:
                    kit.text(tag, W - 10 - tw, bar + 39.5, 17, d.INK, face="display", spacing=1)

    def _card(self, kit, t, ctx, W, H, seam, part=None):
        """The whole card, or while the gate opens the part of it above ("upper") or below ("lower") the seam: each
        part leaves out what only the other one shows, so a gate frame costs about what a whole one does."""
        kit.rect(0, 0, W, H, d.INK)
        self._field(kit, t, W, H, seam, part)
        if part != "lower":                                 # the check lines stand above the seam
            with kit.opacity(0.42) if t > 1.15 else contextlib.nullcontext():     # they step back when the title takes over
                self._lines(kit, t, ctx)
        if part != "upper":                                 # the bar along the floor, on twos
            p = seg(twos(t), 0.04, 1.12)
            kit.segbar(64, H - 46, W - 198, 10, p, d.GOLD, 62)
            kit.text(f"{round(100 * p):03d}", W - 64, H - 36, 15, d.GOLD if p >= 1 else d.BONE2, spacing=2, align="right")
            kit.hazard(0, H - 14, W, 14, d.CLARET, period=40)
        if t >= 1.15:
            self._title(kit, t, seam - 446)                 # the title block rides the seam: the gate opens through the digits

    def _field(self, kit, t, W, H, seam, part):
        """The A.T. field: it assembles outward from one cell on the right, on twos, each cell in two steps. A cell's
        strength is in its picture, so a cell is one node."""
        if t <= 0.5:
            return
        cells = self.cells.get((W, H))
        if cells is None:
            cells = self.cells[(W, H)] = [(cx, cy, 0.55 * math.hypot(cx - 0.72 * W, cy - 0.48 * H) / (0.45 * W), FILL if noise(col, row) > 0.84 else 0.0)
                                          for cx, cy, col, row in hex_cells(0.40 * W, 0, W, H, CELL) if cx >= 0.40 * W]
        tt, dim, full = twos(t), d.col("claret", STRENGTH[0]), d.col("claret", STRENGTH[1])
        for cx, cy, late, fill in cells:
            if (part == "upper" and cy - CELL >= seam) or (part == "lower" and cy + CELL <= seam):
                continue
            u = seg(tt, 0.55 + late, 0.72 + late)
            if u > 0:
                kit.hexagon(cx, cy, CELL - 3, dim if u < 0.6 else full, fill=fill)

    def _lines(self, kit, t, ctx):
        for i, (label, status) in enumerate(lines(ctx)):
            s = 0.04 + 0.085 * i
            typed = seg(t, s, s + 0.07)
            if typed <= 0:
                continue
            y, shown = 84 + 25 * i, label[:math.ceil(len(label) * typed)]
            if status is None:
                kit.text(shown, 64, y, 17, d.BONE, face="display", spacing=1)
                continue
            kit.text(shown, 64, y, 13.5, d.BONE2, spacing=2)
            start = 74 + kit.measure(label, 13.5, spacing=2)
            dots = math.floor((530 - start) / 8 * seg(t, s + 0.07, s + 0.16))     # dots run to the status column
            if dots > 0:
                with kit.tile(start, y - 5, 8 * dots, 2, 8, 2):
                    kit.rect(start, y - 5, 2, 2, d.col("ink5"))
            if t >= s + 0.18:
                kit.lamp(544, y - 10, 9, d.GOLD)
                kit.text(status, 562, y, 13.5, d.GOLD, spacing=2)

    def _title(self, kit, t, oy):
        """Episode zero, in the eye-catch's layout."""
        label = "EPISODE"
        kit.text(label[:math.ceil(len(label) * seg(t, 1.15, 1.30))], 150, 262 + oy, 21, d.RED, spacing=8)
        size, base, x = 330, 560 + oy, 136
        cap = 0.74 * size
        for i, digit in enumerate("00"):                    # each digit rolls up into place
            w = kit.measure(digit, size, face="display")
            u = cubic_out(seg(t, 1.15 + 0.07 * i, 1.37 + 0.07 * i))
            with kit.clip(x - 10, base - cap - 16, w + 20, cap + 34):
                kit.text(digit, x, base + (1 - u) * 0.9 * size, size, d.BONE, face="display")
            x += w - 18
        plate = "第零話 ・ 起動"
        pw, opened = kit.measure(plate, 38, face="display") + 44, stepped(seg(t, 1.36, 1.48), 3)
        if opened > 0:
            kit.rect(150, 590 + oy, pw * opened, 56, d.BONE)
            if opened >= 1:
                kit.text(plate, 172, 632 + oy, 38, d.INK, face="display")
