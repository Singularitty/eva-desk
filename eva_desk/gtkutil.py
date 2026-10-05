"""GTK4 + layer-shell helpers. Import only after libgtk4-layer-shell has been loaded (see __main__)."""
import cairo
import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
gi.require_version("Gtk4LayerShell", "1.0")
gi.require_version("Graphene", "1.0")
from gi.repository import Gdk, GLib, Graphene, Gtk  # noqa: E402
from gi.repository import Gtk4LayerShell as LS  # noqa: E402

LAYER = {"background": LS.Layer.BACKGROUND, "bottom": LS.Layer.BOTTOM, "top": LS.Layer.TOP, "overlay": LS.Layer.OVERLAY}
EDGES = {"top": LS.Edge.TOP, "bottom": LS.Edge.BOTTOM, "left": LS.Edge.LEFT, "right": LS.Edge.RIGHT}

_css_done = False


def _transparent_css():
    global _css_done
    if _css_done:
        return
    prov = Gtk.CssProvider()
    from .config import current_theme
    c, f = current_theme()["colors"], current_theme()["fonts"]
    prov.load_from_string(
        "window.eva-layer, window.eva-layer > * { background: transparent; }"
        # tray menus: ink slab, bone outline, hard claret shadow, square
        f"popover.eva-tray-menu > contents {{ background: #{c['ink']}; color: #{c['bone']}; border: 2px solid #{c['bone']};"
        f" border-radius: 0; box-shadow: 6px 6px 0 0 #{c['claret']}; padding: 4px; }}"
        "popover.eva-tray-menu modelbutton { border-radius: 0; padding: 4px 12px; min-height: 24px; }"
        f"popover.eva-tray-menu modelbutton:hover {{ background: #{c['claret']}; color: #{c['bone']}; }}"
        f"popover.eva-tray-menu modelbutton:disabled {{ color: #{c['dim']}; }}"
        f"popover.eva-tray-menu separator {{ background: #{c['ink4']}; margin: 4px 0; }}"
        f"popover.eva-tray-menu label {{ font-family: '{f['body']}'; font-size: 13px; }}")
    Gtk.StyleContext.add_provider_for_display(Gdk.Display.get_default(), prov, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
    _css_done = True


def layer_window(app, monitor, layer, namespace, anchors=("top", "bottom", "left", "right"), exclusive=-1,
                 keyboard="none", passthrough=True, height=None):
    _transparent_css()
    win = Gtk.Window(application=app)
    win.add_css_class("eva-layer")
    win.set_decorated(False)
    LS.init_for_window(win)
    LS.set_layer(win, LAYER[layer])
    LS.set_namespace(win, namespace)
    if monitor is not None:
        LS.set_monitor(win, monitor)
    for e in anchors:
        LS.set_anchor(win, EDGES[e], True)
    LS.set_exclusive_zone(win, exclusive)
    LS.set_keyboard_mode(win, {"none": LS.KeyboardMode.NONE, "exclusive": LS.KeyboardMode.EXCLUSIVE,
                               "on_demand": LS.KeyboardMode.ON_DEMAND}[keyboard])
    if height:
        win.set_default_size(-1, height)
    if passthrough:
        def on_realize(w):
            surf = w.get_surface()
            if surf:
                surf.set_input_region(cairo.Region())
        win.connect("realize", on_realize)
    return win


def monitors():
    """{connector: Gdk.Monitor} for the current display."""
    out = {}
    model = Gdk.Display.get_default().get_monitors()
    for i in range(model.get_n_items()):
        m = model.get_item(i)
        out[m.get_connector()] = m
    return out


def texture(surf):
    """cairo ARGB32 image surface -> Gdk.MemoryTexture (copies the pixels)."""
    surf.flush()
    data = GLib.Bytes.new(bytes(surf.get_data()))
    return Gdk.MemoryTexture.new(surf.get_width(), surf.get_height(), Gdk.MemoryFormat.B8G8R8A8_PREMULTIPLIED,
                                 data, surf.get_stride())


def render_texture(w, h, fn):
    surf = cairo.ImageSurface(cairo.FORMAT_ARGB32, int(w), int(h))
    fn(cairo.Context(surf))
    return texture(surf)


def rect(x, y, w, h):
    return Graphene.Rect().init(x, y, w, h)


def point(x, y):
    return Graphene.Point().init(x, y)


def tint_matrix(rgba):
    """Colour matrix that paints everything `rgba` (keeps alpha): out = M*in + offset, unpremultiplied."""
    m = Graphene.Matrix().init_from_float([0, 0, 0, 0,
                                           0, 0, 0, 0,
                                           0, 0, 0, 0,
                                           0, 0, 0, 1])
    off = Graphene.Vec4().init(rgba[0], rgba[1], rgba[2], 0)
    return m, off
