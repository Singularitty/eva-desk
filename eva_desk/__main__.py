"""eva-desk entry point.

  eva-desk                 run the daemon (one instance per session)
  eva-desk --write-lua     regenerate ~/.config/eva-desk/settings.lua for hypr/eva.lua
  eva-desk --render DIR    render every scene, flash, the bar and the launcher to PNGs (no windows)
"""
import argparse
import ctypes
import json
import os
import subprocess
import sys
import time

from . import config


def _monitor_size():
    """(width, height) of the main monitor in logical pixels, or (None, None) outside Hyprland."""
    try:
        mons = json.loads(subprocess.run(["hyprctl", "-j", "monitors"], capture_output=True, text=True, timeout=2).stdout)
        cfg = config.load()
        wanted = cfg["general"]["main_monitors"]
        cands = [m for m in mons if not wanted or any(w == m["name"] or w in m.get("description", "") for w in wanted)]
        m = max(cands or mons, key=lambda m: m["width"] * m["height"])
        scale = float(m.get("scale", 1) or 1)
        w, h = int(m["width"] / scale), int(m["height"] / scale)
        if int(m.get("transform", 0)) % 2 == 1:
            w, h = h, w
        return w, h
    except (OSError, ValueError, subprocess.SubprocessError, KeyError):
        return None, None


def _set_process_name(name=b"eva-desk"):
    try:
        ctypes.CDLL(None).prctl(15, name, 0, 0, 0)          # PR_SET_NAME, so `pgrep -x eva-desk` works
    except (OSError, AttributeError):
        pass


def _wait_for_display(tries=60):
    """vibe.lua starts us while Hyprland is still reading its config at login: WAYLAND_DISPLAY is empty
    then and the socket does not exist yet. Wait for this Hyprland instance's socket and use it."""
    run = os.environ.get("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}")
    sig = os.environ.get("HYPRLAND_INSTANCE_SIGNATURE")
    for _ in range(tries):
        name = os.environ.get("WAYLAND_DISPLAY")
        if not name and sig:
            try:
                out = subprocess.run(["hyprctl", "instances", "-j"], capture_output=True, text=True, timeout=2).stdout
                name = next((i.get("wl_socket") for i in json.loads(out) if i.get("instance") == sig), None)
            except (OSError, ValueError, subprocess.SubprocessError):
                name = None
        if name and os.path.exists(name if os.path.isabs(name) else os.path.join(run, name)):
            os.environ["WAYLAND_DISPLAY"] = name
            return True
        time.sleep(0.25)
    return False


def _log_to_file():
    if sys.stdout.isatty():
        return
    config.STATE_DIR.mkdir(parents=True, exist_ok=True)
    log = open(config.STATE_DIR / "eva-desk.log", "a", buffering=1)
    os.dup2(log.fileno(), 1)
    os.dup2(log.fileno(), 2)


def main():
    ap = argparse.ArgumentParser(prog="eva-desk")
    ap.add_argument("--config", help="path to eva.toml")
    ap.add_argument("--write-lua", action="store_true")
    ap.add_argument("--render", metavar="DIR")
    a = ap.parse_args()
    cfg = config.load(a.config)

    if a.write_lua:
        out = config.write_lua_settings(cfg, *_monitor_size())
        print(out)
        return
    if a.render:
        from .preview import render_all
        render_all(cfg, a.render)
        return

    from . import ipc
    if ipc.running():
        print("eva-desk is already running")
        return
    _set_process_name()
    _log_to_file()
    if not _wait_for_display():
        print("eva-desk: no Wayland display to draw on", flush=True)
        sys.exit(1)
    ctypes.CDLL("libgtk4-layer-shell.so")                    # must load before libwayland-client
    from .app import App
    passthrough = sys.argv[1:]
    sys.exit(App(cfg, passthrough).run([sys.argv[0]]))


if __name__ == "__main__":
    main()
