# Motion graphics, plan 3: standby

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** After some minutes without input every monitor is covered by a slow loop: the Eva in the dark in three pictures, a hexagon field, the real clock. Any key, click or real pointer movement folds it away.

**Architecture:** The loop is one more `Piece` (`length = None`), drawn through the kit and rendered offline like the sequences. A new host, `AmbientLayer`, repaints it from a timer at `[ambient] fps` instead of every frame; `Standby` keeps one layer per monitor on one clock and decides what ends it. When it may start is pure logic in `triggers.py`. The idle timer is `hypridle`, run as the daemon's child with a generated config whose one listener calls `eva-ctl standby on`.

**Tech Stack:** as plans 1 and 2 (Python 3.11, PyGObject with GTK 4, Gsk and Pango, pycairo, gtk4-layer-shell, `unittest`); `hypridle` (optional, at run time); numpy, scipy and Pillow only for `tools/gen/prep_art.py`, which makes the pictures and is not needed to run the desk.

**Spec:** `docs/superpowers/specs/2026-10-13-motion-graphics-design.md`, build step 3: "Standby", and the parts of "The kit", "The player", "Pause rules and cost", "Triggers and sources", "Assets", "Configuration", "Error handling", "Testing" and "Open items" that concern it. The living wallpaper and the side wall follow in plans 4 and 5.

## Global Constraints

- A linked install runs the daemon straight from the main checkout, so the main checkout is live. Work only in the worktree `.worktrees/motion-graphics`. Never edit the main checkout, never run `eva-ctl` against the live session, never open a window on it, never kill a process by pattern.
- No commits, merges or pushes unless the owner asks. A task is done when its tests pass; say which files it touched.
- Verification is offline: `python3 -m unittest discover -s tests`, `eva-desk --render DIR`, `eva-desk --render-motion DIR`. Read the PNGs; a render that runs is not a render that looks right.
- No test spawns a process, talks to a bus, reads the machine's `eva.toml`, or opens a window: `hypridle`, the timers, Hyprland and the layer's window are fakes.
- Colours are theme roles through `draw.py` (`d.INK`, `d.BONE`, `d.BONE2`, `d.BONE3`, `d.GOLD`, `d.CLARET`, `d.RED`), never hex in modules. Fonts are `d.F_DISPLAY` at `d.DISPLAY_WEIGHT` ("mincho" below) and `d.F_META` ("mono").
- A piece never calls `random` and never reads the clock or the system: time arrives as `t`, everything else in `ctx`. Every input has a default, so a piece paints with an empty `ctx`.
- The kit's rules (top of `kit.py`): no path nodes; no glyphs under a scale that changes from frame to frame; a shape that is neither a rectangle nor a sheared one is a picture set once. A loop adds one: nothing is made per frame. No picture, stamp or layout may be created on a frame after a shot's first.
- No full-screen flash: no frame fills the screen with `bone`, `gold` or `led`.
- The Eva is never drawn in code. The pictures are the three the owner chose, generated with the local pipeline; nothing here redraws or traces them.
- Image generation uses the GPU fully while it runs. Before any run: `nvidia-smi`; if a game or anything else is using the GPU, do not run, and say so.
- Standby takes the keyboard. Whatever fails while it is up (a paint that raises, a picture that will not load, a monitor that goes away), it must end and give the keyboard back; it may never be left up with nothing able to end it.
- All sizes are design px. A piece lays out from `kit.W` by `kit.H`; the numbers in the tables are for a 1720x720 frame and say what they are anchored to.
- The repo is public: plain voice in README and comments, nothing about private setups.
- Follow the code around you: a module docstring, long lines, short `# why` comments, `unittest`.

## Review Focus

1. **Input that is not the owner coming back.** The layer mapping under a resting pointer sends a first position; a key that was held when standby started sends only its release; a mouse on a desk that shakes moves a pixel now and then. None of these may end it, and a real move, any key press and any click must (Task 5 `test_travel`; Task 6 `test_what_ends_it`).
2. **A failure while the keyboard is held.** `paint` raises on one monitor; `prepare` fails on one monitor, or on all; a picture file is missing, empty or not a picture; a monitor is unplugged while standby is up. It ends everywhere, every layer is hidden, the piece is released once (Task 4 `test_a_picture_that_is_missing_or_broken_drops_its_shot`; Task 6 `test_a_layer_that_cannot_paint_ends_it_everywhere`, `test_it_starts_where_it_can`; Task 8 `test_a_monitor_that_goes_away_ends_it`).
3. **`standby on` at the wrong moment.** A game open on a hidden workspace, a fullscreen window on the other monitor, the session locked, Hyprland not answering, standby already up (a second `on` must not restart the clock), the launcher or the power menu open (closed first), `[standby] enabled = false` (Task 5 `test_what_blocks_standby`; Task 8 `test_standby_on`, `test_when_it_does_not_start`, `test_it_closes_what_holds_the_keyboard`, `test_what_blocks_a_start_also_ends_it`).
4. **The idle child.** `hypridle` not installed; it exits by itself; a stale one left by a daemon that crashed; a reload (stopped before the daemon re-executes, so there are never two); `minutes = 0` and `idle = "none"` (no child at all); a path to `eva-ctl` with a space in it (Task 7, all of `IdleTest`; Task 8 `test_the_idle_child_follows_the_settings`, `test_a_reload_stops_the_idle_child_first`).
5. **Frames and inputs at the edges.** 3440x1440, 1920x1080 and 1080x1920; an empty `ctx`; `second` at 59.99 and past 60; no readings; a clock of `"9:05"`; `t` a week in (the lattice's offset is then millions of px) (Task 3 `test_it_paints_with_nothing_and_with_odd_inputs`, `test_a_week_in`; Task 4 `test_every_shot_at_every_size`).

## File structure

| File | Responsibility |
|---|---|
| `tools/gen/gen_rim.py` (create) | the prompts of the three pictures, as jobs for `gen.py` |
| `tools/gen/prep_art.py` (create) | splits a picture into its body and eye layers, finds the eyes, writes `art.json` |
| `assets/motion/` (create) | `profile_body.jpg`, `profile_eye.jpg`, `front_*.jpg`, `full_*.jpg`, `art.json` |
| `eva_desk/motion/kit.py` (modify) | `cover_box`, `cover`, `screen_blend`, `soft_band`, `ring` |
| `eva_desk/motion/amb/__init__.py`, `amb/standby.py` (create) | `StandbyLoop` and its pure helpers |
| `eva_desk/motion/__init__.py` (modify) | `loops()` and `everything()` beside `pieces()` |
| `eva_desk/motion/render.py`, `eva_desk/preview.py`, `eva_desk/__main__.py` (modify) | loops are rendered too; the fixture inputs of the clock |
| `eva_desk/motion/triggers.py` (modify) | `standby_blocked`, `Travel`, `readings` |
| `eva_desk/motion/player.py` (modify) | `AmbientLayer` and `Standby` |
| `eva_desk/sources/idle.py` (create) | `conf()` and `Idle`, the `hypridle` child |
| `eva_desk/overlays.py` (modify) | `NotifyWatch`: the watch for critical notifications, taken out of `AlarmBand` |
| `eva_desk/app.py` (modify) | owns `Standby` and `Idle`; `standby [on|off]`; what ends standby |
| `eva_desk/config.py`, `config/eva.example.toml` (modify) | `[ambient] fps`, `[standby] enabled, minutes, idle` |
| `hypr/eva.lua` (modify) | the `no_anim` layer rule gains `standby` |
| `bin/eva-ctl`, `README.md`, `packaging/`, the spec (modify) | the command, the feature, `hypridle` as an optional dependency, what changed in the design |
| `tests/test_motion.py`, `tests/test_sources.py` (modify) | every test of this plan (`IdleTest` in `test_sources.py`) |

The approved animated mock-up is the reference for anything a table below leaves open. It is local and git-ignored, in the main checkout: `.superpowers/brainstorm/46040-1791895389/content/mg-r2.js` (`standby2Frame`) and `mg-ambient.js` (`standbyClock`). If they are gone, the tables below are complete. Mock-up names map to roles like this: `lilac` is `d.RED`, the eye glow's green is `d.GOLD`, `easeOut` is `cubic_out`, `easeIn` is `cubic_in`, `hash` is `noise`.

Things in this plan that go past the letter of the spec. The spec is updated in Task 9 to say them:

- **A layout for a tall monitor.** The mock-up was only ever drawn wide. On a frame taller than it is wide the wide pictures sit in a band and the clock goes under or over it (the table in Task 4). The owner has not seen this; the tall contact sheet is shown at hand-over.
- **The pictures ship at the size they were chosen at** (1792x768 and 896x1344). Generating one again larger gives a different picture, which is no longer the owner's choice. Task 1 ends with one attempt at a larger take that keeps the picture; if it works the owner sees it side by side and decides.
- **What blocks a start also ends it.** The spec lists the locker and a critical notification as what ends standby. A game window or a fullscreen window that appears while it is up, a monitor that comes or goes, and the machine going to sleep end it too, at once.
- **Pointer travel is measured from where the pointer last rested**, so a pixel of jitter now and then never adds up to eight.
- **Standby closes the launcher, the power menu, Alt+Tab and any panel** before it covers them: they hold the keyboard, and so does it.
- **`AmbientLayer` has no `pause()` yet.** Nothing in this plan pauses a loop; plan 4 adds it with its first user and the pause-rule table.
- **The watch for critical notifications leaves `AlarmBand`**, so that one ends standby when the band is switched off too.
- **`eva-ctl play` plays sequences only.** A loop on the sequence player would never end; `play standby` says to use `eva-ctl standby on`.

## Changed during execution

The tasks below are the plan as it was written. Building it changed these things; the code, the tests and the
spec are the truth where they differ from a task:

- **The plan was not reviewed before it was built.** The owner asked for the rest of the spec to be built at once.
- **Task 1, Step 6 was not run.** The GPU was in use, so no larger take of the profile was tried. The pictures
  ship at the size they were chosen at, and the spec's open item stays open.
- **`AmbientLayer.show()` is `play(piece, gdk_monitor, inputs, epoch, now=None)`**, as the sequence player names
  it, and it asks `inputs()` once itself so that the first frame has its inputs. It has `on_hidden` beside
  `on_broken`, and takes its layer (`layer=`), since plans 4 and 5 put it on other layers. `Standby.layers()`.
- **The field on a narrower frame.** At 1280 design px wide 待機 and the clock collided: on a frame no wider than
  16:9 the clock is 180 px, and on an upright frame 待機 moves up and the clock goes under it.
- **Tests.** The glyph helper reports points, so clock sizes are checked at three quarters of their px. The
  passing light is measured as blue above the ink at two times one breath apart; the plan's raw red sum was
  swamped by the ink ground and the eye's glow. The front-view picture test has its eyes 36 px apart, inside
  what the pairing allows. `nodes()` walks blend nodes.
- **`[ambient]` holds more than `fps`** by the end of plans 4 and 5, and the layer rule in `eva.lua` gained
  `wallpaper` and `wall` with them.

The final review found no way for standby to stay up or to keep the keyboard. What it did find was fixed, each
with a test seen failing first (class `StandbyHardening`, and `IdleTest`):

- **The readings raised on the sampler's first answer**, which has no CPU share yet. Standby refused to start
  for two seconds after a reload, and one such answer while it was up took it down.
- **Standby goes by what is on its layers, not by what it believes.** `end()` and `poke()` act on every layer
  that is up, each on its own; `start()` sets its piece only once something is up; a layer that cannot come up
  is not up; `hide()` tells its owner whatever else fails. `lock()` starts the lock screen whatever became of
  standby, and a band that raises does not keep standby up.
- **The check that ends it runs even when the refresh failed**, and the layers of monitors that went away are
  destroyed.
- **The idle child.** A stale one is signalled only when it is hypridle given this config; the child is waited
  for after a kill; a daemon that starts no child still ends one left behind, and waits for it to go.
- **The pictures come from one folder**, the theme's if it brings an `art.json`, else the desk's. The daemon
  keeps one loop, so what it cannot find is said once. `[ambient] fps` is kept between 1 and 120.

---

### Task 1: The pictures

**Files:**
- Create: `tools/gen/gen_rim.py`, `tools/gen/prep_art.py`, `assets/motion/*`
- Test: `tests/test_motion.py` (`ArtTest`)

**Interfaces:**
- Consumes: `tools/gen/gen.py` (`JOBS`, `run(job, n, seed, steps)`, `RAW`).
- Produces:

```python
# tools/gen/gen_rim.py: adds the jobs "r_bust", "r_front", "r_full" to gen.JOBS (the prompts of the local pipeline's gen_rim.py, RIM style only)
# tools/gen/prep_art.py
PICKS = {"profile": "r_bust_5002", "front": "r_front_5000", "full": "r_full_5005"}     # the pictures the desk ships
def black_floor(im) -> ndarray            # float RGB in 0..1, the generator's dark grey set to true black (the edge's 40th percentile, times 1.15)
def split(im, name) -> (body, eye, eyes)  # im after black_floor; body + eye == im; eyes = [[x, y], ...] as fractions of the picture, left to right
                                          # "front" keeps two eyes, the others one; "full" looks for the eye only in the top 22 % of the figure
def write(name, im, out) -> dict          # NAME_body.jpg and NAME_eye.jpg (quality 92) in `out`; returns {"w": .., "h": .., "eyes": [...]}
# python3 tools/gen/prep_art.py OUT [--raw DIR]     -> the three PICKS from DIR (default tools/gen/raw), and OUT/art.json = {name: {w, h, eyes}}
```

`assets/motion/art.json` maps `profile`, `front`, `full` to `{"w", "h", "eyes"}`.

- [ ] **Step 1: Write the failing tests** (`ArtTest`, skipped with a reason when numpy, scipy or Pillow is missing)

```python
    def picture(self, eyes, lights=()):
        """A dark grey 320x200 frame with a pale figure, green eyes at `eyes` and duller green lights at `lights`."""
        import numpy as np
        im = np.full((200, 320, 3), 0.05)
        im[30:190, 120:220] = (0.16, 0.12, 0.2)                # the figure
        for (x, y) in eyes:
            im[y - 2:y + 3, x - 5:x + 6] = (0.2, 1.0, 0.3)
        for (x, y) in lights:
            im[y - 6:y + 7, x - 6:x + 7] = (0.3, 0.75, 0.35)
        return im

    def test_the_layers_add_back_to_the_picture_and_the_eye_is_found(self):
        import numpy as np
        prep = self.prep()                                     # tools/gen/prep_art.py, loaded by path
        im = prep.black_floor(self.picture([(170, 60)]))
        self.assertLess(im[5, 5].max(), 0.001)                 # the ground is true black now
        body, eye, eyes = prep.split(im, "profile")
        self.assertLess(np.abs(body + eye - im).max(), 1e-9)
        self.assertEqual(len(eyes), 1)
        self.assertAlmostEqual(eyes[0][0], 170 / 320, delta=0.01)
        self.assertAlmostEqual(eyes[0][1], 60 / 200, delta=0.01)
        self.assertEqual(eye[150, 40].max(), 0)                # the eye layer is the eye and nothing else
        self.assertLess(body[60, 170, 1], 0.1)                 # and the body has lost its glow

    def test_a_front_view_has_two_eyes_and_a_whole_figure_looks_in_the_head(self):
        prep = self.prep()
        _, _, eyes = prep.split(prep.black_floor(self.picture([(150, 60), (190, 60)])), "front")
        self.assertEqual([round(x * 320) for x, _ in eyes], [150, 190])
        _, _, eyes = prep.split(prep.black_floor(self.picture([(170, 50)], lights=[(170, 120)])), "full")
        self.assertEqual(len(eyes), 1)
        self.assertAlmostEqual(eyes[0][1], 50 / 200, delta=0.02)          # the chest light is larger and lower; it is not the eye

    def test_the_pictures_the_desk_ships(self):
        import json
        art = json.loads((ROOT / "assets/motion/art.json").read_text())
        self.assertEqual(sorted(art), ["front", "full", "profile"])
        self.assertEqual([len(art[n]["eyes"]) for n in ("profile", "front", "full")], [1, 2, 1])
        for name, a in art.items():
            for layer in ("body", "eye"):
                tex = Gdk.Texture.new_from_filename(str(ROOT / f"assets/motion/{name}_{layer}.jpg"))
                self.assertEqual((tex.get_width(), tex.get_height()), (a["w"], a["h"]), name)
            self.assertTrue(all(0 < x < 1 and 0 < y < 1 for x, y in a["eyes"]), name)
        self.assertLess(sum(p.stat().st_size for p in (ROOT / "assets/motion").iterdir()), 1_500_000)
```

- [ ] **Step 2: Run them**: `python3 -m unittest tests.test_motion.ArtTest -v`. Expected: FAIL, `tools/gen/prep_art.py` does not exist.
- [ ] **Step 3: Write `tools/gen/gen_rim.py` and `tools/gen/prep_art.py`.** Both are the local pipeline's scripts made into the interface above: `gen_rim.py` keeps the `U` and `RIM` texts and the three shots word for word; `prep_art.py` keeps the arithmetic of the local `prep_art.py` (the green test `g - max(r, b)`, the dilation by 10 and 48, the 2.5 px blur) inside `split`.
- [ ] **Step 4: Make the assets**: `python3 tools/gen/prep_art.py assets/motion --raw ~/.local/share/sdcpp/eva/gen/raw`. Expected: three lines, `profile: 1 eye(s)`, `front: 2 eye(s)`, `full: 1 eye(s)`, and seven files in `assets/motion`. Read the six JPEGs: each body has no green left at the eye, each eye layer is black but for the glow.
- [ ] **Step 5: Run the tests again.** Expected: PASS (3 tests).
- [ ] **Step 6: One attempt at a larger take.** `nvidia-smi` first (see Global Constraints). Then, for the profile only, an image-to-image run of `sdcpp` from the chosen picture at 2688x1152 with a strength of 0.3 and the same prompt and seed (`sdcpp --help` says whether this build takes an init image; if it does not, stop here). Write the result beside the raw pictures, not into the repo. Make one side-by-side sheet of the eye region at the size a 3440x1440 monitor shows it: the shipped picture scaled up, and the larger take. The shipped pictures stay as they are; the sheet goes to the owner at hand-over with a one-line verdict (same picture or not, sharper or not). Expected: either a sheet, or a ledger line saying why there is none.

---

### Task 2: The kit: pictures that fill a box, a screen blend, a soft band, a ring

**Files:**
- Modify: `eva_desk/motion/kit.py`
- Test: `tests/test_motion.py` (`KitTest`)

**Interfaces:**
- Consumes: the kit of plans 1 and 2 (`_rect`, `_point`, `_rgba`, `clip`, `opacity`, `lines`).
- Produces:

```python
# eva_desk/motion/kit.py
def cover_box(tw, th, x, y, w, h, zoom=1.0, fx=0.5, fy=0.5) -> tuple[float, float, float, float]
    # (ix, iy, iw, ih): where a tw x th picture lies when it fills the box at `zoom`. k = max(w / tw, h / th) * zoom;
    # what overhangs is split by (fx, fy): 0 keeps the picture's left or top edge on the box's, 1 its right or bottom
class Kit:
    def cover(self, texture, x, y, w, h, zoom=1.0, fx=0.5, fy=0.5, alpha=1.0) -> tuple[float, float, float, float]
        # the picture filling the box, cut to it; returns its cover_box, so a point of the picture can be found on screen
    def screen_blend(self, ground)        # context manager: what is painted inside is screened onto what ground() paints.
        # A blend node cannot see what lies under it, so the ground is painted again inside it; black in the picture leaves the ground as it was
    def soft_band(self, cx, half, y0, y1) # context manager: what is painted inside shows only in a vertical band, whole at cx, nothing at cx - half and cx + half
    def ring(self, cx, cy, r, colour, width=2.0, alpha=1.0)
        # a pointy-top hexagon outline of any radius as six segments through lines(): for one whose size changes every frame, where hexagon() would make a picture a frame
```

- [ ] **Step 1: Write the failing tests** (in `KitTest`)

```python
    def halves(self):
        """A 4x2 picture: its left half bone, its right half gold."""
        from eva_desk import draw as d, gtkutil

        def paint(cr):
            d.rgba(cr, d.BONE); cr.rectangle(0, 0, 2, 2); cr.fill()
            d.rgba(cr, d.GOLD); cr.rectangle(2, 0, 2, 2); cr.fill()
        return gtkutil.render_texture(4, 2, paint)

    def test_where_a_picture_lies_when_it_fills_a_box(self):
        from eva_desk.motion.kit import cover_box
        self.assertEqual(cover_box(4, 2, 100, 100, 200, 200), (0.0, 100.0, 400.0, 200.0))           # as high as the box, the sides overhang evenly
        self.assertEqual(cover_box(4, 2, 100, 100, 200, 200, fx=0.0), (100.0, 100.0, 400.0, 200.0))
        self.assertEqual(cover_box(4, 2, 100, 100, 200, 200, fx=1.0), (-100.0, 100.0, 400.0, 200.0))
        self.assertEqual(cover_box(4, 2, 0, 0, 400, 100, zoom=2.0, fy=1.0), (-200.0, -300.0, 800.0, 400.0))
        ix, iy, iw, ih = cover_box(1792, 768, 0, 0, 1720, 720)
        self.assertAlmostEqual(iw, 1720.0)
        self.assertAlmostEqual(ih, 768 * 1720 / 1792)

    def test_cover_fills_the_box_and_nothing_else(self):
        tex = self.halves()
        f = self.frame(lambda k: k.cover(tex, 100, 100, 200, 200, fx=0.0))
        self.assertTrue(near(px(f, 150, 150), BONE) and near(px(f, 240, 290), BONE))               # the left half of the picture (sampled clear of
                                                                                                    # the middle, where four px scaled to 400 run into each other)
        self.assertEqual((alpha(f, 95, 150), alpha(f, 305, 150), alpha(f, 150, 95), alpha(f, 150, 305)), (0, 0, 0, 0))
        f = self.frame(lambda k: k.cover(tex, 100, 100, 200, 200, fx=1.0))
        self.assertTrue(near(px(f, 150, 150), GOLD))
        f = self.frame(lambda k: k.cover(tex, 100, 100, 200, 200, fx=0.0, alpha=0.5))
        self.assertAlmostEqual(alpha(f, 150, 150), 128, delta=2)
        self.assertEqual(pink(f), 0)

    def test_a_screen_blend_leaves_the_ground_where_the_picture_is_black(self):
        from eva_desk import draw as d

        def paint(k):
            with k.screen_blend(lambda: k.rect(0, 0, 400, 300, d.INK)):
                k.rect(0, 0, 400, 300, (0, 0, 0, 1))                       # a picture that is black,
                k.rect(100, 100, 100, 100, d.BONE)                         # but for one bone square
        f = self.frame(paint)
        self.assertTrue(near(px(f, 50, 50), INK, tol=1))
        self.assertTrue(near(px(f, 150, 150), BONE, tol=8))
        self.assertEqual((alpha(f, 410, 50), pink(f)), (0, 0))

    def test_a_soft_band(self):
        from eva_desk import draw as d

        def paint(k):
            with k.soft_band(400, 100, 0, 720):
                k.rect(0, 0, 1720, 720, d.BONE)
        f = self.frame(paint)
        self.assertGreaterEqual(alpha(f, 400, 300), 250)
        self.assertAlmostEqual(alpha(f, 350, 300), 128, delta=14)
        self.assertAlmostEqual(alpha(f, 450, 300), 128, delta=14)
        self.assertEqual((alpha(f, 295, 300), alpha(f, 505, 300), pink(f)), (0, 0, 0))

    def test_a_ring_is_six_lines_of_any_size_and_no_picture(self):
        from eva_desk import draw as d
        from eva_desk.motion import Piece, render

        class P(Piece):
            length = 1.0

            def paint(self, kit, t, ctx):
                kit.ring(300, 300, 100, d.GOLD, 4)
        f = render.frame(P(), 0.0, 1720, 720, {})
        self.assertGreater(alpha(f, 386, 300), 200)            # the right edge stands upright at cx + r cos 30
        self.assertGreater(alpha(f, 343, 375), 200)            # the middle of the edge that runs down to the bottom corner
        self.assertEqual((alpha(f, 300, 300), alpha(f, 420, 300)), (0, 0))
        self.assertEqual(texture_widths(render.build(P(), 0.0, 1720, 720, {})), [])
```

- [ ] **Step 2: Run them**: `python3 -m unittest tests.test_motion.KitTest -v`. Expected: the five new tests FAIL with `ImportError` or `AttributeError`.
- [ ] **Step 3: Implement the five in `kit.py`.** `screen_blend` is `push_blend(Gsk.BlendMode.SCREEN)`, the ground, `pop()`, the picture, `pop()`; `soft_band` is `push_mask(Gsk.MaskMode.ALPHA)` over a three-stop linear gradient (probed: both draw offline with no pink). `cover` clips to the box and appends the texture at its `cover_box`. Add the four to the list in the module docstring's first paragraph.
- [ ] **Step 4: Run `KitTest`.** Expected: PASS.

---

### Task 3: The loop: its frame, its clock, the field

**Files:**
- Create: `eva_desk/motion/amb/__init__.py` (a docstring), `eva_desk/motion/amb/standby.py`
- Modify: `eva_desk/motion/__init__.py`, `eva_desk/motion/render.py`, `eva_desk/preview.py`, `eva_desk/__main__.py`
- Test: `tests/test_motion.py` (`StandbyTest`, `RenderTest`)

**Interfaces:**
- Consumes: Task 2's `ring`; `kit.hexagon`, `hex_cells`, `hazard`, `segbar`, `text`, `measure`, `clip`; `timeline`.
- Produces:

```python
# eva_desk/motion/__init__.py
def loops() -> dict        # {"standby": StandbyLoop}: the pieces with no end
def everything() -> dict   # pieces() and then loops(): what the renderer draws
# eva_desk/motion/amb/standby.py
SHOT = 15.0      # seconds a shot
BAR = 44.0       # the letterbox bars
LEAVE = 0.19     # the fold away
ORDER = ("profile", "field", "tilt", "stare")
PICTURE = {"profile": "profile", "tilt": "full", "stare": "front"}        # the picture each shot needs; the field needs none
def shot_at(t, shots) -> tuple[str, float, int]     # the shot at t, how far through it (0..1), and its place in `shots`
def breathe(t) -> float                             # 0.70 + 0.30 sin(2 pi t / 6): the eyes, between 0.40 and 1.00
def passing(t) -> float                             # ((t % 9) / 9) * 1.6 - 0.3: the middle of the passing light, in widths of the picture's box
def tilt(u) -> float                                # 1 - smooth(seg(u, 0.04, 0.74)): the pan of the tilt, 1 at the feet and 0 at the head
def fold(since) -> tuple[float, float, bool]        # leaving: the share of the width and of the height still shown, and whether what is left is the bone line
class StandbyLoop(Piece):
    name = "standby"; length = None; lap = 60.0; covers = True; still = 4.0
    def __init__(self, folder=None)                 # where the pictures are; None = the theme's or the desk's assets/motion (config.asset_path)
    def shots(self) -> list[str]                    # ORDER without the shots whose picture is not there; never empty
```

`ctx`: `clock` (`"22:44"`, default `"00:00"`), `second` (0 to 60, default 0), `date` (`"TUE 13 OCT"`, default `""`), `readings` (a list of strings, default none), `leaving` (seconds since the exit began; default `None`, not leaving). `seconds` is already berserk's, hence `second`.

In this task `shots()` is `["field"]`: the pictures come in Task 4.

The frame, on every shot (y from the top, `H` the frame's height):

| What | Where | How |
|---|---|---|
| ground | the whole frame | `ink` |
| bars | `0..44` and `H-44..H`, over the shot | `ink` |
| hazard edges | 4 px at `y = 40` and at `y = H-44` | `kit.hazard(..., d.CLARET, None, period=24, offset=4t)` above, `offset=-4t` below |
| `待機 ・ STANDBY` | baseline `(28, 27)` | mincho 15, gold, spacing 2 |
| the readings | baseline `(W-28, 26)`, right | mono 11, bone3, spacing 2, joined by four spaces, cut to the width left of the title |
| `SHOT 01 / 04` | baseline `(28, H-16)` | mono 11, bone3, spacing 3; the shot's place and how many there are |
| `任意のキーで復帰 ・ ANY KEY` | baseline `(W-28, H-15)`, right | mincho 12, bone3, spacing 2 |

The clock, `_clock(kit, ctx, x, y, size, align)`: the time in mincho `size`, bone, baseline `y`, its left edge `bx` at `x` (or `x` less its width when `align` is `"right"`). Under it a 60-segment gold bar at `(bx + 0.03 size, y + 0.13 size)`, as wide as the time less `0.06 size`, `max(4, 0.035 size)` high, lit to `second / 60` (clamped). Under that the date, mincho `max(13, 0.13 size)`, bone2, spacing 3, baseline `0.16 size` below the bar.

The field:

| What | Geometry |
|---|---|
| lattice | `hex_cells` of radius 64 over the frame, shifted by `(-5t, -3t)`; each cell an outline of radius 61, claret at 0.30, 2 px |
| breathing cells | a cell with `noise(col, row) > 0.7` is also filled, claret at `0.26 b²`, `b = max(0, sin(2π (t / 9 + noise(col, row))))` |
| ring | `kit.ring` at `(0.26 W, 0.5 H)`, radius `40 + 0.8 H · cubic_out(p)`, gold, 2 px, alpha `0.4 (1 - p)^1.5`, `p = (t % 7) / 7` |
| `待機` | baseline `(104, H/2 + 70)`, mincho 200, bone |
| `STANDBY ・ ALL SYSTEMS HELD` | baseline `(112, H/2 + 112)`, mono 13, spacing 5, `d.RED` |
| clock | 240, right, at `(W - 110, H/2 + 60)` |

Leaving (`ctx["leaving"] = s`): `f = stepped(s / 0.14, 3)`; the frame is cut to a centred box `W · wf` by `H · hf` with `hf = 1 - 0.98 f` and `wf = 1 - cubic_in(seg(s, 0.14, 0.19))`; once `f` is 1 the box is filled bone (the line). From `s = 0.19` nothing is painted. Outside the box nothing is painted, so the desk shows.

- [ ] **Step 1: Write the failing tests** (`StandbyTest`; `FIX = render.fixture_ctx()`; `loop()` returns `StandbyLoop(folder=<an empty temp dir>)`, so only the field plays, and asks it for `shots()` once with stdout swallowed, since from Task 4 a loop says once which pictures it could not find)

```python
    def test_the_pure_parts(self):
        S = self.S                                             # eva_desk.motion.amb.standby
        four = list(S.ORDER)
        self.assertEqual([S.shot_at(t, four)[0] for t in (0, 14.99, 15, 44.99, 45, 60, 75)],
                         ["profile", "profile", "field", "tilt", "stare", "profile", "field"])
        self.assertEqual(S.shot_at(52.5, four), ("stare", 0.5, 3))
        self.assertEqual(S.shot_at(52.5, ["field"]), ("field", 0.5, 0))
        self.assertAlmostEqual(S.breathe(0), 0.70)
        self.assertAlmostEqual(max(S.breathe(i / 50) for i in range(300)), 1.0, places=3)
        self.assertAlmostEqual(min(S.breathe(i / 50) for i in range(300)), 0.40, places=3)
        for t, where in ((0, -0.3), (4.5, 0.5), (9, -0.3), (8.99, 1.2982)):
            self.assertAlmostEqual(S.passing(t), where, places=3)
        self.assertEqual((S.tilt(0.0), S.tilt(0.04), S.tilt(0.74), S.tilt(1.0)), (1.0, 1.0, 0.0, 0.0))
        self.assertEqual(S.fold(0.0), (1.0, 1.0, False))
        self.assertAlmostEqual(S.fold(0.02)[1], 1 - 0.98 / 3)
        self.assertAlmostEqual(S.fold(0.06)[1], 1 - 0.98 * 2 / 3)
        self.assertEqual(S.fold(0.10)[0], 1.0)
        self.assertAlmostEqual(S.fold(0.10)[1], 0.02)
        self.assertTrue(S.fold(0.10)[2])
        self.assertAlmostEqual(S.fold(0.165)[0], 0.875)
        self.assertEqual(S.fold(0.19)[0], 0.0)

    def test_the_registry_keeps_loops_apart(self):
        from eva_desk import motion
        self.assertEqual(list(motion.loops()), ["standby"])
        self.assertNotIn("standby", motion.pieces())           # eva-ctl play must never be handed a piece with no end
        self.assertEqual(list(motion.everything()), list(motion.pieces()) + ["standby"])
        self.assertEqual((motion.loops()["standby"]().length, self.loop().shots()), (None, ["field"]))

    def test_the_field(self):
        f = render.frame(self.loop(), 3.0, 1720, 720, FIX)
        self.assertEqual(set(grid(f)), {255})                  # the whole frame is covered
        self.assertTrue(near(px(f, 860, 20), INK) and near(px(f, 860, 700), INK))        # the bars
        self.assertEqual(pink(f), 0)
        node = render.build(self.loop(), 3.0, 1720, 720, FIX)
        self.assertTrue({240.0, 200.0} <= glyph_sizes(node))   # the clock and 待機, as glyphs at their own size
        self.assertFalse(same(f, render.frame(self.loop(), 4.0, 1720, 720, FIX)))        # it moves

    def test_the_clock_shows_what_it_is_given(self):
        a = render.frame(self.loop(), 3.0, 1720, 720, {**FIX, "second": 10})
        b = render.frame(self.loop(), 3.0, 1720, 720, {**FIX, "second": 50})
        c = render.frame(self.loop(), 3.0, 1720, 720, {**FIX, "clock": "09:05"})
        self.assertFalse(same(a, b) or same(a, c))

    def test_nothing_is_made_after_the_first_frame(self):
        from eva_desk.motion.kit import Kit
        store, loop, sizes = {}, self.loop(), []
        for t in (2.0, 2.5, 9.0, 13.9):                        # the ring grows through all of these
            snap = Gtk.Snapshot()
            kit = Kit(snap, 1720, 720, 1.0, store)
            loop.paint(kit, t, FIX)
            kit.close()
            sizes.append(len(store))
        self.assertEqual(len(set(sizes)), 1, sizes)

    def test_it_folds_away(self):
        loop = self.loop()
        f = render.frame(loop, 3.0, 1720, 720, {**FIX, "leaving": 0.02})
        self.assertEqual((alpha(f, 860, 100), alpha(f, 860, 360), alpha(f, 860, 620)), (0, 255, 0))      # two thirds of the height are left
        f = render.frame(loop, 3.0, 1720, 720, {**FIX, "leaving": 0.10})
        self.assertTrue(near(px(f, 860, 360), BONE) and near(px(f, 20, 360), BONE))                      # the line, the whole width
        self.assertEqual((alpha(f, 860, 340), alpha(f, 860, 380)), (0, 0))
        f = render.frame(loop, 3.0, 1720, 720, {**FIX, "leaving": 0.165})
        self.assertEqual((alpha(f, 60, 360), alpha(f, 860, 360)), (0, 255))                              # the line closes from both ends
        self.assertIsNone(box(render.frame(loop, 3.0, 1720, 720, {**FIX, "leaving": 0.19})))
        self.assertIsNone(box(render.frame(loop, 3.0, 1720, 720, {**FIX, "leaving": 5.0})))

    def test_it_paints_with_nothing_and_with_odd_inputs(self):
        for ctx in ({}, {"second": 59.99}, {"second": 75}, {"second": -1}, {"clock": "9:05", "readings": []},
                    {"readings": ["X" * 400]}, {"date": "مرحبا"}):
            for w, h in ((1720, 720), (1920, 1080), (1080, 1920)):
                f = render.frame(self.loop(), 3.0, w, h, ctx)
                self.assertEqual((set(grid(f)), pink(f)), ({255}, 0), (ctx, w, h))

    def test_a_week_in(self):
        t = 7 * 86400 + 3.0
        f = render.frame(self.loop(), t, 1720, 720, FIX)
        self.assertEqual((set(grid(f)), pink(f)), ({255}, 0))
        self.assertTrue(same(f, render.frame(self.loop(), t, 1720, 720, FIX)))
```

In `RenderTest`: the tests that walk `pieces()` to say what `--render` and `--render-motion` write walk `everything()`; `test_the_registry` keeps asserting `pieces()` is the six sequences.

- [ ] **Step 2: Run them**: `python3 -m unittest tests.test_motion.StandbyTest tests.test_motion.RenderTest -v`. Expected: FAIL, no module `eva_desk.motion.amb`.
- [ ] **Step 3: Implement.** `amb/standby.py` as above, the frame and the clock as their own functions. `motion/__init__.py`: `loops()`, `everything()`. `render.py`: `render_motion` and its unknown-name check walk `everything()`; `fixture_ctx()` gains `"second": 37.0, "date": "TUE 13 OCT", "readings": ["MAGI·1 CPU 07%", "MAGI·2 RAM 9.8G", "MAGI·3 LAN ↓340K"]`. `preview.motion_stills` and the name list in `__main__.py` walk `everything()`.
- [ ] **Step 4: Run them, then the whole suite.** Expected: PASS; `python3 -m unittest discover -s tests` is green.
- [ ] **Step 5: Look.** `python3 -m eva_desk --render-motion render/plan3 --only standby`, and again with `--size 1080x1920` into `render/plan3-tall`. Read both sheets against the mock-up: the lattice, the breathing cells, the ring, the two bars and their edges, the clock with its bar and date.

---

### Task 4: The three pictures: the profile, the tilt, the stare

**Files:**
- Modify: `eva_desk/motion/amb/standby.py`
- Test: `tests/test_motion.py` (`StandbyTest`)

**Interfaces:**
- Consumes: Task 1's `assets/motion` and `art.json`; Task 2's `cover`, `cover_box`, `screen_blend`, `soft_band`; `kit.radial`.
- Produces: the pictures are loaded once (`Gdk.Texture.new_from_filename`) by whichever of `prepare`, `paint` and `shots()` is called first, and `release()` drops them, so the next call loads them again. A picture whose `art.json` entry or either layer is missing or unreadable is logged once for the life of the loop (`eva-desk: standby: <name>: <why>`; one line, `eva-desk: standby: no pictures: <why>`, when `art.json` itself cannot be read) and its shot is left out of `shots()`.

How a picture goes on, inside its box (`x, y, w, h`) at a camera (`zoom, fx, fy`), all cut to the box:

1. the body layer at `body`, screened onto the ink;
2. the body layer again at `light`, inside `soft_band(x + passing(t) · w, half · w, y, y + h)`, screened onto that;
3. the eye layer at `breathe(t)`, screened onto that;
4. at each eye (found through `cover_box`), `kit.radial(ex, ey, glow, d.GOLD, 0.34 · breathe(t))`, for the eyes that lie inside the box.

| Shot | Picture | Box (wide frame) | Camera | `body`, `light`, `half` | `glow` | Clock |
|---|---|---|---|---|---|---|
| profile | `profile` | the whole frame | `zoom = 1 + 0.07u`, anchored on the eye (`0.6, 0.33` with none) | 0.62, 0.70, 0.16 | 190 | 150; left at `(96, H-176)` when the eye is right of the middle, else right at `(W-96, H-176)` |
| tilt | `full` | `(0.50 W, 44, 0.46 W, H-88)` | `zoom = 1`, `fx = 0.5`, `fy = tilt(u)` | 0.66, 0.60, 0.30 | 110 | 220, left at `(110, H/2 + 60)` |
| stare | `front` | the whole frame | `zoom = 1.10 - 0.08u`, anchored between the eyes (`0.5, 0.4` with none) | 0.62, 0.70, 0.16 | 150 | 104, left at `(84, 186)` |

On a frame taller than it is wide (`H > W`):

| Shot | Box | Clock |
|---|---|---|
| profile, stare | a band the frame's width and `0.5625 W` high, at `y = 0.38 (H - 0.5625 W)` | profile: 150, left, baseline 200 under the band; stare: 104, left, baseline 48 over the band |
| tilt | `(0.06 W, 64, 0.88 W, 1.32 W)`: the whole figure, so there is no pan left | 220, left at `(110, 64 + 1.32 W + 250)` |
| field | as on a wide frame | as on a wide frame |

- [ ] **Step 1: Write the failing tests** (`StandbyTest`; `real()` is `StandbyLoop()`, the shipped pictures; `ART` is `art.json`)

```python
    def test_the_four_shots(self):
        loop = self.real()
        self.assertEqual(loop.shots(), ["profile", "field", "tilt", "stare"])
        sizes = {1.0: 150.0, 16.0: 240.0, 31.0: 220.0, 46.0: 104.0}                # the clock moves place and size every shot
        for t, clock in sizes.items():
            node = render.build(loop, t, 1720, 720, FIX)
            self.assertIn(clock, glyph_sizes(node), t)
            widths = set(texture_widths(node))
            self.assertEqual(1792 in widths, t in (1.0, 46.0), t)
            self.assertEqual(896 in widths, t == 31.0, t)
            f = render.frame(loop, t, 1720, 720, FIX)
            self.assertEqual((set(grid(f)), pink(f)), ({255}, 0), t)
            self.assertTrue(near(px(f, 860, 20), INK) and near(px(f, 860, 700), INK), t)       # the bars lie over the picture

    def test_the_picture_is_nearly_all_black(self):
        f = render.frame(self.real(), 1.0, 1720, 720, {})
        data, lit = bytes(f.get_data()), 0
        for i in range(0, len(data), 4 * 97):
            lit += max(data[i:i + 3]) > 60
        self.assertLess(lit / (len(data) / (4 * 97)), 0.25)
        self.assertGreater(lit, 20)                                                # but the Eva is there

    def test_the_eyes_breathe(self):
        from eva_desk.motion.kit import cover_box
        loop, a = self.real(), ART["profile"]
        ex, ey = a["eyes"][0]

        def eye(t):                                            # the green at the eye; the camera pushes in on it, so it stays put
            ix, iy, iw, ih = cover_box(a["w"], a["h"], 0, 0, 1720, 720, 1 + 0.07 * t / 15, ex, ey)
            return px(render.frame(loop, t, 1720, 720, FIX), ix + ex * iw, iy + ey * ih)[1]
        self.assertGreater(eye(1.5), eye(4.5) + 30)            # breathe is 1.0 at 1.5 s and 0.4 at 4.5 s

    def test_the_light_passes(self):
        loop = self.real()

        def red(t, x0, x1):                                    # the eye is green; the rim is white, so red is the armour alone
            data, stride = bytes(render.frame(loop, t, 1720, 720, FIX).get_data()), 1720 * 4
            return sum(data[y * stride + x * 4 + 2] for y in range(60, 660, 7) for x in range(x0, x1, 7))
        ex = ART["profile"]["eyes"][0][0]
        x0, x1 = int(1720 * ex) - 200, int(1720 * ex) + 200    # the head
        lit = 9 * (ex + 0.3) / 1.6                             # when the band's middle is on the eye
        dark = (lit + 4.5) % 9                                 # and when it is as far away as it gets
        self.assertGreater(red(lit, x0, x1), 1.15 * red(dark, x0, x1))

    def test_a_picture_that_is_missing_or_broken_drops_its_shot(self):
        import shutil
        src = ROOT / "assets/motion"
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            for p in src.iterdir():
                shutil.copy(p, tmp / p.name)
            (tmp / "full_eye.jpg").unlink()
            (tmp / "front_body.jpg").write_bytes(b"not a picture")
            with contextlib.redirect_stdout(io.StringIO()) as out:
                loop = self.S.StandbyLoop(folder=tmp)
                self.assertEqual(loop.shots(), ["profile", "field"])
                self.assertEqual(loop.shots(), ["profile", "field"])
                loop.release()
                self.assertEqual(loop.shots(), ["profile", "field"])                 # loaded again, and not said again
            self.assertEqual(out.getvalue().count("eva-desk: standby:"), 2)          # each said once
            self.assertEqual(self.S.shot_at(31.0, loop.shots())[0], "profile")       # two shots: a lap is thirty seconds
            (tmp / "art.json").write_text("{")
            with contextlib.redirect_stdout(io.StringIO()) as out:
                self.assertEqual(self.S.StandbyLoop(folder=tmp).shots(), ["field"])
            self.assertEqual(len(out.getvalue().splitlines()), 1)

    def test_every_shot_at_every_size(self):
        loop = self.real()
        for w, h in ((3440, 1440), (1920, 1080), (1080, 1920)):
            for t in (1.0, 16.0, 31.0, 46.0):
                f = render.frame(loop, t, w, h, FIX)
                self.assertEqual((set(grid(f)), pink(f)), ({255}, 0), (w, h, t))
                self.assertTrue(same(f, render.frame(loop, t, w, h, FIX)), (w, h, t))

    def test_on_a_tall_frame_the_clock_stands_clear_of_the_picture(self):
        s = 1080 / 1280                                        # px to the design px on a 1080x1920 frame
        H = 1920 / s
        band = 0.38 * (H - 0.5625 * 1280)
        node = render.build(self.real(), 1.0, 1080, 1920, FIX)
        self.assertIn(round(150 * s, 2), glyph_sizes(node))
        f = render.frame(self.real(), 1.0, 1080, 1920, {})
        self.assertTrue(near(px(f, 540, (band - 60) * s), INK))                    # over the band there is only ink

    def test_release_drops_the_pictures_and_it_paints_again(self):
        loop = self.real()
        render.frame(loop, 1.0, 1720, 720, FIX)
        loop.release()
        self.assertEqual(loop.shots(), ["profile", "field", "tilt", "stare"])
        self.assertEqual(pink(render.frame(loop, 1.0, 1720, 720, FIX)), 0)
```

`test_nothing_is_made_after_the_first_frame` of Task 3 gains the three picture shots: with `real()`, the store's size after `t = 1.0` equals its size after `t = 8.0` and `14.0`, and likewise within the tilt and the stare.

- [ ] **Step 2: Run them**: `python3 -m unittest tests.test_motion.StandbyTest -v`. Expected: the new tests FAIL (`shots()` is `["field"]`).
- [ ] **Step 3: Implement** the picture loading, `shots()`, the one function that puts a picture on (the four steps above), the three shots and the tall layout.
- [ ] **Step 4: Run them, then the whole suite.** Expected: PASS, suite green.
- [ ] **Step 5: Look and measure.** Render `standby` at 1720x720, 3440x1440 and 1080x1920 into `render/plan3*`; read the three sheets against the mock-up (the black of the picture is the ink with no seam at the tilt's column; the eye glows; the rim brightens under the light). Note the mean and the worst `build` time of a frame at 3440x1440 for each shot (the workspace's `worst.py`); a frame has 33 ms at 30 a second. If the field costs more than 4 ms, draw its outlines as one `kit.tile` of a two-cell picture and measure again.

---

### Task 5: When it may start, and what counts as movement

**Files:**
- Modify: `eva_desk/motion/triggers.py`
- Test: `tests/test_motion.py` (`TriggersTest`)

**Interfaces:**
- Consumes: `game_open`, `fullscreen_monitors`.
- Produces:

```python
# eva_desk/motion/triggers.py
def standby_blocked(monitors, clients, patterns, locked) -> str
    # why standby may not start, or must end: "locked" (locked is True), "game", "fullscreen", else "". The first that holds, in that order.
    # locked None (Hyprland did not say) does not block; monitors or clients None count as none
class Travel:
    """Whether the pointer has really moved: more than LIMIT px from where it last rested."""
    LIMIT = 8.0      # px
    REST = 1.0       # seconds without a report: where it is seen next is where it rests
    def moved(self, x, y, now) -> bool
def readings(res) -> list[str]
    # the sampler's state as the three readings: ["MAGI·1 CPU 07%", "MAGI·2 RAM 9.8G", "MAGI·3 LAN ↓340K"]; [] with no state
```

- [ ] **Step 1: Write the failing tests** (in `TriggersTest`)

```python
    def test_what_blocks_standby(self):
        T = self.T
        mons = [{"id": 0, "name": "DP-1", "activeWorkspace": {"id": 1}}, {"id": 1, "name": "DP-2", "activeWorkspace": {"id": 5}}]
        game = {"class": "steam_app_1145360", "workspace": {"id": 9}, "monitor": 0, "fullscreen": 0}      # on a workspace nobody is looking at
        full = {"class": "mpv", "workspace": {"id": 5}, "monitor": 1, "fullscreen": 2}                    # on the other monitor
        term = {"class": "kitty", "workspace": {"id": 1}, "monitor": 0, "fullscreen": 0}
        pats = ["^steam_app_", "^gamescope$"]
        self.assertEqual(T.standby_blocked(mons, [term], pats, False), "")
        self.assertEqual(T.standby_blocked(mons, [term, game], pats, False), "game")
        self.assertEqual(T.standby_blocked(mons, [term, full], pats, False), "fullscreen")
        self.assertEqual(T.standby_blocked(mons, [term, game, full], pats, True), "locked")
        self.assertEqual(T.standby_blocked(mons, [term], pats, None), "")
        self.assertEqual(T.standby_blocked(None, None, pats, None), "")

    def test_travel(self):
        tr = self.T.Travel()
        self.assertFalse(tr.moved(500, 500, 0.0))              # the layer came up under a resting pointer
        self.assertFalse(tr.moved(504, 503, 0.1))              # 5 px
        self.assertFalse(tr.moved(506, 505, 0.2))              # 7.8 px
        self.assertTrue(tr.moved(507, 506, 0.3))               # 9.2 px
        tr = self.T.Travel()                                   # a mouse on a desk that shakes: a pixel every few seconds
        self.assertFalse(any(tr.moved(500 + i, 500, 3.0 * i) for i in range(40)))
        tr = self.T.Travel()                                   # a slow hand is still a hand
        self.assertTrue(any(tr.moved(500 + i, 500, 0.2 * i) for i in range(12)))

    def test_readings(self):
        T = self.T
        res = {"cpu": 7, "mem": "9.8G", "mem_pct": 31, "net": "lan", "down": "340K", "show": []}
        self.assertEqual(T.readings(res), ["MAGI·1 CPU 07%", "MAGI·2 RAM 9.8G", "MAGI·3 LAN ↓340K"])
        self.assertEqual(T.readings({**res, "cpu": 100, "net": "wifi"})[::2], ["MAGI·1 CPU 100%", "MAGI·3 WIFI ↓340K"])
        self.assertEqual(T.readings({**res, "net": ""})[2], "MAGI·3 NET ↓340K")
        self.assertEqual((T.readings(None), T.readings({})), ([], []))
```

- [ ] **Step 2: Run them**: `python3 -m unittest tests.test_motion.TriggersTest -v`. Expected: the three FAIL with `AttributeError`.
- [ ] **Step 3: Implement the three.**
- [ ] **Step 4: Run `TriggersTest`.** Expected: PASS.

---

### Task 6: The host: `AmbientLayer` and `Standby`

**Files:**
- Modify: `eva_desk/motion/player.py` (and its module docstring)
- Test: `tests/test_motion.py` (`AmbientTest`, `StandbyScreens`, both on `NoCompositor`)

**Interfaces:**
- Consumes: `_Overlay`, `Kit`, `triggers.Travel`, `amb.standby.LEAVE`.
- Produces:

```python
# eva_desk/motion/player.py
class AmbientLayer(_Overlay):
    """A loop on one monitor. It repaints from a timer, fps times a second, at the time it is told: now less the epoch it was shown with."""
    def __init__(self, app, namespace, fps=30, keyboard="none")      # also the controllers: a key press (never a release), a press of any button
                                                                     # and pointer motion call poke(); the key press is reported as handled
    def setup(self)                         # the state of a layer with nothing on it
    up: bool                                # a piece is on it (leaving included)
    def show(self, piece, gdk_monitor, inputs, epoch) -> bool
        # place, prepare, show, start the timer. `inputs()` gives the ctx of each repaint. False, and nothing shown, with no monitor or when prepare raises.
        # The layer does not own the piece: prepare may be called on one piece by several layers, and whoever made the piece releases it.
    def beat(self, now)                     # one repaint: at = now - epoch, ctx = inputs() (and "leaving" while it leaves), queue a draw; hides once the leave is over
    def leave(self, now, seconds)           # give the pointer and the keyboard back at once; paint the piece leaving for `seconds`, every 8 ms; then hide
    def hide(self)                          # stop the timer, hide, drop the stamps
    def poke(self, kind, x=0.0, y=0.0)      # "key" | "click" | "motion", passed to on_poke(layer, kind, x, y) while up and not leaving
    on_poke = None                          # set by the owner
    on_broken = None                        # called (from the main loop) with the layer when its piece raised in paint; the layer has hidden itself
    on_hidden = None                        # called with the layer each time hide() took a piece down
    # seams the tests replace: _every(ms, fn) -> id, _cancel(id), _after(ms, fn), _keyboard(mode)

class Standby:
    """The standby loop on every monitor: a layer each, one clock for all of them, and what ends it."""
    def __init__(self, app, fps=30, make=AmbientLayer, clock=time.monotonic)
    up: bool
    on_end = None                           # called once each time it has gone from every monitor
    def start(self, piece, gdk_monitors, inputs) -> bool      # True when it is up (also when it already was: the clock is not restarted); False when no monitor could show it
    def poke(self, layer, kind, x=0.0, y=0.0)                # a key or a click ends it; motion ends it when that layer's Travel says the pointer moved
    def end(self, at_once=False)            # fold away over LEAVE seconds on every monitor, or go at once; release the piece when the last layer is gone
    def monitors(self) -> list              # the monitors it is up on
    def layers(self) -> list                # its layers, in the order their monitors were first given
    def forget(self, alive)                 # destroy the layers of monitors that are not among `alive`
```

The layer's namespace is `eva-standby`, its keyboard mode `exclusive`, on every monitor: whichever the compositor gives the keyboard to ends it for all. A layer that leaves sets its input region empty and its keyboard mode to `none` before the first leaving frame, and `show` sets both back. Hiding at the end of a leave never waits on a paint: the timer does it, and `_after(seconds * 1000 + 150)` does it again in case the timer was lost.

- [ ] **Step 1: Write the failing tests.** `ambient()` builds an `AmbientLayer` the way `player()` builds a `SequencePlayer` (no window: `FakeWin`, `FakeView`; `_every`, `_cancel`, `_after` and `_keyboard` record into lists). `screens(n=2)` builds a `Standby` whose `make` is `ambient`, with a clock the test sets.

```python
class AmbientTest(NoCompositor):
    def test_it_repaints_from_a_timer_at_the_time_it_is_told(self):
        a, piece, asked = ambient(fps=30), dummy(), []
        self.assertTrue(a.show(piece, MON, lambda: asked.append(1) or {"clock": "22:44"}, epoch=100.0))
        self.assertTrue(a.win.visible and a.up)
        self.assertEqual([ms for ms, _ in a.timers], [33])
        self.assertFalse(a.win.surface.region.is_empty())      # it takes the pointer
        a.beat(107.5)
        self.assertEqual((a.at, a.ctx, len(asked)), (7.5, {"clock": "22:44"}, 1))
        a.hide()
        self.assertEqual((a.win.visible, a.up, a.cancelled, piece.released), (False, False, [1], 0))     # the piece is not the layer's to release

    def test_no_monitor_and_a_piece_that_cannot_prepare(self):
        a = ambient()
        self.assertFalse(a.show(dummy(), None, dict, 0.0))
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertFalse(a.show(dummy(boom="prepare"), MON, dict, 0.0))
        self.assertEqual((a.win.visible, a.up, a.timers), (False, False, []))

    def test_leaving(self):
        a, seen = ambient(), []
        a.show(dummy(), MON, dict, 0.0)
        a.on_poke = lambda layer, kind, x, y: seen.append(kind)
        a.poke("key")
        a.leave(50.0, 0.19)
        self.assertTrue(a.win.surface.region.is_empty())       # the pointer goes through from now on
        self.assertEqual(a.keyboard[-1], "none")
        self.assertEqual(a.timers[-1][0], 8)
        a.poke("key")                                          # what comes now is not for it
        self.assertEqual(seen, ["key"])
        a.beat(50.1)
        self.assertAlmostEqual(a.ctx["leaving"], 0.1)
        self.assertTrue(a.win.visible)
        a.beat(50.2)
        self.assertFalse(a.win.visible or a.up)

    def test_a_leave_ends_even_if_the_timer_never_runs(self):
        a = ambient()
        a.show(dummy(), MON, dict, 0.0)
        a.leave(50.0, 0.19)
        ms, fn = a.afters[-1]
        self.assertEqual(ms, 340)
        fn()
        self.assertFalse(a.win.visible)
        a.show(dummy(), MON, dict, 0.0)                        # and a late one from an old run does not hide the next
        fn()
        self.assertTrue(a.win.visible)
        self.assertEqual(a.keyboard[-1], "exclusive")

    def test_a_piece_that_raises_is_taken_down(self):
        a, broke = ambient(), []
        a.on_broken = broke.append
        a.show(dummy(boom="paint"), MON, dict, 0.0)
        with contextlib.redirect_stdout(io.StringIO()):
            a._paint(Gtk.Snapshot(), 1720, 720)
            a._paint(Gtk.Snapshot(), 1720, 720)                # nothing more is painted
        self.assertTrue(a.win.visible)                         # GTK is in the middle of drawing that window
        for ms, fn in a.afters:
            fn()
        self.assertEqual((a.win.visible, broke), (False, [a]))


class StandbyScreens(NoCompositor):
    def test_one_clock_on_every_monitor(self):
        s, piece = screens()
        s.now = 100.0
        self.assertTrue(s.start(piece, [MON, MON2], dict))
        self.assertEqual((s.up, s.monitors()), (True, [MON, MON2]))
        self.assertEqual({layer.epoch for layer in s.layers()}, {100.0})
        s.now = 130.0
        self.assertTrue(s.start(piece, [MON, MON2], dict))     # already up: the clock is not restarted
        self.assertEqual({layer.epoch for layer in s.layers()}, {100.0})

    def test_what_ends_it(self):
        s, piece = screens()
        ended = []
        s.on_end = lambda: ended.append(1)
        s.start(piece, [MON, MON2], dict)
        one, two = s.layers()
        s.now = 10.0
        s.poke(one, "motion", 500, 500)                        # the pointer was resting there
        s.poke(two, "motion", 40, 40)
        s.now = 10.2
        s.poke(one, "motion", 503, 503)
        self.assertTrue(s.up and not one.leaving)
        s.poke(one, "motion", 520, 500)                        # that is a hand
        self.assertTrue(one.leaving and two.leaving)           # everywhere at once
        self.assertEqual((ended, piece.released), ([], 0))     # it is still folding
        for layer in (one, two):
            layer.beat(10.2 + 0.2)
        self.assertEqual((s.up, ended, piece.released), (False, [1], 1))
        for kind in ("key", "click"):
            s.start(piece, [MON, MON2], dict)
            s.poke(s.layers()[1], kind)
            self.assertTrue(all(layer.leaving for layer in s.layers()), kind)
            s.end(at_once=True)                                # at once, also in the middle of a fold
            self.assertFalse(s.up)
        self.assertEqual((len(ended), piece.released), (3, 3))
        s.end()
        s.end(at_once=True)                                    # ending what is not up does nothing
        self.assertEqual(len(ended), 3)

    def test_it_starts_where_it_can(self):
        s, piece = screens()
        self.assertFalse(s.start(piece, [], dict))
        self.assertEqual(piece.released, 1)
        with contextlib.redirect_stdout(io.StringIO()):
            bad = dummy(boom="prepare")
            self.assertFalse(s.start(bad, [MON, MON2], dict))
        self.assertEqual((s.up, bad.released), (False, 1))

    def test_a_layer_that_cannot_paint_ends_it_everywhere(self):
        s, _ = screens()
        piece = dummy(boom="paint")
        s.start(piece, [MON, MON2], dict)
        one, two = s.layers()
        with contextlib.redirect_stdout(io.StringIO()):
            one._paint(Gtk.Snapshot(), 1720, 720)
        for ms, fn in one.afters:
            fn()
        self.assertFalse(s.up or one.win.visible or two.win.visible)
        self.assertEqual(piece.released, 1)

    def test_forget(self):
        s, piece = screens()
        s.start(piece, [MON, MON2], dict)
        s.end(at_once=True)
        s.forget([MON])
        self.assertEqual(len(s.layers()), 1)
```

- [ ] **Step 2: Run them**: `python3 -m unittest tests.test_motion.AmbientTest tests.test_motion.StandbyScreens -v`. Expected: FAIL, `AmbientLayer` is not defined.
- [ ] **Step 3: Implement both in `player.py`.** `AmbientLayer._paint` is `SequencePlayer._paint` with `on_broken` in place of `finish`; share what is the same between the two rather than copying it.
- [ ] **Step 4: Run them, then the whole suite.** Expected: PASS, suite green, no GTK warning in the output.

---

### Task 7: The idle child

**Files:**
- Create: `eva_desk/sources/idle.py`
- Test: `tests/test_sources.py` (`IdleTest`)

**Interfaces:**
- Produces:

```python
# eva_desk/sources/idle.py
def conf(minutes, ctl) -> str      # the hypridle config: one listener, `timeout` in whole seconds (at least 1), `on-timeout` = the quoted path to eva-ctl, then ` standby on`
class Idle:
    """hypridle as the daemon's child, on a config of its own. Stopped by its handle; a stale one is found by the pid it left, never by name."""
    def __init__(self, minutes, ctl, folder, spawn=subprocess.Popen, which=shutil.which, kill=os.kill, proc="/proc")
    def start(self) -> bool        # writes folder/hypridle.conf, ends a stale child, spawns `hypridle -q -c <conf>`, writes folder/hypridle.pid.
                                   # False, and one logged line, when hypridle is not installed or will not start
    def stop(self)                 # terminate, wait a second, kill if it is still there; removes the pid file. Safe to call twice and with no child
    def gone(self) -> bool         # the child was started and has exited by itself; True once, then False (so it is logged once)
```

The config, for `conf(5, "/usr/bin/eva-ctl")`, to the byte:

```
# written by eva-desk from [standby] in eva.toml; changes here are lost
general {
    ignore_dbus_inhibit = false
}

listener {
    timeout = 300
    on-timeout = /usr/bin/eva-ctl standby on
}
```

A stale child: `folder/hypridle.pid` names a process whose `proc/<pid>/cmdline` holds the path of `folder/hypridle.conf`. Only then is it sent `SIGTERM`. A pid file that names anything else, or nothing alive, is just removed.

- [ ] **Step 1: Write the failing tests** (`IdleTest`: a temp folder, a fake `spawn` that records its arguments and returns a fake process with `pid`, `poll`, `terminate`, `wait`, `kill`; a fake `kill`; a fake `proc` folder)

```python
    def test_the_config(self):
        self.assertEqual(idle.conf(5, "/usr/bin/eva-ctl"), EXPECTED)             # the text above
        self.assertIn("timeout = 30\n", idle.conf(0.5, "/usr/bin/eva-ctl"))
        self.assertIn("timeout = 1\n", idle.conf(0.001, "/usr/bin/eva-ctl"))
        self.assertIn("on-timeout = '/home/a b/eva-ctl' standby on\n", idle.conf(5, "/home/a b/eva-ctl"))

    def test_start_and_stop(self):
        i = self.idle(which=lambda name: "/usr/bin/hypridle")
        self.assertTrue(i.start())
        conf = self.folder / "hypridle.conf"
        self.assertEqual(conf.read_text(), idle.conf(5, "/usr/bin/eva-ctl"))
        self.assertEqual(self.spawned, [["hypridle", "-q", "-c", str(conf)]])
        self.assertEqual((self.folder / "hypridle.pid").read_text().strip(), "4242")
        i.stop()
        self.assertEqual((self.proc.terminated, (self.folder / "hypridle.pid").exists()), (1, False))
        i.stop()
        self.assertEqual(self.proc.terminated, 1)

    def test_one_that_will_not_die_is_killed(self):
        i = self.idle(which=lambda name: "/usr/bin/hypridle")
        i.start()
        self.proc.stubborn = True                              # wait() raises TimeoutExpired
        i.stop()
        self.assertEqual((self.proc.terminated, self.proc.killed), (1, 1))

    def test_no_hypridle(self):
        i = self.idle(which=lambda name: None)
        with contextlib.redirect_stdout(io.StringIO()) as out:
            self.assertFalse(i.start())
            self.assertFalse(i.start())
        self.assertEqual((self.spawned, len(out.getvalue().splitlines())), ([], 1))
        self.assertIn("hypridle", out.getvalue())
        i.stop()

    def test_one_that_cannot_be_started(self):
        i = self.idle(which=lambda name: "/usr/bin/hypridle", spawn=self.refuses)        # raises OSError
        with contextlib.redirect_stdout(io.StringIO()) as out:
            self.assertFalse(i.start())
        self.assertIn("hypridle", out.getvalue())

    def test_a_stale_child_is_ended_by_its_pid_and_only_if_it_is_ours(self):
        conf = self.folder / "hypridle.conf"
        self.fake_process(777, f"hypridle\0-q\0-c\0{conf}\0")
        (self.folder / "hypridle.pid").write_text("777\n")
        self.idle(which=lambda name: "/usr/bin/hypridle").start()
        self.assertEqual(self.killed, [(777, signal.SIGTERM)])
        self.killed.clear()
        self.fake_process(888, "firefox\0")                    # the pid was given to something else since
        (self.folder / "hypridle.pid").write_text("888\n")
        self.idle(which=lambda name: "/usr/bin/hypridle").start()
        (self.folder / "hypridle.pid").write_text("not a number\n")
        self.idle(which=lambda name: "/usr/bin/hypridle").start()
        (self.folder / "hypridle.pid").write_text("999\n")     # nothing has that pid
        self.idle(which=lambda name: "/usr/bin/hypridle").start()
        self.assertEqual(self.killed, [])

    def test_it_says_once_that_the_child_went(self):
        i = self.idle(which=lambda name: "/usr/bin/hypridle")
        self.assertFalse(i.gone())
        i.start()
        self.assertFalse(i.gone())
        self.proc.code = 1
        self.assertEqual((i.gone(), i.gone()), (True, False))
```

- [ ] **Step 2: Run them**: `python3 -m unittest tests.test_sources.IdleTest -v`. Expected: FAIL, no module `eva_desk.sources.idle`.
- [ ] **Step 3: Implement `conf` and `Idle`.** The path is quoted with `shlex.quote`. The child's output is not captured: `stdout` goes nowhere, `stderr` to the daemon's log.
- [ ] **Step 4: Run them.** Expected: PASS (7 tests).

---

### Task 8: The daemon

**Files:**
- Modify: `eva_desk/app.py`, `eva_desk/overlays.py`, `eva_desk/config.py`, `config/eva.example.toml`, `hypr/eva.lua`, `bin/eva-ctl`
- Test: `tests/test_motion.py` (`StandbyWiring`), `tests/test_offline.py` where it pins the defaults

**Interfaces:**
- Consumes: `Standby`, `StandbyLoop`, `LEAVE`; `triggers.standby_blocked`, `triggers.readings`; `Idle`; `App._locked`, `_watch_lock`, `_on_sleep`, `_quiet`, `_covered`, `_sync_components`, `lock`, `close_panels`.
- Produces:

```python
# eva_desk/config.py: DEFAULTS
"ambient": {"fps": 30},                                             # how often the loops repaint, a second
"standby": {"enabled": True, "minutes": 5, "idle": "hypridle"},     # minutes 0 = only by `eva-ctl standby`; idle "none" = your own idle tool calls it

# eva_desk/overlays.py
class NotifyWatch:                      # what AlarmBand._watch and _filter were: hears Notify calls with urgency 2 and calls on_critical(note)
    def __init__(self, on_critical)

# eva_desk/app.py
def standby_on(self) -> str             # "ok" | "standby is off ([standby] enabled)" | "motion is not available" | "not now: <why>" | "no monitor"
def standby_off(self, at_once=False) -> str        # "ok"; nothing to do when it is not up
def _standby_inputs(self) -> dict       # clock, second, date, readings: called thirty times a second, so it asks Hyprland nothing
def _standby_check(self)                # while it is up: what blocks a start ends it at once; so does a monitor that came or went
def _on_critical(self, note)            # the band, when there is one, and standby_off()
def _start_idle(self)                   # the hypridle child, when [standby] says so
def _stop_children(self)                # the idle child; before the daemon quits or re-executes
```

Rules:

- `standby_on`: refused with the reason of `standby_blocked` (`"not now: a game is open"`, `"a window is fullscreen"`, `"the session is locked"`); with Hyprland not answering (`OSError`) it is refused as `"not now: Hyprland does not answer"`. When it may start: the launcher, the power menu and Alt+Tab are hidden and the panels closed, `motion.stop()` ends any sequence, and the loop goes up on every monitor GTK knows (`gtkutil.monitors()`), not only the main ones. Already up: `"ok"`, nothing changes.
- The sampler is also made when standby is enabled, and `NotifyWatch` when the band or standby is.
- What ends it at once: `lock()` (before it hands the command over), `_watch_lock` seeing the session locked (that watch now runs when wake or standby is on; the cover logic stays behind `[motion] wake`), `_on_sleep(True)`, `_standby_check` (called at the end of `refresh()` and from `_sync_components`), and the daemon quitting. What ends it with the fold: input (in `Standby`), `standby off`, a critical notification.
- `_quiet()` and `_covered()` are true while standby is up: no berserk, no track card, no spawn pulse, no eye-catch over it.
- `_start_idle`: only with `enabled`, `idle == "hypridle"` and `minutes > 0`; `Idle(minutes, <eva-ctl>, config.STATE_DIR)` where `<eva-ctl>` is `bin/eva-ctl` under `config.ROOT` when that file exists, else `shutil.which("eva-ctl")`, else no child and one logged line. `_clock` asks `idle.gone()` and logs once: `eva-desk: hypridle has exited: standby only by eva-ctl standby on`.
- `_stop_children` runs in `_restart` before `os.execv`, and in `do_shutdown`.
- `command`: `standby` and `standby on` call `standby_on`, `standby off` calls `standby_off`; anything else answers `standby: on | off`. `play standby` answers `standby is a loop: eva-ctl standby on`.
- `hypr/eva.lua`: the `no_anim` rule's list gains `standby` after `motion`. `bin/eva-ctl`: one help line.

- [ ] **Step 1: Write the failing tests** (`StandbyWiring`; `standby_app(**standby)` is `lock_app()` with `app.standby = FakeStandby()` (`start` records into `starts` and sets `up`, `end(at_once)` records into `ends` and clears it; `monitors()` is what it was started on), `app.idle = None`, `app.panels = {}`, `[standby]` updated, and `gtkutil.monitors` patched to give `self.monitors`, the app's two. `FakeHypr` gains `asked`, the requests it was sent, and `fail`, an exception that `j` raises when it is set. `FakePanel` counts `hide()` in `hidden` and `close()` in `closed`, and is `visible`. `FakeIdle.start()` is true)

```python
    def test_the_defaults(self):
        cfg = config.load("/nonexistent")
        self.assertEqual(cfg["standby"], {"enabled": True, "minutes": 5, "idle": "hypridle"})
        self.assertEqual(cfg["ambient"], {"fps": 30})
        self.assertIn("|pulse|motion|standby|panel-", (ROOT / "hypr" / "eva.lua").read_text())

    def test_standby_on(self):
        app = standby_app()
        self.assertEqual(app.command("standby"), "ok")
        (piece, mons, inputs), = app.standby.starts
        self.assertEqual((type(piece).__name__, sorted(mons)), ("StandbyLoop", ["GDK-1", "GDK-2"]))        # every monitor, not only the main one
        self.assertEqual(app.motion.stopped, [None])           # a sequence that was playing has gone
        ctx = inputs()
        self.assertEqual(sorted(ctx), ["clock", "date", "readings", "second"])
        self.assertTrue(0 <= ctx["second"] < 60)
        self.assertEqual(app.command("standby on"), "ok")      # already up
        self.assertEqual(len(app.standby.starts), 1)
        self.assertEqual(app.command("standby off"), "ok")
        self.assertEqual(app.standby.ends, [False])            # with the fold
        self.assertEqual(app.command("standby maybe"), "standby: on | off")
        self.assertEqual(app.command("play standby"), "standby is a loop: eva-ctl standby on")

    def test_the_inputs_ask_hyprland_nothing(self):
        app = standby_app()
        app.command("standby")
        app.hypr.asked = []
        app.standby.starts[0][2]()
        self.assertEqual(app.hypr.asked, [])

    def test_when_it_does_not_start(self):
        game = {"class": "steam_app_1", "workspace": {"id": 9}, "monitor": 0, "fullscreen": 0}
        full = {"class": "mpv", "workspace": {"id": 5}, "monitor": 1, "fullscreen": 2}
        for state, answer in (({"clients": [game]}, "not now: a game is open"), ({"clients": [full]}, "not now: a window is fullscreen"),
                              ({"locked": {"locked": True}}, "not now: the session is locked")):
            app = standby_app()
            app.hypr.state.update(state)
            self.assertEqual((app.command("standby on"), app.standby.starts), (answer, []))
        app = standby_app()
        app.hypr.fail = OSError("gone")
        self.assertEqual(app.command("standby on"), "not now: Hyprland does not answer")
        app = standby_app(enabled=False)
        app.standby = None
        self.assertEqual(app.command("standby on"), "standby is off ([standby] enabled)")
        app = standby_app()
        app.motion = app.standby = None
        self.assertEqual(app.command("standby on"), "motion is not available")

    def test_it_closes_what_holds_the_keyboard(self):
        app = standby_app()
        app.launcher, app.overlays = FakePanel(), {"power": FakePanel(), "alttab": FakePanel()}
        app.panels = {"sound": FakePanel()}
        app.command("standby on")
        self.assertEqual([p.hidden for p in (app.launcher, app.overlays["power"], app.overlays["alttab"])], [1, 1, 1])
        self.assertEqual(app.panels["sound"].closed, 1)

    def test_what_blocks_a_start_also_ends_it(self):
        app = standby_app()
        app.command("standby on")
        app._standby_check()
        self.assertEqual(app.standby.ends, [])
        app.hypr.state["clients"] = [{"class": "gamescope", "workspace": {"id": 3}, "monitor": 0, "fullscreen": 0}]
        app._standby_check()
        self.assertEqual(app.standby.ends, [True])             # at once

    def test_a_monitor_that_goes_away_ends_it(self):
        app = standby_app()
        app.command("standby on")
        self.monitors.pop("DP-2")                              # what gtkutil.monitors() is patched to give
        app._standby_check()
        self.assertEqual(app.standby.ends, [True])

    def test_locking_sleeping_and_a_critical_notification(self):
        app = standby_app()
        app.command("standby on")
        app.lock()
        app.standby.up = True
        app._on_sleep(True)
        app.standby.up = True
        app.hypr.state["locked"] = {"locked": True}
        app.cfg["motion"]["wake"] = False                      # the watch looks for standby's sake too
        app._watch_lock(now=0.0)
        self.assertEqual(app.standby.ends, [True, True, True])
        app.standby.up, band = True, []
        app.overlays = {"alarm": types.SimpleNamespace(show=band.append)}
        app._on_critical({"summary": "disk"})
        self.assertEqual((app.standby.ends[-1], band), (False, [{"summary": "disk"}]))
        app.overlays = {}
        app._on_critical({"summary": "disk"})                  # with no band it still ends standby

    def test_nothing_else_plays_over_it(self):
        app = standby_app()
        self.assertFalse(app._quiet() or app._covered())
        app.command("standby on")
        self.assertTrue(app._quiet() and app._covered())

    def test_the_idle_child_follows_the_settings(self):
        made = []
        for standby, want in (({}, [5]), ({"minutes": 0}, []), ({"idle": "none"}, []), ({"enabled": False}, []), ({"minutes": 12}, [12])):
            app = standby_app(**standby)
            made.clear()
            with mock.patch("eva_desk.sources.idle.Idle", lambda minutes, ctl, folder: made.append((minutes, ctl, folder)) or FakeIdle()):
                app._start_idle()
            self.assertEqual([m[0] for m in made], want, standby)
        self.assertTrue(made[0][1].endswith("bin/eva-ctl"))

    def test_a_reload_stops_the_idle_child_first(self):
        app, order = standby_app(), []
        app.idle = types.SimpleNamespace(stop=lambda: order.append("stop"))
        app.argv = []
        with mock.patch("os.execv", lambda *a: order.append("exec")):
            app._restart()
        self.assertEqual(order, ["stop", "exec"])
        app._stop_children()                                   # twice is fine
        app.idle = None
        app._stop_children()

    def test_the_idle_child_going_is_said_once(self):
        app = standby_app()
        app.idle, app.minute = types.SimpleNamespace(gone=lambda: True), None
        with contextlib.redirect_stdout(io.StringIO()) as out:
            app._clock()
        self.assertIn("hypridle has exited", out.getvalue())
```

Existing tests of the alarm band (`grep -n "AlarmBand\|_filter\|_watch" tests/`) move with the watch: what tested `AlarmBand._filter` tests `NotifyWatch._filter`, and one new test says a note of urgency 2 reaches `on_critical` and one of urgency 1 does not.

- [ ] **Step 2: Run them**: `python3 -m unittest tests.test_motion.StandbyWiring -v`. Expected: FAIL (`KeyError: 'standby'` and missing methods).
- [ ] **Step 3: Implement**, in this order: `config.py`; `NotifyWatch` in `overlays.py` and the band without its own watch; the methods on `App`; `do_activate` (the sampler's condition, `NotifyWatch`, `Standby` with `on_end = self._update_frames`, `_start_idle`, the lock watch's condition); `command`; `_restart` and `do_shutdown`; `eva.lua`; `eva-ctl`; `eva.example.toml`.
- [ ] **Step 4: Run them, then the whole suite.** Expected: PASS, suite green.
- [ ] **Step 5: The Hyprland side.** `luac -p hypr/eva.lua`: no output. Then a scratch copy of the Hyprland config that loads this worktree's `hypr/eva.lua` instead of the installed one, and `HL_VERIFY=1 timeout 20 Hyprland --verify-config -c "$SCRATCH/hyprland.lua"`. Expected: it reports no error and starts no compositor.

---

### Task 9: Documents, and the whole thing verified offline

**Files:**
- Modify: `README.md`, `config/eva.example.toml`, `packaging/PKGBUILD`, `packaging/.SRCINFO` when there is one, `docs/superpowers/specs/2026-10-13-motion-graphics-design.md`, this plan ("Changed during execution")

- [ ] **Step 1: `README.md`.** A "Standby" paragraph after "Sequences": what it is, that it needs `hypridle` to start by itself (or `idle = "none"` and a line in your own idle tool), `eva-ctl standby [on|off]`, what ends it, when it does not start, that it keeps the screens lit and leaves screen-off to your idle tool, and that the three pictures can be replaced per theme (`assets/themes/<name>/motion/`). `hypridle` joins the optional dependencies and the command list gains `standby`. Plain voice; nothing about how the pictures were chosen.
- [ ] **Step 2: `config/eva.example.toml` and `packaging/`.** The two sections with their comments; `hypridle: standby after some idle minutes` in `optdepends`.
- [ ] **Step 3: The spec.** Under "Standby", "The kit", "The player", "Triggers and sources", "Assets", "Configuration", "Error handling" and "Open items": the eight points listed above under "past the letter of the spec", the `ctx` keys, `loops()`, and what Task 1's last step found about a larger picture.
- [ ] **Step 4: Verify offline** (the project's `verify-offline` skill):
  - `python3 -m unittest discover -s tests`. Expected: all green, no warning in the output.
  - `python3 -m eva_desk --render render/all`. Expected: `motion_standby.png` among the files; read it.
  - `python3 -m eva_desk --render-motion render/plan3`, `--size 1080x1920` into `render/plan3-tall`, and `--only standby --size 3440x1440` into `render/plan3-big`. Read the three `standby.png` sheets, and the six earlier pieces' sheets once for anything this plan changed.
  - Task 8 Step 5 again if `eva.lua` changed since.
  - The audio rule does not apply: nothing here makes a sound.
- [ ] **Step 5: This plan.** Add "Changed during execution" with whatever the build and the review changed.
- [ ] **Step 6: The motion rule in `CLAUDE.md`.** The spec rewords it with the first loop: "An event gets one sequence, then the picture holds still. Ambient pieces may loop, slowly. No flashing and no per-beat colour changes anywhere." That file is the owner's own, untracked, in the live main checkout, so this plan does not edit it: the new wording is put to him at hand-over.

## What only a live run can prove

- That `hypridle` starts standby after the minutes, and does not while a video holds an idle inhibitor.
- That one `hypridle` runs after `eva-ctl apply` and none after `eva-ctl quit` (`pgrep -x hypridle`).
- The keyboard: a key ends standby and does not reach the window under it; the next key does; with three monitors, whichever has the focus.
- The pointer: a nudge does not end it, a real move does, a click does and is not passed on.
- That every monitor is covered and they cut together; how the tall layout looks on the side monitor.
- The pictures at their real size on the 3440x1440 monitor (they are shown at about twice the size they were made); the eye's glow; the passing light; the fold.
- The GPU's load while standby runs (`nvidia-smi`): it must stay well clear of full.
- Locking while it is up (it goes, the wake cover takes its place, the unlock plays wake); a critical notification (it folds away, and the EMERGENCY band still comes); sleep and resume.
- A fullscreen window or a game: it does not start.
