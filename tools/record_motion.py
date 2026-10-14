#!/usr/bin/env python3
"""Render the README's motion images from the pieces' own drawing code. Nothing is recorded from a screen, so the
result is the same on every machine and can be remade after any change.

  docs/eva-launch.gif      the two launch sequences: the card for an app, the shaft for a game
  docs/eva-sequences.png   boot, wake, berserk and the track card, one frame each
  docs/eva-standby.png     the four shots of standby
  docs/eva-wallpaper.gif   the living wallpaper, at real speed
  docs/eva-wall.png        the status wall

The wallpaper and the wall are shown over one of standby's pictures, as a stand-in for a wallpaper of your own.
Needs Pillow. usage: tools/record_motion.py [--width 960]
"""
import io
import sys
import tempfile
from pathlib import Path

from PIL import Image, ImageChops

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from eva_desk import config  # noqa: E402

config.load("/nonexistent")
from eva_desk import gtkutil  # noqa: E402,F401  (pins GTK 4 before any gi.repository import)
from gi.repository import Gdk  # noqa: E402

from eva_desk.motion import everything, render  # noqa: E402

args = sys.argv[1:]
WIDTH = int(args[args.index("--width") + 1]) if "--width" in args else 960
FW, FH = 1720, 720                                   # a 3440x1440 monitor, in the frame the pieces lay out from
DOCS = ROOT / "docs"
PIECES = everything()


def frame(piece, t, ctx, under, w=FW, h=FH):
    """One frame of `piece` at t over the picture `under` (or nothing), as an RGB image of w x h."""
    buf = io.BytesIO()
    render.frame(piece, t, w, h, ctx).write_to_png(buf)
    top = Image.open(buf).convert("RGBA")
    ground = under.copy() if under is not None else Image.new("RGBA", (w, h), (0, 0, 0, 255))
    return Image.alpha_composite(ground, top).convert("RGB")


def scaled(image, width):
    return image.resize((width, round(width * image.height / image.width)), Image.LANCZOS)


def gif(path, frames, fps, colours=128, dither=False):
    """frames as one looping GIF, every frame on one palette made from a few of them."""
    sample = Image.new("RGB", (frames[0].width, frames[0].height * 4))
    for i, k in enumerate(range(0, len(frames), max(1, len(frames) // 4))):
        if i < 4:
            sample.paste(frames[k], (0, i * frames[0].height))
    palette = sample.quantize(colors=colours, method=Image.Quantize.MEDIANCUT)
    mode = Image.Dither.FLOYDSTEINBERG if dither else Image.Dither.NONE
    out = [f.quantize(palette=palette, dither=mode) for f in frames]
    out[0].save(path, save_all=True, append_images=out[1:], duration=round(1000 / fps), loop=0, optimize=True)
    print(f"{path.relative_to(ROOT)}: {len(frames)} frames, {path.stat().st_size // 1024} KB")


def grid(path, cells, cols=2):
    """Frames in a grid the size of the README's other pictures, with a thin ink gutter between them."""
    W = 1280
    cw = (W - (cols - 1) * 4) // cols
    ch = round(cw * FH / FW)
    rows = (len(cells) + cols - 1) // cols
    out = Image.new("RGB", (W, rows * ch + (rows - 1) * 4), (6, 3, 12))
    for i, cell in enumerate(cells):
        out.paste(cell.resize((cw, ch), Image.LANCZOS), ((i % cols) * (cw + 4), (i // cols) * (ch + 4)))
    out.save(path, optimize=True)
    print(f"{path.relative_to(ROOT)}: {out.size[0]}x{out.size[1]}, {path.stat().st_size // 1024} KB")


def stand_in():
    """One of standby's pictures, its two layers put back together, as a wallpaper for the demo."""
    body = Image.open(ROOT / "assets/motion/profile_body.jpg").convert("RGB")
    eye = Image.open(ROOT / "assets/motion/profile_eye.jpg").convert("RGB")
    picture = ImageChops.screen(body, eye)
    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
        picture.save(f.name)
        texture = Gdk.Texture.new_from_filename(f.name)
    Path(f.name).unlink()
    return picture, texture


def main():
    ctx = render.fixture_ctx()
    desk = Image.open(DOCS / "eva-stage.png").convert("RGBA").resize((FW, FH), Image.LANCZOS)
    small = [scaled(desk.convert("RGB"), WIDTH)]

    # the launch: the card for an app, a beat of desk, the shaft for a game
    fps, frames = 15, []
    for name, app in (("card", "FIREFOX"), ("shaft", "HADES")):
        piece = PIECES[name]()
        frames += small * 6
        frames += [scaled(frame(piece, i / fps, {**ctx, "app": app}, desk), WIDTH) for i in range(round(piece.length * fps) + 1)]
    gif(DOCS / "eva-launch.gif", frames + small * 8, fps)

    # the four sequences that play by themselves, at the moment each names as its still
    grid(DOCS / "eva-sequences.png", [frame(PIECES[name](), PIECES[name]().still, ctx, desk) for name in ("boot", "wake", "berserk", "track")])

    # standby: one frame from each shot
    standby = PIECES["standby"]()
    grid(DOCS / "eva-standby.png", [frame(standby, t, ctx, None) for t in (4.0, 16.5, 38.0, 49.0)])

    # the living wallpaper, at real speed, and the wall over the same stand-in
    picture, texture = stand_in()
    wall_ctx = {**ctx, "picture": texture}
    wallpaper, fps = PIECES["wallpaper"](), 8
    gif(DOCS / "eva-wallpaper.gif", [scaled(frame(wallpaper, 0.5 + i / fps, wall_ctx, None), WIDTH) for i in range(fps * 6)], fps,
        colours=128, dither=True)
    under = picture.convert("RGBA").resize((FW, FH), Image.LANCZOS)
    path = DOCS / "eva-wall.png"
    frame(PIECES["wall"](), 3.0, ctx, under).resize((1280, round(1280 * FH / FW)), Image.LANCZOS).save(path, optimize=True)
    print(f"{path.relative_to(ROOT)}: {path.stat().st_size // 1024} KB")


if __name__ == "__main__":
    main()
