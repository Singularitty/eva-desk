"""Control socket ($XDG_RUNTIME_DIR/eva-desk.sock): one line in, one line out."""
import os
import socket
from pathlib import Path

SOCK = Path(os.environ.get("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}")) / "eva-desk.sock"


def send(cmd, timeout=2.0):
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
        s.settimeout(timeout)
        s.connect(str(SOCK))
        s.sendall((cmd.strip() + "\n").encode())
        data = b""
        while not data.endswith(b"\n"):
            b = s.recv(4096)
            if not b:
                break
            data += b
    return data.decode().strip()


def running():
    try:
        return send("ping", timeout=0.5) == "pong"
    except OSError:
        return False


class Server:
    def __init__(self, handler):
        from gi.repository import Gio
        self.handler = handler
        if SOCK.exists():
            SOCK.unlink()
        self.service = Gio.SocketService.new()
        self.service.add_address(Gio.UnixSocketAddress.new(str(SOCK)), Gio.SocketType.STREAM,
                                 Gio.SocketProtocol.DEFAULT, None)
        self.service.connect("incoming", self._incoming)
        self.service.start()

    def _incoming(self, service, conn, source):
        from gi.repository import Gio, GLib
        try:
            line, _ = Gio.DataInputStream.new(conn.get_input_stream()).read_line_utf8(None)
            try:
                reply = self.handler((line or "").strip())
            except Exception as e:                          # a bad command must not kill the daemon
                reply = f"error: {e}"
            conn.get_output_stream().write_all((str(reply) + "\n").encode(), None)
            conn.close(None)
        except GLib.Error:
            pass
        return True
