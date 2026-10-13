# Motion graphics, plan 1: the engine and the launch sequences

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A motion engine inside the daemon (timeline, drawing kit, player, offline renderer) and the two launch sequences built on it: the card for apps and the shaft for games, played on Enter in the launcher.

**Architecture:** A piece paints one frame at a time into a `Gtk.Snapshot` through a small kit. The player hosts a piece on a layer surface and paints it on the frame clock; the renderer builds the same snapshot with no display and draws it through cairo to PNG and mp4. A sequence is a function of time and its inputs only, so the tests assert on rendered frames.

**Tech Stack:** Python 3.11, PyGObject (GTK 4.10 or newer for mask nodes, Gsk, Pango), pycairo, gtk4-layer-shell; `unittest` (`python3 -m unittest discover -s tests`); `ffmpeg` optional, for mp4 previews.

**Spec:** `docs/superpowers/specs/2026-10-13-motion-graphics-design.md`. This plan covers build step 1: "Architecture", "Launch" (the card and the shaft), and the parts of "Configuration", "Error handling" and "Testing" that concern them. Boot, wake, berserk, the track card and the ambient pieces follow in plans 2 to 5.

## Global Constraints

- A linked install runs the daemon straight from the main checkout, so the main checkout is live. Work only in a worktree under `.worktrees/`. Never edit the main checkout, never run `eva-ctl reload` or `eva-ctl apply`, never open a window on the live session, never kill a process by pattern.
- No commits, merges or pushes: the owner does those. A task is done when its tests pass; say which files it touched.
- Verification is offline: `python3 -m unittest discover -s tests`, `eva-desk --render DIR`, `eva-desk --render-motion DIR`. Read the PNGs; a render that runs is not a render that looks right.
- Colours are theme roles through `draw.py` (`d.INK`, `d.BONE`, `d.GOLD`, `d.LED`, `d.CLARET`, `d.RED`, `d.col("ink4")`), never hex in modules. Fonts are `d.F_DISPLAY` at `d.DISPLAY_WEIGHT` and `d.F_META`.
- A piece never calls `random` and never reads the clock or the system: time arrives as `t`, everything else in `ctx`. Frame N is the same bytes on every run.
- No full-screen flash: no frame fills the screen with `bone`, `gold` or `led`.
- Both sequences are drawn in code. No picture assets in this plan, and the Eva is not drawn.
- All sizes are design px. The kit scales by `s = min(h / 720, w / 1280)`; a piece lays out from `kit.W` by `kit.H`.
- No new dependencies. Without `ffmpeg` the renderer writes the contact sheets only.
- No path nodes (`Gsk.PathBuilder`, `append_fill`, `append_stroke`, `push_fill`): GTK rasterises a path on the CPU every time it changes, and cairo asserts on some nested path clips offline. Moving geometry is rectangles, borders, turned or sheared rectangles and glyphs; holes are masks.
- No glyphs under a scale that changes from frame to frame: GTK keeps a glyph by its exact size on screen, so such type is rasterised again every frame. Type that grows or shrinks is a `kit.stamp` (set once as a picture, scaled by the GPU); type that only moves is `kit.text`.
- The repo is public: plain voice in README and comments, nothing about private setups.
- Follow the code around you: a module docstring, long lines, short `# why` comments, `unittest`.

## Review Focus

1. An app name that is very long, empty, or in a script the display face lacks (`LibreOffice Calc Spreadsheet Editor`, `""`, `火狐 🦊`): the name is set smaller until it fits and nothing raises (Task 3 `test_a_long_name_is_set_smaller`, `test_odd_names_and_missing_inputs`; Task 4 `test_odd_names_and_shapes`).
2. The launcher opened on a portrait or a small monitor: the pieces lay out from the frame and still cover it (Task 2 `test_design_frame`; Task 3 `test_other_monitor_shapes`; Task 4 `test_odd_names_and_shapes`).
3. Two launches in quick succession: the second sequence replaces the first, each done callback fires once, nothing stays on screen (Task 6 `test_a_new_piece_replaces_the_running_one`).
4. No monitor to play on (the focused monitor went away): nothing is shown, and no invisible surface takes clicks (Task 6 `test_no_monitor_no_show`).
5. A piece that raises in the middle of a sequence: the overlay goes away at once, and a stale safety timer never ends a later run (Task 6 `test_a_piece_that_raises_ends_the_sequence`, `test_the_safety_timeout_only_ends_its_own_run`).

## Changed during execution

The tasks below are the plan as it was written, with the kit's interface brought up to date. What the build and
the final review changed, so that the code and `tests/test_motion.py` are read with the right expectations:

- **The kit has no path nodes** (found in Task 4). `poly` and `clip_polys` went; `band`, `para` and
  `clip_out_para` came. Holes are inverted-alpha masks, so `available()` asks for GTK 4.10, not 4.14.
- **Frame comparisons** go through `same(a, b)`, and the tests also assert that nothing is GTK's
  cannot-draw pink.
- **From the final review** (one fix pass, each fix with a test seen failing first):
  - `kit.stamp(...)`: `text()` as a picture, for type that changes size (the shaft's sign and gate numbers,
    the card's kanji while they fold). `Kit(snap, w, h, density=1.0, stamps=None)` takes the monitor's px per
    unit and the store the pictures are kept in; the player gives each run its own store and drops it at the end.
    `Piece.prepare` makes the stamps early.
  - `kit.letters(...)`: a name is cut where a caret can stand, and not at all when its script joins letters or
    runs right to left; the card then raises the name in one piece.
  - The card's seam edge is the hazard pattern again, each stripe a parallelogram (Task 3 had it as dashes
    after the kit rework). The kanji's travel is `H / 2 + 200` (560 on a 720 frame), so they also enter from
    outside a portrait frame.
  - `LAUNCH` under the shaft's sign is centred (x = 0): Pango puts no letter spacing after the last letter.
    `shaft.sign(kit)` and `shaft.gate_label(...)` are module functions.
  - The player: a piece that raises ends from the main loop, not from inside the snapshot; one that cannot
    prepare is not shown; `play()` forgets the last monitor's size before placing; the kit made for `prepare`
    is closed and is the frame `_paint` gets (points, with the monitor's scale as density).
  - The app: no spawn pulse and no eye-catch while a sequence that covers the screen plays (`App._covered`).
  - `render.build(...)` is public (the node tree of a frame); `_rgba` stores the alpha it rounds to.

## File structure

| File | Responsibility |
|---|---|
| `eva_desk/motion/__init__.py` | `Piece`, the registry `pieces()`, `available()` |
| `eva_desk/motion/timeline.py` | progress, easing, steps, repeatable noise; no GTK |
| `eva_desk/motion/kit.py` | `design()`, `Kit`: shapes, type, clips and transforms over a snapshot |
| `eva_desk/motion/render.py` | one frame, a contact sheet, an mp4, `render_motion()` |
| `eva_desk/motion/seq/__init__.py` | empty |
| `eva_desk/motion/seq/card.py` | `Card` and its geometry helpers |
| `eva_desk/motion/seq/shaft.py` | `Shaft` and its geometry helpers |
| `eva_desk/motion/player.py` | `SequencePlayer`, the overlay that plays one piece |
| `tests/test_motion.py` | every test of this plan |
| Modified | `draw.py` (`plain_layout`), `config.py`, `launcher.py`, `app.py`, `__main__.py`, `preview.py`, `hypr/eva.lua`, `bin/eva-ctl`, `config/eva.example.toml`, `packaging/PKGBUILD`, `packaging/.SRCINFO`, `README.md`, the 2026-10-06 spec |

The approved animated mock-ups of both sequences are the reference for anything a table below leaves open. They are local and git-ignored: `.superpowers/brainstorm/46040-1791895389/content/mg-r3.js` (the two sequences) and `mg-kit.js` (the helpers they call), in the main checkout. If they are gone, the tables below are complete.

Every test goes in `tests/test_motion.py`. Its head, written in Task 1:

```python
"""Motion: timeline, kit, renderer, player and the launch sequences. No compositor, no windows."""
import contextlib
import io
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ.pop("WAYLAND_DISPLAY", None)

from eva_desk import config  # noqa: E402

config.load("/nonexistent")                     # the default theme, whatever this machine's eva.toml says
CTX = {"app": "FIREFOX", "workspace": 2, "clock": "22:44"}
BONE, GOLD = (0xf7, 0xe6, 0xeb), (0x3f, 0xff, 0x7d)     # as cairo stores them: blue, green, red


def px(surf, x, y):
    """(blue, green, red, alpha) of one pixel of an ARGB32 surface."""
    i = int(y) * surf.get_stride() + int(x) * 4
    return tuple(surf.get_data()[i:i + 4])


def alpha(surf, x, y):
    return px(surf, x, y)[3]


def grid(surf, cols=12, rows=6):
    """The alpha at the middle of every cell of a cols x rows grid."""
    w, h = surf.get_width(), surf.get_height()
    return [alpha(surf, (c + 0.5) * w / cols, (r + 0.5) * h / rows) for r in range(rows) for c in range(cols)]
```

---

### Task 1: The timeline

**Files:**
- Create: `eva_desk/motion/__init__.py` (a docstring only, for now), `eva_desk/motion/timeline.py`
- Test: `tests/test_motion.py`

**Interfaces:**
- Produces, all in `eva_desk.motion.timeline`, all pure:
  `clamp(v, a=0.0, b=1.0)`, `lerp(a, b, u)`, `seg(t, a, b)` (progress of `t` inside `[a, b]`, clamped),
  `cubic_out(u)`, `cubic_in(u)`, `smooth(u)`, `back_out(u, s=1.5)`, `quint_out(u)`, `expo_in(u)`,
  `stepped(u, n)`, `twos(t)`, `crt(u)`, `noise(i, seed=0)`.

- [ ] **Step 1: Write the failing tests**

```python
class Timeline(unittest.TestCase):
    def setUp(self):
        from eva_desk.motion import timeline
        self.T = timeline

    def test_seg(self):
        T = self.T
        self.assertEqual(T.seg(0.5, 1, 2), 0.0)
        self.assertEqual(T.seg(3, 1, 2), 1.0)
        self.assertAlmostEqual(T.seg(1.5, 1, 2), 0.5)

    def test_easings_run_from_0_to_1_without_falling(self):
        T = self.T
        for f in (T.cubic_out, T.cubic_in, T.smooth, T.quint_out, T.expo_in):
            self.assertAlmostEqual(f(0.0), 0.0, places=6)
            self.assertAlmostEqual(f(1.0), 1.0, places=6)
            ys = [f(i / 100) for i in range(101)]
            self.assertEqual(ys, sorted(ys), f.__name__)

    def test_exact_values(self):
        T = self.T
        self.assertAlmostEqual(T.cubic_out(0.5), 0.875)
        self.assertAlmostEqual(T.cubic_in(0.5), 0.125)
        self.assertAlmostEqual(T.smooth(0.25), 0.15625)
        self.assertAlmostEqual(T.quint_out(0.5), 0.96875)
        self.assertAlmostEqual(T.expo_in(0.5), 2 ** -5)
        self.assertAlmostEqual(T.back_out(1.0), 1.0)
        self.assertGreater(max(T.back_out(i / 100) for i in range(101)), 1.0)      # it overshoots
        self.assertAlmostEqual(T.lerp(10, 20, 0.25), 12.5)
        self.assertEqual(T.clamp(-1), 0.0)
        self.assertEqual(T.clamp(7, 0, 5), 5)

    def test_stepped_twos_and_crt(self):
        T = self.T
        self.assertEqual([T.stepped(u, 3) for u in (0, 0.01, 0.34, 0.67, 1)], [0, 1 / 3, 2 / 3, 1, 1])
        self.assertAlmostEqual(T.twos(0.20), 2 / 12)
        self.assertAlmostEqual(T.twos(0.2501), 3 / 12)
        self.assertEqual(T.crt(0), 0)
        self.assertAlmostEqual(T.crt(0.2), 0.02)
        self.assertAlmostEqual(T.crt(0.41), 0.02 + 0.98 * 0.25)
        self.assertEqual(T.crt(1), 1)

    def test_noise_is_repeatable(self):
        T = self.T
        vals = [T.noise(i, 7) for i in range(200)]
        self.assertTrue(all(0 <= v < 1 for v in vals))
        self.assertEqual(vals, [T.noise(i, 7) for i in range(200)])
        self.assertGreater(len({round(v, 3) for v in vals}), 150)
```

- [ ] **Step 2: Run them and see them fail**

Run: `python3 -m unittest tests.test_motion -v`
Expected: `ModuleNotFoundError: No module named 'eva_desk.motion'`

- [ ] **Step 3: Write `timeline.py`**

The definitions the tests do not pin:

| Function | Definition |
|---|---|
| `cubic_out` / `cubic_in` | `1 − (1 − u)³` / `u³` |
| `smooth` | `u²(3 − 2u)` |
| `back_out(u, s)` | with `v = u − 1`: `v²((s + 1)v + s) + 1` |
| `quint_out` | `1 − (1 − u)⁵` |
| `expo_in` | `0` for `u ≤ 0`, else `2^(10(u − 1))` |
| `stepped(u, n)` | `0` for `u ≤ 0`, else `min(1, ceil(u·n − 1e-6) / n)` |
| `twos(t)` | `floor(t·12 + 1e-6) / 12` |
| `crt(u)` | `0` for `u ≤ 0`; `0.02` below `0.4`; then `min(1, 0.02 + 0.98 · stepped((u − 0.4) / 0.6, 4))` |
| `noise(i, seed)` | the fractional part of `sin(i·127.1 + seed·311.7) · 43758.5453` |

- [ ] **Step 4: Run the tests and see them pass**

Run: `python3 -m unittest tests.test_motion -v`
Expected: 5 tests, `OK`

---

### Task 2: The kit, the piece and one rendered frame

**Files:**
- Modify: `eva_desk/draw.py` (the text section), `eva_desk/motion/__init__.py`
- Create: `eva_desk/motion/kit.py`, `eva_desk/motion/render.py`
- Test: `tests/test_motion.py`

**Interfaces:**
- Consumes: `timeline.clamp`.
- Produces:

```python
# eva_desk/draw.py
def plain_layout(text, family, size, weight=Pango.Weight.NORMAL, italic=False, spacing=0)   # like layout(), from the default font map, no cairo context

# eva_desk/motion/__init__.py
class Piece:
    name = ""        # the registry key
    length = None    # seconds; None = a loop
    covers = True    # takes the pointer while it plays; a click skips it
    still = 0.0      # the moment `eva-desk --render` shows
    def prepare(self, kit, ctx): pass
    def paint(self, kit, t, ctx): raise NotImplementedError
    def release(self): pass
    def draw(self, kit, t, ctx)          # paint(), unless a sequence is before its start or at or past its end
def available() -> bool                  # this GTK has mask nodes (GTK 4.10)

# eva_desk/motion/kit.py
def design(w, h) -> tuple[float, float, float]      # (s, W, H): s = min(h / 720, w / 1280), W = w / s, H = h / s
class Kit:
    W: float; H: float; s: float
    def __init__(self, snap, w, h)                   # saves the snapshot and scales it by s
    def close(self)                                  # restores it; whoever made the kit calls this after painting
    def rect(self, x, y, w, h, colour, alpha=1.0)
    def stroke_rect(self, x, y, w, h, colour, width, alpha=1.0)        # the stroke is centred on the edge
    def band(self, outer, inner, colour, alpha=1.0)                    # what lies between two rectangles (x, y, w, h)
    def para(self, p0, p1, p3, colour, alpha=1.0)                      # a parallelogram: p0, p1, p1 + p3 - p0, p3
    def lines(self, segments, colour, width, alpha=1.0)                # [(x0, y0, x1, y1), ...], each a turned rectangle
    def hazard(self, x, y, w, h, a, b=None, period=28.0, offset=0.0, alpha=1.0)
    def segbar(self, x, y, w, h, value, colour, n, off=None)           # n segments, each 72 % of its pitch; unlit ones in `off` (ink4)
    def radial(self, x, y, r, colour, alpha)                           # a glow that fades to nothing at r
    def text(self, string, x, y, size, colour, face="meta", spacing=0.0, align="left", alpha=1.0) -> float   # y is the baseline; returns the width
    def measure(self, string, size, face="meta", spacing=0.0) -> float
    def clip(self, x, y, w, h)                       # the five below are context managers
    def clip_out(self, x, y, w, h)                   # everything but this rectangle (a mask)
    def clip_out_para(self, p0, p1, p3)              # everything but this parallelogram (a mask)
    def opacity(self, alpha)
    def transform(self, dx=0.0, dy=0.0, rotate=0.0, scale=1.0)         # translate, then rotate (radians), then scale

# eva_desk/motion/render.py
def frame(piece, t, w, h, ctx) -> cairo.ImageSurface    # ARGB32, w x h device px, clear where the piece paints nothing
```

Colours are the rgba tuples `draw.py` hands out. `face` is `"display"` (`d.F_DISPLAY` at `d.DISPLAY_WEIGHT`) or `"meta"` (`d.F_META`). `align` is `"left"`, `"center"` or `"right"`.

- [ ] **Step 1: Write the failing tests**

```python
class KitTest(unittest.TestCase):
    def frame(self, fn, w=1720, h=720):
        from eva_desk.motion import Piece, render

        class P(Piece):
            length = 1.0

            def paint(self, kit, t, ctx):
                fn(kit)
        return render.frame(P(), 0.0, w, h, {})

    def test_design_frame(self):
        from eva_desk.motion.kit import design
        self.assertEqual(design(3440, 1440), (2.0, 1720.0, 720.0))
        self.assertEqual(design(1920, 1080), (1.5, 1280.0, 720.0))
        s, W, H = design(1080, 1920)
        self.assertAlmostEqual(s, 0.84375)
        self.assertAlmostEqual(W, 1280.0)
        self.assertAlmostEqual(H, 1920 / 0.84375)

    def test_rect_lands_where_asked_at_any_monitor_size(self):
        from eva_desk import draw as d
        f = self.frame(lambda k: k.rect(100, 100, 200, 100, d.BONE))
        self.assertEqual(px(f, 150, 150), BONE + (255,))
        self.assertEqual(alpha(f, 90, 150), 0)
        f = self.frame(lambda k: k.rect(100, 100, 200, 100, d.BONE), 3440, 1440)
        self.assertEqual(alpha(f, 300, 300), 255)             # design (150, 150) at twice the size
        self.assertEqual(alpha(f, 150, 150), 0)

    def test_clips(self):
        from eva_desk import draw as d

        def inside(k):
            with k.clip(0, 0, 120, 720):
                k.rect(100, 100, 200, 100, d.BONE)
        f = self.frame(inside)
        self.assertEqual((alpha(f, 110, 150), alpha(f, 150, 150)), (255, 0))

        def hole(k):
            with k.clip_out(760, 260, 200, 200):
                k.rect(0, 0, k.W, k.H, d.INK)
        f = self.frame(hole)
        self.assertEqual((alpha(f, 860, 360), alpha(f, 20, 20)), (0, 255))

        def slanted_gap(k):                                                   # everything but a leaning band
            with k.clip_out_para((400, 0), (600, 0), (300, 720)):
                k.rect(0, 0, k.W, k.H, d.INK)
        f = self.frame(slanted_gap)
        self.assertEqual((alpha(f, 500, 10), alpha(f, 350, 700)), (0, 0))          # inside the band, top and bottom
        self.assertEqual((alpha(f, 700, 360), alpha(f, 100, 360)), (255, 255))

    def test_transform_and_opacity(self):
        from eva_desk import draw as d

        def fn(k):
            with k.transform(dx=860, dy=360, scale=0.5):
                with k.opacity(0.5):
                    k.rect(-100, -100, 200, 200, d.BONE)
        f = self.frame(fn)
        self.assertTrue(120 <= alpha(f, 860, 360) <= 135)
        self.assertEqual(alpha(f, 860 + 60, 360), 0)          # half size: it ends 50 px out

    def test_text(self):
        from eva_desk import draw as d
        got = {}

        def fn(k):
            got["w"] = k.measure("FIREFOX", 92, face="display")
            got["drawn"] = k.text("FIREFOX", 400, 300, 92, d.BONE, face="display")
            k.text("M", 1000, 300, 92, d.BONE, face="display", align="right")
        f = self.frame(fn)
        self.assertGreater(got["w"], 250)
        self.assertEqual(got["w"], got["drawn"])
        lit = [x for x in range(380, 420 + int(got["w"])) if any(alpha(f, x, y) for y in range(220, 310, 3))]
        self.assertTrue(lit and 394 <= lit[0] <= 410 and lit[-1] <= 404 + got["w"], (lit[:1], lit[-1:]))   # starts at x
        self.assertFalse(any(alpha(f, x, y) for x in range(1004, 1040) for y in range(220, 310, 3)))     # right-aligned: ends at x
        self.assertFalse(any(alpha(f, x, 330) for x in range(380, 900)))                                # y was the baseline

    def test_hazard_segbar_lines_poly_radial(self):
        from eva_desk import draw as d
        a = self.frame(lambda k: k.hazard(0, 0, 400, 40, d.CLARET, d.INK, period=30))
        b = self.frame(lambda k: k.hazard(0, 0, 400, 40, d.CLARET, d.INK, period=30, offset=15))
        self.assertEqual((alpha(a, 200, 20), alpha(a, 200, 60)), (255, 0))            # filled, and inside its box
        self.assertNotEqual(bytes(a.get_data()), bytes(b.get_data()))                   # the offset moves the stripes
        f = self.frame(lambda k: k.segbar(100, 100, 260, 10, 0.5, d.GOLD, 26))
        self.assertEqual(px(f, 102, 105)[:3], GOLD)                                     # the first segment is lit
        self.assertNotEqual(px(f, 355, 105)[:3], GOLD)                                  # the last is not
        self.assertEqual(alpha(f, 355, 105), 255)                                       # but it is drawn
        f = self.frame(lambda k: (k.lines([(0, 100, 400, 100)], d.BONE, 4), k.para((500, 0), (600, 0), (450, 100), d.BONE),
                                  k.stroke_rect(700, 100, 100, 100, d.BONE, 4), k.radial(1200, 360, 100, d.GOLD, 0.5)))
        self.assertEqual((alpha(f, 200, 100), alpha(f, 200, 110)), (255, 0))
        self.assertEqual((alpha(f, 525, 10), alpha(f, 610, 50), alpha(f, 470, 10)), (255, 0, 0))    # the parallelogram leans left
        self.assertEqual((alpha(f, 700, 150), alpha(f, 750, 150)), (255, 0))
        self.assertGreater(alpha(f, 1200, 360), 100)
        self.assertEqual(alpha(f, 1320, 360), 0)

    def test_a_sequence_paints_nothing_outside_its_length(self):
        from eva_desk import draw as d
        from eva_desk.motion import Piece, render

        class P(Piece):
            length = 1.0

            def paint(self, kit, t, ctx):
                kit.rect(0, 0, kit.W, kit.H, d.INK)
        self.assertEqual(set(grid(render.frame(P(), 0.5, 320, 180, {}))), {255})
        for t in (-0.1, 1.0, 3.0):
            self.assertEqual(set(grid(render.frame(P(), t, 320, 180, {}))), {0}, t)

    def test_same_frame_twice(self):
        from eva_desk import draw as d
        fn = lambda k: (k.rect(0, 0, 300, 300, d.CLARET), k.text("発進", 100, 200, 120, d.BONE, face="display"))
        self.assertEqual(bytes(self.frame(fn).get_data()), bytes(self.frame(fn).get_data()))

    def test_plain_layout_and_available(self):
        from eva_desk import draw as d, motion
        ink, logical = d.plain_layout("EVA", d.F_META, 20, spacing=2).get_pixel_extents()
        self.assertGreater(logical.width, 30)
        self.assertTrue(motion.available())
```

- [ ] **Step 2: Run them and see them fail**

Run: `python3 -m unittest tests.test_motion.KitTest -v`
Expected: `ImportError: cannot import name 'Piece' from 'eva_desk.motion'`

- [ ] **Step 3: Add `plain_layout` to `draw.py`**

Move the font description and letter spacing out of `layout()` into a private helper and call it from both, so `layout(cr, ...)` behaves exactly as before. `plain_layout` makes its layout with `Pango.Layout.new(PangoCairo.FontMap.get_default().create_context())`.

- [ ] **Step 4: Write `Piece` and `available` in `motion/__init__.py`**

`draw()` returns without painting when `length` is not `None` and `t` is outside `[0, length)`.

- [ ] **Step 5: Write `kit.py`**

Import `gtkutil` first for the GTK version pins, as the other modules do. What the signatures leave open:

- `text` and `measure` take their layout from `d.plain_layout`, kept in a module-level cache keyed by string, family, weight, size and spacing, cleared when it passes 512 entries. `text` goes on with `snap.append_layout`, placed so that `y` is the baseline (`layout.get_baseline() / Pango.SCALE`), and returns the logical width.
- `hazard` is the geometry of `draw.hazard` (stripes at 135 degrees, half a period wide), each stripe a `para`, inside a clip, shifted right by `offset`.
- `stroke_rect` and `band` are border nodes. `para` is a unit square under translate, rotate, skew and scale (a raw matrix is not a 2D transform to GTK and draws as pink offline). `lines` is one turned rectangle per segment.
- `clip_out` and `clip_out_para` are `snap.push_mask(Gsk.MaskMode.INVERTED_ALPHA)` with the rectangle or the parallelogram as the mask.
- `radial` is `append_radial_gradient` with two stops of the colour, `alpha` at the centre and 0 at `r`.

- [ ] **Step 6: Write `render.frame`**

`Gtk.Snapshot()`, a `Kit`, `piece.draw(kit, t, ctx)`, `kit.close()`, `snap.to_node()`, and `node.draw()` into a cairo context on a fresh ARGB32 surface. `to_node()` is `None` when nothing was painted: return the clear surface.

- [ ] **Step 7: Run the tests and see them pass**

Run: `python3 -m unittest discover -s tests`
Expected: `OK`, with the 9 tests of `KitTest` among them and nothing else broken by the `draw.py` change

---

### Task 3: The card

**Files:**
- Create: `eva_desk/motion/seq/__init__.py`, `eva_desk/motion/seq/card.py`
- Test: `tests/test_motion.py`

**Interfaces:**
- Consumes: `Piece`, `Kit`, `timeline`, `render.frame`.
- Produces, in `eva_desk.motion.seq.card`:
  `class Card(Piece)` with `name = "card"`, `length = 2.0`, `covers = True`, `still = 1.15`;
  `plates(W, H, p) -> (left, right)`, two polygons of four `(x, y)` points each, `p` from 0 (apart) to 1 (met);
  `name_width(kit, name, size) -> float`; `name_size(kit, name) -> float`.
  `ctx` keys read: `app` (str), `workspace` (int or `None`), `clock` (`"hh:mm"`). All optional.

- [ ] **Step 1: Write the failing tests**

```python
class CardTest(unittest.TestCase):
    def setUp(self):
        from eva_desk.motion import render
        from eva_desk.motion.seq.card import Card
        self.render, self.card = render, Card()

    def at(self, t, w=1720, h=720, **ctx):
        return self.render.frame(self.card, t, w, h, dict(CTX, **ctx))

    def test_identity(self):
        self.assertEqual((self.card.name, self.card.length, self.card.covers), ("card", 2.0, True))

    def test_plates_cover_the_desk_from_026_to_162(self):
        for t in (0.26, 0.9, 1.3, 1.61):
            self.assertEqual(set(grid(self.at(t))), {255}, t)

    def test_clear_at_both_ends(self):
        self.assertEqual(alpha(self.at(0.0), 860, 360), 0)
        self.assertEqual(set(grid(self.at(2.0))), {0})

    def test_the_seam_leans(self):
        from eva_desk.motion.seq import card
        left, right = card.plates(1720, 720, 1.0)
        self.assertEqual((left[1], left[2]), ((955, 0), (765, 720)))          # 190 px over the height, about the centre
        self.assertEqual((right[1], right[2]), (left[1], left[2]))            # met
        left, right = card.plates(1720, 720, 0.0)
        self.assertLess(left[1][0], 0)                                        # both off the screen
        self.assertGreater(right[2][0], 1720)

    def test_never_a_bright_screen(self):
        f = self.at(0.6)                                                      # the slab at its widest
        points = [(x, y) for y in range(10, 720, 20) for x in range(10, 1720, 20)]
        self.assertLess(sum(px(f, x, y)[:3] == BONE for x, y in points) / len(points), 0.5)

    def test_the_name_is_the_apps(self):
        self.assertEqual(bytes(self.at(0.5).get_data()), bytes(self.at(0.5, app="KITTY").get_data()))        # not shown yet
        self.assertNotEqual(bytes(self.at(1.15).get_data()), bytes(self.at(1.15, app="KITTY").get_data()))

    def test_a_long_name_is_set_smaller(self):
        from eva_desk.motion import Piece
        from eva_desk.motion.seq import card
        long, got = "LIBREOFFICE CALC SPREADSHEET EDITOR", {}

        class P(Piece):
            length = 1.0

            def paint(self, kit, t, ctx):
                got["short"], got["long"] = card.name_size(kit, "FIREFOX"), card.name_size(kit, long)
                got["width"] = card.name_width(kit, long, got["long"])
        self.render.frame(P(), 0, 1720, 720, {})
        self.assertEqual(got["short"], 170)
        self.assertLess(got["long"], 170)
        self.assertLessEqual(got["width"], 1720 - 128)

    def test_odd_names_and_missing_inputs(self):
        for app in ("", None, "火狐 🦊", "A" * 80):
            for t in (0.9, 1.2):
                self.at(t, app=app)
        self.render.frame(self.card, 1.2, 1720, 720, {})                      # no inputs at all

    def test_other_monitor_shapes(self):
        for w, h in ((3440, 1440), (1080, 1920), (640, 360)):
            self.assertEqual(set(grid(self.at(1.0, w, h))), {255}, (w, h))

    def test_same_frame_twice(self):
        self.assertEqual(bytes(self.at(1.234).get_data()), bytes(self.at(1.234).get_data()))
```

- [ ] **Step 2: Run them and see them fail**

Run: `python3 -m unittest tests.test_motion.CardTest -v`
Expected: `ModuleNotFoundError: No module named 'eva_desk.motion.seq'`

- [ ] **Step 3: Write `card.py`**

`W`, `H` are the kit's frame, `cx = W / 2`, `cy = H / 2`. Times in seconds, lengths in design px. Painted in this order:

| Part | Geometry and timing |
|---|---|
| Plates | `p = quint_out(seg(t, 0, 0.26)) · (1 − smooth(seg(t, 1.62, 2.0)))`. With `slant = 190` and `off = (1 − p)(W/2 + slant + 40)`: left `(−W − off, 0), (cx + 95 − off, 0), (cx − 95 − off, H), (−W − off, H)`; right `(2W + off, 0), (cx + 95 + off, 0), (cx − 95 + off, H), (2W + off, H)`. In `ink`, each drawn as a sheared rectangle (`para`) that reaches 0.75 px past its seam, so no hairline shows where they meet. |
| Seam edges | Only while `p ≤ 0.995`, at alpha `clamp(5(1 − p))`: `claret` dashes inside each plate along its seam, 16 wide, 15 long, one every 30 px of height, each a `para` following the lean. |
| Everything below | Only for `0.12 ≤ t ≤ 1.9`, with the gap between the plates cut out of it (`clip_out_para`) while they are apart. All but the speed lines is shifted up by `1.3 · H · lift`, `lift = expo_in(seg(t, 1.25, 1.62))`. |
| Fold | `fold = smooth(seg(t, 0.64, 0.84))`. |
| Kanji | `kin = quint_out(seg(t, 0.14, 0.50))`. Inside a transform at `(lerp(cx, 142, fold), lerp(cy + 128, 136, fold))` scaled `lerp(1, 0.2, fold)`: 発 centred on x −190 with baseline `(1 − kin) · 560`, 進 centred on x +190 with baseline `−(1 − kin) · 560`, display face, 380. In `bone`. |
| Slab | Centred on `(cx, ry)`, `ry = lerp(cy, 0.60H, fold)`; height `lerp(300, 4, fold)`; width `lerp(W · smooth(seg(t, 0.30, 0.56)), W − 128, fold)`. Filled `bone`, and the kanji drawn once more in `ink`, clipped to the slab. |
| Name | From 0.78. Display face in `bone`, size `name_size(kit, name)`, baseline `ry − 16`, starting at x 64. Letter `i` has width `wᵢ` and rises with `r = quint_out(seg(t, 0.80 + step·i, 1.08 + step·i))`, `step = min(0.035, 0.30 / len(name))`: clip `(x − 12, base − size, wᵢ + 24, size + 14)`, baseline `base + (1 − r) · size`; then `x += wᵢ − 4`. |
| Meta line | `TARGET ・ {name} ・ WORKSPACE {nn} ・ {clock}` (the parts whose input is missing are left out), meta face 13, spacing 4, in `d.RED`, at `(64, ry + 30)`, clipped to `(64, ry + 8, width · smooth(seg(t, 0.92, 1.2)), 30)`. |
| Gold line | `rect(64, ry − 2, (W − 128) · smooth(seg(t, 0.84, 1.24)), 4)` in `gold`. |
| Speed lines | Not lifted. `sa = seg(t, 1.25, 1.42) · (1 − seg(t, 1.62, 1.84))`. 46 lines, 2 px wide, alpha `0.55 · sa`: `x = noise(i, 51) · W`; length `(60 + 520 · noise(i, 52)) · (0.3 + lift)`; top at `((noise(i, 53) + 2.4 · t · (0.6 + noise(i, 54))) mod 1.3) · H − 0.2H`; `gold` when `noise(i, 55) > 0.75`, else `bone`. |

`name_width(kit, name, size)` is the sum of `wᵢ − 4`. `name_size` is 170 when that fits `kit.W − 128`, otherwise 170 scaled down to fit, never under 24. A missing or empty name is `APP`.

- [ ] **Step 4: Run the tests and see them pass**

Run: `python3 -m unittest tests.test_motion.CardTest -v`
Expected: 10 tests, `OK`

- [ ] **Step 5: Look at it**

Run: `python3 - <<'EOF'` from the worktree root, with a scratch directory of your own in place of `/tmp/card`:

```python
import os, sys; sys.path.insert(0, "."); os.environ.pop("WAYLAND_DISPLAY", None)
from eva_desk import config; config.load("/nonexistent")
from eva_desk.motion import render
from eva_desk.motion.seq.card import Card
os.makedirs("/tmp/card", exist_ok=True)
for t in (0.10, 0.30, 0.45, 0.60, 0.75, 0.95, 1.20, 1.45, 1.80):
    render.frame(Card(), t, 1720, 720, {"app": "FIREFOX", "workspace": 2, "clock": "22:44"}).write_to_png(f"/tmp/card/{t:.2f}.png")
EOF
```

Read the nine PNGs against the storyboard in the spec ("The card"): plates closing, the two kanji arriving, the bone slab with ink kanji, the fold to a rule with the tag at the top left, the name rising, the gold line, lift-off with speed lines, the plates parting. Fix what does not match before going on.

---

### Task 4: The shaft

**Files:**
- Create: `eva_desk/motion/seq/shaft.py`
- Test: `tests/test_motion.py`

**Interfaces:**
- Consumes: `Piece`, `Kit`, `timeline`, `render.frame`.
- Produces, in `eva_desk.motion.seq.shaft`:
  `class Shaft(Piece)` with `name = "shaft"`, `length = 2.0`, `covers = True`, `still = 1.0`;
  `travel(u) -> float` (bays covered at progress `u` of the two seconds);
  `exit_half(t, W, H) -> (hw, hh)` (half the exit's size on screen at time `t`);
  `gate_number(k) -> int | None` (the number on bay `k`'s gate, `None` where there is no gate).
  `ctx` keys read: `app`. Optional.

- [ ] **Step 1: Write the failing tests**

```python
class ShaftTest(unittest.TestCase):
    def setUp(self):
        from eva_desk.motion import render
        from eva_desk.motion.seq.shaft import Shaft
        self.render, self.shaft = render, Shaft()

    def at(self, t, w=1720, h=720, **ctx):
        return self.render.frame(self.shaft, t, w, h, dict(CTX, **ctx))

    def test_identity(self):
        self.assertEqual((self.shaft.name, self.shaft.length, self.shaft.covers), ("shaft", 2.0, True))

    def test_travel(self):
        from eva_desk.motion.seq import shaft
        self.assertEqual(shaft.travel(0.0), 0.0)
        self.assertAlmostEqual(shaft.travel(1.0), 59.0)
        ds = [shaft.travel(i / 200) for i in range(201)]
        self.assertEqual(ds, sorted(ds))
        self.assertLess(shaft.travel(0.25), 2.0)                              # slow off the locks
        self.assertAlmostEqual(shaft.travel(0.5), 59 * 0.125 / (0.125 + 0.5 ** 1.7))
        self.assertGreater(shaft.travel(0.9), 57.0)                           # nearly there: it is braking

    def test_the_exit_grows_into_the_screen(self):
        from eva_desk.motion.seq import shaft
        self.assertEqual(shaft.exit_half(0.0, 1720, 720), (860 / 60, 360 / 60))
        hw, hh = shaft.exit_half(2.0, 1720, 720)
        self.assertAlmostEqual(hw, 860)
        self.assertAlmostEqual(hh, 360)
        ws = [shaft.exit_half(i / 50, 1720, 720)[0] for i in range(101)]
        self.assertEqual(ws, sorted(ws))

    def test_the_far_end_is_the_desk(self):
        f = self.at(1.0)
        self.assertEqual((alpha(f, 860, 360), alpha(f, 12, 12)), (0, 255))    # the hole, the shaft
        f = self.at(1.98)
        self.assertEqual((alpha(f, 860, 360), alpha(f, 300, 200)), (0, 0))    # nearly all of the screen now
        self.assertEqual(set(grid(self.at(2.0))), {0})

    def test_gates_count_down(self):
        from eva_desk.motion.seq import shaft
        self.assertEqual([shaft.gate_number(k) for k in (10, 20, 30, 40, 50)], [5, 4, 3, 2, 1])
        self.assertIsNone(shaft.gate_number(60))
        self.assertIsNone(shaft.gate_number(15))

    def test_the_instruments_carry_the_name_and_leave(self):
        self.assertNotEqual(bytes(self.at(0.6).get_data()), bytes(self.at(0.6, app="KITTY").get_data()))
        self.assertEqual(bytes(self.at(1.85).get_data()), bytes(self.at(1.85, app="KITTY").get_data()))      # gone by 1.80

    def test_never_a_bright_screen(self):
        points = [(x, y) for y in range(10, 720, 20) for x in range(10, 1720, 20)]
        for t in (0.0, 0.3, 0.55, 1.0, 1.4, 1.7, 1.95):
            f = self.at(t)
            bright = sum(1 for x, y in points if alpha(f, x, y) and min(px(f, x, y)[:3]) > 200)
            self.assertLess(bright / len(points), 0.2, t)

    def test_odd_names_and_shapes(self):
        for app in ("", None, "火狐 🦊", "A" * 80):
            self.at(0.6, app=app)
        self.render.frame(self.shaft, 0.6, 1720, 720, {})
        for w, h in ((3440, 1440), (1080, 1920), (640, 360)):
            f = self.at(1.0, w, h)
            self.assertEqual((alpha(f, w // 2, h // 2), alpha(f, 4, 4)), (0, 255), (w, h))

    def test_same_frame_twice(self):
        self.assertEqual(bytes(self.at(1.234).get_data()), bytes(self.at(1.234).get_data()))
```

- [ ] **Step 2: Run them and see them fail**

Run: `python3 -m unittest tests.test_motion.ShaftTest -v`
Expected: `ModuleNotFoundError: No module named 'eva_desk.motion.seq.shaft'`

- [ ] **Step 3: Write `shaft.py`**

The numbers of the run, with `u = t / 2`:

| Name | Value |
|---|---|
| `travel(u)` | `59 · u³ / (u³ + (1 − u)^1.7)` |
| `d`, `zx` | `d = travel(u)`; the exit is `zx = 60 − d` bays ahead |
| `exit_half` | `(W/2 / zx, H/2 / zx)`, called `hw`, `hh` below |
| speed `vn` | `clamp((travel(min(1, u + 0.004)) − travel(max(0, u − 0.004))) / 0.008 / 59 / 2.5)` |
| `damp` | `(1 − u)^1.6` |
| roll (radians) | `(0.028 · sin(5.2t) + 0.012 · sin(11t)) · damp` |
| rumble | `jx = 2.6 · vn · sin(190t) · damp`, `jy = 2.6 · vn · cos(163t) · damp` |
| `gate_number(k)` | `(60 − k) / 10` when `k` is a multiple of 10 below 60 |

A frame `z` bays ahead is the rectangle of half-size `(W/2 / z, H/2 / z)` about the origin of shaft space, which is `transform(dx = W/2 + jx, dy = H/2 + jy, rotate = roll)`. Painted in this order:

| Part | Geometry |
|---|---|
| Clip | Everything in shaft space but the rim is inside `clip_out(−hw, −hh, 2hw, 2hh)`: the exit is a hole. The band between two bay frames is `kit.band`. |
| Ground and glow | `ink` over `(−2W, −2H, 4W, 4H)`. Then `radial(0, 0, max(110, 5hw), bone, 0.30 · clamp((zx − 1.2) / 6))`. |
| Corner rails | Four lines from `(±1.5W, ±1.5H)` to `(±hw, ±hh)`, `claret`, 1.5 wide, alpha 0.55. |
| Bays | For `k` from `min(60, floor(d + 46))` down to `max(1, ceil(d + 0.3))`, with `z = k − d` and `fog = clamp(1 − z / 46)^1.4`. If `k` is even and below 60: the band between this frame and the one at `z + 1`, `d.col("ink4")`, alpha `0.6 · fog`. Then the frame's outline: `claret`, alpha `0.85 · fog`, width `clamp(4.5 / z, 1.2, 20)`; or, for a gate, `led`, alpha `0.95 · fog`, width `clamp(10 / z, 1.2, 44)`. |
| Gate labels | For a gate with `z > 0.5`, inside a `1 / z` scale: `GATE 0{n}`, display face 30, spacing 3.6, centred on x 0, baseline `−H/2 + 45`, `led`, alpha `fog`. |
| Wall lights | 44 lights. Light `i` sits on side `i mod 4` (top, bottom, left, right) at `a = 1.7 · noise(i, 31) − 0.85` along it: wall point `(a · W/2, ∓H/2)` or `(∓W/2, a · H/2)`. It repeats every 9 bays from `base = 9 · noise(i, 32)`. `gold` when `noise(i, 33) > 0.72`, else `bone`. Each copy starts `z0 = base + 9n − d` ahead and is `len = 0.18 + 2.6 · vn` bays long; skip copies beyond `z0 > 40`, past bay 59.5, or wholly nearer than 0.35. Its segment runs from the wall point divided by `za = max(0.35, z0)` to the wall point divided by `z0 + len`; its alpha is `0.8 · clamp(1 − za / 40)^1.2` and its width `clamp(2.4 / za, 0.8, 9)`. Draw them as one `kit.lines` call per colour and depth band (band edges at `za` = 0.35, 1, 2, 4, 8, 16, 40; alpha and width from the middle of the band). |
| The sign | `zs = 3.2 − d`. While `zs > 0.3`, at alpha `clamp(t / 0.14) · clamp((zs − 0.3) / 0.45)` and inside a `1 / zs` scale: 発進 display face 430, centred, baseline 150, `bone`; `rect(−430, 196, 860, 8)` in `gold`; `LAUNCH` meta face 44, spacing 46, centred, baseline 262, `gold`. |
| The rim | Outside the clip, in shaft space: `stroke_rect(−hw, −hh, 2hw, 2hh, bone, clamp(9 / zx, 1.5, 8), 0.9)`. |
| Instruments | In screen space. `out = smooth(seg(t, 1.46, 1.80))`; the left group is shifted by `−480 · out`, the right by `+480 · out`, both at alpha `1 − out`. |
| Left group | `発進シーケンス ・ LAUNCH`, display 14, spacing 2, `gold`, at `(64, 92)`. Five locks: `rect(64 + 44i, 106, 36, 9)` in `led`, and over it in `gold` at width `36 · smooth(seg(t, 0.05 + 0.06i, 0.19 + 0.06i))`. At `(292, 115)`, meta 10.5, spacing 2: `LOCK BOLTS 01-05` in `led` before 0.44, `LOCK BOLTS RELEASED` in `gold` after. `TARGET`, meta 11, spacing 5, `d.RED`, at `(66, H − 170)`. The name: display face, 92 or smaller to fit `W/2 − 96`, `bone`, at `(62, H − 78)`, clipped to `(56, H − 162, (nw + 16) · rev, 112)` with `rev = quint_out(seg(t, 0.10, 0.52))` and `nw` its width; under it `rect(64, H − 62, nw · rev, 3)` in `gold`. |
| Right group | Right-aligned at x `W − 64`: `ALTITUDE` (meta 11, spacing 5, `d.RED`) at y 92; `-NNNN M` (meta 54, spacing 2, `bone`) at y 146, `NNNN = round(20(zx − 1))` padded to four digits; `VELOCITY` at y `H − 104`. `segbar(W − 324, H − 90, 260, 10, vn, gold, 26)`. |

A missing or empty name is `APP`.

- [ ] **Step 4: Run the tests and see them pass**

Run: `python3 -m unittest tests.test_motion.ShaftTest -v`
Expected: 9 tests, `OK`

- [ ] **Step 5: Look at it**

As in Task 3 Step 5, with `Shaft` and the times `0.30, 0.60, 0.80, 1.10, 1.40, 1.60, 1.80, 1.90, 1.97`. Read the PNGs against the spec ("The shaft"): the sign in the tunnel, then behind you; orange gates with their numbers; the lights growing longer with speed; the instruments, and their leaving; the exit growing until it is the frame. Fix what does not match.

---

### Task 5: Contact sheets, mp4 and the command line

**Files:**
- Modify: `eva_desk/motion/__init__.py`, `eva_desk/motion/render.py`, `eva_desk/__main__.py`, `eva_desk/preview.py`
- Test: `tests/test_motion.py`

**Interfaces:**
- Consumes: `Card`, `Shaft`, `render.frame`.
- Produces:

```python
# eva_desk/motion/__init__.py
def pieces() -> dict[str, type]                 # {"card": Card, "shaft": Shaft}; imports them when called

# eva_desk/motion/render.py
def fixture_ctx() -> dict                       # {"app": "FIREFOX", "workspace": 2, "clock": "22:44"}
def parse_size(text) -> tuple[int, int]         # "1720x720"; ValueError for anything else, and for a zero side
def sheet(piece, w, h, ctx, cols=4, rows=3) -> cairo.ImageSurface     # cols * rows frames of w x h, no gaps
def build_ms(piece, w, h, ctx, n=40) -> float   # mean time to build one frame's node tree, in ms
def write(name, piece, out_dir, w, h, fps, ctx) -> list[Path]         # NAME.png, and NAME.mp4 when ffmpeg is on PATH
def render_motion(out, only=None, size=(1720, 720), fps=30) -> list[Path]   # KeyError for an unknown name

# eva_desk/preview.py
def motion_stills(out, w, h) -> list[Path]      # motion_NAME.png for every piece, at its `still`
```

Command line: `eva-desk --render-motion DIR [--only NAME] [--size WxH] [--fps N]`.

- [ ] **Step 1: Write the failing tests**

```python
class RenderTest(unittest.TestCase):
    def test_registry(self):
        from eva_desk import motion
        self.assertEqual(sorted(motion.pieces()), ["card", "shaft"])
        self.assertEqual({n: p().name for n, p in motion.pieces().items()}, {"card": "card", "shaft": "shaft"})

    def test_parse_size(self):
        from eva_desk.motion import render
        self.assertEqual(render.parse_size("1720x720"), (1720, 720))
        for bad in ("", "1720", "0x720", "axb", "1720x720x3"):
            with self.assertRaises(ValueError, msg=bad):
                render.parse_size(bad)

    def test_sheet_and_files(self):
        from eva_desk.motion import pieces, render
        s = render.sheet(pieces()["card"](), 320, 180, render.fixture_ctx(), cols=4, rows=2)
        self.assertEqual((s.get_width(), s.get_height()), (1280, 360))
        self.assertEqual(alpha(s, 10, 10), 255)                               # frames sit on a stand-in desk, not on nothing
        with tempfile.TemporaryDirectory() as tmp, mock.patch("shutil.which", return_value=None), \
                contextlib.redirect_stdout(io.StringIO()):
            out = render.render_motion(tmp, only="card", size=(320, 180), fps=10)
            self.assertEqual([p.name for p in out], ["card.png"])
            self.assertGreater((Path(tmp) / "card.png").stat().st_size, 2000)
            with self.assertRaises(KeyError):
                render.render_motion(tmp, only="nope")

    @unittest.skipUnless(shutil.which("ffmpeg"), "ffmpeg is not installed")
    def test_mp4(self):
        from eva_desk.motion import render
        with tempfile.TemporaryDirectory() as tmp, contextlib.redirect_stdout(io.StringIO()):
            out = render.render_motion(tmp, only="shaft", size=(321, 181), fps=10)       # odd sizes are made even
            self.assertEqual(sorted(p.name for p in out), ["shaft.mp4", "shaft.png"])
            self.assertGreater((Path(tmp) / "shaft.mp4").stat().st_size, 1000)

    def test_build_time_is_measured(self):
        from eva_desk.motion import pieces, render
        self.assertGreater(render.build_ms(pieces()["shaft"](), 1720, 720, render.fixture_ctx(), n=5), 0)

    def test_stills_for_the_standing_render(self):
        from eva_desk import preview
        with tempfile.TemporaryDirectory() as tmp:
            out = preview.motion_stills(tmp, 640, 360)
            self.assertEqual(sorted(p.name for p in out), ["motion_card.png", "motion_shaft.png"])

    def test_command_line(self):
        env = dict(os.environ, WAYLAND_DISPLAY="eva-none", PYTHONPATH=str(ROOT))
        with tempfile.TemporaryDirectory() as tmp:
            r = subprocess.run([sys.executable, "-m", "eva_desk", "--render-motion", tmp, "--only", "card", "--size", "320x180", "--fps", "10"],
                               cwd=ROOT, env=env, capture_output=True, text=True, timeout=180)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertTrue((Path(tmp) / "card.png").exists())
            self.assertIn("card", r.stdout)
            r = subprocess.run([sys.executable, "-m", "eva_desk", "--render-motion", tmp, "--only", "nope"],
                               cwd=ROOT, env=env, capture_output=True, text=True, timeout=60)
            self.assertEqual(r.returncode, 2)
            self.assertIn("card, shaft", r.stdout + r.stderr)
```

- [ ] **Step 2: Run them and see them fail**

Run: `python3 -m unittest tests.test_motion.RenderTest -v`
Expected: `AttributeError: module 'eva_desk.motion' has no attribute 'pieces'`

- [ ] **Step 3: Write `pieces()` and the rest of `render.py`**

- `sheet` takes `cols · rows` frames at `t = seconds · (i + 0.5) / n`, where `seconds` is the piece's `length` (or its `lap` attribute, or 20, for a loop). Each frame is painted over a stand-in desk, a flat `d.col("wine")`, so that what the piece leaves clear reads as the desk.
- `write` saves the sheet as `NAME.png`. When `shutil.which("ffmpeg")` finds it, it also pipes every frame at `fps`, over the same stand-in, as raw BGRA to `ffmpeg -loglevel error -y -f rawvideo -pix_fmt bgra -s WxH -r FPS -i - -c:v libx264 -pix_fmt yuv420p -crf 18 NAME.mp4`, with both sides rounded down to even. Call it as `shutil.which`, not through a `from` import, so the test can patch it.
- `render_motion` prints one line per piece: its name, the frame count, the mean ms to draw a frame and `build_ms`.

- [ ] **Step 4: Wire the command line and the standing render**

In `__main__.py` add `--render-motion DIR`, `--only NAME`, `--size WxH` (default `1720x720`) and `--fps N` (default 30), handled next to `--render`. An unknown piece or a bad size prints `eva-desk: ` and the reason, with the known names for a piece, and exits with status 2. Add the line to the module docstring.
In `preview.py` write `motion_stills` and call it at the end of `render_all` with its `out`, `w`, `h`.

- [ ] **Step 5: Run the tests and see them pass**

Run: `python3 -m unittest tests.test_motion.RenderTest -v`
Expected: 7 tests, `OK` (6 and one skip without `ffmpeg`)

---

### Task 6: The player

**Files:**
- Create: `eva_desk/motion/player.py`
- Test: `tests/test_motion.py`

**Interfaces:**
- Consumes: `overlays._Overlay` (its window, `place`, `show`, `hide`), `Kit`, `Piece`.
- Produces:

```python
class SequencePlayer(_Overlay):                 # one piece at a time, on one monitor
    at: float                                   # seconds into the running piece
    def __init__(self, app)                     # the layer surface "eva-motion": overlay layer, keyboard none; a click calls skip()
    def setup(self)                             # the state __init__ sets once the window exists; the tests call it on a bare instance
    def play(self, piece, gdk_monitor, ctx, on_done=None) -> bool
    def advance(self, now) -> bool              # one tick at `now` seconds; True when that ended the piece
    def skip(self)                              # ends a covering piece; nothing for a pass-through one
    def finish(self)                            # hide, release, call on_done once; safe to call again
    @property
    def busy(self) -> bool                      # a covering piece is on screen
    def _paint(self, snap, w, h)                # what the view calls
    def _after(self, ms, fn)                    # GLib.timeout_add; the tests replace it
```

- [ ] **Step 1: Write the failing tests**

```python
class FakeSurface:
    region = None

    def set_input_region(self, region):
        self.region = region


class FakeWin:
    def __init__(self):
        self.visible, self.surface = False, FakeSurface()

    def set_visible(self, on):
        self.visible = on

    def get_visible(self):
        return self.visible

    def present(self):
        pass

    def get_surface(self):
        return self.surface


class FakeView:
    def queue_draw(self):
        pass

    def add_tick_callback(self, fn):
        return 1

    def remove_tick_callback(self, tick):
        pass


def dummy(covers=True, boom=False):
    from eva_desk.motion import Piece

    class Dummy(Piece):
        length = 2.0
        released = 0

        def paint(self, kit, t, ctx):
            if boom:
                raise RuntimeError("boom")

        def release(self):
            self.released += 1
    piece = Dummy()
    piece.covers = covers
    return piece


def player():
    from eva_desk.motion.player import SequencePlayer
    p = SequencePlayer.__new__(SequencePlayer)
    p.app, p.win, p.view = object(), FakeWin(), FakeView()
    p.setup()
    p.timers = []
    p._after = lambda ms, fn: p.timers.append((ms, fn))

    def place(mon):
        p.w, p.h = (1720, 720) if mon else (0, 0)
    p.place = place
    return p


class PlayerTest(unittest.TestCase):
    def test_plays_to_the_end_once(self):
        p, done, piece = player(), [], dummy()
        self.assertTrue(p.play(piece, "MON", {"app": "X"}, on_done=lambda: done.append(1)))
        self.assertTrue(p.win.visible and p.busy)
        self.assertFalse(p.advance(10.0))                 # the first tick is t = 0
        self.assertFalse(p.advance(11.5))
        self.assertAlmostEqual(p.at, 1.5)
        self.assertTrue(p.advance(12.0))                  # t = length: over
        self.assertFalse(p.win.visible or p.busy)
        self.assertEqual((done, piece.released), ([1], 1))
        p.finish()
        self.assertEqual((done, piece.released), ([1], 1))

    def test_a_click_skips_only_what_covers(self):
        p = player()
        p.play(dummy(covers=True), "MON", {})
        p.skip()
        self.assertFalse(p.win.visible)
        p.play(dummy(covers=False), "MON", {})
        p.skip()
        self.assertTrue(p.win.visible)
        self.assertFalse(p.busy)                          # on screen, but it covers nothing

    def test_the_pointer_goes_through_what_does_not_cover(self):
        p = player()
        p.play(dummy(covers=True), "MON", {})
        self.assertFalse(p.win.surface.region.is_empty())
        p.finish()
        p.play(dummy(covers=False), "MON", {})
        self.assertTrue(p.win.surface.region.is_empty())

    def test_a_new_piece_replaces_the_running_one(self):
        p, log, a, b = player(), [], dummy(), dummy()
        p.play(a, "MON", {}, on_done=lambda: log.append("a"))
        p.play(b, "MON", {}, on_done=lambda: log.append("b"))
        self.assertEqual((log, a.released), (["a"], 1))
        self.assertTrue(p.win.visible)
        p.advance(0.0)
        p.advance(2.0)
        self.assertEqual((log, b.released), (["a", "b"], 1))

    def test_no_monitor_no_show(self):
        p = player()
        self.assertFalse(p.play(dummy(), None, {}))
        self.assertFalse(p.win.visible or p.busy)
        self.assertEqual(p.timers, [])

    def test_a_piece_that_raises_ends_the_sequence(self):
        from eva_desk import gtkutil  # noqa: F401
        from gi.repository import Gtk
        p, done = player(), []
        p.play(dummy(boom=True), "MON", {}, on_done=lambda: done.append(1))
        with contextlib.redirect_stdout(io.StringIO()) as out:
            p._paint(Gtk.Snapshot(), 1720, 720)
        self.assertFalse(p.win.visible)
        self.assertEqual(done, [1])
        self.assertIn("eva-desk: motion", out.getvalue())

    def test_the_safety_timeout_only_ends_its_own_run(self):
        p = player()
        p.play(dummy(), "MON", {})
        ms, late = p.timers[-1]
        self.assertEqual(ms, 3000)                        # length + 1 s
        p.finish()
        p.play(dummy(), "MON", {})
        late()                                            # the first run's timer fires late
        self.assertTrue(p.win.visible)
        p.timers[-1][1]()
        self.assertFalse(p.win.visible)
```

- [ ] **Step 2: Run them and see them fail**

Run: `python3 -m unittest tests.test_motion.PlayerTest -v`
Expected: `ModuleNotFoundError: No module named 'eva_desk.motion.player'`

- [ ] **Step 3: Write `player.py`**

What the tests leave open:

- `__init__` builds the overlay with `passthrough=False` (the input region is set per piece), adds a `Gtk.GestureClick` on the view that calls `skip`, and calls `setup()`.
- `play` first finishes whatever is running. Then `place(gdk_monitor)`; with no width it returns `False`. Otherwise `piece.prepare`, `show()`, then the input region on `self.win.get_surface()`: the whole surface for a covering piece, an empty `cairo.Region()` otherwise. It starts the tick callback, which calls `advance(clock.get_frame_time() / 1e6)` and queues a draw, and arms `_after(int((length + 1) * 1000), ...)` with a callback that finishes only if its run is still the current one (a counter bumped by every `play`).
- `_paint` makes a `Kit`, calls `piece.draw(kit, self.at, ctx)` and `kit.close()`. If the piece raises it prints `eva-desk: motion: <name>: <error>` and finishes. The kit is closed either way, so the snapshot stays balanced.
- `finish` clears the running piece before it calls anything, so a done callback that plays the next piece is safe.

- [ ] **Step 4: Run the tests and see them pass**

Run: `python3 -m unittest tests.test_motion.PlayerTest -v`
Expected: 7 tests, `OK`

---

### Task 7: Enter in the launcher plays it

**Files:**
- Modify: `eva_desk/config.py` (`DEFAULTS`), `eva_desk/launcher.py` (`show`, `_key`, `_launch`), `eva_desk/app.py` (`do_activate`, `command`, one new method), `hypr/eva.lua` (the layer rule), `bin/eva-ctl` (the docstring), `config/eva.example.toml`, `packaging/PKGBUILD`, `packaging/.SRCINFO`, `README.md`, `docs/superpowers/specs/2026-10-06-motion-redesign-design.md`
- Test: `tests/test_motion.py`

**Interfaces:**
- Consumes: `SequencePlayer.play`, `motion.available`, `Card`, `Shaft`.
- Produces:

```python
# eva_desk/config.py
DEFAULTS["motion"] = {"launch": True}

# eva_desk/launcher.py
def launch_info(item) -> tuple[str, bool]       # (the name to show, whether the entry is a game)
class Launcher:
    gdk_monitor                                 # the monitor show() was last given
    def _launch(self, item, plain=False)        # plain: no sequence

# eva_desk/app.py
class App:
    motion: SequencePlayer | None
    def play_launch(self, name, game, gdk_monitor) -> bool
    # command(): "play NAME [TEXT]"
```

- [ ] **Step 1: Write the failing tests**

```python
class FakeHypr:
    lua = True

    def __init__(self):
        self.state, self.execs = {}, []

    def j(self, what):
        return self.state.get(what)

    def exec(self, cmd):
        self.execs.append(cmd)


class FakeAppInfo:
    def __init__(self, name, categories, app_id="x.desktop"):
        self.name, self.categories, self.app_id = name, categories, app_id

    def get_display_name(self):
        return self.name

    def get_name(self):
        return self.name

    def get_categories(self):
        return self.categories

    def get_id(self):
        return self.app_id


class FakePlayer:
    def __init__(self):
        self.calls = []

    def play(self, piece, mon, ctx, on_done=None):
        self.calls.append((piece, mon, ctx))
        return True


class LaunchWiring(unittest.TestCase):
    def test_launch_info(self):
        from eva_desk.launcher import launch_info
        self.assertEqual(launch_info(("app", FakeAppInfo("Firefox", "Network;WebBrowser;"))), ("FIREFOX", False))
        self.assertEqual(launch_info(("app", FakeAppInfo("Hades", "Game;ActionGame;"))), ("HADES", True))
        self.assertEqual(launch_info(("app", FakeAppInfo("Gamescope Settings", "Settings;GameTool;"))), ("GAMESCOPE SETTINGS", False))   # a whole category, not a substring
        self.assertEqual(launch_info(("app", FakeAppInfo("Thing", None))), ("THING", False))
        self.assertEqual(launch_info(("app", FakeAppInfo("", ""))), ("APP", False))
        self.assertEqual(launch_info(("cmd", "notify-send hi")), ("NOTIFY-SEND", False))
        self.assertEqual(launch_info(("cmd", "  ")), ("RUN", False))
        self.assertEqual(launch_info(("web", "unit 01")), ("SEARCH", False))

    def launcher(self):
        from eva_desk import launcher as L
        lau = L.Launcher.__new__(L.Launcher)
        lau.cfg, lau.hypr, lau.counts, lau.gdk_monitor, lau.played = config.load("/nonexistent"), FakeHypr(), {}, "MON", []
        lau.app = type("A", (), {"play_launch": lambda s, name, game, mon: lau.played.append((name, game, mon))})()
        lau._save_counts = lau.hide = lau._arm_idle = lambda: None
        return lau

    def test_enter_plays_and_shift_enter_does_not(self):
        from eva_desk import gtkutil  # noqa: F401
        from gi.repository import Gdk
        lau = self.launcher()
        lau.results, lau.sel = [("cmd", "true")], 0
        lau._key(None, Gdk.KEY_Return, 0, Gdk.ModifierType(0))
        self.assertEqual((lau.hypr.execs, lau.played), (["true"], [("TRUE", False, "MON")]))
        lau._key(None, Gdk.KEY_Return, 0, Gdk.ModifierType.SHIFT_MASK)
        self.assertEqual((lau.hypr.execs, lau.played), (["true", "true"], [("TRUE", False, "MON")]))

    def test_a_game_entry_is_flagged(self):
        lau = self.launcher()
        lau._launch(("app", FakeAppInfo("Hades", "Game;", "hades.desktop")))
        self.assertEqual((lau.played, lau.hypr.execs), ([("HADES", True, "MON")], ["gtk-launch hades.desktop"]))

    def test_without_a_player_it_still_launches(self):
        lau = self.launcher()
        lau.app = object()
        lau._launch(("cmd", "true"))
        self.assertEqual(lau.hypr.execs, ["true"])

    def app(self):
        from eva_desk.app import App
        app = App.__new__(App)
        app.cfg, app.hypr, app.motion, app.stages = config.load("/nonexistent"), FakeHypr(), FakePlayer(), {}
        app.hypr.state = {"activeworkspace": {"id": 2}}
        app.focused_gdk = lambda: "FOCUSED"
        return app

    def test_the_default_is_on(self):
        self.assertIs(config.load("/nonexistent")["motion"]["launch"], True)

    def test_play_launch_picks_the_piece(self):
        from eva_desk.motion.seq.card import Card
        from eva_desk.motion.seq.shaft import Shaft
        app = self.app()
        self.assertTrue(app.play_launch("FIREFOX", False, "MON"))
        self.assertTrue(app.play_launch("HADES", True, None))
        (p1, m1, c1), (p2, m2, c2) = app.motion.calls
        self.assertIsInstance(p1, Card)
        self.assertIsInstance(p2, Shaft)
        self.assertEqual((m1, m2), ("MON", "FOCUSED"))
        self.assertEqual((c1["app"], c1["workspace"]), ("FIREFOX", 2))
        self.assertRegex(c1["clock"], r"^\d\d:\d\d$")

    def test_switched_off_or_unavailable(self):
        app = self.app()
        app.cfg["motion"]["launch"] = False
        self.assertFalse(app.play_launch("X", False, "MON"))
        self.assertEqual(app.motion.calls, [])
        app.motion = None
        app.cfg["motion"]["launch"] = True
        self.assertFalse(app.play_launch("X", False, "MON"))

    def test_the_play_command(self):
        app = self.app()
        self.assertEqual(app.command("play card"), "ok")
        self.assertEqual(app.command("play shaft STEAM"), "ok")
        self.assertEqual(app.motion.calls[1][2]["app"], "STEAM")
        self.assertEqual(app.command("play nope"), "unknown piece: nope (card, shaft)")
        self.assertEqual(app.command("play"), "play: card | shaft")
        app.motion = None
        self.assertEqual(app.command("play card"), "motion is not available")

    def test_hyprland_plays_no_animation_of_its_own_over_it(self):
        self.assertIn("|pulse|motion|panel-", (ROOT / "hypr" / "eva.lua").read_text())
```

- [ ] **Step 2: Run them and see them fail**

Run: `python3 -m unittest tests.test_motion.LaunchWiring -v`
Expected: `ImportError: cannot import name 'launch_info' from 'eva_desk.launcher'`

- [ ] **Step 3: `config.py` and `launcher.py`**

- `DEFAULTS["motion"]`, after `"launcher"`, with a comment in the file's style.
- `launch_info`: an app's display name (or its name) in capitals, `APP` when both are empty; a game when `Game` is one of the `;`-separated entries of `get_categories()`. A command is its first word in capitals, `RUN` when blank. A search is `SEARCH`.
- `show` remembers `self.gdk_monitor`.
- `_key`: Enter passes `plain=bool(mods & Gdk.ModifierType.SHIFT_MASK)`.
- `_launch(item, plain=False)`: fetch the launch context only in the one branch that uses it (an app without an id), so the method runs with no display. After `self.hide()`, unless `plain`, call the app's `play_launch(*launch_info(item), self.gdk_monitor)` if the app has one.

- [ ] **Step 4: `app.py`**

- In `do_activate`, next to the overlays and inside its own `try`: `self.motion = SequencePlayer(self) if motion.available() else None`, with one log line when it is not available (`eva-desk: motion needs GTK 4.10 or newer`).
- `play_launch`: `False` when `self.motion` is `None` or `[motion] launch` is off. Otherwise `Shaft()` for a game and `Card()` for anything else, `ctx = {"app": name, "workspace": <id of hypr's activeworkspace, or None>, "clock": time.strftime("%H:%M")}`, played on `gdk_monitor or self.focused_gdk()`.
- `command`: `play NAME [TEXT]` plays that piece on the focused monitor with `TEXT` (default `EVA-DESK`) as the app, whatever `[motion] launch` says. The four replies are the ones in `test_the_play_command`.

- [ ] **Step 5: The rest**

- `hypr/eva.lua`: the `no_anim` layer rule's namespace list gains `motion` after `pulse`.
- `bin/eva-ctl` docstring: `eva-ctl play card|shaft [NAME]   play a launch sequence on the focused monitor (to try it)`.
- `config/eva.example.toml`: a `[motion]` section after `[launcher]`: `launch = true`, commented `Enter in the launcher plays a sequence: the card for apps, the shaft for games. Shift+Enter launches without it.`
- `packaging/PKGBUILD` and `.SRCINFO`: `ffmpeg` as an optional dependency, `mp4 previews from eva-desk --render-motion`.
- `README.md`: a paragraph after the Launcher one (what plays on Enter, that a click skips it, that typing goes to the new window, Shift+Enter, `[motion] launch`); `eva-desk --render-motion DIR` in the Development block; `ffmpeg` among the optional dependencies, and "GTK 4.10 or newer for the motion sequences" with the required ones. Plain voice.
- The 2026-10-06 spec: one line under the heading "Launch sequence": `Replaced by 2026-10-13-motion-graphics-design.md: the launch is drawn in code, not cut from key frames.`

- [ ] **Step 6: Run everything**

Run: `python3 -m unittest discover -s tests`
Expected: `OK`, every earlier test included

Run: `luac -p hypr/eva.lua`
Expected: no output

---

### Task 8: Verify and hand over

**Files:** none

- [ ] **Step 1: Render both sequences at the two monitor shapes**

Run, from the worktree root, with a scratch directory of your own:
`PYTHONPATH=. python3 -m eva_desk --render-motion "$SCRATCH/wide" --size 3440x1440 --fps 60`
`PYTHONPATH=. python3 -m eva_desk --render-motion "$SCRATCH/tall" --size 1080x1920 --fps 60`
Expected: `card.png`, `shaft.png`, and with `ffmpeg` `card.mp4`, `shaft.mp4` in each; one line per piece with its timings.

- [ ] **Step 2: Read the four contact sheets**

Against the spec's two storyboards, frame by frame. On the tall ones: nothing off the frame, the name fits, the plates and the shaft still cover it.

- [ ] **Step 3: Check the cost**

The `build` time `render_motion` prints is the Python side of one live frame. At 3440x1440 it should be under 2 ms for the card and under 4 ms for the shaft. If the shaft is over, widen its wall-light bands before anything else.

- [ ] **Step 4: The standing checks**

Run: `python3 -m unittest discover -s tests`
Expected: `OK`
Run: `PYTHONPATH=. python3 -m eva_desk --render "$SCRATCH/render"` and read `motion_card.png` and `motion_shaft.png`.
Verify the Hyprland side with the worktree's file: point a scratch copy of the Hyprland config at this worktree's `hypr/eva.lua` instead of the installed one, then `HL_VERIFY=1 timeout 20 Hyprland --verify-config -c "$SCRATCH/hyprland.lua"`.
Expected: the config verifies.

- [ ] **Step 5: Hand over**

Report: the files touched, the checks that ran and their results, the four sheets and the mp4s, and what only a live run can show:

- the frame pacing of both sequences on a high-refresh monitor;
- that the keyboard stays with the new window while a sequence plays, and that a click skips it;
- Shift+Enter;
- that a game entry (one whose `.desktop` file lists `Game`) gets the shaft;
- that Hyprland plays no layer animation of its own over the `eva-motion` surface.
