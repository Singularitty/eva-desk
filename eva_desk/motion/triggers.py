"""When each motion piece plays: the decisions, as plain functions and a few small state machines.

Nothing here touches GTK, the clock or a file. Hyprland's answers come in as the lists `hyprctl -j` gives and time as
a number, so every rule can be tested with plain values.
"""
import re

from ..hypr import class_matches


def boot_due(marker, signature):
    """Whether the boot sequence is due: there is a Hyprland session, and the marker file's text does not name it."""
    return bool(signature) and (marker or "").strip() != signature


def boot_inputs(monitors, version, lua, net):
    """What the boot card reads live: the outputs that are up, as the desk sees them, and Hyprland's version."""
    outputs = []
    for m in monitors or []:
        if not m.get("disabled"):
            w, h = m.get("width", 0), m.get("height", 0)
            outputs.append(f"{h}×{w}" if int(m.get("transform", 0) or 0) % 2 else f"{w}×{h}")       # a turned monitor is as tall as it was wide
    raw = str((version or {}).get("version") or (version or {}).get("tag") or "")
    found = re.search(r"(\d+)\.(\d+)", raw)
    return {"outputs": outputs, "hyprland": f"{found.group(1)}.{found.group(2)}" if found else raw, "lua": lua, "net": net}


def game_open(clients, patterns):
    """A game is open when any window's class matches, whether it is fullscreen, visible, or on another workspace."""
    return any(class_matches(c.get("class", ""), patterns) for c in clients or [])


def fullscreen_monitors(monitors, clients):
    """The names of the monitors that show a fullscreen (not merely maximised) window."""
    showing = {}                                             # the id of a workspace that is on show -> its monitor
    for m in monitors or []:
        for ws in (m.get("activeWorkspace") or {}, m.get("specialWorkspace") or {}):
            if ws.get("id"):
                showing[ws["id"]] = m.get("name")
    found = set()
    for c in clients or []:
        ws = (c.get("workspace") or {}).get("id")
        if ws in showing and c.get("mapped", True) and not c.get("hidden") and int(c.get("fullscreen", 0) or 0) >= 2:
            found.add(showing[ws])
    return found


def track_monitor(monitors, mains):
    """Where the track card goes: the focused monitor when it is a main one, else the first main one that exists."""
    names = [m.get("name") for m in monitors or []]
    mains = [name for name in mains if name in names]
    focused = next((m.get("name") for m in monitors or [] if m.get("focused")), None)
    return focused if focused in mains else (mains[0] if mains else None)


def standby_blocked(monitors, clients, patterns, locked):
    """Why standby may not start, and must end if it is up: "locked", "game", "fullscreen", or "" when nothing
    stands in its way. `locked` is Hyprland's word on the session; None, when it did not say, blocks nothing."""
    if locked:
        return "locked"
    if game_open(clients, patterns):
        return "game"
    if fullscreen_monitors(monitors, clients):
        return "fullscreen"
    return ""


def paused_monitors(monitors, clients, patterns, locked=False, asleep=False, off=False, standby=False):
    """The names of the monitors on which the loops stand still. All of them while a game is open anywhere (the
    loops must cost a game nothing), while the session is locked, the machine is going to sleep, standby covers
    them, or they were switched off by hand; otherwise the ones that show a fullscreen window."""
    names = {m.get("name") for m in monitors or [] if m.get("name")}
    if locked or asleep or off or standby or game_open(clients, patterns):
        return names
    return fullscreen_monitors(monitors, clients) & names


def wall_monitor(monitors, mains, want):
    """The name of the monitor the status wall belongs on: the one `want` names (its connector, or part of its
    description), else the first that is not a main one. None when there is no such monitor: the wall never goes
    on a main one."""
    others = [m for m in monitors or [] if m.get("name") and not m.get("disabled") and m["name"] not in mains]
    if want:
        return next((m["name"] for m in others if m["name"] == want or want in (m.get("description") or "")), None)
    return others[0]["name"] if others else None


def workspace_empty(monitor, clients):
    """Whether that monitor shows no window at all: none on its workspace, none on a scratchpad open over it."""
    if not monitor:
        return False
    showing = {ws.get("id") for ws in (monitor.get("activeWorkspace") or {}, monitor.get("specialWorkspace") or {}) if ws.get("id")}
    return not any((c.get("workspace") or {}).get("id") in showing and c.get("mapped", True) and not c.get("hidden") for c in clients or [])


def readings(res):
    """The sampler's state as the three readings a loop shows; none without it."""
    if not res or "cpu" not in res:
        return []
    try:
        cpu = round(float(res["cpu"] or 0))                  # the sampler's first answer has no share yet: it needs two looks
    except (TypeError, ValueError):
        cpu = 0
    return [f"MAGI·1 CPU {cpu:02d}%", f"MAGI·2 RAM {res.get('mem') or ''}",
            f"MAGI·3 {str(res.get('net') or 'net').upper()} ↓{res.get('down') or ''}"]


class Travel:
    """Whether the pointer has really moved: more than LIMIT px from where it last rested. A layer that comes up
    under a resting pointer is told where it is, and a mouse on a desk that shakes moves a pixel now and then;
    neither is a hand."""

    LIMIT = 8.0      # px
    REST = 1.0       # seconds without a report: where it is seen next is where it rests

    def __init__(self):
        self.origin = self.seen = None

    def moved(self, x, y, now):
        if self.origin is None or now - self.seen > self.REST:
            self.origin = (x, y)
        self.seen = now
        return (x - self.origin[0]) ** 2 + (y - self.origin[1]) ** 2 > self.LIMIT ** 2


def outranks(new, old):
    """Whether the piece `new` may take the place of `old` on a monitor. What covers the screen takes the place of
    anything; among the rest the higher rank wins, and an equal one replaces. What is outranked is dropped."""
    return (bool(new.covers), new.rank) >= (bool(old.covers), old.rank)


class TrackWatch:
    """Which reports of the player are a new track worth a card."""

    QUIET = 1.5        # seconds after the reports begin in which one is the track that was already playing
    SETTLE = 0.4       # a title is announced once nothing more has changed for this long
    GAP = 10.0         # seconds between two cards, at least: a stream that renames itself all the time gets no more
    RECENT = 120.0     # a track announced this recently is not announced again (another player cut in and went)

    def __init__(self, now):
        self.born, self.changed = now, now
        self.seen = None           # the last report: (status, title, artist)
        self.last = None           # the (title, artist) last noted or announced
        self.said = None           # when the last card went out
        self.recent = {}           # (title, artist) -> when it was announced
        self.pending = False       # a new track is waiting for the gap to pass: ask again

    def begin(self, now):
        """The player's reports start flowing now (the daemon has finished coming up): QUIET counts from here."""
        self.born = now

    def feed(self, status, title, artist, now):
        """Every report of the player, as it comes."""
        self.seen, self.changed = (status, title, artist), now
        if title and now - self.born < self.QUIET:
            self.last = (title, artist)

    def settle(self, now):
        """(title, artist) to announce, once; None while the reports are still coming, when there is nothing new,
        and while a new track waits for the gap after the last card (`pending` then says to ask again)."""
        self.pending = False
        if self.seen is None or now - self.changed < self.SETTLE:
            return None
        status, title, artist = self.seen
        if status != "Playing" or not title:
            return None
        pair = (title, artist)
        if self.last is not None and title == self.last[0] and (artist == self.last[1] or not artist or not self.last[1]):
            if pair != self.last and artist:                 # the same track; its artist arrived late
                self.recent[pair] = self.recent.pop(self.last, now)
                self.last = pair
            return None
        announced = self.recent.get(pair)
        if announced is not None and now - announced < self.RECENT:
            self.last = pair
            return None
        if self.said is not None and now - self.said < self.GAP:
            self.pending = True
            return None
        self.recent = {p: t for p, t in self.recent.items() if now - t < self.RECENT}
        self.last, self.said, self.recent[pair] = pair, now, now
        return pair


class LockWatch:
    """What the session's lock state means for the wake cover. The daemon only watches: Hyprland says whether the
    session is locked (`hyprctl locked`), and nothing here starts, stops or waits on a locker.

    The cover may be up only while Hyprland says the session is locked. That is its whole liveness rule, so no
    mistake elsewhere can leave it on an unlocked desk for more than PATIENCE."""

    PATIENCE = 2.0     # seconds the cover may stay while Hyprland does not answer

    def __init__(self):
        self.covered = False
        self.unsure = None         # since when Hyprland has not answered, while covered

    def tick(self, now, locked):
        """`locked` is True, False, or None when Hyprland did not say. "idle" (nothing is up, nothing to do);
        "cover" (locked: put the cover up); "hold" (keep it); "play" (unlocked: the sequence runs); "drop"
        (no answer for too long: take the cover down)."""
        if not self.covered:
            if locked is True:
                self.covered, self.unsure = True, None
                return "cover"
            return "idle"
        if locked is True:
            self.unsure = None
            return "hold"
        if locked is None:
            if self.unsure is None:
                self.unsure = now
            if now - self.unsure < self.PATIENCE:
                return "hold"
        self.covered, self.unsure = False, None
        return "play" if locked is False else "drop"
