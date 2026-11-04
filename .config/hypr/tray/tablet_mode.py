#!/usr/bin/env python3
"""Tablet mode, as a service (systemd/hyprdots-tablet.service): with no keyboard attached the on-screen keyboard comes up
for text fields and the built-in screen follows the rotation sensor; with one attached, neither, and the screen goes back to
how it was set. The tray's Rotation lock tile holds the screen still (a file, so this and the tray need not talk).
Hyprland turns a screen in one jump, so a black layer fades in over it first and out again after (see ScreenFade).
squeekboard has no key to put itself away, so in tablet mode a small button sits above it (see KeyboardButton).
Touchscreen gestures run here too, with or without a keyboard (touch_gestures.py).
Ends straight away on a PC without a touchscreen. Keyboards come and go without an event a program can wait on cheaply,
so /proc/bus/input/devices is read every 2 seconds, and Hyprland is asked only for a few ticks after that changes: the
kernel knows of a keyboard before Hyprland does, so asking once can get the old answer."""
import json
import re
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path

import touch_gestures
import touch_lift

import cairo
import gi
gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
gi.require_version("GtkLayerShell", "0.1")
from gi.repository import Gdk, Gio, GLib, GLibUnix, Gtk, GtkLayerShell  # noqa: E402

ROTATION_LOCK = Path.home() / ".local/state/hyprdots/rotation-locked"
INPUT_DEVICES = Path("/proc/bus/input/devices")
# Things that report as keyboards but cannot type. The lock screen has the same list (scripts/lock-screen.sh).
NOT_A_KEYBOARD = re.compile(r"button|video-bus|consumer|audio|power|sleep|hotkey|virtual|wmi")
TRANSFORMS = {"normal": 0, "left-up": 1, "bottom-up": 2, "right-up": 3}  # iio-sensor-proxy's words, Hyprland's numbers
ORIENTATION = re.compile(r"(?:orientation changed: |orientation: )([a-z-]+)")
TICK_MS = 2000
# Long enough for Hyprland's layersIn fade (window.lua) to darken the screen, and for the screen to settle before fading back
FADE_IN_MS = 170
SETTLE_MS = 90
ASK_TICKS = 3  # how many ticks Hyprland is asked after input devices change
BUTTON_MARGIN = 12


def run(*args: str) -> str:
    try:
        return subprocess.run(args, capture_output=True, text=True, timeout=5).stdout
    except (OSError, subprocess.SubprocessError):
        return ""


def devices() -> dict:
    try:
        return json.loads(run("hyprctl", "devices", "-j") or "{}")
    except json.JSONDecodeError:
        return {}


def has_keyboard(found: dict) -> bool:
    return any(not NOT_A_KEYBOARD.search(k.get("name", "")) for k in found.get("keyboards", []))


def orientation_in(line: str) -> str | None:
    """The orientation in a line of monitor-sensor's output, if it gives one that can be applied."""
    match = ORIENTATION.search(line)
    return match.group(1) if match and match.group(1) in TRANSFORMS else None


def built_in_screen(monitors: list[dict]) -> dict | None:
    return next((m for m in monitors if m.get("name", "").startswith(("eDP", "LVDS", "DSI"))), None)


def monitor_lua(m: dict, transform: int) -> str:
    return (f'hl.monitor({{ output = "{m["name"]}", mode = "{m["width"]}x{m["height"]}@{m["refreshRate"]:.2f}", '
            f'position = "{m["x"]}x{m["y"]}", scale = {m["scale"]}, transform = {transform} }})')


def screen_to_rotate(transform: int) -> dict | None:
    """The built-in screen, if it is not turned that way already."""
    try:
        screen = built_in_screen(json.loads(run("hyprctl", "monitors", "-j") or "[]"))
    except json.JSONDecodeError:
        return None
    return screen if screen and screen.get("transform") != transform else None


def rotate(transform: int) -> None:
    if (screen := screen_to_rotate(transform)):
        run("hyprctl", "eval", monitor_lua(screen, transform))


class InputWatch:
    """Whether to ask Hyprland about keyboards, given what the kernel lists now."""

    def __init__(self) -> None:
        self.seen = None
        self.asks_left = 0

    def should_ask(self, now: str) -> bool:
        if now != self.seen:
            self.seen = now
            self.asks_left = ASK_TICKS
        if self.asks_left:
            self.asks_left -= 1
            return True
        return False


def button_margin(layers: dict) -> int:
    """How far up from the bottom the button goes: above the keyboard while it is up. hyprctl layers -j gives the layers."""
    heights = [surface.get("h", 0) for monitor in layers.values() for level in monitor.get("levels", {}).values()
               for surface in level if surface.get("namespace") == "osk"]
    return BUTTON_MARGIN + max(heights, default=0)


class KeyboardButton(Gtk.Window):
    """Puts squeekboard away and brings it back, through the switch it offers on D-Bus."""

    def __init__(self):
        super().__init__()
        self.proxy = None
        self.margin = None
        GtkLayerShell.init_for_window(self)
        GtkLayerShell.set_namespace(self, "tablet-keyboard-button")
        GtkLayerShell.set_layer(self, GtkLayerShell.Layer.OVERLAY)
        GtkLayerShell.set_keyboard_mode(self, GtkLayerShell.KeyboardMode.NONE)
        GtkLayerShell.set_anchor(self, GtkLayerShell.Edge.RIGHT, True)
        GtkLayerShell.set_anchor(self, GtkLayerShell.Edge.BOTTOM, True)
        GtkLayerShell.set_margin(self, GtkLayerShell.Edge.RIGHT, BUTTON_MARGIN)
        self.button = Gtk.Button(label="\u2328")
        self.button.set_can_focus(False)  # the text field keeps the focus, or the keyboard would close by itself
        self.button.set_tooltip_text("Show or hide the on-screen keyboard")
        self.button.connect("clicked", self.toggle)
        self.add(self.button)
        css = Gtk.CssProvider()
        css.load_from_data(b"""
            window { background: transparent; }
            button { min-width: 56px; min-height: 56px; padding: 0 16px; border: none; border-radius: 28px; box-shadow: none;
                     background-image: none; background-color: #70CFB3; color: black; font-size: 20px; font-weight: bold; }
            button:active { background-color: white; }
        """)
        for widget in (self, self.button):
            widget.get_style_context().add_provider(css, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)

    def present_for(self, wanted: bool) -> None:
        if wanted:
            self.proxy = self.proxy or Gio.DBusProxy.new_for_bus_sync(
                Gio.BusType.SESSION, Gio.DBusProxyFlags.DO_NOT_AUTO_START, None, "sm.puri.OSK0", "/sm/puri/OSK0", "sm.puri.OSK0", None)
            self.proxy.connect("g-properties-changed", lambda *_a: GLib.timeout_add(250, self.update))
            self.show_all()
            self.update()
        else:
            self.proxy = None
            self.hide()

    def visible(self) -> bool:
        value = self.proxy.get_cached_property("Visible") if self.proxy else None
        return bool(value and value.get_boolean())

    def toggle(self, _button) -> None:
        if self.proxy:
            self.proxy.call("SetVisible", GLib.Variant("(b)", (not self.visible(),)), Gio.DBusCallFlags.NONE, -1, None, None)

    def update(self) -> bool:
        """After the keyboard comes or goes, and every tick: it changes height when the screen turns."""
        self.button.set_label("Hide keyboard \u25be" if self.visible() else "\u2328")
        try:
            margin = button_margin(json.loads(run("hyprctl", "layers", "-j") or "{}"))
        except json.JSONDecodeError:
            margin = BUTTON_MARGIN
        if margin != self.margin:
            self.margin = margin
            GtkLayerShell.set_margin(self, GtkLayerShell.Edge.BOTTOM, margin)
        return False


class ScreenFade(Gtk.Window):
    """Hyprland does the fading, as for any layer: this only shows a black layer, turns the screen, and hides it again."""

    def __init__(self):
        super().__init__()
        self.turning = False
        GtkLayerShell.init_for_window(self)
        GtkLayerShell.set_namespace(self, "tablet-rotate")
        GtkLayerShell.set_layer(self, GtkLayerShell.Layer.OVERLAY)
        GtkLayerShell.set_keyboard_mode(self, GtkLayerShell.KeyboardMode.NONE)
        GtkLayerShell.set_exclusive_zone(self, -1)
        for edge in (GtkLayerShell.Edge.TOP, GtkLayerShell.Edge.BOTTOM, GtkLayerShell.Edge.LEFT, GtkLayerShell.Edge.RIGHT):
            GtkLayerShell.set_anchor(self, edge, True)
        css = Gtk.CssProvider()
        css.load_from_data(b"window { background: black; }")
        self.get_style_context().add_provider(css, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
        self.connect("map", lambda _w: self.input_shape_combine_region(cairo.Region()))  # touches go straight through

    def on_screen(self, screen: dict) -> None:
        display = Gdk.Display.get_default()
        for index in range(display.get_n_monitors()):
            monitor = display.get_monitor(index)
            if monitor.get_model() == screen.get("model"):
                GtkLayerShell.set_monitor(self, monitor)

    def rotate(self, transform: int) -> None:
        screen = None if self.turning else screen_to_rotate(transform)
        if not screen:
            return  # one turning already: the next tick catches up, should the sensor have moved on
        self.turning = True
        self.on_screen(screen)
        self.show()
        GLib.timeout_add(FADE_IN_MS, self.turn, screen, transform)

    def turn(self, screen: dict, transform: int) -> bool:
        run("hyprctl", "eval", monitor_lua(screen, transform))
        GLib.timeout_add(SETTLE_MS, self.finish)
        return False

    def finish(self) -> bool:
        self.hide()
        self.turning = False
        return False


class TabletMode:
    def __init__(self) -> None:
        self.tablet: bool | None = None
        self.keyboard: subprocess.Popen | None = None
        self.orientation = "normal"
        self.turn_to = rotate
        self.button = None

    def on_screen_keyboard(self, wanted: bool) -> None:
        run("gsettings", "set", "org.gnome.desktop.a11y.applications", "screen-keyboard-enabled", "true" if wanted else "false")
        if wanted and not (self.keyboard and self.keyboard.poll() is None) and shutil.which("squeekboard"):
            self.keyboard = subprocess.Popen(["squeekboard"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        elif not wanted and self.keyboard:
            self.keyboard.terminate()
            self.keyboard.wait(timeout=5)
            self.keyboard = None

    def set_tablet(self, tablet: bool) -> None:
        if tablet == self.tablet:
            return
        self.tablet = tablet
        self.on_screen_keyboard(tablet)
        if self.button:
            self.button.present_for(tablet)
        self.follow_sensor()

    def follow_sensor(self) -> None:
        """Also every tick while in tablet mode: reloading the config puts the screen back."""
        if not self.tablet:
            self.turn_to(0)
        elif not ROTATION_LOCK.exists():
            self.turn_to(TRANSFORMS[self.orientation])

    def stop(self) -> None:
        self.on_screen_keyboard(False)
        rotate(0)


def main() -> int:
    if not devices().get("touch"):
        return 0
    mode = TabletMode()
    mode.turn_to = ScreenFade().rotate
    mode.button = KeyboardButton()
    watch = InputWatch()
    touch = [None]
    timing = [False]

    def resting() -> bool:
        """While fingers are down: resting ones send no events, but picking up happens after holding still."""
        gestures = touch[0][1].gestures
        gestures.frame(time.time())
        timing[0] = bool(gestures.fingers)
        return timing[0]

    def touched(*_args) -> bool:
        keep = touch_gestures.read_events(*touch[0])
        if touch[0][1].gestures.fingers and not timing[0]:
            timing[0] = True
            GLib.timeout_add(100, resting)
        return keep

    def tick() -> bool:
        if not touch[0]:  # again each tick: access can arrive just after login
            touch[0] = touch_gestures.open_touchscreen()
            if touch[0]:
                lift = touch_lift.Lift()
                touch[0][1].gestures.act = lambda name, *where: getattr(lift, name)(*where) if hasattr(lift, name) else touch_gestures.perform(name)
                GLib.io_add_watch(touch[0][0], GLib.PRIORITY_DEFAULT, GLib.IO_IN | GLib.IO_HUP | GLib.IO_ERR, touched)
        screen = touch_gestures.built_in(touch_gestures.hypr_json("monitors")) if touch[0] else None
        if screen:
            touch[0][1].set_screen(screen)
        if watch.should_ask(INPUT_DEVICES.read_text()):
            mode.set_tablet(not has_keyboard(devices()))
        if mode.tablet:
            mode.follow_sensor()
            mode.button.update()
        return True

    def sensor_says(stream, _condition) -> bool:
        line = stream.readline()
        if not line:  # the sensor program ended: stop watching it, the rest still works
            return False
        if (found := orientation_in(line)):
            mode.orientation = found
            mode.follow_sensor()
        return True

    sensor = None
    if shutil.which("monitor-sensor"):
        sensor = subprocess.Popen(["monitor-sensor", "--accel"], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, bufsize=1)
        GLib.io_add_watch(sensor.stdout, GLib.PRIORITY_DEFAULT, GLib.IO_IN | GLib.IO_HUP, sensor_says)
    GLibUnix.signal_add(GLib.PRIORITY_DEFAULT, signal.SIGTERM, Gtk.main_quit)
    tick()
    GLib.timeout_add(TICK_MS, tick)
    try:
        Gtk.main()
    finally:
        if sensor:
            sensor.terminate()
        touch_gestures.set_apps_touch(True)
        mode.stop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
