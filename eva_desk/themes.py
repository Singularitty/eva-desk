"""Themes: every colour, font and border style the desk uses, by role.

A theme is a dict with the same keys as THEMES["vibe"]; `[theme] name = "..."` in eva.toml picks one.
Assets (figures, herald rig, wallpapers) can be overridden per theme under assets/themes/<name>/.
"""
import copy
import re

THEMES = {}

# ---------------------------------------------------------------- vibe: wine, bone and gold (Persona 5 / fight card)
THEMES["vibe"] = {
    "title": "Fight Card",
    "look": "card",                # card: skewed tags, speed lines, staircase launcher
    "colors": {
        "ink": "0c0608", "ink_deep": "070304", "ink2": "140a0d", "ink3": "1c1012", "ink4": "2e1a1f", "ink5": "4a2a31",
        "wine": "3b0a14", "wine_d": "2a0710",
        "claret": "8e1b33", "claret_hi": "c4304b",        # accent 1: hard shadows, underlines, badges
        "red": "e5475f",                                   # accent 1 as text on ink
        "led": "ff4d3a", "coral": "e86a4a",                # urgent / hot
        "gold": "c9a24a", "gold_hi": "e9d29a",             # accent 2: highlights, playing, the star
        "bone": "efe4cf", "bone2": "b9ab92", "bone3": "8a7a68", "paper": "f4ede0",
        "dim": "6a4a4e", "ember": "ff7a3a",
        "echo": "8e1b33",                                  # the figures' offset trail (X2 treatment)
        # extra tones used by the generated GTK theme, eww partials and dunst (same keys in every theme)
        "rose": "b0708a", "slate": "7fa89a", "bone_hi": "f7efdd", "gold_glow": "ffd27a",
        "iron_d": "5c0f22", "iron": "3a1a20", "well": "1f0a10", "sand": "a8977d",
        "ember_hi": "ff825a", "ember_lo": "ff5a3a", "pink": "ee7a88",
        # terminal / editor tones (kitty, nvim): the ANSI colours that are not desk roles, and diff backgrounds
        "green": "8fa36a", "green_hi": "a9bd84", "blue": "7f9fb0", "blue_hi": "a0bccb", "cyan_hi": "9cc2b4",
        "rose_hi": "c98ba3", "diff_add": "1a2412", "diff_change": "2a2010", "diff_text": "4a3a14",
    },
    "fonts": {
        "display": "Anton", "display_weight": 400, "display_italic": True,
        "title": "Archivo Black", "digits": "Doto", "body": "Rubik", "meta": "Special Elite", "accent": "Cinzel",
    },
    # the launcher (board AC2 "PAPER"): paper room, ink slab, red halftone
    "launcher": {
        "bg": "paper", "slab": "ink", "dots": ("claret", 0.16), "s1": "claret", "s2": "gold",
        "q": [("bone", "ink", "display"), ("claret", "bone", "accent"), ("gold", "ink", "meta"), ("bone", "ink", "title")],
        "cur": "bone", "top": ("bone", "ink"), "arrow": "claret",
        "items": ["bone", "gold", "sand", "dim"],
        "card": ("ink", "led", "bone", "bone2"), "cshadow": "claret",
        "btn": [("ink", "bone"), ("claret", "bone"), ("gold", "ink")],
    },
    # Hyprland border + shadow styles (hypr/eva.lua), colours by role; "#rrggbbaa" adds alpha
    "hypr": {
        "inactive_border": "wine_d/aa",
        "card": {"size": 4, "colors": ["bone", "bone2", "bone", "bone2", "bone"],
                 "shadow": {"sharp": True, "range": 2, "power": 1, "offset": [14, 14], "color": "claret", "inactive": "claret/80"}},
        "halo": {"size": 4, "colors": ["gold", "coral", "gold_glow", "claret", "gold"],
                 "shadow": {"sharp": False, "range": 40, "power": 2, "offset": [0, 0], "color": "coral/8c", "inactive": "coral/30"}},
        "iron": {"size": 6, "colors": ["iron", "claret", "ink3", "iron_d", "iron"],
                 "shadow": {"sharp": False, "range": 50, "power": 2, "offset": [0, 0], "color": "claret/73", "inactive": "claret/26"}},
    },
    "gtk_theme": "Vibe-Dark",
    "halftone": "bone",
    "sun": ["bone_hi", "gold_hi", "gold_glow", "coral"],   # the herald's disc: core -> rim            # the wallpapers' baked dot screen
}

# ---------------------------------------------------------------- eva: Unit-01 purple, acid green, NERV orange
THEMES["eva"] = {
    "title": "Evangelion",
    "look": "nerv",                # nerv: title-card blocks, MAGI readouts, AT-field hexes, hazard stripes
    "colors": {
        "ink": "0a0612", "ink_deep": "050309", "ink2": "130b20", "ink3": "1b1030", "ink4": "2a1a48", "ink5": "44307a",
        "wine": "2b1450", "wine_d": "1c0d36",
        "claret": "6a2fb8", "claret_hi": "8d4ff0",        # Unit-01 purple: shadows, underlines, badges
        "red": "a981ff",                                   # purple as text on ink
        "led": "ff5a1f", "coral": "ff8a45",                # NERV orange: urgent / hot
        "gold": "7dff3f", "gold_hi": "c8ff9a",             # acid green: highlights, playing, the star
        "bone": "ebe6f7", "bone2": "b7aed0", "bone3": "857b9e", "paper": "efeaf8",
        "dim": "5a4b7a", "ember": "9dff5a",
        "echo": "5ee82a",                                  # acid green trail behind the black Eva
        "rose": "c77dff", "slate": "6fbf9f", "bone_hi": "f6f2ff", "gold_glow": "b4ff7a",
        "iron_d": "3a1d6e", "iron": "22123f", "well": "120a22", "sand": "9a90b8",
        "ember_hi": "c4ff8a", "ember_lo": "7dff3f", "pink": "c99cff",
        "green": "6fd63a", "green_hi": "9dff5a", "blue": "8a8fe8", "blue_hi": "adb3ff", "cyan_hi": "9ad9c0",
        "rose_hi": "dcaaff", "diff_add": "143a16", "diff_change": "2b1a4a", "diff_text": "4a3080",
    },
    "fonts": {
        "display": "Shippori Mincho B1", "display_weight": 800, "display_italic": False,
        "title": "Shippori Mincho B1", "digits": "Doto", "body": "Rubik", "meta": "Share Tech Mono",
        "accent": "Shippori Mincho B1",
    },
    # the launcher as an episode title card: black room, the query set as the title, cast list, monolith card
    "launcher": {
        "bg": "ink_deep", "slab": "bone", "dots": ("claret", 0.22), "s1": "claret", "s2": "gold",
        "q": [("ink", "bone", "display"), ("claret", "bone", "accent"), ("gold", "ink", "meta"), ("ink", "bone", "title")],
        "cur": "gold", "top": ("bone", "ink"), "arrow": "gold",
        "items": ["bone", "bone2", "bone3", "dim"],
        "card": ("ink", "gold", "bone", "bone2"), "cshadow": "claret",
        "btn": [("bone", "ink"), ("claret", "bone"), ("gold", "ink")],
    },
    "hypr": {
        "inactive_border": "wine_d/aa",
        "card": {"size": 4, "colors": ["bone", "bone2", "bone", "bone2", "bone"],
                 "shadow": {"sharp": True, "range": 2, "power": 1, "offset": [14, 14], "color": "claret", "inactive": "claret/80"}},
        "halo": {"size": 4, "colors": ["gold", "gold_hi", "gold", "claret", "gold"],
                 "shadow": {"sharp": False, "range": 40, "power": 2, "offset": [0, 0], "color": "gold/8c", "inactive": "gold/30"}},
        "iron": {"size": 6, "colors": ["iron", "claret", "ink3", "iron_d", "iron"],
                 "shadow": {"sharp": False, "range": 50, "power": 2, "offset": [0, 0], "color": "claret/73", "inactive": "claret/26"}},
    },
    "gtk_theme": "Eva-Dark",
    "halftone": "bone",
    "sun": [],                                             # no disc: the Eva just rises behind the window
}

DEFAULT = "eva"


def get(name):
    """The theme dict (a deep copy), falling back to the default for unknown names."""
    return copy.deepcopy(THEMES.get(name) or THEMES[DEFAULT])


def color(theme, role):
    """'role' or 'role/aa' -> 'rrggbb' or 'rrggbbaa'; a literal hex passes through."""
    role, _, alpha = role.partition("/")
    hx = theme["colors"].get(role, role).lstrip("#")
    return hx + alpha


def hypr_styles(theme):
    """The border styles as Lua-ready values: {name: {size, colors: ['rgb(..)'...], shadow: {...}}}."""
    def css(role):
        hx = color(theme, role)
        return f"rgba({hx})" if len(hx) == 8 else f"rgb({hx})"
    out = {}
    for name in ("card", "halo", "iron"):
        st = theme["hypr"][name]
        sh = st["shadow"]
        out[name] = {"size": st["size"], "colors": [css(c) for c in st["colors"]],
                     "shadow": {"sharp": sh["sharp"], "range": sh["range"], "power": sh["power"], "offset": list(sh["offset"]),
                                "color": css(sh["color"]), "inactive": css(sh["inactive"])}}
    return out, css(theme["hypr"]["inactive_border"])


# scss variable -> role, for the eww widgets (css/_vibe-palette.scss)
EWW_VARS = [
    ("ink", "ink"), ("ink-deep", "ink_deep"), ("ink2", "ink2"), ("ink3", "ink3"), ("ink4", "ink4"), ("ink5", "ink5"),
    ("wine", "wine"), ("claret", "claret"), ("claret-hi", "claret_hi"), ("red", "red"), ("led", "led"), ("coral", "coral"),
    ("gold", "gold"), ("gold-hi", "gold_hi"), ("bone", "bone"), ("bone2", "bone2"), ("bone3", "bone3"), ("dim", "dim"),
]


def eww_scss(theme):
    f = theme["fonts"]
    lines = ["// generated by eva-desk from the active theme (eva.toml [theme]); do not edit, run `eva-ctl apply`",
             f"// theme: {theme['title']}"]
    for var, role in EWW_VARS:
        lines.append(f"$v-{var}: #{theme['colors'][role]};")
    lines += [
        f"$v-display: '{f['display']}', 'Anton', sans-serif;",
        f"$v-title: '{f['title']}', 'Archivo Black', sans-serif;",
        f"$v-digits: '{f['digits']}', monospace;",
        f"$v-body: '{f['body']}', sans-serif;",
        f"$v-type: '{f['meta']}', monospace;",
        "$v-icons: 'Material Symbols Rounded';",
        f"$v-display-weight: {f['display_weight']};",
        f"$v-display-style: {'italic' if f['display_italic'] else 'normal'};",
        f"$v-look: {theme.get('look', 'card')};",
    ]
    return "\n".join(lines) + "\n"


def retheme(text, src, dst):
    """Rewrite every colour of theme `src` found in `text` (as #rrggbb, rrggbb in rgb()/rgba(), or a bare
    6-hex Hyprland token) into the same role of theme `dst`. Files with hand-written theme colours (dunst,
    greeter css, eww partials) follow a theme switch this way."""
    if src is dst or src["colors"] == dst["colors"]:
        return text
    table = {}
    for role, hx in src["colors"].items():
        table.setdefault(hx.lower(), dst["colors"][role])
    fonts = {src["fonts"][k]: dst["fonts"][k] for k in ("display", "title", "meta") if src["fonts"][k] != dst["fonts"][k]}

    def swap(m):
        hx = m.group(1).lower()
        return m.group(0)[:m.start(1) - m.start(0)] + table.get(hx, m.group(1)) + m.group(0)[m.end(1) - m.start(0):]
    text = re.sub(r"(?<![0-9a-fA-F])#?([0-9a-fA-F]{6})(?![0-9a-fA-F])", swap, text)
    text = re.sub(r"(rgba\()([0-9a-fA-F]{6})(?=[0-9a-fA-F]{2}\))", lambda m: m.group(1) + table.get(m.group(2).lower(), m.group(2)), text)
    for a, b in fonts.items():
        text = text.replace(a, b)
    if src.get("gtk_theme") and dst.get("gtk_theme"):
        text = text.replace(src["gtk_theme"], dst["gtk_theme"])     # gtk settings.ini: theme + icon theme names
    return text
