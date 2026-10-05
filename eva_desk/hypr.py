"""Hyprland IPC: event stream (socket2) and requests (socket), legacy or Lua config mode."""
import json
import os
import re
import socket
import subprocess
from pathlib import Path

from gi.repository import Gio, GLib


def instance_dir():
    run = os.environ.get("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}")
    sig = os.environ.get("HYPRLAND_INSTANCE_SIGNATURE")
    if not sig:
        raise RuntimeError("HYPRLAND_INSTANCE_SIGNATURE is not set: is Hyprland running?")
    return Path(run) / "hypr" / sig


class Hypr:
    def __init__(self):
        self.dir = instance_dir()
        self._lua = None
        self._conn = None
        self._stream = None

    # ---------------------------------------------------------------- requests
    def request(self, cmd):
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
            s.settimeout(2.0)
            s.connect(str(self.dir / ".socket.sock"))
            s.sendall(cmd.encode())
            chunks = []
            while True:
                b = s.recv(65536)
                if not b:
                    break
                chunks.append(b)
        return b"".join(chunks).decode(errors="replace")

    def j(self, what):
        out = self.request("j/" + what)
        try:
            return json.loads(out)
        except json.JSONDecodeError:
            return None

    @property
    def lua(self):
        """Lua-configured Hyprland refuses legacy `keyword`/`dispatch` calls ("non-legacy parsers")."""
        if self._lua is None:
            try:
                self._lua = "non-legacy" in self.request("keyword evadesk:probe 0")
            except OSError:
                self._lua = False
        return self._lua

    def eval_lua(self, code):
        subprocess.Popen(["hyprctl", "eval", code], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    def focus_workspace(self, ws):
        if self.lua:
            target = f'"{ws}"' if isinstance(ws, str) else str(int(ws))
            self.eval_lua(f"hl.dispatch(hl.dsp.focus({{ workspace = {target} }}))")
        else:
            self.request(f"dispatch workspace {ws}")

    def focus_window(self, address):
        if self.lua:
            self.eval_lua(f'hl.dispatch(hl.dsp.focus({{ window = "address:{address}" }}))')
        else:
            self.request(f"dispatch focuswindow address:{address}")

    def exec(self, cmd):
        if self.lua:
            self.eval_lua("hl.exec_cmd(" + json.dumps(cmd) + ")")
        else:
            self.request("dispatch exec " + cmd)

    # ---------------------------------------------------------------- events
    def listen(self, on_event):
        """Read `name>>data` lines from socket2 on the GLib main loop."""
        client = Gio.SocketClient.new()
        addr = Gio.UnixSocketAddress.new(str(self.dir / ".socket2.sock"))
        self._conn = client.connect(addr, None)
        self._stream = Gio.DataInputStream.new(self._conn.get_input_stream())

        def read_next():
            self._stream.read_line_async(GLib.PRIORITY_DEFAULT, None, on_line)

        def on_line(stream, res):
            try:
                line, _ = stream.read_line_finish_utf8(res)
            except GLib.Error:
                line = None
            if line is None:                       # Hyprland went away
                on_event("evadesk-disconnected", "")
                return
            name, _, data = line.partition(">>")
            try:
                on_event(name, data)
            finally:
                read_next()
        read_next()


def class_matches(cls, patterns):
    return any(re.search(p, cls or "") for p in patterns)
