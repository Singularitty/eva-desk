"""Now-playing state for the bar: `playerctl --follow` events (MPRIS), no polling."""
import shutil

from gi.repository import Gio, GLib


class NowPlaying:
    """Calls on_change(status, title, artist); status is "Playing", "Paused" or "" (no player)."""

    def __init__(self, on_change, players="spotify,%any"):
        self.on_change, self.players = on_change, players
        self.proc = self.stream = None
        if shutil.which("playerctl"):
            self._start()

    def _start(self):
        try:
            self.proc = Gio.Subprocess.new(
                ["playerctl", "-p", self.players, "--follow", "metadata", "--format",
                 "{{status}}\t{{title}}\t{{artist}}"],
                Gio.SubprocessFlags.STDOUT_PIPE | Gio.SubprocessFlags.STDERR_SILENCE)
        except GLib.Error:
            return
        self.stream = Gio.DataInputStream.new(self.proc.get_stdout_pipe())
        self._read()

    def _read(self):
        self.stream.read_line_async(GLib.PRIORITY_DEFAULT, None, self._line)

    def _line(self, stream, res):
        try:
            line, _ = stream.read_line_finish_utf8(res)
        except GLib.Error:
            line = None
        if line is None:                                  # playerctl exited: try again later
            self.on_change("", "", "")
            GLib.timeout_add_seconds(5, lambda: (self._start(), False)[1])
            return
        self.on_change(*parse(line))
        self._read()

    def stop(self):
        if self.proc:
            self.proc.force_exit()


def parse(line):
    """A `status<TAB>title<TAB>artist` line; an empty line means the player went away."""
    parts = (line.split("\t") + ["", "", ""])[:3]
    status, title, artist = (p.strip() for p in parts)
    if status not in ("Playing", "Paused") or not title:
        return "", "", ""
    return status, title, artist
