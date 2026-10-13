"""The shaft: a game's launch, first person up the launch shaft. Two seconds, every move eased.

The lock bolts release, 発進 hangs in the shaft and you pass through it, gates count down as they go by, the wall
lights stretch with the speed. The far end of the shaft is a hole in the picture: the desk shows through it, small
at first, and the run brakes as that opening grows into the whole screen.
Input (optional): ctx["app"].

A frame z bays ahead is drawn at 1 / z of the screen about the vanishing point, which is the origin of shaft space.
"""
import math

from ... import draw as d
from .. import Piece
from ..timeline import clamp, noise, quint_out, seg, smooth

BAYS = 60                              # the exit is sixty bays up
SIGN = 3.2                             # where 発進 hangs
BANDS = (0.35, 1, 2, 4, 8, 16, 40)     # the wall lights are drawn in these depth bands, one node each


def travel(u):
    """Bays covered at progress u of the run: slow off the locks, hard in the middle, braking into the exit."""
    u = clamp(u)
    a, b = u ** 3, (1 - u) ** 1.7
    return (BAYS - 1) * a / (a + b)


def exit_half(t, W, H):
    """Half the size of the exit on screen at t seconds."""
    zx = BAYS - travel(t / 2)
    return W / 2 / zx, H / 2 / zx


def gate_number(k):
    """Every tenth bay is a gate; they count down to the exit. None where there is no gate."""
    return (BAYS - k) // 10 if k % 10 == 0 and 0 < k < BAYS else None


def sign(kit):
    """発進 over a rule and LAUNCH, about the origin, at the size it has one bay ahead. It is only ever seen
    growing, so its type is stamps; they are fine enough for where it starts to fade, 0.75 bays ahead."""
    kit.stamp("発進", 0, 150, 430, d.BONE, face="display", align="center", most=1 / 0.75)
    kit.rect(-430, 196, 860, 8, d.GOLD)
    kit.stamp("LAUNCH", 0, 262, 44, d.GOLD, spacing=46, align="center", most=1 / 0.75)


def gate_label(kit, gate, H, alpha=1.0):
    """A gate's number on its top edge, in the gate's own frame. Seen from 46 bays down to half a bay: a stamp."""
    kit.stamp(f"GATE 0{gate}", 0, -H / 2 + 45, 30, d.LED, face="display", spacing=3.6, align="center", alpha=alpha, most=2)


class Shaft(Piece):
    name, length, covers, still = "shaft", 2.0, True, 1.0

    def prepare(self, kit, ctx):
        sign(kit)                                           # the stamps, so that no frame waits for one
        for gate in range(1, BAYS // 10):
            gate_label(kit, gate, kit.H)

    def paint(self, kit, t, ctx):
        W, H = kit.W, kit.H
        u = t / self.length
        dist = travel(u)
        zx = BAYS - dist                                    # the exit is this many bays ahead
        hw, hh = W / 2 / zx, H / 2 / zx
        vn = clamp((travel(min(1, u + 0.004)) - travel(max(0, u - 0.004))) / 0.008 / (BAYS - 1) / 2.5)      # speed, 0..1
        damp = (1 - u) ** 1.6                               # the roll and the rumble die away: the exit arrives level
        roll = (0.028 * math.sin(5.2 * t) + 0.012 * math.sin(11 * t)) * damp
        jx, jy = 2.6 * vn * math.sin(190 * t) * damp, 2.6 * vn * math.cos(163 * t) * damp
        with kit.transform(dx=W / 2 + jx, dy=H / 2 + jy, rotate=roll):
            with kit.clip_out(-hw, -hh, 2 * hw, 2 * hh):    # the exit is a hole: the desk shows through it
                self._walls(kit, t, W, H, dist, zx, hw, hh, vn)
            kit.stroke_rect(-hw, -hh, 2 * hw, 2 * hh, d.BONE, clamp(9 / zx, 1.5, 8), 0.9)       # the rim of the exit
        self._instruments(kit, t, ctx, W, H, zx, vn)

    def _walls(self, kit, t, W, H, dist, zx, hw, hh, vn):
        kit.rect(-2 * W, -2 * H, 4 * W, 4 * H, d.INK)
        kit.radial(0, 0, max(110, 5 * hw), d.BONE, 0.30 * clamp((zx - 1.2) / 6))       # light from the exit; it dims on arrival
        kit.lines([(sx * 1.5 * W, sy * 1.5 * H, sx * hw, sy * hh) for sx in (-1, 1) for sy in (-1, 1)], d.CLARET, 1.5, 0.55)
        ink4 = d.col("ink4")
        for k in range(min(BAYS, math.floor(dist + 46)), max(1, math.ceil(dist + 0.3)) - 1, -1):        # bays, far to near
            z = k - dist
            fog = clamp(1 - z / 46) ** 1.4
            w2, h2 = W / 2 / z, H / 2 / z
            if k % 2 == 0 and k < BAYS:                     # every other bay is a shade lighter
                z1 = z + 1
                kit.band((-w2, -h2, 2 * w2, 2 * h2), (-W / 2 / z1, -H / 2 / z1, W / z1, H / z1), ink4, 0.6 * fog)
            gate = gate_number(k)
            if gate is None:
                kit.stroke_rect(-w2, -h2, 2 * w2, 2 * h2, d.CLARET, clamp(4.5 / z, 1.2, 20), 0.85 * fog)
                continue
            kit.stroke_rect(-w2, -h2, 2 * w2, 2 * h2, d.LED, clamp(10 / z, 1.2, 44), 0.95 * fog)
            if z > 0.5:                                     # the gate's number rides its top edge
                with kit.transform(scale=1 / z):
                    gate_label(kit, gate, H, fog)
        self._lights(kit, W, H, dist, vn)
        zs = SIGN - dist                                    # the sign: you go through it
        if zs > 0.3:
            with kit.opacity(clamp(t / 0.14) * clamp((zs - 0.3) / 0.45)):
                with kit.transform(scale=1 / zs):
                    sign(kit)

    def _lights(self, kit, W, H, dist, vn):
        """44 wall lights, each repeating every 9 bays; they stretch with the speed."""
        length, bands = 0.18 + 2.6 * vn, {}
        for i in range(44):
            side, a, base = i % 4, 1.7 * noise(i, 31) - 0.85, 9 * noise(i, 32)
            px, py = (a * W / 2, H / 2 * (-1 if side == 0 else 1)) if side < 2 else (W / 2 * (-1 if side == 2 else 1), a * H / 2)
            gold = noise(i, 33) > 0.72
            n = math.floor((dist - base) / 9)
            while True:
                z0 = base + 9 * n - dist
                if z0 > 40 or base + 9 * n > BAYS - 0.5:
                    break
                n += 1
                if z0 + length < 0.35:
                    continue
                za, zb = max(0.35, z0), z0 + length
                band = next((j for j in range(len(BANDS) - 1) if za < BANDS[j + 1]), len(BANDS) - 2)
                bands.setdefault((gold, band), []).append((px / za, py / za, px / zb, py / zb))
        for (gold, band), segments in sorted(bands.items()):
            mid = math.sqrt(BANDS[band] * BANDS[band + 1])  # the band's middle sets its width and its fog
            kit.lines(segments, d.GOLD if gold else d.BONE, clamp(2.4 / mid, 0.8, 9), 0.8 * clamp(1 - mid / 40) ** 1.2)

    def _instruments(self, kit, t, ctx, W, H, zx, vn):
        """Fixed to the screen; they slide off to the sides as the exit arrives."""
        out = smooth(seg(t, 1.46, 1.80))
        if out >= 1:
            return
        name = str(ctx.get("app") or "APP")
        with kit.opacity(1 - out):
            with kit.transform(dx=-480 * out):
                kit.text("発進シーケンス ・ LAUNCH", 64, 92, 14, d.GOLD, face="display", spacing=2)
                for i in range(5):                          # each lock fills green, left to right
                    kit.rect(64 + 44 * i, 106, 36, 9, d.LED)
                    kit.rect(64 + 44 * i, 106, 36 * smooth(seg(t, 0.05 + 0.06 * i, 0.19 + 0.06 * i)), 9, d.GOLD)
                released = t >= 0.44
                kit.text("LOCK BOLTS RELEASED" if released else "LOCK BOLTS 01-05", 292, 115, 10.5, d.GOLD if released else d.LED, spacing=2)
                kit.text("TARGET", 66, H - 170, 11, d.RED, spacing=5)
                size, room = 92, W / 2 - 96
                nw = kit.measure(name, size, face="display")
                if nw > room:                               # a long name is set smaller
                    size = max(20, int(size * room / nw))
                    nw = kit.measure(name, size, face="display")
                rev = quint_out(seg(t, 0.10, 0.52))
                with kit.clip(56, H - 162, (nw + 16) * rev, 112):
                    kit.text(name, 62, H - 78, size, d.BONE, face="display")
                kit.rect(64, H - 62, nw * rev, 3, d.GOLD)
            with kit.transform(dx=480 * out):
                kit.text("ALTITUDE", W - 64, 92, 11, d.RED, spacing=5, align="right")
                kit.text(f"-{round(20 * (zx - 1)):04d} M", W - 64, 146, 54, d.BONE, spacing=2, align="right")
                kit.text("VELOCITY", W - 64, H - 104, 11, d.RED, spacing=5, align="right")
                kit.segbar(W - 324, H - 90, 260, 10, vn, d.GOLD, 26)
