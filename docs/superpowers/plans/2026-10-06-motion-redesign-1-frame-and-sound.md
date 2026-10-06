# Motion redesign, plan 1: toggle removal, window frame, MFD language, sound panel

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove the figure toggle, draw the static bracket frame around the focused window, and land the MFD panel language with its first panel (sound settings) inside the eva-desk daemon.

**Architecture:** Everything is a daemon surface in the existing `_Overlay` pattern (a layer-shell window, a `_View` that paints with cairo, a tick animation). New packages `eva_desk/mfd/` (the language and the panels) and `eva_desk/sources/` (data wrappers around the eww audio scripts, which move into the repo) plus `eva_desk/frame.py`. Panel logic lives in GTK-free model classes so it is tested offline; GTK classes only paint and route input.

**Tech Stack:** Python 3.11, GTK 4 + gtk4-layer-shell (PyGObject), cairo, Pango; `unittest` (`python3 -m unittest discover -s tests`); bash data scripts (`pactl`, `dunstctl`, `powerprofilesctl`).

**Spec:** `docs/superpowers/specs/2026-10-06-motion-redesign-design.md` (this plan covers "Build order" steps 1 and 2; music/OSD, notifications, the other panels and the launch sequence follow in later plans).

## Global Constraints

- Colours are theme roles through `draw.py` (`d.INK`, `d.CLARET`, `d.GOLD`, `d.BONE`, `d.LED`, `d.DIM`, `d.col("ink3")`), never hex literals in modules (spec: "new colours go into themes.py roles").
- Fonts through `d.F_DISPLAY` (Shippori Mincho B1, weight `d.DISPLAY_WEIGHT`) and `d.F_META` (Share Tech Mono); `d.layout`, `d.text_size`, `d.draw_text`, `d.ellipsize`.
- Nothing animates at idle. The only motion in this plan is the CRT snap on panel open (380 ms) and close (190 ms). The frame never animates.
- No flashing and no colour changes on a beat anywhere.
- Every surface drops its textures on hide (`release()`), like the existing overlays.
- Tests never touch the running Hyprland; everything renders headless. Live checks are the user's.
- Config keys default to on; an existing `eva.toml` keeps working with a log line for keys that no longer exist.
- Commit messages in the repo's style: `area: what changed` in lower case (see `git log`), ending with the attribution line from the session reminder.

## Review Focus

1. A floating window dragged or resized by the mouse: Hyprland sends no resize event, so the frame must follow it anyway (Task 2 polls while the focused window is floating; test `test_frame_polls_floating`).
2. The focused window on the side monitor: brackets must be drawn on that monitor at local coordinates, not on the main one (Task 2, `test_frame_geometry_side_monitor`).
3. `audiostate` missing or failing (script not installed, PipeWire down): the panel still opens and shows `NO SIGNAL` (Task 5 `test_audio_source_missing_script`, Task 6 `test_sound_no_signal_render`).
4. A sink or app name longer than the row (`"WEBRTC VoiceEngine · Making a CHICAGO STYLE Deep dish pizza?!? …"`): the row ellipsizes and the bar keeps its width (Task 6 `test_sound_long_names_render`).
5. Opening the sound panel while the launcher or the power menu is up, or opening it twice: one surface at a time, the second call closes the first (Task 4 `test_panel_exclusive`, Task 6 `test_command_panel_toggle`).

---

### Task 1: Remove the figure toggle keybind

**Files:**
- Modify: `eva_desk/config.py:105` (drop `figure_toggle_bind` from `DEFAULTS["hyprland"]`), `eva_desk/config.py:266` (drop the `figure_toggle_bind` line from the settings.lua writer), `eva_desk/config.py` `load()` (log ignored keys)
- Modify: `hypr/eva.lua:243-246` (drop the `figure_key` block)
- Modify: `README.md:54,63,113,195,274`, `bin/eva-ctl:7`, `config/eva.example.toml` (the `figure_toggle_bind` line, if present)
- Test: `tests/test_offline.py`

**Interfaces:**
- Consumes: `config.load(path)`, `config.write_lua_settings(cfg)` (the settings.lua writer, `config.py:227-277`).
- Produces: `config.load()` returns a cfg without `hyprland.figure_toggle_bind`; `settings.lua` has no `figure_toggle_bind` line; `EVA_SET_FIGURE` and `eva-ctl figure` keep working.

- [ ] **Step 1: Write the failing tests**

```python
class ToggleRemoved(unittest.TestCase):
    def test_default_has_no_toggle_bind(self):
        cfg = config.load("/nonexistent")
        self.assertNotIn("figure_toggle_bind", cfg["hyprland"])

    def test_settings_lua_has_no_toggle_line(self):
        cfg = config.load("/nonexistent")
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(config, "CONFIG_DIR", Path(tmp)):
            out = config.write_lua_settings(cfg)
            self.assertNotIn("figure_toggle_bind", out.read_text())

    def test_old_toml_key_is_ignored_with_a_note(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "eva.toml"
            p.write_text('[hyprland]\nfigure_toggle_bind = "SUPER + SHIFT + B"\n')
            with contextlib.redirect_stdout(io.StringIO()) as out:
                cfg = config.load(str(p))
            self.assertNotIn("figure_toggle_bind", cfg["hyprland"])
            self.assertIn("figure_toggle_bind", out.getvalue())
```

- [ ] **Step 2: Run them to verify they fail**

Run: `python3 -m unittest tests.test_offline.ToggleRemoved -v`
Expected: FAIL (`figure_toggle_bind` present in defaults and in the written file; no note printed).

- [ ] **Step 3: Implement**

In `config.py`: remove the key from `DEFAULTS["hyprland"]`; remove the writer line; in `load()`, after merging the file, pop `cfg["hyprland"].pop("figure_toggle_bind", None)` and when it was present `print("eva-desk: [hyprland] figure_toggle_bind is gone (the figure has no toggle key any more; use `eva-ctl figure`)", flush=True)`. Keep a module constant `REMOVED_KEYS = {("hyprland", "figure_toggle_bind")}` and loop over it so later removals reuse it.

In `hypr/eva.lua`: delete the four lines `local figure_key = opt("figure_toggle_bind", nil)` … `end`. Keep `EVA_SET_FIGURE`.

In `README.md`: remove the `Super+Shift+B` row from the key table; in the figure paragraph change "`Super+D` docks a window into its space, `Super+Shift+B` hides it." to "`Super+D` docks a window into its space; `eva-ctl figure off` hides it."; in "Your own keybinds are left alone" drop `Super+Shift+B` from the list; in the `eva-ctl` reference replace "(same as Super+Shift+B)" with nothing; in the FAQ replace "`Super+Shift+B` hides it." with "`eva-ctl figure off` hides it.". In `bin/eva-ctl` line 7 drop "(Super+Shift+B toggles)".

- [ ] **Step 4: Run the whole suite**

Run: `python3 -m unittest discover -s tests`
Expected: all pass, including the three new tests. Also run `grep -rn "figure_toggle_bind\|Shift+B" --include=*.py --include=*.lua --include=*.md --include=*.toml . | grep -v docs/superpowers` and expect no output.

- [ ] **Step 5: Commit**

```bash
git add eva_desk/config.py hypr/eva.lua README.md bin/eva-ctl config/eva.example.toml tests/test_offline.py
git commit -m "figure: the Super+Shift+B toggle is gone, eva-ctl figure stays"
```

---

### Task 2: The window frame overlay

**Files:**
- Create: `eva_desk/frame.py`
- Modify: `eva_desk/config.py` (`DEFAULTS["overlays"]["frame"] = True`; new section `"frame": {"brackets": True, "tag": True, "lock": True}`; `DEFAULTS["hyprland"]["border_speed"] = 0`)
- Modify: `eva_desk/app.py:84-100` (build the frames with the overlays), `eva_desk/app.py:114-131` (`_event`: feed the frame), `eva_desk/preview.py` (render a frame)
- Modify: `README.md` (Windows line: brackets, tag, LOCK; the rotating border is off by default)
- Test: `tests/test_offline.py`

**Interfaces:**
- Consumes: `overlays._Overlay`, `overlays._View`, `gtkutil.rect`, `app.hypr.j("activewindow")` → dict with `at [x, y]`, `size [w, h]`, `monitor` (int id), `floating`, `fullscreen` (0/1/2), `class`, `workspace.id`; `app.hypr.j("monitors")` → list with `id`, `name`, `x`, `y`, `width`, `height`, `scale`; `hypr.class_matches(cls, patterns)`; `cfg["figures"]["ignore_classes"]`.
- Produces:
  - `frame.geometry(active: dict, monitors: list, cfg: dict) -> tuple[str, dict] | None` — pure. Returns `(monitor_name, {"x", "y", "w", "h", "cls", "ws", "floating"})` with the window rectangle in that monitor's local pixels (window `at` minus monitor `x, y`), or `None` when nothing should be drawn: no active window, `fullscreen != 0`, class matches `ignore_classes`, or the window is not on a known monitor.
  - `frame.draw_frame(cr, geo: dict, cfg_frame: dict) -> None` — pure cairo. Brackets: 4 px stroke, 24 px legs, 12 px outside the rectangle, `d.BONE`. Tag: `geo["cls"].upper()` in `d.F_DISPLAY` 14 px on a `d.BONE` block at `(x + 18, y - 12)` height 22, the workspace number after it in `d.CLARET`; omitted when `cfg_frame["tag"]` is false or `ws <= 0`. `LOCK` in `d.F_META` 11 px, letter-spacing 3, `d.GOLD` on a `d.INK` block at the right end of the top edge, 18 px inset, omitted when `cfg_frame["lock"]` is false.
  - `class Frame(_Overlay)` with `__init__(app, cfg, gdk_monitor, name)`, `update() -> None` (reads Hyprland, recomputes, queues a redraw; hides the brackets when a launcher/power/alttab surface is visible), `set_suspended(on: bool)`.
  - `app.frames: dict[str, Frame]` keyed by monitor name; `app._update_frames()`.

- [ ] **Step 1: Write the failing tests**

```python
MONS = [{"id": 0, "name": "DP-3", "x": 0, "y": 746, "width": 3440, "height": 1440, "scale": 1},
        {"id": 1, "name": "HDMI-A-1", "x": 3440, "y": 583, "width": 1920, "height": 1080, "scale": 1}]

class FrameGeometry(unittest.TestCase):
    def setUp(self):
        from eva_desk import frame
        self.frame, self.cfg = frame, config.load("/nonexistent")

    def test_frame_geometry_main_monitor(self):
        act = {"at": [12, 814], "size": [3416, 1360], "monitor": 0, "floating": False, "fullscreen": 0, "class": "kitty", "workspace": {"id": 4}}
        self.assertEqual(self.frame.geometry(act, MONS, self.cfg),
                         ("DP-3", {"x": 12, "y": 68, "w": 3416, "h": 1360, "cls": "kitty", "ws": 4, "floating": False}))

    def test_frame_geometry_side_monitor(self):
        act = {"at": [3450, 600], "size": [1900, 1040], "monitor": 1, "floating": True, "fullscreen": 0, "class": "firefox", "workspace": {"id": 7}}
        name, geo = self.frame.geometry(act, MONS, self.cfg)
        self.assertEqual((name, geo["x"], geo["y"], geo["floating"]), ("HDMI-A-1", 10, 17, True))

    def test_frame_hidden_for_fullscreen_games_and_nothing(self):
        act = {"at": [0, 0], "size": [1, 1], "monitor": 0, "floating": False, "fullscreen": 1, "class": "kitty", "workspace": {"id": 1}}
        self.assertIsNone(self.frame.geometry(act, MONS, self.cfg))
        self.assertIsNone(self.frame.geometry(dict(act, fullscreen=0, **{"class": "steam_app_42"}), MONS, self.cfg))
        self.assertIsNone(self.frame.geometry({}, MONS, self.cfg))
        self.assertIsNone(self.frame.geometry(dict(act, fullscreen=0, monitor=9), MONS, self.cfg))

    def test_frame_draws_offline(self):
        import cairo
        surf = cairo.ImageSurface(cairo.FORMAT_ARGB32, 800, 500)
        self.frame.draw_frame(cairo.Context(surf), {"x": 100, "y": 80, "w": 600, "h": 360, "cls": "kitty", "ws": 2, "floating": False}, self.cfg["frame"])
        self.assertGreater(sum(surf.get_data()), 0)       # something was painted
```

And in `Logic` (the existing fake-app test class):

```python
    def test_frame_polls_floating(self):
        from eva_desk import frame
        f = frame.Frame.__new__(frame.Frame)
        f.app, f.cfg, f.poll_id, f.geo = self.app, self.cfg, None, None
        f.queue = lambda: None
        self.app.hypr.state = {"monitors": MONS, "activewindow": {"at": [100, 900], "size": [400, 300], "monitor": 0, "floating": True, "fullscreen": 0, "class": "mpv", "workspace": {"id": 1}}}
        with mock.patch("eva_desk.frame.GLib.timeout_add", return_value=7) as ta:
            f.update()
        ta.assert_called_once()                      # floating: a 200 ms poll is armed
        self.assertEqual(ta.call_args[0][0], 200)
        self.app.hypr.state["activewindow"]["floating"] = False
        with mock.patch("eva_desk.frame.GLib.source_remove") as sr:
            f.update()
        sr.assert_called_once_with(7)                # tiled again: the poll is dropped
```

- [ ] **Step 2: Run them to verify they fail**

Run: `python3 -m unittest tests.test_offline.FrameGeometry tests.test_offline.Logic.test_frame_polls_floating -v`
Expected: FAIL with `ModuleNotFoundError: eva_desk.frame`.

- [ ] **Step 3: Implement `eva_desk/frame.py`**

`geometry()` and `draw_frame()` as specified in Interfaces. `Frame(_Overlay)`: `super().__init__(app, f"eva-frame-{name}", keyboard="none", passthrough=True)` then `LS.set_layer(self.win, LS.Layer.TOP)` (the base class puts surfaces on `overlay`; the frame sits under the panels), `place(gdk_monitor)`, shown once at construction and left visible (an empty paint costs nothing). `update()`: `geo = geometry(hypr.j("activewindow") or {}, hypr.j("monitors") or [], cfg)`; `self.geo = geo[1] if geo and geo[0] == self.name and not self._busy() else None`; arm or drop the 200 ms poll (`GLib.timeout_add(200, self._poll)` while `geo` is floating, `GLib.source_remove` otherwise; `_poll` calls `update()` and returns `GLib.SOURCE_CONTINUE` only while still floating); `self.view.queue_draw()`. `_busy()` is true when `app.launcher` is visible or any of `app.overlays["power"|"alttab"]` is visible. `_paint(snap, w, h)`: if `self.geo`: `cr = snap.append_cairo(rect(0, 0, w, h))`, scale by `self.scale`, `draw_frame(cr, self.geo, self.cfg["frame"])`.

In `app.py`: after the overlays block, `self.frames = {}`; in `_sync_components` where bars are created per monitor (`app.py:229-233`), create `Frame(self, cfg, gdk[name], name)` when `cfg["overlays"]["frame"]`; in `_event`, for `name in REFRESH_EVENTS` call `self._update_frames()` (which calls `update()` on each) after `self.schedule()`; also call it from `launcher.hide()/show()` paths via `app._update_frames()` so the frame returns when the launcher closes (the launcher and overlays call `self.app._update_frames()` in their `show()` and `hide()` if the attribute exists). `_update_frames` is a no-op when `self.frames` is empty.

In `config.py`: the three default changes from Files. In `preview.py`: `save("frame", w, h, lambda cr: frame.draw_frame(cr, {"x": 300, "y": 160, "w": 1400, "h": 900, "cls": "kitty", "ws": 2, "floating": False}, cfg["frame"]))`.

README "Windows" line becomes: "**Windows**: square corners, a thin purple border, a hard purple shadow, bone corner brackets, the app name and workspace number as a tag, and a LOCK readout on the focused window. The border gradient no longer rotates (`border_speed = 100` under `[hyprland]` brings it back)."

- [ ] **Step 4: Run the tests and the renderer**

Run: `python3 -m unittest discover -s tests` → all pass.
Run: `python3 -m eva_desk --config /nonexistent --render /tmp/claude-1000/-home-luisf/8a3a8ce4-6cbe-4ce3-9de2-d8d7a25b3995/scratchpad/render` → prints `frame: N ms`; open `render/frame.png` and check brackets, tag `KITTY 02`, `LOCK`.

- [ ] **Step 5: Commit**

```bash
git add eva_desk/frame.py eva_desk/app.py eva_desk/config.py eva_desk/preview.py README.md tests/test_offline.py
git commit -m "frame: bone brackets, a tag and a LOCK readout around the focused window"
```

---

### Task 3: The MFD drawing language

**Files:**
- Create: `eva_desk/mfd/__init__.py` (empty), `eva_desk/mfd/widgets.py`
- Modify: `eva_desk/preview.py` (render a widget sampler)
- Test: `tests/test_mfd.py` (new file, same header as `test_offline.py`)

**Interfaces:**
- Consumes: `draw.py` helpers and roles; `d.col("ink2")`, `d.col("ink3")`, `d.col("ink4")`, `d.col("dim")`.
- Produces (all pure cairo, all take `cr` first, geometry in surface pixels):
  - `screen(cr, x, y, w, h, tag: str, hot: str = "") -> tuple[float, float, float, float]` — bezel (`ink3`, 6 px) with a 2 px `ink4` outline, face `ink_deep`, scanlines (1 px `bone` at 4.5 % alpha every 4 px), the tag line in `F_META` 11 px letter-spacing 3 in `dim` with `hot` appended in `GOLD`. Returns the inner content rectangle `(cx, cy, cw, ch)` (face minus 10 px padding, minus the tag line).
  - `segbar(cr, x, y, w, h, value: float, colour, peak: float | None = None) -> None` — `value` 0..1; segments from `segments(w)`; lit ones in `colour`, unlit in `ink3`; `peak` (0..1) draws one `BONE` segment.
  - `segments(w: float, pitch: float = 0.032, duty: float = 0.75) -> list[tuple[float, float]]` — the `(x_offset, width)` of each segment across `w`; `len(segments(1000))` is 31, the last one ends at or before `w`.
  - `lamp(cr, x, y, size, on: bool, hot: bool = False) -> None` — square, `ink3` off, `GOLD` on with a 6 px glow (two alpha rings), `LED` hot (steady).
  - `keyrow(cr, x, y, keys: list[str], active: int = -1, key_w=36, key_h=26, gap=6) -> list[tuple]` — key caps `ink3` with `ink4` outline, the active one `BONE` with `INK` text; returns hit rectangles `(x0, y0, x1, y1, index)`.
  - `rows(cr, x, y, w, items: list[dict], selected: int, row_h=34) -> list[tuple]` — each item `{"label", "sub", "value" (0..1 or None), "peak", "muted", "colour"}`: label `F_META` 13 px (`bone`, muted → `dim`), sub `F_META` 10 px letter-spacing 2 `dim`, a `segbar` from 38 % of `w` to `w - 48`, the value as `NN` in `GOLD` at the right; the selected row's label block inverted (`BONE` block, `INK` text). Labels ellipsize at 36 % of `w`. Returns hit rectangles `(x0, y0, x1, y1, index)` and, for the bars, `(x0, y0, x1, y1, ("bar", index))`.
  - `snap_scale(t: float) -> float` — the CRT open curve: `0.02` for `t < 0.4`, then `0.02 + 0.98 * k/4` with `k = ceil((t - 0.4) / 0.6 * 4)` (four steps), `1.0` at `t >= 1`.
  - `stagger(i: int, t: float, total_ms: float = 380, step_ms: float = 120) -> float` — the section's own `t` given the panel's `t`: `clamp((t * total_ms - i * step_ms) / total_ms, 0, 1)`.

- [ ] **Step 1: Write the failing tests**

```python
class Widgets(unittest.TestCase):
    def setUp(self):
        from eva_desk.mfd import widgets
        self.w = widgets

    def test_segments_count_and_bounds(self):
        segs = self.w.segments(1000)
        self.assertEqual(len(segs), 31)
        self.assertLessEqual(segs[-1][0] + segs[-1][1], 1000)
        self.assertAlmostEqual(segs[1][0] - segs[0][0], 32, delta=0.01)

    def test_snap_scale_steps(self):
        s = self.w.snap_scale
        self.assertEqual(s(0.0), 0.02); self.assertEqual(s(0.39), 0.02)
        self.assertAlmostEqual(s(0.55), 0.02 + 0.98 * 1 / 4)
        self.assertEqual(s(1.0), 1.0); self.assertEqual(s(2.0), 1.0)

    def test_stagger(self):
        self.assertEqual(self.w.stagger(0, 0.5), 0.5)
        self.assertEqual(self.w.stagger(1, 0.0), 0.0)
        self.assertAlmostEqual(self.w.stagger(1, 1.0), (380 - 120) / 380)

    def test_rows_hit_map_and_drawing(self):
        import cairo
        surf = cairo.ImageSurface(cairo.FORMAT_ARGB32, 600, 200)
        items = [{"label": "AG346UCD", "sub": "HDMI · DEFAULT", "value": .68, "peak": None, "muted": False, "colour": None},
                 {"label": "X" * 200, "sub": "", "value": 1.0, "peak": .5, "muted": True, "colour": None}]
        hits = self.w.rows(cairo.Context(surf), 10, 10, 580, items, 0)
        self.assertEqual([h[4] for h in hits if not isinstance(h[4], tuple)], [0, 1])
        self.assertEqual([h[4] for h in hits if isinstance(h[4], tuple)], [("bar", 0), ("bar", 1)])
        self.assertGreater(sum(surf.get_data()), 0)
```

- [ ] **Step 2: Run them to verify they fail**

Run: `python3 -m unittest tests.test_mfd -v` → FAIL with `ModuleNotFoundError: eva_desk.mfd`.

- [ ] **Step 3: Implement `eva_desk/mfd/widgets.py`** per Interfaces. Scanlines: a cached `cairo.SurfacePattern` of a 1×4 px tile with `EXTEND_REPEAT`, painted with `cr.mask`/`paint_with_alpha` over the face, so a 1500×600 screen costs one paint.

- [ ] **Step 4: Add the sampler render and run everything**

In `preview.py`: `save("mfd_sampler", 1200, 700, lambda cr: _mfd_sampler(cr, 1200, 700))` where `_mfd_sampler` draws one `screen` with a `rows` list of three items, a `keyrow`, three lamps (off/on/hot) and a lone `segbar` with a peak.
Run: `python3 -m unittest discover -s tests` → pass. Run the renderer and look at `mfd_sampler.png`: bezel, scanlines, inverted selected row, lamps.

- [ ] **Step 5: Commit**

```bash
git add eva_desk/mfd tests/test_mfd.py eva_desk/preview.py
git commit -m "mfd: the panel drawing language (screens, segment bars, lamps, keys, rows, the crt snap)"
```

---

### Task 4: The panel base class

**Files:**
- Create: `eva_desk/mfd/panel.py`
- Modify: `eva_desk/app.py` (`self.panels = {}`, `open_panel(name, gdk_monitor)`, `close_panels(except_name=None)`, the `panel` command)
- Modify: `bin/eva-ctl` (docstring: `eva-ctl panel NAME|close`)
- Test: `tests/test_mfd.py`

**Interfaces:**
- Consumes: `overlays._Overlay` (`animate(ms, on_done)`, `self.t`, `show()`, `hide()`, `release()`, `place()`), `overlays.render_texture` (it is `gtkutil.render_texture(w, h, fn)`), `widgets.snap_scale`, `widgets.stagger`, `gtkutil.rect`.
- Produces:
  - `class Panel(_Overlay)`: `__init__(app, cfg, namespace, width, height, anchor: str)` — `anchor` one of `"left"`, `"right"`, `"bottom"`, `"top"`, `"center"`; the surface is full-monitor and pass-through except inside the panel rectangle (`set_input_region` with that rectangle), keyboard `exclusive` while open. Attributes `self.px, self.py, self.pw, self.ph` (the panel rectangle in surface pixels, computed in `place()` from the anchor with a 12 px margin and `cfg["bar"]["height"]` kept free at the top).
  - `open(gdk_monitor) -> str`: `place`, `self.app.close_panels(except_name=self.name)`, `on_open()`, `show()`, `animate(380)`; returns `"ok"`.
  - `close() -> None`: `animate(190, on_done=self._finish_close)` playing the snap in reverse; `_finish_close` → `on_close()`, `hide()`.
  - `toggle(gdk_monitor) -> str`.
  - `on_open()`, `on_close()`, `draw(cr, w, h) -> list[hit]` (subclass hooks; `draw` paints the panel's content into its rectangle and returns the hit map), `on_key(name: str, mods) -> bool`, `on_click(x, y, button) -> None`, `on_scroll(x, y, dy) -> None`.
  - `sections: list[tuple[float, float]]` set by `draw` (the `y, h` of each section) so `_paint` can apply `snap_scale(stagger(i, t))` per section while `t < 1` (rendered through `render_texture` once per frame during the snap, then cached until `invalidate()`).
  - `invalidate() -> None` — drop the cached texture and queue a draw.
  - `app.open_panel(name, gdk) -> str` (`"<name> disabled"` when not built), `app.close_panels(except_name=None)`, `app.command("panel NAME")` toggles, `app.command("panel close")` closes all.
  - `self.name` is the key in `app.panels`.

- [ ] **Step 1: Write the failing tests**

```python
class PanelBase(unittest.TestCase):
    def test_panel_rect_anchors(self):
        from eva_desk.mfd import panel
        cfg = config.load("/nonexistent")
        r = panel.panel_rect("left", 3440, 1440, 1100, 1300, cfg["bar"]["height"], margin=12)
        self.assertEqual(r, (12, 56 + 12, 1100, 1300))
        r = panel.panel_rect("bottom", 3440, 1440, 3416, 320, 56, 12)
        self.assertEqual(r, (12, 1440 - 12 - 320, 3416, 320))
        r = panel.panel_rect("center", 3440, 1440, 1000, 600, 56, 12)
        self.assertEqual(r, (1220, 56 + (1440 - 56 - 600) // 2, 1000, 600))

    def test_panel_exclusive(self):
        app = FakeApp()                                  # see below
        a, b = FakePanel(app, "a"), FakePanel(app, "b")
        app.panels = {"a": a, "b": b}
        self.assertEqual(app.open_panel("a", None), "ok")
        self.assertEqual(app.open_panel("b", None), "ok")
        self.assertEqual((a.opened, a.closed, b.opened), (1, 1, 1))
        self.assertEqual(app.open_panel("zzz", None), "zzz disabled")
```

`FakePanel` records `opened`/`closed` and implements `open(gdk)` as `app.close_panels(except_name=self.name); self.opened += 1; return "ok"` and `close()`; `FakeApp` is `App.__new__(App)` with `panels = {}` and the real `open_panel` / `close_panels` bound. `panel_rect(anchor, mw, mh, pw, ph, bar_h, margin) -> tuple[int, int, int, int]` is the pure helper `place()` uses.

- [ ] **Step 2: Run them to verify they fail** — `python3 -m unittest tests.test_mfd.PanelBase -v` → FAIL (`eva_desk.mfd.panel` missing; `App` has no `open_panel`).

- [ ] **Step 3: Implement `eva_desk/mfd/panel.py` and the `app.py` hooks** per Interfaces. The snap: in `_paint`, when `self.t < 1`, draw each section scaled about its own top edge by `snap_scale(stagger(i, t))` (clip to the section, `cr.translate(0, y); cr.scale(1, s)`); when closing, use `1 - t`. Input: a `Gtk.EventControllerKey` on the window (`on_key` gets `Gdk.keyval_name`), a `Gtk.GestureClick` and a `Gtk.EventControllerScroll` on the view, coordinates translated into panel space before calling the hooks. Escape closes every panel. The `panel` command in `app.command`: `panel close` → `close_panels()`, `panel NAME` → `self.panels[NAME].toggle(self.focused_gdk())` or `"NAME disabled"`.

- [ ] **Step 4: Run the tests** — `python3 -m unittest discover -s tests` → pass.

- [ ] **Step 5: Commit**

```bash
git add eva_desk/mfd/panel.py eva_desk/app.py bin/eva-ctl tests/test_mfd.py
git commit -m "mfd: the panel base (anchored surface, crt snap open and close, one panel at a time)"
```

---

### Task 5: The audio data source

**Files:**
- Create: `tools/sources/audiostate`, `tools/sources/audio-set`, `tools/sources/audio-quick` (copied from `~/.config/eww/scripts/`, `chmod +x`; in `audio-quick` drop the `cd "$HOME/.config/eww"` line and the eww refresh calls, keep the state and the actions; in `audiostate` keep everything, the icon cache dir is fine)
- Create: `eva_desk/sources/__init__.py` (empty), `eva_desk/sources/audio.py`
- Modify: `install.sh:60` (`chmod +x "$SHARE/tools/sources/"*`), `packaging/PKGBUILD` (nothing to add: `tools` is copied whole; verify)
- Test: `tests/test_sources.py`, fixtures `tests/fixtures/audiostate.json` (one real `audiostate --once` line, names shortened to plausible but not personal values) and `tests/fixtures/levels.json`

**Interfaces:**
- Produces:
  - `audio.scripts_dir() -> Path` — `Path(__file__).resolve().parents[2] / "tools" / "sources"` (true in the repo, in `~/.local/share/eva-desk` and in `/usr/share/eva-desk`, where `eva_desk/` and `tools/` are siblings).
  - `audio.snapshot() -> dict | None` — runs `audiostate --once`, returns the parsed JSON or `None` when the script is missing, fails, or prints no JSON within 3 s.
  - `audio.quick() -> dict` — `audio-quick` state, `{"dnd": False, "night": False, "power": "unknown"}` on failure.
  - `class audio.Listener`: `__init__(on_struct: Callable[[dict], None], on_levels: Callable[[dict], None])`; `start()` spawns `audiostate --struct` and `audiostate --levels` with `Gio.Subprocess` and reads lines on the main loop; `stop()` kills both. Lines that are not JSON are ignored.
  - `audio.set_volume(kind: str, ident: str | int, value: int) -> None`, `audio.toggle_mute(kind, ident)`, `audio.set_default(kind, name)`, `audio.move(kind, ident, target)`, `audio.quick_toggle(what: str)` — `subprocess.Popen` of the matching script, never waited on, exceptions logged not raised.
  - `audio.parse_line(line: str) -> dict | None`.

- [ ] **Step 1: Write the failing tests**

```python
class AudioSource(unittest.TestCase):
    def test_parse_line(self):
        from eva_desk.sources import audio
        self.assertIsNone(audio.parse_line("not json"))
        self.assertEqual(audio.parse_line('{"a": 1}\n'), {"a": 1})

    def test_audio_source_missing_script(self):
        from eva_desk.sources import audio
        with mock.patch.object(audio, "scripts_dir", return_value=Path("/nonexistent")):
            self.assertIsNone(audio.snapshot())
            self.assertEqual(audio.quick(), {"dnd": False, "night": False, "power": "unknown"})
            audio.set_volume("sink", 60, 50)             # does not raise

    def test_snapshot_reads_the_script(self):
        from eva_desk.sources import audio
        fx = Path(__file__).parent / "fixtures" / "audiostate.json"
        with tempfile.TemporaryDirectory() as tmp:
            fake = Path(tmp) / "audiostate"; fake.write_text(f"#!/bin/sh\ncat {fx}\n"); fake.chmod(0o755)
            with mock.patch.object(audio, "scripts_dir", return_value=Path(tmp)):
                snap = audio.snapshot()
        self.assertEqual(set(snap), {"sinks", "sources", "apps", "recs"})
```

- [ ] **Step 2: Run them to verify they fail** — `python3 -m unittest tests.test_sources -v` → FAIL (`eva_desk.sources` missing).

- [ ] **Step 3: Implement** the scripts copy and `eva_desk/sources/audio.py` per Interfaces. Also run the copied scripts by hand once: `tools/sources/audiostate --once | head -c 200` and `tools/sources/audio-quick` print JSON.

- [ ] **Step 4: Run the tests** — `python3 -m unittest discover -s tests` → pass.

- [ ] **Step 5: Commit**

```bash
git add tools/sources eva_desk/sources tests/test_sources.py tests/fixtures install.sh
git commit -m "sources: the audio scripts move into the repo with a python wrapper"
```

---

### Task 6: The sound panel

**Files:**
- Create: `eva_desk/mfd/sound.py`
- Modify: `eva_desk/app.py` (build `SoundPanel` into `self.panels["sound"]` when `cfg["overlays"]["sound"]`), `eva_desk/config.py` (`DEFAULTS["overlays"]["sound"] = True`; `DEFAULTS["bar"]["actions"]["volume"]` default becomes `"eva-ctl panel sound"`), `eva_desk/bar.py:255` (left click on the volume tag runs the action; middle click keeps the mute), `eva_desk/preview.py` (render the panel from the fixture), `README.md` (a "Sound" feature paragraph and the `eva-ctl panel sound` line), `bin/eva-ctl` docstring
- Test: `tests/test_mfd.py`

**Interfaces:**
- Consumes: Task 3 widgets, Task 4 `Panel`, Task 5 `audio`.
- Produces:
  - `class SoundModel` (GTK-free): `__init__(state: dict | None, quick: dict)`; `sections: list[dict]` each `{"key": "sinks"|"sources"|"apps"|"recs"|"quick", "title": "出力"|"入力"|"配信"|"収録"|"切替", "eng": "OUTPUT · SINKS"…, "rows": [...]}`; a row is `{"kind": "sink"|"source"|"sink-input"|"source-output", "id", "label", "sub", "value" (0..1), "muted", "default": bool, "target": str}`; `sel: tuple[int, int]` (section, row); `levels(levels_json: dict)` updates values and mutes in place (keys `sink<ID>`, `source<ID>`, `app<INDEX>`, `rec<INDEX>` as `audiostate --levels` prints them); `move(dy: int)`, `move_section(d: int)`; `action(name: str) -> list[tuple]` where `name` ∈ `{"up", "down", "left", "right", "mute", "default", "next_section", "prev_section", "dnd", "night", "power"}` and the result is the list of audio calls to make, e.g. `[("set_volume", "sink", 60, 73)]`, `[("quick_toggle", "dnd")]`; `pick(index: int)` for a device picker on an app row (`[("move", "sink-input", 618, "<sink name>")]`); `set_from_bar(section, row, frac: float)`.
  - `draw_sound(cr, x, y, w, h, model: SoundModel, no_signal: bool) -> tuple[list[hit], list[tuple[float, float]]]` — paints the four screens and the quick toggles (lamps `on` for dnd/night true, the power profile as a `keyrow` of `BALANCED · POWER · SAVER` with the active one lit); `no_signal` paints one screen with `NO SIGNAL` in `LED` `F_DISPLAY` 40 px instead of the lists. Returns the hit map and the section `(y, h)` list.
  - `class SoundPanel(Panel)`: `name = "sound"`, anchored `"left"`, width `min(1100, 0.34 * monitor_w)`, height `monitor_h - bar - 24`; `on_open` → `audio.snapshot()` (None → `no_signal`), `audio.quick()`, starts a `Listener` whose `on_struct` rebuilds the model and `on_levels` calls `model.levels()` then `invalidate()`; `on_close` stops the listener; keys: `Up/Down/j/k` move, `Left/Right/h/l` ±5 (`set_volume`), `m` mute, `d` default, `Tab`/`ISO_Left_Tab` sections, `1 2 3` quick toggles, `Return` opens the picker on app/rec rows (a `keyrow` of sink/source short names under the row; `Return` again or a digit picks), `Escape` closes; clicks select rows, a click on a bar sets the volume by position, scroll ±5.

- [ ] **Step 1: Write the failing tests**

```python
class Sound(unittest.TestCase):
    def setUp(self):
        from eva_desk.mfd import sound
        self.sound = sound
        self.state = json.loads((Path(__file__).parent / "fixtures" / "audiostate.json").read_text())
        self.m = sound.SoundModel(self.state, {"dnd": False, "night": True, "power": "balanced"})

    def test_sections_and_rows(self):
        self.assertEqual([s["key"] for s in self.m.sections], ["sinks", "sources", "apps", "recs", "quick"])
        first = self.m.sections[0]["rows"][0]
        self.assertEqual(first["kind"], "sink")
        self.assertTrue(0.0 <= first["value"] <= 1.0)

    def test_actions(self):
        self.m.sel = (0, 0)
        row = self.m.sections[0]["rows"][0]
        self.assertEqual(self.m.action("right"), [("set_volume", "sink", row["id"], min(100, round(row["value"] * 100) + 5))])
        self.assertEqual(self.m.action("mute"), [("toggle_mute", "sink", row["id"])])
        self.assertEqual(self.m.action("dnd"), [("quick_toggle", "dnd")])
        self.m.action("next_section"); self.assertEqual(self.m.sel[0], 1)
        self.m.sel = (2, 0)
        self.assertEqual(self.m.action("down")[0:0], [])               # moving returns no calls
        app = self.m.sections[2]["rows"][0]
        self.assertEqual(self.m.pick(0), [("move", "sink-input", app["id"], self.m.sections[0]["rows"][0]["target"])])

    def test_levels_update_in_place(self):
        sid = self.m.sections[0]["rows"][0]["id"]
        self.m.levels({f"sink{sid}": {"v": 12, "m": True}})
        self.assertEqual((self.m.sections[0]["rows"][0]["value"], self.m.sections[0]["rows"][0]["muted"]), (0.12, True))

    def test_sound_long_names_render(self):
        import cairo
        self.state["apps"][0]["app"] = "WEBRTC VoiceEngine"
        self.state["apps"][0]["title"] = "Making a CHICAGO STYLE Deep dish pizza?!? #youtube #shorts " * 3
        m = self.sound.SoundModel(self.state, {"dnd": False, "night": False, "power": "balanced"})
        surf = cairo.ImageSurface(cairo.FORMAT_ARGB32, 1100, 1300)
        hits, sections = self.sound.draw_sound(cairo.Context(surf), 0, 0, 1100, 1300, m, False)
        bars = [h for h in hits if isinstance(h[4], tuple)]
        self.assertTrue(all(h[2] - h[0] > 300 for h in bars))            # the bar keeps its width
        self.assertEqual(len(sections), 5)

    def test_sound_no_signal_render(self):
        import cairo
        m = self.sound.SoundModel(None, {"dnd": False, "night": False, "power": "unknown"})
        surf = cairo.ImageSurface(cairo.FORMAT_ARGB32, 1100, 1300)
        hits, sections = self.sound.draw_sound(cairo.Context(surf), 0, 0, 1100, 1300, m, True)
        self.assertEqual(hits, [])
        self.assertGreater(sum(surf.get_data()), 0)
```

And in `Logic`:

```python
    def test_command_panel_toggle(self):
        calls = []
        class P:
            name = "sound"
            def toggle(self, gdk): calls.append(("toggle", gdk)); return "ok"
            def close(self): calls.append("close")
        self.app.panels, self.app.launcher, self.app.overlays = {"sound": P()}, None, {}
        self.app.focused_gdk = lambda: None
        self.assertEqual(self.app.command("panel sound"), "ok")
        self.assertEqual(self.app.command("panel close"), "ok")
        self.assertEqual(self.app.command("panel music"), "music disabled")
        self.assertEqual(calls, [("toggle", None), "close"])
```

- [ ] **Step 2: Run them to verify they fail** — `python3 -m unittest tests.test_mfd.Sound tests.test_offline.Logic.test_command_panel_toggle -v` → FAIL (`eva_desk.mfd.sound` missing).

- [ ] **Step 3: Implement `eva_desk/mfd/sound.py`** per Interfaces, then the wiring: `app.py` builds the panel; `bar.py` `_click`: `what[0] == "volume"` with button 1 runs `cfg["bar"]["actions"]["volume"]` (button 2 stays mute); `config.py` defaults; `preview.py`: `save("sound", 1100, 1300, lambda cr: draw_sound(cr, 0, 0, 1100, 1300, SoundModel(fixture, quick), False))` and `save("sound_no_signal", …, True)`; README paragraph under Features: "**Sound** (click `VOL` on the bar, or `eva-ctl panel sound`). Outputs, inputs, app streams and recordings on four screens with level bars; arrows move and set, `m` mutes, `d` makes a device the default, Enter moves a stream to another device, `1 2 3` toggle do-not-disturb, night light and the power profile."; `bin/eva-ctl` docstring line `eva-ctl panel sound|close`.

- [ ] **Step 4: Run the tests and the renderer**

Run: `python3 -m unittest discover -s tests` → pass. Run the renderer; open `sound.png` and `sound_no_signal.png`: five screens, the selected row inverted, bars segmented, the quick lamps and the power key row; the no-signal screen in orange. Check that `python3 -m eva_desk --help` still works (imports are lazy enough that GTK-free code paths do not pull `Gtk` at module import of `sound.py`; keep `from gi.repository import …` inside `SoundPanel` methods or guard it the way `overlays.py` does).

- [ ] **Step 5: Commit**

```bash
git add eva_desk/mfd/sound.py eva_desk/app.py eva_desk/bar.py eva_desk/config.py eva_desk/preview.py README.md bin/eva-ctl tests/test_mfd.py tests/test_offline.py
git commit -m "sound: the sound settings panel, first of the mfd panels"
```

---

### Task 7: Wrap-up for this plan

**Files:**
- Modify: `README.md` (Configuration section: the new `[overlays]` keys `frame`, `sound`, the `[frame]` section; note that the eww `osettings` window is no longer needed), `config/eva.example.toml` (the same keys with comments), `packaging/.SRCINFO` only if the PKGBUILD changed (it should not).

- [ ] **Step 1: Document the keys** exactly as `config.py` defaults them, in the README's configuration table and the example TOML.

- [ ] **Step 2: Full verification**

Run: `python3 -m unittest discover -s tests` → pass.
Run: `python3 -m eva_desk --config /nonexistent --render <scratchpad>/render` → `frame`, `mfd_sampler`, `sound`, `sound_no_signal` rendered.
Run: `cd packaging && makepkg -f --noextract -p PKGBUILD` is NOT run here (sudo/pacman); instead `bash -n install.sh` and `grep -n "tools/sources" install.sh`.

- [ ] **Step 3: Commit**

```bash
git add README.md config/eva.example.toml
git commit -m "docs: the frame and sound panel keys"
```

Then stop and report: the user applies with `eva-ctl apply` and tries `eva-ctl panel sound`, the volume tag click, and the frame on both monitors. Live checks are theirs.
