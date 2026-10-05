#!/usr/bin/env bash
# Remove eva-desk. Keeps ~/.config/eva-desk and the fonts unless --purge.
set -euo pipefail
DATA="${XDG_DATA_HOME:-$HOME/.local/share}"
CONF="${XDG_CONFIG_HOME:-$HOME/.config}/eva-desk"
HYPR="${XDG_CONFIG_HOME:-$HOME/.config}/hypr/hyprland.lua"
PURGE=0
[ "${1:-}" = "--purge" ] && PURGE=1

"$HOME/.local/bin/eva-ctl" quit >/dev/null 2>&1 || true
if [ -f "$HYPR" ] && grep -qF "eva-desk/hypr/eva.lua" "$HYPR"; then
    cp "$HYPR" "$HYPR.bak-eva-uninstall-$(date +%Y%m%d-%H%M%S)"
    # --follow-symlinks: keep hyprland.lua a symlink if it is one (dotfiles)
    sed -i --follow-symlinks -e '/-- eva-desk (added by eva-desk\/install.sh/d' -e '/eva-desk\/hypr\/vibe\.lua/d' "$HYPR"
    echo ":: unhooked from $HYPR"
fi
rm -f "$HOME/.local/bin/eva-desk" "$HOME/.local/bin/eva-ctl" "$HOME/.local/bin/eva-extras"
rm -rf "$DATA/eva-desk"
if [ "$PURGE" = 1 ]; then
    rm -rf "$CONF" "${XDG_STATE_HOME:-$HOME/.local/state}/eva-desk" "$DATA/fonts/eva-desk"
    fc-cache -f >/dev/null 2>&1 || true
fi
echo ":: eva-desk removed"
