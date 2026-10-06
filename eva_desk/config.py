"""Configuration: ~/.config/eva-desk/eva.toml merged over built-in defaults."""
import copy
import os
import tomllib
from pathlib import Path

from . import themes

HOME = Path.home()
CONFIG_DIR = Path(os.environ.get("XDG_CONFIG_HOME", HOME / ".config")) / "eva-desk"
STATE_DIR = Path(os.environ.get("XDG_STATE_HOME", HOME / ".local/state")) / "eva-desk"
ROOT = Path(__file__).resolve().parent.parent          # install root: holds assets/ and hypr/
ASSETS = ROOT / "assets"

DEFAULTS = {
    "theme": {
        "name": "eva",            # eva (Unit-01 purple / acid green, the NERV look) or vibe (wine / bone / gold fight card)
        "eww_palette": "",        # write the theme's scss variables here on `eva-ctl apply` (e.g. ~/.config/eww/css/_vibe-palette.scss)
        "retheme_files": [],      # files with hand-written theme colours (dunst, greeter css): rewritten on a theme switch
        "after_apply": [],        # commands after apply, e.g. ["dunstctl reload", "eww reload"]
        "swap_files": [],         # files with a per-theme version beside them: ~/.config/starship.toml <- starship.eva.toml
        "gsettings": True,        # also set org.gnome.desktop.interface gtk-theme / icon-theme to the theme's GTK theme
    },
    "themes": {},                 # per-theme overrides of any section: [themes.eva.wallpapers] pool = [...]
    "general": {
        # monitors that get the bar, scenes and wallpapers: Hyprland names or description substrings;
        # empty = the largest monitor
        "main_monitors": [],
    },
    "figures": {
        "figure": "all",           # "all" (workspaces 1..workspaces), a workspace id, a list, or 0 = off
        "workspaces": 10,         # how many numbered workspaces "all" covers
        "herald": True,           # herald plays when a window is maximised
        "stage": "auto",    # share of the monitor width kept free for the figure: "auto" = 0.30 on ultrawides,
                                  # 0.24 on 16:9 / 16:10, 0.20 on squarer screens; or a number
        "herald_ms": 360,         # length of the arm sweep
        "figure_entry_ms": 450,    # length of the figure's entrance
        "ignore_classes": ["^steam_app_", "^gamescope$"],
    },
    "wallpapers": {
        "enabled": True,
        "daemon": "auto",         # auto | awww | swww | none
        "transition": "fade",
        "duration": 0.9,
        "shuffle_minutes": 20,
        "pool": [],               # your own images (paths); nothing is bundled
        "workspaces": {},
        "named": {},              # named workspace -> image or "#rrggbb"
        "static": {},             # other monitors: description substring -> image
    },
    "bar": {
        "enabled": True,
        "height": 56,
        "opacity": 0.8,           # the bar's ink ground over the wallpaper (0 = see-through, 1 = solid); Hyprland blurs behind it
        "motif": "both",          # dots (halftone screen) | hazard (the stripe along the bottom) | both | none
        "workspaces": 10,
        "hide_on_workspaces": [],
        "resources": ["cpu", "mem", "net"],   # resource tags left of the date; [] hides them
        "resource_seconds": 2,
        "music": True,                    # now-playing tag (needs playerctl); hidden while nothing plays
        "music_players": "spotify,%any",  # playerctl -p order
        "tray": True,                     # app tray icons (StatusNotifierItem): click, middle click, right-click menu
        # extra tags between VOL and the star: {name, label, action, right_action, active_file};
        # the tag turns LED red while active_file exists ($VARS and ~ are expanded)
        "buttons": [],
        "actions": {"clock": "", "date": "", "volume": "", "star": "", "title": "", "cpu": "", "mem": "", "net": "",
                    "music": ""},
    },
    "shot": {
        "enabled": True,          # the themed screenshot tool (needs grim; wl-copy for the clipboard)
        "folder": "",             # where shots are saved; empty = <Pictures>/Screenshots
        "editor": "satty --filename {}",   # opened when you hold Shift as you finish; empty = never
    },
    "hooks": {},                  # named workspace -> {enter = "cmd", leave = "cmd"}
    "overlays": {                 # the nerv look's extra surfaces (all off in the card look unless enabled)
        "eyecatch": True,         # the episode card cut on a workspace switch you make
        "eyecatch_style": "soft", # soft: translucent card that fades (240 ms); cut: black card, inverted frame, lift (320 ms)
        "eyecatch_ms": 0,         # 0 = the style's own length
        "alarm_band": True,       # the EMERGENCY band under the bar for critical notifications
        "alarm_seconds": 120,     # the band goes away by itself after this
        "alttab": True,           # Alt+Tab as the cast strip (re-points the bind below)
        "power": True,            # the Third Impact power menu (re-points the bind below)
        "names": {},              # workspace id -> name shown on the eye-catch: {"3" = "PROJECTS"}
        "spawn_pulse": True,      # one hexagon pulse from the centre of a window that just opened
        "pulse_ms": 260,
        "launcher_cut": True,     # the two-frame 起動 cut when the launcher opens
        "minute_flip": True,      # the clock badge's digits slide at the minute
        "berserk": 90,            # CPU or RAM at or above this % for berserk_seconds turns the stage orange (0 = never)
        "berserk_seconds": 30,
    },
    "power": {                    # what the power menu runs
        "lock": "hyprlock",
        "sleep": "systemctl suspend",
        "logout": "",             # empty = Hyprland's own exit
        "reboot": "systemctl reboot",
        "shutdown": "systemctl poweroff",
    },
    "launcher": {
        "enabled": True,
        "search_url": "https://duckduckgo.com/?q={}",
    },
    "hyprland": {
        "maximize_bind": ["SUPER + RETURN"],   # one key or a list; fills the screen under the bar
        "launcher_bind": "SUPER + Space",
        "side_bind": "SUPER + D",                    # dock the focused window into the figure's space
        "screenshot_bind": "Print",                  # re-pointed at the themed screenshot tool
        "alttab_bind": "ALT + Tab",                  # re-pointed at the cast strip when overlays.alttab is on
        "power_bind": "SUPER + M",                   # re-pointed at the power menu when overlays.power is on
        "style": "card",          # card | halo | iron: border + shadow style for ordinary workspaces
        "rounding": 0,
        "gaps_in": 4,
        "gaps_out": 8,
        "border_speed": 100,      # tenths of a second per turn of the border gradient (max 100 = 10 s); 0 = still
    },
}


def _merge(base, over):
    for k, v in over.items():
        if isinstance(v, dict) and isinstance(base.get(k), dict):
            _merge(base[k], v)
        else:
            base[k] = v
    return base


REMOVED_KEYS = {("hyprland", "figure_toggle_bind")}   # old eva.toml keys: popped on load(), noted once each

_theme = {"name": themes.DEFAULT, "data": themes.get(themes.DEFAULT), "listeners": []}


def current_theme():
    return _theme["data"]


def theme_name():
    return _theme["name"]


def on_theme(fn):
    """Call fn(theme) whenever load() activates a theme (draw.py rebinds its palette this way)."""
    _theme["listeners"].append(fn)


def activate_theme(name):
    _theme["name"], _theme["data"] = (name if name in themes.THEMES else themes.DEFAULT), themes.get(name)
    for fn in _theme["listeners"]:
        fn(_theme["data"])
    return _theme["data"]


def load(path=None):
    cfg = copy.deepcopy(DEFAULTS)
    p = Path(path) if path else CONFIG_DIR / "eva.toml"
    if p.exists():
        with open(p, "rb") as f:
            _merge(cfg, tomllib.load(f))
    for section, key in REMOVED_KEYS:
        if key in cfg.get(section, {}):
            cfg[section].pop(key, None)
            print(f"eva-desk: [{section}] {key} is gone (the figure has no toggle key any more; "
                  f"use `eva-ctl figure`)", flush=True)
    name = str(cfg["theme"].get("name") or themes.DEFAULT)
    over = cfg.get("themes", {}).get(name)
    if isinstance(over, dict):                 # [themes.<name>.<section>] wins while that theme is active
        _merge(cfg, copy.deepcopy(over))
    activate_theme(name)
    return cfg


def theme_dir():
    """assets/themes/<name>, where a theme keeps its own figures, herald rig and wallpapers."""
    return ASSETS / "themes" / _theme["name"]


def asset_path(rel):
    """A bundled asset by relative name ("figures/unit01.png"): the active theme's copy if it has one."""
    p = theme_dir() / rel
    return p if p.exists() else ASSETS / rel


def asset(name, folder="wallpapers"):
    """A bare name means a bundled asset (the active theme's first); anything with a slash or ~ is a path."""
    if name.startswith("#"):
        return name
    if "/" in name or name.startswith("~"):
        return str(Path(name).expanduser())
    for base in (theme_dir(), ASSETS):
        for ext in (".webp", ".png", ".jpg"):
            p = base / folder / (name + ext)
            if p.exists():
                return str(p)
    return str(ASSETS / folder / name)


def stage_share(cfg, width=None, height=None, key="stage"):
    """The stage's share of the monitor width: a number from the config, or "auto" by aspect ratio."""
    v = cfg["figures"].get(key, "auto")
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        return float(v)
    aspect = (width / height) if width and height else 2.39
    return 0.30 if aspect >= 2.0 else 0.24 if aspect >= 1.6 else 0.20


def figure_workspaces(cfg):
    b, n = cfg["figures"]["figure"], int(cfg["figures"].get("workspaces", 10))
    if b == "all":
        return list(range(1, n + 1))
    if isinstance(b, bool) or not b:
        return []
    if isinstance(b, int):
        return [b]
    return [int(x) for x in b if int(x) > 0]


def figure_enabled():
    """The eva-ctl figure on/off state, shared with hypr/eva.lua through a state file."""
    try:
        return (STATE_DIR / "figure").read_text().strip() != "off"
    except OSError:
        return True


def set_figure_enabled(on):
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    (STATE_DIR / "figure").write_text("on\n" if on else "off\n")


def _keys(v):
    return [v] if isinstance(v, str) else [k for k in (v or []) if k]


def write_lua_settings(cfg, monitor_width=None, monitor_height=None):
    """settings.lua: the part of the config Hyprland itself needs (read by hypr/eva.lua)."""
    f, h = cfg["figures"], cfg["hyprland"]
    width = monitor_width or 3440
    height = monitor_height or (round(width / 2.39) if monitor_width else 1440)
    stage_px = int(round(width * stage_share(cfg, width, height)))

    def lua_str(s):
        return '"' + str(s).replace("\\", "\\\\").replace('"', '\\"') + '"'
    theme = current_theme()
    styles, inactive = themes.hypr_styles(theme)
    style_lines = []
    for name, st in styles.items():
        sh = st["shadow"]
        style_lines.append(
            f"        {name} = {{ size = {st['size']}, colors = {{ " + ", ".join(lua_str(c) for c in st["colors"]) + " },"
            f" shadow = {{ enabled = true, sharp = {'true' if sh['sharp'] else 'false'}, range = {sh['range']},"
            f" render_power = {sh['power']}, offset = {{ {sh['offset'][0]}, {sh['offset'][1]} }},"
            f" color = {lua_str(sh['color'])}, color_inactive = {lua_str(sh['inactive'])} }} }},")
    lines = [
        "-- generated by eva-desk from eva.toml; edit that file and run `eva-ctl apply`",
        "return {",
        f"    theme = {lua_str(theme_name())},",
        f"    gtk_theme = {lua_str(theme['gtk_theme']) if theme.get('gtk_theme') else 'nil'},",
        "    styles = {",
        *style_lines,
        "    },",
        f"    inactive_border = {lua_str(inactive)},",
        "    figure_workspaces = {" + ", ".join(str(w) for w in figure_workspaces(cfg)) + "},",
        "    main_monitors = {" + ", ".join(lua_str(m) for m in cfg["general"]["main_monitors"]) + "},",
        f"    herald = {'true' if f['herald'] else 'false'},",
        f"    stage_px = {stage_px},",
        f"    style = {lua_str(h['style'])},",
        f"    rounding = {int(h['rounding'])},",
        f"    gaps_in = {int(h['gaps_in'])},",
        f"    gaps_out = {int(h['gaps_out'])},",
        f"    border_speed = {max(0, min(100, int(h['border_speed'])))},",   # Hyprland caps animation speed at 100
        "    maximize_binds = {" + ", ".join(lua_str(k) for k in _keys(h["maximize_bind"])) + "},",
        f"    launcher_bind = {lua_str(h['launcher_bind']) if cfg['launcher']['enabled'] and h['launcher_bind'] else 'nil'},",
        f"    side_bind = {lua_str(h['side_bind']) if h.get('side_bind') else 'nil'},",
        f"    screenshot_bind = {lua_str(h['screenshot_bind']) if cfg['shot']['enabled'] and h.get('screenshot_bind') else 'nil'},",
        f"    alttab_bind = {lua_str(h['alttab_bind']) if cfg['overlays'].get('alttab') and h.get('alttab_bind') else 'nil'},",
        f"    power_bind = {lua_str(h['power_bind']) if cfg['overlays'].get('power') and h.get('power_bind') else 'nil'},",
        f"    bar_height = {int(cfg['bar']['height']) if cfg['bar']['enabled'] else 0},",
        "}",
    ]
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    out = CONFIG_DIR / "settings.lua"
    out.write_text("\n".join(lines) + "\n")
    return out
