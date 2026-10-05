#!/usr/bin/env python3
"""Build a eva-desk icon theme from an installed Everforest (Suru++) icon theme: same role colours as the
GTK theme, but folders go claret instead of the accent. make-icon-theme.py [--theme vibe|eva] [SOURCE_THEME_DIR]"""
import importlib.util, os, re, shutil, subprocess, sys
from pathlib import Path

HERE = Path(__file__).parent
spec = importlib.util.spec_from_file_location("gtkmk", HERE / "make-gtk-theme.py")
src_text = (HERE / "make-gtk-theme.py").read_text().rsplit("\nmain()", 1)[0]   # reuse the colour mapping, not main()
ns = {"__file__": str(HERE / "make-gtk-theme.py")}
args = sys.argv[1:]
theme_args = args[args.index("--theme"):args.index("--theme") + 2] if "--theme" in args else []
rest = [a for a in args if a not in theme_args]
sys.argv = [sys.argv[0]] + theme_args
exec(compile(src_text, "make-gtk-theme.py", "exec"), ns)
import colorsys
hexmap, T = ns["hexmap"], ns["T"]
FOLDER = tuple(int(T["colors"]["claret"][i:i + 2], 16) for i in (0, 2, 4))

SRC = Path(rest[0] if rest else "~/.local/share/icons/Everforest-Dark").expanduser()
DST = SRC.parent / T["gtk_theme"]

def folder_map(h):
    r, g, b = (int(h[i:i + 2], 16) for i in (0, 2, 4))
    hue, sat, val = colorsys.rgb_to_hsv(r / 255, g / 255, b / 255)
    if sat > 0.2 and 60 <= hue * 360 < 170:              # the green accent of the folder -> claret, keeping its lightness
        k = 0.45 + 0.75 * val
        return "%02x%02x%02x" % tuple(min(255, round(c * k)) for c in FOLDER)
    return hexmap(h)

def main():
    if DST.exists():
        shutil.rmtree(DST)
    shutil.copytree(SRC, DST, symlinks=True)
    n = 0
    for p in DST.rglob("*.svg"):
        if p.is_symlink():
            continue
        t = p.read_text(errors="ignore")
        fn = folder_map if "places" in p.parts else hexmap
        t2 = re.sub(r"#([0-9a-fA-F]{6})\b", lambda m: "#" + fn(m.group(1)), t)
        if t2 != t:
            p.write_text(t2); n += 1
    idx = DST / "index.theme"
    idx.write_text(re.sub(r"(?m)^Name=.*", "Name=" + T["gtk_theme"], idx.read_text()))
    (DST / "icon-theme.cache").unlink(missing_ok=True)
    subprocess.run(["gtk-update-icon-cache", "-f", "-t", str(DST)], check=False)
    print(f"icon theme written: {DST} ({n} svgs recoloured)")

main()
