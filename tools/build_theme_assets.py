#!/usr/bin/env python3
"""Build a theme's runtime assets (assets/themes/<name>/) from its generation folder.

usage: tools/build_theme_assets.py THEME GEN_DIR [--figure cut/figure.png] [--herald RIG_DIR]
  --figure      a silhouette RGBA (from tools/gen/sil.py): potrace-cleaned into figures/unit01.png
  --herald     a rig folder (from tools/gen/rig.py): body.png, arm_l.png, arm_r.png, rig.json copied in
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

if "--figure" in args:
    out = A / "figures"
    out.mkdir(parents=True, exist_ok=True)
    f = Path(args[args.index("--figure") + 1])
    a = np.asarray(Image.open(f).convert("RGBA"))[..., 3]
    img = vectorize(a, 1, out / "figure.png")
    print("figure", img.size)

if "--herald" in args:
    out = A / "herald"
    out.mkdir(parents=True, exist_ok=True)
    rig = Path(args[args.index("--herald") + 1])
    for n in ("body.png", "arm_l.png", "arm_r.png", "rig.json"):
        shutil.copy(rig / n, out / n)
    print("herald rig copied")
