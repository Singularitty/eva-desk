#!/usr/bin/env python3
"""prep_art.py OUT [--raw DIR]: the standby pictures as the desk draws them.

Each picture of PICKS (made by gen_rim.py, read from DIR, by default the raw/ folder beside this file) is split
into two layers, which the standby loop puts on with a screen blend:

  NAME_body.jpg   the picture without the glow of its eyes
  NAME_eye.jpg    that glow alone, on black, so that it can breathe

OUT/art.json says how large each picture is and where its eyes are: {name: {"w", "h", "eyes": [[x, y], ...]}},
the eyes as fractions of the picture. Needs numpy, scipy and Pillow.
"""
import argparse
import json
from pathlib import Path

import numpy as np
from PIL import Image
from scipy import ndimage as ndi

HERE = Path(__file__).resolve().parent
PICKS = {"profile": "r_bust_5002", "front": "r_front_5000", "full": "r_full_5005"}     # the pictures the desk ships


def black_floor(im):
    """The generator's black is a dark grey: set it to true black, so that a screen blend adds nothing there."""
    edge = np.concatenate([im[:24].reshape(-1, 3), im[-24:].reshape(-1, 3), im[:, :24].reshape(-1, 3), im[:, -24:].reshape(-1, 3)])
    floor = np.percentile(edge, 40, axis=0) * 1.15
    return np.clip((im - floor) / (1 - floor), 0, 1)


def split(im, name):
    """(body, eye, eyes) of a picture that has been through black_floor(): body + eye is the picture again, and
    eyes are the centres of its lit eyes, left to right, as fractions of the picture. "front" has two eyes, the
    others one; "full" is a whole figure, whose eyes are looked for in its head only."""
    r, g, b = im[..., 0], im[..., 1], im[..., 2]
    green = g - np.maximum(r, b)                                    # greener than anything else
    core = (green > 0.18) & (g > 0.45)                              # the lit eye itself
    if name == "full":                                              # the eyes are small and the chest lights are brighter,
        lit = im.max(axis=2) > 0.07                                 # so look only in the head, the top of the figure
        rows = np.flatnonzero(lit.sum(axis=1) > lit.shape[1] * 0.004)
        if rows.size:
            top, bottom = rows[0], rows[-1]
            head = np.zeros_like(core)
            head[top:top + int((bottom - top) * 0.22)] = True
            relaxed = (green > 0.08) & (g > 0.25) & head
            rl, rn = ndi.label(ndi.binary_dilation(relaxed, iterations=6))
            if rn:                                                  # the shoulder pylons are green too, but dull: the eyes are the purest green there
                peaks = ndi.maximum(np.where(relaxed, green, 0), rl, range(1, rn + 1))
                best = int(np.argmax(peaks)) + 1
                if peaks[best - 1] > 0.2:
                    core = relaxed & (rl == best)
    lab, n = ndi.label(ndi.binary_dilation(core, iterations=10))   # one eye, even when a lid splits its glow in two
    eyes = []
    if n:
        sizes = ndi.sum(core, lab, range(1, n + 1))
        cands = [i + 1 for i in np.flatnonzero(sizes >= max(20, sizes.max() * 0.03))]
        cands = sorted(cands, key=lambda i: -sizes[i - 1])[:6] or [int(np.argmax(sizes)) + 1]
        spots = sorted((float(cy) / im.shape[0], float(cx) / im.shape[1], i)
                       for (cy, cx), i in zip(ndi.center_of_mass(core, lab, cands), cands))        # other lights sit lower: the eyes are the highest
        top = spots[0]
        pair = [sp for sp in spots[1:] if name == "front" and abs(sp[0] - top[0]) < 0.05 and abs(sp[1] - top[1]) < 0.12][:1]
        eyes = sorted([round(sp[1], 4), round(sp[0], 4)] for sp in [top] + pair)
        core = core & np.isin(lab, [sp[2] for sp in [top] + pair])
    near = ndi.binary_dilation(core, iterations=48)                 # the glow lives close to the eye
    soft = np.clip((green - 0.03) / 0.16, 0, 1) * near
    soft = np.maximum(ndi.gaussian_filter(soft, 2.5), core)
    return im * (1 - soft[..., None]), im * soft[..., None], eyes


def write(name, im, out):
    """NAME_body.jpg and NAME_eye.jpg in `out`; returns the picture's entry in art.json."""
    body, eye, eyes = split(im, name)
    for layer, suffix in ((body, "body"), (eye, "eye")):
        Image.fromarray((np.clip(layer, 0, 1) * 255 + 0.5).astype(np.uint8)).save(Path(out) / f"{name}_{suffix}.jpg", quality=92)
    return {"w": im.shape[1], "h": im.shape[0], "eyes": eyes}


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("out")
    ap.add_argument("--raw", default=str(HERE / "raw"))
    a = ap.parse_args()
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    art = {}
    for name, take in PICKS.items():
        im = black_floor(np.asarray(Image.open(Path(a.raw).expanduser() / f"{take}.png").convert("RGB"), float) / 255)
        art[name] = write(name, im, out)
        print(f"{name}: {len(art[name]['eyes'])} eye(s) {art[name]['eyes']}")
    (out / "art.json").write_text(json.dumps(art, indent=1) + "\n")


if __name__ == "__main__":
    main()
