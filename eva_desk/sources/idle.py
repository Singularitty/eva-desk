"""The idle timer: hypridle as the daemon's child, on a config of its own.

Its one listener calls `eva-ctl standby on` after the minutes of [standby]. hypridle counts idle time the way the
compositor does, so anything that holds an idle inhibitor (a video, a call) keeps standby away by itself.

The child is stopped by its handle. One left behind by a daemon that died is found by the pid that daemon wrote
down, and only ended when that process is hypridle running on this config: never by name.
"""
import os
import shlex
import shutil
import signal
import subprocess
import time
from pathlib import Path


def conf(minutes, ctl):
    """The hypridle config: after `minutes` without input, `ctl standby on`."""
    seconds = max(1, round(float(minutes) * 60))
    return ("# written by eva-desk from [standby] in eva.toml; changes here are lost\n"
            "general {\n"
            "    ignore_dbus_inhibit = false\n"
            "}\n"
            "\n"
            "listener {\n"
            f"    timeout = {seconds}\n"
            f"    on-timeout = {shlex.quote(str(ctl))} standby on\n"
            "}\n")


def end_stale(folder, kill=os.kill, proc="/proc", sleep=time.sleep):
    """End the hypridle that a daemon left behind in `folder`: the pid it wrote down, if that process is hypridle
    and was given this folder's config. Anything else that has the pid by now is left alone. Then wait for it to
    go, a second at most, so that the next one does not find its place on the session bus taken."""
    folder = Path(folder)
    pidfile, config = folder / "hypridle.pid", os.fsencode(str(folder / "hypridle.conf"))
    try:
        pid = int(pidfile.read_text().strip())
    except (OSError, ValueError):
        pid = 0
    if pid > 1:
        entry = Path(proc) / str(pid)
        try:
            words = (entry / "cmdline").read_bytes().split(b"\0")
        except OSError:
            words = []
        ours = bool(words) and os.path.basename(words[0]) == b"hypridle" and (b"-c", config) in zip(words, words[1:])
        if ours:
            try:
                kill(pid, signal.SIGTERM)
            except OSError:
                pass
            else:
                for _ in range(20):
                    if not entry.exists():
                        break
                    sleep(0.05)
    try:
        pidfile.unlink(missing_ok=True)
    except OSError:
        pass


class Idle:
    def __init__(self, minutes, ctl, folder, spawn=subprocess.Popen, which=shutil.which, kill=os.kill, proc="/proc", sleep=time.sleep):
        self.minutes, self.ctl, self.folder = minutes, ctl, Path(folder)
        self.spawn, self.which, self.kill, self.procfs, self.sleep = spawn, which, kill, proc, sleep
        self.child = None
        self.said = False          # that hypridle is missing or would not start
        self.left = False          # that the child has exited was already told

    @property
    def path(self):
        return self.folder / "hypridle.conf"

    @property
    def pidfile(self):
        return self.folder / "hypridle.pid"

    def _say(self, what):
        if not self.said:
            self.said = True
            print(f"eva-desk: {what}: standby only by eva-ctl standby on", flush=True)

    def start(self):
        """Write the config and run hypridle on it. False, said once, when it is not installed or will not start."""
        self.stop()
        if not self.which("hypridle"):
            self._say("hypridle is not installed")
            return False
        try:
            self.folder.mkdir(parents=True, exist_ok=True)
            end_stale(self.folder, self.kill, self.procfs, self.sleep)
            self.path.write_text(conf(self.minutes, self.ctl))
            self.child = self.spawn(["hypridle", "-q", "-c", str(self.path)], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL)
            self.pidfile.write_text(f"{self.child.pid}\n")
        except OSError as e:
            self._say(f"hypridle did not start ({e})")
            return False
        self.left = False
        return True

    def stop(self):
        """End the child: ask, wait a second, then insist. Nothing when there is none."""
        child, self.child = self.child, None
        if child is None:
            return
        if child.poll() is None:
            child.terminate()
            try:
                child.wait(timeout=1)
            except subprocess.TimeoutExpired:
                child.kill()
                try:
                    child.wait(timeout=1)              # so that it is not left a zombie
                except subprocess.TimeoutExpired:
                    pass
        self.pidfile.unlink(missing_ok=True)

    def gone(self):
        """Whether the child has exited by itself. True once, so that it is said once."""
        if self.child is None or self.left or self.child.poll() is None:
            return False
        self.left = True
        return True
