# Motion graphics, plan 2: boot, wake, berserk and the track card

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Four more sequences on the engine of plan 1, each played by the daemon when its event happens: boot at the first start in a Hyprland session, wake when the lock screen closes or the machine resumes, berserk when sustained load crosses the limit, and a card in a corner when a new track starts.

**Architecture:** Each sequence is a `Piece` drawn through the kit, like the card and the shaft. `triggers.py` holds the decisions as pure functions and small state machines (boot once per session, what counts as a game, the track de-duplication, the locker's life), so they are tested with plain values. The daemon gets one player per monitor (`Players`), because boot and wake play on every main monitor at once, and a rule for what may interrupt what.

**Tech Stack:** as plan 1: Python 3.11, PyGObject (GTK 4, Gsk, Pango), pycairo, gtk4-layer-shell; `unittest`; `playerctl` (already optional) for the track card; logind on the system bus for resume.

**Spec:** `docs/superpowers/specs/2026-10-13-motion-graphics-design.md`, build step 2: the sections "Boot", "Wake", "Berserk", "Track change", "Triggers and sources", and the parts of "Pause rules and cost", "Configuration", "Error handling" and "Testing" that concern them. Standby, the living wallpaper and the side wall follow in plans 3 to 5.

## Global Constraints

- A linked install runs the daemon straight from the main checkout, so the main checkout is live. Work only in the worktree `.worktrees/motion-graphics`. Never edit the main checkout, never run `eva-ctl` against the live session, never open a window on it, never kill a process by pattern.
- No commits, merges or pushes unless the owner asks. A task is done when its tests pass; say which files it touched.
- Verification is offline: `python3 -m unittest discover -s tests`, `eva-desk --render DIR`, `eva-desk --render-motion DIR`. Read the PNGs; a render that runs is not a render that looks right.
- No test spawns a process, talks to a bus, or reads the machine's `eva.toml`: the locker, the timers and Hyprland are fakes.
- Colours are theme roles through `draw.py` (`d.INK`, `d.BONE`, `d.BONE2`, `d.BONE3`, `d.GOLD`, `d.LED`, `d.CLARET`, `d.RED`, `d.col("ink4")`, `d.col("ink5")`, `d.col("ink_deep")`), never hex in modules. Fonts are `d.F_DISPLAY` at `d.DISPLAY_WEIGHT` ("mincho" below) and `d.F_META` ("mono").
- A piece never calls `random` and never reads the clock or the system: time arrives as `t`, everything else in `ctx`. Every input has a default, so a piece paints with an empty `ctx`.
- The kit's two rules (top of `kit.py`): no path nodes, and no glyphs under a scale that changes from frame to frame (such type is a `kit.stamp`). A shape that is neither a rectangle nor a parallelogram is a picture set once (`kit.hexagon`).
- No full-screen flash: no frame fills the screen with `bone`, `gold` or `led`.
- All sizes are design px. A piece lays out from `kit.W` by `kit.H`; the numbers in the tables below are for a 1720x720 frame and say what they are anchored to.
- Sequences never take the keyboard. Berserk and the track card never take the pointer either (`covers = False`).
- The repo is public: plain voice in README and comments, nothing about private setups.
- Follow the code around you: a module docstring, long lines, short `# why` comments, `unittest`.

## Review Focus

1. A title or artist that is very long, empty, right to left, or all emoji (`"X" * 300`, `""`, `"مرحبا بالعالم"`, `"🦊🦊🦊"`): the card keeps its width between 320 and 640, the type is cut with an ellipsis inside its padding, nothing raises (Task 1 `test_type_can_be_cut_to_a_width`; Task 5 `test_the_card_is_as_wide_as_its_type_within_limits`, `test_odd_titles`).
2. Two events at once on one monitor (a track change during berserk, a launch during the track card, a track change under a launch): what covers takes the place of anything, berserk outranks the track card, the loser is dropped, nothing stays on screen (Task 6 `test_what_may_take_the_place_of_what`; Task 7 `test_what_outranks_what_on_one_monitor`).
3. A locker that comes straight back or never held the screen (not installed, `loginctl lock-session`, already locked, crashed): no cover stays up and no sequence plays (Task 6 `test_the_locker`; Task 9 `test_a_locker_that_comes_straight_back`, `test_a_locker_that_dies`).
4. A burst of metadata (title, then artist; a pause and resume; the player restarting on the same track; the track that was playing when the daemon started): one card per new track, none for the rest (Task 6 `test_track_changes`).
5. Nothing to play on, or somewhere it must not play (no main monitor known yet at boot, a fullscreen window on the monitor, a game open on a hidden workspace, the launcher or the power menu up): nothing plays and nothing raises (Task 6 `test_a_game_is_open_wherever_its_window_is`, `test_fullscreen_monitors`; Task 8 `test_boot_plays_once_per_session`, `test_berserk_and_the_track_card_stay_out_of_the_way`).

## File structure

| File | Responsibility |
|---|---|
| `eva_desk/motion/kit.py` (modify) | `tile`, `scanlines`, `hexagon`, `hex_cells`, `lamp`, `brackets`, `block`; `text` and `measure` cut to a width |
| `eva_desk/motion/seq/boot.py` (create) | `Boot` and `lines()` |
| `eva_desk/motion/seq/wake.py` (create) | `Wake` |
| `eva_desk/motion/seq/berserk.py` (create) | `Berserk` |
| `eva_desk/motion/seq/track.py` (create) | `Track` and `card_width()` |
| `eva_desk/motion/triggers.py` (create) | the decisions: `boot_due`, `boot_inputs`, `game_open`, `fullscreen_monitors`, `track_monitor`, `outranks`, `TrackWatch`, `LockWatch`. No GTK |
| `eva_desk/motion/player.py` (modify) | held pieces (`play(held=True)`, `start()`), and `Players`: one player per monitor |
| `eva_desk/motion/__init__.py` (modify) | `Piece.rank`; the registry gains the four pieces |
| `eva_desk/motion/render.py` (modify) | `fixture_ctx()` carries the new pieces' inputs |
| `eva_desk/app.py` (modify) | owns `Players`; boot at start, the berserk edge, the track watch, `lock()`, resume; `play` for all six, `lock` |
| `eva_desk/overlays.py` (modify) | the power menu's LOCK goes through `App.lock()` |
| `eva_desk/config.py`, `config/eva.example.toml` (modify) | `[motion] boot, wake, berserk, track, track_corner` |
| `bin/eva-ctl`, `README.md`, the spec (modify) | the commands, the features, what changed in the design |
| `tests/test_motion.py` (modify) | every test of this plan |

The approved animated mock-ups are the reference for anything a table below leaves open. They are local and git-ignored, in the main checkout: `.superpowers/brainstorm/46040-1791895389/content/mg-events.js` (the four sequences) and `mg-kit.js` (the helpers). If they are gone, the tables below are complete. Mock-up names map to roles like this: `lilac` is `d.RED`, `ink5` is `d.col("ink5")`, `deep` is `d.col("ink_deep")`, `easeOut` is `cubic_out`, `easeIn` is `cubic_in`, `back` is `back_out`, `hash` is `noise`.

Two things in this plan go past the letter of the spec, and the spec is updated in Task 10 to say them:

- **The wake cover goes up under the lock screen.** The spec says the sequence plays when the locker exits. A lock screen fades out onto the desk, so a cover that only appears after the exit would show the desk, then black, then the desk again. Instead, one second after the locker has started (it holds the screen by then, and has taken its screenshot if it uses one), the wake sequence is put up on its first frame, an ink cover, and held there. When the locker exits it plays. A locker that exits before that second, or with an error, gets no cover and no sequence.
- **One player per monitor, and a rank.** The spec's player plays one piece on one monitor. Boot and wake play on every main monitor at once, and berserk and the track card can fall on the same corner, so the daemon keeps a player for each monitor and a rule: a piece that covers takes the place of anything, berserk outranks the track card, and what is outranked is dropped.

## Changed during execution

The tasks below are the plan as it was written. The final review changed these things, each fixed with a test seen failing first; the code, `tests/test_motion.py` and the spec are the truth where they differ from a task:

- **The lock path was redesigned (Tasks 6 and 9).** As planned, the daemon ran the locker as its own child and judged the lock by that child. One failed Hyprland request could then leave it answering `already locked` to every later lock, and the cover's timing rested on a guess. Now the daemon only watches: `LockWatch.tick(now, locked)` follows what Hyprland says (`j/locked`), `App._watch_lock` asks every two seconds (twice a second while the cover is up), and `App.lock()` hands `[power] lock` to Hyprland as it always did and never refuses. There is no `_spawn`, `_every`, `locker` or `_watch_locker`. The wake sequence therefore follows any lock screen, not only one started with `eva-ctl lock`, and `eva-ctl lock` runs the command itself when the daemon cannot be reached. The cover may be up only while Hyprland says the session is locked.
- **`Players.playing(monitor)`**: the watch puts a cover back on a monitor that went away and returned.
- **`TrackWatch`**: `begin(now)` starts the quiet period when the reports begin; an artist that arrives late is the same track; a track announced in the last two minutes is not announced again; two cards are at least ten seconds apart (`pending` asks the caller to try again).
- **Boot**: not marked while no main monitor is known (each refresh tries again for twenty seconds); never over a game or a fullscreen window; the gate draws each part of the card once (`_card(..., part)`), and a cell's strength is in its picture, so a gate frame costs about what a whole one does; the brackets and the tag end at 2.58.
- **The bar** is told of the player and the load only when its own switches ask (`App._bar_state`); the sampler's timer survives a Hyprland request that fails.
- **Small**: berserk's line reads `0 S` for a limit of no seconds; the system bus connection does not end the daemon when it closes, and is only made with `[motion] wake` on.

---

### Task 1: The kit: tiles, hexagons, lamps, brackets, blocks, type cut to a width

**Files:**
- Modify: `eva_desk/motion/kit.py`
- Test: `tests/test_motion.py` (`KitTest`)

**Interfaces:**
- Consumes: the kit of plan 1 (`_layout`, `_stamp`, the stamp store, `rect`, `clip`, `opacity`).
- Produces:

```python
# eva_desk/motion/kit.py
def hex_cells(x0, y0, x1, y1, r, ox=0.0, oy=0.0) -> list[tuple[float, float, int, int]]
    # (cx, cy, col, row) of the pointy-top cells of radius r that cover the box and one ring more, the lattice shifted by (ox, oy)
class Kit:
    def tile(self, x, y, w, h, tw, th)                 # context manager: what is painted in the cell (x, y, tw, th) repeats over the box (x, y, w, h)
    def scanlines(self, x, y, w, h, alpha=0.04)        # a bone line of 1 px every third px
    def hexagon(self, cx, cy, r, colour, alpha=1.0, width=2.0, fill=0.0)
        # a pointy-top outline of radius r, and inside it the colour at `fill` of the line's strength; a picture, set once
    def lamp(self, x, y, size, colour)                 # a square lamp and its halo (the square 3 px larger each way, at 22 %)
    def brackets(self, x0, y0, x1, y1, leg, colour, width=2.0, alpha=1.0)     # the four corners of a box, each two legs, the stroke centred on the edge
    def block(self, x, y, w, h, colour, shadow=None, off=7.0, alpha=1.0)      # a slab over its hard shadow, the shadow `off` px right and down
    def text(self, string, x, y, size, colour, face="meta", spacing=0.0, align="left", alpha=1.0, width=None) -> float
    def measure(self, string, size, face="meta", spacing=0.0, width=None) -> float
        # with `width`, the type is cut to it with an ellipsis (Pango does the cutting, so any script is cut properly)
```

- [ ] **Step 1: Write the failing tests** (in `KitTest`)

```python
    def test_tile_repeats_what_is_painted_in_one_cell(self):
        from eva_desk import draw as d

        def dots(k):
            with k.tile(100, 100, 80, 2, 8, 2):                   # ten dots, 8 px apart
                k.rect(100, 100, 2, 2, d.BONE)
        f = self.frame(dots)
        self.assertEqual([alpha(f, x, 101) > 0 for x in (101, 105, 109, 173, 177, 181)], [True, False, True, True, False, False])
        f = self.frame(lambda k: k.scanlines(0, 0, 400, 300, 0.5))
        self.assertEqual([alpha(f, 50, y) > 0 for y in range(6)], [True, False, False, True, False, False])
        self.assertEqual((alpha(f, 399, 0) > 0, alpha(f, 401, 0), alpha(f, 50, 300)), (True, 0, 0))
        self.assertEqual(pink(f), 0)

    def test_hexagon_is_a_picture_of_an_outline(self):
        from eva_desk import draw as d
        from eva_desk.motion import Piece, render

        class P(Piece):
            length = 1.0

            def __init__(self, fill):
                self.fill = fill

            def paint(self, kit, t, ctx):
                kit.hexagon(400, 300, 58, d.CLARET, width=2, fill=self.fill)
                kit.hexagon(600, 300, 58, d.CLARET, alpha=0.5, width=2, fill=self.fill)

        def lit(f, x, y):                                          # the strongest of the pixels around a point
            return max(alpha(f, x + dx, y + dy) for dx in (-1, 0, 1) for dy in (-1, 0, 1))
        f = render.frame(P(0.0), 0, 1720, 720, {})
        self.assertGreater(lit(f, 400, 242), 150)                  # a point at the top: 58 above the centre
        self.assertGreater(lit(f, 450, 300), 150)                  # a flat side: 58 * cos 30 = 50.2 out
        self.assertEqual((alpha(f, 400, 300), alpha(f, 470, 300)), (0, 0))     # hollow, and nothing outside
        self.assertTrue(60 < lit(f, 650, 300) < 140)               # the second one at half strength
        g = render.frame(P(0.4), 0, 1720, 720, {})
        self.assertTrue(80 < alpha(g, 400, 300) < 125)             # filled at 0.4 of its line
        widths = texture_widths(render.build(P(0.0), 0, 1720, 720, {}))
        self.assertEqual((len(widths), len(set(widths))), (2, 1))  # pictures of one picture: no path for GTK to rasterise every frame

    def test_hex_cells_cover_a_box(self):
        from eva_desk.motion.kit import hex_cells
        cells = hex_cells(0, 0, 1000, 500, 58)
        dx, dy, rows = math.sqrt(3) * 58, 1.5 * 58, {}
        for cx, cy, col, row in cells:
            rows.setdefault(row, []).append(cx)
            self.assertAlmostEqual(cy, row * dy)
        self.assertAlmostEqual(rows[0][1] - rows[0][0], dx)                    # neighbours are one cell apart
        self.assertAlmostEqual((rows[1][0] - rows[0][0]) % dx, dx / 2)         # every other row sits half a cell over
        self.assertTrue(min(c[0] for c in cells) <= 0 and max(c[0] for c in cells) >= 1000)     # past every edge of the box
        self.assertTrue(min(c[1] for c in cells) <= 0 and max(c[1] for c in cells) >= 500)
        self.assertEqual(len(cells), len(set(cells)))
        self.assertAlmostEqual(hex_cells(0, 0, 10, 10, 58, ox=7, oy=5)[0][1] % dy, 5)           # the lattice can be shifted

    def test_lamp_brackets_and_block(self):
        from eva_desk import draw as d
        f = self.frame(lambda k: (k.lamp(100, 100, 10, d.GOLD), k.brackets(300, 100, 500, 300, 30, d.BONE, 4),
                                  k.block(600, 100, 200, 100, d.LED, shadow=d.BONE, off=8)))
        self.assertEqual(px(f, 105, 105), GOLD + (255,))                       # the lamp
        self.assertTrue(20 < alpha(f, 98, 105) < 90)                           # its halo, 3 px out
        self.assertEqual(alpha(f, 95, 105), 0)
        self.assertEqual((alpha(f, 310, 101), alpha(f, 301, 120), alpha(f, 340, 101), alpha(f, 400, 200)), (255, 255, 0, 0))     # a corner: two legs of 30
        self.assertEqual((alpha(f, 490, 299), alpha(f, 499, 280)), (255, 255))                                                 # and the opposite one
        self.assertEqual((px(f, 804, 150)[:3], px(f, 700, 204)[:3]), (BONE, BONE))                                             # the hard shadow, right and under
        self.assertNotEqual(px(f, 700, 150)[:3], BONE)

    def test_type_can_be_cut_to_a_width(self):
        from eva_desk import draw as d
        long, got = "A VERY LONG TITLE THAT CANNOT FIT IN THE CARD AT ALL", {}

        def fn(k):
            got["full"] = k.measure(long, 38, face="display")
            got["cut"] = k.measure(long, 38, face="display", width=300)
            got["short"] = (k.measure("EVA", 38, face="display"), k.measure("EVA", 38, face="display", width=300))
            got["drawn"] = k.text(long, 100, 300, 38, d.BONE, face="display", width=300)
            k.text("مرحبا بالعالم " * 6, 100, 500, 38, d.BONE, face="display", width=300)
        f = self.frame(fn)
        self.assertGreater(got["full"], 600)
        self.assertTrue(200 < got["cut"] <= 300)
        self.assertEqual(got["short"][0], got["short"][1])                     # what fits is left alone
        self.assertEqual(got["drawn"], got["cut"])
        for rows in (range(250, 320, 3), range(450, 520, 3)):                  # nothing past the width, in either script
            self.assertFalse(any(alpha(f, x, y) for x in range(404, 900, 3) for y in rows))
```

- [ ] **Step 2: Run them and see them fail**

Run: `python3 -m unittest tests.test_motion.KitTest`
Expected: five errors, each `AttributeError` (`'Kit' object has no attribute 'tile'`, `'hexagon'`, `'lamp'`), `ImportError: cannot import name 'hex_cells'`, or `TypeError: ... unexpected keyword argument 'width'`

- [ ] **Step 3: Write the kit's new pieces**

What the signatures leave open:

- `tile` is `snap.push_repeat(box, cell)` around what the caller paints, popped on exit. `scanlines` is a tile of 3 px rows with one `d.BONE` rect of 1 px at `alpha`.
- `hexagon` is a picture kept in the stamp store, as stamps are. Move what `_stamp` does with cairo into `_picture(store, key, box, fine, draw) -> (texture, x, y, w, h)`, where `draw(cr)` paints in design px inside `box`, and call it from both. The hexagon's picture is drawn once with a cairo path (points at 30 + 60 i degrees), stroked at `width` in the colour and filled at `fill`; its box is the hexagon grown by the line width and one clear px. `alpha` goes on with `opacity`. Its key carries `r`, `width`, `fill` and the colour.
- `hex_cells`: columns are `sqrt(3) * r` apart, rows `1.5 * r`, odd rows half a column over; rows run from `floor((y0 - oy) / dy) - 1` to `ceil((y1 - oy) / dy) + 1` and columns likewise, as in the mock-up's `hexCells`.
- `brackets`: per corner two rects, each `width` thick and centred on the edge, the corner itself covered once.
- `text` and `measure` with `width`: the layout cache key gains the width; such a layout has `set_width(width * Pango.SCALE)` and `set_ellipsize(Pango.EllipsizeMode.END)`.

- [ ] **Step 4: Run the tests and see them pass**

Run: `python3 -m unittest discover -s tests`
Expected: `OK` (189 tests)

---

### Task 2: Boot

**Files:**
- Create: `eva_desk/motion/seq/boot.py`
- Modify: `eva_desk/motion/__init__.py` (the registry), `eva_desk/motion/render.py` (`fixture_ctx`)
- Test: `tests/test_motion.py` (`BootTest`, and the registry tests)

**Interfaces:**
- Consumes: Task 1's `hexagon`, `hex_cells`, `tile`, `lamp`, `brackets`; plan 1's `segbar`, `hazard`, `clip`, `transform`, `opacity`, `text`.
- Produces:

```python
# eva_desk/motion/seq/boot.py
SEAM = 0.62            # the gate opens along this share of the height
def lines(ctx) -> list[tuple[str, str | None]]        # the six check lines, each with its status (None for the header)
class Boot(Piece): name, length, covers, still = "boot", 2.6, True, 1.6

# eva_desk/motion/__init__.py: pieces() returns card, shaft, boot, wake, berserk, track, in that order (each added by its task)
# eva_desk/motion/render.py: fixture_ctx() also carries
#   "outputs": ["3440×1440", "1080×1920"], "hyprland": "0.56", "lua": True, "net": "lan",
#   "load": "CPU 97%", "seconds": 30, "title": "Walking on a Dream", "artist": "Empire of the Sun", "corner": "bottom-left"
```

Inputs, all optional: `ctx["outputs"]` (a list of `"WxH"` strings), `ctx["hyprland"]` (the version, `"0.56"`), `ctx["lua"]` (bool, default `True`), `ctx["net"]` (`lan`, `wifi`, `vpn` or `none`, default `lan`), `ctx["bar"]` (the bar's height in the surface's own px; without it the bar is taken as 28 design px, its size on the main monitor).

`lines(ctx)`:

| | Label | Status |
|---|---|---|
| 0 | `EVA-DESK ・ 起動シーケンス` | none: the header |
| 1 | `MAGI-1  MELCHIOR   CPU` | `OK` |
| 2 | `MAGI-2  BALTHASAR  RAM` | `OK` |
| 3 | `MAGI-3  CASPER     ` + the net kind in capitals | `OK`, or `DOWN` when the kind is `none` |
| 4 | `OUTPUT  ` + up to three outputs joined by ` ・ ` (`NONE` when there are none) | the count and ` UP` |
| 5 | `HYPRLAND ` + the version + ` ・ LUA` or ` ・ LEGACY` | `LINKED` |

The picture, on a 1720x720 frame. `seam = round(SEAM * H)`, `oy = seam - 446` (the title block rides the seam, so the gate always opens through the digits), `bar` as above.

| What | When | Geometry |
|---|---|---|
| Ground | always | ink over the whole frame |
| The field | from 0.55, on twos | cells of `hex_cells(0.40 W, 0, W, H, 58)` whose centre is right of `0.40 W`. For a cell at distance `d = hypot(cx - 0.72 W, cy - 0.48 H) / (0.45 W)`: `u = seg(twos(t), 0.55 + 0.55 d, 0.72 + 0.55 d)`; nothing at 0, then `k = 0.4` while `u < 0.6`, then `k = 1`. `hexagon(cx, cy, 55, claret, alpha=0.6 k, width=2)`, filled at `0.22 / 0.6` where `noise(col, row) > 0.84` |
| Check lines | line `i` types on over `s .. s + 0.07`, `s = 0.04 + 0.085 i` | baseline `84 + 25 i`, at x 64. Header: mincho 17, spacing 1, bone. The rest: mono 13.5, spacing 2, `bone2`. Typed = the first `ceil(len * progress)` characters |
| Their dots | `s + 0.07 .. s + 0.16` | 2x2 squares in `ink5` every 8 px from 10 px after the full label to x 530, 5 px above the baseline; `floor(n * progress)` of them (one `tile`) |
| Their status | from `s + 0.18` | `lamp(544, baseline - 10, 9, gold)` and the status at x 562: mono 13.5, spacing 2, gold |
| | from 1.15 | all the check lines at 42 % |
| The bar | `p = seg(twos(t), 0.04, 1.12)` | `segbar(64, H - 46, W - 198, 10, p, gold, 62)`; the counter `round(100 p)` as three digits, right-aligned at `W - 64`, baseline `H - 36`, mono 15, spacing 2, gold at 100 and `bone2` before; `hazard(0, H - 14, W, 14, claret, period=40)` |
| `EPISODE` | types on 1.15 .. 1.30 | x 150, baseline `262 + oy`, mono 21, spacing 8, `d.RED` |
| `00` | digit `i` rolls up over `1.15 + 0.07 i .. 1.37 + 0.07 i`, cubic out | mincho 330, bone, baseline `560 + oy + (1 - u) * 297`, the first at x 136, the next `w - 18` further; each inside a clip from 16 px above its cap height (`0.74 * 330`) to 18 px under the baseline |
| The plate | opens over 1.36 .. 1.48 in three steps | a bone slab at (150, `590 + oy`), 56 high, as wide as `第零話 ・ 起動` in mincho 38 plus 44; the words in ink at x 172, baseline `632 + oy`, once it is fully open |
| The gate | `open = smooth(seg(t, 1.95, 2.35))` | everything above is drawn twice, cut at the seam: the upper part moved up by `(seam + 14) * open`, the lower part down by `(H - seam + 14) * open`. While `open > 0` each part carries a 12 px `hazard(claret, ink, period=30)` along its cut edge. A 4 px bone line on the seam from 1.95 to 1.99. While `open` is 0 it is drawn once |
| Brackets | 2.30 .. 2.58 | `brackets(10, bar + 10, W - 10, H - 10, 34, bone, 3)`, scaled about the centre by `1.05 - 0.05 * back_out(seg(t, 2.30, 2.48))` |
| The tag | opens over 2.36 .. 2.44 in three steps, holds to 2.58 | a gold slab 30 high at y `bar + 18`, its right edge at `W - 24`, as wide as `全系統正常 ・ ALL GREEN` in mincho 17 (spacing 1) plus 28; the words in ink, 14 px in, baseline `bar + 39.5`, once it is fully open |

`prepare` makes the two hexagon pictures (plain and filled).

- [ ] **Step 1: Write the failing tests**

In `RenderTest`, the registry now names all six (this test stays red until Task 5; each task adds its piece):

```python
    def test_registry(self):
        from eva_desk import motion
        self.assertEqual(list(motion.pieces()), ["card", "shaft", "boot", "wake", "berserk", "track"])
        self.assertEqual({n: p().name for n, p in motion.pieces().items()}, {n: n for n in motion.pieces()})
```

In `test_stills_for_the_standing_render`, the expected names become `sorted(f"motion_{n}.png" for n in motion.pieces())`. In `test_prepare_makes_the_stamps_before_the_first_frame`, replace `self.assertGreater(made, 0, name)` with `self.assertEqual(made > 0, name in ("card", "shaft", "boot", "berserk"), name)`.

```python
class BootTest(unittest.TestCase):
    def setUp(self):
        from eva_desk.motion import render
        from eva_desk.motion.seq.boot import Boot
        self.render, self.boot = render, Boot()

    def at(self, t, w=1720, h=720, **ctx):
        return self.render.frame(self.boot, t, w, h, dict(self.render.fixture_ctx(), **ctx))

    def test_identity(self):
        self.assertEqual((self.boot.name, self.boot.length, self.boot.covers), ("boot", 2.6, True))

    def test_it_covers_the_desk_until_the_gate_opens(self):
        for t in (0.0, 0.5, 1.2, 1.94):
            self.assertEqual(set(grid(self.at(t))), {255}, t)

    def test_the_lines_carry_what_is_read_live(self):
        from eva_desk.motion.seq import boot
        got = boot.lines({"outputs": ["3440×1440", "1080×1920"], "hyprland": "0.56", "lua": True, "net": "wifi"})
        self.assertEqual(len(got), 6)
        self.assertEqual(got[0], ("EVA-DESK ・ 起動シーケンス", None))
        self.assertEqual(got[3], ("MAGI-3  CASPER     WIFI", "OK"))
        self.assertEqual(got[4], ("OUTPUT  3440×1440 ・ 1080×1920", "2 UP"))
        self.assertEqual(got[5], ("HYPRLAND 0.56 ・ LUA", "LINKED"))
        bare = boot.lines({})
        self.assertEqual((bare[3], bare[4], bare[5]), (("MAGI-3  CASPER     LAN", "OK"), ("OUTPUT  NONE", "0 UP"), ("HYPRLAND  ・ LUA", "LINKED")))
        self.assertEqual(boot.lines({"net": "none", "lua": False, "outputs": ["a", "b", "c", "d"]})[3:],
                         [("MAGI-3  CASPER     NONE", "DOWN"), ("OUTPUT  a ・ b ・ c", "4 UP"), ("HYPRLAND  ・ LEGACY", "LINKED")])

    def test_the_field_and_the_bar_run_on_twos(self):
        self.assertTrue(same(self.at(0.84), self.at(0.90)))                    # the same twelfth of a second: the same picture
        self.assertFalse(same(self.at(0.90), self.at(0.93)))

    def test_the_gate_opens_along_the_seam(self):
        from eva_desk import draw as d
        claret = tuple(round(255 * c) for c in d.CLARET[2::-1])
        self.assertEqual(px(self.at(1.96), 860, 446)[:3], BONE)                # the seam is marked for a moment
        f = self.at(2.15)                                                      # half open
        self.assertEqual((alpha(f, 860, 100), alpha(f, 860, 400), alpha(f, 860, 660)), (255, 0, 255))
        for y in (210, 596):                                                   # a hazard edge on each part, along the cut
            self.assertTrue(any(px(f, x, y)[:3] == claret for x in range(0, 1720, 3)), y)

    def test_it_ends_on_the_desk_under_brackets_and_a_tag(self):
        f = self.at(2.5)
        self.assertEqual(alpha(f, 860, 360), 0)
        self.assertEqual(px(f, 20, 38), BONE + (255,))                         # a bracket at the top left, under the bar
        self.assertEqual(px(f, 1690, 60)[:3], GOLD)                            # the tag, in its padding
        self.assertEqual(set(grid(self.at(2.6))), {0})

    def test_never_a_bright_screen(self):
        points = [(x, y) for y in range(10, 720, 20) for x in range(10, 1720, 20)]
        for t in (0.3, 1.0, 1.5, 1.9, 2.2):
            f = self.at(t)
            bright = sum(1 for x, y in points if alpha(f, x, y) and min(px(f, x, y)[:3]) > 200)
            self.assertLess(bright / len(points), 0.2, t)

    def test_nothing_the_offline_renderer_cannot_draw(self):
        for t in (0.1, 0.6, 1.0, 1.3, 1.6, 2.1, 2.4):
            self.assertEqual(pink(self.at(t)), 0, t)

    def test_other_monitor_shapes_and_missing_inputs(self):
        for w, h in ((3440, 1440), (1080, 1920), (640, 360)):
            self.assertEqual(set(grid(self.at(1.0, w, h))), {255}, (w, h))
        tall = self.at(1.9, 1080, 1920)                                        # the gate opens through the digits on any frame
        self.assertTrue(any(px(tall, x, round(0.62 * 1920))[:3] == BONE for x in range(0, 1080, 2)))
        self.at(1.0, outputs=[], hyprland="", net="none", bar=0)
        self.render.frame(self.boot, 1.0, 1720, 720, {})

    def test_same_frame_twice(self):
        self.assertTrue(same(self.at(1.234), self.at(1.234)))
```

- [ ] **Step 2: Run them and see them fail**

Run: `python3 -m unittest tests.test_motion.BootTest`
Expected: `ModuleNotFoundError: No module named 'eva_desk.motion.seq.boot'`

- [ ] **Step 3: Write `boot.py`, register it, extend `fixture_ctx`**

One function paints the card (ground, field, lines, bar, title); `paint` calls it once, or twice inside `clip` and `transform(dy=...)` while the gate is opening, then adds the seam line, the hazard edges, the brackets and the tag.

- [ ] **Step 4: Run the tests and see them pass**

Run: `python3 -m unittest discover -s tests`
Expected: `FAILED (failures=1)`: only `test_registry`, which waits for the other three pieces

- [ ] **Step 5: Look at it**

Run: `WAYLAND_DISPLAY=eva-none PYTHONPATH=. python3 -m eva_desk --config /nonexistent --render-motion render/plan2 --only boot --size 3440x1440`
Read `render/plan2/boot.png` against the table. Expected in the printed line: built live in under 4 ms a frame.

---

### Task 3: Wake

**Files:**
- Create: `eva_desk/motion/seq/wake.py`
- Modify: `eva_desk/motion/__init__.py` (the registry)
- Test: `tests/test_motion.py` (`WakeTest`)

**Interfaces:**
- Consumes: Task 1's `scanlines`, `lamp`; plan 1's `lines`, `hazard`, `clip`, `text`.
- Produces: `class Wake(Piece): name, length, covers, still = "wake", 1.1, True, 0.4`. No inputs.

The picture, with `cy = H / 2`:

| What | When | Geometry |
|---|---|---|
| The cover | to 1.08; nothing from 1.08 | everything below, inside one clip about the centre: `H * (1 - 0.98 * stepped(seg(t, 0.85, 0.97), 3))` high and `W * (1 - cubic_in(seg(t, 0.97, 1.08)))` wide. Once the fold is complete (from 0.97) the clip is filled bone |
| Ground | always | ink; `scanlines` over the frame at 0.025; `hazard(0, H - 14, W, 14, claret, period=40)` |
| Graph frame | fades in over 0.06 .. 0.16 | in `ink5`: 1 px lines across at `cy - 100` and `cy + 100` from x 64 to `W - 64`, and 1 px uprights 200 high every 86 px from x 64. Labels `+1.0`, ` 0.0`, `-1.0` at x 26, baselines `cy - 88`, `cy + 4`, `cy + 96`: mono 9.5, `bone3` |
| The line | 0 .. 0.12 | gold, 3 high, centred on (`W / 2`, `cy`), `(W - 128) * cubic_out(seg(t, 0, 0.12))` wide |
| Two waves | 0.12 .. 0.62 | `e = smooth(seg(t, 0.12, 0.62))`; `y = cy + 80 (1 - 0.88 e) * a * sin(2π x / 430 - 10 t + ph)`, from x 64 to `W - 64` in steps of 12, as `lines` 3 wide. First `d.RED` with `a = 0.9`, `ph = 0.95 π (1 - e)`, then gold over it with `a = 1`, `ph = 0` |
| Lock | from 0.62 | one bone line, 4 high, from x 64 to `W - 64` on `cy` |
| Type | from 0.08 | `PILOT RE-ENTRY ・ SYNC RATIO` at (66, 96): mono 13, spacing 4, gold. `同期` at (60, 216): mincho 116, bone. Right-aligned at `W - 64` on baseline 216: `%` in mincho 44, and 8 px left of it the ratio with one decimal in mincho 116. The ratio runs `lerp(41.3, 99.9, cubic_out(seg(twos(t), 0.12, 0.62)))` in bone (`%` in `bone2`), and reads `100.0` in gold (with `%`) from 0.62 |
| The plate | opens over 0.62 .. 0.72 in three steps | a bone slab at (64, `cy + 134`), 50 high, `w` wide: `同期完了 ・ SYNCHRONISED` in mincho 30 (spacing 1) plus 44. Once fully open: the words in ink at x 86, baseline `cy + 170`, and `lamp(80 + w, cy + 152, 14, gold)` |

- [ ] **Step 1: Write the failing tests**

```python
class WakeTest(unittest.TestCase):
    def setUp(self):
        from eva_desk.motion import render
        from eva_desk.motion.seq.wake import Wake
        self.render, self.wake = render, Wake()

    def at(self, t, w=1720, h=720):
        return self.render.frame(self.wake, t, w, h, self.render.fixture_ctx())

    def test_identity(self):
        self.assertEqual((self.wake.name, self.wake.length, self.wake.covers), ("wake", 1.1, True))

    def test_it_covers_the_desk_from_its_first_frame(self):
        for t in (0.0, 0.3, 0.7, 0.84):                                        # held under a lock screen, it is frame 0 that shows
            self.assertEqual(set(grid(self.at(t))), {255}, t)

    def test_two_waves_close_on_each_other(self):
        def rows(t):                                                           # how many rows of the graph the gold wave reaches
            f = self.at(t)
            return sum(any(near(px(f, x, y), GOLD) for x in range(64, 1656, 4)) for y in range(250, 470))
        early, late = rows(0.2), rows(0.55)
        self.assertGreater(late, 0)
        self.assertGreater(early, 3 * late)

    def test_they_lock_into_one_bone_line_and_a_plate(self):
        f = self.at(0.7)
        self.assertEqual(px(f, 860, 360)[:3], BONE)
        self.assertEqual(px(f, 70, 500)[:3], BONE)                             # the plate, in its padding
        self.assertNotEqual(px(self.at(0.6), 70, 500)[:3], BONE)

    def test_the_cover_folds_to_a_line_and_the_line_closes(self):
        f = self.at(0.86)                                                      # the first of three steps
        self.assertEqual((alpha(f, 860, 50), alpha(f, 860, 360), alpha(f, 860, 680)), (0, 255, 0))
        f = self.at(1.0)                                                       # a bone line across the middle
        self.assertEqual((px(f, 860, 360), alpha(f, 860, 300)), (BONE + (255,), 0))
        f = self.at(1.06)                                                      # closing on the centre
        self.assertEqual((alpha(f, 200, 360), alpha(f, 860, 360)), (0, 255))
        for t in (1.08, 1.09, 1.1):
            self.assertEqual(set(grid(self.at(t))), {0}, t)

    def test_never_a_bright_screen(self):
        points = [(x, y) for y in range(10, 720, 20) for x in range(10, 1720, 20)]
        for t in (0.1, 0.4, 0.7, 0.9, 1.0):
            f = self.at(t)
            bright = sum(1 for x, y in points if alpha(f, x, y) and min(px(f, x, y)[:3]) > 200)
            self.assertLess(bright / len(points), 0.2, t)

    def test_nothing_the_offline_renderer_cannot_draw(self):
        for t in (0.0, 0.1, 0.3, 0.6, 0.7, 0.9, 1.0):
            self.assertEqual(pink(self.at(t)), 0, t)

    def test_other_monitor_shapes(self):
        for w, h in ((3440, 1440), (1080, 1920), (640, 360)):
            self.assertEqual(set(grid(self.at(0.5, w, h))), {255}, (w, h))
            self.assertEqual(set(grid(self.at(1.09, w, h))), {0}, (w, h))
        self.render.frame(self.wake, 0.5, 1720, 720, {})

    def test_same_frame_twice(self):
        self.assertTrue(same(self.at(0.4321), self.at(0.4321)))
```

- [ ] **Step 2: Run them and see them fail**

Run: `python3 -m unittest tests.test_motion.WakeTest`
Expected: `ModuleNotFoundError: No module named 'eva_desk.motion.seq.wake'`

- [ ] **Step 3: Write `wake.py` and register it**

- [ ] **Step 4: Run the tests and see them pass**

Run: `python3 -m unittest discover -s tests`
Expected: `FAILED (failures=1)`: only `test_registry`

- [ ] **Step 5: Look at it**

Run: `WAYLAND_DISPLAY=eva-none PYTHONPATH=. python3 -m eva_desk --config /nonexistent --render-motion render/plan2 --only wake --size 3440x1440`
Read `render/plan2/wake.png`. Expected: built live in under 3 ms a frame.

---

### Task 4: Berserk

**Files:**
- Create: `eva_desk/motion/seq/berserk.py`
- Modify: `eva_desk/motion/__init__.py` (`Piece.rank`, the registry)
- Test: `tests/test_motion.py` (`BerserkTest`)

**Interfaces:**
- Consumes: Task 1's `block`; plan 1's `hazard`, `stamp`, `text`, `clip`, `transform`, `opacity`.
- Produces:

```python
# eva_desk/motion/__init__.py
class Piece:
    rank = 0         # among pieces that do not cover: the higher one takes the place of the lower (see triggers.outranks)

# eva_desk/motion/seq/berserk.py
class Berserk(Piece): name, length, covers, still, rank = "berserk", 1.3, False, 0.7, 1
```

Inputs: `ctx["load"]` (what is hot, default `"CPU 97%"`), `ctx["seconds"]` (for how long, default 30), `ctx["bar"]` (as in Boot).

The picture, with `top = bar + 3`, `inn = cubic_out(seg(t, 0, 0.22))`, `out = cubic_in(seg(t, 0.98, 1.28))`:

| What | When | Geometry |
|---|---|---|
| Two strips | in over 0 .. 0.22, out over 0.98 .. 1.28 | `hazard(led, ink, period=30)`, 16 high, `W * inn * (1 - out)` wide: one from the left edge at y `top` crawling right (`offset = 46 t`), one from the right edge on the floor (`H - 16`) crawling left |
| Two edge lines | in over 0.10 .. 0.32 (cubic out), out with the strips | `led`, 4 wide, `(H - top) * progress * (1 - out)` long: down the left edge from `top`, up the right edge from the floor |
| The block | `u = seg(t, 0.18, 0.40)`; gone when `stepped(seg(t, 0.95, 1.07), 3)` reaches 1 | `block(40, H - 218, 300, 168, led, shadow=bone, off=9 * cubic_out(u))`, scaled about its centre by `1.3 - 0.3 * back_out(u)`, at 50 % while `u < 0.25`. `暴走` in ink at (62, `H - 102`): mincho 122, spacing -2; a stamp while the block is still scaling (`u < 1`), type after. Closing: the whole block is cut to `168 * (1 - 0.98 * step)` high about its centre (shadow included, so the cut is 9 px wider and lower than the slab) |
| The line | types on 0.40 .. 0.60 | `BERSERK ・ ` + the load + ` ・ ` + the seconds + ` S` in ink at (66, `H - 68`): mono 12.5, spacing 3 |

`prepare` makes the kanji's stamp.

- [ ] **Step 1: Write the failing tests**

```python
class BerserkTest(unittest.TestCase):
    def setUp(self):
        from eva_desk import draw as d
        from eva_desk.motion import render
        from eva_desk.motion.seq.berserk import Berserk
        self.render, self.berserk = render, Berserk()
        self.led = tuple(round(255 * c) for c in d.LED[2::-1])

    def at(self, t, w=1720, h=720, **ctx):
        return self.render.frame(self.berserk, t, w, h, dict(self.render.fixture_ctx(), **ctx))

    def test_identity(self):
        b = self.berserk
        self.assertEqual((b.name, b.length, b.covers, b.rank), ("berserk", 1.3, False, 1))

    def test_the_edges_only(self):
        for t in (0.1, 0.3, 0.6, 0.9, 1.1, 1.25):
            f = self.at(t)
            self.assertEqual((alpha(f, 860, 360), alpha(f, 860, 200), alpha(f, 1200, 500)), (0, 0, 0), t)

    def test_strips_run_in_from_opposite_sides(self):
        f = self.at(0.05)
        self.assertEqual((alpha(f, 100, 39), alpha(f, 1600, 39)), (255, 0))    # under the bar, from the left
        self.assertEqual((alpha(f, 1600, 712), alpha(f, 100, 712)), (255, 0))  # along the floor, from the right
        f = self.at(0.6)
        for y in (39, 712):
            row = [px(f, x, y) for x in range(0, 1720, 2)]
            self.assertTrue(all(p[3] == 255 for p in row), y)
            self.assertTrue({self.led, INK} <= {p[:3] for p in row}, y)        # orange on ink
        self.assertEqual((px(f, 1, 300)[:3], px(f, 1718, 400)[:3]), (self.led, self.led))       # and a line down each side
        self.assertFalse(same(self.at(0.6), self.at(0.7)))                     # the strips crawl while they are up

    def test_the_block_slams_in_at_the_lower_left(self):
        f = self.at(0.7)
        self.assertEqual(px(f, 330, 510)[:3], self.led)                        # the slab, clear of its type
        self.assertEqual((px(f, 344, 600)[:3], px(f, 200, 674)[:3]), (BONE, BONE))               # its hard shadow, right and under
        self.assertEqual(alpha(self.at(0.15), 200, 600), 0)                    # not before 0.18
        self.assertEqual(alpha(self.at(1.1), 200, 600), 0)                     # and closed again by 1.07

    def test_the_line_says_what_is_hot(self):
        self.assertFalse(same(self.at(0.8), self.at(0.8, load="RAM 91%")))
        self.assertFalse(same(self.at(0.8), self.at(0.8, seconds=5)))
        self.assertTrue(same(self.at(0.3), self.at(0.3, load="RAM 91%")))      # it types on from 0.40

    def test_the_top_strip_sits_under_the_bar(self):
        self.assertEqual(alpha(self.at(0.6), 860, 10), 0)                      # no bar named: 28 design px of it
        self.assertEqual(alpha(self.at(0.6, bar=0), 860, 10), 255)             # no bar: at the top of the screen
        self.assertEqual(alpha(self.at(0.6, 3440, 1440, bar=56), 1720, 78), 255)                 # 56 px of bar on the wide monitor

    def test_it_leaves_the_way_it_came(self):
        for t in (1.29, 1.3):
            self.assertEqual(set(grid(self.at(t))), {0}, t)

    def test_nothing_the_offline_renderer_cannot_draw(self):
        for t in (0.05, 0.2, 0.3, 0.5, 0.8, 1.0, 1.2):
            self.assertEqual(pink(self.at(t)), 0, t)

    def test_other_monitor_shapes_and_missing_inputs(self):
        for w, h in ((3440, 1440), (1080, 1920), (640, 360)):
            f = self.at(0.6, w, h)
            self.assertEqual((alpha(f, w // 2, h // 2), alpha(f, w // 2, h - 3)), (0, 255), (w, h))
        self.render.frame(self.berserk, 0.6, 1720, 720, {})
        self.at(0.6, load="", seconds=None)

    def test_same_frame_twice(self):
        self.assertTrue(same(self.at(0.777), self.at(0.777)))
```

- [ ] **Step 2: Run them and see them fail**

Run: `python3 -m unittest tests.test_motion.BerserkTest`
Expected: `ModuleNotFoundError: No module named 'eva_desk.motion.seq.berserk'`

- [ ] **Step 3: Write `berserk.py`, add `Piece.rank`, register it**

- [ ] **Step 4: Run the tests and see them pass**

Run: `python3 -m unittest discover -s tests`
Expected: `FAILED (failures=1)`: only `test_registry`

- [ ] **Step 5: Look at it**

Run: `WAYLAND_DISPLAY=eva-none PYTHONPATH=. python3 -m eva_desk --config /nonexistent --render-motion render/plan2 --only berserk --size 3440x1440`
Read `render/plan2/berserk.png`. Expected: built live in under 3 ms a frame.

---

### Task 5: The track card

**Files:**
- Create: `eva_desk/motion/seq/track.py`
- Modify: `eva_desk/motion/__init__.py` (the registry)
- Test: `tests/test_motion.py` (`TrackTest`)

**Interfaces:**
- Consumes: Task 1's `text(width=)`, `measure(width=)`; plan 1's `rect`, `clip`.
- Produces:

```python
# eva_desk/motion/seq/track.py
def card_width(kit, title, artist) -> float      # the wider of title (mincho 38) and artist (mono 13.5, spacing 3) plus 52, kept between 320 and 640
class Track(Piece): name, length, covers, still, rank = "track", 1.6, False, 0.8, 0
```

Inputs: `ctx["title"]` (with none, nothing is painted), `ctx["artist"]` (may be empty: then there is no lower slab), `ctx["corner"]` (`"bottom-left"`, the default, or `"bottom-right"`). The artist is set in capitals.

The picture, with `cw = card_width(...)`, `x0 = 44` (or `W - 44 - cw` on the right), `ry = H - 96`, the title slab 62 high above the rule and the artist slab 32 high below it (0 without an artist):

| What | When | Geometry |
|---|---|---|
| The rule | draws out over 0 .. 0.20 (cubic out), retracts over 1.40 .. 1.58 (cubic in) | gold, 3 high, centred on `ry`, from `x0` (from the card's right edge on the right) |
| The tag | 0.08 .. 1.42 | a gold slab 18 high, 24 above the title slab's top edge, at `x0`, as wide as `再生 ・ NOW PLAYING` in mincho 11 (spacing 2) plus 18; the words in ink 9 px in, baseline 13.5 below its top |
| The slabs | `up = cubic_out(seg(t, 0.14, 0.34)) * (1 - cubic_in(seg(t, 1.24, 1.42)))` | from `ry - 62 up` to `ry + 32 up`, `cw` wide: `ink_deep` at 95 % over a claret hard shadow 7 px right and down |
| The title | `tu = back_out(seg(t, 0.20, 0.48), 1.1) * (1 - cubic_in(seg(t, 1.18, 1.36)))` | mincho 38, bone, at `x0 + 22`, baseline `ry - 18 + (1 - tu) * 62`, cut to `cw - 44`, inside a clip of the upper slab |
| The artist | `au = cubic_out(seg(t, 0.28, 0.50)) * (1 - cubic_in(seg(t, 1.18, 1.34)))` | mono 13.5, spacing 3, `bone2`, at `x0 + 24`, baseline `ry + 21 - (1 - au) * 32`, cut to `cw - 48`, inside a clip of the lower slab |

- [ ] **Step 1: Write the failing tests**

```python
class TrackTest(unittest.TestCase):
    def setUp(self):
        from eva_desk.motion import render
        from eva_desk.motion.seq.track import Track
        self.render, self.track = render, Track()

    def at(self, t, w=1720, h=720, **ctx):
        return self.render.frame(self.track, t, w, h, dict(self.render.fixture_ctx(), **ctx))

    def test_identity(self):
        k = self.track
        self.assertEqual((k.name, k.length, k.covers, k.rank), ("track", 1.6, False, 0))

    def test_a_card_in_the_lower_left_corner(self):
        x0, y0, x1, y1 = box(self.at(0.8))
        self.assertEqual((x0, y0, y1), (44, 538, 662))                         # the tag's top; the shadow's foot
        self.assertTrue(320 <= x1 - 50 <= 640)                                 # the slab, and 7 px of shadow
        self.assertEqual(alpha(self.at(0.8), 860, 360), 0)
        self.assertEqual(box(self.at(0.8, corner="bottom-right"))[2], 1682)    # or the lower right, 44 px from the side

    def test_the_card_is_as_wide_as_its_type_within_limits(self):
        self.assertEqual(box(self.at(0.8, title="A", artist="B"))[2], 370)     # never under 320
        f = self.at(0.8, title="X" * 300, artist="Y" * 300)
        self.assertEqual(box(f)[2], 690)                                       # never over 640
        self.assertFalse(any(px(f, x, y)[:3] == BONE for x in range(664, 684) for y in range(570, 620)))     # cut inside its padding, not run off the edge

    def test_no_artist_no_lower_slab(self):
        self.assertEqual(box(self.at(0.8, artist=""))[3], 630)                 # the title slab's own shadow, and nothing under it

    def test_it_holds_still(self):
        self.assertTrue(same(self.at(0.6), self.at(1.1)))                      # nothing reacts to the music
        self.assertFalse(same(self.at(0.8), self.at(0.8, title="Other")))
        self.assertFalse(same(self.at(0.8), self.at(0.8, artist="Other")))

    def test_it_comes_out_of_a_rule_and_goes_back_into_it(self):
        for t in (0.05, 1.5):
            x0, y0, x1, y1 = box(self.at(t))
            self.assertLessEqual(y1 - y0, 3, t)                                # only the rule
        self.assertEqual(set(grid(self.at(1.6))), {0})

    def test_odd_titles(self):
        for title in ("مرحبا بالعالم", "🦊🦊🦊", "火狐", "X" * 300):
            for t in (0.3, 0.8, 1.3):
                self.at(t, title=title, artist=title)
        self.assertIsNone(box(self.at(0.8, title="")))                         # nothing to announce: nothing painted
        self.render.frame(self.track, 0.8, 1720, 720, {})

    def test_nothing_the_offline_renderer_cannot_draw(self):
        for t in (0.05, 0.2, 0.4, 0.8, 1.3, 1.5):
            self.assertEqual(pink(self.at(t)), 0, t)

    def test_other_monitor_shapes(self):
        self.assertEqual(box(self.at(0.8, 3440, 1440))[0], 88)
        for w, h in ((1080, 1920), (640, 360)):
            x0, y0, x1, y1 = box(self.at(0.8, w, h))
            self.assertTrue(0 < x0 and x1 < w and h / 2 < y0 and y1 < h, (w, h))

    def test_same_frame_twice(self):
        self.assertTrue(same(self.at(0.3333), self.at(0.3333)))
```

- [ ] **Step 2: Run them and see them fail**

Run: `python3 -m unittest tests.test_motion.TrackTest`
Expected: `ModuleNotFoundError: No module named 'eva_desk.motion.seq.track'`

- [ ] **Step 3: Write `track.py` and register it**

- [ ] **Step 4: Run the tests and see them pass**

Run: `python3 -m unittest discover -s tests`
Expected: `OK` (228 tests), `test_registry` among them

- [ ] **Step 5: Look at it**

Run: `WAYLAND_DISPLAY=eva-none PYTHONPATH=. python3 -m eva_desk --config /nonexistent --render-motion render/plan2 --only track --size 3440x1440`
Read `render/plan2/track.png`. Expected: built live in under 1 ms a frame.

---

### Task 6: The decisions (`triggers.py`)

**Files:**
- Create: `eva_desk/motion/triggers.py`
- Test: `tests/test_motion.py` (`TriggersTest`)

**Interfaces:**
- Consumes: `hypr.class_matches`.
- Produces:

```python
# eva_desk/motion/triggers.py: no GTK, no clock, no files. Hyprland's answers come in as the lists hyprctl -j gives.
def boot_due(marker, signature) -> bool               # the marker file's text (None when there is none) against this Hyprland's signature
def boot_inputs(monitors, version, lua, net) -> dict  # {"outputs": ["3440×1440", ...], "hyprland": "0.56", "lua": ..., "net": ...}
def game_open(clients, patterns) -> bool              # any window whose class matches, wherever it is
def fullscreen_monitors(monitors, clients) -> set     # names of the monitors showing a fullscreen (not merely maximised) window
def track_monitor(monitors, mains) -> str | None      # the focused monitor when it is one of `mains`, else the first of `mains` that exists
def outranks(new, old) -> bool                        # may the piece `new` take the place of `old` on a monitor

class TrackWatch:
    QUIET, SETTLE = 1.5, 0.4
    def __init__(self, now)
    def feed(self, status, title, artist, now)        # every report of the player
    def settle(self, now) -> tuple[str, str] | None   # (title, artist) to announce, once, or None

class LockWatch:
    COVER_AFTER = 1.0
    alive: bool
    def started(self, now)
    def tick(self, now, status) -> str                # status: None while the locker runs, else its exit status. "wait" | "cover" | "play" | "drop"
```

The rules:

- `boot_due`: true when there is a signature and the marker, stripped, is not it.
- `boot_inputs`: each enabled monitor as `width×height` with the multiplication sign, in the order given; the version as its first two numbers (`"0.56.0"` and `"v0.56.0-12-gabc"` both give `"0.56"`; anything else is passed through, an absent one is `""`).
- `fullscreen_monitors`: a monitor counts when a mapped, not hidden window with `fullscreen >= 2` is on its active workspace or on its open special workspace.
- `outranks`: `(new.covers, new.rank) >= (old.covers, old.rank)`.
- `TrackWatch`: a report with a title in the first `QUIET` seconds is the track that was already playing: noted, not announced. After that, `settle` announces the last report when it is at least `SETTLE` old, its status is `Playing`, it has a title, and (title, artist) is not the pair last noted or announced.
- `LockWatch`: while the locker runs, `tick` says `wait`, and once, when it has run for `COVER_AFTER`, `cover`. When it has exited: `play` if the cover went up and the status is 0, else `drop`. Either way it is no longer `alive`. A `tick` when nothing was started says `drop`.

- [ ] **Step 1: Write the failing tests**

```python
class TriggersTest(unittest.TestCase):
    def setUp(self):
        from eva_desk.motion import triggers
        self.T = triggers

    def test_boot_once_per_hyprland_session(self):
        T = self.T
        self.assertTrue(T.boot_due(None, "abc"))
        self.assertTrue(T.boot_due("another\n", "abc"))
        self.assertFalse(T.boot_due("abc\n", "abc"))
        self.assertFalse(T.boot_due(None, ""))                                 # not under Hyprland: nothing to boot into

    def test_boot_inputs(self):
        T = self.T
        mons = [{"width": 3440, "height": 1440}, {"width": 1080, "height": 1920, "disabled": True}, {"width": 1920, "height": 1080}]
        self.assertEqual(T.boot_inputs(mons, {"version": "0.56.0"}, True, "wifi"),
                         {"outputs": ["3440×1440", "1920×1080"], "hyprland": "0.56", "lua": True, "net": "wifi"})
        self.assertEqual(T.boot_inputs([], {"tag": "v0.57.1-12-gabc"}, False, None)["hyprland"], "0.57")
        self.assertEqual(T.boot_inputs(None, None, True, "lan"), {"outputs": [], "hyprland": "", "lua": True, "net": "lan"})
        self.assertEqual(T.boot_inputs([], {"version": "git"}, True, "lan")["hyprland"], "git")

    def test_a_game_is_open_wherever_its_window_is(self):
        T, pats = self.T, ["^steam_app_", "^gamescope$"]
        self.assertFalse(T.game_open([{"class": "kitty"}], pats))
        self.assertTrue(T.game_open([{"class": "kitty"}, {"class": "steam_app_42", "hidden": True, "workspace": {"id": 9}}], pats))
        self.assertFalse(T.game_open([], pats))
        self.assertFalse(T.game_open(None, pats))

    def test_fullscreen_monitors(self):
        T = self.T
        mons = [{"id": 0, "name": "DP-1", "activeWorkspace": {"id": 1}, "specialWorkspace": {"id": 0}},
                {"id": 1, "name": "DP-2", "activeWorkspace": {"id": 5}, "specialWorkspace": {"id": -98}}]

        def win(ws, fs, **more):
            return dict({"workspace": {"id": ws}, "fullscreen": fs, "mapped": True}, **more)
        self.assertEqual(T.fullscreen_monitors(mons, [win(1, 2)]), {"DP-1"})
        self.assertEqual(T.fullscreen_monitors(mons, [win(1, 1)]), set())      # maximised is not fullscreen
        self.assertEqual(T.fullscreen_monitors(mons, [win(2, 2)]), set())      # on a workspace that is not showing
        self.assertEqual(T.fullscreen_monitors(mons, [win(1, 2, hidden=True)]), set())
        self.assertEqual(T.fullscreen_monitors(mons, [win(-98, 2), win(1, 0)]), {"DP-2"})        # on the open special workspace
        self.assertEqual(T.fullscreen_monitors(None, None), set())

    def test_track_monitor(self):
        T = self.T
        mons = [{"name": "DP-1", "focused": False}, {"name": "DP-2", "focused": True}]
        self.assertEqual(T.track_monitor(mons, ["DP-1"]), "DP-1")              # the focused one is not a main monitor
        self.assertEqual(T.track_monitor(mons, ["DP-1", "DP-2"]), "DP-2")
        self.assertEqual(T.track_monitor(mons, ["GONE", "DP-1"]), "DP-1")
        self.assertIsNone(T.track_monitor(mons, []))
        self.assertIsNone(T.track_monitor(None, ["DP-1"]))

    def test_what_may_take_the_place_of_what(self):
        T = self.T

        def piece(covers, rank=0):
            return types.SimpleNamespace(covers=covers, rank=rank)
        card, berserk, track = piece(True), piece(False, 1), piece(False, 0)
        for new, old, may in ((card, card, True), (card, berserk, True), (card, track, True), (berserk, track, True),
                              (berserk, berserk, True), (track, track, True), (track, berserk, False),
                              (berserk, card, False), (track, card, False)):
            self.assertEqual(T.outranks(new, old), may)

    def test_track_changes(self):
        w = self.T.TrackWatch(100.0)
        w.feed("Playing", "A", "X", 100.2)                                     # what was playing when the daemon came up
        self.assertIsNone(w.settle(101.0))                                     # is noted, not announced
        w.feed("Playing", "B", "", 110.0)                                      # a new title; its artist arrives a moment later
        w.feed("Playing", "B", "Y", 110.1)
        self.assertIsNone(w.settle(110.3))                                     # not settled yet
        self.assertEqual(w.settle(110.6), ("B", "Y"))
        self.assertIsNone(w.settle(111.0))                                     # once
        w.feed("Paused", "B", "Y", 120.0)
        w.feed("Playing", "B", "Y", 125.0)
        self.assertIsNone(w.settle(126.0))                                     # the same track, resumed
        w.feed("Paused", "C", "Z", 130.0)
        self.assertIsNone(w.settle(131.0))                                     # a new title, but nothing plays
        w.feed("Playing", "C", "Z", 140.0)
        self.assertEqual(w.settle(140.5), ("C", "Z"))
        w.feed("", "", "", 150.0)                                              # the player went away and came back on the same track
        w.feed("Playing", "C", "Z", 155.0)
        self.assertIsNone(w.settle(156.0))
        late = self.T.TrackWatch(0.0)
        self.assertIsNone(late.settle(30.0))                                   # nothing reported yet
        late.feed("Playing", "A", "X", 60.0)                                   # nothing was playing at the start: the first track is announced
        self.assertEqual(late.settle(60.5), ("A", "X"))

    def test_the_locker(self):
        w = self.T.LockWatch()
        self.assertFalse(w.alive)
        self.assertEqual(w.tick(1.0, None), "drop")                            # nothing was started
        w.started(10.0)
        self.assertTrue(w.alive)
        self.assertEqual([w.tick(10.2, None), w.tick(10.9, None)], ["wait", "wait"])
        self.assertEqual(w.tick(11.0, None), "cover")                          # it holds the screen: the cover goes up under it
        self.assertEqual(w.tick(11.3, None), "wait")                           # once
        self.assertEqual(w.tick(500.0, 0), "play")
        self.assertFalse(w.alive)
        w.started(600.0)
        self.assertEqual(w.tick(600.1, 0), "drop")                             # it came straight back: loginctl lock-session, or already locked
        w.started(700.0)
        self.assertEqual(w.tick(701.5, None), "cover")
        self.assertEqual(w.tick(710.0, 1), "drop")                             # it died: the cover goes, no sequence
        w.started(800.0)
        self.assertEqual(w.tick(800.2, 127), "drop")                           # not installed
        self.assertFalse(w.alive)
```

- [ ] **Step 2: Run them and see them fail**

Run: `python3 -m unittest tests.test_motion.TriggersTest`
Expected: `ImportError: cannot import name 'triggers' from 'eva_desk.motion'`

- [ ] **Step 3: Write `triggers.py`**

- [ ] **Step 4: Run the tests and see them pass**

Run: `python3 -m unittest discover -s tests`
Expected: `OK` (236 tests)

---

### Task 7: A player for every monitor, and held pieces

**Files:**
- Modify: `eva_desk/motion/player.py`
- Test: `tests/test_motion.py` (`PlayerTest`, `PlayersTest`)

**Interfaces:**
- Consumes: `triggers.outranks`, `Piece.rank`.
- Produces:

```python
# eva_desk/motion/player.py
class SequencePlayer(_Overlay):
    held: bool                                                   # the piece is up on its first frame and has not been started
    def play(self, piece, gdk_monitor, ctx, on_done=None, held=False) -> bool
    def start(self)                                              # set a held piece going; nothing otherwise

class Players:
    """One SequencePlayer per monitor, made when a piece first plays there, and the rule for what interrupts what."""
    by_monitor: dict                                             # Gdk monitor -> SequencePlayer
    def __init__(self, app, make=SequencePlayer)
    def play(self, piece, gdk_monitor, ctx, on_done=None, held=False) -> bool    # False: no monitor, or what plays there outranks it
    def start(self)                                              # every held piece, on every monitor
    def stop(self, name=None)                                    # end what is playing: everything, or the pieces of that name
    def forget(self, alive)                                      # destroy the players of monitors that are not in `alive`
    busy: bool                                                   # a piece that covers is playing on some monitor
```

A held piece is shown and takes the pointer as usual, but no tick runs and no safety timeout is set: it may wait for hours under a lock screen. `start()` sets the safety and the tick, as `play()` does for a piece that is not held. A click ends a held piece like any other. `finish()` clears `held`.

- [ ] **Step 1: Write the failing tests**

`FakeView` counts its tick callbacks (replace its `add_tick_callback`):

```python
class FakeView:
    ticks = 0

    def queue_draw(self):
        pass

    def add_tick_callback(self, fn):
        self.ticks += 1
        return self.ticks

    def remove_tick_callback(self, tick):
        pass
```

In `PlayerTest`:

```python
    def test_a_held_piece_waits_on_its_first_frame(self):
        from gi.repository import Gtk
        p, done = player(), []
        self.assertTrue(p.play(dummy(), MON, {}, on_done=lambda: done.append(1), held=True))
        self.assertTrue(p.win.visible and p.busy and p.held)
        self.assertEqual((p.timers, p.view.ticks), ([], 0))                    # no clock runs and no safety counts down: it may wait for hours
        p._paint(Gtk.Snapshot(), 1720, 720)
        self.assertEqual(p.at, 0.0)
        p.start()
        self.assertEqual(([ms for ms, _ in p.timers], p.view.ticks, p.held), ([3000], 1, False))
        p.start()                                                              # again: nothing more
        self.assertEqual((len(p.timers), p.view.ticks), (1, 1))
        p.advance(5.0)
        p.advance(7.0)
        self.assertEqual(done, [1])

    def test_a_click_ends_a_held_piece_too(self):
        p = player()
        p.play(dummy(), MON, {}, held=True)
        p.skip()
        self.assertFalse(p.win.visible or p.busy or p.held)
        p.start()                                                              # the locker exits later: nothing is left to start
        self.assertEqual((p.timers, p.view.ticks), ([], 0))
```

A new class (it shares `PlayerTest`'s `setUp`: move that into a small base class `NoCompositor` and derive both from it):

```python
class PlayersTest(NoCompositor):
    def players(self):
        from eva_desk.motion.player import Players
        return Players(object(), make=lambda app: player())

    def test_a_player_for_every_monitor(self):
        ps, side = self.players(), FakeMonitor(1080, 1920)
        self.assertFalse(ps.busy)
        self.assertTrue(ps.play(dummy(), MON, {}))
        self.assertTrue(ps.play(dummy(), side, {}))
        self.assertEqual(set(ps.by_monitor), {MON, side})
        self.assertTrue(all(p.win.visible for p in ps.by_monitor.values()) and ps.busy)
        self.assertTrue(ps.play(dummy(), MON, {}))                             # the same monitor again: the same player
        self.assertEqual(len(ps.by_monitor), 2)
        self.assertFalse(ps.play(dummy(), None, {}))
        ps.stop()
        self.assertFalse(ps.busy or any(p.win.visible for p in ps.by_monitor.values()))

    def test_what_outranks_what_on_one_monitor(self):
        ps, berserk, track, card = self.players(), dummy(covers=False), dummy(covers=False), dummy()
        berserk.rank = 1
        self.assertTrue(ps.play(berserk, MON, {}))
        self.assertFalse(ps.play(track, MON, {}))                              # the track card is dropped: berserk outranks it
        self.assertIs(ps.by_monitor[MON].piece, berserk)
        self.assertFalse(ps.busy)                                              # nothing covers yet
        self.assertTrue(ps.play(card, MON, {}))                                # what covers takes the place of anything
        self.assertEqual((berserk.released, ps.busy), (1, True))
        self.assertFalse(ps.play(dummy(covers=False), MON, {}))
        self.assertTrue(ps.play(track, FakeMonitor(), {}))                     # another monitor is its own matter

    def test_held_pieces_start_together_and_stop_by_name(self):
        ps, side, a, b = self.players(), FakeMonitor(1080, 1920), dummy(), dummy()
        a.name = b.name = "wake"
        ps.play(a, MON, {}, held=True)
        ps.play(b, side, {}, held=True)
        self.assertTrue(all(p.held for p in ps.by_monitor.values()))
        ps.start()
        self.assertFalse(any(p.held for p in ps.by_monitor.values()))
        ps.stop("card")                                                        # another name: nothing ends
        self.assertTrue(ps.busy)
        ps.stop("wake")
        self.assertEqual((ps.busy, a.released, b.released), (False, 1, 1))

    def test_a_monitor_that_went_away_is_forgotten(self):
        ps, side, gone = self.players(), FakeMonitor(1080, 1920), []
        ps.play(dummy(), MON, {})
        ps.play(dummy(), side, {})
        ps.by_monitor[side].destroy = lambda: gone.append(side)
        ps.forget([MON])
        self.assertEqual((set(ps.by_monitor), gone), ({MON}, [side]))
```

- [ ] **Step 2: Run them and see them fail**

Run: `python3 -m unittest tests.test_motion.PlayerTest tests.test_motion.PlayersTest`
Expected: `TypeError: SequencePlayer.play() got an unexpected keyword argument 'held'` and `ImportError: cannot import name 'Players'`

- [ ] **Step 3: Write `held`, `start` and `Players`**

`forget` ends a forgotten player's piece (`finish()`) before destroying it.

- [ ] **Step 4: Run the tests and see them pass**

Run: `python3 -m unittest discover -s tests`
Expected: `OK` (242 tests)

---

### Task 8: The daemon plays boot, berserk and the track card

**Files:**
- Modify: `eva_desk/app.py`, `eva_desk/config.py`, `config/eva.example.toml`, `bin/eva-ctl`
- Test: `tests/test_motion.py` (`EventsWiring`, and `LaunchWiring.test_the_play_command`)

**Interfaces:**
- Consumes: `Players`, the four pieces, `triggers`.
- Produces:

```python
# eva_desk/config.py: DEFAULTS["motion"] = {"launch": True, "boot": True, "wake": True, "berserk": True, "track": True, "track_corner": "bottom-left"}

# eva_desk/app.py
class App:
    motion: Players | None                       # was one SequencePlayer
    tracks: triggers.TrackWatch
    def _later(self, ms, fn)                     # GLib.timeout_add, once; a seam for the tests
    def _inputs(self, **more) -> dict            # what any piece may show: workspace, clock, bar, and whatever is passed
    def _play(self, piece, gdk_monitor=None, **inputs) -> bool     # on that monitor, or the focused one
    def _mains_gdk(self, skip=()) -> list        # the Gdk monitors of the main monitors, without the names in `skip`
    def _quiet(self) -> bool                     # a sequence that covers, the launcher, the power menu or Alt+Tab is up
    def _boot(self, marker=None) -> bool
    def _announce_berserk(self, cpu, mem_pct) -> int               # how many monitors it played on
    def _on_music(self, status, title, artist, now=None)
    def _track_settled(self, now=None) -> bool
```

What each does:

- `do_activate` makes `self.motion = Players(self)` where it made the single player, and `self.tracks = TrackWatch(time.monotonic())` before `NowPlaying` exists. The sampler and its timer are made when the bar shows resources **or** `[overlays] berserk` is above 0; `NowPlaying` when the bar shows music **or** `[motion] track` is on. After the first `refresh()` it calls `self._boot()`. `_sync_components` ends with `self.motion.forget(gdk.values())` when there is a player.
- `_inputs`: `workspace` and `clock` as `_play` built them in plan 1, and `bar`: `[bar] height` when the bar is enabled, else 0.
- `play_launch(name, game, gdk_monitor)` keeps its signature and passes `app=name`.
- `_boot`: the marker is `$XDG_RUNTIME_DIR/eva-desk.boot`. When `triggers.boot_due` says so, the signature is written to it (whatever `[motion] boot` says, so that switching it on later does not replay the boot in the middle of a session), and with `[motion] boot` on, `Boot` plays on every main monitor with `triggers.boot_inputs(...)`; the net kind comes from the sampler when there is one.
- `_berserk_check` calls `_announce_berserk(cpu, mem_pct)` when it turns berserk on. That plays `Berserk` on each main monitor with `load` (`CPU nn%`, or `RAM nn%` when memory is the higher of the two) and `seconds` (`[overlays] berserk_seconds`), unless `[motion] berserk` is off, `_quiet()`, a game is open, or that monitor shows a fullscreen window.
- `_on_music` keeps updating the bars, feeds `self.tracks`, and asks for `_track_settled` 450 ms later through `_later`. `_track_settled` plays `Track` with `title`, `artist` and `corner` (`[motion] track_corner`) on `triggers.track_monitor(...)`, under the same four conditions as berserk. A track that settles while one of them holds is not announced later.
- The `play` command takes all six names: `play: card | shaft | boot | wake | berserk | track`, `unknown piece: X (card, shaft, boot, wake, berserk, track)`. It plays on the focused monitor whatever the conditions above say. Its inputs: `app` is the text or `EVA-DESK`; boot reads its inputs live; berserk shows the last sample (or `CPU 97%`); track shows the text as its title, or the track that is playing, or `TITLE` by `ARTIST`.

- [ ] **Step 1: Write the failing tests**

In `LaunchWiring.test_the_play_command`, the two messages become `"unknown piece: nope (card, shaft, boot, wake, berserk, track)"` and `"play: card | shaft | boot | wake | berserk | track"`. `FakePlayer.play` gains `held=False` and a `forget` that does nothing.

```python
class FakePlayers:
    busy = False

    def __init__(self):
        self.calls, self.started, self.stopped = [], 0, []

    def play(self, piece, mon, ctx, on_done=None, held=False):
        self.calls.append((type(piece).__name__, mon, ctx, held))
        return True

    def start(self):
        self.started += 1

    def stop(self, name=None):
        self.stopped.append(name)

    def forget(self, alive):
        pass


def events_app(**motion):
    """An App with no windows: two monitors, DP-1 (the main one, focused) and DP-2."""
    from eva_desk.app import App
    from eva_desk.motion import triggers
    app = App.__new__(App)
    app.cfg = config.load("/nonexistent")
    app.cfg["motion"].update(motion)
    app.hypr, app.motion = FakeHypr(), FakePlayers()
    app.stages, app.bars, app.overlays, app.prev, app.launcher = {}, {}, {}, {}, None
    app.gdk_of = {"DP-1": "GDK-1", "DP-2": "GDK-2"}
    app.hypr.state = {"monitors": [{"id": 0, "name": "DP-1", "width": 3440, "height": 1440, "focused": True, "activeWorkspace": {"id": 1}},
                                   {"id": 1, "name": "DP-2", "width": 1080, "height": 1920, "focused": False, "activeWorkspace": {"id": 5}}],
                      "clients": [], "activeworkspace": {"id": 1}, "version": {"version": "0.56.0"}}
    app.res_state = app.music_state = None
    app.tracks = triggers.TrackWatch(0.0)
    app.later = []
    app._later = lambda ms, fn: app.later.append((ms, fn))
    app.schedule = lambda *a: None
    app.focused_gdk = lambda: "FOCUSED"
    return app


class EventsWiring(unittest.TestCase):
    def test_the_defaults_are_on(self):
        self.assertEqual(config.load("/nonexistent")["motion"],
                         {"launch": True, "boot": True, "wake": True, "berserk": True, "track": True, "track_corner": "bottom-left"})

    def test_boot_plays_once_per_session(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(os.environ, {"HYPRLAND_INSTANCE_SIGNATURE": "sig-1"}):
            marker, app = Path(tmp) / "eva-desk.boot", events_app()
            self.assertTrue(app._boot(marker))
            (name, mon, ctx, held), = app.motion.calls                         # the main monitor only
            self.assertEqual((name, mon, held), ("Boot", "GDK-1", False))
            self.assertEqual((ctx["outputs"], ctx["hyprland"], ctx["bar"]), (["3440×1440", "1080×1920"], "0.56", 56))
            self.assertEqual(marker.read_text().strip(), "sig-1")
            self.assertFalse(app._boot(marker))                                # eva-ctl reload: not again
            self.assertEqual(len(app.motion.calls), 1)
            with mock.patch.dict(os.environ, {"HYPRLAND_INSTANCE_SIGNATURE": "sig-2"}):           # the next session
                off = events_app(boot=False)
                self.assertFalse(off._boot(marker))                            # switched off: nothing plays,
                self.assertEqual((off.motion.calls, marker.read_text().strip()), ([], "sig-2"))   # but the session is marked
                nowhere = events_app()
                nowhere.gdk_of = {}                                            # no monitor known yet
                marker.unlink()
                self.assertFalse(nowhere._boot(marker))
                none = events_app()
                none.motion = None
                marker.unlink()
                self.assertFalse(none._boot(marker))

    def test_berserk_announces_itself_when_it_starts(self):
        app = events_app()
        app.cfg["overlays"].update(berserk=90, berserk_seconds=0)
        app._berserk_check(97, 40)
        (name, mon, ctx, held), = app.motion.calls
        self.assertEqual((name, mon, held, ctx["load"], ctx["seconds"]), ("Berserk", "GDK-1", False, "CPU 97%", 0))
        app._berserk_check(98, 40)                                             # still hot: it said so already
        self.assertEqual(len(app.motion.calls), 1)
        app._berserk_check(10, 10)                                             # cooled
        app._berserk_check(20, 95)                                             # and hot again, on memory this time
        self.assertEqual([c[2]["load"] for c in app.motion.calls], ["CPU 97%", "RAM 95%"])

    def test_berserk_and_the_track_card_stay_out_of_the_way(self):
        game = {"class": "steam_app_42", "workspace": {"id": 9}, "fullscreen": 0, "mapped": True}
        full = {"class": "mpv", "workspace": {"id": 1}, "fullscreen": 2, "mapped": True}

        def blocked(change):
            app = events_app()
            change(app)
            app.tracks.feed("Playing", "B", "Y", 50.0)
            return (app._announce_berserk(97, 40), app._track_settled(50.5), app.motion.calls)
        self.assertEqual(blocked(lambda a: None)[:2], (1, True))               # nothing in the way: both play
        for change in (lambda a: a.hypr.state.update(clients=[game]),          # a game is open, on a workspace that is not showing
                       lambda a: a.hypr.state.update(clients=[full]),          # a fullscreen window on that monitor
                       lambda a: setattr(a.motion, "busy", True),              # a sequence that covers is playing
                       lambda a: setattr(a, "launcher", types.SimpleNamespace(visible=lambda: True)),
                       lambda a: a.overlays.update(power=types.SimpleNamespace(visible=True)),
                       lambda a: a.overlays.update(alttab=types.SimpleNamespace(visible=True)),
                       lambda a: a.cfg["motion"].update(berserk=False, track=False),
                       lambda a: setattr(a, "gdk_of", {})):
            self.assertEqual(blocked(change), (0, False, []))
        gone = events_app()
        gone.motion = None
        self.assertEqual((gone._announce_berserk(97, 40), gone._track_settled(1.0)), (0, False))

    def test_a_new_track_gets_a_card(self):
        app = events_app(track_corner="bottom-right")
        app.hypr.state["monitors"][0]["focused"], app.hypr.state["monitors"][1]["focused"] = False, True     # the side monitor has the focus
        app._on_music("Playing", "B", "", now=50.0)
        app._on_music("Playing", "B", "Y", now=50.1)
        self.assertEqual([ms for ms, _ in app.later], [450, 450])
        self.assertEqual(app.music_state, {"status": "Playing", "title": "B", "artist": "Y"})
        self.assertFalse(app._track_settled(50.3))                             # not settled yet
        self.assertTrue(app._track_settled(50.6))
        (name, mon, ctx, held), = app.motion.calls
        self.assertEqual((name, mon, held), ("Track", "GDK-1", False))         # on the main monitor all the same
        self.assertEqual((ctx["title"], ctx["artist"], ctx["corner"]), ("B", "Y", "bottom-right"))
        self.assertFalse(app._track_settled(51.0))                             # once

    def test_play_tries_any_of_the_six(self):
        app = events_app()
        for name in ("card", "shaft", "boot", "wake", "berserk", "track"):
            self.assertEqual(app.command(f"play {name}"), "ok", name)
        self.assertEqual([c[0] for c in app.motion.calls], ["Card", "Shaft", "Boot", "Wake", "Berserk", "Track"])
        self.assertTrue(all(c[1] == "FOCUSED" for c in app.motion.calls))
        self.assertEqual(app.motion.calls[4][2]["load"], "CPU 97%")            # nothing sampled yet
        self.assertEqual((app.motion.calls[5][2]["title"], app.motion.calls[5][2]["artist"]), ("TITLE", "ARTIST"))
        app.music_state = {"status": "Playing", "title": "Now", "artist": "Them"}
        app.command("play track")
        app.command("play track My own words")
        self.assertEqual([c[2]["title"] for c in app.motion.calls[6:]], ["Now", "My own words"])
```

- [ ] **Step 2: Run them and see them fail**

Run: `python3 -m unittest tests.test_motion.EventsWiring tests.test_motion.LaunchWiring`
Expected: `AttributeError: 'App' object has no attribute '_boot'` (and `_announce_berserk`, `_track_settled`), `KeyError: 'track'`, and the two `play` messages differing

- [ ] **Step 3: Write the wiring**

`bin/eva-ctl`'s `play` line names the six pieces. `config/eva.example.toml` gains under `[motion]`, each with a comment in the file's voice: `boot = true`, `wake = true`, `berserk = true`, `track = true`, `track_corner = "bottom-left"`.

- [ ] **Step 4: Run the tests and see them pass**

Run: `python3 -m unittest discover -s tests`
Expected: `OK` (248 tests)

---

### Task 9: The locker as the daemon's child, and resume

**Files:**
- Modify: `eva_desk/app.py`, `eva_desk/overlays.py`, `bin/eva-ctl`
- Test: `tests/test_motion.py` (`LockWiring`)

**Interfaces:**
- Consumes: `triggers.LockWatch`, `Players.play(held=True)`, `Players.start`, `Players.stop`, `Wake`.
- Produces:

```python
# eva_desk/app.py
class App:
    locker: object | None                        # the running locker (it has poll()), or None
    lock_watch: triggers.LockWatch
    def _spawn(self, cmd)                        # subprocess.Popen of /bin/sh -c cmd in a session of its own, its output discarded; a seam for the tests
    def _every(self, ms, fn)                     # GLib.timeout_add, repeating while fn returns True; a seam for the tests
    def lock(self, now=None) -> str              # "ok" | "already locked" | "no lock command" | "lock failed (see the log)"
    def _watch_locker(self, now=None) -> bool    # the 250 ms timer while the locker runs; False ends it
    def _on_sleep(self, sleeping)                # logind's PrepareForSleep
```

What each does:

- `lock()`: with no `[power] lock` command, `no lock command`. With `[motion] wake` off or no player, the command goes to Hyprland as it did (`self.hypr.exec`) and that is all. Otherwise, unless a locker is already running (`already locked`), the command is started with `_spawn`, `lock_watch.started(now)`, and `_watch_locker` runs every 250 ms. An `OSError` from `_spawn` is logged and answered with `lock failed (see the log)`.
- The locker runs in a session of its own so that a signal meant for the daemon's process group cannot end it, and it is never killed by the daemon: if the daemon goes away, the screen stays locked.
- `_watch_locker` asks `lock_watch.tick(now, self.locker.poll())`: on `cover`, `Wake` goes up held on every main monitor; on `play`, `self.motion.start()`; on `drop`, `self.motion.stop("wake")`. `play` and `drop` clear `self.locker` and end the timer.
- The power menu's `_run` calls `self.app.lock()` for the `lock` key when the app has one, instead of `hypr.exec`. The `lock` command of `eva-ctl` answers with what `lock()` returns.
- `_on_sleep(False)` (resume) plays `Wake`, not held, on every main monitor, unless a locker is running (its exit will play it), `[motion] wake` is off, or there is no player. `_on_sleep(True)` does nothing in this plan.
- `do_activate` subscribes to `org.freedesktop.login1.Manager.PrepareForSleep` on the system bus and passes its boolean to `_on_sleep`. Without a system bus, one log line (`eva-desk: no system bus: no wake sequence after sleep`) and nothing else. This subscription is not tested; `_on_sleep` is.

- [ ] **Step 1: Write the failing tests**

```python
class FakeLocker:
    status = None

    def poll(self):
        return self.status


def lock_app(**motion):
    from eva_desk.motion import triggers
    app = events_app(**motion)
    app.spawned, app.every, app.locker = [], [], None
    app.lock_watch = triggers.LockWatch()

    def spawn(cmd):
        app.spawned.append(cmd)
        return FakeLocker()
    app._spawn = spawn
    app._every = lambda ms, fn: app.every.append((ms, fn))
    return app


class LockWiring(unittest.TestCase):
    def test_the_cover_goes_up_under_the_lock_screen_and_plays_when_it_closes(self):
        app = lock_app()
        self.assertEqual(app.lock(now=100.0), "ok")
        self.assertEqual((app.spawned, [ms for ms, _ in app.every], app.hypr.execs), (["hyprlock"], [250], []))
        self.assertTrue(app._watch_locker(100.5))                              # the locker is coming up: nothing yet
        self.assertEqual(app.motion.calls, [])
        self.assertTrue(app._watch_locker(101.0))                              # it holds the screen
        (name, mon, ctx, held), = app.motion.calls
        self.assertEqual((name, mon, held), ("Wake", "GDK-1", True))
        self.assertTrue(app._watch_locker(3000.0))                             # locked for a long while
        self.assertEqual((len(app.motion.calls), app.motion.started), (1, 0))
        app.locker.status = 0                                                  # unlocked
        self.assertFalse(app._watch_locker(3600.0))
        self.assertEqual((app.motion.started, app.motion.stopped, app.locker), (1, [], None))
        self.assertEqual(app.lock(now=4000.0), "ok")                           # and it can be locked again
        self.assertEqual(len(app.spawned), 2)

    def test_a_locker_that_comes_straight_back(self):
        app = lock_app()
        app.lock(now=100.0)
        app.locker.status = 0                                                  # loginctl lock-session, or a second hyprlock: gone at once
        self.assertFalse(app._watch_locker(100.25))
        self.assertEqual((app.motion.calls, app.motion.started, app.motion.stopped, app.locker), ([], 0, ["wake"], None))

    def test_a_locker_that_dies(self):
        app = lock_app()
        app.lock(now=100.0)
        app._watch_locker(101.0)
        app.locker.status = 1
        self.assertFalse(app._watch_locker(200.0))
        self.assertEqual((app.motion.started, app.motion.stopped), (0, ["wake"]))                 # the cover goes; no sequence

    def test_lock_twice_none_and_failure(self):
        app = lock_app()
        self.assertEqual((app.lock(now=1.0), app.lock(now=2.0)), ("ok", "already locked"))
        self.assertEqual(len(app.spawned), 1)
        none = lock_app()
        none.cfg["power"]["lock"] = ""
        self.assertEqual((none.lock(), none.spawned), ("no lock command", []))
        broken = lock_app()
        broken._spawn = mock.Mock(side_effect=OSError("no /bin/sh"))
        with contextlib.redirect_stdout(io.StringIO()) as out:
            self.assertEqual(broken.lock(now=1.0), "lock failed (see the log)")
        self.assertIn("eva-desk: lock", out.getvalue())
        self.assertEqual((broken.locker, broken.every), (None, []))

    def test_with_the_sequence_off_the_locker_starts_as_before(self):
        for app in (lock_app(wake=False), lock_app()):
            if app.cfg["motion"]["wake"]:
                app.motion = None                                              # or with no player at all
            self.assertEqual(app.lock(), "ok")
            self.assertEqual((app.hypr.execs, app.spawned, app.every), (["hyprlock"], [], []))

    def test_the_power_menu_and_eva_ctl_lock_go_through_it(self):
        from eva_desk import overlays as O
        app, locked = lock_app(), []
        app.lock = lambda now=None: locked.append(1) or "ok"
        self.assertEqual(app.command("lock"), "ok")
        menu = O.PowerMenu.__new__(O.PowerMenu)
        menu.app, menu.cross, menu.hide = app, None, lambda: None
        menu._run("lock", "hyprlock")
        self.assertEqual((locked, app.hypr.execs), ([1, 1], []))
        menu._run("sleep", "systemctl suspend")                                # the other keys are as they were
        self.assertEqual(app.hypr.execs, ["systemctl suspend"])
        bare = O.PowerMenu.__new__(O.PowerMenu)                                # an app with no lock(): the command, as before
        bare.app, bare.cross, bare.hide = types.SimpleNamespace(hypr=FakeHypr()), None, lambda: None
        bare._run("lock", "hyprlock")
        self.assertEqual(bare.app.hypr.execs, ["hyprlock"])

    def test_resume_from_sleep(self):
        app = lock_app()
        app._on_sleep(True)                                                    # going to sleep: nothing
        self.assertEqual(app.motion.calls, [])
        app._on_sleep(False)
        (name, mon, ctx, held), = app.motion.calls
        self.assertEqual((name, mon, held), ("Wake", "GDK-1", False))
        locked = lock_app()
        locked.lock(now=1.0)
        locked._on_sleep(False)                                                # resumed onto a lock screen: its closing plays the sequence
        self.assertEqual(locked.motion.calls, [])
        off = lock_app(wake=False)
        off._on_sleep(False)
        self.assertEqual(off.motion.calls, [])
        bare = lock_app()
        bare.motion = None                                                     # no player: nothing to do, and nothing raised
        bare._on_sleep(False)
```

- [ ] **Step 2: Run them and see them fail**

Run: `python3 -m unittest tests.test_motion.LockWiring`
Expected: `AttributeError: 'App' object has no attribute 'lock'` (and `_watch_locker`, `_on_sleep`), `unknown command: lock`

- [ ] **Step 3: Write `lock`, `_watch_locker`, `_on_sleep`, the subscription, and the power menu's call**

`bin/eva-ctl` gains a line: `eva-ctl lock                  lock the screen; the wake sequence plays when it unlocks (bind your lock key to this)`.

- [ ] **Step 4: Run the tests and see them pass**

Run: `python3 -m unittest discover -s tests`
Expected: `OK` (255 tests)

---

### Task 10: Documents, and the whole thing verified offline

**Files:**
- Modify: `README.md`, `docs/superpowers/specs/2026-10-13-motion-graphics-design.md`

- [ ] **Step 1: README**

After the launcher paragraph, one paragraph in the README's voice: what plays and when (boot once per session, wake after the lock screen and after sleep, berserk under sustained load, a card when a new track starts), that none of them takes the keyboard and a click skips the two that cover, that berserk and the track card keep out of the way of fullscreen windows and games, that the lock screen must be started with `eva-ctl lock` (from the power menu, or bound to your lock key, or as your idle tool's lock command) for the wake sequence to follow it, and the switches under `[motion]`. `eva-ctl lock` joins the command list, and the `eva-ctl play` line there names a second piece.

- [ ] **Step 2: The spec**

Bring four places in line with what was built: "Wake" and "Triggers and sources" (the cover goes up under the lock screen one second after the locker starts, is held on its first frame, and plays when the locker exits with status 0; a locker that exits before that, or with an error, gets neither); "The player" (one player per monitor, held pieces, and the rule for what takes the place of what); "The kit" (`tile`, `scanlines`, `hexagon`, `hex_cells`, `lamp`, `brackets`, `block`, type cut to a width); "Boot" (the title block rides the seam, so the gate opens through the digits on any frame; the session is marked even when the sequence is switched off).

- [ ] **Step 3: Run everything**

Run: `python3 -m unittest discover -s tests`
Expected: `OK` (255 tests), with no GTK warning in the output

Run: `WAYLAND_DISPLAY=eva-none PYTHONPATH=. python3 -m eva_desk --config /nonexistent --render-motion render/plan2 --size 3440x1440 --fps 60`
Expected: six lines; built live in under 2 ms (card), 4 (shaft), 4 (boot), 3 (wake), 3 (berserk), 1 (track)

Run: `WAYLAND_DISPLAY=eva-none PYTHONPATH=. python3 -m eva_desk --config /nonexistent --render-motion render/plan2-tall --size 1080x1920 --fps 60`

Run: `WAYLAND_DISPLAY=eva-none PYTHONPATH=. python3 -m eva_desk --config /nonexistent --render render/all`
Expected: `motion_boot`, `motion_wake`, `motion_berserk`, `motion_track` among the stills

Run: `luac -p hypr/eva.lua`
Expected: no output (`eva.lua` is not changed by this plan: every player uses the `eva-motion` namespace)

- [ ] **Step 4: Read the renders**

Read all four new contact sheets at both sizes against the tables of Tasks 2 to 5, and the four stills. Say in the hand-over what was looked at.

- [ ] **Step 5: Hand over**

List the files touched, the checks and their results, the mp4s for the owner to watch, and the live checks below.

### What only a live run can prove

- Boot at login: it plays once, on the main monitor, and not again on `eva-ctl reload`. The first `eva-ctl apply` after this lands plays it once, because the session has no marker yet.
- Lock from the power menu and from `eva-ctl lock`: the lock screen looks as it did (the cover goes up a second after it), the ink cover is what shows when the lock screen fades, and the sequence follows without the desk showing first.
- A lock key or idle tool that starts the locker itself gets no sequence, and nothing else changes for it.
- Resume from sleep, with and without a lock screen.
- Berserk under real load: the strips sit under the real bar and on the floor, the block does not cover anything that matters, and a game or a fullscreen video keeps it away.
- The track card with the real player: one card per track, none when pausing and resuming, none for the track playing at start-up.
- Frame pacing of all four on the high-refresh monitor, and the first sequence on a monitor (its player is made at that moment).
