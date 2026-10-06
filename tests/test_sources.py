"""Audio data source tests: no compositor, no windows. Run: python3 -m unittest discover -s tests"""
import contextlib
import io
import os
import signal
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.pop("WAYLAND_DISPLAY", None)


class AudioSource(unittest.TestCase):
    def test_parse_line(self):
        from eva_desk.sources import audio
        self.assertIsNone(audio.parse_line("not json"))
        self.assertEqual(audio.parse_line('{"a": 1}\n'), {"a": 1})

    def test_audio_source_missing_script(self):
        from eva_desk.sources import audio
        out = io.StringIO()
        with mock.patch.object(audio, "scripts_dir", return_value=Path("/nonexistent")), contextlib.redirect_stdout(out):
            self.assertIsNone(audio.snapshot())
            self.assertEqual(audio.quick(), {"dnd": False, "night": False, "power": "unknown"})
            audio.set_volume("sink", 60, 50)             # does not raise
            audio.toggle_mute("source", 12)               # does not raise
            audio.set_default("sink", "alsa_output.foo")  # does not raise
            audio.move("sink-input", 105, "alsa_output.bar")  # does not raise
            audio.quick_toggle("dnd")                      # does not raise
        self.assertEqual(out.getvalue().count("eva-desk: audio: "), 5)   # each failed write is logged once

    def test_snapshot_reads_the_script(self):
        from eva_desk.sources import audio
        fx = Path(__file__).parent / "fixtures" / "audiostate.json"
        with tempfile.TemporaryDirectory() as tmp:
            fake = Path(tmp) / "audiostate"
            fake.write_text(f"#!/bin/sh\ncat {fx}\n")
            fake.chmod(0o755)
            with mock.patch.object(audio, "scripts_dir", return_value=Path(tmp)):
                snap = audio.snapshot()
        self.assertEqual(set(snap), {"sinks", "sources", "apps", "recs"})
        self.assertEqual(snap["sinks"][0]["friendly"], "Monitor speakers (HDMI)")

    def test_quick_reads_the_script(self):
        from eva_desk.sources import audio
        with tempfile.TemporaryDirectory() as tmp:
            fake = Path(tmp) / "audio-quick"
            fake.write_text('#!/bin/sh\nprintf \'{"dnd":true,"night":false,"power":"balanced"}\\n\'\n')
            fake.chmod(0o755)
            with mock.patch.object(audio, "scripts_dir", return_value=Path(tmp)):
                self.assertEqual(audio.quick(), {"dnd": True, "night": False, "power": "balanced"})

    def test_snapshot_returns_none_on_nonzero_exit(self):
        from eva_desk.sources import audio
        fx = Path(__file__).parent / "fixtures" / "audiostate.json"
        with tempfile.TemporaryDirectory() as tmp:
            fake = Path(tmp) / "audiostate"
            fake.write_text(f"#!/bin/sh\ncat {fx}\nexit 1\n")
            fake.chmod(0o755)
            out = io.StringIO()
            with mock.patch.object(audio, "scripts_dir", return_value=Path(tmp)), contextlib.redirect_stdout(out):
                self.assertIsNone(audio.snapshot())
            self.assertIn("audiostate exited 1", out.getvalue())

    def test_quick_returns_default_on_nonzero_exit(self):
        from eva_desk.sources import audio
        with tempfile.TemporaryDirectory() as tmp:
            fake = Path(tmp) / "audio-quick"
            fake.write_text('#!/bin/sh\nprintf \'{"dnd":true,"night":false,"power":"balanced"}\\n\'\nexit 1\n')
            fake.chmod(0o755)
            out = io.StringIO()
            with mock.patch.object(audio, "scripts_dir", return_value=Path(tmp)), contextlib.redirect_stdout(out):
                self.assertEqual(audio.quick(), {"dnd": False, "night": False, "power": "unknown"})
            self.assertIn("audio-quick exited 1", out.getvalue())

    def test_write_commands_build_the_right_argv(self):
        from eva_desk.sources import audio
        with mock.patch("eva_desk.sources.audio.subprocess.Popen") as popen:
            with mock.patch.object(audio, "scripts_dir", return_value=Path("/opt/tools")):
                audio.set_volume("sink", 60, 50)
                audio.toggle_mute("source", 12)
                audio.set_default("sink", "alsa_output.foo")
                audio.move("sink-input", 105, "alsa_output.bar")
                audio.quick_toggle("dnd")
        argvs = [c.args[0] for c in popen.call_args_list]
        self.assertEqual(argvs[0], ["/opt/tools/audio-set", "vol", "sink", "60", "50"])
        self.assertEqual(argvs[1], ["/opt/tools/audio-set", "mute", "source", "12"])
        self.assertEqual(argvs[2], ["/opt/tools/audio-set", "default", "sink", "alsa_output.foo"])
        self.assertEqual(argvs[3], ["/opt/tools/audio-set", "move", "sink-input", "105", "alsa_output.bar"])
        self.assertEqual(argvs[4], ["/opt/tools/audio-quick", "dnd"])

    def test_listener_reads_struct_and_levels(self):
        from gi.repository import GLib
        from eva_desk.sources import audio
        struct_fx = Path(__file__).parent / "fixtures" / "audiostate.json"
        levels_fx = Path(__file__).parent / "fixtures" / "levels.json"
        with tempfile.TemporaryDirectory() as tmp:
            fake = Path(tmp) / "audiostate"
            fake.write_text(
                "#!/bin/sh\n"
                "case \"$1\" in\n"
                f"  --struct) cat {struct_fx} ;;\n"
                f"  --levels) cat {levels_fx} ;;\n"
                "esac\n"
            )
            fake.chmod(0o755)
            structs, levels = [], []
            loop = GLib.MainLoop()
            t = threading.Thread(target=loop.run, daemon=True)
            t.start()
            try:
                with mock.patch.object(audio, "scripts_dir", return_value=Path(tmp)):
                    listener = audio.Listener(structs.append, levels.append)
                    listener.start()
                    time.sleep(0.3)
                    listener.stop()
            finally:
                loop.quit()
                t.join(timeout=1)
        self.assertEqual(len(structs), 1)
        self.assertEqual(set(structs[0]), {"sinks", "sources", "apps", "recs"})
        self.assertEqual(levels, [{"sink50": {"v": 68, "m": False}, "app105": {"v": 67, "m": False}}])

    def test_listener_ignores_non_json_lines(self):
        from gi.repository import GLib
        from eva_desk.sources import audio
        with tempfile.TemporaryDirectory() as tmp:
            fake = Path(tmp) / "audiostate"
            fake.write_text("#!/bin/sh\necho 'not json'\n")
            fake.chmod(0o755)
            structs, levels = [], []
            loop = GLib.MainLoop()
            t = threading.Thread(target=loop.run, daemon=True)
            t.start()
            try:
                with mock.patch.object(audio, "scripts_dir", return_value=Path(tmp)):
                    listener = audio.Listener(structs.append, levels.append)
                    listener.start()
                    time.sleep(0.3)
                    listener.stop()
            finally:
                loop.quit()
                t.join(timeout=1)
        self.assertEqual(structs, [])
        self.assertEqual(levels, [])

    def test_listener_missing_script_does_not_raise(self):
        from eva_desk.sources import audio
        with mock.patch.object(audio, "scripts_dir", return_value=Path("/nonexistent")):
            listener = audio.Listener(lambda d: None, lambda d: None)
            listener.start()               # does not raise
            listener.stop()                # does not raise

    def test_start_twice_does_not_double_spawn(self):
        from eva_desk.sources import audio
        with mock.patch.object(audio, "scripts_dir", return_value=Path("/nonexistent")):
            listener = audio.Listener(lambda d: None, lambda d: None)
            with mock.patch.object(listener, "_spawn") as spawn:
                listener.start()
                listener.start()           # already running: a no-op
            self.assertEqual(spawn.call_count, 2)       # one for --struct, one for --levels, not four
            listener.stop()

    def test_stop_cancels_the_pending_read(self):
        from eva_desk.sources import audio
        with mock.patch.object(audio, "scripts_dir", return_value=Path("/nonexistent")):
            listener = audio.Listener(lambda d: None, lambda d: None)
            listener.start()
            cancellable = listener._cancellable
            self.assertFalse(cancellable.is_cancelled())
            listener.stop()
            self.assertTrue(cancellable.is_cancelled())
            self.assertFalse(listener.running)

    def test_stop_prevents_late_callbacks(self):
        from gi.repository import GLib
        from eva_desk.sources import audio
        with tempfile.TemporaryDirectory() as tmp:
            fake = Path(tmp) / "audiostate"
            fake.write_text("#!/bin/sh\necho '{\"a\":1}'\n")
            fake.chmod(0o755)
            calls = []
            loop = GLib.MainLoop()
            t = threading.Thread(target=loop.run, daemon=True)
            t.start()
            try:
                with mock.patch.object(audio, "scripts_dir", return_value=Path(tmp)):
                    listener = audio.Listener(calls.append, calls.append)
                    listener.start()
                    listener.stop()                     # stop right away: a buffered line may still land,
                    frozen = len(calls)                  # but nothing more should arrive after this point
                    time.sleep(0.3)
            finally:
                loop.quit()
                t.join(timeout=1)
        self.assertEqual(len(calls), frozen)             # the counter is frozen at stop() time


def _alive(pid):
    """True while `pid` runs (a zombie counts as gone: it no longer holds anything)."""
    try:
        with open(f"/proc/{pid}/stat") as f:
            return f.read().rsplit(")", 1)[1].split()[0] != "Z"
    except OSError:
        return False


def _kill_leftovers(pidfile):
    """Even when a test fails, never leave a fake `pactl subscribe` behind."""
    try:
        pids = [int(p) for p in pidfile.read_text().split()]
    except (OSError, ValueError):
        return
    for pid in pids:
        if _alive(pid):
            try:
                os.kill(pid, signal.SIGKILL)
            except OSError:
                pass


class AudioStateScript(unittest.TestCase):
    """The real tools/sources/audiostate against a fake `pactl` on PATH (no audio is touched)."""

    def _fake_bin(self, tmp):
        bin_dir = Path(tmp) / "bin"
        bin_dir.mkdir()
        pactl = bin_dir / "pactl"
        pactl.write_text(
            "#!/bin/sh\n"
            "case \"$1\" in\n"
            f"  subscribe) echo $$ >> {tmp}/subscribe.pid; exec sleep 60 ;;\n"
            "  --format=json) [ \"$2\" = info ] && echo '{}' || echo '[]' ;;\n"
            "esac\n")
        pactl.chmod(0o755)
        return bin_dir

    def test_listener_stop_leaves_no_subscribe_child(self):
        from gi.repository import GLib
        from eva_desk.sources import audio
        with tempfile.TemporaryDirectory() as tmp:
            env = {"PATH": f"{self._fake_bin(tmp)}:{os.environ['PATH']}", "XDG_CACHE_HOME": tmp}
            pidfile = Path(tmp) / "subscribe.pid"
            loop = GLib.MainLoop()
            t = threading.Thread(target=loop.run, daemon=True)
            t.start()
            try:
                with mock.patch.dict(os.environ, env):
                    listener = audio.Listener(lambda d: None, lambda d: None)
                    listener.start()
                    for _ in range(100):                     # wait until both scripts (struct, levels) subscribed
                        if pidfile.exists() and len(pidfile.read_text().split()) == 2:
                            break
                        time.sleep(0.05)
                    self.assertTrue(pidfile.exists(), "the fake pactl subscribe never started")
                    pids = [int(p) for p in pidfile.read_text().split()]
                    self.assertEqual(len(pids), 2)
                    self.assertTrue(all(_alive(p) for p in pids))
                    script_pids = [int(p.get_identifier()) for p in listener._procs]
                    listener.stop()
                    for _ in range(60):
                        if not any(_alive(p) for p in pids + script_pids):
                            break
                        time.sleep(0.05)
                    lingering = [p for p in pids + script_pids if _alive(p)]
            finally:
                loop.quit()
                t.join(timeout=1)
                _kill_leftovers(pidfile)
            self.assertEqual(lingering, [], "pactl subscribe or audiostate outlived the listener")

    def test_sigterm_takes_the_subscribe_child_down(self):
        script = Path(__file__).resolve().parent.parent / "tools" / "sources" / "audiostate"
        with tempfile.TemporaryDirectory() as tmp:
            env = dict(os.environ, PATH=f"{self._fake_bin(tmp)}:{os.environ['PATH']}", XDG_CACHE_HOME=tmp)
            pidfile = Path(tmp) / "subscribe.pid"
            proc = subprocess.Popen([str(script), "--levels"], env=env, stdout=subprocess.DEVNULL)
            try:
                for _ in range(100):
                    if pidfile.exists():
                        break
                    time.sleep(0.05)
                time.sleep(0.2)
                sub = int(pidfile.read_text().split()[0])
                self.assertTrue(_alive(sub))
                proc.send_signal(signal.SIGTERM)
                self.assertEqual(proc.wait(timeout=5), 143)
                for _ in range(40):
                    if not _alive(sub):
                        break
                    time.sleep(0.05)
                self.assertFalse(_alive(sub), "pactl subscribe outlived audiostate")
            finally:
                if proc.poll() is None:
                    proc.kill()
                    proc.wait(timeout=5)
                _kill_leftovers(pidfile)


if __name__ == "__main__":
    unittest.main()
