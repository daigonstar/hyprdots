#!/usr/bin/env python3
"""Quick tray: phone-style quick settings, a system monitor and your notifications in one panel (GTK3 + layer-shell).

It runs in the background and opens and closes with swaync's control centre, which has no window of its own: swaync
stays in charge of notifications and popups, so the bar's bell button and `swaync-client -t` still open it, and
click_away.lua closes it on a click outside. notifications.py keeps the list this panel draws.

Anything this PC does not have is left out: no Wi-Fi card, no Wi-Fi tile; battery, brightness, touchpad and airplane
mode only on a laptop. popups.py and overview.py have the volume level, Alt+Tab and Super+Tab, which run in this process too. Colours come from the settings Theme page (theme.css, see theme_parts.tray_css).
"""
import fcntl
import json
import os
import pwd
import shlex
import shutil
import signal
import socket
import subprocess
import sys
import threading
import time
from collections import deque
from math import pi
from pathlib import Path

import gi
gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
gi.require_version("GtkLayerShell", "0.1")
gi.require_version("GdkPixbuf", "2.0")
gi.require_version("GLibUnix", "2.0")
from gi.repository import Gdk, GdkPixbuf, Gio, GLib, GLibUnix, Gtk, GtkLayerShell, Pango

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import notifications  # noqa: E402
from overview import Overview  # noqa: E402
import touch_mode  # noqa: E402
from popups import Meter, Osd, Switcher, label  # noqa: E402
import sysinfo  # noqa: E402
sys.path.insert(0, str(HERE.parent / "audio"))
import headset  # noqa: E402

THEME = HERE / "theme.css"
SOUND_OFF = Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local/state")) / "quick-tray/sounds-off"
ROTATION_LOCK = Path.home() / ".local/state/hyprdots/rotation-locked"  # read by tablet_mode.py
SOUND_DIR = Path("/usr/share/sounds/freedesktop/stereo")
SOUNDLESS_APPS = ("Screenshot", "Screen recording", "Colour picker")  # they have their own sound, or you just asked for them
LOCK = Path(os.environ.get("XDG_RUNTIME_DIR", "/tmp")) / "quick-tray.lock"
SCRIPTS = "~/.config/hypr/scripts"
EDGE = 10  # from the top and right of the screen; the panel's own 10px margin (room for its shadow) comes on top
WIDTH = 400
SAMPLE_SECONDS = 2
HISTORY = 60  # samples on each graph: two minutes
ATTENTION_DISK = 90
ATTENTION_BATTERY = 15
HEADSET_SECONDS = 60  # how often the headset is asked: headsetcontrol talks to it over the radio
SOUND_APP = "~/.config/hypr/audio/audio.sh"

ICON = {
    "wifi": "\U000f05a9", "wifi_off": "\U000f05aa", "ethernet": "\U000f0200", "bluetooth": "\U000f00af",
    "bluetooth_off": "\U000f00b2", "bell": "\U000f009a", "bell_off": "\U000f009b", "game": "\U000f0297",
    "awake": "\U000f0176", "vpn": "\U000f099d", "night": "\U000f0594", "airplane": "\U000f001d", "profile": "\U000f04c5",
    "touchpad": "\U000f0322", "rotation": "\U000f0d5c", "volume": "\U000f057e", "volume_off": "\U000f0581", "mic": "\U000f036c",
    "mic_off": "\U000f036d", "brightness": "\U000f00e0", "settings": "\U000f0493", "lock": "\U000f033e",
    "power": "\U000f0425", "screenshot": "\U000f0100", "clipboard": "\U000f0147", "wallpaper": "\U000f02e9",
    "keybinds": "\U000f030c", "monitor": "\U000f0128", "chevron": "\U000f0140", "check": "\U000f012c",
    "battery": "\U000f0079", "charging": "\U000f0084", "mouse": "\U000f037d", "keyboard": "\U000f030c",
    "device": "\U000f0079", "headset": "\U000f02cb",
    "close": "\U000f0156", "clear": "\U000f00e2", "previous": "\U000f04ae", "play_pause": "\U000f040e", "next": "\U000f04ad",
    "music": "\U000f075a", "record": "\U000f044a", "colour": "\U000f03d8", "emoji": "\U000f01f5",
    "overview": "\U000f0570", "notes": "\U000f082e", "disks": "\U000f02ca", "sounds": "\U000f009e", "eject": "\U000f01ea",
}

# Used until the settings app has written theme.css
DEFAULT_THEME = """
@define-color tray_bg rgba(27, 26, 27, 0.9);
@define-color tray_text #F9F8F9;
@define-color tray_card rgba(128, 128, 128, 0.18);
@define-color tray_accent #7aa2f7;
@define-color tray_on_accent #1B1A1B;
@define-color tray_muted #9a9a9a;
@define-color tray_attention #e06c75;
"""

CSS = """
window { background: transparent; }
#panel {
    background: @tray_bg; color: @tray_text; border-radius: 12px; padding: 14px;
    box-shadow: 0 0 10px 0 rgba(0, 0, 0, 0.6); margin: 10px; border: 1px solid @tray_accent;
}
label { color: @tray_text; font-size: 13px; }
.host { font-size: 15px; font-weight: 700; }
.dim { color: @tray_muted; font-size: 12px; }
.heading { color: @tray_muted; font-size: 12px; font-weight: 700; }
button { all: unset; }
.round { background: @tray_card; border-radius: 99px; min-width: 36px; min-height: 36px; }
.round label { font-size: 17px; }
.round:hover, .tile-main:hover, .tile-more:hover, .device:hover, .icon-button:hover { background: alpha(@tray_accent, 0.25); }
.tile { background: @tray_card; border-radius: 14px; min-height: 54px; }
flowboxchild { padding: 0; }
.tile-main { border-radius: 14px; padding: 8px; }
.tile-more { border-radius: 0 14px 14px 0; padding: 0 7px; }
.tile-icon { font-size: 19px; min-width: 26px; }
.tile-title { font-size: 13px; font-weight: 700; }
.tile.on { background: @tray_accent; }
.tile.on label { color: @tray_on_accent; }
.tile.on .tile-main:hover, .tile.on .tile-more:hover { background: alpha(@tray_on_accent, 0.14); }
.icon-button { border-radius: 99px; min-width: 32px; min-height: 32px; }
.icon-button label { font-size: 17px; }
.icon-button.off label { color: @tray_muted; }
scale { padding: 6px 2px; }
scale trough { background: @tray_card; border-radius: 99px; min-height: 8px; }
scale highlight { background: @tray_accent; border-radius: 99px; min-height: 8px; }
scale slider { background: @tray_text; border-radius: 99px; min-width: 16px; min-height: 16px; margin: -5px 0; }
.device { border-radius: 8px; padding: 5px 10px; }
.stat { background: @tray_card; border-radius: 14px; padding: 9px 11px; }
.stat-value { font-size: 19px; font-weight: 700; }
.attention { color: @tray_attention; }
.notes-head { background: @tray_card; border-radius: 14px; padding: 8px 10px; }
.notes-head:hover, .note:hover { background: alpha(@tray_accent, 0.25); }
.note { background: @tray_card; border-radius: 14px; padding: 8px 10px; }
.note-title { font-size: 13px; font-weight: 700; }
.note.critical { border: 1px solid @tray_attention; }
.note-action { background: alpha(@tray_accent, 0.35); border-radius: 8px; padding: 3px 10px; }
.note-action:hover { background: @tray_accent; }
#osd, #switcher { background: @tray_bg; border: 1px solid @tray_accent; border-radius: 16px; margin: 10px; box-shadow: 0 0 10px 0 rgba(0, 0, 0, 0.6); }
#osd { padding: 10px 16px; }
#switcher { padding: 16px; }
.switch-item { border-radius: 14px; padding: 10px; }
.switch-item:hover { background: alpha(@tray_accent, 0.25); }
.switch-item.on { background: alpha(@tray_accent, 0.55); }
#overview { background: alpha(@tray_bg, 0.75); }
.ws-card { background: @tray_card; border-radius: 14px; padding: 8px; border: 2px solid transparent; }
.ws-card.current { border-color: alpha(@tray_accent, 0.45); }
.ws-card.on, .ws-card:hover { border-color: @tray_accent; }
tooltip { background: @tray_bg; color: @tray_text; border-radius: 8px; }
tooltip label { color: @tray_text; }
"""


def run(*cmd, timeout=3):
    """Output of a command; empty if it is missing, fails or hangs."""
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout).stdout
    except (OSError, subprocess.SubprocessError):
        return ""


def spawn(command):
    """Starts a shell command that outlives the tray."""
    subprocess.Popen(["bash", "-c", command], start_new_session=True, stdin=subprocess.DEVNULL,
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def background(job, then=None):
    def work():
        result = job()
        if then:
            GLib.idle_add(lambda: then(result) and False)
    threading.Thread(target=work, daemon=True).start()


def hand_cursor(widget):
    def enter(w, _event):
        if w.get_window():
            w.get_window().set_cursor(Gdk.Cursor.new_from_name(w.get_display(), "pointer"))
    widget.connect("enter-notify-event", enter)


class Avatar(Gtk.DrawingArea):
    """Your picture from the User page of Settings, in a circle. Takes no room if you have none."""
    SIZE = 36

    def __init__(self):
        super().__init__()
        self.set_size_request(self.SIZE, self.SIZE)
        self.set_valign(Gtk.Align.CENTER)
        self.set_no_show_all(True)
        self.picture = None
        self.connect("draw", self._draw)

    def reload(self):
        try:
            self.picture = GdkPixbuf.Pixbuf.new_from_file_at_scale(str(Path.home() / ".face"), self.SIZE, self.SIZE, False)
        except GLib.Error:
            self.picture = None
        self.set_visible(self.picture is not None)
        self.queue_draw()

    def _draw(self, _area, cr):
        if self.picture:
            cr.arc(self.SIZE / 2, self.SIZE / 2, self.SIZE / 2, 0, 2 * pi)
            cr.clip()
            Gdk.cairo_set_source_pixbuf(cr, self.picture, 0, 0)
            cr.paint()
        return False


def icon_button(icon, tooltip, action, css="round"):
    b = Gtk.Button()
    b.add(label(icon, xalign=0.5))
    b.get_style_context().add_class(css)
    b.set_tooltip_text(tooltip)
    b.connect("clicked", lambda _b: action())
    hand_cursor(b)
    return b


def play(name):
    """A system sound, unless they are switched off (Settings tile) or the theme is not installed."""
    path = SOUND_DIR / f"{name}.oga"
    if path.exists() and not SOUND_OFF.exists():
        subprocess.Popen(["pw-play", str(path)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def recording_since():
    """When record.sh started, or None if nothing is being recorded."""
    pidfile = Path(os.environ.get("XDG_RUNTIME_DIR", "/tmp")) / "recording.pid"
    try:
        os.kill(int(pidfile.read_text()), 0)
        return pidfile.stat().st_mtime
    except (OSError, ValueError):
        return None


class Tile(Gtk.Box):
    """A quick setting. Click switches it; the arrow (or a right click) opens its full settings, if it has any."""

    def __init__(self, icon, title, toggle=None, more=None):
        super().__init__()
        self.get_style_context().add_class("tile")
        self.title, self.toggle, self.more = title, toggle, more
        main = Gtk.Button()
        main.get_style_context().add_class("tile-main")
        row = Gtk.Box(spacing=8)
        self.icon = label(icon, "tile-icon", 0.5)
        words = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        words.set_valign(Gtk.Align.CENTER)
        words.pack_start(label(title, "tile-title", ellipsize=True), False, False, 0)
        self.sub = label("", "dim", ellipsize=True)
        words.pack_start(self.sub, False, False, 0)
        row.pack_start(self.icon, False, False, 0)
        row.pack_start(words, True, True, 0)
        main.add(row)
        main.connect("clicked", lambda _b: (toggle or more)() if (toggle or more) else None)
        main.connect("button-press-event", self._press)
        hand_cursor(main)
        self.pack_start(main, True, True, 0)
        if toggle and more:
            arrow = Gtk.Button()
            arrow.get_style_context().add_class("tile-more")
            icon_label = label(ICON["chevron"], xalign=0.5)
            icon_label.set_angle(90)
            arrow.add(icon_label)
            arrow.set_tooltip_text(f"{title} settings")
            arrow.connect("clicked", lambda _b: more())
            hand_cursor(arrow)
            self.pack_start(arrow, False, False, 0)

    def _press(self, _w, event):
        if event.button == 3 and self.more:
            self.more()
            return True
        return False

    def show_state(self, on, sub, icon=None):
        ctx = self.get_style_context()
        (ctx.add_class if on else ctx.remove_class)("on")
        self.sub.set_text(sub)
        if icon:
            self.icon.set_text(icon)

    def present(self, yes):
        parent = self.get_parent()  # the FlowBox's child, or a hidden tile would leave a hole
        if parent:
            parent.set_visible(yes)


class Slider(Gtk.Box):
    """Icon (click to mute), slider, percent, and the list of outputs or inputs to pick from."""

    def __init__(self, icon, icon_off, setter, mute=None, pick=None, tooltip=""):
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self.icons, self.setter, self.pick = (icon, icon_off), setter, pick
        self.touched, self.wanted, self.writing, self.current = 0.0, None, False, None
        row = Gtk.Box(spacing=6)
        self.button = icon_button(icon, tooltip, mute or (lambda: None), "icon-button")
        self.icon = self.button.get_child()
        self.scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 0, 100, 1)
        self.scale.set_draw_value(False)
        self.scale.connect("change-value", self._changed)
        self.percent = label("", "dim", 1.0)
        self.percent.set_width_chars(4)
        row.pack_start(self.button, False, False, 0)
        row.pack_start(self.scale, True, True, 0)
        row.pack_start(self.percent, False, False, 0)
        self.pack_start(row, False, False, 0)
        self.choices = None
        if not pick:
            self.percent.set_margin_end(38)  # lines up with the sliders that have an arrow
        if pick:
            self.arrow = icon_button(ICON["chevron"], "Choose the device", self._toggle_list, "icon-button")
            row.pack_start(self.arrow, False, False, 0)
            self.revealer = Gtk.Revealer()
            self.list = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
            self.revealer.add(self.list)
            self.pack_start(self.revealer, False, False, 0)

    def _toggle_list(self):
        self.revealer.set_reveal_child(not self.revealer.get_reveal_child())

    def collapse(self):
        if self.pick:
            self.revealer.set_reveal_child(False)

    def _changed(self, _scale, _scroll, value):
        self.touched = time.monotonic()
        self.wanted = int(max(0, min(100, value)))
        self.percent.set_text(f"{self.wanted}%")
        self._write()
        return False

    def _write(self):
        # One command at a time, always the latest value, so dragging does not queue up dozens of them
        if self.writing or self.wanted is None:
            return
        self.writing, value, self.wanted = True, self.wanted, None

        def finished(_result):
            self.writing = False
            self._write()
        background(lambda: self.setter(value), finished)

    def show_state(self, percent, muted):
        self.icon.set_text(self.icons[1] if muted else self.icons[0])
        ctx = self.button.get_style_context()
        (ctx.add_class if muted else ctx.remove_class)("off")
        if time.monotonic() - self.touched > 1.5:  # or the slider jumps back under your mouse
            self.scale.set_value(percent)
            self.percent.set_text(f"{percent}%")

    def show_choices(self, choices, current):
        """choices: [(name, description)]. Rebuilt only when something changed, so an open list does not flicker."""
        if (choices, current) == (self.choices, self.current):
            return
        self.choices, self.current = choices, current
        self.arrow.set_visible(len(choices) > 1)
        for child in self.list.get_children():
            self.list.remove(child)
        for name, description in choices:
            b = Gtk.Button()
            b.get_style_context().add_class("device")
            row = Gtk.Box(spacing=8)
            row.pack_start(label(ICON["check"] if name == current else " ", xalign=0.5), False, False, 0)
            row.pack_start(label(description, ellipsize=True), True, True, 0)
            b.add(row)
            b.connect("clicked", lambda _b, n=name: self.pick(n))
            hand_cursor(b)
            self.list.pack_start(b, False, False, 0)
        self.list.show_all()


class Stat(Gtk.Box):
    """A number, a line under it, and its last two minutes as a graph."""

    def __init__(self, title, ceiling=None):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=1)
        self.get_style_context().add_class("stat")
        self.ceiling = ceiling  # None: scale to the busiest moment on the graph
        self.history = deque(maxlen=HISTORY)
        self.pack_start(label(title, "heading"), False, False, 0)
        self.value = label("–", "stat-value")
        self.sub = label(" ", "dim", ellipsize=True)
        self.pack_start(self.value, False, False, 0)
        self.pack_start(self.sub, False, False, 0)
        self.graph = Gtk.DrawingArea()
        self.graph.set_size_request(-1, 30)
        self.graph.set_margin_top(5)
        self.graph.connect("draw", self._draw)
        self.pack_start(self.graph, False, False, 0)

    def add(self, sample, value, sub, tip):
        if sample is not None:
            self.history.append(sample)
        self.value.set_text(value)
        self.sub.set_text(sub)
        self.set_tooltip_text(tip)
        self.graph.queue_draw()

    def _draw(self, area, cr):
        points = list(self.history)
        width, height = area.get_allocated_width(), area.get_allocated_height()
        if len(points) < 2:
            return False
        ctx = area.get_style_context()
        ok, colour = ctx.lookup_color("tray_accent")
        colour = colour if ok else Gdk.RGBA(0.5, 0.6, 1, 1)
        top = self.ceiling or max(max(points), 1)
        step = width / (HISTORY - 1)
        start = width - step * (len(points) - 1)  # new samples come in on the right
        line = [(start + i * step, height - 1 - (height - 2) * min(p, top) / top) for i, p in enumerate(points)]
        cr.move_to(line[0][0], height)
        for x, y in line:
            cr.line_to(x, y)
        cr.line_to(width, height)
        cr.close_path()
        cr.set_source_rgba(colour.red, colour.green, colour.blue, 0.2)
        cr.fill()
        for x, y in line:
            cr.line_to(x, y)
        cr.set_source_rgba(colour.red, colour.green, colour.blue, 1)
        cr.set_line_width(2)
        cr.set_line_join(1)  # round
        cr.stroke()
        return False


class Tray(Gtk.Window):
    def __init__(self):
        super().__init__()
        self.set_title("Quick tray")
        self.inhibitor = None
        self.touchpad_off = False
        self.dnd = False
        self.polling = self.sampling = False
        self.poll_timer = None
        self.previous = None  # last CPU and network counters
        self.disk_rows = {}
        self.battery_reached = None
        self.peripherals_warned = {}
        self.notes = []  # newest first
        self.notes_open = False
        self.notes_expanded = set()  # the ones showing all their text
        self.swaync_count = 0
        self.levels = {}
        self.osd_timer = None
        self.osd = Osd()
        self.switcher = Switcher()
        self.overview = Overview()
        self.note_times = []
        self.peripheral_labels = {}
        self.laptop = sysinfo.is_laptop()
        self.has_backlight = sysinfo.backlight()
        self.has_profiles = bool(shutil.which("powerprofilesctl"))

        GtkLayerShell.init_for_window(self)
        GtkLayerShell.set_namespace(self, "quick-tray")
        GtkLayerShell.set_layer(self, GtkLayerShell.Layer.OVERLAY)  # above swaync's full-screen window, which is on top
        GtkLayerShell.set_anchor(self, GtkLayerShell.Edge.TOP, True)
        GtkLayerShell.set_anchor(self, GtkLayerShell.Edge.RIGHT, True)
        GtkLayerShell.set_keyboard_mode(self, GtkLayerShell.KeyboardMode.NONE)  # swaync keeps the keyboard (Escape)
        GtkLayerShell.set_margin(self, GtkLayerShell.Edge.RIGHT, EDGE)
        GtkLayerShell.set_margin(self, GtkLayerShell.Edge.TOP, EDGE)
        self.add(self._build())
        self.get_child().show_all()
        self._apply_hardware()
        self._draw_notes()
        self.watcher = notifications.Watcher(self._note_added, self._note_closed)
        self.watcher.start()
        self._sample()
        GLib.timeout_add_seconds(SAMPLE_SECONDS, self._sample)

    def _build(self):
        scroller = Gtk.ScrolledWindow()
        scroller.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroller.set_propagate_natural_height(True)
        self.scroller = scroller
        panel = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        panel.set_name("panel")
        panel.set_size_request(WIDTH, -1)
        scroller.add(panel)

        # Who and how long, then the session buttons
        top = Gtk.Box(spacing=6)
        self.avatar = Avatar()
        top.pack_start(self.avatar, False, False, 2)
        words = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.who = label(socket.gethostname(), "host")
        words.pack_start(self.who, False, False, 0)
        self.uptime = label("", "dim")
        words.pack_start(self.uptime, False, False, 0)
        top.pack_start(words, True, True, 0)
        top.pack_start(icon_button(ICON["settings"], "Settings", lambda: self.launch(f"{SCRIPTS}/settings.sh")), False, False, 0)
        top.pack_start(icon_button(ICON["lock"], "Lock the screen", lambda: self.launch(f"{SCRIPTS}/lock.sh")), False, False, 0)
        top.pack_start(icon_button(ICON["power"], "Power menu", lambda: self.launch("~/.config/rofi/powermenu/powermenu.sh")), False, False, 0)
        panel.pack_start(top, False, False, 0)

        # Quick settings
        self.wifi = Tile(ICON["wifi"], "Wi-Fi", self.toggle_wifi, self.network_settings)
        self.ethernet = Tile(ICON["ethernet"], "Ethernet", None, self.network_settings)
        self.bluetooth = Tile(ICON["bluetooth"], "Bluetooth", self.toggle_bluetooth, lambda: self.launch("blueman-manager"))
        self.vpn = Tile(ICON["vpn"], "VPN", self.toggle_vpn, self.network_settings)
        self.dnd_tile = Tile(ICON["bell"], "Do not disturb", self.toggle_dnd)
        self.game = Tile(ICON["game"], "Game mode", self.toggle_game)
        self.awake = Tile(ICON["awake"], "Stay awake", self.toggle_awake)
        self.night = Tile(ICON["night"], "Night light", self.toggle_night)
        self.sounds = Tile(ICON["sounds"], "System sounds", self.toggle_sounds)
        self.record = Tile(ICON["record"], "Record screen", lambda: self.launch(f"{SCRIPTS}/record.sh screen", 0.4))
        self.profile = Tile(ICON["profile"], "Power profile", self.next_profile)
        self.airplane = Tile(ICON["airplane"], "Airplane mode", self.toggle_airplane)
        self.touchpad = Tile(ICON["touchpad"], "Touchpad", self.toggle_touchpad)
        self.rotation = Tile(ICON["rotation"], "Rotation lock", self.toggle_rotation)
        tiles = Gtk.FlowBox()
        tiles.set_selection_mode(Gtk.SelectionMode.NONE)
        tiles.set_min_children_per_line(2)
        tiles.set_max_children_per_line(2)
        tiles.set_homogeneous(True)
        tiles.set_column_spacing(8)
        tiles.set_row_spacing(8)
        tiles.set_can_focus(False)
        for tile in (self.wifi, self.ethernet, self.bluetooth, self.vpn, self.dnd_tile, self.awake, self.game,
                     self.record, self.sounds, self.night, self.profile, self.airplane, self.touchpad, self.rotation):
            tiles.add(tile)
            tile.get_parent().set_can_focus(False)
        panel.pack_start(tiles, False, False, 0)

        # Sliders
        sliders = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.output = Slider(ICON["volume"], ICON["volume_off"],
                             lambda v: run("wpctl", "set-volume", "-l", "1", "@DEFAULT_AUDIO_SINK@", f"{v}%"),
                             lambda: self.command("wpctl", "set-mute", "@DEFAULT_AUDIO_SINK@", "toggle"),
                             lambda n: self.command("pactl", "set-default-sink", n), "Mute or unmute the sound")
        self.input = Slider(ICON["mic"], ICON["mic_off"],
                            lambda v: run("wpctl", "set-volume", "-l", "1", "@DEFAULT_AUDIO_SOURCE@", f"{v}%"),
                            lambda: self.command("wpctl", "set-mute", "@DEFAULT_AUDIO_SOURCE@", "toggle"),
                            lambda n: self.command("pactl", "set-default-source", n), "Mute or unmute the microphone")
        self.brightness = Slider(ICON["brightness"], ICON["brightness"], lambda v: run("brightnessctl", "-e4", "-n2", "set", f"{v}%"))
        for slider in (self.output, self.input, self.brightness):
            sliders.pack_start(slider, False, False, 0)
        panel.pack_start(sliders, False, False, 0)

        # Handy jobs
        jobs = Gtk.Box(homogeneous=True)
        for icon, tip, command, delay in (
                (ICON["screenshot"], "Screenshot a region", f"{SCRIPTS}/screenshot.sh region", 0.4),
                (ICON["clipboard"], "Clipboard history", "clipvault list | rofi -dmenu -display-columns 2 | clipvault get | wl-copy", 0),
                (ICON["wallpaper"], "Wallpaper picker", "~/.config/rofi/wallpaper/wallpaper.sh", 0),
                (ICON["keybinds"], "Keybind cheatsheet", "~/.config/hypr/cheatsheet/cheatsheet.sh", 0),
                (ICON["notes"], "Notes (Super+I)", "~/.config/hypr/notes/notes.sh", 0.2),
                (ICON["volume"], "Sound: outputs, apps, equaliser (Super+Shift+A)", SOUND_APP, 0),
                (ICON["overview"], "All workspaces", "pkill -HUP -f '[h]ypr/tray/quick_tray'", 0.25),
                (ICON["colour"], "Pick a colour", f"{SCRIPTS}/colour-picker.sh", 0.3),
                (ICON["emoji"], "Pick an emoji", f"{SCRIPTS}/emoji.sh", 0.2),
                (ICON["disks"], "Partition manager", "partitionmanager", 0),
                (ICON["monitor"], "Task manager (btop)", "ghostty -e btop", 0)):
            if icon == ICON["monitor"] and not shutil.which("btop"):
                continue
            b = icon_button(icon, tip, lambda c=command, d=delay: self.launch(c, d))
            b.set_halign(Gtk.Align.CENTER)
            jobs.pack_start(b, True, True, 0)
        panel.pack_start(jobs, False, False, 0)

        # What is playing (hidden when nothing is)
        self.media = Gtk.Box(spacing=4)
        self.media.pack_start(label(ICON["music"], "tile-icon", 0.5), False, False, 0)
        self.media_text = label("", ellipsize=True)
        self.media.pack_start(self.media_text, True, True, 0)
        for icon, tip, verb in ((ICON["previous"], "Previous", "previous"), (ICON["play_pause"], "Play or pause", "play-pause"),
                                (ICON["next"], "Next", "next")):
            self.media.pack_start(icon_button(icon, tip, lambda v=verb: self.command("playerctl", v), "icon-button"), False, False, 0)
        panel.pack_start(self.media, False, False, 0)

        # System monitor
        self.battery = Gtk.Box(spacing=8)
        self.battery_icon, self.battery_text = label(ICON["battery"], "tile-icon", 0.5), label()
        self.battery_meter = Meter()
        self.battery_meter.set_valign(Gtk.Align.CENTER)
        self.battery.pack_start(self.battery_icon, False, False, 0)
        self.battery.pack_start(self.battery_text, False, False, 0)
        self.battery.pack_start(self.battery_meter, True, True, 0)
        panel.pack_start(self.battery, False, False, 0)

        grid = Gtk.Grid(column_spacing=8, row_spacing=8, column_homogeneous=True)
        self.cpu = Stat("CPU", 100)
        self.ram = Stat("MEMORY", 100)
        self.gpu_stat = Stat("GPU", 100)
        self.net = Stat("NETWORK")
        self.stats = (self.cpu, self.ram, self.gpu_stat, self.net)
        for i, stat in enumerate(self.stats):
            grid.attach(stat, i % 2, i // 2, 1, 1)
        panel.pack_start(grid, False, False, 0)

        self.disks_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        panel.pack_start(self.disks_box, False, False, 0)
        self.peripherals_box = Gtk.Box(spacing=14)
        panel.pack_start(self.peripherals_box, False, False, 0)

        # Notifications: one line until clicked
        head = Gtk.Box(spacing=6)
        self.notes_button = Gtk.Button()
        self.notes_button.get_style_context().add_class("notes-head")
        row = Gtk.Box(spacing=8)
        self.notes_icon = label(ICON["bell"], "tile-icon", 0.5)
        words = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.notes_title = label("No notifications", "tile-title")
        self.notes_latest = label("", "dim", ellipsize=True)
        words.pack_start(self.notes_title, False, False, 0)
        words.pack_start(self.notes_latest, False, False, 0)
        self.notes_arrow = label(ICON["chevron"], xalign=0.5)
        row.pack_start(self.notes_icon, False, False, 0)
        row.pack_start(words, True, True, 0)
        row.pack_start(self.notes_arrow, False, False, 0)
        self.notes_button.add(row)
        self.notes_button.connect("clicked", lambda _b: self.toggle_notes())
        hand_cursor(self.notes_button)
        head.pack_start(self.notes_button, True, True, 0)
        self.notes_clear = icon_button(ICON["clear"], "Clear all notifications", self.clear_notes)
        self.notes_clear.set_valign(Gtk.Align.CENTER)
        head.pack_start(self.notes_clear, False, False, 0)
        panel.pack_start(head, False, False, 0)
        self.notes_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        panel.pack_start(self.notes_box, False, False, 0)
        return scroller

    def _apply_hardware(self):
        """Hides what does not depend on anything that can change while the tray runs."""
        self.brightness.set_visible(self.has_backlight)
        self.battery.set_visible(sysinfo.system_battery() is not None)
        self.profile.present(self.has_profiles)
        self.airplane.present(self.laptop)
        self.touchpad.present(False)
        self.rotation.present(sysinfo.has_accelerometer())
        self.rotation.show_state(ROTATION_LOCK.exists(), "On" if ROTATION_LOCK.exists() else "Off")
        self.vpn.present(False)
        self.wifi.present(False)
        self.ethernet.present(False)
        self.bluetooth.present(sysinfo.has_bluetooth())
        self.record.present(False)
        self.sounds.present(SOUND_DIR.is_dir())
        self.sounds.show_state(not SOUND_OFF.exists(), "Off" if SOUND_OFF.exists() else "On")
        self.media.set_visible(False)

    # ---- opening and closing --------------------------------------------------------------------------------------
    def follow_swaync(self):
        """Opens and closes with the notification centre. Comes back after swaync restarts (game mode does that)."""
        while True:
            try:
                with subprocess.Popen(["swaync-client", "-s"], stdout=subprocess.PIPE, text=True) as client:
                    for line in client.stdout:
                        try:
                            GLib.idle_add(self._swaync_changed, json.loads(line))
                        except ValueError:
                            pass
            except OSError:
                pass
            GLib.idle_add(self._swaync_changed, {"visible": False, "count": 0})  # a restart empties its history
            time.sleep(2)

    def _swaync_changed(self, status):
        self.dnd = status.get("dnd", self.dnd)
        if status.get("count", self.swaync_count) != self.swaync_count:
            self.swaync_count = status["count"]
            if not self.swaync_count:
                self.notes.clear()
            self._draw_notes()
        self.dnd_tile.show_state(self.dnd, "On" if self.dnd else "Off", ICON["bell_off"] if self.dnd else ICON["bell"])
        if status.get("visible") and not self.get_visible():
            self.open()
        elif not status.get("visible") and self.get_visible():
            self.close_panel()
        return False

    def open(self):
        self.touch_css.load_from_data(touch_mode.TRAY_CSS.encode() if touch_mode.active() else b"")
        self.show()
        self.avatar.reload()
        self.who.set_text(pwd.getpwuid(os.getuid()).pw_gecos.split(",")[0].strip() or socket.gethostname())
        self._fit_to_screen()
        self.poll()
        self.poll_timer = GLib.timeout_add_seconds(SAMPLE_SECONDS, self.poll)

    def close_panel(self):
        self.hide()
        self.output.collapse()
        self.input.collapse()
        self.notes_open = False
        self.notes_expanded.clear()
        self._draw_notes()
        if self.poll_timer:
            GLib.source_remove(self.poll_timer)
            self.poll_timer = None

    def _fit_to_screen(self):
        """On a small screen the panel scrolls instead of running off the bottom."""
        display = self.get_display()
        window = self.get_window()
        monitor = display.get_monitor_at_window(window) if window else display.get_monitor(0)
        limit = max(320, monitor.get_geometry().height - 120 if monitor else 1010)  # the bar, the margins and the panel's padding
        _smallest, natural = self.scroller.get_child().get_preferred_height()
        self.scroller.set_min_content_height(min(natural, limit))
        self.scroller.set_max_content_height(limit)
        self.resize(WIDTH, 1)  # also shrinks back when a list closes

    def launch(self, command, delay=0.0):
        """Closes the tray and starts something. The delay keeps a screenshot from catching the tray fading out."""
        subprocess.Popen(["swaync-client", "-cp", "-sw"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        spawn(f"sleep {delay}; {command}" if delay else command)

    def command(self, *cmd):
        """Runs a quick change, then re-reads the state so the tray shows the result."""
        background(lambda: run(*cmd, timeout=15), lambda _r: self.poll())

    # ---- the quick settings ---------------------------------------------------------------------------------------
    def network_settings(self):
        self.launch(f"{SCRIPTS}/settings.sh --page=Network")

    def toggle_wifi(self):
        self.command("nmcli", "radio", "wifi", "off" if self.state.get("wifi_radio") else "on")

    def toggle_bluetooth(self):
        self.command("bluetoothctl", "power", "off" if self.state.get("bt_on") else "on")

    def toggle_dnd(self):
        run("swaync-client", "-d", "-sw")

    def toggle_game(self):
        # The script turns animations off, or restores the desktop and restarts the bar and notifications
        self.launch(f"{SCRIPTS}/gamemode.sh")

    def toggle_awake(self):
        if self.inhibitor and self.inhibitor.poll() is None:
            self.inhibitor.terminate()
            self.inhibitor.wait(timeout=2)
            self.inhibitor = None
        else:
            # tail ends with this process, so the lock can never outlive the tray
            self.inhibitor = subprocess.Popen(
                ["systemd-inhibit", "--what=idle", "--who=Quick tray", "--why=Stay awake is switched on",
                 "tail", f"--pid={os.getpid()}", "-f", "/dev/null"],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.poll()

    def toggle_sounds(self):
        if SOUND_OFF.exists():
            SOUND_OFF.unlink()
            play("audio-volume-change")
        else:
            SOUND_OFF.parent.mkdir(parents=True, exist_ok=True)
            SOUND_OFF.touch()
        self.sounds.show_state(not SOUND_OFF.exists(), "Off" if SOUND_OFF.exists() else "On")

    def toggle_night(self):
        if self.state.get("night"):
            self.command("pkill", "-x", "hyprsunset")
        else:
            spawn("exec hyprsunset -t 4500")
            GLib.timeout_add(400, lambda: self.poll() and False)

    def next_profile(self):
        profiles = self.state.get("profiles") or []
        if profiles:
            at = profiles.index(self.state["profile"]) if self.state.get("profile") in profiles else -1
            self.command("powerprofilesctl", "set", profiles[(at + 1) % len(profiles)])

    def toggle_airplane(self):
        off = not self.state.get("airplane")

        def job():
            run("nmcli", "radio", "all", "off" if off else "on")
            if sysinfo.has_bluetooth():
                run("bluetoothctl", "power", "off" if off else "on")
        background(job, lambda _r: self.poll())

    def toggle_touchpad(self):
        pads = self.state.get("touchpads") or []
        self.touchpad_off = not self.touchpad_off
        for pad in pads:
            run("hyprctl", "eval", f'hl.device({{ name = "{pad}", enabled = {"false" if self.touchpad_off else "true"} }})')
        self.poll()

    def toggle_rotation(self):
        """tablet_mode.py looks for the file."""
        if ROTATION_LOCK.exists():
            ROTATION_LOCK.unlink()
        else:
            ROTATION_LOCK.parent.mkdir(parents=True, exist_ok=True)
            ROTATION_LOCK.touch()
        self.rotation.show_state(ROTATION_LOCK.exists(), "On" if ROTATION_LOCK.exists() else "Off")

    def toggle_vpn(self):
        vpns = self.state.get("vpns") or []
        active = [name for name, on in vpns if on]
        if active:
            self.command("nmcli", "connection", "down", active[0])
        elif vpns:
            self.command("nmcli", "connection", "up", vpns[0][0])

    # ---- reading the state ----------------------------------------------------------------------------------------
    state: dict = {}

    def poll(self):
        """Runs on a timer while the tray is open; nothing here runs while it is closed."""
        if not self.polling:
            self.polling = True
            background(self._read_state, self._show_state)
        return True

    def _read_state(self):
        s = {"network": sysinfo.parse_network(run("nmcli", "-t", "-f", "TYPE,STATE,CONNECTION", "dev"))}
        s["wifi_radio"] = run("nmcli", "radio", "wifi").strip() == "enabled"
        s["bt_present"] = sysinfo.has_bluetooth()
        if s["bt_present"]:
            s["bt_on"] = "Powered: yes" in run("bluetoothctl", "show")
            s["bt_devices"] = [line.split(" ", 2)[2] for line in run("bluetoothctl", "devices", "Connected").splitlines()
                               if line.count(" ") >= 2] if s["bt_on"] else []
        s["vpns"] = []
        for line in run("nmcli", "-t", "-f", "NAME,TYPE,ACTIVE", "connection", "show").splitlines():
            name, _, rest = line.rpartition(":")
            name, _, kind = name.rpartition(":")
            if kind in ("vpn", "wireguard"):
                s["vpns"].append((name.replace("\\:", ":"), rest == "yes"))
        s["game"] = (run("hyprctl", "getoption", "animations:enabled").split() + ["", "true"])[1] == "false"
        s["record_present"] = bool(shutil.which("gpu-screen-recorder"))
        s["recording_since"] = recording_since()
        s["night_present"] = bool(shutil.which("hyprsunset"))
        s["night"] = s["night_present"] and bool(run("pgrep", "-x", "hyprsunset").strip())
        if self.has_profiles:
            s["profile"] = run("powerprofilesctl", "get").strip()
            s["profiles"] = [line.strip(" *:") for line in run("powerprofilesctl", "list").splitlines()
                             if line.rstrip().endswith(":") and not line.startswith("  ")]
        if self.laptop:
            s["airplane"] = "enabled" not in run("nmcli", "radio", "all")
            try:
                mice = json.loads(run("hyprctl", "devices", "-j") or "{}").get("mice", [])
            except ValueError:
                mice = []
            s["touchpads"] = [m["name"] for m in mice if "touchpad" in m.get("name", "").lower()]
        s["media"] = run("playerctl", "metadata", "--format", "{{status}}\t{{artist}}\t{{title}}").strip().split("\t")
        s["output"] = sysinfo.parse_volume(run("wpctl", "get-volume", "@DEFAULT_AUDIO_SINK@"))
        s["input"] = sysinfo.parse_volume(run("wpctl", "get-volume", "@DEFAULT_AUDIO_SOURCE@"))
        s["sink"] = run("pactl", "get-default-sink").strip()
        s["source"] = run("pactl", "get-default-source").strip()
        for key, kind in (("sinks", "sinks"), ("sources", "sources")):
            try:
                found = json.loads(run("pactl", "-f", "json", "list", kind) or "[]")
            except ValueError:
                found = []
            # A source that only copies a speaker's sound (a "monitor") is not a microphone
            s[key] = [(d["name"], d.get("description", d["name"])) for d in found if not d["name"].endswith(".monitor")]
        if self.has_backlight:
            try:
                now, top = int(run("brightnessctl", "get")), int(run("brightnessctl", "max"))
                s["brightness"] = round(100 * now / top)
            except (ValueError, ZeroDivisionError):
                pass
        return s

    def _show_state(self, s):
        self.polling = False
        self.state = s
        net = s["network"]
        self.wifi.present(net["wifi"])
        self.wifi.show_state(s["wifi_radio"], net["wifi_name"] or ("No network" if s["wifi_radio"] else "Off"),
                             ICON["wifi"] if s["wifi_radio"] else ICON["wifi_off"])
        self.ethernet.present(net["ethernet"])
        self.ethernet.show_state(net["ethernet_on"], "Connected" if net["ethernet_on"] else "Unplugged")
        self.bluetooth.present(s["bt_present"])
        if s["bt_present"]:
            devices = s["bt_devices"]
            sub = ("Off" if not s["bt_on"] else devices[0] if len(devices) == 1
                   else f"{len(devices)} connected" if devices else "On")
            self.bluetooth.show_state(s["bt_on"], sub, ICON["bluetooth"] if s["bt_on"] else ICON["bluetooth_off"])
        self.vpn.present(bool(s["vpns"]))
        active = [name for name, on in s["vpns"] if on]
        self.vpn.show_state(bool(active), active[0] if active else "Off")
        self.game.show_state(s["game"], "On" if s["game"] else "Off")
        awake = bool(self.inhibitor and self.inhibitor.poll() is None)
        self.awake.show_state(awake, "Screen stays on" if awake else "Off")
        self.record.present(s["record_present"])
        since = s["recording_since"]
        self.record.show_state(since is not None, f"{int((time.time() - since) // 60):02d}:{int((time.time() - since) % 60):02d}, click to stop" if since else "This screen")
        self.night.present(s["night_present"])
        self.night.show_state(s["night"], "On" if s["night"] else "Off")
        if self.has_profiles:
            self.profile.show_state(s.get("profile") not in (None, "", "balanced"), (s.get("profile") or "").replace("-", " ").capitalize())
        if self.laptop:
            self.airplane.show_state(s["airplane"], "On" if s["airplane"] else "Off")
            self.touchpad.present(bool(s["touchpads"]))
            self.touchpad.show_state(not self.touchpad_off, "Off" if self.touchpad_off else "On")
        for slider, key, listing, selected in ((self.output, "output", "sinks", "sink"),
                                               (self.input, "input", "sources", "source")):
            slider.set_visible(s[key] is not None)
            if s[key] is not None:
                slider.show_state(*s[key])
            slider.show_choices(s[listing], s[selected])
        media = s["media"]
        self.media.set_visible(len(media) == 3 and media[0] in ("Playing", "Paused"))
        if len(media) == 3:
            self.media_text.set_text(" – ".join(x for x in media[1:] if x))
        if "brightness" in s:
            self.brightness.show_state(s["brightness"], False)
        self._fit_to_screen()  # tiles may have come or gone
        return False

    # ---- notifications ----------------------------------------------------------------------------------------------
    def _note_added(self, note_id, note):
        if not self.dnd and note["app"] not in SOUNDLESS_APPS:
            play("dialog-warning" if note["critical"] else "message-new-instant")
        if not note["transient"]:  # swaync only shows those as a popup, and keeps no history of them
            replaced = note["replaces"]
            self.notes = [n for n in self.notes if n["id"] not in (note_id, replaced)]
            self.notes.insert(0, {**note, "id": note_id})
            self._draw_notes()
        return False

    def _note_closed(self, note_id):
        before = len(self.notes)
        self.notes = [n for n in self.notes if n["id"] != note_id]
        if len(self.notes) != before:
            self._draw_notes()
        return False

    def toggle_notes(self):
        if self.notes:
            self.notes_open = not self.notes_open
            self._draw_notes()

    def toggle_note(self, note_id):
        self.notes_expanded.symmetric_difference_update({note_id})
        self._draw_notes()

    def clear_notes(self):
        run("swaync-client", "-C", "-sw")
        self.notes.clear()
        self.notes_open = False
        self._draw_notes()

    def dismiss_note(self, note_id):
        Gio.bus_get_sync(Gio.BusType.SESSION, None).call(
            "org.erikreider.swaync.cc", "/org/erikreider/swaync/cc", "org.erikreider.swaync.cc", "CloseNotification",
            GLib.Variant("(u)", (note_id,)), None, Gio.DBusCallFlags.NONE, 3000, None, None)
        self._note_closed(note_id)
        if not self.notes:
            self.notes_open = False
            self._draw_notes()

    def _draw_notes(self):
        count = len(self.notes)
        earlier = max(0, self.swaync_count - count)  # came in before the tray started, so it never saw their text
        total = count + earlier
        self.notes_title.set_text(f"{total} notification{'' if total == 1 else 's'}" if total else "No notifications")
        latest = self.notes[0]["summary"] or self.notes[0]["app"] if self.notes else ""
        self.notes_latest.set_text(latest if not self.notes_open else "")
        self.notes_latest.set_visible(bool(latest) and not self.notes_open)
        self.notes_icon.set_text(ICON["bell_off"] if self.dnd else ICON["bell"])
        self.notes_arrow.set_visible(bool(self.notes))
        self.notes_arrow.set_angle(180 if self.notes_open else 0)
        self.notes_clear.set_visible(total > 0)
        for child in self.notes_box.get_children():
            self.notes_box.remove(child)
        self.note_times = []
        if self.notes_open:
            for note in self.notes:
                self.notes_box.pack_start(self._note_card(note), False, False, 0)
            if earlier:
                self.notes_box.pack_start(label(f"And {earlier} from before the tray started", "dim"), False, False, 0)
            self.notes_box.show_all()
            for note, box in zip(self.notes, self.notes_box.get_children()):
                box.short.set_visible(note["id"] not in self.notes_expanded and bool(note["body"]))
        if self.get_visible():
            self._fit_to_screen()

    def _note_card(self, note):
        expanded = note["id"] in self.notes_expanded
        card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        button = Gtk.Button()
        ctx = card.get_style_context()
        ctx.add_class("note")
        if note["critical"]:
            ctx.add_class("critical")
        button.connect("clicked", lambda _b, i=note["id"]: self.toggle_note(i))
        hand_cursor(button)
        inner = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        top = Gtk.Box(spacing=8)
        top.pack_start(self._note_picture(note), False, False, 0)
        words = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        source = Gtk.Box(spacing=6)
        source.pack_start(label(note["app"] or "Notification", "dim", ellipsize=True), True, True, 0)
        when = label(notifications.time_ago(note["time"]), "dim", 1.0)
        self.note_times.append((when, note["time"]))
        source.pack_start(when, False, False, 0)
        words.pack_start(source, False, False, 0)
        title = label(note["summary"] or note["app"], "note-title", ellipsize=not expanded)
        title.set_line_wrap(expanded)
        title.set_line_wrap_mode(Pango.WrapMode.WORD_CHAR)
        words.pack_start(title, False, False, 0)
        card.short = label(note["body"].replace("\n", " "), "dim", ellipsize=True)
        words.pack_start(card.short, False, False, 0)
        top.pack_start(words, True, True, 0)
        inner.pack_start(top, False, False, 0)
        if note["body"] and expanded:
            text = label(note["body"])
            text.set_line_wrap(True)
            text.set_line_wrap_mode(Pango.WrapMode.WORD_CHAR)
            text.set_max_width_chars(40)
            inner.pack_start(text, False, False, 0)
        button.add(inner)
        card.pack_start(button, False, False, 0)
        # Beside the card's button rather than in it: a GTK 3 button takes every click made inside it, so one in another
        # would never fire. No buttons of the notification's own (Reply and so on): swaync only runs those for a popup
        # still on screen, and opening its panel, which this tray does, closes every popup.
        if expanded:
            row = Gtk.Box(spacing=6)
            dismiss = Gtk.Button(label="Dismiss")
            dismiss.get_style_context().add_class("note-action")
            dismiss.connect("clicked", lambda _b, i=note["id"]: self.dismiss_note(i))
            hand_cursor(dismiss)
            row.pack_end(dismiss, False, False, 0)
            card.pack_start(row, False, False, 0)
            card.dismiss = dismiss
        return card

    def _note_picture(self, note):
        """The picture it came with, else its icon, else a bell. A bad picture must not cost you the notification."""
        size = 32
        try:
            if note["image"]:
                width, height, stride, alpha, data = note["image"]
                pixbuf = GdkPixbuf.Pixbuf.new_from_bytes(data, GdkPixbuf.Colorspace.RGB, alpha, 8, width, height, stride)
                return Gtk.Image.new_from_pixbuf(pixbuf.scale_simple(size, size, GdkPixbuf.InterpType.BILINEAR))
            icon = note["icon"].removeprefix("file://")
            if icon.startswith("/"):
                return Gtk.Image.new_from_pixbuf(GdkPixbuf.Pixbuf.new_from_file_at_size(icon, size, size))
            if icon and Gtk.IconTheme.get_default().has_icon(icon):
                picture = Gtk.Image.new_from_icon_name(icon, Gtk.IconSize.DND)
                picture.set_pixel_size(size)
                return picture
        except GLib.Error:
            pass
        return label(ICON["bell"], "tile-icon", 0.5)

    # ---- the system monitor ---------------------------------------------------------------------------------------
    def _sample(self):
        """Keeps the graphs filled while closed too, so they already show the last two minutes when you open the tray.
        The GPU is only asked while open: on a laptop that could wake a sleeping graphics card."""
        if not self.sampling:
            self.sampling = True
            visible = self.get_visible()
            background(lambda: self._read_sample(visible), self._show_sample)
        return True

    def _read_sample(self, visible):
        s = {"cpu": sysinfo.cpu_times(), "memory": sysinfo.memory(), "net": sysinfo.net_bytes(), "at": time.monotonic(),
             "visible": visible}
        s.update(peripherals=sysinfo.peripherals() + self._headset(), battery=sysinfo.system_battery())
        if visible:
            s.update(cpu_temp=sysinfo.cpu_temp(), gpu=sysinfo.gpu(), disks=sysinfo.disks(), uptime=sysinfo.uptime())
        return s

    def _headset(self):
        """A wireless headset's battery, through headsetcontrol, asked once a minute (it answers over the radio)."""
        now = time.monotonic()
        if headset.available() and now - getattr(self, "headset_at", -HEADSET_SECONDS) >= HEADSET_SECONDS:
            self.headset_at = now
            self.headset_seen = headset.peripheral()
        return [self.headset_seen] if getattr(self, "headset_seen", None) else []

    def _show_sample(self, s):
        self.sampling = False
        before, self.previous = self.previous, s
        cpu = sysinfo.percent_between(before["cpu"], s["cpu"]) if before else 0.0
        seconds = (s["at"] - before["at"]) or 1 if before else 1
        down = max(0, s["net"][0] - before["net"][0]) / seconds if before else 0.0
        up = max(0, s["net"][1] - before["net"][1]) / seconds if before else 0.0
        used, total = s["memory"]
        memory = 100 * used / total if total else 0.0
        temp = f"{s['cpu_temp']:.0f}°C" if s.get("cpu_temp") is not None else " "

        def peak(stat, current, fmt):
            return f"Highest in the last 2 minutes: {fmt(max(stat.history, default=current))}"
        pct = lambda v: f"{v:.0f}%"  # noqa: E731
        rate = lambda v: f"{sysinfo.fmt_bytes(v)}/s"  # noqa: E731
        self.cpu.add(cpu, f"{cpu:.0f}%", temp, peak(self.cpu, cpu, pct))
        self.ram.add(memory, f"{memory:.0f}%", f"{sysinfo.fmt_bytes(used)} of {sysinfo.fmt_bytes(total)}", peak(self.ram, memory, pct))
        self.net.add(down, rate(down), f"Sending {rate(up)}", peak(self.net, down, rate))
        self._check_batteries(s["battery"], s["peripherals"])
        if s["visible"]:
            self.uptime.set_text(f"Up {sysinfo.fmt_uptime(s['uptime'])}")
            for when, then in self.note_times:
                when.set_text(notifications.time_ago(then))
            gpu = s["gpu"]
            self.gpu_stat.set_visible(gpu is not None)
            if gpu:
                temp = f"{gpu['temp']:.0f}°C · " if gpu["temp"] is not None else ""
                self.gpu_stat.add(gpu["busy"], f"{gpu['busy']}%", f"{temp}{sysinfo.fmt_bytes(gpu['used'])} VRAM",
                                  f"{sysinfo.fmt_bytes(gpu['used'])} of {sysinfo.fmt_bytes(gpu['total'])} video memory. "
                                  + peak(self.gpu_stat, gpu["busy"], pct))
            self._show_disks(s["disks"])
            self._show_peripherals(s["peripherals"])
            self._show_battery(s["battery"])
            self._fit_to_screen()
        return False

    def _check_batteries(self, battery, peripherals):
        """Runs while the tray is closed too: this is the only thing watching them."""
        if battery:
            alert, self.battery_reached = sysinfo.battery_alert(battery["capacity"], battery["status"], self.battery_reached)
            left = f"{battery['capacity']}% left."
            if alert == "low":
                spawn(f"notify-send -a Battery -i battery-low 'Battery low' '{left} Time to find the charger.'")
            elif alert == "critical":
                spawn(f"notify-send -u critical -a Battery -i battery-caution 'Battery very low' '{left} The PC will sleep at 3%.'")
            elif alert == "sleep":
                spawn("notify-send -u critical -a Battery -i battery-empty 'Going to sleep' 'The battery is nearly empty.'; "
                      "sleep 5; systemctl suspend")
        for device in peripherals:
            model = device["model"]
            say, self.peripherals_warned[model] = sysinfo.peripheral_alert(device["capacity"], self.peripherals_warned.get(model, False))
            if say:
                spawn(f"notify-send -a Battery -i battery-low {shlex.quote(model + ' battery low')} '{device['capacity']}% left.'")

    def _show_disks(self, disks):
        wanted = {d["mount"] for d in disks}
        for mount in list(self.disk_rows):
            if mount not in wanted:
                self.disks_box.remove(self.disk_rows.pop(mount)[0])
        for disk in disks:
            if disk["mount"] not in self.disk_rows:
                row = Gtk.Box(spacing=10)
                # A USB drive's mount point is long and only its last part says which one it is
                name = label(os.path.basename(disk["mount"]) if disk["removable"] else disk["mount"], "dim", ellipsize=True)
                name.set_width_chars(11)
                name.set_max_width_chars(11)
                meter = Meter()
                meter.set_valign(Gtk.Align.CENTER)
                text = label("", "dim", 1.0)
                text.set_width_chars(15)
                row.pack_start(name, False, False, 0)
                row.pack_start(meter, True, True, 0)
                row.pack_start(text, False, False, 0)
                if disk["removable"]:
                    row.pack_start(icon_button(ICON["eject"], "Safely remove", lambda m=disk["mount"]: self.eject(m), "icon-button"), False, False, 0)
                row.show_all()
                self.disks_box.pack_start(row, False, False, 0)
                self.disk_rows[disk["mount"]] = (row, meter, text)
            _row, meter, text = self.disk_rows[disk["mount"]]
            fraction = disk["used"] / disk["total"]
            meter.show_fraction(fraction, fraction * 100 >= ATTENTION_DISK)
            text.set_text(f"{sysinfo.fmt_bytes(disk['used'])} / {sysinfo.fmt_bytes(disk['total'])}")

    def eject(self, mount):
        def job():
            out = subprocess.run(["udiskie-umount", "--detach", mount], capture_output=True, text=True, timeout=30)
            return out.returncode == 0
        name = os.path.basename(mount)

        def done(ok):
            title, body = ("Safe to remove", name) if ok else ("Could not remove it", f"Something is still using {name}.")
            subprocess.Popen(["notify-send", "-a", "Drives", "-i", "drive-removable-media", title, body])
        background(job, done)

    def _show_peripherals(self, peripherals):
        for child in self.peripherals_box.get_children():
            self.peripherals_box.remove(child)
        for device in peripherals:
            model = device["model"].lower()
            icon = ICON["mouse"] if "mouse" in model else ICON["keyboard"] if "keyboard" in model else ICON["device"]
            charging = device.get("charging") == "charging"
            chip = Gtk.Box(spacing=5)
            tip = f"{device['model']}: {device['capacity']}%"
            if device.get("headset"):
                icon = ICON["headset"]
                tip += f", {headset.CHARGING_TEXT[device['charging']].lower()}. Click for its settings"
            chip.set_tooltip_text(tip)
            chip.pack_start(label(icon), False, False, 0)
            text = label(f"{device['capacity']}%" + (f" {ICON['charging']}" if charging else ""))
            if device["capacity"] <= ATTENTION_BATTERY and not charging:
                text.get_style_context().add_class("attention")
            chip.pack_start(text, False, False, 0)
            if device.get("headset"):
                button = Gtk.Button(relief=Gtk.ReliefStyle.NONE)
                button.get_style_context().add_class("device")
                button.add(chip)
                button.connect("clicked", lambda _b: self.launch(SOUND_APP + " --page headset"))
                hand_cursor(button)
                chip = button
            self.peripherals_box.pack_start(chip, False, False, 0)
        self.peripherals_box.show_all()
        self.peripherals_box.set_visible(bool(peripherals))

    def _show_battery(self, battery):
        self.battery.set_visible(battery is not None)
        if battery and battery["capacity"] is not None:
            charging = battery["status"] in ("Charging", "Full")
            self.battery_icon.set_text(ICON["charging"] if charging else ICON["battery"])
            self.battery_text.set_text(f"{battery['capacity']}% · {battery['status'].replace('Not charging', 'Plugged in')}")
            self.battery_meter.show_fraction(battery["capacity"] / 100, not charging and battery["capacity"] <= ATTENTION_BATTERY)

    # ---- the level popup ---------------------------------------------------------------------------------------------
    def follow_audio(self):
        """Any change of volume, whoever made it: keys, this tray, an app, or the wheel on a headset."""
        while True:
            try:
                with subprocess.Popen(["pactl", "subscribe"], stdout=subprocess.PIPE, text=True) as client:
                    for line in client.stdout:
                        if " on sink #" in line or " on source #" in line:
                            GLib.idle_add(self._audio_changed)
            except OSError:
                pass
            time.sleep(5)

    def _audio_changed(self):
        if self.osd_timer is None:  # one read for a burst of events
            self.osd_timer = GLib.timeout_add(40, self._read_levels)
        return False

    def _read_levels(self):
        self.osd_timer = None
        background(lambda: {
            "output": (run("pactl", "get-default-sink").strip(), sysinfo.parse_volume(run("wpctl", "get-volume", "@DEFAULT_AUDIO_SINK@"))),
            "input": (run("pactl", "get-default-source").strip(), sysinfo.parse_volume(run("wpctl", "get-volume", "@DEFAULT_AUDIO_SOURCE@")))},
            self._show_levels)
        return False

    def _show_levels(self, levels):
        for key, icons in (("output", (ICON["volume"], ICON["volume_off"])), ("input", (ICON["mic"], ICON["mic_off"]))):
            device, level = levels[key]
            before = self.levels.get(key)
            self.levels[key] = (device, level)
            # Nothing on start-up or when the device itself changes, and the panel's sliders already show their value
            if before and before[0] == device and before[1] != level and level and not self.get_visible():
                self.osd.flash(icons[1] if level[1] else icons[0], level[0], level[1])
                if key == "output" and not self.dnd:
                    play("audio-volume-change")
        return False

    def brightness_changed(self):
        """Told by the brightness keys' binding (SIGUSR1): the kernel gives no event for it that a program can wait on."""
        def read():
            try:
                return round(100 * int(run("brightnessctl", "get")) / int(run("brightnessctl", "max")))
            except (ValueError, ZeroDivisionError):
                return None
        background(read, lambda percent: percent is not None and self.osd.flash(ICON["brightness"], percent))
        return True

    # ---- colours --------------------------------------------------------------------------------------------------
    def load_css(self):
        screen = Gdk.Screen.get_default()
        base = Gtk.CssProvider()
        base.load_from_data((DEFAULT_THEME + CSS).encode())
        Gtk.StyleContext.add_provider_for_screen(screen, base, Gtk.STYLE_PROVIDER_PRIORITY_USER)
        self.theme = Gtk.CssProvider()
        self._load_theme()
        Gtk.StyleContext.add_provider_for_screen(screen, self.theme, Gtk.STYLE_PROVIDER_PRIORITY_USER + 1)
        self.touch_css = Gtk.CssProvider()  # filled when the panel opens, in touch mode
        Gtk.StyleContext.add_provider_for_screen(screen, self.touch_css, Gtk.STYLE_PROVIDER_PRIORITY_USER + 2)
        # Follows the wallpaper and the Theme page: both end up rewriting theme.css
        self.monitor = Gio.File.new_for_path(str(THEME)).monitor_file(Gio.FileMonitorFlags.WATCH_MOVES, None)
        self.monitor.connect("changed", lambda *_a: self._load_theme())

    def _load_theme(self):
        try:
            self.theme.load_from_path(str(THEME))
        except GLib.Error:
            self.theme.load_from_data(b"")  # missing, or half written: the defaults show until the next write


POWER_STATUS = Path("/run/hyprdots-power/status.json")  # from hyprdots-power.service (install/power/powerd.py)


class PowerNotices:
    """Says when the heat guard holds the CPU or graphics card back, and when it lets go. Only events from after the
    tray started: a restart of the tray does not repeat old ones."""
    def __init__(self):
        self.seen = time.time()

    def check(self):
        try:
            events = json.loads(POWER_STATUS.read_text()).get("events", [])
        except (OSError, ValueError, AttributeError):
            return True
        for e in events:
            if e.get("time", 0) > self.seen:
                urgency = "critical" if "held back" in e.get("text", "") else "normal"
                subprocess.Popen(["notify-send", "-u", urgency, "-a", "Heat guard", "-i", "temperature-symbolic", "Heat guard", e["text"]])
        self.seen = max([self.seen] + [e.get("time", 0) for e in events])
        return True


def main():
    lock = open(LOCK, "w")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        return 0  # already running
    tray = Tray()
    tray.load_css()
    tray.connect("delete-event", lambda *_a: True)
    threading.Thread(target=tray.follow_swaync, daemon=True).start()
    threading.Thread(target=tray.follow_audio, daemon=True).start()
    tray._read_levels()
    # From keybinds.lua; a signal because starting anything slower would make Alt+Tab lag
    GLibUnix.signal_add(GLib.PRIORITY_DEFAULT, signal.SIGUSR1, tray.brightness_changed)
    GLibUnix.signal_add(GLib.PRIORITY_DEFAULT, signal.SIGUSR2, lambda: tray.switcher.step(1) or True)
    GLibUnix.signal_add(GLib.PRIORITY_DEFAULT, signal.SIGWINCH, lambda: tray.switcher.step(-1) or True)
    GLibUnix.signal_add(GLib.PRIORITY_DEFAULT, signal.SIGHUP, lambda: tray.overview.toggle() or True)
    GLib.timeout_add_seconds(5, PowerNotices().check)
    Gtk.main()
    return 0


if __name__ == "__main__":
    sys.exit(main())
