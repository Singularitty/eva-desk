"""Audio data source tests: no compositor, no windows. Run: python3 -m unittest discover -s tests"""
import os
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
        with mock.patch.object(audio, "scripts_dir", return_value=Path("/nonexistent")):
            self.assertIsNone(audio.snapshot())
            self.assertEqual(audio.quick(), {"dnd": False, "night": False, "power": "unknown"})
            audio.set_volume("sink", 60, 50)             # does not raise
            audio.toggle_mute("source", 12)               # does not raise
            audio.set_default("sink", "alsa_output.foo")  # does not raise
            audio.move("sink-input", 105, "alsa_output.bar")  # does not raise
            audio.quick_toggle("dnd")                      # does not raise

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
            with mock.patch.object(audio, "scripts_dir", return_value=Path(tmp)):
                self.assertIsNone(audio.snapshot())

    def test_quick_returns_default_on_nonzero_exit(self):
        from eva_desk.sources import audio
        with tempfile.TemporaryDirectory() as tmp:
            fake = Path(tmp) / "audio-quick"
            fake.write_text('#!/bin/sh\nprintf \'{"dnd":true,"night":false,"power":"balanced"}\\n\'\nexit 1\n')
            fake.chmod(0o755)
            with mock.patch.object(audio, "scripts_dir", return_value=Path(tmp)):
                self.assertEqual(audio.quick(), {"dnd": False, "night": False, "power": "unknown"})

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


if __name__ == "__main__":
    unittest.main()
