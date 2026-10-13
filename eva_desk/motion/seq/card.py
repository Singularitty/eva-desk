"""The card: an app's launch, told flat in the title-card language. Two seconds, every move eased.

Two slanted ink plates close over the desk; 発 and 進 arrive and turn to ink inside a bone slab; the slab folds
to a rule and the app's name rises from behind it letter by letter; everything lifts off; the plates part.
Inputs (all optional): ctx["app"], ctx["workspace"], ctx["clock"].
"""
import contextlib
import math

from ... import draw as d
from .. import Piece
from ..timeline import clamp, expo_in, lerp, noise, quint_out, seg, smooth

SLANT = 190        # how far the seam leans over the height
INSET = 64         # the side margin of the rule and of the name
OVER = 0.75        # each plate reaches this far past its seam, so no hairline of desk shows where they meet
EDGE = 16          # the hazard edge a plate carries on its seam
STRIPE = 30        # one claret stripe and one gap of that edge


def plates(W, H, p):
    """The two plates as polygons: p = 0 apart and off the screen, 1 met on the slanted seam."""
    cx, half = W / 2, SLANT / 2
    off = (1 - p) * (W / 2 + SLANT + 40)
    left = [(-W - off, 0), (cx + half - off, 0), (cx - half - off, H), (-W - off, H)]
    right = [(2 * W + off, 0), (cx + half + off, 0), (cx - half + off, H), (2 * W + off, H)]
    return left, right


def letters(kit, name):
    """What rises one piece at a time: the name's letters, or the whole name where cutting it would spoil it."""
    return kit.letters(name, 170, face="display") or [name]


def name_width(kit, name, size):
    """The name as the card sets it: letter by letter, each 4 px tighter than its own advance."""
    return sum(kit.measure(part, size, face="display") - 4 for part in letters(kit, name))


def name_size(kit, name):
    """170, or smaller when the name would not fit between the margins; never under 24."""
    room, n = kit.W - 2 * INSET, len(letters(kit, name))
    wide = name_width(kit, name, 170)
    if wide <= room:
        return 170
    size = max(24, int(170 * (room + 4 * n) / (wide + 4 * n)))
    while size > 24 and name_width(kit, name, size) > room:        # glyph widths round, so step down the last bit
        size -= 1
    return size


def _label(ctx):
    return str(ctx.get("app") or "APP")


def _seam_edge(kit, top, side, H, alpha):
    """The hazard edge of one plate: the stripes of kit.hazard inside the EDGE px of plate along a seam that meets
    the top of the frame at x = `top`. The seam leans, so a stripe cut by the edge's two sides is a parallelogram."""
    lean = SLANT / H
    near, far = sorted((top, top + EDGE * side))            # the two sides of the edge, each the line x + lean * y = this

    def meet(c, e):                                         # where a stripe's side, x + y = c, crosses one of them
        y = (c - e) / (1 - lean)
        return c - y, y

    start = top - 1.5 * SLANT                               # the stripes ride the plate: their phase is taken from the seam
    c = start + STRIPE * math.ceil((near - STRIPE / 2 - start) / STRIPE)
    while c <= far + H * (1 - lean):
        kit.para(meet(c, near), meet(c + STRIPE / 2, near), meet(c, far), d.CLARET, alpha)
        c += STRIPE


class Card(Piece):
    name, length, covers, still = "card", 2.0, True, 1.15

    def prepare(self, kit, ctx):
        for colour in (d.BONE, d.INK):                      # the kanji as stamps, so the fold does not wait for them
            for ch in "発進":
                kit.stamp(ch, 0, 0, 380, colour, face="display")

    def paint(self, kit, t, ctx):
        W, H = kit.W, kit.H
        p = quint_out(seg(t, 0, 0.26)) * (1 - smooth(seg(t, 1.62, 2.0)))
        left, right = plates(W, H, p)
        (lt, lb), (rt, rb) = (left[1][0], left[2][0]), (right[1][0], right[2][0])      # each seam's x at the top and at the floor
        kit.para((lt + OVER, 0), (lt - 3 * W, 0), (lb + OVER, H), d.INK)               # a plate is a sheared rectangle
        kit.para((rt - OVER, 0), (rt + 3 * W, 0), (rb - OVER, H), d.INK)
        if p <= 0.995:                                      # a hazard edge inside each seam, only while the plates move
            for top, side in ((lt, -1), (rt, 1)):
                _seam_edge(kit, top, side, H, clamp(5 * (1 - p)))
        if not 0.12 <= t <= 1.9:
            return
        apart = rt - lt > 0.5                               # everything else lives on the plates: cut the gap out of it
        with kit.clip_out_para((lt, 0), (rt, 0), (lb, H)) if apart else contextlib.nullcontext():
            lift = expo_in(seg(t, 1.25, 1.62))
            with kit.transform(dy=-1.3 * H * lift):         # lift-off: it all leaves upward
                self._title(kit, t, ctx, W, H)
            self._speed_lines(kit, t, W, H, lift)

    def _title(self, kit, t, ctx, W, H):
        cx, cy = W / 2, H / 2
        fold = smooth(seg(t, 0.64, 0.84))                   # the slab folds to a rule, the kanji shrink into a tag
        ry = lerp(cy, 0.60 * H, fold)
        slab_h = lerp(300, 4, fold)
        slab_w = lerp(W * smooth(seg(t, 0.30, 0.56)), W - 2 * INSET, fold)
        away = (1 - quint_out(seg(t, 0.14, 0.50))) * (H / 2 + 200)     # the kanji come from outside the frame, whatever its height
        put = kit.stamp if 0 < fold < 1 else kit.text       # while they shrink they change size every frame: stamps

        def kanji(colour):
            with kit.transform(dx=lerp(cx, 142, fold), dy=lerp(cy + 128, 136, fold), scale=lerp(1, 0.2, fold)):
                put("発", -190, away, 380, colour, face="display", align="center")
                put("進", 190, -away, 380, colour, face="display", align="center")

        kanji(d.BONE)
        if slab_w > 1:                                      # inside the slab the kanji are ink on bone
            with kit.clip(cx - slab_w / 2, ry - slab_h / 2, slab_w, slab_h):
                kit.rect(cx - slab_w / 2, ry - slab_h / 2, slab_w, slab_h, d.BONE)
                kanji(d.INK)
        if t < 0.78:
            return
        name = _label(ctx)
        parts = letters(kit, name)
        size, base, x = name_size(kit, name), ry - 16, INSET
        step = min(0.035, 0.30 / len(parts))                # a long name still finishes before lift-off
        for i, part in enumerate(parts):                    # the name rises from behind the rule, a letter at a time
            w = kit.measure(part, size, face="display")
            r = quint_out(seg(t, 0.80 + step * i, 1.08 + step * i))
            if r > 0:
                with kit.clip(x - 12, base - size, w + 24, size + 14):
                    kit.text(part, x, base + (1 - r) * size, size, d.BONE, face="display")
            x += w - 4
        parts, ws = ["TARGET", name], ctx.get("workspace")
        if ws is not None:
            parts.append(f"WORKSPACE {ws:02d}" if isinstance(ws, int) else f"WORKSPACE {ws}")
        if ctx.get("clock"):
            parts.append(str(ctx["clock"]))
        meta = " ・ ".join(parts)
        with kit.clip(INSET, ry + 8, kit.measure(meta, 13, spacing=4) * smooth(seg(t, 0.92, 1.2)), 30):
            kit.text(meta, INSET, ry + 30, 13, d.RED, spacing=4)
        kit.rect(INSET, ry - 2, (W - 2 * INSET) * smooth(seg(t, 0.84, 1.24)), 4, d.GOLD)

    def _speed_lines(self, kit, t, W, H, lift):
        sa = seg(t, 1.25, 1.42) * (1 - seg(t, 1.62, 1.84))
        if sa <= 0:
            return
        for i in range(46):
            x, length = noise(i, 51) * W, (60 + 520 * noise(i, 52)) * (0.3 + lift)
            y = ((noise(i, 53) + 2.4 * t * (0.6 + noise(i, 54))) % 1.3) * H - 0.2 * H
            kit.rect(x, y, 2, length, d.GOLD if noise(i, 55) > 0.75 else d.BONE, 0.55 * sa)
