"""System tray for the bar: a StatusNotifierItem host (and watcher, when nobody else runs one).

Apps (Discord, Steam, nm-applet, ...) register with org.kde.StatusNotifierWatcher; we read their icon,
activate them on click and show their com.canonical.dbusmenu menu on right click.
"""
import glob
import io
import os

import cairo

from . import gtkutil  # noqa: F401  (pins GTK 4 before any gi.repository import)

from gi.repository import Gdk, GdkPixbuf, Gio, GLib, Gtk

WATCHER = "org.kde.StatusNotifierWatcher"
WATCHER_PATH = "/StatusNotifierWatcher"
ITEM = "org.kde.StatusNotifierItem"
MENU = "com.canonical.dbusmenu"
WATCHER_XML = f"""
<node><interface name="{WATCHER}">
  <method name="RegisterStatusNotifierItem"><arg type="s" direction="in"/></method>
  <method name="RegisterStatusNotifierHost"><arg type="s" direction="in"/></method>
  <property name="RegisteredStatusNotifierItems" type="as" access="read"/>
  <property name="IsStatusNotifierHostRegistered" type="b" access="read"/>
  <property name="ProtocolVersion" type="i" access="read"/>
  <signal name="StatusNotifierItemRegistered"><arg type="s"/></signal>
  <signal name="StatusNotifierItemUnregistered"><arg type="s"/></signal>
  <signal name="StatusNotifierHostRegistered"/>
</interface></node>"""


def split_item(spec, sender):
    """A registration string -> (bus name, object path). Apps send a bus name or just a path."""
    if spec.startswith("/"):
        return sender, spec
    if "/" in spec:
        name, _, path = spec.partition("/")
        return name, "/" + path
    return spec, "/StatusNotifierItem"


def pixmap_surface(pixmaps, size=48):
    """IconPixmap a(iiay) (ARGB32, network byte order) -> cairo surface, picking the size closest to `size`."""
    best = None
    for w, h, data in pixmaps or []:
        if w > 0 and h > 0 and len(data) >= w * h * 4:
            if best is None or (abs(w - size), -w) < (abs(best[0] - size), -best[0]):   # ties: the larger one
                best = (w, h, bytes(data))
    if not best:
        return None
    w, h, argb = best
    rgba = bytearray(len(argb))
    rgba[0::4], rgba[1::4], rgba[2::4], rgba[3::4] = argb[1::4], argb[2::4], argb[3::4], argb[0::4]
    pb = GdkPixbuf.Pixbuf.new_from_bytes(GLib.Bytes.new(bytes(rgba)), GdkPixbuf.Colorspace.RGB, True, 8, w, h, w * 4)
    return _pb_surface(pb)


def _pb_surface(pb):
    ok, buf = pb.save_to_bufferv("png", [], [])
    return cairo.ImageSurface.create_from_png(io.BytesIO(buf))


def icon_surface(name, theme_path="", size=48):
    """An icon name (or file path) -> cairo surface via the app's own folder, then the icon theme."""
    if not name:
        return None
    path = name if os.path.isabs(name) and os.path.exists(name) else None
    if not path and theme_path:
        hits = sorted(glob.glob(os.path.join(theme_path, "**", name + ".*"), recursive=True))
        path = next((h for h in hits if h.endswith((".png", ".svg"))), None)
    if not path:
        display = Gdk.Display.get_default()
        if display is None:
            return None
        theme = Gtk.IconTheme.get_for_display(display)
        if not theme.has_icon(name):
            return None
        f = theme.lookup_icon(name, None, size, 1, Gtk.TextDirection.NONE, 0).get_file()
        path = f.get_path() if f else None
    if not path:
        return None
    try:
        return _pb_surface(GdkPixbuf.Pixbuf.new_from_file_at_size(path, size, size))
    except GLib.Error:
        return None


class Tray:
    """Keeps `items` (ordered dict key -> {"icon", "title", ...}) and calls on_change() when it changes."""

    def __init__(self, on_change):
        self.on_change = on_change
        self.items = {}
        self.conn = Gio.bus_get_sync(Gio.BusType.SESSION, None)
        self.own_watcher = False
        info = Gio.DBusNodeInfo.new_for_xml(WATCHER_XML).interfaces[0]
        self.reg_id = self.conn.register_object(WATCHER_PATH, info, self._watcher_call, self._watcher_prop, None)
        Gio.bus_own_name_on_connection(self.conn, WATCHER, Gio.BusNameOwnerFlags.NONE,
                                       self._acquired, self._lost)

    # ---------------------------------------------------------------- watcher side
    def _acquired(self, conn, name):
        self.own_watcher = True
        self.conn.emit_signal(None, WATCHER_PATH, WATCHER, "StatusNotifierHostRegistered", None)

    def _lost(self, conn, name):
        if self.own_watcher or self.reg_id is None:
            return
        # someone else is the watcher: be a host and follow theirs
        self.conn.unregister_object(self.reg_id)
        self.reg_id = None
        for sig, fn in (("StatusNotifierItemRegistered", self._remote_added),
                        ("StatusNotifierItemUnregistered", self._remote_removed)):
            self.conn.signal_subscribe(WATCHER, WATCHER, sig, WATCHER_PATH, None, Gio.DBusSignalFlags.NONE, fn)
        try:
            self.conn.call_sync(WATCHER, WATCHER_PATH, WATCHER, "RegisterStatusNotifierHost",
                                GLib.Variant("(s)", (self.conn.get_unique_name(),)), None, 0, 2000, None)
            props = self.conn.call_sync(WATCHER, WATCHER_PATH, "org.freedesktop.DBus.Properties", "Get",
                                        GLib.Variant("(ss)", (WATCHER, "RegisteredStatusNotifierItems")),
                                        None, 0, 2000, None)
            for spec in props.unpack()[0]:
                self._add(*split_item(spec, ""))
        except GLib.Error:
            pass

    def _remote_added(self, conn, sender, path, iface, signal, params):
        self._add(*split_item(params.unpack()[0], ""))

    def _remote_removed(self, conn, sender, path, iface, signal, params):
        self._remove(f"{split_item(params.unpack()[0], '')[0]}{split_item(params.unpack()[0], '')[1]}")

    def _watcher_call(self, conn, sender, path, iface, method, params, invocation):
        if method == "RegisterStatusNotifierItem":
            name, obj = split_item(params.unpack()[0], sender)
            self._add(name, obj)
            self.conn.emit_signal(None, WATCHER_PATH, WATCHER, "StatusNotifierItemRegistered",
                                  GLib.Variant("(s)", (name + obj,)))
        invocation.return_value(None)

    def _watcher_prop(self, conn, sender, path, iface, prop):
        if prop == "RegisteredStatusNotifierItems":
            return GLib.Variant("as", list(self.items))
        if prop == "IsStatusNotifierHostRegistered":
            return GLib.Variant("b", True)
        if prop == "ProtocolVersion":
            return GLib.Variant("i", 0)
        return None

    # ---------------------------------------------------------------- items
    def _add(self, name, path):
        key = name + path
        if key in self.items:
            return
        item = {"name": name, "path": path, "icon": None, "title": "", "status": "Active", "menu": None,
                "is_menu": False, "watch": None, "sub": None}
        self.items[key] = item
        item["watch"] = Gio.bus_watch_name_on_connection(self.conn, name, Gio.BusNameWatcherFlags.NONE, None,
                                                         lambda c, n, k=key: self._remove(k))
        item["sub"] = self.conn.signal_subscribe(name, ITEM, None, path, None, Gio.DBusSignalFlags.NONE,
                                                 lambda *a, k=key: self._fetch(k))
        self._fetch(key)

    def _remove(self, key):
        item = self.items.pop(key, None)
        if not item:
            return
        if item["watch"]:
            Gio.bus_unwatch_name(item["watch"])
        if item["sub"]:
            self.conn.signal_unsubscribe(item["sub"])
        if self.own_watcher:
            self.conn.emit_signal(None, WATCHER_PATH, WATCHER, "StatusNotifierItemUnregistered",
                                  GLib.Variant("(s)", (key,)))
        self.on_change()

    def _fetch(self, key):
        item = self.items.get(key)
        if not item:
            return
        self.conn.call(item["name"], item["path"], "org.freedesktop.DBus.Properties", "GetAll",
                       GLib.Variant("(s)", (ITEM,)), GLib.VariantType("(a{sv})"), Gio.DBusCallFlags.NONE, 3000,
                       None, self._got_props, key)

    def _got_props(self, conn, res, key):
        try:
            props = conn.call_finish(res).unpack()[0]
        except GLib.Error:
            return
        item = self.items.get(key)
        if not item:
            return
        status = props.get("Status", "Active")
        attention = status == "NeedsAttention"
        icon = None
        name = props.get("AttentionIconName" if attention else "IconName", "") or props.get("IconName", "")
        if name:
            icon = icon_surface(name, props.get("IconThemePath", ""))
        if icon is None:
            icon = pixmap_surface(props.get("AttentionIconPixmap" if attention else "IconPixmap")
                                  or props.get("IconPixmap"))
        tip = props.get("ToolTip")
        item.update(icon=icon, status=status, menu=props.get("Menu"), is_menu=bool(props.get("ItemIsMenu")),
                    title=props.get("Title", "") or (tip[2] if tip and len(tip) > 2 else "") or props.get("Id", ""))
        self.on_change()

    def visible(self):
        """[(key, surface, title)] in registration order, without Passive items."""
        return [(k, i["icon"], i["title"]) for k, i in self.items.items() if i["status"] != "Passive"]

    # ---------------------------------------------------------------- clicks
    def _call(self, key, method, args=None):
        item = self.items.get(key)
        if item:
            self.conn.call(item["name"], item["path"], ITEM, method, args, None, Gio.DBusCallFlags.NONE, 3000,
                           None, None)

    def activate(self, key, widget, x, y):
        item = self.items.get(key)
        if item and item["is_menu"] and item["menu"]:
            self.menu(key, widget, x, y)
        else:
            self._call(key, "Activate", GLib.Variant("(ii)", (int(x), 0)))

    def secondary(self, key, x, y):
        self._call(key, "SecondaryActivate", GLib.Variant("(ii)", (int(x), 0)))

    def menu(self, key, widget, x, y):
        item = self.items.get(key)
        if not item:
            return
        if not item["menu"]:
            self._call(key, "ContextMenu", GLib.Variant("(ii)", (int(x), 0)))
            return
        name, path = item["name"], item["menu"]
        try:
            self.conn.call_sync(name, path, MENU, "AboutToShow", GLib.Variant("(i)", (0,)), None, 0, 1000, None)
        except GLib.Error:
            pass
        try:
            layout = self.conn.call_sync(name, path, MENU, "GetLayout", GLib.Variant("(iias)", (0, -1, [])),
                                         None, 0, 3000, None).unpack()[1]
        except GLib.Error:
            self._call(key, "ContextMenu", GLib.Variant("(ii)", (int(x), 0)))
            return
        group = Gio.SimpleActionGroup()
        act = Gio.SimpleAction.new("item", GLib.VariantType("i"))
        act.connect("activate", lambda a, v: self.conn.call(
            name, path, MENU, "Event", GLib.Variant("(isvu)", (v.unpack(), "clicked", GLib.Variant("i", 0), 0)),
            None, Gio.DBusCallFlags.NONE, 3000, None, None))
        group.add_action(act)
        pop = Gtk.PopoverMenu.new_from_model(menu_model(layout))
        pop.add_css_class("eva-tray-menu")
        pop.insert_action_group("tray", group)
        pop.set_has_arrow(False)
        pop.set_parent(widget)
        rect = Gdk.Rectangle()
        rect.x, rect.y, rect.width, rect.height = int(x), int(y), 1, 1
        pop.set_pointing_to(rect)
        pop.connect("closed", lambda p: GLib.idle_add(p.unparent))
        pop.popup()


def menu_model(layout):
    """A dbusmenu layout (id, props, children) -> Gio.Menu; separators start a new section."""
    menu, section = Gio.Menu(), Gio.Menu()
    for child in layout[2]:
        cid, props, kids = child
        if not props.get("visible", True):
            continue
        if props.get("type") == "separator":
            if section.get_n_items():
                menu.append_section(None, section)
            section = Gio.Menu()
            continue
        label = props.get("label", "")
        if props.get("toggle-type") in ("checkmark", "radio") and props.get("toggle-state") == 1:
            label = "✓ " + label
        if props.get("children-display") == "submenu" or kids:
            section.append_submenu(label, menu_model(child))
        else:
            it = Gio.MenuItem.new(label, None)
            if props.get("enabled", True):
                it.set_action_and_target_value("tray.item", GLib.Variant("i", cid))
            else:
                it.set_action_and_target_value("tray.disabled", None)
            section.append_item(it)
    if section.get_n_items():
        menu.append_section(None, section)
    return menu
