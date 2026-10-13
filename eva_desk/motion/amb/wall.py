"""The status wall: what a monitor that is not a main one shows while it holds no window.

Screens in the language of the MFD panels (a bezel, scanlines, segment bars, lamps): the time, the three readings
with a minute of history each, two slow waves that follow the load, the workspaces, the playing track. Everything
moves slowly and continuously; nothing blinks.

It is laid out in units of its own, a column 540 wide, as it was designed for a monitor standing upright; on a
wider one the screens flow into as many columns as make them largest. It is drawn under one scale that never
changes, so its type is set once.

Most of it is still from one frame to the next: the screens and what is written on them change when a reading
does, about once a second. That part is kept as one node (kit.keep) and only the strips, the curves and the waves
are built for every frame.
"""
import math
from collections import deque

from ... import draw as d
from .. import Piece
from ..kit import screen_box
from ..timeline import clamp

COLUMN = 540.0       # a column, in the wall's own units
EDGE = 16.0          # the margin inside a column
HEAD = 54.0          # the strip and the title line over the screens
FOOT = 28.0          # the strip under them
HEIGHTS = {"time": 208.0, "magi": 258.0, "harmonics": 162.0, "workspaces": 116.0, "audio": 134.0}        # each screen and the gap under it
COLUMNS = ([["time", "magi", "harmonics", "workspaces", "audio"]],
           [["time", "magi"], ["harmonics", "workspaces", "audio"]],
           [["time", "workspaces"], ["magi"], ["harmonics", "audio"]])
MAGI = (("MAGI-1", "MELCHIOR", "CPU"), ("MAGI-2", "BALTHASAR", "RAM"), ("MAGI-3", "CASPER", "NET"))


def _number(value, default=0.0):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


class History:
    """A minute of readings, one a second, read back at any moment. Between two samples the value lies on the line
    between them, so a curve drawn from it slides instead of stepping; before the oldest and after the newest it
    holds still."""

    SPAN = 60

    def __init__(self):
        self.samples = deque(maxlen=self.SPAN + 4)       # (when, value), oldest first

    def push(self, now, value):
        self.samples.append((float(now), _number(value)))

    def at(self, when):
        if not self.samples:
            return 0.0
        before = self.samples[0]
        if when <= before[0]:
            return before[1]
        for sample in self.samples:
            if sample[0] >= when:
                span = sample[0] - before[0]
                return sample[1] if span <= 0 else before[1] + (sample[1] - before[1]) * (when - before[0]) / span
            before = sample
        return before[1]

    def series(self, now, n=SPAN):
        """The reading at now, a second before, two before, and so on: n + 1 values, newest first. One walk back
        through the samples, since this is asked at every repaint."""
        samples, out = list(self.samples), []
        if not samples:
            return [0.0] * (n + 1)
        j = last = len(samples) - 1
        for i in range(n + 1):
            when = now - i
            while j > 0 and samples[j][0] > when:
                j -= 1
            before = samples[j]
            if before[0] >= when or j == last:
                out.append(before[1])
            else:
                after = samples[j + 1]
                span = after[0] - before[0]
                out.append(before[1] if span <= 0 else before[1] + (after[1] - before[1]) * (when - before[0]) / span)
        return out


def layout(W, H):
    """(scale, columns) for a W x H frame: as many columns as make the screens largest, each a list of
    (screen, height in units)."""
    best = None
    for names in COLUMNS:
        tall = max(sum(HEIGHTS[name] for name in column) for column in names) + HEAD + FOOT
        scale = min(W / (len(names) * COLUMN), H / tall)
        if best is None or scale > best[0] + 1e-9:
            best = (scale, [[(name, HEIGHTS[name]) for name in column] for column in names])
    return best


class WallLoop(Piece):
    name = "wall"
    length = None
    lap = 20.0       # what the offline renderer shows of it
    covers = False
    still = 3.0

    def paint(self, kit, t, ctx):
        kit.rect(0, 0, kit.W, kit.H, d.INK, 0.62)            # the monitor's wallpaper shows through, dimmed
        scale, columns = layout(kit.W, kit.H)
        wide = len(columns) * COLUMN
        tall = max(sum(h for _, h in column) for column in columns) + HEAD + FOOT
        hot = bool(ctx.get("berserk"))
        strip = d.LED if hot else d.CLARET
        readings = self._readings(ctx)
        where = {}                                           # each screen's corner, as its column places it
        for i, column in enumerate(columns):
            y = HEAD
            for name, height in column:
                where[name] = (i * COLUMN + EDGE, y)
                y += height
        with kit.transform((kit.W - wide * scale) / 2, (kit.H - tall * scale) / 2, scale=scale):
            for slot, y, shift in (("top", 16.0, 6 * t), ("bottom", tall - FOOT, -6 * t)):
                with kit.clip(EDGE, y, wide - 2 * EDGE, 8), kit.transform(shift % 20.0):         # one long strip, slid along under a clip
                    kit.keep("strip-" + slot, (wide, y, strip),
                             lambda y=y: kit.hazard(EDGE - 20, y, wide - 2 * EDGE + 20, 8, strip, d.INK, 20.0))
            kit.keep("screens", self._shown(ctx, where, wide, hot, readings),
                     lambda: self._still(kit, ctx, where, wide, hot, readings))
            self._moving(kit, t, where, hot, readings)

    # ---------------------------------------------------------------- what it is given
    def _readings(self, ctx):
        """The three readings as (value from 0 to 1, its label, its history): whatever is missing reads nothing."""
        given = ctx.get("magi")
        given = list(given)[:3] if isinstance(given, (list, tuple)) else []
        out = []
        for i in range(3):
            entry = given[i] if i < len(given) and isinstance(given[i], dict) else {}
            series = entry.get("series")
            series = [v if isinstance(v, (int, float)) and not isinstance(v, bool) else 0.0 for v in series] if isinstance(series, (list, tuple)) else []
            out.append((clamp(_number(entry.get("value"))), str(entry.get("label") or "--"), series))
        return out

    def _tags(self, ctx):
        """The workspaces as (number, state), ten at most."""
        tags = []
        for entry in ctx.get("workspaces") or []:
            if isinstance(entry, (list, tuple)) and len(entry) == 2 and isinstance(entry[0], int):
                tags.append((entry[0], str(entry[1])))
        return tags[:10]

    def _music(self, ctx):
        music = ctx.get("music") if isinstance(ctx.get("music"), dict) else {}
        return tuple(str(music.get(key) or "") for key in ("status", "title", "artist"))

    def _shown(self, ctx, where, wide, hot, readings):
        """Everything the still part shows: while this is the same, that part is the same."""
        return (hot, wide, tuple(sorted(where.items())), str(ctx.get("clock")), str(ctx.get("date")), str(ctx.get("uptime")),
                round(clamp(_number(ctx.get("second")) / 60) * 60), str(ctx.get("net")),
                tuple((round(value * 16), value > 0.9, label) for value, label, _ in readings),
                tuple(self._tags(ctx)), self._music(ctx))

    # ---------------------------------------------------------------- what is still
    def _still(self, kit, ctx, where, wide, hot, readings):
        kit.text("EVA-DESK ・ STATUS WALL", EDGE, 44, 10, d.BONE2, spacing=3)
        kit.text("暴走 ・ BERSERK" if hot else "正常 ・ NOMINAL", wide - EDGE, 44, 11, d.LED if hot else d.GOLD,
                 face="display", spacing=2, align="right")
        for name, (x, y) in where.items():
            getattr(self, "_" + name)(kit, ctx, x, y, COLUMN - 2 * EDGE, hot, readings)

    def _time(self, kit, ctx, x, y, w, hot, readings):
        bx, by, bw, bh = kit.screen(x, y, w, 196, "TIME", "LOCAL")
        kit.text(str(ctx.get("clock") or "00:00"), bx - 4, by + 116, 128, d.BONE, face="display")
        kit.text(str(ctx.get("date") or ""), bx + bw, by - 8, 11, d.BONE2, spacing=2, align="right")
        if ctx.get("uptime"):
            kit.text(f"UPTIME {ctx['uptime']}", bx + bw, by + 136, 10, d.BONE3, spacing=2, align="right")
        kit.segbar(bx, by + bh - 10, bw, 7, clamp(_number(ctx.get("second")) / 60), d.GOLD, 60)

    def _magi(self, kit, ctx, x, y, w, hot, readings):
        net = str(ctx.get("net") or "net").upper()
        for i, ((tag, name, what), (value, label, _)) in enumerate(zip(MAGI, readings)):
            over = (hot and i == 0) or value > 0.9           # a reading over nine tenths is orange, steadily
            colour = d.LED if over else d.GOLD
            bx, by, bw, bh = kit.screen(x + i * 172, y, 164, 246, tag, net if i == 2 else what)
            kit.text(name, bx, by + 16, 13, d.BONE2, face="display", spacing=1)
            size = 42 if kit.measure(label, 42, face="display") <= bw + 2 else 30         # a long reading is set smaller, not cut
            kit.text(label, bx - 2, by + 70, size, d.LED if over else d.BONE, face="display", width=bw + 2)
            kit.segbar(bx, by + 86, bw, 8, value, colour, 16)
            kit.lamp(bx + bw - 9, by - 17, 9, colour)

    def _harmonics(self, kit, ctx, x, y, w, hot, readings):
        bx, by, bw, bh = kit.screen(x, y, w, 150, "HARMONICS", "SYNC")
        grid = d.col("ink5")
        kit.rect(bx, by + bh / 2 + 2, bw, 1, grid)
        for k in range(int(bw // 43) + 1):
            kit.rect(bx + k * 43, by, 1, bh, grid)

    def _workspaces(self, kit, ctx, x, y, w, hot, readings):
        tags = self._tags(ctx)
        active = next((n for n, state in tags if state == "active"), None)
        bx, by, bw, bh = kit.screen(x, y, w, 104, "WORKSPACES", f"{active:02d} ACTIVE" if active is not None else "")
        cell = (bw - 54) / 10
        for i, (n, state) in enumerate(tags):
            left = bx + i * (cell + 6)
            kit.rect(left, by + 8, cell, 44, d.BONE if state == "active" else d.CLARET if state == "occupied" else d.col("ink4"))
            kit.text(f"{n:02d}", left + cell / 2, by + 38, 17, d.INK if state == "active" else d.BONE if state == "occupied" else d.col("ink5"),
                     face="display", align="center")

    def _audio(self, kit, ctx, x, y, w, hot, readings):
        status, title, artist = self._music(ctx)
        bx, by, bw, bh = kit.screen(x, y, w, 122, "AUDIO", status.upper() if title else "")
        if title:
            kit.text(title, bx, by + 30, 24, d.BONE, face="display", width=bw)
            kit.text(artist.upper(), bx, by + 52, 11, d.BONE2, spacing=3, width=bw)
        else:
            kit.text("NO SIGNAL", bx, by + 44, 26, d.LED, face="display")

    # ---------------------------------------------------------------- what moves
    def _moving(self, kit, t, where, hot, readings):
        """The curves of the three readings, kept until a reading moves them on, and the two waves, which never rest."""
        x, y = where["magi"]
        for i, (value, _, series) in enumerate(readings):
            colour = d.LED if (hot and i == 0) or value > 0.9 else d.GOLD
            bx, by, bw, _ = screen_box(x + i * 172, y, 164, 246)
            kit.keep(f"curve-{i}", (bx, by, colour, tuple(series)),
                     lambda bx=bx, by=by, bw=bw, series=series, colour=colour: kit.spark(bx, by + 108, bw, 86, series, colour))
        x, y = where["harmonics"]
        bx, by, bw, bh = screen_box(x, y, COLUMN - 2 * EDGE, 150)
        middle = by + bh / 2 + 2
        cpu, mem = readings[0][0], readings[1][0]
        for colour, swing, wave, speed, phase in ((d.RED, 14 + 26 * mem, 0.035, 0.8, 1.0), (d.LED if hot else d.GOLD, 10 + 34 * cpu, 0.022, 1.2, 0.0)):
            points = [(bx + px, middle + swing * math.sin(wave * px - speed * t + phase) * math.sin(math.pi * px / bw))
                      for px in (min(bw, 8.0 * k) for k in range(int(bw // 8) + 2))]
            kit.lines([(x0, y0, x1, y1) for (x0, y0), (x1, y1) in zip(points, points[1:])], colour, 2.0)
