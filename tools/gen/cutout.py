#!/usr/bin/env python3
"""Cut a generated figure off its flat background and recolour it into the desk palette.

usage: cutout.py in.png out.png [--ramp wine|red|gold|iron|none] [--t0 0.10] [--t1 0.30] [--max-h 1100]
"""
import argparse
import numpy as np
from PIL import Image
from scipy import ndimage as ndi

REFS, SOLID, GAP = [], False, 0.09

RAMPS = {
    "wine": [(0.00, "#0c0608"), (0.30, "#2a0710"), (0.52, "#8e1b33"), (0.72, "#e86a4a"), (0.88, "#e9d29a"), (1.00, "#fff6e6")],
    "red":  [(0.00, "#0c0608"), (0.34, "#3b0a14"), (0.60, "#ff4d3a"), (0.84, "#efe4cf"), (1.00, "#ffffff")],
    "gold": [(0.00, "#0c0608"), (0.30, "#2a0710"), (0.58, "#c9a24a"), (0.82, "#e9d29a"), (1.00, "#fff6e0")],
    "iron": [(0.00, "#060304"), (0.40, "#1c1012"), (0.66, "#5c0f22"), (0.86, "#ff5a3a"), (1.00, "#ffc9a0")],
    "bone": [(0.00, "#0c0608"), (0.40, "#1a0d10"), (0.70, "#8a7a68"), (1.00, "#efe4cf")],
}


def hex2rgb(h):
    return np.array([int(h[i:i + 2], 16) for i in (1, 3, 5)], float) / 255


def ramp_map(L, stops):
    xs = [s[0] for s in stops]
    cols = np.stack([hex2rgb(s[1]) for s in stops])
    return np.stack([np.interp(L, xs, cols[:, c]) for c in range(3)], axis=-1)


def border_bg(img):
    h, w, _ = img.shape
    s = max(4, int(min(h, w) * 0.025))
    strips = np.concatenate([img[:s].reshape(-1, 3), img[:, :s].reshape(-1, 3), img[:, -s:].reshape(-1, 3)])
    return np.median(strips, axis=0)


def cut(img, t0, t1, key="green"):
    bg = border_bg(img)
    if key == "green":
        # green dominance survives vignetting and floor shadows that a plain colour distance does not
        # ratio, not difference, so a dim vignette corner reads as green as the lit middle
        s = (img[..., 1] - np.maximum(img[..., 0], img[..., 2])) / np.maximum(img[..., 1], 0.10)
        a = 1 - np.clip((s - t0) / (t1 - t0), 0, 1)
    elif key == "refs":
        # distance to the nearest of several backdrop greens (wall, floor, floor shadow): reflective
        # armour that only picked up a green tint stays solid
        d = np.min([np.linalg.norm(img - np.array(r) / 255, axis=2) for r in REFS], axis=0)
        a = np.clip((d - t0) / (t1 - t0), 0, 1)
    else:
        d = np.linalg.norm(img - bg, axis=2)
        a = np.clip((d - t0) / (t1 - t0), 0, 1)
    hard = a > 0.5
    lab, n = ndi.label(hard)
    if n:
        sizes = ndi.sum(hard, lab, range(1, n + 1))
        big = int(np.argmax(sizes)) + 1
        edge = set(np.unique(np.concatenate([lab[0], lab[:, 0], lab[:, -1]]))) - {0}
        ok = [i + 1 for i in np.flatnonzero(sizes >= sizes.max() * 0.01) if i + 1 == big or i + 1 not in edge]
        keep = np.isin(lab, ok)
    else:
        keep = hard
    # fill only pinholes; real gaps (between arm and head, legs, sword) stay open
    holes = ndi.binary_fill_holes(keep) & ~keep
    hl, hn = ndi.label(holes)
    if hn:
        hs = ndi.sum(holes, hl, range(1, hn + 1))
        small = np.isin(hl, 1 + np.flatnonzero(hs < img.shape[0] * img.shape[1] * 0.0004))
        a = np.where(small, 1.0, a)
        keep = keep | small
    a = a * ndi.binary_dilation(keep, iterations=2)
    if SOLID:
        # seal thin openings, fill everything enclosed, then reopen only true see-through gaps:
        # pixels that match a backdrop green almost exactly (reflections only carry a green tint)
        filled = ndi.binary_fill_holes(keep)
        refs = REFS or [tuple(bg * 255)]
        d_bg = np.min([np.linalg.norm(img - np.array(r) / 255, axis=2) for r in refs], axis=0)
        gap = filled & (d_bg < GAP)
        gl, gn = ndi.label(gap)
        if gn:
            gs = ndi.sum(gap, gl, range(1, gn + 1))
            gap = np.isin(gl, 1 + np.flatnonzero(gs >= 200))
        solid = ndi.binary_erosion(filled & ~gap, iterations=1)
        a = np.maximum(a, np.clip(ndi.gaussian_filter(solid.astype(float), 1.0) * 1.6, 0, 1))
    # unmix soft edges: observed = a*fg + (1-a)*bg
    if key in ("green", "refs"):
        fg = img.copy()
        fg[..., 1] = np.minimum(fg[..., 1], np.maximum(fg[..., 0], fg[..., 2]))  # despill
    else:
        am = np.maximum(a, 0.05)[..., None]
        fg = np.clip((img - (1 - a[..., None]) * bg) / am, 0, 1)
    return fg, a, bg


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("src")
    ap.add_argument("dst")
    ap.add_argument("--ramp", default="wine")
    ap.add_argument("--key", default="green", choices=["green", "dist", "refs"])
    ap.add_argument("--refs", default="", help="backdrop colours 'r,g,b;r,g,b' for --key refs")
    ap.add_argument("--solid", action="store_true", help="make everything enclosed by the figure opaque except true gaps")
    ap.add_argument("--gap", type=float, default=0.09, help="max distance to a backdrop colour for a true gap")
    ap.add_argument("--t0", type=float, default=0.22)
    ap.add_argument("--t1", type=float, default=0.45)
    ap.add_argument("--max-h", type=int, default=1100)
    ap.add_argument("--gamma", type=float, default=1.0)
    ap.add_argument("--flip", action="store_true")
    a = ap.parse_args()
    global REFS, SOLID, GAP
    REFS = [tuple(int(v) for v in c.split(",")) for c in a.refs.split(";") if c] if a.refs else []
    SOLID = a.solid
    GAP = a.gap

    img = np.asarray(Image.open(a.src).convert("RGB"), float) / 255
    fg, alpha, bg = cut(img, a.t0, a.t1, a.key)

    if a.ramp != "none":
        # luminance without the backdrop's hue leaking in through spill
        L = fg.max(axis=2) * 0.6 + fg.mean(axis=2) * 0.4
        inside = alpha > 0.9
        lo, hi = np.percentile(L[inside], [3, 99.6]) if inside.any() else (0, 1)
        L = np.clip((L - lo) / max(hi - lo, 1e-3), 0, 1) ** a.gamma
        fg = ramp_map(L, RAMPS[a.ramp])

    rgba = np.dstack([fg, alpha])
    ys, xs = np.nonzero(alpha > 0.02)
    pad = 6
    y0, y1 = max(ys.min() - pad, 0), min(ys.max() + pad + 1, img.shape[0])
    x0, x1 = max(xs.min() - pad, 0), min(xs.max() + pad + 1, img.shape[1])
    out = Image.fromarray((rgba[y0:y1, x0:x1] * 255 + 0.5).astype(np.uint8), "RGBA")
    if a.flip:
        out = out.transpose(Image.FLIP_LEFT_RIGHT)
    if out.height > a.max_h:
        out = out.resize((round(out.width * a.max_h / out.height), a.max_h), Image.LANCZOS)
    out.save(a.dst, optimize=True)
    print(f"{a.dst}: {out.width}x{out.height} bg={np.round(bg * 255).astype(int).tolist()}")


if __name__ == "__main__":
    main()
