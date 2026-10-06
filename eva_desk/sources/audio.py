"""Audio state for the sound settings panel: the eww `audiostate`/`audio-set`/`audio-quick`
scripts (tools/sources), wrapped so the daemon can read a snapshot, listen for live changes
on the GLib main loop, and fire-and-forget volume/mute/default/move/quick-toggle writes.
"""
import json
import subprocess
from pathlib import Path
from typing import Callable

from gi.repository import Gio, GLib

DEFAULT_QUICK = {"dnd": False, "night": False, "power": "unknown"}


def scripts_dir() -> Path:
    return Path(__file__).resolve().parents[2] / "tools" / "sources"


def parse_line(line: str) -> dict | None:
    try:
        data = json.loads(line)
    except (TypeError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def snapshot() -> dict | None:
    """One `audiostate --once` snapshot, or None if the script is missing, fails, or
    prints no JSON within 3 s."""
    script = scripts_dir() / "audiostate"
    try:
        out = subprocess.run([str(script), "--once"], capture_output=True, text=True, timeout=3)
    except (OSError, subprocess.SubprocessError):
        return None
    return parse_line(out.stdout)


def quick() -> dict:
    """`audio-quick` state, or the all-off default on any failure."""
    script = scripts_dir() / "audio-quick"
    try:
        out = subprocess.run([str(script)], capture_output=True, text=True, timeout=3)
    except (OSError, subprocess.SubprocessError):
        return dict(DEFAULT_QUICK)
    data = parse_line(out.stdout)
    return data if data is not None else dict(DEFAULT_QUICK)


def _popen(script_name: str, *args) -> None:
    """Fire-and-forget: start the script, never wait on it, never raise."""
    script = scripts_dir() / script_name
    try:
        subprocess.Popen([str(script), *(str(a) for a in args)],
                          stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except OSError as e:
        print(f"eva-desk: audio: {e}")


def set_volume(kind: str, ident: str | int, value: int) -> None:
    _popen("audio-set", "vol", kind, ident, value)


def toggle_mute(kind: str, ident: str | int) -> None:
    _popen("audio-set", "mute", kind, ident)


def set_default(kind: str, name: str) -> None:
    _popen("audio-set", "default", kind, name)


def move(kind: str, ident: str | int, target: str) -> None:
    _popen("audio-set", "move", kind, ident, target)


def quick_toggle(what: str) -> None:
    _popen("audio-quick", what)


class Listener:
    """Live audio state, read on the GLib main loop: `audiostate --struct` (layout
    changes) and `audiostate --levels` (volume/mute changes), each its own long-lived
    Gio.Subprocess. Lines that are not JSON are ignored."""

    def __init__(self, on_struct: Callable[[dict], None], on_levels: Callable[[dict], None]):
        self.on_struct = on_struct
        self.on_levels = on_levels
        self._procs: list[Gio.Subprocess] = []
        self._streams: list[Gio.DataInputStream] = []

    def start(self) -> None:
        self._spawn(["--struct"], self.on_struct)
        self._spawn(["--levels"], self.on_levels)

    def _spawn(self, args: list[str], callback: Callable[[dict], None]) -> None:
        script = scripts_dir() / "audiostate"
        try:
            proc = Gio.Subprocess.new([str(script), *args],
                                       Gio.SubprocessFlags.STDOUT_PIPE | Gio.SubprocessFlags.STDERR_SILENCE)
        except GLib.Error:
            return
        stream = Gio.DataInputStream.new(proc.get_stdout_pipe())
        self._procs.append(proc)
        self._streams.append(stream)
        self._read(stream, callback)

    def _read(self, stream: Gio.DataInputStream, callback: Callable[[dict], None]) -> None:
        stream.read_line_async(GLib.PRIORITY_DEFAULT, None, lambda s, res: self._line(s, res, callback))

    def _line(self, stream: Gio.DataInputStream, res, callback: Callable[[dict], None]) -> None:
        try:
            line, _ = stream.read_line_finish_utf8(res)
        except GLib.Error:
            line = None
        if line is None:                        # the script exited: stop reading this stream
            return
        data = parse_line(line)
        if data is not None:
            callback(data)
        self._read(stream, callback)

    def stop(self) -> None:
        for proc in self._procs:
            proc.force_exit()
        self._procs = []
        self._streams = []
