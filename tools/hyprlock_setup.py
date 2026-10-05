#!/usr/bin/env python3
"""Set up hyprlock for the eva look on this machine: renders a SEELE council background per monitor (at that
monitor's own size and orientation) and writes ~/.config/hypr/hyprlock.conf from the template.

usage: tools/hyprlock_setup.py [--theme eva] [--out ~/.config/hypr/hyprlock.conf] [--dry-run]
Needs hyprctl (reads the monitors). Backs up an existing hyprlock.conf as *.bak-eva-<date>.
"""
import json
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from eva_desk import config  # noqa: E402

args = sys.argv[1:]
theme = args[args.index("--theme") + 1] if "--theme" in args else "eva"
out = Path(args[args.index("--out") + 1] if "--out" in args else "~/.config/hypr/hyprlock.conf").expanduser()
dry = "--dry-run" in args
config.activate_theme(theme)
from eva_desk import draw as d  # noqa: E402
import cairo  # noqa: E402

sys.argv = [sys.argv[0], "/dev/null", "--theme", theme]      # lock_screen.py reads argv at import
ls_src = (ROOT / "tools" / "lock_screen.py").read_text().split("out.mkdir(")[0]
ns = {"__file__": str(ROOT / "tools" / "lock_screen.py")}
exec(compile(ls_src, "lock_screen", "exec"), ns)

mons = json.loads(subprocess.run(["hyprctl", "-j", "monitors"], capture_output=True, text=True, timeout=3).stdout)
pics = Path(os.environ.get("XDG_DATA_HOME", "~/.local/share")).expanduser() / "eva-desk" / "lock"
pics.mkdir(parents=True, exist_ok=True)
C = config.current_theme()["colors"]
cfg = config.load()
main = None
blocks = []
for m in mons:
    scale = float(m.get("scale", 1) or 1)
    w, h = int(m["width"] / scale), int(m["height"] / scale)
    if int(m.get("transform", 0)) % 2 == 1:
        w, h = h, w
    wanted = cfg["general"]["main_monitors"]
    is_main = (any(x == m["name"] or x in m.get("description", "") for x in wanted) if wanted else False)
    surf = cairo.ImageSurface(cairo.FORMAT_ARGB32, w, h)
    if w >= h:
        ns["council"](cairo.Context(surf), w, h)
    else:
        surf = ns["side_screen"](w, h)
    path = pics / f"{m['name']}.png"
    if not dry:
        surf.write_to_png(str(path))
    blocks.append((m["name"], w, h, is_main, path))
if not any(b[3] for b in blocks) and blocks:
    big = max(blocks, key=lambda b: b[1] * b[2])
    blocks = [(n, w, h, b is big, p) for (n, w, h, _, p) in blocks for b in [(n, w, h, _, p)]]
main = next((b for b in blocks if b[3]), blocks[0] if blocks else None)
user = os.environ.get("USER", "pilot").upper()

conf = [f"# hyprlock, {config.current_theme()['title']} look, written by eva-desk tools/hyprlock_setup.py ({time.strftime('%Y-%m-%d')})",
        "# Backgrounds: the SEELE council, one picture per monitor at its own size (re-run the tool after a monitor change).",
        "general {", "    hide_cursor = true", "    grace = 2", "    ignore_empty_input = true", "}", ""]
for name, w, h, _, path in blocks:
    conf += ["background {", f"    monitor = {name}", f"    path = {path}", "    color = rgb(020104)", "}", ""]
conf += ["background {", "    monitor =", "    color = rgb(020104)", "}", ""]
if main:
    mn = main[0]
    conf += [
        "# clock, top left, as a title card",
        "label {", f"    monitor = {mn}", "    text = cmd[update:1000] echo \"$(date +'%A %d %B' | tr '[:lower:]' '[:upper:]') · LOCKED\"",
        f"    color = rgb({C['red']})", "    font_size = 12", "    font_family = Share Tech Mono", "    position = 60, -40", "    halign = left", "    valign = top", "}",
        "label {", f"    monitor = {mn}", "    text = cmd[update:1000] date +'%H:%M'", f"    color = rgb({C['bone']})", "    font_size = 54",
        "    font_family = Shippori Mincho B1 ExtraBold", "    position = 60, -62", "    halign = left", "    valign = top", "}", "",
        "# MAGI readout, top right",
        "label {", f"    monitor = {mn}", "    text = MAGI · ALL SYSTEMS NOMINAL", f"    color = rgb({C['gold']})", "    font_size = 12",
        "    font_family = Share Tech Mono", "    position = -60, -40", "    halign = right", "    valign = top", "}",
        "label {", f"    monitor = {mn}", "    text = cmd[update:60000] echo \"UPTIME $(uptime -p | sed 's/up //; s/ days\\?/D/; s/ hours\\?/H/; s/ minutes\\?/M/; s/,//g' | tr '[:lower:]' '[:upper:]')\"",
        f"    color = rgb({C['bone3']})", "    font_size = 12", "    font_family = Share Tech Mono", "    position = -60, -62", "    halign = right", "    valign = top", "}", "",
        "# the password line",
        "label {", f"    monitor = {mn}", "    text = IDENTIFY · PILOT", f"    color = rgb({C['red']})", "    font_size = 12", "    font_family = Share Tech Mono",
        "    position = 0, -210", "    halign = center", "    valign = center", "}",
        "input-field {", f"    monitor = {mn}", "    size = 520, 56", "    outline_thickness = 2", "    dots_size = 0.25", "    dots_spacing = 0.35", "    dots_center = false",
        f"    outer_color = rgb({C['bone']})", f"    inner_color = rgb({C['ink']})", f"    font_color = rgb({C['bone']})", "    font_family = Share Tech Mono",
        "    fade_on_empty = false",
        f"    placeholder_text = <span foreground=\"##{C['gold']}\" font_family=\"Share Tech Mono\">{user}  </span><span foreground=\"##{C['dim']}\">········</span>",
        "    hide_input = false", "    rounding = 0", f"    check_color = rgb({C['gold']})", f"    fail_color = rgb({C['led']})",
        "    fail_text = <span font_family=\"Share Tech Mono\">ACCESS DENIED · $ATTEMPTS</span>", f"    capslock_color = rgb({C['coral']})",
        "    position = 0, -270", "    halign = center", "    valign = center", "    shadow_passes = 1", "    shadow_size = 10",
        f"    shadow_color = rgb({C['claret']})", "    shadow_boost = 1.0", "}",
        "label {", f"    monitor = {mn}", "    text = SOUND ONLY", f"    color = rgb({C['dim']})", "    font_size = 11", "    font_family = Share Tech Mono",
        "    position = 0, -330", "    halign = center", "    valign = center", "}", "",
    ]
text = "\n".join(conf)
if dry:
    print(text)
else:
    if out.exists():
        bak = out.with_name(out.name + ".bak-eva-" + time.strftime("%Y%m%d-%H%M%S"))
        bak.write_text(out.read_text())
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text)
    print("hyprlock:", out, "| backgrounds:", ", ".join(str(b[4]) for b in blocks))
