#!/usr/bin/env python3
"""Build a eva-desk GTK theme from an installed Everforest GTK theme: recolour every colour by role
(ink / bone / claret / gold of the chosen theme), square the corners, add the hard offset shadows on popups.
   make-gtk-theme.py [--theme vibe|eva] [SOURCE_THEME_DIR]   -> ~/.themes/<theme's gtk_theme> (Vibe-Dark, Eva-Dark)"""
import colorsys, os, re, shutil, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from eva_desk import themes  # noqa: E402

args = sys.argv[1:]
THEME_NAME = "vibe"
if "--theme" in args:
    i = args.index("--theme")
    THEME_NAME = args[i + 1]
    del args[i:i + 2]
T = themes.get(THEME_NAME)
C = T["colors"]
SRC = Path(args[0] if args else "~/.themes/Everforest-Green-Dark-Medium").expanduser()
DST = Path("~/.themes/" + T["gtk_theme"]).expanduser()

ROLE = {  # Everforest -> theme role
    "1e2326": "ink_deep", "232a2e": "ink", "293136": "ink", "2d353b": "ink2", "0d0e11": "#000000",
    "434a4e": "ink4", "3a4146": "ink4", "262d32": "ink",
    "fffbef": "bone", "f2efdf": "bone", "f4f0e1": "bone", "bfbeb8": "bone2", "898c8a": "bone3",
    "a7c080": "bone",                                    # accent: bone plate, ink text
    "bfd1a2": "bone_hi", "b5ca94": "bone_hi", "b4c991": "bone_hi",   # lighter accent (hover)
    "8da101": "bone2", "81bea3": "slate",
    "f85552": "red", "f73d39": "led", "fa8781": "pink",
    "dfa000": "gold", "e69875": "coral", "3a94c5": "#7f9fb0",
    "df69ba": "rose", "d25de6": "rose", "b84acb": "rose",
}
EXACT = {k: (v[1:] if v.startswith("#") else C[v]) for k, v in ROLE.items()}

def rgb(role):
    return tuple(int(C[role][i:i + 2], 16) for i in (0, 2, 4))

def mix(h):
    r, g, b = (int(h[i:i + 2], 16) for i in (0, 2, 4))
    hue, sat, val = colorsys.rgb_to_hsv(r / 255, g / 255, b / 255)
    if sat < 0.12 or (sat < 0.32 and 90 <= hue * 360 < 260):   # neutral / slate -> ink/bone ramp
        t = val ** 1.8                   # darker lows: slate becomes ink, not mid-grey
        lo, hi = rgb("ink"), rgb("bone")
        return "%02x%02x%02x" % tuple(round(lo[i] + (hi[i] - lo[i]) * t) for i in range(3))
    deg = hue * 360
    if deg < 20 or deg >= 330: base = rgb("red")           # red
    elif deg < 70: base = rgb("gold")                      # orange / yellow -> accent 2
    elif deg < 170: base = rgb("bone")                     # green -> bone (the accent)
    elif deg < 260: base = (127, 159, 176)                 # blue / cyan
    else: base = rgb("rose")                               # purple -> rose
    k = 0.55 + 0.45 * val
    return "%02x%02x%02x" % tuple(min(255, round(c * k)) for c in base)

def hexmap(h):
    h = h.lower()
    return EXACT.get(h) or mix(h)

def recolour(text):
    text = re.sub(r"#([0-9a-fA-F]{6})\b", lambda m: "#" + hexmap(m.group(1)), text)
    def rgba(m):
        r, g, b = (int(x) for x in m.group(2, 3, 4))
        if (r, g, b) in ((0, 0, 0), (255, 255, 255)):    # shadows and plain white overlays stay
            return m.group(0)
        n = hexmap("%02x%02x%02x" % (r, g, b))
        return "%s(%d, %d, %d%s" % (m.group(1), int(n[0:2], 16), int(n[2:4], 16), int(n[4:6], 16), m.group(5))
    return re.sub(r"(rgba?)\((\d+), ?(\d+), ?(\d+)(, ?[\d.]+\)|\))", rgba, text)

def square(css):
    css = re.sub(r"border-radius:\s*[\d.]+(?:px)?(?:\s+[\d.]+(?:px)?){0,3}\s*;", lambda m: "border-radius: 0;" if "9999" not in m.group(0) else m.group(0), css)
    return css

EXTRA = f"""
/* ---- eva-desk ({T['title']}): hard offset shadows, bone outlines, flat everything ---- */
popover > contents, popover.background > contents, .popup .window-frame, menu, .menu, .context-menu {{
  border: 2px solid #{C['bone']}; box-shadow: 6px 6px 0 0 #{C['claret']};
}}
tooltip, tooltip.background {{ border: 2px solid #{C['bone']}; box-shadow: 4px 4px 0 0 #{C['claret']}; border-radius: 0; }}
dialog.background, messagedialog.background {{ border: 2px solid #{C['bone']}; }}
button.suggested-action, button.default {{ box-shadow: 3px 3px 0 0 #{C['claret']}; }}
entry:focus, entry:focus-within {{ border-color: #{C['gold']}; }}
*:selected, selection, *:selected:focus {{ background-color: #{C['bone']}; color: #{C['ink']}; }}
"""
if T.get("look") == "nerv":
    # the NERV look for GTK3 apps (Thunar first): flat ink surfaces with purple rules, title-card blocks for the
    # path bar and selections, MAGI monospace for the status bar and column headers
    EXTRA += f"""
/* ---- nerv: flat surfaces, purple rules, title-card blocks ---- */
window, .background {{ background-color: #{C['ink']}; color: #{C['bone']}; }}
headerbar, .titlebar, toolbar, .toolbar, .primary-toolbar, .inline-toolbar {{
  background-color: #{C['ink']}; background-image: none; border: none; border-bottom: 2px solid #{C['ink4']}; box-shadow: none; padding: 4px 8px;
}}
headerbar button, toolbar button, .toolbar button {{ background-color: transparent; background-image: none; border: none; border-radius: 0; color: #{C['bone2']}; box-shadow: none; padding: 4px 10px; }}
headerbar button:hover, toolbar button:hover, .toolbar button:hover {{ background-color: #{C['ink3']}; color: #{C['bone']}; }}
headerbar button:checked, toolbar button:checked, .toolbar button:checked {{ background-color: #{C['bone']}; color: #{C['ink']}; }}
.path-bar button, .path-bar.linked button, .linked.path-bar > button {{
  background-color: #{C['ink']}; background-image: none; color: #{C['bone']}; border: none; border-bottom: 3px solid #{C['claret']}; border-radius: 0;
  font-family: "{T['fonts']['display']}"; font-weight: 800; padding: 2px 12px; margin: 0 2px; box-shadow: none;
}}
.path-bar button:checked, .path-bar button:active {{ background-color: #{C['bone']}; color: #{C['ink']}; border-bottom-color: #{C['bone']}; }}
.path-bar button:hover {{ background-color: #{C['ink3']}; }}
.sidebar, placessidebar, scrolledwindow.sidebar, .sidebar treeview.view, placessidebar viewport {{
  background-color: #{C['ink_deep']}; color: #{C['bone2']}; border-right: 2px solid #{C['ink4']};
}}
.sidebar treeview.view:selected, placessidebar row:selected, placessidebar row:selected label, .sidebar row:selected {{
  background-color: #{C['bone']}; color: #{C['ink']}; font-weight: 800;
}}
.sidebar treeview.view:hover, placessidebar row:hover {{ background-color: #{C['ink3']}; color: #{C['bone']}; }}
treeview.view, iconview, .view {{ background-color: #{C['ink']}; color: #{C['bone']}; }}
treeview.view:selected, iconview:selected, .view:selected, treeview.view:selected:focus, iconview:selected:focus {{
  background-color: #{C['bone']}; color: #{C['ink']}; outline: none;
}}
treeview.view:hover {{ background-color: #{C['ink2']}; }}
treeview.view header button {{
  background-color: #{C['ink']}; background-image: none; color: #{C['bone3']}; border: none; border-bottom: 2px solid #{C['ink4']}; border-radius: 0;
  font-family: "{T['fonts']['meta']}"; font-size: 12px; padding: 4px 8px;
}}
treeview.view header button:hover {{ color: #{C['bone']}; border-bottom-color: #{C['claret']}; }}
statusbar, .statusbar, statusbar label {{ background-color: #{C['ink']}; color: #{C['bone2']}; font-family: "{T['fonts']['meta']}"; font-size: 12px; border-top: 2px solid #{C['ink4']}; }}
entry, entry.flat {{ background-color: #{C['ink_deep']}; color: #{C['bone']}; border: 1px solid #{C['ink5']}; border-radius: 0; box-shadow: none; font-family: "{T['fonts']['meta']}"; }}
entry:focus, entry:focus-within {{ border-color: #{C['gold']}; box-shadow: 3px 3px 0 0 #{C['claret']}; }}
scrollbar {{ background-color: #{C['ink_deep']}; border: none; }}
scrollbar slider {{ background-color: #{C['claret']}; border-radius: 0; min-width: 8px; min-height: 8px; border: none; }}
scrollbar slider:hover {{ background-color: #{C['claret_hi']}; }}
button {{ border-radius: 0; }}
button.suggested-action, button.default {{ background-color: #{C['bone']}; background-image: none; color: #{C['ink']}; border: none; font-weight: 800; }}
button.destructive-action {{ background-color: #{C['led']}; background-image: none; color: #{C['ink']}; border: none; font-weight: 800; }}
notebook > header {{ background-color: #{C['ink']}; border-bottom: 2px solid #{C['ink4']}; }}
notebook > header tab {{ background-color: transparent; color: #{C['bone3']}; border: none; border-bottom: 3px solid transparent; border-radius: 0; font-family: "{T['fonts']['display']}"; font-weight: 800; padding: 4px 14px; }}
notebook > header tab:checked {{ background-color: #{C['bone']}; color: #{C['ink']}; }}
notebook > header tab:hover {{ border-bottom-color: #{C['claret']}; color: #{C['bone']}; }}
infobar.warning, .warning {{ background-color: #{C['led']}; color: #{C['ink']}; }}
progressbar trough {{ background-color: #{C['ink3']}; border: none; border-radius: 0; }}
progressbar progress {{ background-color: #{C['gold']}; background-image: none; border: none; border-radius: 0; }}
menu, .menu, .context-menu, popover > contents {{ background-color: #{C['ink']}; }}
menuitem:hover, .menu menuitem:hover, modelbutton:hover {{ background-color: #{C['claret']}; color: #{C['bone']}; }}
/* the theme's figure watches over file views: Thunar's .standard-view (a style class) carries the
   picture and its child view goes transparent so it shows through; file choosers get the same under paned */
.standard-view, paned > scrolledwindow.frame, filechooser scrolledwindow {{
  background-color: #{C['ink']}; background-image: url("assets/vibe-figure.png"); background-repeat: no-repeat; background-position: right bottom;
}}
.standard-view > *, .standard-view .view, .standard-view treeview.view, filechooser scrolledwindow .view {{
  background-color: transparent; background-image: none;
}}
.standard-view treeview.view:selected, .standard-view .view:selected {{ background-color: #{C['bone']}; color: #{C['ink']}; }}
.standard-view treeview.view header button {{ background-color: #{C['ink']}; }}
"""

def figure_watermark(out, height=440):
    """The theme's stage figure as a dim silhouette with its echo, for the file-view background."""
    from PIL import Image
    import numpy as np
    src = Path(__file__).resolve().parent.parent / "assets" / "themes" / THEME_NAME / "figures" / "boxer.png"
    if not src.exists():
        return
    fig = Image.open(src).convert("RGBA")
    fig = fig.resize((round(fig.width * height / fig.height), height), Image.LANCZOS)
    a = np.asarray(fig)[..., 3].astype(float) / 255
    echo = 10
    w, h = fig.width + 2 * echo + 24, fig.height + 12
    out_img = np.zeros((h, w, 4))
    ink3 = tuple(int(C["ink3"][i:i + 2], 16) / 255 for i in (0, 2, 4))
    ec = tuple(int(C["claret"][i:i + 2], 16) / 255 for i in (0, 2, 4))
    def paint(dx, col, alpha):
        for c in range(3):
            out_img[:fig.height, dx:dx + fig.width, c] = np.where(a > 0.01, col[c], out_img[:fig.height, dx:dx + fig.width, c])
        out_img[:fig.height, dx:dx + fig.width, 3] = np.maximum(out_img[:fig.height, dx:dx + fig.width, 3], a * alpha)
    paint(2 * echo, ec, 0.22)
    paint(echo, ec, 0.45)
    paint(0, ink3, 1.0)
    out.parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray((out_img * 255 + 0.5).astype(np.uint8), "RGBA").save(out, optimize=True)
    print("figure watermark:", out)


def main():
    if not SRC.is_dir():
        sys.exit(f"source theme not found: {SRC}")
    if DST.exists():
        shutil.rmtree(DST)
    shutil.copytree(SRC, DST, symlinks=True)
    for p in DST.rglob("*"):
        if p.is_symlink() or not p.is_file():
            continue
        if p.suffix in (".css", ".svg", ".theme", ".rc", ".xml", ".scss") or p.name in ("gtkrc", "index.theme"):
            t = p.read_text(errors="ignore")
            t = recolour(t)
            if p.suffix == ".css":
                t = re.sub(r"\n[ \t]*border-spacing:[^;]*;", "", t) if p.parent.name == "gtk-3.0" else t   # not a GTK3 property
                t = square(t)
                if p.name.startswith("gtk") and p.parent.name in ("gtk-3.0", "gtk-4.0"):
                    t += EXTRA
            p.write_text(t)
        elif p.suffix == ".png":
            try:
                from PIL import Image
                im = Image.open(p).convert("RGBA"); px = im.load()
                for y in range(im.height):
                    for x in range(im.width):
                        r, g, b, a = px[x, y]
                        if a and (r, g, b) not in ((0, 0, 0), (255, 255, 255)):
                            n = hexmap("%02x%02x%02x" % (r, g, b)); px[x, y] = (int(n[0:2], 16), int(n[2:4], 16), int(n[4:6], 16), a)
                im.save(p)
            except Exception as e:
                print("png skipped", p.name, e)
    if T.get("look") == "nerv":
        figure_watermark(DST / "gtk-3.0" / "assets" / "vibe-figure.png")
    idx = DST / "index.theme"
    t = idx.read_text().replace(SRC.name, T["gtk_theme"])
    idx.write_text(t)
    for d in DST.parent.glob(SRC.name + "-*dpi"):   # hdpi variants are not needed
        pass
    print("theme written:", DST)

main()
