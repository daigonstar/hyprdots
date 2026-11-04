"""Picking a window up to throw it away, for touch_gestures.py: hold it with two fingers and a small copy lifts off under them
with a shadow, while a red bin appears over the bar's middle island. Bring the picture over the bin, which says when it is ready,
and let go to close the window; let go anywhere else to put it back. Hyprland cannot move a tiled window under a finger, so what moves is a picture: the window stays where it was
until it is closed, and closing is the normal kind, so an app can still ask to save."""
import subprocess
import threading

import cairo
import gi
gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
gi.require_version("GtkLayerShell", "0.1")
gi.require_version("GdkPixbuf", "2.0")
from gi.repository import GdkPixbuf, GLib, Gtk, GtkLayerShell  # noqa: E402

import touch_gestures  # noqa: E402
import touch_mode  # noqa: E402

COPY_WIDTH = 320      # the picture's size under the fingers
PADDING = 48          # around the picture, for its shadow
BIN_WIDTH = 300
BIN_HEIGHT = 38
BIN_TOP = 3

CSS = b"""
#lift-window { background: transparent; }
#lift-copy { margin: 48px; border-radius: 12px; box-shadow: 0 18px 40px rgba(0, 0, 0, 0.75), 0 0 0 1px rgba(255, 255, 255, 0.25); }
#bin-window { background: transparent; }
#bin { border-radius: 19px; background-color: #b3261e; color: white; font-weight: bold; }
#bin.over { background-color: #ff3b30; box-shadow: 0 0 18px 4px rgba(255, 59, 48, 0.9); }
#lift-copy.over { box-shadow: 0 0 0 4px #ff3b30, 0 0 34px 10px rgba(255, 59, 48, 0.75); }
"""


def over_bin(x: float, y: float, size: tuple[int, int], screen: tuple[float, float], at_bottom: bool = False) -> bool:
    """Whether the picture, centred on the fingers, overlaps the bin, which is over the bar's middle: at the top, or at the bottom."""
    width, height = screen
    across = abs(x - width / 2) <= (BIN_WIDTH + size[0]) / 2
    if at_bottom:
        return across and y + size[1] / 2 >= height - BIN_TOP - BIN_HEIGHT
    return across and y - size[1] / 2 <= BIN_TOP + BIN_HEIGHT


def copy_size(width: int, height: int) -> tuple[int, int]:
    """The picture's size: the window's shape, COPY_WIDTH across, or less so that a tall one fits under the fingers."""
    scale = min(COPY_WIDTH / max(1, width), COPY_WIDTH / max(1, height))
    return max(1, round(width * scale)), max(1, round(height * scale))


def layer(name: str, namespace: str) -> Gtk.Window:
    window = Gtk.Window()
    window.set_name(name)
    GtkLayerShell.init_for_window(window)
    GtkLayerShell.set_namespace(window, namespace)
    GtkLayerShell.set_layer(window, GtkLayerShell.Layer.OVERLAY)
    GtkLayerShell.set_keyboard_mode(window, GtkLayerShell.KeyboardMode.NONE)
    GtkLayerShell.set_exclusive_zone(window, -1)  # both go over the bar, which Hyprland otherwise keeps them out of
    window.connect("map", lambda w: w.input_shape_combine_region(cairo.Region()))  # touches go straight through
    return window


def style(*widgets) -> None:
    css = Gtk.CssProvider()
    css.load_from_data(CSS)
    for widget in widgets:
        widget.get_style_context().add_provider(css, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)


class Lift:
    def __init__(self):
        self.address = None
        self.over = False
        self.screen = (0.0, 0.0)
        self.at_bottom = False
        self.size = (0, 0)
        self.copy_window = layer("lift-window", "touch-lift")
        GtkLayerShell.set_anchor(self.copy_window, GtkLayerShell.Edge.TOP, True)
        GtkLayerShell.set_anchor(self.copy_window, GtkLayerShell.Edge.LEFT, True)
        self.copy = Gtk.Image()
        self.copy.set_name("lift-copy")
        self.copy_window.add(self.copy)
        self.bin_window = layer("bin-window", "touch-bin")
        GtkLayerShell.set_anchor(self.bin_window, GtkLayerShell.Edge.TOP, True)
        GtkLayerShell.set_margin(self.bin_window, GtkLayerShell.Edge.TOP, BIN_TOP)
        self.bin = Gtk.Label(label="Drop here to close")
        self.bin.set_name("bin")
        self.bin.set_size_request(BIN_WIDTH, BIN_HEIGHT)
        self.bin_window.add(self.bin)
        style(self.copy_window, self.copy, self.bin_window, self.bin)
        self.copy.show()
        self.bin.show()

    def picture(self, client: dict, size: tuple[int, int]) -> GdkPixbuf.Pixbuf | None:
        (x, y), (width, height) = client["at"], client["size"]
        try:
            data = subprocess.run(["grim", "-g", f"{x},{y} {width}x{height}", "-s", f"{size[0] / width:.3f}", "-t", "ppm", "-"],
                                  capture_output=True, timeout=5).stdout
            loader = GdkPixbuf.PixbufLoader()
            loader.write(data)
            loader.close()
            return loader.get_pixbuf().scale_simple(*size, GdkPixbuf.InterpType.BILINEAR)
        except (OSError, subprocess.SubprocessError, TypeError, AttributeError, GLib.Error):
            return None

    def pickup(self, x: float, y: float) -> None:
        screen = touch_gestures.built_in(touch_gestures.hypr_json("monitors"))
        client = touch_gestures.client_at(touch_gestures.hypr_json("clients") or [], screen["activeWorkspace"]["id"], x, y) if screen else None
        print(f"Gesture: pick up {client['title'] if client else 'nothing: no window under the fingers'}", flush=True)
        if not client:
            return
        self.address = client["address"]
        turned = screen.get("transform", 0) % 2
        self.screen = tuple(side / screen["scale"] for side in ((screen["height"], screen["width"]) if turned else (screen["width"], screen["height"])))
        self.at_bottom = touch_mode.active()  # where the bar is
        GtkLayerShell.set_anchor(self.bin_window, GtkLayerShell.Edge.TOP, not self.at_bottom)
        GtkLayerShell.set_anchor(self.bin_window, GtkLayerShell.Edge.BOTTOM, self.at_bottom)
        GtkLayerShell.set_margin(self.bin_window, GtkLayerShell.Edge.BOTTOM, BIN_TOP)
        self.size = copy_size(*client["size"])
        # The app under two resting fingers may have opened a right-click menu by now, which nothing can stop it doing
        subprocess.Popen(["wtype", "-k", "Escape"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.copy.clear()
        self.copy.set_size_request(*self.size)
        self.carry(x, y)
        self.copy_window.show()
        self.bin_window.show()  # after, so that it is on top: the picture passes under it, and it can still be read
        # Not here: taking the picture takes a quarter of a second, and while nothing reads the touchscreen its events are lost
        threading.Thread(target=self.fetch_picture, args=(client, self.size, self.address), daemon=True).start()

    def fetch_picture(self, client: dict, size: tuple[int, int], address: str) -> None:
        picture = self.picture(client, size)
        if picture:
            GLib.idle_add(self.show_picture, picture, address)

    def show_picture(self, picture: GdkPixbuf.Pixbuf, address: str) -> bool:
        if address == self.address:  # not if it has been let go already
            self.copy.set_from_pixbuf(picture)
        return False

    def carry(self, x: float, y: float) -> None:
        if not self.address:
            return
        # Under the fingers, even past the top of the screen, so that it can reach the bin. Moving it costs far less than redrawing
        GtkLayerShell.set_margin(self.copy_window, GtkLayerShell.Edge.LEFT, round(x - self.size[0] / 2 - PADDING))
        GtkLayerShell.set_margin(self.copy_window, GtkLayerShell.Edge.TOP, round(y - self.size[1] / 2 - PADDING))
        over = over_bin(x, y, self.size, self.screen, self.at_bottom)
        if over != self.over:
            self.over = over
            self.bin.set_text("Release to close" if over else "Drop here to close")
            for widget in (self.bin, self.copy):
                context = widget.get_style_context()
                (context.add_class if over else context.remove_class)("over")

    def drop(self, x: float, y: float) -> None:
        if not self.address:
            return
        address, self.address = self.address, None
        print(f"Gesture: let go at {x:.0f},{y:.0f}, {'on' if over_bin(x, y, self.size, self.screen, self.at_bottom) else 'not on'} the bin", flush=True)
        self.copy_window.hide()
        self.bin_window.hide()
        self.carry_ended()
        if over_bin(x, y, self.size, self.screen, self.at_bottom):
            print(f"Gesture: close {address}", flush=True)
            touch_gestures.dispatch(f'hl.dsp.window.close({{ window = "address:{address}" }})')

    def carry_ended(self) -> None:
        self.over = False
        self.bin.set_text("Drop here to close")
        for widget in (self.bin, self.copy):
            widget.get_style_context().remove_class("over")
