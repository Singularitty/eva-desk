# Motion graphics, plans 4 and 5: the living wallpaper and the status wall

This is a record, written as the two steps were built. The owner asked for the rest of the spec to be built
without a plan review for each step, so the decisions a plan would have put to him are listed here instead, with
what each costs if it is wrong. The tests are in `tests/test_motion.py`; they were written first.

**Spec:** `docs/superpowers/specs/2026-10-13-motion-graphics-design.md`, build steps 4 and 5: "Living wallpaper",
"Side wall", "Pause rules and cost". The spec says what was built where it differs from the first design.

## What was built

| File | What it holds |
|---|---|
| `eva_desk/motion/amb/wallpaper.py` | `WallpaperLoop`: the drift, the ripples, the embers; `camera`, `place`, `rings`, `ring_centre`, `embers` as plain functions |
| `eva_desk/motion/living.py` | `Living`: a background layer per main monitor, the pictures it is handed, the cross-fade, what stands still; `decode` on a thread |
| `eva_desk/motion/amb/wall.py` | `WallLoop`: the screens; `History`, a minute of readings read back at any moment; `layout`, one to three columns |
| `eva_desk/motion/sidewall.py` | `SideWall`: the wall's layer on the bottom of its monitor, a reading a second while it is up; `uptime_text` |
| `eva_desk/motion/player.py` | `AmbientLayer`: the layer it sits on, `pause`, `resume`, `redraw` |
| `eva_desk/motion/kit.py` | `sprite`, `screen`, `spark`, `keep`, `screen_box` |
| `eva_desk/motion/triggers.py` | `paused_monitors`, `wall_monitor`, `workspace_empty` |
| `eva_desk/wallpaper.py` | the `living` hook, `direct` (the awww path), `forget` |
| `eva_desk/app.py` | owns both hosts; `_ambient_sync`, `_wall_sync`, `_living_show`, `_living_failed`; `eva-ctl ambient [on|off]` |
| `eva_desk/config.py`, `config/eva.example.toml` | `[ambient] wallpaper, drift, lap, ripples, embers, wall, wall_monitor` |
| `hypr/eva.lua`, `bin/eva-ctl`, `README.md` | the layer rule gains `wallpaper` and `wall`; the command; the features |

Test classes: `AmbientPause`, `PauseRules`, `WallpaperTest`, `LivingTest`, `LivingWiring`, `WallKit`, `WallTest`,
`WallRules`, `SideWallTest`, `WallWiring`.

## Decisions taken without the owner

1. **The wallpaper layer is on the background layer**, not the bottom one the spec named. On the bottom layer an
   opaque full-screen surface would cover other programs' desktop widgets and would depend on being created
   before the stage. If wrong: an awww daemon that restarts could come up over it and show a still picture.
2. **A picture is handed over through a hook on `Wallpapers`**, and the daemon's own wallpaper needs no awww.
   A picture the daemon cannot read gives the monitor back and goes to awww. If wrong: a monitor with no
   wallpaper where neither can show it, which is what happened before for such a picture.
3. **`drift = 0` is a still picture**, with no pan either.
4. **`eva-ctl ambient off` lasts until `ambient on` or the daemon's next start.** It is not written anywhere.
5. **The wall has no progress bar for the track.** The player watch gives no position, and asking a player for it
   every second means running a program every second.
6. **The wall's WORKSPACES marks the focused monitor's workspace.**
7. **The wall takes as many columns as make its screens largest.** A monitor standing upright gets the one column
   of the mock-up; a wide one gets two, a very wide one three. Nobody has seen the wide layouts but in a render.
8. **The wall runs at fifteen frames a second at most, and its curves move on five times a second.** Built whole,
   a frame took 4 ms, thirty times a second; with its still part kept as one node it takes 0.6 ms. If wrong:
   curves that look as if they step.
9. **The wall reads the CPU, the memory and the network itself**, with a sampler of its own, once a second and
   only while it is up and running. The bar's readings are untouched.
10. **Both are on by default**, as the spec's configuration has them.
11. **A wall that must stand still is taken down**, where the spec has a paused piece keep its last frame. A clock
    that has stopped still reads as the time, and so do readings. If wrong: the side monitor shows its bare
    wallpaper while a game is open, where a frozen wall may have been wanted.
12. **The wallpaper layer never shows through.** What lies under it is awww's last picture, which is not the
    desk's any more. So the first picture goes up whole, and a picture that follows a colour fades in over that
    colour. Only a picture that follows a picture cross-fades.

## What the review changed

A fresh reviewer read both steps when they were built. It proved no way to lose the wallpaper in ordinary use,
and found these, each fixed with a test seen failing first (class `LoopsHardening` and the changed tests):

- A layer's window was shown again after its monitor had gone away. A monitor that comes back now gets a new
  layer, as the stage and the bar do.
- The loops were never told to stand still at start-up, and a sync that could not ask Hyprland was skipped and
  not tried again. It now runs after the first refresh and after one that raised, tries again every second
  while Hyprland does not answer, and what stops the loops everywhere (a lock, sleep, standby, `ambient off`)
  asks Hyprland nothing. A lock answer that did not come is not an unlock.
- A wallpaper layer that broke hid itself and nobody was told. It gives the monitor back, and awww shows the
  wallpaper. A hand-over that raises goes to awww.
- A hidden layer kept its last pictures. `decode` answers whatever goes wrong. Only `#rrggbb` is a colour, and a
  malformed one leaves what is up. The layer's monitor comes from GTK, not from a table that was never pruned.
- The wall cost 4 ms a frame; see decision 8. After a gap its minute starts again instead of drawing a ramp.

## What only a live run can prove

- That the wallpaper layer lies over awww's surface and under the stage, on every main monitor, and that the
  desk is never without a wallpaper: at start, on a workspace switch, on a shuffle, after a monitor is replugged.
- The cross-fade, the drift at real speed, the ripples and the embers over a real wallpaper.
- The GPU's load with the wallpaper running, with and without blur behind the bar and windows (`nvidia-smi`): it
  must stay well clear of full. This fixes the default `fps`.
- That nothing repaints while a game is open: the wallpaper and the wall stand still, and a game's frame times
  are the same with the daemon running as without.
- That the wall comes up on the side monitor when its workspace is empty and goes when a window opens there; its
  readings against the bar's; the layout at the monitor's real size.
- `eva-ctl ambient off` and `on`; the loops under a lock screen, across sleep, and under standby.
