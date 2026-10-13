"""Standby: what covers every monitor when nobody is there.

Four shots of fifteen seconds with hard cuts between them: the Eva in profile, a field of hexagons, the whole
figure, the face from the front. Nearly all of it is black. The eyes breathe, a light passes over the armour, and
the real clock stands somewhere else in every shot.

The three pictures are files (assets/motion, or the theme's own motion folder), each in two layers that go on with
a screen blend, so that the black of the picture is the ink of the frame. A picture that is not there leaves its
shot out; with none of them the loop is the field alone.
"""
import json
import math
from pathlib import Path

from ... import gtkutil  # noqa: F401  (pins GTK 4 before any gi.repository import)

from gi.repository import Gdk, GLib  # noqa: E402

from ... import config  # noqa: E402
from ... import draw as d  # noqa: E402
from .. import Piece  # noqa: E402
from ..kit import hex_cells  # noqa: E402
from ..timeline import clamp, cubic_in, cubic_out, noise, seg, smooth, stepped  # noqa: E402

SHOT = 15.0      # seconds a shot
BAR = 44.0       # the letterbox bars
LEAVE = 0.19     # the fold away
ORDER = ("profile", "field", "tilt", "stare")
PICTURE = {"profile": "profile", "tilt": "full", "stare": "front"}        # the picture each shot needs; the field needs none


def shot_at(t, shots):
    """(shot, how far through it from 0 to 1, its place in `shots`) at t seconds."""
    index = int(t // SHOT) % len(shots)
    return shots[index], (t % SHOT) / SHOT, index


def breathe(t):
    """The strength of the eyes: one breath in six seconds, between 0.40 and 1.00."""
    return 0.70 + 0.30 * math.sin(2 * math.pi * t / 6)


def passing(t):
    """The middle of the passing light, in widths of the picture's box: it crosses once in nine seconds, from
    well before the left edge to well past the right one."""
    return (t % 9) / 9 * 1.6 - 0.3


def tilt(u):
    """The pan of the tilt: 1 at the feet, 0 at the head, over the first three quarters of the shot."""
    return 1 - smooth(seg(u, 0.04, 0.74))


def fold(since):
    """Leaving: (the share of the width still shown, the share of the height, whether what is left is the line).
    The height folds in three steps over 0.14 s, then the line closes from both ends."""
    f = stepped(since / 0.14, 3)
    return 1 - cubic_in(seg(since, 0.14, LEAVE)), 1 - 0.98 * f, f >= 1


class StandbyLoop(Piece):
    name = "standby"
    length = None
    lap = 60.0       # what the offline renderer shows of it
    covers = True
    still = 4.0

    def __init__(self, folder=None):
        """`folder` holds the pictures; with none given they are the theme's, or the desk's own."""
        self.folder = None if folder is None else Path(folder)
        self.art = None          # picture -> (body, eye glow, where the eyes are); None until they are loaded
        self.said = set()        # what has been logged, so that a reload does not say it again

    # ---------------------------------------------------------------- the pictures
    def _base(self):
        """Where the pictures are: the folder it was given, else the theme's own if it brings an art.json, else the
        desk's. One folder for all of them: a picture's layers and its eyes belong together."""
        if self.folder is not None:
            return self.folder
        theme = config.theme_dir() / "motion"
        return theme if (theme / "art.json").exists() else config.ASSETS / "motion"

    def _say(self, what):
        if what not in self.said:
            self.said.add(what)
            print(f"eva-desk: standby: {what}", flush=True)

    def _load(self):
        if self.art is not None:
            return self.art
        self.art = {}
        base = self._base()
        try:
            entries = json.loads((base / "art.json").read_text())
            if not isinstance(entries, dict):
                raise ValueError("art.json is not a table")
        except (OSError, ValueError) as e:
            self._say(f"no pictures: {e}")
            return self.art
        for name in sorted(set(PICTURE.values())):
            try:
                entry = entries.get(name)
                if not isinstance(entry, dict):
                    raise ValueError("not in art.json")
                eyes = [(float(x), float(y)) for x, y in entry.get("eyes", [])]
                layers = [Gdk.Texture.new_from_filename(str(base / f"{name}_{layer}.jpg")) for layer in ("body", "eye")]
                self.art[name] = (layers[0], layers[1], eyes)
            except (GLib.Error, TypeError, ValueError) as e:
                self._say(f"{name}: {e}")
        return self.art

    def shots(self):
        """The shots the loop cuts between: all four, without those whose picture is not there."""
        art = self._load()
        return [shot for shot in ORDER if shot not in PICTURE or PICTURE[shot] in art]

    def prepare(self, kit, ctx):
        self._load()

    def release(self):
        self.art = None

    # ---------------------------------------------------------------- a frame
    def paint(self, kit, t, ctx):
        leaving = ctx.get("leaving")
        if leaving is None:
            self._frame(kit, t, ctx)
            return
        wide, high, line = fold(max(0.0, leaving))
        if wide <= 0:
            return
        w, h = kit.W * wide, kit.H * high
        x, y = (kit.W - w) / 2, (kit.H - h) / 2
        if line:                                             # what is left of the picture: a line, closing
            kit.rect(x, y, w, h, d.BONE)
        else:
            with kit.clip(x, y, w, h):
                self._frame(kit, t, ctx)

    def _frame(self, kit, t, ctx):
        shots = self.shots()
        shot, u, index = shot_at(t, shots)
        kit.rect(0, 0, kit.W, kit.H, d.INK)
        getattr(self, "_" + shot)(kit, t, u, ctx)
        self._bars(kit, t, ctx, index, len(shots))

    def _bars(self, kit, t, ctx, index, count):
        """The letterbox: two ink bars over the shot, each with a hazard edge that crawls, and what is written in them."""
        W, H = kit.W, kit.H
        kit.rect(0, 0, W, BAR, d.INK)
        kit.rect(0, H - BAR, W, BAR, d.INK)
        kit.hazard(0, BAR - 4, W, 4, d.CLARET, None, 24.0, 4 * t)
        kit.hazard(0, H - BAR, W, 4, d.CLARET, None, 24.0, -4 * t)
        title = kit.text("待機 ・ STANDBY", 28, 27, 15, d.GOLD, face="display", spacing=2)
        readings = "    ".join(str(r) for r in ctx.get("readings") or [])
        room = W - 28 - title - 40 - 28
        if readings and room > 60:
            kit.text(readings, W - 28, 26, 11, d.BONE3, spacing=2, align="right", width=room)
        kit.text(f"SHOT {index + 1:02d} / {count:02d}", 28, H - 16, 11, d.BONE3, spacing=3)
        kit.text("任意のキーで復帰 ・ ANY KEY", W - 28, H - 15, 12, d.BONE3, face="display", spacing=2, align="right")

    def _clock(self, kit, ctx, x, y, size, align):
        """The time, the seconds as a bar of sixty under it, and the date under that."""
        clock = str(ctx.get("clock") or "00:00")
        w = kit.measure(clock, size, face="display")
        left = x - w if align == "right" else x
        kit.text(clock, left, y, size, d.BONE, face="display")
        try:
            second = float(ctx.get("second") or 0)
        except (TypeError, ValueError):
            second = 0.0
        bar = max(4.0, size * 0.035)
        kit.segbar(left + size * 0.03, y + size * 0.13, w - size * 0.06, bar, clamp(second / 60), d.GOLD, 60)
        date = str(ctx.get("date") or "")
        if date:
            kit.text(date, left + size * 0.03, y + size * 0.13 + bar + size * 0.16, max(13.0, size * 0.13), d.BONE2, face="display", spacing=3)

    # ---------------------------------------------------------------- the shots
    def _field(self, kit, t, u, ctx):
        """No picture: a lattice that drifts, a third of its cells breathing, and a ring that spreads."""
        W, H, r = kit.W, kit.H, 64.0
        line = (*d.CLARET[:3], d.CLARET[3] * 0.30)           # the strength is in the picture: one picture for every cell, and no node around it
        for cx, cy, col, row in hex_cells(0, 0, W, H, r, -5 * t, -3 * t):
            phase = noise(col, row)
            if phase > 0.7:
                b = max(0.0, math.sin(2 * math.pi * (t / 9 + phase)))
                kit.hexagon(cx, cy, r - 3, d.CLARET, alpha=0.26 * b * b, width=0.0, fill=1.0)
            kit.hexagon(cx, cy, r - 3, line)
        p = (t % 7) / 7
        kit.ring(0.26 * W, 0.5 * H, 40 + 0.8 * H * cubic_out(p), d.GOLD, 2.0, 0.4 * (1 - p) ** 1.5)
        up = 200 if H > W else 0                             # an upright frame has no room beside 待機: it moves up, the clock under it
        kit.text("待機", 104, H / 2 + 70 - up, 200, d.BONE, face="display")
        kit.text("STANDBY ・ ALL SYSTEMS HELD", 112, H / 2 + 112 - up, 13, d.RED, spacing=5)
        if H > W:
            self._clock(kit, ctx, 104, H / 2 + 190, 240, "left")
        else:                                                # beside it; smaller where the frame is no wider than 16:9
            self._clock(kit, ctx, W - 110, H / 2 + 60, 240 if W >= 1500 else 180, "right")

    def _put(self, kit, t, name, box, zoom, fx, fy, body, light, half, glow):
        """A picture in its box: the body, the body again where the light passes, the eyes at the strength of their
        breath, and a glow at each eye. Each layer is screened onto what is under it, so black stays ink."""
        picture, eyes_layer, eyes = self.art[name]
        x, y, w, h = box
        b = breathe(t)
        middle = x + passing(t) * w

        def ink():
            kit.rect(x, y, w, h, d.INK)

        def lit():
            with kit.screen_blend(ink):
                kit.cover(picture, x, y, w, h, zoom, fx, fy, body)

        def swept():
            if middle + half * w <= x or middle - half * w >= x + w:        # the light is off the picture: one blend less
                return lit()
            with kit.screen_blend(lit), kit.soft_band(middle, half * w, y, y + h):
                kit.cover(picture, x, y, w, h, zoom, fx, fy, light)
        with kit.clip(x, y, w, h):
            with kit.screen_blend(swept):
                ix, iy, iw, ih = kit.cover(eyes_layer, x, y, w, h, zoom, fx, fy, b)
            for ex, ey in eyes:
                px, py = ix + ex * iw, iy + ey * ih
                if x <= px <= x + w and y <= py <= y + h:
                    kit.radial(px, py, glow, d.GOLD, 0.34 * b)

    def _wide(self, kit):
        """The box of a wide picture: the whole frame, or on a frame that stands upright a band across it."""
        W, H = kit.W, kit.H
        return (0.0, 0.0, W, H) if H <= W else (0.0, 0.38 * (H - 0.5625 * W), W, 0.5625 * W)

    def _profile(self, kit, t, u, ctx):
        W, H = kit.W, kit.H
        eyes = self.art["profile"][2]
        ex, ey = eyes[0] if eyes else (0.6, 0.33)
        box = self._wide(kit)
        self._put(kit, t, "profile", box, 1 + 0.07 * u, ex, ey, 0.62, 0.70, 0.16, 190.0)        # a slow push-in on the eye
        if H > W:
            self._clock(kit, ctx, 96, box[1] + box[3] + 200, 150, "left")
        elif ex > 0.5:                                       # low, on the side away from the eye
            self._clock(kit, ctx, 96, H - 176, 150, "left")
        else:
            self._clock(kit, ctx, W - 96, H - 176, 150, "right")

    def _tilt(self, kit, t, u, ctx):
        W, H = kit.W, kit.H
        if H > W:                                            # the whole figure fits: there is nothing left to pan
            box, clock = (0.06 * W, 64.0, 0.88 * W, 1.32 * W), 64 + 1.32 * W + 250
        else:
            box, clock = (0.50 * W, BAR, 0.46 * W, H - 2 * BAR), H / 2 + 60
        self._put(kit, t, "full", box, 1.0, 0.5, tilt(u), 0.66, 0.60, 0.30, 110.0)             # up the body, from the feet to the head
        self._clock(kit, ctx, 110, clock, 220, "left")

    def _stare(self, kit, t, u, ctx):
        eyes = self.art["front"][2]
        fx, fy = (sum(e[0] for e in eyes) / len(eyes), sum(e[1] for e in eyes) / len(eyes)) if eyes else (0.5, 0.4)
        box = self._wide(kit)
        self._put(kit, t, "front", box, 1.10 - 0.08 * u, fx, fy, 0.62, 0.70, 0.16, 150.0)       # it looks at you; a slow pull-out
        self._clock(kit, ctx, 84, box[1] - 48 if kit.H > kit.W else BAR + 142, 104, "left")
