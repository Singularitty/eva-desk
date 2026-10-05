"""Per-workspace wallpapers through awww (or swww): fixed ones per workspace, the rest from a pool."""
import random
import shutil
import subprocess
import time

from .config import asset


class Wallpapers:
    def __init__(self, cfg):
        self.cfg = cfg["wallpapers"]
        want = self.cfg["daemon"]
        self.bin = None
        for b in (["awww", "swww"] if want == "auto" else [want]):
            if b != "none" and shutil.which(b):
                self.bin = b
                break
        self.current = {}
        self.assign = {}
        self.shuffle()

    @property
    def ok(self):
        return self.bin is not None and self.cfg["enabled"]

    def ensure_daemon(self):
        if not self.ok:
            return
        if subprocess.run([self.bin, "query"], capture_output=True).returncode == 0:
            return
        subprocess.Popen([self.bin + "-daemon"], start_new_session=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        for _ in range(25):
            time.sleep(0.2)
            if subprocess.run([self.bin, "query"], capture_output=True).returncode == 0:
                return

    def shuffle(self):
        pool = list(self.cfg["pool"])
        random.shuffle(pool)
        self.pool = pool

    def choice(self, ws_id, ws_name):
        named = self.cfg["named"].get(ws_name or "")
        if named:
            return named
        fixed = self.cfg["workspaces"].get(str(ws_id))
        if fixed:
            return fixed
        if not self.pool or not isinstance(ws_id, int) or ws_id < 1:
            return None
        return self.pool[(ws_id - 1) % len(self.pool)]

    def set_for(self, monitor, ws_id, ws_name, force=False):
        if not self.ok:
            return
        value = self.choice(ws_id, ws_name)
        if not value:
            return
        target = asset(value)
        if not force and self.current.get(monitor) == target:
            return
        self.current[monitor] = target
        if target.startswith("#"):
            cmd = [self.bin, "clear", "-o", monitor, target.lstrip("#")]
        else:
            cmd = [self.bin, "img", "-o", monitor, "--resize", "crop", "-t", self.cfg["transition"],
                   "--transition-duration", str(self.cfg["duration"]), "--transition-fps", "60", target]
        subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    def set_static(self, monitor, description):
        if not self.ok:
            return
        for key, value in self.cfg["static"].items():
            if key in (description or "") or key == monitor:
                target = asset(value)
                if self.current.get(monitor) != target:
                    self.current[monitor] = target
                    subprocess.Popen([self.bin, "img", "-o", monitor, "--resize", "crop", "-t", "none", target],
                                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                return True
        return False
