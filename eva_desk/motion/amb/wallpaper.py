"""The living wallpaper: the picture behind the windows, moving.

Three things, each with its own switch. The drift: the picture pushes in and back once a lap, with a slow pan on
other periods, so it never repeats exactly and never jumps. Ripples: every few seconds a ring of hexagons spreads
from a point and fades. Embers: small specks rising slowly.

The piece is handed its pictures; it loads nothing. Whoever hosts it decodes them and says how far a new one has
faded in over the old one, or over the colour that was there before it. A plain colour is a plain fill: nothing
moves on it.
"""
import math

from ... import draw as d
from .. import Piece
from ..kit import cover_box, hex_cells
from ..timeline import clamp, noise

PUSH = 1.035         # the zoom at rest: room for the pan on every side
PAN = 0.015          # how far the picture slides each way, of the frame's side
EVERY = 5.5          # seconds between two ripples
LIFE = 4.2           # how long one lasts
SPEED = 250.0        # px a second its ring spreads at
CELL = 58.0          # the lattice of the ripples
BAND = 95.0          # how far from the ring a cell still lights
EMBERS = 70


def _num(value, default):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def camera(t, drift, lap):
    """(zoom, pan across, pan down) at t: the pans as shares of the frame's sides. No drift, or no lap, is a
    still picture."""
    if not (0 < drift < math.inf and 0 < lap < math.inf):        # also what is not a number: it compares as neither
        return 1.0, 0.0, 0.0
    turn = 2 * math.pi * t / lap
    return PUSH + drift * (0.5 - 0.5 * math.cos(turn)), PAN * math.sin(turn / 1.3), PAN * math.sin(turn / 1.1 + 1)


def place(tw, th, W, H, t, drift, lap):
    """(x, y, w, h): where a tw x th picture lies over a W x H frame at t. It always covers the frame."""
    zoom, across, down = camera(t, drift, lap)
    x, y, w, h = cover_box(tw, th, 0, 0, W, H, zoom)
    return x + across * W, y + down * H, w, h


def rings(t):
    """The ripples alive at t, as (which, its age in seconds)."""
    last = int(t // EVERY)
    return [(k, t - k * EVERY) for k in (last - 1, last) if k >= 0 and t - k * EVERY <= LIFE]


def ring_centre(k, W, H):
    """Where ripple k starts: somewhere on the picture, away from its edges."""
    return (0.12 + 0.76 * noise(k, 21)) * W, (0.15 + 0.7 * noise(k, 22)) * H


def embers(t, W, H, pan, berserk=False):
    """The specks at t, as (x, y, size, strength, "bone" | "gold" | "led"). They rise at 9 to 25 px a second, sway
    a little, and come round again at the bottom."""
    out, span = [], H * 1.15
    for i in range(EMBERS):
        y = H + 20 - (t * (9 + 16 * noise(i, 4)) + noise(i, 5) * span) % span
        x = noise(i, 3) * W + 16 * math.sin(t * 0.4 + i) + pan * (1 + noise(i, 8))
        strength = (0.2 + 0.45 * (0.5 + 0.5 * math.sin(t * 0.7 + i * 1.7))) * min(1.0, (H + 20 - y) / 120)
        out.append((x, y, 1 + 1.8 * noise(i, 6), strength, "led" if berserk else "gold" if noise(i, 7) > 0.82 else "bone"))
    return out


class WallpaperLoop(Piece):
    name = "wallpaper"
    length = None
    lap = 30.0       # what the offline renderer shows of it
    covers = False
    still = 7.0

    def paint(self, kit, t, ctx):
        W, H = kit.W, kit.H
        colour = ctx.get("colour")
        if isinstance(colour, (tuple, list)) and len(colour) == 4:
            kit.rect(0, 0, W, H, tuple(colour))
            return
        picture, previous, fade = ctx.get("picture"), ctx.get("previous"), clamp(_num(ctx.get("fade"), 1.0))
        if picture is None:
            picture, previous, fade = previous, None, 1.0
        if picture is None:
            return
        drift, lap = _num(ctx.get("drift"), 0.08), _num(ctx.get("lap"), 30.0)
        ground = ctx.get("ground")
        if fade < 1 and isinstance(ground, (tuple, list)) and len(ground) == 4:        # the colour it follows, while it fades in over it
            kit.rect(0, 0, W, H, tuple(ground))
        if previous is not None and fade < 1:
            kit.sprite(previous, *place(previous.get_width(), previous.get_height(), W, H, t, drift, lap))
        kit.sprite(picture, *place(picture.get_width(), picture.get_height(), W, H, t, drift, lap), fade)
        berserk = bool(ctx.get("berserk"))
        if ctx.get("ripples", True):
            self._ripples(kit, t, d.LED if berserk else d.RED)
        if ctx.get("embers", True):
            colours = {"bone": d.BONE, "gold": d.GOLD, "led": d.LED}
            for x, y, size, strength, kind in embers(t, W, H, camera(t, drift, lap)[1] * W, berserk):
                kit.rect(x, y, size, size, colours[kind], strength)

    def _ripples(self, kit, t, tone):
        alive = [(*ring_centre(k, kit.W, kit.H), age * SPEED, 1 - age / LIFE) for k, age in rings(t)]
        if not alive:
            return
        for cx, cy, _, _ in hex_cells(0, 0, kit.W, kit.H, CELL, -6 * t, -3.4 * t):
            for rx, ry, radius, fade in alive:
                strength = (1 - abs(math.hypot(cx - rx, cy - ry) - radius) / BAND) * fade
                if strength > 0.02:
                    kit.hexagon(cx, cy, CELL - 3, tone, alpha=0.62 * strength, width=2.0, fill=0.21)
