# eva-desk motion graphics — design

Date: 2026-10-13. Status: draft for review.

## Goal

Give the desk motion graphics of its own: short sequences that play when something happens, and slow
loops that keep the desk alive when nothing does. Six sequences and three ambient pieces, all drawn by
the daemon.

| | Piece | Plays | Length | Drawn from |
|---|---|---|---|---|
| Sequence | Launch, the card | Enter in the launcher, for an app | 2.0 s | code |
| Sequence | Launch, the shaft | Enter in the launcher, for a game | 2.0 s | code |
| Sequence | Boot | the daemon's first start in a Hyprland session | 2.6 s | code |
| Sequence | Wake | the lock screen closes, or the machine resumes | 1.1 s | code |
| Sequence | Berserk | sustained load crosses the berserk limit | 1.3 s | code |
| Sequence | Track change | a new title starts playing | 1.6 s | code |
| Ambient | Standby | some minutes without input | loop, 60 s lap | three pictures and code |
| Ambient | Living wallpaper | always, on main monitors | loop | your wallpaper and code |
| Ambient | Side wall | a non-main monitor whose workspace is empty | loop | code, live readings |

Out of scope: sound, the figure and its stage (left as they are), the launcher's layout, the eye-catch,
the power menu's cross, the lock and login screens, and the panels of the 2026-10-06 motion redesign
that are still to be built (music, notifications, system, calendar, popups, overview).

This spec replaces the "Launch sequence" section and the `[launch]` settings of
`2026-10-06-motion-redesign-design.md`. That launch was a cut sequence over generated key frames; it was
rejected in review as "a picture moving". `assets/launch/` is never created.

## Decisions taken during design

| Topic | Decision |
|---|---|
| Approach | Drawn live in the daemon through the GTK snapshot API. No pre-rendered video, no shaders. |
| Launch | Drawn and animated entirely in code, every move eased. No pictures. The Eva is not drawn in code: the launch is told through type, the shaft and instruments. Apps get the card, games get the shaft. |
| Launch input | The keyboard stays free: typing goes to the focused window, which is the new one once it has opened. A click with any button skips the sequence. Shift+Enter launches with no sequence. |
| The Eva in pictures | Only the standby loop shows it. The pictures are generated: the figure nearly lost in black, drawn by its rim light, with lit green eyes. The flat poster frames of the earlier launch design are not used anywhere. |
| Berserk | Until now berserk only recoloured the stage, which is hidden whenever the figure is off. It gets a sequence on the edges of the screen and colours the wallpaper's ripples and embers; the stage keeps its own berserk colour. |
| Unlock | Hyprland reports no unlock, so the daemon starts the locker itself and plays the sequence when it exits. |
| Idle | The daemon runs its own `hypridle` with a generated config. Without `hypridle`, standby starts only by command. |
| Wallpaper | On main monitors the daemon draws the wallpaper itself and moves it visibly. `awww` keeps serving the other monitors. |
| GPU | Ambient motion may use the GPU, but never to full load and never at a game's cost: while a game is open, every ambient piece stops repainting on every monitor. |
| Flashes | No full-screen flash in any piece. Bright frames are bands, blooms or washes of limited area. |
| Motion rule | An event gets one sequence, then the picture holds still. Ambient pieces may loop, slowly. No flashing and no per-beat colour changes anywhere. |

## Architecture

```
eva_desk/motion/
  timeline.py    progress, easing, steps, repeatable noise. Pure Python, no GTK.
  kit.py         the drawing kit over a Gtk.Snapshot
  player.py      SequencePlayer and AmbientLayer: the layer surfaces that host a piece
  render.py      the offline renderer
  triggers.py    when each piece plays, and the pause rules. Pure logic over desk state.
  seq/           card.py  shaft.py  boot.py  wake.py  berserk.py  track.py
  amb/           standby.py  wallpaper.py  wall.py
eva_desk/sources/idle.py     the hypridle child
assets/motion/               the three standby pictures, two layers each, and art.json
tools/gen/gen_rim.py         prompts and batches for the pictures
tools/gen/prep_art.py        splits a picture into its body and eye layers
```

### One drawing path

Every piece paints into a `Gtk.Snapshot` and nothing else. Live, the snapshot is the widget's own and
the GPU composites it. Offline, the renderer makes a bare `Gtk.Snapshot()`, takes `to_node()` and calls
`node.draw(cairo_context)`. GTK draws its nodes through cairo without a display (checked on GTK 4.22:
transforms, opacity, colour matrix, clips, blur, mask, blend, borders, linear and radial gradients, text;
a 3440x1440 frame takes about 60 ms). A piece is therefore written once, and the frames the tests and
the owner look at come from the code that runs on the desk.

One limit shapes the kit: no path nodes. GTK rasterises a path on the CPU every time it changes, and in
a piece everything changes every frame; and cairo asserts on some nested path clips when it draws a
frame offline. So moving geometry is made of what the GPU draws by itself: rectangles, borders, glyphs
and gradients, turned or sheared by 2D transforms and cut by masks. A transform must be built from
translate, rotate, skew and scale; a raw matrix is not 2D to GTK, which then paints a pink box offline.
Anything more complex and still (a field of hundreds of hexagons, say) is drawn once into a texture.

The same rule covers type. GTK keeps a glyph by its exact size on screen, so glyphs under a scale that
changes are rasterised again every frame (a 1100 px kanji costs about 2 ms). Type that only moves is
glyphs; type that grows or shrinks is a stamp: set once as a picture, at most 2048 px on its longer side,
and scaled by the GPU. The player keeps a run's stamps and drops them when the run ends.

### A piece

```python
class Piece:
    length = 2.0          # seconds; None for a loop
    covers = True         # takes the pointer while it plays (a click skips it); False = fully pass-through

    def prepare(self, kit, ctx): ...     # build textures early: pictures, and the stamps of type that changes size
    def paint(self, kit, t, ctx): ...    # one frame at t seconds; the kit carries the frame, kit.W by kit.H
    def release(self): ...               # drop textures
```

`ctx` carries the live inputs a piece may show: the app's name, the track's title and artist, the
readings, the clock, the berserk flag. Pieces never read the system themselves, so the renderer and
the tests can feed fixed values.

All sizes below are in design px. The kit scales them by `min(h / 720, w / 1280)`, so a piece sees a frame
720 design px high on anything as wide as 16:9 (1720x720 on a 21:9 monitor, the design space `scenes.py`
already uses) and a taller one on a narrower monitor. Positions are laid out from that frame, so a
portrait monitor gets the same piece in its own shape.
Nothing calls `random`: jitter comes from `timeline.noise(i, seed)`, so frame N is the same on every run.

### The kit (`kit.py`)

Thin helpers over the snapshot, colours by theme role only:

- `text(...)`: type as glyphs, for type that keeps its size; layouts are cached. `stamp(...)`: the same
  call for type that changes size, drawn as a picture. `letters(string, ...)`: a name cut where a caret can
  stand, or `None` when its script joins its letters or runs right to left (it is then set whole).
  `sprite(texture, x, y, w, h, alpha, tint)` for pictures.
- `rect`, `stroke_rect`, `band` (what lies between two rectangles), `para` (a parallelogram), `lines`,
  `hazard`, `hexagon`, `brackets`, `segbar`, `lamp`, `screen`: the shapes the pieces share. The MFD
  ones wrap `mfd/widgets.py`.
- `clip(rect)`, `clip_out(rect)` and `clip_out_para(...)` (holes, as masks), `opacity`, `transform`,
  `screen_blend`: scoped with `with`.
- `cover(texture, box, zoom, anchor)`: a picture filling a box, zoomed about an anchor point.
- `radial(x, y, r, colour, alpha)`: a soft glow.

`timeline.py` holds `seg(t, a, b)` (progress of `t` inside an interval), the easings (`cubic_out`,
`cubic_in`, `smooth`, `back_out`, `quint_out`, `expo_in`), `stepped(u, n)`, `twos(t)` (time quantised to
12 per second, for the few drawn effects that run on twos), `crt(u)` (the panel snap: a line, then four
steps), and `noise`.

### The player (`player.py`)

`SequencePlayer` is an `_Overlay` on the overlay layer, namespace `eva-motion`, keyboard none. It plays
one piece once on one monitor: place, `prepare`, show, a tick callback on the frame clock that paints at
the monitor's own rate, and at the end hide, `release`, done callback. A piece with `covers = True`
takes the pointer and a click with any button ends it at once; one with `covers = False` has an empty
input region. A timeout at `length + 1 s`, set before the overlay is shown, hides it whatever happened.
An exception inside `paint` ends the sequence: nothing more is painted and the overlay is hidden from the
main loop (GTK is in the middle of drawing that window when `paint` runs). A piece whose `prepare` raises
is not shown at all. A covering sequence replaces whatever is playing on its monitor; berserk and the
track card are dropped if a covering sequence, the launcher, the power menu, Alt+Tab or standby is up.
While a covering sequence plays, the spawn pulse and the workspace eye-catch do not: the window a launch
opens lands under the sequence, and its pulse would be drawn on top.

`AmbientLayer` hosts a loop: a layer surface that repaints from a timer at `[ambient] fps`, with
`pause()` and `resume()`. The wallpaper and the wall sit on the bottom layer (as the stage does), standby
on the overlay layer.

### The offline renderer (`render.py`)

`eva-desk --render-motion DIR [--only NAME] [--size WxH] [--fps N]` writes, for every piece, a contact
sheet `NAME.png` of evenly spaced frames and, when `ffmpeg` is installed, `NAME.mp4`. Loops render one
lap. `eva-desk --render DIR` gains one frame per piece, so the standing check covers motion too.
Inputs are fixtures: a fixed clock, a fixed app name, the readings of `tests/fixtures`.

## The sequences

Times are seconds from the start. "Design px" are in the 1720x720 space.

### Launch

Enter in the launcher starts the app at t = 0 exactly as today, hides the launcher, and plays a
sequence on the launcher's monitor. The sequence is the shaft when the entry's `.desktop` file lists the
`Game` category, the card otherwise (commands and web searches included). Shift+Enter launches with no
sequence, and so does `[motion] launch = false`. The name shown is the entry's display name in capitals
(for a command, its first word; for a search, `SEARCH`), set smaller when it would not fit.

#### The card

Flat kinetic type in the title-card language.

| Time | What happens | Easing |
|---|---|---|
| 0.00 – 0.26 | Two ink plates with a slanted seam (190 px lean over the height) slide in from the sides and meet. Each carries a 16 px hazard edge on its seam, visible only while the plates move. | quint out |
| 0.14 – 0.50 | 発 rises from below and 進 drops from above (380 px, bone), each from outside the frame whatever its height, meeting at the centre. | quint out |
| 0.30 – 0.56 | A bone slab 300 px high opens from the centre to the full width; inside it the two kanji are ink on bone. | smooth |
| 0.64 – 0.84 | The slab folds to a 4 px rule at 60 % of the height, inset 64 px. The kanji shrink to a fifth and settle as a tag at the top left. | smooth |
| 0.80 – 1.30 | The app's name (170 px) rises from behind the rule one letter at a time, 35 ms apart, 0.28 s each. A name whose script joins its letters or runs right to left rises whole. | quint out |
| 0.84 – 1.24 | A gold line runs along the rule. A meta line under it wipes in from 0.92: `TARGET ・ name ・ WORKSPACE nn ・ hh:mm`. | smooth |
| 1.25 – 1.62 | Lift-off: everything on the plates leaves upward by 1.3 screen heights. 46 thin speed lines run down the plates from 1.25 to 1.84. | expo in |
| 1.62 – 2.00 | The plates part the way they came. The desk is underneath. | smooth |

#### The shaft

First person up the launch shaft. The shaft is 60 bays long and the camera travels 59 of them:
`travel(u) = 59 · u³ / (u³ + (1 − u)^1.7)` with `u = t / 2.0`, which leaves the locks slowly, runs
hardest in the middle and brakes into the exit. A frame at depth `z` bays ahead is drawn at `1 / z` of
the screen about the vanishing point (the centre).

- **The shaft.** Bay frames in claret, every other bay a shade lighter (`ink4`), four corner rails, and
  fog toward the far end. Every tenth bay is a gate in orange with its number on the top edge, counting
  down `GATE 05` to `GATE 01`.
- **Wall lights.** 44 lights on a 9-bay period, bone with about a quarter of them gold. Their length is
  `0.18 + 2.6 · speed` bays, so they stretch as the run speeds up.
- **The sign.** 発進 with a gold rule and `LAUNCH` hangs 3.2 bays up. The camera passes through it at
  about 0.6 s.
- **The exit.** The far end of the shaft is a hole in the overlay, so the desk shows through it: a small
  lit rectangle at first, growing with the approach until it is the screen at 2.0 s. A soft glow around
  it dims on arrival.
- **The camera.** A slow roll of about 2 degrees at most and a fine rumble of at most 2.6 px, both scaled by
  `(1 − u)^1.6` so the exit arrives level and still. Both are sums of sines, not noise.
- **The instruments**, fixed to the screen: five lock bolts filling from orange to green one after
  another (0.05 to 0.43 s) with `LOCK BOLTS RELEASED` after; the app's name (92 px) wiping in at the lower
  left (0.10 to 0.52 s); the altitude running from −1180 m to 0 at 20 m a bay; a velocity bar. They slide
  off to the sides between 1.46 and 1.80 s.

### Boot

Plays once per Hyprland session on every main monitor, covering it. Not on `eva-ctl reload`: the daemon
keeps a marker in `$XDG_RUNTIME_DIR` holding the Hyprland instance signature.

| Time | What happens |
|---|---|
| 0.04 – 0.65 | On ink, six check lines type on 85 ms apart: a header in mincho, the three MAGI lines (the bar's CPU, RAM and network tags), the outputs, and the Hyprland version, the last two read live. Each line types in 70 ms, dots run to the status column, and the status snaps in with a green lamp. |
| 0.04 – 1.12 | A 62-segment bar along the floor lights in order, on twos, with a counter to 100. |
| 0.55 – 1.30 | The A.T. field (hexagons, 58 px) assembles over the right 60 % outward from one cell, on twos; each cell arrives in two steps. |
| 1.15 – 1.48 | Episode zero in the eye-catch's layout: `EPISODE` types on, the digits `00` (330 px) roll up into place 70 ms apart, the plate `第零話 ・ 起動` opens in three steps. The check lines step back to 42 %. |
| 1.95 – 2.35 | The gate: the whole picture splits along a horizontal line at 62 % of the height, through the digits. The two halves leave up and down with hazard edges; the desk is underneath. A 4 px bone line marks the seam for the first 40 ms. |
| 2.30 – 2.58 | Bone brackets settle on the screen's edge from 105 % with a small overshoot. A green tag `全系統正常 ・ ALL GREEN` opens in three steps under the bar and holds. Cut. |

### Wake

Plays on every main monitor, covering it, when the locker exits or the machine resumes from sleep.

| Time | What happens |
|---|---|
| 0.00 – 0.12 | On ink, one gold line draws out from the centre. A graph frame fades in behind it. |
| 0.12 – 0.62 | The line splits into two waves (gold and lilac, 430 px wavelength) whose height and phase difference close with a smooth ease. 同期 (116 px) and `PILOT RE-ENTRY ・ SYNC RATIO` stand above; a counter runs from 41.3 to 99.9 on twos. |
| 0.62 – 0.85 | Lock: one 4 px bone line, the counter reads 100.0 in gold, and the plate `同期完了 ・ SYNCHRONISED` opens in three steps with a lamp. |
| 0.85 – 1.08 | The cover folds to a line in three steps, the line turns bone and closes on the centre. |

### Berserk

Plays on main monitors when `_berserk_check` turns on. It never takes input (`covers = False`), is
skipped on a monitor that has a fullscreen window, and does not play at all while a game is open.

| Time | What happens |
|---|---|
| 0.00 – 0.22 | Two orange hazard strips, 16 px, run in: under the bar from the left, along the floor from the right. They crawl at 46 px/s while they are up. |
| 0.10 – 0.32 | A 4 px orange line grows down the left edge and up the right. |
| 0.18 – 0.40 | The block slams in at the lower left: an orange slab 300x168 with a bone hard shadow, 暴走 in ink, scaled from 130 % with an overshoot. |
| 0.40 – 0.60 | A mono line types on under the kanji: `BERSERK ・ CPU nn% ・ nn S`, from the live readings. |
| 0.95 – 1.28 | The block closes like a panel (three steps), then the strips and lines leave the way they came. |

What lasts while the load does: the bar's CPU tag is orange (as today), and the living wallpaper's
ripples and embers are orange. The stage's own berserk colour is left alone.

### Track change

A card in a corner of the focused monitor when it is a main one, otherwise of the first main monitor,
when the player reports a new title. It never takes
input, is skipped under a fullscreen window, and does not play while a game is open. `[motion] track_corner` picks bottom-left or bottom-right.

| Time | What happens |
|---|---|
| 0.00 – 0.20 | A 3 px gold rule draws out, 96 px above the floor and 44 px from the side. Its width is the wider of title and artist plus 52 px, between 320 and 640. |
| 0.08 | A gold tag `再生 ・ NOW PLAYING` appears above it. |
| 0.14 – 0.34 | Two ink slabs with a claret hard shadow open from the rule: 62 px above for the title, 32 px below for the artist. |
| 0.20 – 0.50 | The title (mincho, 38 px) rises from behind the rule with a small overshoot; the artist (mono, 13.5 px) drops from it. |
| 0.50 – 1.18 | Hold. Nothing reacts to the music. |
| 1.18 – 1.58 | The type goes back into the rule, the slabs close, the rule retracts. |

## The ambient pieces

### Standby

After `[standby] minutes` without input, every monitor is covered by a slow loop on the overlay layer.
The loop is four shots of 15 s with hard cuts between them; all monitors share one clock, so they cut
together. Nearly the whole screen is black.

| Shot | Picture | Camera | Clock |
|---|---|---|---|
| The profile | head and shoulders, side on | push-in from 100 % to 107 %, anchored on the eye | 150 px, low, on the side away from the eye |
| The field | none: a hexagon lattice (64 px) drifting at 6 px/s, a third of its cells breathing on a 9 s period, one gold hexagon ring spreading every 7 s, 待機 at 200 px | still | 240 px, right |
| The tilt | the whole body, in a column over the right 46 % | a pan from the feet to the head over the first three quarters of the shot | 220 px, left |
| The stare | the face, front on | pull-out from 110 % to 102 %, anchored between the eyes | 104 px, top left |

- **The eyes** are a layer of their own and breathe between 40 % and 100 % once in 6 s, with a soft
  green glow at each eye.
- **The passing light.** The body layer is drawn at 62 %. Every 9 s a soft vertical band a third of the
  frame wide crosses it, and inside the band the picture is drawn again at 70 %, so the rim brightens
  where the light is.
- **The frame.** 44 px letterbox bars with a thin claret hazard edge crawling at 4 px/s; `待機 ・ STANDBY`
  and the three readings in the top bar, the shot number and `ANY KEY` in the bottom one.
- **The clock** is the real one, in mincho, with the seconds as a 60-segment bar under it and the date
  below. It moves place every shot.

Any key, click, or pointer travel of more than 8 px ends it; the event is swallowed. The picture folds
to a line in three steps over 0.14 s and the line closes in 0.05 s. Standby never starts while any
monitor has a fullscreen window, while a game is open, or while the locker runs. Starting the locker and a critical
notification both end it.

### Living wallpaper

With `[ambient] wallpaper = true`, each main monitor gets a bottom-layer surface on which the daemon
draws that workspace's wallpaper itself; `Wallpapers.set_for` hands it the picture instead of calling
`awww`. A named colour is a plain fill with no motion. Pictures decode off the main loop and cross-fade
over `[wallpapers] duration`.

- **The drift.** `zoom = 1.035 + drift · (0.5 − 0.5 · cos(2π t / lap))`, with `drift = 8 %` and
  `lap = 30 s` by default, and a pan of 1.5 % of each side on periods of 1.3 and 1.1 laps. The motion is
  visible at real speed and never jumps.
- **A.T. ripples.** Every 5.5 s a ring of hexagons (58 px cells on a slowly drifting lattice) spreads
  from a point at 250 px/s for 4.2 s and fades. Lilac; orange while berserk.
- **Embers.** 70 specks of 1 to 3 px rising at 9 to 25 px/s, bone with about a fifth green; orange while
  berserk.

Each of the three has its own switch.

### Side wall

With `[ambient] wall = true`, the monitor named by `wall_monitor` (by default the first monitor that is
not a main one) shows a status wall on the bottom layer while its workspace holds no window. Its ground
is ink at 62 % over that monitor's wallpaper. The screens are the MFD panel language of
`mfd/widgets.py`, stacked in one column on a portrait monitor and flowed into equal columns on a
landscape one:

| Screen | Content |
|---|---|
| TIME | the clock (128 px), the date, the uptime, the seconds as a 60-segment bar |
| MAGI-1, -2, -3 | CPU, RAM and network: the value (42 px), a 16-segment bar, a minute of history as a sparkline scrolling smoothly, a lamp that turns orange above 90 % |
| HARMONICS | two slow standing waves whose heights follow CPU and RAM |
| WORKSPACES | the ten tags: active inverted, occupied in claret |
| AUDIO | title, artist and progress of the playing track, or `NO SIGNAL` |

A hazard strip crawls at 6 px/s at the top and bottom. Nothing blinks. The readings come from the
existing `resources.Sampler` at one sample a second while the wall is visible; drawing interpolates
between the last two samples.

### Pause rules and cost

The ambient pieces may use the GPU, with two limits: they never drive it to full load, and they cost a
game nothing.

A game is open when any window's class matches `[figures] ignore_classes`, whether that window is
fullscreen, visible, or on another workspace. While a game is open:

- every ambient piece on every monitor is paused and repaints nothing, the side wall included even when
  the game is on the other monitor,
- standby does not start, and the berserk sequence and the track card do not play.

The launch sequences are not affected: the shaft is how a game starts, and it is over before the game
has a window.

An ambient piece is also paused on a monitor that has a fullscreen window, while the locker runs,
between `PrepareForSleep(true)` and resume, and after `eva-ctl ambient off`. Standby pauses the
wallpaper and the wall beneath it. A paused piece keeps its last frame on screen and its timer stopped.

What keeps the cost down the rest of the time: the `[ambient] fps` cap; pictures and type are textures
made once and only moved by the GPU, so no frame is rasterised on the CPU; the side wall and the
wallpaper's ripples and embers change small areas; and a piece that is not visible has no timer at all.
Whether the defaults stay clear of full load can only be measured live (see below). If the living
wallpaper does not, its cap drops, or it pauses on a workspace that windows cover.

## Triggers and sources

- **Launch**: `Launcher._launch` calls `app.play_launch(item, monitor, plain)`.
- **Boot**: on start, if the runtime marker is missing or names another Hyprland instance.
- **Wake**: `App.lock()` runs `[power] lock` as a child of the daemon and plays the sequence when it
  exits with status 0. The power menu's LOCK calls it, and so does the new `eva-ctl lock`; any other
  lock key should be bound to that. Resume from sleep is logind's `PrepareForSleep(false)` on the system
  bus; if a locker child is alive then, its exit plays the sequence instead.
- **Berserk**: the rising edge of the existing `_berserk_check`.
- **Track change**: the existing `NowPlaying`, when the status is Playing and (title, artist) differs
  from the last one announced, after 0.4 s without a further change. The track that is already playing
  when the daemon starts is noted and not announced.
- **Standby**: `sources/idle.py` writes `hypridle.conf` in the state directory (one listener:
  `timeout`, `on-timeout = <path to eva-ctl> standby on`) and runs `hypridle -c` on it as a child, stopped
  by its handle on quit.
- The sampler and `NowPlaying` are created when the bar or any motion piece needs them, no longer only
  with the bar.

## Assets

Three pictures for standby, generated with the same local generator as the figure and chosen by the
owner from contact sheets: a profile, a front view and a whole body. `tools/gen/gen_rim.py` holds the
prompts and `tools/gen/prep_art.py` splits each picture into two JPEG layers, the body without the eye
glow and the eye glow alone on black. The split sets the generator's dark grey to true black and
records each eye's centre. In `assets/motion/`: `profile_body.jpg`, `profile_eye.jpg`, `front_*.jpg`,
`full_*.jpg` and `art.json` (`{name: {w, h, eyes}}`), about 0.3 MB together at their present size. Both layers go on with a
screen blend, so the picture's black is the desk's ink.

## Configuration

```toml
[motion]                  # the sequences, each with its own switch
launch = true             # the card for apps, the shaft for games
boot = true
wake = true
berserk = true            # the sequence; [overlays] berserk still sets the load limit
track = true
track_corner = "bottom-left"   # or "bottom-right"

[ambient]
wallpaper = true          # main monitors: the daemon draws the wallpaper and moves it
drift = 8                 # how far the picture pushes in, percent; 0 = still
lap = 30                  # seconds for one push-in and back
ripples = true
embers = true
wall = true               # the status wall on a monitor that is not a main one
wall_monitor = ""         # connector or part of the description; empty = the first non-main monitor
fps = 30                  # frame-rate cap of the ambient pieces

[standby]
enabled = true
minutes = 5               # 0 = only by eva-ctl standby
idle = "hypridle"         # or "none": you call eva-ctl standby from your own idle tool
```

`eva-ctl` grows `play NAME` (card, shaft, boot, wake, berserk, track: to try one), `standby [on|off]`,
`ambient [on|off]` and `lock`.

## Error handling

- A sequence can never trap the screen: the safety timeout, the click, and the exception guard above.
- A missing or unreadable standby picture drops its shot; with none, standby is the field shot alone.
- A wallpaper that fails to decode falls back to `awww` for that monitor, logged once.
- `hypridle` missing, or exiting: logged once; standby then starts only by command.
- The locker failing to start: logged; no sequence.
- A reading that fails shows `NO SIGNAL` on its wall screen, as the panels do.
- Every piece drops its textures when it leaves the screen, as the overlays do.

## Testing

All of it runs with no compositor, in `tests/test_motion.py`:

- `timeline`: easing bounds and monotonicity, `stepped`, `twos`, `crt`, `noise` repeatability.
- Every piece renders sampled frames headless at 3440x1440 and 1080x1920 through the offline renderer
  with fixture inputs: no exception, a non-empty frame, and the same bytes on a second run.
- Storyboard facts that are cheap to assert: the card's plates cover the whole frame from 0.26 to 1.62 s
  and none of it at 2.0 s; the shaft's exit hole is the full frame at 2.0 s; boot, wake and both
  launches leave a fully transparent frame at their end.
- The player with a fake clock: progress, skip on click, one done callback, `release` called, the
  safety timeout.
- Triggers as pure functions with fakes: boot once per instance signature; game detection from
  categories; track change de-duplication, debounce and the silent first track; the berserk edge; wake
  on locker exit and on resume, never twice; the standby guards; the pause rule as a table, with a game
  open on another monitor and on a hidden workspace among its rows.
- The generated `hypridle.conf` as text. No process is spawned in tests.
- `prep_art.py` on a small synthetic picture: the layers add back to the input and the eye is found.

`eva-desk --render-motion` output is read as part of the verify-offline check: the contact sheets by
whoever makes the change, the mp4s by the owner.

### What only a live run can prove

Frame pacing on a high-refresh monitor; the GPU load of each ambient piece at its defaults, read from
the GPU's own monitor on an idle desk, which must stay clear of full load; that every ambient repaint
stops when a game opens and a game's frame times are the same with the daemon running as without; that `hypridle` fires and honours idle inhibitors; the locker path and resume from sleep; boot
at login; that the keyboard really stays with the new window during a launch. Each plan lists its own.

## Changes to existing files

| File | Change |
|---|---|
| `eva_desk/app.py` | owns the player, the ambient layers and the triggers; `play`, `standby`, `ambient`, `lock` commands; shared sampler and now-playing |
| `eva_desk/launcher.py` | Enter plays the launch through the app; Shift+Enter is the plain launch |
| `eva_desk/overlays.py` | the power menu's LOCK goes through `App.lock()` |
| `eva_desk/wallpaper.py` | main monitors are handed to the living wallpaper when it is on |
| `eva_desk/mfd/widgets.py` | `spark()`, the sparkline |
| `eva_desk/config.py`, `config/eva.example.toml` | the three new sections |
| `eva_desk/__main__.py`, `eva_desk/preview.py` | `--render-motion`; one frame per piece in `--render` |
| `hypr/eva.lua` | the `no_anim` layer rule gains `motion`, `standby`, `wallpaper` and `wall` |
| `bin/eva-ctl`, `README.md`, `install.sh`, `packaging/` | the commands, the features and settings, `assets/motion`, `hypridle` and `ffmpeg` as optional dependencies |
| `CLAUDE.md` | the motion rule, reworded as in the decisions table |
| `2026-10-06-motion-redesign-design.md` | one line under "Launch sequence" pointing here |

## Build order

One plan each; each ends with offline renders and its list of live checks.

1. The engine (`timeline`, `kit`, `player`, `render`, `--render-motion`) and both launch sequences with
   the launcher wiring.
2. Boot, wake (the locker child, resume), berserk and the track card, with `triggers.py`.
3. Standby: the pictures, the loop, the idle source. The motion rule in `CLAUDE.md` changes here, with
   the first loop.
4. The living wallpaper.
5. The side wall.

## Open items

- The pictures are generated at 1792x768 and a main monitor shows them at nearly twice that. Plan 3
  first tries generating the three chosen ones larger; if the GPU cannot, they are upscaled, and the
  owner sees the result before it is final.
- The cost of the living wallpaper is unknown until it runs. The limit is set under "Pause rules and
  cost"; plan 4 ends with the owner's measurement and the default cap is fixed then.
- The track card shows on the focused main monitor only. Whether the side wall should announce the
  track instead, when it is up, is left for after plan 5.
