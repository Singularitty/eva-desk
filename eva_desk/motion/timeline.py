"""Time for the motion pieces: progress inside an interval, easing, hard steps, repeatable noise. No GTK."""
import math


def clamp(v, a=0.0, b=1.0):
    return max(a, min(b, v))


def lerp(a, b, u):
    return a + (b - a) * u


def seg(t, a, b):
    """How far `t` is through [a, b], from 0 to 1."""
    return clamp((t - a) / (b - a))


# ---------------------------------------------------------------- easing: u in, u out, both 0..1
def cubic_out(u):
    return 1 - (1 - u) ** 3


def cubic_in(u):
    return u ** 3


def smooth(u):
    return u * u * (3 - 2 * u)


def back_out(u, s=1.5):
    """Lands with a small overshoot."""
    v = u - 1
    return v * v * ((s + 1) * v + s) + 1


def quint_out(u):
    return 1 - (1 - u) ** 5


def expo_in(u):
    return 0.0 if u <= 0 else 2 ** (10 * (u - 1))


# ---------------------------------------------------------------- the drawn look: steps instead of slopes
def stepped(u, n):
    """`u` in `n` hard steps: 0 until it starts, then 1/n, 2/n ... 1."""
    return 0 if u <= 0 else min(1, math.ceil(u * n - 1e-6) / n)


def twos(t):
    """Time held on twos (12 a second), for the few effects that should look drawn."""
    return math.floor(t * 12 + 1e-6) / 12


def crt(u):
    """The panel snap: a line for the first 40 %, then full height in four steps."""
    if u <= 0:
        return 0
    if u < 0.4:
        return 0.02
    return min(1, 0.02 + 0.98 * stepped((u - 0.4) / 0.6, 4))


def noise(i, seed=0):
    """A value in [0, 1) that is the same on every run: jitter without `random`."""
    x = math.sin(i * 127.1 + seed * 311.7) * 43758.5453
    return x - math.floor(x)
