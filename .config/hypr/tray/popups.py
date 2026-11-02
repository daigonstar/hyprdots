"""The quick tray's other two windows, which share its process and colours: the level shown when the volume or
brightness changes, and the Alt+Tab window switcher. Running in the tray means they appear at once, with no start-up."""
import json
import subprocess
from math import pi

import cairo
import gi
gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
gi.require_version("GtkLayerShell", "0.1")
from gi.repository import Gdk, Gio, GLib, Gtk, GtkLayerShell, Pango

OSD_SECONDS = 1.4
OSD_MARGIN = 90  # up from the bottom of the screen
SWITCHER_COLUMNS = 6
SWITCHER_ROWS = 2
SWITCHER_ICON = 64
ALT_CHECK_MS = 25


def label(text="", css=None, xalign=0.0, ellipsize=False):
    w = Gtk.Label(label=text, xalign=xalign)
    if css:
        w.get_style_context().add_class(css)
    if ellipsize:
        w.set_ellipsize(Pango.EllipsizeMode.END)
    return w


class Meter(Gtk.DrawingArea):
    """A thin bar for how full something is."""

    def __init__(self):
        super().__init__()
        self.fraction, self.alarm = 0.0, False
        self.set_size_request(-1, 6)
        self.connect("draw", self._draw)

    def show_fraction(self, fraction, alarm):
        self.fraction, self.alarm = fraction, alarm
        self.queue_draw()

    def _draw(self, area, cr):
        width, height = area.get_allocated_width(), area.get_allocated_height()
        ctx = area.get_style_context()

        def bar(w, name):
            ok, c = ctx.lookup_color(name)
            cr.set_source_rgba(c.red, c.green, c.blue, c.alpha) if ok else cr.set_source_rgba(0.5, 0.5, 0.5, 1)
            r = height / 2
            cr.new_path()
            cr.arc(r, r, r, pi / 2, 3 * pi / 2)
            cr.arc(max(r, w - r), r, r, 3 * pi / 2, pi / 2)
            cr.close_path()
            cr.fill()
        bar(width, "tray_card")
        if self.fraction > 0:
            bar(max(height, width * self.fraction), "tray_attention" if self.alarm else "tray_accent")
        return False


class Osd(Gtk.Window):
    """A short-lived level: icon, bar, percent. Clicks pass straight through it."""

    def __init__(self):
        super().__init__()
        self.set_title("Quick tray level")
        self.timer = None
        GtkLayerShell.init_for_window(self)
        GtkLayerShell.set_namespace(self, "quick-tray-osd")
        GtkLayerShell.set_layer(self, GtkLayerShell.Layer.OVERLAY)
        GtkLayerShell.set_anchor(self, GtkLayerShell.Edge.BOTTOM, True)
        GtkLayerShell.set_margin(self, GtkLayerShell.Edge.BOTTOM, OSD_MARGIN)
        GtkLayerShell.set_keyboard_mode(self, GtkLayerShell.KeyboardMode.NONE)
        box = Gtk.Box(spacing=12)
        box.set_name("osd")
        self.icon = label("", "tile-icon", 0.5)
        self.meter = Meter()
        self.meter.set_valign(Gtk.Align.CENTER)
        self.meter.set_size_request(200, 6)
        self.percent = label("", "dim", 1.0)
        self.percent.set_width_chars(4)
        box.pack_start(self.icon, False, False, 0)
        box.pack_start(self.meter, True, True, 0)
        box.pack_start(self.percent, False, False, 0)
        self.add(box)
        box.show_all()
        self.connect("map", lambda _w: self.input_shape_combine_region(cairo.Region()))

    def flash(self, icon, percent, muted=False):
        self.icon.set_text(icon)
        self.meter.show_fraction(0 if muted else min(percent, 100) / 100, False)
        self.percent.set_text("Muted" if muted else f"{percent}%")
        if self.timer:
            GLib.source_remove(self.timer)
        self.show()  # on whichever screen you are on, as it is placed anew each time
        self.timer = GLib.timeout_add(int(OSD_SECONDS * 1000), self._done)

    def _done(self):
        self.timer = None
        self.hide()
        return False


def desktop_icon(desktop_id):
    try:
        return Gio.DesktopAppInfo.new(desktop_id).get_icon()
    except TypeError:  # how this binding says there is no such file
        return None


def app_icon(window_class, cache={}):
    """The icon of the app a window belongs to. Window classes are not always the name of its desktop file."""
    if window_class not in cache:
        found = desktop_icon(f"{window_class}.desktop") or desktop_icon(f"{window_class.lower()}.desktop")
        if not found:
            for group in Gio.DesktopAppInfo.search(window_class)[:1]:
                found = desktop_icon(group[0])
        if not found and Gtk.IconTheme.get_default().has_icon(window_class.lower()):
            found = Gio.ThemedIcon.new(window_class.lower())
        cache[window_class] = found or Gio.ThemedIcon.new("application-x-executable")
    return cache[window_class]


def open_windows():
    """Normal windows on every screen, most recently used first. Scratch workspaces are left out: they have keys of their own."""
    try:
        clients = json.loads(subprocess.run(["hyprctl", "clients", "-j"], capture_output=True, text=True, timeout=2).stdout)
    except (OSError, subprocess.SubprocessError, ValueError):
        return []
    usable = [c for c in clients if c.get("mapped") and not c.get("hidden") and not c["workspace"]["name"].startswith("special")]
    return sorted(usable, key=lambda c: c["focusHistoryID"])


class Switcher(Gtk.Window):
    """Alt+Tab. Hyprland's keybind tells the tray each time Tab is pressed (see step). Letting go of Alt picks the
    highlighted window, which this has to check for itself: the release may come before this window has the keyboard."""

    def __init__(self):
        super().__init__()
        self.set_title("Quick tray switcher")
        self.windows, self.buttons, self.at = [], [], 0
        self.has_keyboard = False
        self.watch = None
        GtkLayerShell.init_for_window(self)
        GtkLayerShell.set_namespace(self, "quick-tray-switcher")
        GtkLayerShell.set_layer(self, GtkLayerShell.Layer.OVERLAY)
        GtkLayerShell.set_keyboard_mode(self, GtkLayerShell.KeyboardMode.EXCLUSIVE)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        box.set_name("switcher")
        self.grid = Gtk.Grid(column_spacing=6, row_spacing=6)
        self.grid.set_halign(Gtk.Align.CENTER)
        self.title_label = label("", "host", 0.5, ellipsize=True)
        self.title_label.set_max_width_chars(50)
        box.pack_start(self.grid, False, False, 0)
        box.pack_start(self.title_label, False, False, 0)
        self.add(box)
        box.show_all()
        self.connect("key-press-event", self._key)
        self.connect("focus-in-event", self._focused)

    def alt_held(self):
        state = Gdk.Keymap.get_for_display(self.get_display()).get_modifier_state()
        return bool(state & Gdk.ModifierType.MOD1_MASK)

    def step(self, direction):
        """Tab with Alt held: opens on the window you used before this one, then moves along."""
        if self.get_visible():
            self._select((self.at + direction) % len(self.windows))
            return
        self.windows = open_windows()[:SWITCHER_COLUMNS * SWITCHER_ROWS]
        if len(self.windows) < 2:
            return
        for child in self.grid.get_children():
            self.grid.remove(child)
        self.buttons = []
        for i, window in enumerate(self.windows):
            button = Gtk.Button()
            button.get_style_context().add_class("switch-item")
            image = Gtk.Image.new_from_gicon(app_icon(window["class"]), Gtk.IconSize.DIALOG)
            image.set_pixel_size(SWITCHER_ICON)
            button.add(image)
            button.connect("clicked", lambda _b, n=i: self._pick(n))
            self.grid.attach(button, i % SWITCHER_COLUMNS, i // SWITCHER_COLUMNS, 1, 1)
            self.buttons.append(button)
        self.grid.show_all()
        self._select(direction % len(self.windows))
        self.has_keyboard = False
        self.show()
        self.watch = GLib.timeout_add(ALT_CHECK_MS, self._check_alt)

    def _select(self, index):
        self.at = index
        for i, button in enumerate(self.buttons):
            ctx = button.get_style_context()
            (ctx.add_class if i == index else ctx.remove_class)("on")
        window = self.windows[index]
        self.title_label.set_text(f"{window['title'] or window['class']}  ·  workspace {window['workspace']['name']}")

    def _focused(self, *_args):
        self.has_keyboard = True
        return False

    def _check_alt(self):
        if self.has_keyboard and not self.alt_held():
            self.watch = None
            self._pick(self.at)
            return False
        return True

    def _pick(self, index):
        address = self.windows[index]["address"]
        self.cancel()
        subprocess.Popen(["hyprctl", "dispatch", f'hl.dsp.focus({{ window = "address:{address}" }})'], stdout=subprocess.DEVNULL)

    def cancel(self):
        if self.watch:
            GLib.source_remove(self.watch)
            self.watch = None
        self.hide()

    def _key(self, _w, event):
        key = event.keyval
        if key == Gdk.KEY_Escape:
            self.cancel()
        elif key in (Gdk.KEY_Right, Gdk.KEY_Down):
            self._select((self.at + 1) % len(self.windows))
        elif key in (Gdk.KEY_Left, Gdk.KEY_Up):
            self._select((self.at - 1) % len(self.windows))
        elif key == Gdk.KEY_Return:
            self._pick(self.at)
        return True
