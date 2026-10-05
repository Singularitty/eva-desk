#!/usr/bin/env python3
"""Build a theme's runtime assets (assets/themes/<name>/) from its generation folder.

usage: tools/build_theme_assets.py THEME GEN_DIR [--boxer cut/figure.png] [--herald RIG_DIR] [--wallpapers]
  --boxer      a silhouette RGBA (from tools/gen/sil.py): potrace-cleaned into figures/boxer.png
  --herald     a rig folder (from tools/gen/rig.py): body.png, arm_l.png, arm_r.png, rig.json copied in
  --wallpapers every GEN_DIR/final/wp/png/*.png (3440x1440 from wallpaper.py) with the theme's halftone dots baked in
"""
import shutil
import sys
from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from eva_desk import themes  # noqa: E402

src = open(ROOT / "tools/build_assets.py").read().split('if __name__ == "__main__":')[0]
ns = {"__file__": str(ROOT / "tools/build_assets.py")}
exec(compile(src, "build_assets", "exec"), ns)
vectorize = ns["vectorize"]

args = sys.argv[1:]
name, gen = args[0], Path(args[1]).expanduser()
theme = themes.get(name)
A = ROOT / "assets/themes" / name
ink = tuple(int(theme["colors"]["ink"][i:i + 2], 16) for i in (0, 2, 4))
ns["INK"] = ink

if "--boxer" in args:
    out = A / "figures"
    out.mkdir(parents=True, exist_ok=True)
    f = Path(args[args.index("--boxer") + 1])
    a = np.asarray(Image.open(f).convert("RGBA"))[..., 3]
    img = vectorize(a, 1, out / "boxer.png")
    print("boxer", img.size)

if "--herald" in args:
    out = A / "herald"
    out.mkdir(parents=True, exist_ok=True)
    rig = Path(args[args.index("--herald") + 1])
    for n in ("body.png", "arm_l.png", "arm_r.png", "rig.json"):
        shutil.copy(rig / n, out / n)
    print("herald rig copied")

if "--wallpapers" in args:
    out = A / "wallpapers"
    out.mkdir(parents=True, exist_ok=True)
    spacing = 12
    dot_col = tuple(int(theme["colors"][theme["halftone"]][i:i + 2], 16) for i in (0, 2, 4))
    dot = None
    for src in sorted((gen / "final/wp/png").glob("*.png")):
        im = Image.open(src).convert("RGB")
        if dot is None or dot.size != im.size:
            w, h = im.size
            yy, xx = np.mgrid[0:h, 0:w]
            fx, fy = (xx % spacing) - spacing / 2 + 0.5, (yy % spacing) - spacing / 2 + 0.5
            d = np.hypot(fx, fy)
            cov = np.clip(spacing * 0.30 + 0.5 - d, 0, 1) * 0.10
            dot = Image.fromarray((cov * 255).astype(np.uint8))
        im = Image.composite(Image.new("RGB", im.size, dot_col), im, dot)
        im.save(out / f"{src.stem}.webp", "WEBP", quality=90, method=6)
        print("wallpaper", src.stem)
