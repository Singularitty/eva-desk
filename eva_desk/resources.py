"""CPU, memory and network readings for the bar, straight from /proc and /sys (no extra tools)."""
import time
from pathlib import Path


def human(n):
    """Bytes (or bytes/s) as a short tag label: 0K, 980K, 1.2M, 12M, 9.8G."""
    n = max(0, float(n or 0))
    for unit, size in (("T", 1 << 40), ("G", 1 << 30), ("M", 1 << 20)):
        if n >= size:
            v = n / size
            return f"{v:.1f}{unit}" if v < 10 else f"{v:.0f}{unit}"
    return f"{n / 1024:.0f}K"


class Sampler:
    """Call sample() every couple of seconds; rates and CPU load are measured between calls."""

    def __init__(self, root="/"):
        self.root = Path(root)
        self._cpu = None              # (idle, total) jiffies at the previous sample
        self._net = None              # (iface, rx, tx, time) at the previous sample

    def _read(self, rel):
        try:
            return (self.root / rel).read_text()
        except OSError:
            return ""

    def cpu(self):
        """Busy percentage since the previous call (None on the first call)."""
        line = self._read("proc/stat").split("\n", 1)[0].split()
        if len(line) < 5 or line[0] != "cpu":
            return None
        v = [int(x) for x in line[1:9]]          # user nice system idle iowait irq softirq steal
        idle, total = v[3] + (v[4] if len(v) > 4 else 0), sum(v)
        prev, self._cpu = self._cpu, (idle, total)
        if not prev or total <= prev[1]:
            return None
        return round(100 * (1 - (idle - prev[0]) / (total - prev[1])))

    def mem(self):
        """(used, total) bytes; used = total - available, like free(1)."""
        info = {}
        for line in self._read("proc/meminfo").splitlines():
            k, _, rest = line.partition(":")
            if k in ("MemTotal", "MemAvailable"):
                info[k] = int(rest.split()[0]) * 1024
        total = info.get("MemTotal", 0)
        return total - info.get("MemAvailable", total), total

    def route_iface(self):
        """Interface of the default route (IPv4, then IPv6), or None when offline."""
        best = None
        for line in self._read("proc/net/route").splitlines()[1:]:
            f = line.split()
            if len(f) > 6 and f[1] == "00000000" and f[0] != "lo":
                if best is None or int(f[6]) < best[1]:
                    best = (f[0], int(f[6]))
        if best:
            return best[0]
        for line in self._read("proc/net/ipv6_route").splitlines():
            f = line.split()
            if len(f) == 10 and f[0] == "0" * 32 and f[1] == "00" and f[9] != "lo":
                return f[9]
        return None

    def kind(self, iface):
        if not iface:
            return "none"
        if iface.startswith(("wg", "tun", "tap", "ppp")):
            return "vpn"
        net = self.root / "sys/class/net" / iface
        if (net / "wireless").exists() or (net / "phy80211").exists():
            return "wifi"
        return "lan"

    def net(self, now=None):
        """{"iface", "kind": lan|wifi|vpn|none, "down", "up"} with rates in bytes/s."""
        now = time.monotonic() if now is None else now
        iface = self.route_iface()
        rx = tx = None
        for line in self._read("proc/net/dev").splitlines()[2:]:
            name, _, rest = line.partition(":")
            if name.strip() == iface:
                f = rest.split()
                rx, tx = int(f[0]), int(f[8])
                break
        down = up = 0
        prev = self._net
        if rx is not None and prev and prev[0] == iface and now > prev[3]:
            dt = now - prev[3]
            down, up = max(0, rx - prev[1]) / dt, max(0, tx - prev[2]) / dt
        self._net = (iface, rx, tx, now) if rx is not None else None
        return {"iface": iface, "kind": self.kind(iface), "down": down, "up": up}

    def sample(self, now=None):
        used, total = self.mem()
        return {"cpu": self.cpu(), "mem_used": used, "mem_total": total, "net": self.net(now)}
