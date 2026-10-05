#!/usr/bin/env bash
# Give the greetd/ReGreet login screen the eva-desk look. Needs root: sudo ./install-greeter.sh
# Backs up what it replaces as *.bak-eva-<date>. Undo: copy the backups back.
set -euo pipefail
[ "$(id -u)" = 0 ] || { echo "run with sudo" >&2; exit 1; }
HERE="$(cd "$(dirname "$(readlink -f "$0")")" && pwd)"
OWNER="${SUDO_USER:-$(logname 2>/dev/null || echo "$USER")}"
THEME="${1:-vibe}"                 # ./install-greeter.sh eva -> login-eva.png + regreet-eva.css
BG="$HERE/login.png"; CSS="$HERE/regreet.css"; INK="0c0608"
if [ "$THEME" = eva ]; then BG="$HERE/login-eva.png"; CSS="$HERE/regreet-eva.css"; INK="050309"; fi
FONTS="$(getent passwd "$OWNER" | cut -d: -f6)/.local/share/fonts/eva-desk"
D=$(date +%Y%m%d-%H%M%S)

install -d /usr/share/backgrounds/vibe /usr/local/share/fonts/vibe
install -m644 "$BG" /usr/share/backgrounds/vibe/login.png
for f in Anton-Regular.ttf Doto.ttf SpecialElite-Regular.ttf ShipporiMinchoB1-ExtraBold.ttf ShareTechMono-Regular.ttf; do   # the greeter user cannot read ~/.local
    [ -f "$FONTS/$f" ] && install -m644 "$FONTS/$f" /usr/local/share/fonts/vibe/
done
fc-cache -f /usr/local/share/fonts/vibe

[ -f /etc/greetd/regreet.css ] && cp -a /etc/greetd/regreet.css "/etc/greetd/regreet.css.bak-eva-$D"
install -m644 "$CSS" /etc/greetd/regreet.css
[ -f /etc/greetd/regreet.toml ] && cp -a /etc/greetd/regreet.toml "/etc/greetd/regreet.toml.bak-eva-$D"
install -m644 "$HERE/regreet.toml" /etc/greetd/regreet.toml
# the compositor's own background while the greeter loads: the theme's ink instead of Everforest
sed -i -E "s/background_color = \"rgb\([0-9a-f]{6}\)\"/background_color = \"rgb($INK)\"/" /etc/greetd/hyprland.lua
echo "done: log out (or reboot) to see it"
