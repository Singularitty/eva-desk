# eva-desk motion redesign — design

Date: 2026-10-06. Status: draft for review.

## Goal

Make the desk feel like sitting in an Entry Plug: every panel reads as one instrument of one machine,
and the interactions have weight. Concretely:

1. Remove the `Super+Shift+B` figure toggle.
2. On Enter in the launcher, play an Eva launch sequence while the app opens.
3. Rebuild every panel that today lives in eww as a daemon overlay in one visual language ("MFD").
4. Give windows a hardware frame (corner brackets, title tag, LOCK readout).
5. Keep the workspace switch animation exactly as it is.

Out of scope: the launcher layout (stays as it is), the bar, the lock and login screens, the
screenshot tool, wallpapers, the figure and its stage, the maximise backdrop.

## Decisions taken during design

| Topic | Decision |
|---|---|
| Launcher | Unchanged. Enter still runs the app; the launch sequence plays on top. |
| Figure | Stays on its stage permanently. Only the keybind and its config key go. `eva-ctl figure` stays as a command. |
| Launch sequence | A cut sequence of generated key frames with camera, cuts and drawn effects, 2.1 s. Silhouette-and-poster style: flat violet Unit-01 with a green rim, smoke drawn into each frame. Current frame picks are placeholders for the shaft and cage cuts (see "Open items"). |
| Panels | Rebuilt inside the daemon (GTK4 + cairo), not restyled in eww. The MFD language: screens in a bezel, scanlines, segmented LED bars, lamps, mono readouts, mincho headers, the CRT snap on open. |
| Borders | Option A "brackets": the current thin purple border and hard shadow from Hyprland, plus a static overlay drawn by the daemon around the focused window: bone corner brackets, a title tag with the workspace number, a LOCK readout. No animation on focus. |
| Visualizer | 36 LED columns from cava, one colour (Unit-01 purple), steady bone peak marks. No per-beat colour changes anywhere; nothing in the panels flashes. |
| Workspace switch | Unchanged (Hyprland `slidevert` plus the eyecatch card). |
| Motion budget | Short bursts on events, still at idle. The only continuous motion is the visualizer while the music panel is open, and the countdown line on a notification. |

## Architecture

The daemon (`eva_desk/`) already draws the bar, launcher, stage and the overlays in `overlays.py`
through one pattern: a layer-shell window per surface, a `_View` widget that paints with cairo, a
tick-callback animation. The redesign extends that pattern and splits it into packages so that no
module grows past what it has now.

```
eva_desk/
  overlays.py        stays: Eyecatch, AlarmBand, AltTab, PowerMenu, SpawnPulse, _Overlay
  mfd/               NEW  the panel language and the panels
    widgets.py       screen(), segbar(), lamp(), keyrow(), list_rows(), slider hit-testing, the CRT snap
    panel.py         Panel(_Overlay): a sized, anchored MFD surface; open/close; keyboard; hit map
    sound.py         SoundPanel      replaces eww osettings
    music.py         MusicPanel      replaces eww music (+ cava)
    osd.py           Osd             replaces eww osd / winosd
    notify.py        NotifyPanel     replaces dunst + eww winnotif/onotify  (D-Bus server)
    system.py        SystemPanel     replaces eww system-menu + dashboard
    calendar.py      CalendarPanel   replaces eww calendar
    popups.py        NetPopup, SysPopup  replace eww popups (netinfo, sysinfo)
    overview.py      Overview        replaces eww overview
  launch/            NEW  the launch sequence
    player.py        Sequence(_Overlay): shots, camera, cuts, effects, timing
    shots.py         the cut list as data (length, shot, camera, action, fx)
    fx.py            speed lines, smear, impact frame, insert, letterbox, line boil, shake
  frame.py           NEW  the window frame overlay (brackets, tag, LOCK)
  sources/           NEW  data sources shared by panels
    audio.py         wraps the existing eww scripts: audiostate --struct/--levels, audio-set, audio-quick
    media.py         playerctl (already in media.py today; moves here) + cava fifo reader
    sysinfo.py       cpu/ram/net/battery/bluetooth readers (from resources.py and the eww scripts)
assets/launch/       the key frames: eye.png, cage.png, shaft.png, pass.png (JPEG-free PNG, palette-mapped)
```

`app.py` wires the new panels exactly like the existing overlays (`self.overlays[...]`), adds the
`launch` player to the launcher's Enter path, and starts `frame.py` with the bar.

### The MFD language (`mfd/widgets.py`)

Drawing helpers, all in `draw.py` style (role colours only, never hex):

- `screen(cr, x, y, w, h, tag, ...)`: bezel (`bez`), outline (`line`), dark face, scanlines, a tag
  line top-left in mono with the hot word in `gold`.
- `segbar(cr, x, y, w, h, value, colour)`: segmented LED bar, 3.2 % pitch, optional peak mark.
- `lamp(cr, x, y, on, hot)`: square lamp; `on` = gold with glow, `hot` = orange (steady, no blink
  except the critical-notification lamp, which blinks at 1.2 s).
- `keyrow(cr, keys, active)`: key caps.
- `rows(cr, items, selected)`: list rows, the selected one inverted in bone.
- `crt_snap(t)`: the open animation: the screen is a line (2 % height) for the first 40 %, then
  snaps to full height in four steps; sections stagger by 120 ms. Close is the reverse at half the
  length. 380 ms open, 190 ms close.

Panels are keyboard-first and mouse-capable. Each panel keeps a hit map (`[(x0,y0,x1,y1, action)]`)
rebuilt on every paint, the same way `launcher.py` and `bar.py` do today.

### Panels

| Panel | Opens from | Content (from the eww rig, kept) | Replaces |
|---|---|---|---|
| Sound | bar volume tag click, `eva-ctl panel sound` | outputs, inputs, app streams, recording streams with level bars and per-row device pickers; quick toggles DND, night light, power profile | osettings |
| Music | bar music tag click, `eva-ctl panel music` | cover, title/artist, progress, transport, 36-band visualizer, output screen | music, winnews |
| OSD | volume/brightness keys (via `eva-ctl osd volume|bright`) | one screen: label, big number, segbar; 1.2 s hold | osd, winosd |
| Notify | D-Bus `org.freedesktop.Notifications` | stack top right, newest on top, max 5; app tag, title, body, countdown; critical pinned with hazard header; Enter ack, Esc close; actions as a key row | dunst, winnotif, onotify |
| System | bar MAGI readout click, `eva-ctl panel system` | CPU / RAM / net / disk screens with segbars and sparklines on a 1 s poll while open; bluetooth and network toggles; uptime | system-menu, dashboard, dashfs |
| Calendar | bar date click | month grid, today inverted, week numbers | calendar |
| Net / Sys popups | hover-free: click on the bar net or cpu readouts | one small screen each with the live numbers | popups |
| Overview | `eva-ctl overview` (was the hot corner, off) | workspaces as screens with window title rows; click or Enter to jump | overview, winoverview |

Session actions that were in osettings are dropped; the power menu covers them.

Panels never open two at a time on one monitor: opening one closes the other (same as the launcher
and power menu today).

### Notifications

The daemon becomes the notification server: it claims `org.freedesktop.Notifications` on the
session bus (GDBus, same stack `AlarmBand` uses to monitor it today), implements `Notify`,
`CloseNotification`, `GetCapabilities` (`body`, `actions`, `persistence`), `GetServerInformation`,
and emits `NotificationClosed` / `ActionInvoked`. `AlarmBand` stops monitoring the bus and is fed
by `NotifyPanel` directly for urgency 2. dunst is removed from `hyprland.lua` autostart by
`install.sh` (and its layer rule), with a note in the README. If the name is already owned (dunst
still running), the daemon logs it and keeps the old monitor behaviour, so nothing breaks mid-migration.

### Launch sequence (`launch/`)

Enter in the launcher: the app is executed at t = 0 (unchanged), the launcher hides, and
`Sequence` plays on the launcher's monitor on the overlay layer, keyboard none, pass-through off
for its duration. Esc skips it. Total 2.10 s (50 frames at 24):

| Cut | Length | Shot | Camera | Effects |
|---|---|---|---|---|
| C1 the eye | 0.40 s | bust in profile | push-in 1.25 → 1.37× | eye bloom on a two-frame green flash, line boil |
| C2 the cage | 0.55 s | low angle | dip 18 px, snap up | restraint bars open, orange flash 2 f, shake |
| C3 insert | 0.05 s | 発進 on bone | — | bone/ink alternating |
| C4 the shaft | 0.55 s | tall frame | whip pan bottom → top, ease-in | speed lines, smear, one inverted impact frame at midpoint |
| C5 the pass | 0.25 s | from below | push-in 1 → 1.5×, shake | speed lines |
| C6 the desk | 0.30 s | the desk | letterbox retracts | overlay cuts out, the new window is underneath |

Letterbox bars (56 px at 1440p, scaled) for C1–C5. Drawn elements run on twos (12 fps): the boil,
the insert, the flash; camera and overlays at the frame clock. The smoke is in the key frames; the
player draws no particle smoke. Frames are loaded on first use and dropped when the sequence ends
(same `release()` discipline as the other overlays). On a multi-monitor desk the sequence plays on
the monitor the launcher was on.

Key frames live in `assets/launch/` as palette-mapped PNGs (the generator's output run through the
existing `tools/gen/wallpaper_eva.py` palette map so they are strictly ink / Unit-01 purple / bone /
acid green / one orange). A `tools/gen/gen_launch.py` (the script used during design) ships so the
frames can be regenerated with more seeds.

### Window frame (`frame.py`)

One pass-through layer-shell overlay per monitor on the `top` layer, below panels. It subscribes to
the Hyprland events the daemon already gets (`activewindow`, `movewindow`, `resizewindow`,
`workspace`, `fullscreen`) and draws, around the focused tiled or floating window:

- four bone corner brackets (4 px stroke, 24 px legs) 12 px outside the border,
- a title tag top-left in the border line: app class in mincho on bone, the workspace number in purple,
- `LOCK` in gold mono top-right, in an ink block.

Nothing animates. The frame is hidden for fullscreen windows, for games (`steam_app_*`, `gamescope`)
and while the launcher, power menu or Alt+Tab is up. Hyprland keeps the 3 px purple border and the
14 px hard shadow from `hypr/eva.lua`; `border_speed` (the rotating gradient) is set to 0 in the eva
style since the frame carries the focus signal now.

### Removing the toggle

- `config.py`: drop `figure_toggle_bind` from `DEFAULTS["hyprland"]` and from the settings.lua writer.
- `hypr/eva.lua`: drop the `figure_key` bind. `EVA_SET_FIGURE` stays (used by `eva-ctl figure`).
- README: remove the key from the table and the feature line.
- Existing `eva.toml` files with the key keep working: the key is ignored with a log line.

### Configuration

```toml
[overlays]
sound = true          # the new panels, each one switchable
music = true
osd = true
notify = true         # take over org.freedesktop.Notifications
system = true
calendar = true
popups = true
overview = true
launch = true         # the launch sequence on Enter
frame = true          # the window frame

[launch]
length = 2.1          # seconds; the cut lengths scale with it
letterbox = true
insert = true

[frame]
brackets = true
tag = true
lock = true

[music]
bands = 36
cava_config = ""      # default: a generated config in the state dir

[notify]
timeout = 8           # seconds, normal urgency
max = 5
```

`eva-ctl` grows `panel <name>|close`, `osd volume|bright`, `overview`. `eva.lua` binds nothing
new. The OSD watches PipeWire through `audiostate --levels` and brightness through
`/sys/class/backlight`, so the user's existing `wpctl` / `brightnessctl` binds trigger it without
changes; `eva-ctl osd` exists for scripts.

### Error handling

- A data source that fails (script missing, cava not installed, playerctl without a player) shows
  the panel with that screen reading `NO SIGNAL` in orange; the panel never refuses to open.
- A missing key frame skips its cut and logs once; with no frames at all the launch is a 0.3 s cut
  (the current behaviour).
- The notification server falling back to monitor mode is logged at startup.
- All panels drop their textures on close (`release()`), as the overlays do today; the music panel
  stops cava on close.

### Testing

- `tests/test_offline.py` grows: each panel renders headless through `--render DIR` with fixture
  data (no scripts run), and the PNGs are checked for size and non-emptiness. The sequence renders
  its six cuts to PNGs at fixed times; the frame overlay renders brackets for a fixture geometry.
- Unit tests for `mfd/widgets.py` layout math (segbar segment counts, hit maps), `launch/shots.py`
  timing (cut lengths sum to `length`), the notification server's D-Bus method signatures (with a
  private session bus via `dbus-run-session`).
- Live checks are the user's (`eva-ctl apply` and the binds); nothing in the test suite touches the
  running Hyprland.

### Migration and packaging

- Each panel lands with its eww window retired in the same change (the eww window file is left in
  the user's dotfiles untouched; the daemon stops nothing in eww, the user removes the windows from
  `eww.yuck` when they are happy). When all panels are in, the README documents eww as no longer
  needed.
- `install.sh` and the PKGBUILD list the new optional dependencies: `cava`, `playerctl`
  (`playerctl` is already used by the bar).
- The eww data scripts the daemon reuses (`audiostate`, `audio-set`, `audio-quick`, `cavajson`)
  move into the repo under `tools/sources/` so the package does not depend on the user's dotfiles.

## Build order

1. Remove the toggle. Window frame. (small, independent, lands first)
2. `mfd/widgets.py` + `panel.py` + Sound panel. Sets the language.
3. Music panel with the visualizer. OSD.
4. Notification server and panel; AlarmBand fed from it; dunst retired.
5. System, calendar, popups, overview.
6. Launch sequence player, assets, generator script.

## Open items

- The shaft (C4) and cage (C2) key frames are the weakest; they are accepted as placeholders. Replace
  with more seeds or pose-guided generation during step 6; the player does not change.
- Whether the OSD should also show on the side monitor (default: main monitor only).

## Extra suggestions (not approved, listed for later)

- Bar readouts roll their digits like the clock does at the minute (one cut per change, no loops).
- The lock screen gets an MFD boot sequence on wake (screens snapping in before the password field).
- The eyecatch card borrows the CRT snap instead of its fade.
