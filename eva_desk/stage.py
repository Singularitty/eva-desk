"""Stage: the per-monitor layer behind windows (bottom layer) that shows the figure scenes, plus the
overlay layer that plays the impact frames on top of everything."""
import concurrent.futures
import math
import time

from . import gtkutil  # noqa: F401  (pins GTK 4 before any gi.repository import)

from gi.repository import GLib, Gtk

from . import draw as d
from . import scenes as S
from .gtkutil import layer_window, point, rect, render_texture, tint_matrix

_pool = concurrent.futures.ThreadPoolExecutor(max_workers=1, thread_name_prefix="eva-render")


class _View(Gtk.Widget):
    """Paints whatever the owner's snapshot callback draws."""

    def __init__(self, painter):
        super().__init__()
        self.painter = painter
        self.set_hexpand(True)
        self.set_vexpand(True)

    def do_snapshot(self, snap):
        self.painter(snap, self.get_width(), self.get_height())


class Stage:
    """Scenes for one monitor. `scene` is None, "figure" or "herald"."""

    def __init__(self, app, gdk_monitor, connector, cfg):
        self.cfg = cfg
        self.connector = connector
        self.rig = S.HeraldRig()
        self.scene = None
        self.tex = {}                 # (name, w, h) -> texture
        self.pending = set()
        self.theta = None             # herald arm angle while shown
        self.anim, self.anim_ms, self.anim_start, self.anim_t = None, 1, None, 1.0
        self.tick_id = None
        self.win = layer_window(app, gdk_monitor, "bottom", "eva-stage")
        self.view = _View(self._paint)
        self.win.set_child(self.view)
        self.flash = layer_window(app, gdk_monitor, "overlay", "eva-flash")
        self.flash_view = _View(self._paint_flash)
        self.flash.set_child(self.flash_view)
        self.flash_frames = []
        self.flash_tex = None
        geo = gdk_monitor.get_geometry()
        self.w, self.h = geo.width, geo.height
        self.scale = max(1, gdk_monitor.get_scale_factor())
        self.berserk = False

    def set_berserk(self, on):
        if on != self.berserk:
            self.berserk = bool(on)
            self.drop(keep=("glow",))
            self.view.queue_draw()

    # ---------------------------------------------------------------- geometry + textures
    def geometry(self, figure):
        from .config import stage_share
        frac = {"figure": stage_share(self.cfg, self.w, self.h)}.get(figure, 0)
        s = self.scale
        return S.Geometry(self.w * s, self.h * s, self.w * s * float(frac))

    def _build(self, name):
        if name == "figure_back":
            g = self.geometry("figure")
            hot = self.berserk
            return lambda cr: S.figure_back(cr, g, hot=hot), g
        if name == "glow":
            return lambda cr: S.glow(cr, 512), S.Geometry(512, 512, 0)
        if name == "herald_back":
            g = self.geometry(None)
            hot = self.berserk
            return lambda cr: S.herald_backdrop(cr, g, hot=hot), g
        raise KeyError(name)

    def texture(self, name, wait=False):
        """Rendered texture for a scene/frame; renders off the main loop unless `wait`."""
        key = (name, self.w, self.h, self.scale, self.berserk)
        if key in self.tex:
            return self.tex[key]
        fn, g = self._build(name)
        if wait:
            self.tex[key] = render_texture(g.w, g.h, fn)
            return self.tex[key]
        if key not in self.pending:
            self.pending.add(key)

            def done(fut):
                def store():
                    self.pending.discard(key)
                    try:
                        surf = fut.result()
                    except Exception as e:                       # keep running, show nothing
                        print("eva-desk: render failed", name, e, flush=True)
                        return False
                    from .gtkutil import texture
                    self.tex[key] = texture(surf)
                    self.view.queue_draw()
                    return False
                GLib.idle_add(store)
            _pool.submit(_render_surface, g.w, g.h, fn).add_done_callback(done)
        return None

    def prepare(self, figure):
        """Warm the textures a workspace will need so its entrance starts at once."""
        for name in {"figure": ("figure_back", "glow")}.get(figure, ()):
            self.texture(name)

    def drop(self, keep=()):
        for key in list(self.tex):
            if key[0] not in keep:
                del self.tex[key]

    # ---------------------------------------------------------------- scenes
    def show(self, scene, impact=False, herald_fresh=False):
        if scene == self.scene and not impact and not herald_fresh:
            return
        self.scene = scene
        if scene is None:
            self._stop_anim()
            self.win.set_visible(False)
            self.drop(keep=("figure_back", "glow"))         # the figure's backdrop stays warm; the rest goes
            return
        f = self.cfg["figures"]
        if scene == "herald":
            self.drop(keep=("herald_back",))
            self.texture("herald_back", wait=True)
            if herald_fresh:
                self._start_anim("herald", f["herald_ms"])
            else:
                self._stop_anim()
        elif scene == "figure":
            self.drop(keep=("figure_back", "glow"))
            self.texture("figure_back", wait=True)
            self.texture("glow", wait=True)
            if impact:
                self._start_anim("figure", f.get("figure_entry_ms", 450))   # smooth, behind the windows
            else:
                self._stop_anim()
        else:
            self._stop_anim()
        self.win.set_visible(True)
        self.view.queue_draw()

    def _start_anim(self, kind, ms):
        self._stop_anim()
        self.anim, self.anim_ms, self.anim_start, self.anim_t = kind, max(1, int(ms)), None, 0.0
        self.tick_id = self.view.add_tick_callback(self._tick)

    def _stop_anim(self):
        if self.tick_id is not None:
            self.view.remove_tick_callback(self.tick_id)
            self.tick_id = None
        self.anim, self.anim_t = None, 1.0

    def _tick(self, widget, clock):
        now = clock.get_frame_time() / 1e6
        if self.anim_start is None:
            self.anim_start = now
        self.anim_t = min(1.0, (now - self.anim_start) * 1000 / self.anim_ms)
        widget.queue_draw()
        if self.anim_t >= 1.0:
            self.tick_id, self.anim = None, None
            return GLib.SOURCE_REMOVE
        return GLib.SOURCE_CONTINUE

    def _progress(self, kind):
        return self.anim_t if getattr(self, "anim", None) == kind else 1.0

    # ---------------------------------------------------------------- painting
    def _paint(self, snap, w, h):
        if self.scene == "figure":
            self._paint_figure(snap, w, h, self._progress("figure"))
        elif self.scene == "herald":
            t = self._progress("herald")
            tex = self.texture("herald_back")
            if tex:
                a = S.ease_out_cubic(min(1.0, t * 3))           # the backdrop fades in behind the window
                if a < 1:
                    snap.push_opacity(a)
                snap.append_texture(tex, rect(0, 0, w, h))
                if a < 1:
                    snap.pop()
            self.theta = self.rig.theta(t)
            self._paint_herald(snap, w, h)

    def _paint_figure(self, snap, w, h, t):
        p = S.figure_entry(t)
        from .config import stage_share
        g = S.Geometry(w, h, w * stage_share(self.cfg, self.w, self.h))
        surf, x, y, bw, bh, cx, cy = g.figure()
        back = self.texture("figure_back")
        if back:
            snap.save()
            snap.translate(point(cx, cy))
            snap.scale(p["back_scale"], p["back_scale"])
            snap.translate(point(-cx, -cy))
            if p["back_alpha"] < 1:
                snap.push_opacity(p["back_alpha"])
            snap.append_texture(back, rect(0, 0, w, h))
            if p["back_alpha"] < 1:
                snap.pop()
            snap.restore()
        glow = self.texture("glow")
        if glow and p["glow"] > 0.001:
            gs = h * 1.1
            snap.push_opacity(p["glow"])
            snap.append_texture(glow, rect(cx - gs / 2, cy - gs / 2, gs, gs))
            snap.pop()
        tex = self._piece_tex(surf)
        sc, dx = p["fig_scale"], p["fig_dx"] * h
        fw, fh = bw * sc, bh * sc
        fx, fy = cx - fw / 2 + dx, h - fh
        echo = 18 * h / 720 * p["echo"]
        if p["fig_alpha"] < 1:
            snap.push_opacity(p["fig_alpha"])
        echo_col = d.LED if self.berserk else d.ECHO
        for off, alpha, tint in ((2 * echo, 0.45, echo_col), (echo, 1.0, echo_col), (0, 1.0, None)):
            if tint:
                snap.push_color_matrix(*tint_matrix(tint))
            if alpha < 1:
                snap.push_opacity(alpha)
            snap.append_texture(tex, rect(fx + off, fy, fw, fh))
            if alpha < 1:
                snap.pop()
            if tint:
                snap.pop()
        if p["fig_alpha"] < 1:
            snap.pop()

    def _paint_herald(self, snap, w, h):
        g = S.Geometry(w, h, 0)
        k, ox, oy = self.rig.place(g)
        echo = 18 * h / 720
        pieces = [(self._piece_tex(s), piv, ang) for s, piv, ang in self.rig.pieces(self.theta or self.rig.theta(1.0))]

        def figure():
            for tex, piv, ang in pieces:
                snap.save()
                snap.translate(point(ox, oy))
                snap.scale(k, k)
                if piv:
                    snap.translate(point(piv[0], piv[1]))
                    snap.rotate(ang)
                    snap.translate(point(-piv[0], -piv[1]))
                snap.append_texture(tex, rect(0, 0, tex.get_width(), tex.get_height()))
                snap.restore()

        echo_col = d.LED if self.berserk else d.ECHO
        for dx, alpha, tint in ((2 * echo, 0.45, echo_col), (echo, 1.0, echo_col), (0, 1.0, None)):
            snap.save()
            snap.translate(point(dx, 0))
            if tint:
                snap.push_color_matrix(*tint_matrix(tint))
            if alpha < 1:
                snap.push_opacity(alpha)
            figure()
            if alpha < 1:
                snap.pop()
            if tint:
                snap.pop()
            snap.restore()

    _piece_cache = {}

    def _piece_tex(self, surf):
        from .gtkutil import texture
        key = id(surf)
        if key not in self._piece_cache:
            self._piece_cache[key] = texture(surf)
        return self._piece_cache[key]

    # ---------------------------------------------------------------- impact frames
    def play_flash(self, frames):
        """frames: [(texture name, ms)] shown on the overlay layer, then hidden."""
        self.flash_frames = list(frames)
        self._next_flash()
        # safety: whatever happens, the overlay never outlives the flash
        GLib.timeout_add(1500, self._flash_off)

    def _flash_off(self):
        self.flash_frames = []
        self.flash_tex = None
        self.flash.set_visible(False)
        return False

    def _next_flash(self):
        if not self.flash_frames:
            return self._flash_off()
        name, ms = self.flash_frames.pop(0)
        try:
            self.flash_tex = self.texture(name, wait=True)
        except Exception as e:
            print("eva-desk: flash frame failed", name, e, flush=True)
            return self._flash_off()
        self.flash.set_visible(True)
        self.flash_view.queue_draw()
        GLib.timeout_add(ms, self._next_flash)
        return False

    def _paint_flash(self, snap, w, h):
        if self.flash_tex:
            snap.append_texture(self.flash_tex, rect(0, 0, w, h))

    def destroy(self):
        self._stop_anim()
        self.win.destroy()
        self.flash.destroy()


def _render_surface(w, h, fn):
    import cairo
    surf = cairo.ImageSurface(cairo.FORMAT_ARGB32, int(w), int(h))
    fn(cairo.Context(surf))
    surf.flush()
    return surf
