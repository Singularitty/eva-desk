#!/usr/bin/env bash
# eva-desk installer: an impact-frame / Persona desktop layer for Hyprland (Lua config).
#   ./install.sh             install a copy into ~/.local/share/eva-desk
#   ./install.sh --link      install by symlinking this checkout (edit here, `eva-ctl reload` to see it)
#   ./install.sh --no-hypr   do not touch hyprland.lua (add the dofile line yourself)
#   ./install.sh --no-fonts  skip the font download (Anton, Archivo Black, Cinzel, Special Elite, Doto, VT323;
#                            Shippori Mincho B1 and Share Tech Mono for the eva theme)
#   ./install.sh --theme eva       start with the eva theme (default: vibe); `eva-ctl theme` switches later
#   ./install.sh --extras all      also theme kitty, starship, neovim, firefox, discord, spotify, the shell
#                                  (or a comma list: --extras kitty,starship); see `eva-extras list`
#   ./install.sh --lock            set up hyprlock (SEELE council backgrounds per monitor + hyprlock.conf)
#   ./install.sh --gtk             build the GTK + icon themes (needs an Everforest GTK/icon theme installed)
set -euo pipefail

HERE="$(cd "$(dirname "$(readlink -f "$0")")" && pwd)"
DATA="${XDG_DATA_HOME:-$HOME/.local/share}"
PREFIX="$DATA/eva-desk"
BIN="$HOME/.local/bin"
CONF="${XDG_CONFIG_HOME:-$HOME/.config}/eva-desk"
FONTS="$DATA/fonts/eva-desk"
HYPR="${XDG_CONFIG_HOME:-$HOME/.config}/hypr/hyprland.lua"
MARK='-- eva-desk (added by eva-desk/install.sh; remove these two lines to unhook it)'
LINE='dofile(os.getenv("HOME") .. "/.local/share/eva-desk/hypr/eva.lua")'

LINK=0 HOOK=1 GET_FONTS=1 THEME="" EXTRAS="" LOCK=0 GTK=0
while [ $# -gt 0 ]; do
    case "$1" in
        --link) LINK=1 ;;
        --no-hypr) HOOK=0 ;;
        --no-fonts) GET_FONTS=0 ;;
        --theme) THEME="$2"; shift ;;
        --theme=*) THEME="${1#--theme=}" ;;
        --extras) EXTRAS="$2"; shift ;;
        --extras=*) EXTRAS="${1#--extras=}" ;;
        --lock) LOCK=1 ;;
        --gtk) GTK=1 ;;
        -h|--help) sed -n '2,12p' "$0"; exit 0 ;;
        *) echo "unknown option: $1" >&2; exit 2 ;;
    esac
    shift
done

say()  { printf '\033[1;31m::\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m!!\033[0m %s\n' "$*" >&2; }

# ---------------------------------------------------------------- 1. dependencies
say "checking dependencies"
if ! python3 - <<'EOF' 2>/dev/null
import sys
assert sys.version_info >= (3, 11)
from ctypes import CDLL
CDLL("libgtk4-layer-shell.so")
import gi, cairo
for ns, v in (("Gtk", "4.0"), ("Gtk4LayerShell", "1.0"), ("PangoCairo", "1.0"), ("GdkPixbuf", "2.0")):
    gi.require_version(ns, v)
from gi.repository import Gtk, Gtk4LayerShell, PangoCairo, GdkPixbuf
EOF
then
    warn "missing: Python >= 3.11 with PyGObject, pycairo, GTK 4 and gtk4-layer-shell"
    if command -v pacman >/dev/null; then
        warn "  sudo pacman -S --needed python-gobject python-cairo gtk4 gtk4-layer-shell"
    elif command -v apt >/dev/null; then
        warn "  sudo apt install python3-gi python3-gi-cairo gir1.2-gtk-4.0 gir1.2-gtk4layershell-1.0"
    elif command -v dnf >/dev/null; then
        warn "  sudo dnf install python3-gobject python3-cairo gtk4 gtk4-layer-shell"
    fi
    exit 1
fi
command -v hyprctl >/dev/null || warn "hyprctl not found: eva-desk only works inside Hyprland"
command -v awww >/dev/null || command -v swww >/dev/null || warn "no awww/swww: workspace wallpapers stay off"
command -v wpctl >/dev/null || warn "no wpctl: the bar shows no volume"

# ---------------------------------------------------------------- 2. files
# a vibe-desk install (the old name) moves over: config, state, and the dofile line in hyprland.lua
OLD_CONF="${XDG_CONFIG_HOME:-$HOME/.config}/vibe-desk"
OLD_STATE="${XDG_STATE_HOME:-$HOME/.local/state}/vibe-desk"
if [ -d "$OLD_CONF" ] && [ ! -e "$CONF" ]; then
    mv "$OLD_CONF" "$CONF"
    [ -f "$CONF/vibe.toml" ] && mv "$CONF/vibe.toml" "$CONF/eva.toml"
    ln -s "$CONF" "$OLD_CONF"
    say "moved $OLD_CONF to $CONF (vibe.toml is now eva.toml; a symlink keeps the old path working)"
fi
if [ -d "$OLD_STATE" ] && [ ! -e "${XDG_STATE_HOME:-$HOME/.local/state}/eva-desk" ]; then
    mv "$OLD_STATE" "${XDG_STATE_HOME:-$HOME/.local/state}/eva-desk"
fi
if [ -f "$HYPR" ] && grep -qF "vibe-desk/hypr/vibe.lua" "$HYPR"; then
    cp "$HYPR" "$HYPR.bak-eva-$(date +%Y%m%d-%H%M%S)"
    sed -i --follow-symlinks -e 's|vibe-desk/hypr/vibe\.lua|eva-desk/hypr/eva.lua|' -e 's|-- vibe-desk (added by vibe-desk/install.sh|-- eva-desk (added by eva-desk/install.sh|' "$HYPR"
    say "hyprland.lua: the dofile line now points at eva-desk"
fi
say "installing to $PREFIX"
mkdir -p "$PREFIX" "$BIN" "$CONF"
for d in eva_desk assets hypr bin tools extras gtk greeter; do
    rm -rf "${PREFIX:?}/$d"
    if [ "$LINK" = 1 ]; then ln -s "$HERE/$d" "$PREFIX/$d"; else cp -r "$HERE/$d" "$PREFIX/$d"; fi
done
chmod +x "$PREFIX/bin/"* "$PREFIX/tools/"*.py 2>/dev/null || true
ln -sf "$PREFIX/bin/eva-desk" "$BIN/eva-desk"
ln -sf "$PREFIX/bin/eva-ctl" "$BIN/eva-ctl"
ln -sf "$PREFIX/bin/eva-extras" "$BIN/eva-extras"
# the old names keep working for scripts that still call them
for old in vibe-desk vibe-ctl; do [ -L "$BIN/$old" ] || [ ! -e "$BIN/$old" ] && ln -sf "$PREFIX/bin/${old/vibe/eva}" "$BIN/$old"; done
[ -e "$DATA/vibe-desk" ] && [ ! -L "$DATA/vibe-desk" ] && mv "$DATA/vibe-desk" "$DATA/vibe-desk.old-$(date +%Y%m%d)"
[ -e "$DATA/vibe-desk" ] || ln -s "$PREFIX" "$DATA/vibe-desk"
if [ -f "$CONF/eva.toml" ]; then
    say "keeping your $CONF/eva.toml"
else
    cp "$HERE/config/eva.example.toml" "$CONF/eva.toml"
    say "wrote $CONF/eva.toml"
fi
if [ -n "$THEME" ]; then
    python3 - "$CONF/eva.toml" "$THEME" <<'PY'
import re, sys
path, theme = sys.argv[1], sys.argv[2]
text = open(path).read()
new, n = re.subn(r'(?ms)^(\[theme\][^\[]*?^\s*name\s*=\s*)"[^"]*"', lambda m: m.group(1) + f'"{theme}"', text, count=1)
if n == 0:
    new = f'[theme]\nname = "{theme}"\n\n' + text
open(path, "w").write(new)
PY
    say "theme: $THEME"
fi

# ---------------------------------------------------------------- 3. fonts
if [ "$GET_FONTS" = 1 ]; then
    mkdir -p "$FONTS"
    got=0
    while read -r file path; do
        [ -f "$FONTS/$file" ] && continue
        if curl -fsSL "https://github.com/google/fonts/raw/main/$path" -o "$FONTS/$file.part"; then
            mv "$FONTS/$file.part" "$FONTS/$file"; got=1
        else
            rm -f "$FONTS/$file.part"; warn "could not download $file"
        fi
    done <<'EOF'
Anton-Regular.ttf ofl/anton/Anton-Regular.ttf
ArchivoBlack-Regular.ttf ofl/archivoblack/ArchivoBlack-Regular.ttf
Cinzel.ttf ofl/cinzel/Cinzel%5Bwght%5D.ttf
SpecialElite-Regular.ttf apache/specialelite/SpecialElite-Regular.ttf
Doto.ttf ofl/doto/Doto%5BROND,wght%5D.ttf
VT323-Regular.ttf ofl/vt323/VT323-Regular.ttf
ShipporiMinchoB1-ExtraBold.ttf ofl/shipporiminchob1/ShipporiMinchoB1-ExtraBold.ttf
ShipporiMinchoB1-Bold.ttf ofl/shipporiminchob1/ShipporiMinchoB1-Bold.ttf
ShareTechMono-Regular.ttf ofl/sharetechmono/ShareTechMono-Regular.ttf
EOF
    [ "$got" = 1 ] && fc-cache -f "$FONTS" >/dev/null 2>&1 || true
    say "fonts in $FONTS (OFL / Apache, from Google Fonts)"
fi

# ---------------------------------------------------------------- 4. Hyprland
"$BIN/eva-desk" --write-lua >/dev/null
say "wrote $CONF/settings.lua"
if [ "$HOOK" = 1 ]; then
    if [ -f "$HYPR" ]; then
        if grep -qF "eva-desk/hypr/eva.lua" "$HYPR"; then
            say "hyprland.lua already loads eva-desk"
        else
            cp "$HYPR" "$HYPR.bak-eva-$(date +%Y%m%d-%H%M%S)"
            printf '\n%s\n%s\n' "$MARK" "$LINE" >> "$HYPR"
            say "hooked into $HYPR (backup next to it)"
        fi
    else
        warn "no $HYPR: eva-desk needs Hyprland's Lua config. Add at the end of it:"
        warn "  $LINE"
    fi
fi

# ---------------------------------------------------------------- 5. optional pieces
THEME_NOW="$(python3 -c "import sys; sys.path.insert(0, '$PREFIX'); from eva_desk import config; config.load(); print(config.theme_name())")"
if [ -n "$EXTRAS" ]; then
    say "extras ($THEME_NOW): ${EXTRAS//,/ }"
    "$BIN/eva-extras" install --theme "$THEME_NOW" ${EXTRAS//,/ }
fi
if [ "$LOCK" = 1 ]; then
    if command -v hyprlock >/dev/null && command -v hyprctl >/dev/null; then
        python3 "$PREFIX/tools/hyprlock_setup.py" --theme "$THEME_NOW" || warn "hyprlock setup failed"
    else
        warn "--lock needs hyprlock and a running Hyprland"
    fi
fi
if [ "$GTK" = 1 ]; then
    python3 "$PREFIX/gtk/make-gtk-theme.py" --theme "$THEME_NOW" || warn "GTK theme: needs ~/.themes/Everforest-Green-Dark-Medium (or pass its path)"
    python3 "$PREFIX/gtk/make-icon-theme.py" --theme "$THEME_NOW" || warn "icon theme: needs ~/.local/share/icons/Everforest-Dark"
fi

say "done. Hyprland reloads its config by itself and eva.lua starts the daemon."
say "settings: $CONF/eva.toml, then run: eva-ctl apply   (try: eva-ctl impact boxer)"
