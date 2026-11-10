"""The Sound app's building blocks: its look (the Theme page's colours, through the quick tray's theme file, like the
notes window), cards, a volume row and a list to choose from that can change under it. GTK only, no sound code."""
import re
import threading
from pathlib import Path

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
from gi.repository import Gdk, Gio, GLib, Gtk, Pango

import pulse

THEME = Path(__file__).resolve().parent.parent / "tray/theme.css"
DEFAULT_COLOURS = {"tray_bg": "rgba(27,26,27,0.96)", "tray_text": "#F9F8F9", "tray_card": "rgba(128,128,128,0.18)",
                   "tray_accent": "#7aa2f7", "tray_on_accent": "#1B1A1B", "tray_muted": "#9a9a9a", "tray_attention": "#e06c75"}
VOLUME_AFTER_MS = 40  # a dragged volume slider is sent this often at most
# CSS variables, not @define-color: GTK 4.24 ignores those names here
CSS = """
window.sound { background: var(--tray_solid); color: var(--tray_text); }
window.sound label { color: var(--tray_text); }
.card { background: var(--tray_card); border-radius: 14px; padding: 12px 14px; }
.big { font-size: 2.2em; font-weight: bold; }
.title { font-size: 1.15em; font-weight: bold; }
.dim, window.sound label.dim { color: var(--tray_muted); font-size: 0.92em; }
.attention, window.sound label.attention { color: var(--tray_attention); }
.good, window.sound label.good { color: var(--tray_accent); }
.pages { padding: 10px 16px 0 16px; }
stackswitcher button { border-radius: 10px; padding: 4px 12px; background: none; border: none; box-shadow: none; }
stackswitcher button:checked { background: color-mix(in srgb, var(--tray_accent) 40%, transparent); }
stackswitcher button:hover { background: color-mix(in srgb, var(--tray_accent) 22%, transparent); }
levelbar block.filled { background: var(--tray_accent); border-radius: 6px; }
levelbar.low block.filled, levelbar.hot block.filled { background: var(--tray_attention); }
levelbar block.empty { background: color-mix(in srgb, var(--tray_text) 12%, transparent); border-radius: 6px; }
levelbar trough { min-height: 10px; }
levelbar.meter trough { min-height: 6px; }
scale trough { background: color-mix(in srgb, var(--tray_text) 14%, transparent); }
scale highlight { background: var(--tray_accent); }
scale slider { background: var(--tray_text); }
scale.eq { min-height: 150px; }
scale.eq trough { min-width: 4px; }
scale marks indicator { color: var(--tray_muted); min-height: 4px; }
switch:checked { background: var(--tray_accent); }
checkbutton check:checked { background: var(--tray_accent); color: var(--tray_on_accent); }
button { border-radius: 10px; }
button.flat { background: none; box-shadow: none; border: none; }
button.flat:hover { background: color-mix(in srgb, var(--tray_accent) 25%, transparent); }
button.muted { color: var(--tray_attention); }
.device { padding: 6px 0; }
.device.current .name { font-weight: bold; }
.band { font-size: 0.85em; }
.eq-curve { min-height: 90px; }
dropdown button { border-radius: 10px; }
expander title label { font-weight: bold; }
"""


def theme_colours():
    colours = dict(DEFAULT_COLOURS)
    try:
        text = THEME.read_text(encoding="utf-8")
    except OSError:
        return colours
    colours.update(dict(re.findall(r"@define-color\s+(\w+)\s+([^;]+);", text)))
    return colours


class Look:
    """Loads the CSS and follows the theme file, which the Settings app rewrites when the wallpaper or Theme page
    changes."""

    def __init__(self, display):
        self.theme_css, self.css = Gtk.CssProvider(), Gtk.CssProvider()
        Gtk.StyleContext.add_provider_for_display(display, self.theme_css, 800)
        Gtk.StyleContext.add_provider_for_display(display, self.css, 801)
        self.css.load_from_string(CSS)
        self.monitor = Gio.File.new_for_path(str(THEME)).monitor_file(Gio.FileMonitorFlags.NONE, None)
        self.monitor.connect("changed", lambda *_a: self.load())
        self.load()

    def load(self):
        colours = theme_colours()
        solid = Gdk.RGBA()
        solid.parse(colours["tray_bg"].strip())
        solid.alpha = 1.0
        names = {**colours, "tray_solid": solid.to_string()}
        font = ""
        try:
            found = re.search(r"font-family:\s*([^;]+);", THEME.read_text(encoding="utf-8"))
            font = f"window.sound {{ font-family: {found[1]}; }}\n" if found else ""
        except OSError:
            pass
        self.theme_css.load_from_string(":root {\n" + "".join(f"  --{k}: {v};\n" for k, v in names.items()) + "}\n" + font)


def background(job, done=None):
    """Runs job in a thread (pactl, headsetcontrol and systemctl each take a moment) and hands its result to done on
    the main loop."""
    def work():
        result = job()
        if done:
            GLib.idle_add(lambda: done(result) and False)
    threading.Thread(target=work, daemon=True).start()


def card(title, help_text=""):
    """A rounded panel with a title row (returned too, for a switch or button on the right)."""
    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10, css_classes=["card"])
    head = Gtk.Box(spacing=10)
    head.append(Gtk.Label(label=title, xalign=0, hexpand=True, css_classes=["title"]))
    box.append(head)
    if help_text:
        box.append(Gtk.Label(label=help_text, xalign=0, wrap=True, css_classes=["dim"]))
    return box, head


def page(*children):
    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12, margin_top=12, margin_bottom=16,
                  margin_start=16, margin_end=16)
    for child in children:
        box.append(child)
    return Gtk.ScrolledWindow(child=box, hscrollbar_policy=Gtk.PolicyType.NEVER, vexpand=True), box


def label(text="", *classes, wrap=False, xalign=0.0, ellipsize=False):
    widget = Gtk.Label(label=text, xalign=xalign, wrap=wrap, css_classes=list(classes))
    if ellipsize:
        widget.set_ellipsize(Pango.EllipsizeMode.END)
    return widget


class Volume(Gtk.Box):
    """A volume slider (0-153%) and a mute button. set() leaves the slider alone while you drag
    it, so a refresh never pulls it out from under your finger."""

    def __init__(self, changed, muted, microphone=False):
        super().__init__(spacing=6, hexpand=True)
        self.changed, self.muted, self.quiet, self.timer = changed, muted, False, 0
        self.icons = (("microphone-sensitivity-high-symbolic", "microphone-sensitivity-muted-symbolic") if microphone
                      else ("audio-volume-high-symbolic", "audio-volume-muted-symbolic"))
        self.scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 0, pulse.MAX_VOLUME, 1)
        self.scale.set_hexpand(True)
        self.scale.set_draw_value(True)
        self.scale.set_value_pos(Gtk.PositionType.RIGHT)
        self.scale.set_format_value_func(lambda _s, v: f"{v:.0f}%")
        self.scale.connect("value-changed", self._moved)
        self.mute = Gtk.ToggleButton(icon_name=self.icons[0], css_classes=["flat"], tooltip_text="Mute",
                                     valign=Gtk.Align.CENTER)
        self.mute.connect("toggled", self._toggled)
        self.append(self.scale)
        self.append(self.mute)

    def set(self, volume, mute):
        self.quiet = True
        if not self.timer:
            self.scale.set_value(min(pulse.MAX_VOLUME, volume))
        self.mute.set_active(mute)
        self._show_mute()
        self.quiet = False

    def _show_mute(self):
        on = self.mute.get_active()
        self.mute.set_icon_name(self.icons[on])
        (self.mute.add_css_class if on else self.mute.remove_css_class)("muted")
        self.mute.set_tooltip_text("Unmute" if on else "Mute")

    def _moved(self, scale):
        if self.quiet:
            return
        if self.timer:
            GLib.source_remove(self.timer)

        def send():
            self.timer = 0
            self.changed(round(scale.get_value()))
            return False
        self.timer = GLib.timeout_add(VOLUME_AFTER_MS, send)

    def _toggled(self, button):
        self._show_mute()
        if not self.quiet:
            self.muted(button.get_active())


class Choice(Gtk.DropDown):
    """A drop-down of (key, label) pairs that can be replaced while it is open in the UI, without firing its handler."""

    def __init__(self, chosen):
        super().__init__(model=Gtk.StringList(), hexpand=True)
        self.keys, self.chosen, self.quiet = [], chosen, False
        self.connect("notify::selected", self._picked)

    def show(self, pairs, current):
        self.quiet = True
        keys = [k for k, _l in pairs]
        if keys != self.keys or [self.get_model().get_string(i) for i in range(len(keys))] != [l for _k, l in pairs]:
            self.keys = keys
            self.set_model(Gtk.StringList.new([l for _k, l in pairs]))
        if current in self.keys:
            self.set_selected(self.keys.index(current))
        else:
            self.set_selected(Gtk.INVALID_LIST_POSITION)
        self.quiet = False

    def _picked(self, *_a):
        index = self.get_selected()
        if not self.quiet and 0 <= index < len(self.keys):
            self.chosen(self.keys[index])


class Keyed:
    """Keeps one widget per key inside a box, in order: new keys get a widget from make(), gone ones are removed, and
    the rest stay as they are (so a slider being dragged is not rebuilt)."""

    def __init__(self, box, make):
        self.box, self.make, self.rows = box, make, {}

    def show(self, keys):
        keys = list(keys)
        for key in list(self.rows):
            if key not in keys:
                self.box.remove(self.rows.pop(key))
        previous = None
        for key in keys:
            if key not in self.rows:
                self.rows[key] = self.make(key)
                self.box.insert_child_after(self.rows[key], previous)
            elif self.rows[key].get_prev_sibling() is not previous:  # the box holds only these rows
                self.box.reorder_child_after(self.rows[key], previous)
            previous = self.rows[key]
        return [self.rows[k] for k in keys]
