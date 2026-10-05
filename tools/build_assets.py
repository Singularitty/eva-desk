#!/usr/bin/env python3
"""Build the theme's runtime assets from the image-generation pipeline output.

usage: tools/build_assets.py [GEN_DIR]
GEN_DIR is the pipeline folder holding raw/ and final/ (default ~/.local/share/sdcpp/vibe/gen).
Writes into assets/: figures (boxer silhouette, knight + glow, castle), the herald rig (body and two arms
as crisp vector renders + pivots) and the dark wallpapers with the halftone dots baked in.
"""
import json
import math
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np
from PIL import Image, ImageFilter
from scipy import ndimage as ndi

ROOT = Path(__file__).resolve().parent.parent
A = ROOT / "assets"
GEN = Path(sys.argv[1]) if len(sys.argv) > 1 else Path.home() / ".local/share/sdcpp/vibe/gen"
INK = (12, 6, 8)


def vectorize(alpha, scale, out):
    """Trace a coverage mask with potrace and render it back at `scale` for clean silhouette edges."""
    h, w = alpha.shape
    with tempfile.TemporaryDirectory() as td:
        pbm, svg = Path(td) / "m.pbm", Path(td) / "m.svg"
        bits = np.packbits((alpha >= 128).astype(np.uint8), axis=1)
        pbm.write_bytes(f"P4\n{w} {h}\n".encode() + bits.tobytes())
        subprocess.run(["potrace", "-s", "--turdsize", "6", "--alphamax", "1.0", "--opttolerance", "0.2",
                        "-o", str(svg), str(pbm)], check=True)
        png = Path(td) / "m.png"
        subprocess.run(["rsvg-convert", "-w", str(w * scale), "-h", str(h * scale), "-o", str(png), str(svg)], check=True)
        cov = np.asarray(Image.open(png).convert("RGBA"))[..., 3]
    img = Image.new("RGBA", cov.shape[::-1], INK + (0,))
    img.putalpha(Image.fromarray(cov))
    img.save(out, optimize=True)
    return img


def figures():
    out = A / "figures"
    out.mkdir(parents=True, exist_ok=True)
    boxer = np.asarray(Image.open(GEN / "final/png/boxer_red.png").convert("RGBA"))[..., 3]
    vectorize(boxer, 1, out / "boxer.png")

    knight = Image.open(GEN / "final/png/knight.png").convert("RGBA")
    knight.save(out / "knight.png", optimize=True)
    # cairo cannot blur at runtime: ship the ember glow as a soft mask (white, tinted when drawn)
    a = knight.split()[3]
    pad = 40
    big = Image.new("L", (a.width + 2 * pad, a.height + 2 * pad), 0)
    big.paste(a, (pad, pad))
    glow = big.filter(ImageFilter.MaxFilter(9)).filter(ImageFilter.GaussianBlur(14))
    rim = big.filter(ImageFilter.MaxFilter(5)).filter(ImageFilter.GaussianBlur(1.3))
    for name, m in (("knight_glow.png", glow), ("knight_rim.png", rim)):
        g = Image.new("RGBA", big.size, (255, 255, 255, 0))
        g.putalpha(m)
        g.save(out / name, optimize=True)
    (out / "knight.json").write_text(json.dumps({"glow_pad": pad}))

    castle = Image.open(GEN / "raw/castle_b_3000.png").convert("RGB")
    w, h = castle.size
    ch = round(w / (3440 / 1440))
    castle = castle.crop((0, (h - ch) // 2, w, (h - ch) // 2 + ch)).resize((3440, 1440), Image.LANCZOS)
    castle = castle.filter(ImageFilter.UnsharpMask(radius=2, percent=50, threshold=2))
    castle.save(out / "castle.jpg", "JPEG", quality=90, optimize=True)
    print("figures ok")


def herald(scale=2):
    """Body + two arms cut from the aligned arms-out frame, jointed at the shoulders (see herald_frames.py)."""
    out = A / "herald"
    out.mkdir(parents=True, exist_ok=True)
    meta = json.loads((GEN / "final/herald.json").read_text())
    a = np.asarray(Image.open(GEN / "final/png/herald2.png"))[..., 3].astype(np.uint8)
    H, W = a.shape
    TOP, BOT = 296, 428
    PIV_L, PIV_R, R = (380, 390), (628, 390), 36
    yy, xx = np.mgrid[0:H, 0:W]
    d_l = np.hypot(xx - PIV_L[0], yy - PIV_L[1])
    d_r = np.hypot(xx - PIV_R[0], yy - PIV_R[1])
    band_l = ((yy >= TOP) & (yy < BOT) & (xx < PIV_L[0])) | ((yy >= BOT) & (yy < BOT + 18) & (xx < 362))
    band_r = ((yy >= TOP) & (yy < BOT) & (xx > PIV_R[0])) | ((yy >= BOT) & (yy < BOT + 18) & (xx > 646))
    m_l, m_r = band_l & (d_l > R - 2), band_r & (d_r > R - 2)
    body = np.where(m_l | m_r, 0, a)
    body = np.maximum(body, ((d_l <= R) | (d_r <= R)).astype(np.uint8) * 255)

    def theta(mask, piv, side):
        ys, xs = np.nonzero(mask & (a > 128))
        i = np.argmin(xs) if side < 0 else np.argmax(xs)
        return 90 + math.degrees(math.atan2(piv[1] - ys[i], abs(xs[i] - piv[0])))

    vectorize(body, scale, out / "body.png")
    vectorize(np.where(m_l, a, 0).astype(np.uint8), scale, out / "arm_l.png")
    vectorize(np.where(m_r, a, 0).astype(np.uint8), scale, out / "arm_r.png")
    rig = {"w": W * scale, "h": H * scale, "pivot_l": [PIV_L[0] * scale, PIV_L[1] * scale],
           "pivot_r": [PIV_R[0] * scale, PIV_R[1] * scale], "theta0_l": theta(m_l, PIV_L, -1),
           "theta0_r": theta(m_r, PIV_R, 1), "head": meta["head"] * scale, "feet": meta["feet"] * scale,
           "cx": meta["cx"] * scale, "theta_from": 15, "theta_to": 155}
    (out / "rig.json").write_text(json.dumps(rig, indent=1))
    print("herald ok", {k: (round(v, 1) if isinstance(v, float) else v) for k, v in rig.items()})


def wallpapers(spacing=12):
    out = A / "wallpapers"
    out.mkdir(parents=True, exist_ok=True)
    # halftone dots (the boards' "dot effect"): bone at 10%, baked so any wallpaper daemon shows them
    dot = None
    for src in sorted((GEN / "final/wp/png").glob("dk_*.png")):
        im = Image.open(src).convert("RGB")
        if dot is None or dot.size != im.size:
            w, h = im.size
            yy, xx = np.mgrid[0:h, 0:w]
            fx, fy = (xx % spacing) - spacing / 2 + 0.5, (yy % spacing) - spacing / 2 + 0.5
            d = np.hypot(fx, fy)
            cov = np.clip(spacing * 0.30 + 0.5 - d, 0, 1) * 0.10
            dot = Image.fromarray((cov * 255).astype(np.uint8))
        bone = Image.new("RGB", im.size, (239, 228, 207))
        im = Image.composite(bone, im, dot)
        name = src.stem.removeprefix("dk_")
        im.save(out / f"{name}.webp", "WEBP", quality=90, method=6)
        print("wallpaper", name)


if __name__ == "__main__":
    figures()
    herald()
    wallpapers()
