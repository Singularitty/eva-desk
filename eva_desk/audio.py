"""Default sink volume for the bar: `pactl subscribe` events, `wpctl get-volume` for the value."""
import re
import shutil
import subprocess

from gi.repository import Gio, GLib


class Volume:
    def __init__(self, on_change):
        self.on_change = on_change
        self.pending = None
        self.stream = None
        self.query()
        if shutil.which("pactl"):
            try:
                self.proc = Gio.Subprocess.new(["pactl", "subscribe"], Gio.SubprocessFlags.STDOUT_PIPE)
                self.stream = Gio.DataInputStream.new(self.proc.get_stdout_pipe())
                self._read()
                return
            except GLib.Error:
                pass
        GLib.timeout_add_seconds(3, lambda: (self.query(), True)[1])

    def query(self):
        try:
            out = subprocess.run(["wpctl", "get-volume", "@DEFAULT_AUDIO_SINK@"], capture_output=True, text=True, timeout=1).stdout
        except (OSError, subprocess.SubprocessError):
            return
        m = re.search(r"Volume:\s*([\d.]+)", out)
        if m:
            self.on_change(round(float(m.group(1)) * 100), "MUTED" in out)

    def _read(self):
        self.stream.read_line_async(GLib.PRIORITY_DEFAULT, None, self._line)

    def _line(self, stream, res):
        try:
            line, _ = stream.read_line_finish_utf8(res)
        except GLib.Error:
            line = None
        if line is None:                                   # pactl went away: fall back to polling
            GLib.timeout_add_seconds(3, lambda: (self.query(), True)[1])
            return
        if " sink " in line or " server " in line:
            if self.pending is None:
                self.pending = GLib.timeout_add(80, self._fire)
        self._read()

    def _fire(self):
        self.pending = None
        self.query()
        return False
