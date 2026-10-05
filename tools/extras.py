#!/usr/bin/env python3
"""eva-desk extras: the same look for the apps around the desk (kitty, starship, neovim, the shell). The files under extras/ are written for the eva theme; installing for another theme from themes.py
rewrites their colours role by role (themes.retheme).

  eva-extras list
  eva-extras install [--theme NAME] kitty starship nvim shell | all
  eva-extras paths                         where each extra goes on this machine

Every file written gets a backup next to it (*.bak-eva-<date>) and is added to eva.toml's
retheme_files, so `eva-ctl theme` keeps it in step afterwards.
"""
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from eva_desk import config, themes  # noqa: E402

EXTRAS = ROOT / "extras"
HOME = Path.home()
CONF = Path(os.environ.get("XDG_CONFIG_HOME", HOME / ".config"))
STAMP = time.strftime("%Y%m%d-%H%M%S")


def targets():
    """{extra: [(source under extras/, destination, mode)]}; mode: text (rethemed) or copy."""
    return {
        "kitty": [("kitty/colors.conf", CONF / "kitty" / "eva.conf", "text"),
                  ("kitty/tab_bar.py", CONF / "kitty" / "tab_bar.py", "text")],
        "starship": [("starship/starship.toml", CONF / "starship.toml", "text")],
        "nvim": [("nvim/colors/eva.lua", CONF / "nvim" / "colors" / "eva.lua", "text"),
                 ("nvim/plugins/eva-ui.lua", CONF / "nvim" / "lua" / "plugins" / "eva-ui.lua", "text")],
        "shell": [("shell/eva.zsh", CONF / "zsh" / "eva.zsh", "text"),
                  ("shell/vivid.yml", CONF / "vivid" / "themes" / "eva.yml", "text")],
    }


NOTES = {
    "kitty": "add to kitty.conf:  include ./eva.conf   and   tab_bar_style custom   (tab_bar.py sits next to it)",
    "starship": "the prompt is the whole starship.toml; starship reads it on the next prompt",
    "nvim": "AstroNvim: colorscheme = \"eva\" in astroui opts; plugins/eva-ui.lua is picked up by lazy. Other setups: :colorscheme eva",
    "shell": "zsh: source ~/.config/zsh/eva.zsh at the end of .zshrc; LS_COLORS via vivid (optional)",
}


def retheme_text(text, theme_name):
    src, dst = themes.get("eva"), themes.get(theme_name)
    return themes.retheme(text, src, dst) if theme_name != "eva" else text


def register(paths):
    """Add the installed files to eva.toml [theme] retheme_files (dedup), creating the key if needed."""
    toml = config.CONFIG_DIR / "eva.toml"
    if not toml.exists():
        return
    text = toml.read_text()
    entries = [f'"{p}"' for p in paths]
    m = re.search(r"(?ms)^retheme_files\s*=\s*\[(.*?)\]", text)
    if m:
        have = m.group(1)
        new = [e for e in entries if e not in have]
        if not new:
            return
        body = have.rstrip()
        sep = "," if body.strip() and not body.rstrip().endswith(",") else ""
        text = text[:m.start(1)] + body + sep + "\n                 " + ", ".join(new) + "\n" + text[m.end(1):]
    elif re.search(r"(?m)^\[theme\]", text):
        text = re.sub(r"(?m)^\[theme\]\s*$", "[theme]\nretheme_files = [" + ", ".join(entries) + "]", text, count=1)
    else:
        text = "[theme]\nretheme_files = [" + ", ".join(entries) + "]\n\n" + text
    toml.write_text(text)


def install(names, theme_name, dry=False):
    t = targets()
    if "all" in names:
        names = list(t)
    done = []
    for name in names:
        if name not in t:
            print(f"unknown extra: {name} (have: {', '.join(t)})", file=sys.stderr)
            continue
        for rel, dst, mode in t[name]:
            src = EXTRAS / rel
            if dry:
                print(f"{name}: {src.relative_to(ROOT)} -> {dst} ({mode})")
                continue
            dst.parent.mkdir(parents=True, exist_ok=True)
            if dst.exists() and mode != "append":
                shutil.copy(dst, dst.with_name(dst.name + ".bak-eva-" + STAMP))
            if mode == "copy":
                shutil.copy(src, dst)
            elif mode == "append":
                old = dst.read_text() if dst.exists() else ""
                add = src.read_text()
                if add.strip() not in old:
                    dst.write_text(old.rstrip("\n") + ("\n" if old else "") + add)
            else:
                dst.write_text(retheme_text(src.read_text(), theme_name))
            if mode == "text":
                done.append(str(dst).replace(str(HOME), "~"))
        print(f"{name}: installed ({theme_name}) · {NOTES.get(name, '')}")
    if done and not dry:
        register(done)


def main():
    args = sys.argv[1:]
    theme_name = "eva"
    if "--theme" in args:
        i = args.index("--theme")
        theme_name = args[i + 1]
        del args[i:i + 2]
    dry = "--dry-run" in args
    args = [a for a in args if a != "--dry-run"]
    if not args or args[0] in ("-h", "--help", "help"):
        print(__doc__.strip())
        return 0
    if args[0] == "list":
        for name, files in targets().items():
            print(f"{name:9s} {NOTES.get(name, '')}")
        return 0
    if args[0] == "paths":
        for name, files in targets().items():
            for rel, dst, mode in files:
                print(f"{name:9s} {dst}")
        return 0
    if args[0] == "install":
        if theme_name not in themes.THEMES:
            print(f"unknown theme {theme_name}", file=sys.stderr)
            return 1
        install(args[1:] or ["all"], theme_name, dry)
        return 0
    print(__doc__.strip())
    return 2


if __name__ == "__main__":
    sys.exit(main())
