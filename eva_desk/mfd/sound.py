"""The sound panel: outputs, inputs, app streams and recordings on four MFD screens with level
bars, and a fifth screen of quick toggles (do-not-disturb, night light, the power profile).

Three layers, so everything but the window can be tested headless:
  SoundModel     GTK-free state: the rows, the selection, and `action()` turning a key into the
                 list of `audio` calls to make (it never makes them itself).
  draw_sound     pure cairo: paints the screens from a model, returns the hit map and the
                 section rectangles the CRT snap staggers.
  SoundControls  the panel's behaviour minus GTK: open/close, routing keys, clicks and scrolls
                 into the model and running the calls. `SoundPanel` is SoundControls on top of
                 the GTK `Panel`, built on first use so importing this module never pulls in Gtk.

House rule: nothing flashes, nothing changes colour on a beat. Bars move, that's all.
"""
from .. import draw as d
from ..sources import audio
from . import widgets as W

# (key, kanji title, english tag, the level-bar colour role, what an empty list says)
SECTIONS = (
    ("sinks", "出力", "OUTPUT · SINKS", "claret", "NO OUTPUTS"),
    ("sources", "入力", "INPUT · SOURCES", "ink5", "NO INPUTS"),
    ("apps", "配信", "STREAMS · APPS", "claret", "NO STREAMS"),
    ("recs", "収録", "RECORDING · RECS", "ink5", "NOTHING RECORDING"),
    ("quick", "切替", "QUICK · TOGGLES", None, ""),
)
KIND = {"sinks": "sink", "sources": "source", "apps": "sink-input", "recs": "source-output"}
LEVEL_KEY = {"sinks": "sink", "sources": "source", "apps": "app", "recs": "rec"}
QUICK = (("dnd", "DO NOT DISTURB", "DND"), ("night", "NIGHT LIGHT", "NIGHT"), ("power", "POWER", "POWER"))
POWER_KEYS = ("BALANCED", "POWER", "SAVER")
POWER_PROFILES = ("balanced", "performance", "power-saver")
POWER_NEXT = {"performance": "balanced", "balanced": "power-saver"}   # audio-quick's cycle; else -> performance
STEP = 5


def _frac(volume):
    """A 0..100 (or louder) volume as a 0..1 bar value."""
    try:
        return max(0.0, min(1.0, float(volume) / 100))
    except (TypeError, ValueError):
        return 0.0


class SoundModel:
    """The panel's state. `sections` follows `SECTIONS`; `sel` is (section, row) and always
    points at a real row (the quick section is never empty). `picker`, when not None, is the
    highlighted device in the move-to picker of the selected stream row.

    Rows show what the listener last reported: an action never writes a row's volume, mute,
    default or device. A volume step does remember its target in `pending` ((kind, id) -> 0..100)
    so held keys and fast scrolls build on the last step sent, until `levels()` reports that row.
    Only the quick toggles, which no listener reports, are flipped locally."""

    def __init__(self, state, quick):
        state = state or {}
        self.quick = {"dnd": False, "night": False, "power": "unknown", **(quick or {})}
        self.sections = []
        self.reported = set()           # (kind, id) of rows whose volume the state carried
        for key, title, eng, _, _ in SECTIONS:
            if key == "quick":
                rows = [self._quick_row(k, label) for k, label, _ in QUICK]
            else:
                src = state.get(key) or []
                make = self._device_row if key in ("sinks", "sources") else self._stream_row
                rows = [make(key, item) for item in src]
                self.reported |= {(r["kind"], r["id"]) for r, item in zip(rows, src) if "volume" in item}
            self.sections.append({"key": key, "title": title, "eng": eng, "rows": rows})
        self.pending = {}
        self.picker = None
        self.sel = self.clamp((0, 0))

    def rebuild(self, state):
        """A new model for a fresh layout (an `audiostate --struct` line, which carries no volume
        or mute), keeping what the layout line can't know: each surviving row's value and mute
        (unless the line did carry them), the pending steps, the quick state, and the selection and
        open picker by row identity -- falling back to the clamped index when the row is gone."""
        new = SoundModel(state, self.quick)
        old_rows = {(r["kind"], r["id"]): r for sec in self.sections for r in sec["rows"]}
        for sec in new.sections:
            for r in sec["rows"]:
                ident = (r["kind"], r["id"])
                old = old_rows.get(ident)
                if old is not None and ident not in new.reported:
                    r["value"], r["muted"] = old["value"], old["muted"]
        new.pending = {k: v for k, v in self.pending.items() if k in old_rows}
        cur = self.row()
        where = {(r["kind"], r["id"]): (s, i) for s, sec in enumerate(new.sections) for i, r in enumerate(sec["rows"])}
        found = where.get((cur["kind"], cur["id"]))
        new.sel = found if found is not None else new.clamp(self.sel)
        if found is not None and self.picker is not None:
            old_devs, devs = self.targets(), new.targets()
            if devs:
                was = old_devs[self.picker]["target"] if self.picker < len(old_devs) else None
                new.picker = next((i for i, dev in enumerate(devs) if dev["target"] == was),
                                  min(self.picker, len(devs) - 1))
        return new

    # ---------------------------------------------------------------- rows
    @staticmethod
    def _device_row(key, dev):
        return {"kind": KIND[key], "id": dev.get("id"), "label": dev.get("friendly") or dev.get("short") or "",
                "sub": str(dev.get("sub", "")).upper(), "value": _frac(dev.get("volume")),
                "muted": bool(dev.get("muted")), "default": bool(dev.get("default")), "target": dev.get("name", ""),
                "short": dev.get("short") or dev.get("friendly") or ""}

    @staticmethod
    def _stream_row(key, st):
        title = st.get("title") or ""
        label = f"{st.get('app', '')} · {title}" if title else st.get("app", "")
        arrow = "→" if key == "apps" else "←"
        sub = f"{arrow} {str(st.get('dev_short', '')).upper()}" + (" · PAUSED" if st.get("corked") else "")
        return {"kind": KIND[key], "id": st.get("index"), "label": label, "sub": sub,
                "value": _frac(st.get("volume")), "muted": bool(st.get("muted")), "default": False,
                "target": st.get("sink" if key == "apps" else "source", "")}

    @staticmethod
    def _quick_row(key, label):
        return {"kind": "quick", "id": key, "label": label, "sub": "", "value": None, "muted": False,
                "default": False, "target": ""}

    def row(self, sel=None):
        s, r = self.sel if sel is None else sel
        return self.sections[s]["rows"][r]

    def _flat(self):
        return [(s, r) for s, sec in enumerate(self.sections) for r in range(len(sec["rows"]))]

    def clamp(self, sel):
        """`sel` if it is a real row, else the nearest row in that section, else the first row of
        the next non-empty section (wrapping; the quick section always has rows)."""
        s, r = sel
        s = max(0, min(len(self.sections) - 1, s))
        n = len(self.sections)
        for i in range(n):
            rows = self.sections[(s + i) % n]["rows"]
            if rows:
                return ((s + i) % n, max(0, min(len(rows) - 1, r)) if i == 0 else 0)
        return (n - 1, 0)

    # ---------------------------------------------------------------- live updates
    def levels(self, levels_json):
        """Apply one `audiostate --levels` line ({"sink50": {"v": 68, "m": false}, ...}) in place."""
        for sec in self.sections:
            prefix = LEVEL_KEY.get(sec["key"])
            if not prefix:
                continue
            for row in sec["rows"]:
                lv = levels_json.get(f"{prefix}{row['id']}")
                if isinstance(lv, dict):
                    self.pending.pop((row["kind"], row["id"]), None)
                    if "v" in lv:
                        row["value"] = _frac(lv["v"])
                    if "m" in lv:
                        row["muted"] = bool(lv["m"])

    # ---------------------------------------------------------------- selection
    def move(self, dy):
        """Move the selection `dy` rows, flowing across sections (empty ones are skipped)."""
        flat = self._flat()
        i = flat.index(self.sel) if self.sel in flat else 0
        self.sel = flat[max(0, min(len(flat) - 1, i + dy))]
        self.picker = None

    def move_section(self, step):
        """Jump to the first row of the next (step > 0) or previous non-empty section, wrapping."""
        n = len(self.sections)
        s = self.sel[0]
        for _ in range(n):
            s = (s + (1 if step > 0 else -1)) % n
            if self.sections[s]["rows"]:
                self.sel = (s, 0)
                break
        self.picker = None

    # ---------------------------------------------------------------- actions -> audio calls
    def _set(self, row, volume):
        volume = max(0, min(100, int(volume)))
        self.pending[(row["kind"], row["id"])] = volume
        return [("set_volume", row["kind"], row["id"], volume)]

    def action(self, name):
        """The audio calls for one named action on the selection (see the module docstring)."""
        if name in ("up", "down"):
            self.move(-1 if name == "up" else 1)
            return []
        if name in ("next_section", "prev_section"):
            self.move_section(1 if name == "next_section" else -1)
            return []
        if name in ("dnd", "night", "power"):
            if name == "power":
                self.quick["power"] = POWER_NEXT.get(self.quick.get("power"), "performance")
            else:
                self.quick[name] = not self.quick.get(name)
            return [("quick_toggle", name)]
        row = self.row()
        if row["kind"] == "quick":
            return []
        if name in ("left", "right"):
            step = STEP if name == "right" else -STEP
            base = self.pending.get((row["kind"], row["id"]), round(row["value"] * 100))
            return self._set(row, base + step)
        if name == "mute":
            return [("toggle_mute", row["kind"], row["id"])]
        if name == "default":
            if row["kind"] not in ("sink", "source"):
                return []
            return [("set_default", row["kind"], row["target"])]
        return []

    def targets(self):
        """The device rows the selected stream can move to ([] when the selection isn't a stream)."""
        kind = self.row()["kind"]
        if kind == "sink-input":
            return self.sections[0]["rows"]
        if kind == "source-output":
            return self.sections[1]["rows"]
        return []

    def open_picker(self):
        """Open the move-to picker on the selected stream, highlighting its current device."""
        devs = self.targets()
        if not devs:
            return False
        cur = self.row()["target"]
        self.picker = next((i for i, dev in enumerate(devs) if dev["target"] == cur), 0)
        return True

    def pick(self, index):
        """Move the selected stream to device `index` of its picker; closes the picker."""
        devs = self.targets()
        self.picker = None
        if not 0 <= index < len(devs):
            return []
        row = self.row()
        return [("move", row["kind"], row["id"], devs[index]["target"])]

    def set_from_bar(self, section, row, frac):
        """A click on a level bar: select that row and set its volume to the clicked fraction."""
        self.sel, self.picker = (section, row), None
        target = self.row()
        if target["kind"] == "quick":
            return []
        return self._set(target, round(max(0.0, min(1.0, frac)) * 100))


# ---------------------------------------------------------------- drawing
ROW_H = 40
GAP = 8
PICK_H = 26 + 10            # a key row (26) and its breathing room
QUICK_CONTENT = 34


def _screen_extra(cr):
    """What a `W.screen` takes around its content: bezel, padding and the tag line (measured with
    a kanji in it, as every tag here has -- the fallback CJK font sets a taller line)."""
    tag_h = d.text_size(d.layout(cr, f"{SECTIONS[0][1]} · {SECTIONS[0][2]}", d.F_META, 11, spacing=3))[1]
    return 2 * W.BEZEL_W + 2 * W.PAD + tag_h


def _display_sub(row):
    sub = row["sub"]
    if row["default"]:
        sub = "DEFAULT · " + sub if sub else "DEFAULT"
    if row["muted"]:
        sub = sub + " · MUTED" if sub else "MUTED"
    return sub


def _picker_keys(cr, model):
    labels = [f"{i + 1} {str(dev['short']).upper()}" for i, dev in enumerate(model.targets())]
    key_w = max([d.text_size(d.layout(cr, lab, d.F_META, 12))[0] + 20 for lab in labels] + [64])
    return labels, key_w


def _list_screen(cr, x, y, w, h, s, model):
    _, title, eng, colour_role, empty = SECTIONS[s]
    sec = model.sections[s]
    active = model.sel[0] == s
    cx, cy, cw, ch = W.screen(cr, x, y, w, h, f"{title} · {eng}", hot="· ACTIVE" if active else "")
    rows = sec["rows"]
    hits = []
    if not rows:
        d.draw_text(cr, d.layout(cr, empty, d.F_META, 12, spacing=2), cx + 12, cy + 10, d.col("dim"))
        return hits
    colour = d.CLARET if colour_role == "claret" else d.col(colour_role)
    picking = active and model.picker is not None and model.targets()
    pick_h = PICK_H if picking else 0
    visible = max(1, int((ch - pick_h + 0.5) // ROW_H))      # +0.5: a content-sized screen fits exactly
    sel_r = model.sel[1] if active else -1
    start = max(0, sel_r - visible + 1) if active else 0
    shown = rows[start:start + visible]
    items = [{"label": r["label"], "sub": _display_sub(r), "value": r["value"], "peak": None,
              "muted": r["muted"], "colour": colour} for r in shown]

    def put(chunk, first, top):
        for x0, y0, x1, y1, what in W.rows(cr, cx, top, cw, chunk, sel_r - start - first, row_h=ROW_H):
            if isinstance(what, tuple):
                hits.append((x0, y0, x1, y1, ("bar", s, start + first + what[1])))
            else:
                hits.append((x0, y0, x1, y1, (s, start + first + what)))

    cr.save()
    cr.rectangle(cx, cy, cw, ch)
    cr.clip()
    if picking:
        cut = sel_r - start + 1                         # the picker sits right under the selected row
        put(items[:cut], 0, cy)
        labels, key_w = _picker_keys(cr, model)
        ky = cy + cut * ROW_H + 4
        for x0, y0, x1, y1, i in W.keyrow(cr, cx + 12, ky, labels, active=model.picker, key_w=key_w):
            hits.append((x0, y0, x1, y1, i))
        put(items[cut:], cut, cy + cut * ROW_H + PICK_H)
    else:
        put(items, 0, cy)
    cr.restore()
    return hits


def _quick_screen(cr, x, y, w, h, model):
    _, title, eng, _, _ = SECTIONS[4]
    active = model.sel[0] == 4
    cx, cy, cw, ch = W.screen(cr, x, y, w, h, f"{title} · {eng}", hot="· ACTIVE" if active else "")
    hits = []
    sel_r = model.sel[1] if active else -1
    keys = [d.layout(cr, k, d.F_META, 12) for k in POWER_KEYS]
    key_w = max(d.text_size(k)[0] for k in keys) + 20
    keys_w = len(POWER_KEYS) * key_w + (len(POWER_KEYS) - 1) * 6
    lamp, lamp_gap, item_gap = 14, 10, 36

    def labels(long):
        return [d.layout(cr, f"{i + 1} {lab if long else short}", d.F_META, 13)
                for i, (_, lab, short) in enumerate(QUICK)]

    lays = labels(True)
    need = sum(d.text_size(lay)[0] for lay in lays) + 2 * (lamp + lamp_gap) + 2 * item_gap + 14 + keys_w
    if need > cw:
        lays = labels(False)
    ix = cx + 4
    for i, ((key, _, _), lay) in enumerate(zip(QUICK, lays)):
        lw, lh = d.text_size(lay)
        ly = cy + (ch - lh) / 2
        x0 = ix
        if key != "power":
            W.lamp(cr, ix, cy + (ch - lamp) / 2, lamp, bool(model.quick.get(key)))
            ix += lamp + lamp_gap
        if i == sel_r:
            d.block(cr, ix - 6, ly - 4, lw + 12, lh + 8, d.BONE)
            d.draw_text(cr, lay, ix, ly, d.INK)
        else:
            d.draw_text(cr, lay, ix, ly, d.BONE)
        ix += lw
        if key == "power":
            ix += 14
            power = model.quick.get("power")
            act = POWER_PROFILES.index(power) if power in POWER_PROFILES else -1
            for k0, k1, k2, k3, _ in W.keyrow(cr, ix, cy + (ch - 26) / 2, list(POWER_KEYS), active=act, key_w=key_w):
                hits.append((k0, k1, k2, k3, "power"))
            hits.append((x0 - 4, cy, ix, cy + ch, "power"))
        else:
            hits.append((x0 - 4, cy, ix + 6, cy + ch, key))
            ix += item_gap
    return hits


def _no_signal(cr, x, y, w, h):
    cx, cy, cw, ch = W.screen(cr, x, y, w, h, "信号 · AUDIO", hot="· LOST")
    big = d.layout(cr, "NO SIGNAL", d.F_DISPLAY, 40, weight=d.DISPLAY_WEIGHT)
    bw, bh = d.text_size(big)
    note = d.layout(cr, "AUDIOSTATE DID NOT ANSWER", d.F_META, 11, spacing=3)
    nw, nh = d.text_size(note)
    by = cy + (ch - bh - nh - 10) / 2
    d.draw_text(cr, big, cx + (cw - bw) / 2, by, d.LED)
    d.draw_text(cr, note, cx + (cw - nw) / 2, by + bh + 10, d.col("dim"))


def _fit(needs, room, floor):
    """Heights for screens wanting `needs` in `room`: all of it when it fits, else water-filling --
    every screen gets min(need, cap) for the one cap that fills `room` (never below `floor`)."""
    if sum(needs) <= room:
        return list(needs)
    cap, left = room, room
    order = sorted(needs)
    for k, n in enumerate(order):
        share = left / (len(order) - k)
        if n > share:
            cap = share
            break
        left -= n
    return [max(floor, min(n, cap)) for n in needs]


def draw_sound(cr, x, y, w, h, model, no_signal):
    """Paint the sound panel into (x, y, w, h). Returns (hits, sections): hits are
    (x0, y0, x1, y1, what) where `what` is (section, row) for a row, ("bar", section, row) for its
    level bar, an int for a key of the move-to picker, or "dnd" / "night" / "power" for the quick
    toggles; sections are the (y, h) of each screen and the gap under it, top to bottom, the
    quick screen's running on to the bottom edge so the snap covers the bare ink there too.
    The screens are sized to their content and stacked from the top; when they don't fit, the
    short lists keep their height and the long ones share what's left (see `_fit`).
    The whole rectangle is backed in `ink`, so no window shows through between the screens."""
    d.block(cr, x, y, w, h, d.INK)
    if no_signal:
        _no_signal(cr, x, y, w, h)
        return [], [(y, h)]
    extra = _screen_extra(cr)
    picking = model.picker is not None and bool(model.targets())
    needs = [extra + max(1, len(model.sections[s]["rows"])) * ROW_H + (PICK_H if picking and model.sel[0] == s else 0)
             for s in range(4)]
    quick_h = extra + QUICK_CONTENT
    heights = _fit(needs, h - quick_h - 4 * GAP, extra + ROW_H)
    hits, sections = [], []
    sy = y
    for s, sh in enumerate(heights):
        hits += _list_screen(cr, x, sy, w, sh, s, model)
        sections.append((sy, sh + GAP))
        sy += sh + GAP
    hits += _quick_screen(cr, x, sy, w, quick_h, model)
    sections.append((sy, max(quick_h, y + h - sy)))
    return hits, sections


# ---------------------------------------------------------------- the panel
KEYS = {"Up": "up", "k": "up", "Down": "down", "j": "down", "Left": "left", "h": "left", "Right": "right",
        "l": "right", "m": "mute", "d": "default", "Tab": "next_section", "ISO_Left_Tab": "prev_section",
        "1": "dnd", "2": "night", "3": "power"}


class SoundControls:
    """Everything SoundPanel does that isn't GTK. Mixed in ahead of `Panel` (see `SoundPanel`),
    so `super()` here reaches the panel base; the tests drive it bare with a fake `invalidate`."""

    name = "sound"

    def __init__(self, app, cfg):
        super().__init__(app, cfg, self.name, 1100, 1300, "left")
        self.model = SoundModel(None, audio.DEFAULT_QUICK)
        self.no_signal = True
        self.listener = None

    def place(self, gdk_monitor):
        """Size from the monitor: min(1100, 34% of its width) wide, the height under the bar
        less the panel's top and bottom margins."""
        if gdk_monitor is not None:
            geo = gdk_monitor.get_geometry()
            bar_h = int(self.cfg["bar"]["height"]) if self.cfg["bar"]["enabled"] else 0
            self.pwidth = min(1100, int(0.34 * geo.width))
            self.pheight = max(200, geo.height - bar_h - 2 * self.MARGIN)
        super().place(gdk_monitor)

    # ---------------------------------------------------------------- open / close / live state
    def on_open(self):
        state = audio.snapshot()
        self.no_signal = state is None
        self.model = SoundModel(state, audio.quick())
        self.listener = audio.Listener(self._on_struct, self._on_levels)
        self.listener.start()

    def on_close(self):
        if self.listener is not None:
            self.listener.stop()
            self.listener = None
        self.model.picker = None

    def _on_struct(self, state):
        self.model, self.no_signal = self.model.rebuild(state), False
        self.invalidate()

    def _on_levels(self, levels):
        self.model.levels(levels)
        self.invalidate()

    def _run(self, calls):
        for name, *args in calls:
            try:
                getattr(audio, name)(*args)
            except Exception as e:                      # a write must never take the panel down
                print(f"eva-desk: sound: {name}: {e}")
        self.invalidate()

    # ---------------------------------------------------------------- drawing
    def draw(self, cr, w, h):
        s = self.scale or 1
        cr.save()
        cr.scale(s, s)
        hits, sections = draw_sound(cr, 0, 0, w / s, h / s, self.model, self.no_signal)
        cr.restore()
        self.sections = [(sy * s, sh * s) for sy, sh in sections]
        return [(x0 * s, y0 * s, x1 * s, y1 * s, what) for x0, y0, x1, y1, what in hits]

    # ---------------------------------------------------------------- input
    def on_key(self, name, mods):
        m = self.model
        if self.no_signal:
            return False
        if m.picker is not None:
            n = len(m.targets())
            if name in ("Left", "h", "Right", "l") and n:
                m.picker = (m.picker + (1 if name in ("Right", "l") else -1)) % n
                self.invalidate()
                return True
            if name in ("Return", "KP_Enter"):
                self._run(m.pick(m.picker))
                return True
            if name.isdigit() and name != "0":
                self._run(m.pick(int(name) - 1))
                return True
            m.picker = None                             # anything else closes it and acts as usual
        if name in ("Return", "KP_Enter"):
            row = m.row()
            if row["kind"] == "quick":
                self._run(m.action(row["id"]))
            elif m.open_picker():
                self.invalidate()
            return True
        action = KEYS.get(name)
        if action is None:
            return False
        self._run(m.action(action))
        return True

    def _hit(self, x, y):
        for x0, y0, x1, y1, what in reversed(self.hits):     # bars and keys sit on top of rows
            if x0 <= x <= x1 and y0 <= y <= y1:
                return x0, x1, what
        return None

    def on_click(self, x, y, button):
        hit = self._hit(x, y)
        if hit is None or button != 1:
            return
        x0, x1, what = hit
        m = self.model
        if isinstance(what, str):
            self._run(m.action(what))
        elif isinstance(what, int):
            self._run(m.pick(what))
        elif what[0] == "bar":
            self._run(m.set_from_bar(what[1], what[2], (x - x0) / (x1 - x0) if x1 > x0 else 0.0))
        else:
            m.sel, m.picker = what, None
            self.invalidate()

    def on_scroll(self, x, y, dy):
        hit = self._hit(x, y)
        if hit is not None and isinstance(hit[2], tuple):
            what = hit[2]
            self.model.sel = what[1:] if what[0] == "bar" else what
        if dy:
            self._run(self.model.action("left" if dy > 0 else "right"))


def __getattr__(name):
    """`SoundPanel`, built on first use: it subclasses the GTK `Panel`, and importing this module
    must not import Gtk (the model and drawing run headless in the tests and `--render`)."""
    if name != "SoundPanel":
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    from .panel import Panel

    class SoundPanel(SoundControls, Panel):
        """The sound panel: SoundControls on the anchored MFD panel base, docked left."""

    SoundPanel.__module__ = __name__
    globals()["SoundPanel"] = SoundPanel
    return SoundPanel
