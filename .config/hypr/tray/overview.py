"""Workspace overview (Super+Tab): every workspace at once with live pictures of its windows, in the quick tray's
process. Click a window to go to it, a workspace to go there, or drag a window to move it. Arrows and Enter work too,
as do the number keys, and Escape or a click on the background closes it. Pictures come from grim, which can capture a
window on a hidden workspace; icons stand in until they arrive, or when an app cannot be captured."""
import json
import math
import subprocess
from concurrent.futures import ThreadPoolExecutor

import cairo  # noqa: F401  (needed for GTK's drawing callback)
import gi
gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
gi.require_version("GdkPixbuf", "2.0")
gi.require_version("GtkLayerShell", "0.1")
from gi.repository import Gdk, GdkPixbuf, GLib, Gtk, GtkLayerShell

from popups import app_icon, label

MAX_COLUMNS = 4
CARD_WIDTH = 620  # at most
GAP = 16
RADIUS = 8
DRAG_TARGET = "hypr-window"


def hypr(what):
    try:
        return json.loads(subprocess.run(["hyprctl", what, "-j"], capture_output=True, text=True, timeout=2).stdout)
    except (OSError, subprocess.SubprocessError, ValueError):
        return []


def layout_columns(count):
    return min(MAX_COLUMNS, max(1, math.ceil(math.sqrt(count))))


def workspace_list(workspaces, clients, active):
    """Numbers to show: those with windows, the ones on screen, and a free one to move windows to."""
    numbers = {w["id"] for w in workspaces if w.get("id", 0) > 0 and w.get("windows")} | {a for a in active if a > 0}
    numbers |= {c["workspace"]["id"] for c in clients if c["workspace"]["id"] > 0}
    free = 1
    while free in numbers:
        free += 1
    return sorted(numbers | {free})


class Thumb(Gtk.DrawingArea):
    """One window, drawn at the place and size it has on its workspace."""

    def __init__(self, window, owner):
        super().__init__()
        self.window_info, self.owner = window, owner
        self.pixbuf = None
        self.set_tooltip_text(window["title"] or window["class"])
        self.connect("draw", self._draw)
        self.add_events(Gdk.EventMask.BUTTON_PRESS_MASK | Gdk.EventMask.BUTTON_RELEASE_MASK)
        self.connect("button-release-event", self._released)
        self.drag_source_set(Gdk.ModifierType.BUTTON1_MASK, [Gtk.TargetEntry.new(DRAG_TARGET, Gtk.TargetFlags.SAME_APP, 0)],
                             Gdk.DragAction.MOVE)
        self.connect("drag-data-get", lambda _w, _c, data, _i, _t: data.set_text(window["address"], -1))

    def _released(self, _w, event):
        if event.button == 1:
            self.owner.go_to_window(self.window_info["address"])
        return True

    def _draw(self, area, cr):
        width, height = area.get_allocated_width(), area.get_allocated_height()
        r = min(RADIUS, width / 2, height / 2)
        cr.new_path()
        cr.arc(width - r, r, r, -math.pi / 2, 0)
        cr.arc(width - r, height - r, r, 0, math.pi / 2)
        cr.arc(r, height - r, r, math.pi / 2, math.pi)
        cr.arc(r, r, r, math.pi, 3 * math.pi / 2)
        cr.close_path()
        cr.clip()
        ok, colour = area.get_style_context().lookup_color("tray_card")
        cr.set_source_rgba(*((colour.red, colour.green, colour.blue, 1) if ok else (0.2, 0.2, 0.2, 1)))
        cr.paint()
        if self.pixbuf:
            cr.save()
            cr.scale(width / self.pixbuf.get_width(), height / self.pixbuf.get_height())
            Gdk.cairo_set_source_pixbuf(cr, self.pixbuf, 0, 0)
            cr.paint()
            cr.restore()
        # The app's icon: in the middle until the picture comes, then small in the corner
        size = max(12, min(40, int(min(width, height) / 2))) if not self.pixbuf else max(12, min(22, int(min(width, height) / 3)))
        info = Gtk.IconTheme.get_default().lookup_by_gicon(app_icon(self.window_info["class"]), size, 0)
        if info:
            try:
                icon = info.load_icon()
            except GLib.Error:
                return False
            x, y = (width - size) / 2, (height - size) / 2
            if self.pixbuf:
                x, y = width - size - 4, height - size - 4
            Gdk.cairo_set_source_pixbuf(cr, icon, x, y)
            cr.paint()
        return False


class Overview(Gtk.Window):
    def __init__(self):
        super().__init__()
        self.set_title("Quick tray overview")
        self.cards, self.at = [], 0
        self.pictures = {}  # last picture of each window: shown at once next time, then replaced
        self.generation = 0  # a capture that finishes after the overview was closed or reopened is dropped
        self.pool = ThreadPoolExecutor(max_workers=4)
        GtkLayerShell.init_for_window(self)
        GtkLayerShell.set_namespace(self, "quick-tray-overview")
        GtkLayerShell.set_layer(self, GtkLayerShell.Layer.OVERLAY)
        GtkLayerShell.set_keyboard_mode(self, GtkLayerShell.KeyboardMode.EXCLUSIVE)
        GtkLayerShell.set_exclusive_zone(self, -1)
        for edge in (GtkLayerShell.Edge.TOP, GtkLayerShell.Edge.BOTTOM, GtkLayerShell.Edge.LEFT, GtkLayerShell.Edge.RIGHT):
            GtkLayerShell.set_anchor(self, edge, True)
        back = Gtk.EventBox()
        back.set_name("overview")
        back.connect("button-release-event", lambda *_a: self.close_overview() or True)
        self.grid = Gtk.Grid(column_spacing=GAP, row_spacing=GAP)
        self.grid.set_halign(Gtk.Align.CENTER)
        self.grid.set_valign(Gtk.Align.CENTER)
        back.add(self.grid)
        self.add(back)
        back.show_all()
        self.connect("key-press-event", self._key)

    def toggle(self):
        if self.get_visible():
            self.close_overview()
        else:
            self.open_overview()

    def close_overview(self):
        self.generation += 1
        self.hide()

    def open_overview(self):
        monitors = hypr("monitors")
        if not monitors:
            return
        clients = [c for c in hypr("clients") if c.get("mapped") and not c["workspace"]["name"].startswith("special")]
        workspaces = hypr("workspaces")
        focused = next((m for m in monitors if m["focused"]), monitors[0])
        active = [m["activeWorkspace"]["id"] for m in monitors]
        numbers = workspace_list(workspaces, clients, active)
        by_monitor = {m["name"]: m for m in monitors}
        where = {w["id"]: w["monitor"] for w in workspaces if "id" in w}  # special workspaces have no number
        for child in self.grid.get_children():
            self.grid.remove(child)
        columns = layout_columns(len(numbers))
        width = min(CARD_WIDTH, int((focused["width"] / focused["scale"] * 0.92 - GAP * (columns - 1)) / columns))
        thumbs = []
        self.cards = []
        for i, number in enumerate(numbers):
            monitor = by_monitor.get(where.get(number), focused)
            on_it = [c for c in clients if c["workspace"]["id"] == number]
            card, added = self._card(number, monitor, on_it, width, number in active, len(monitors) > 1 and number in where)
            self.grid.attach(card, i % columns, i // columns, 1, 1)
            self.cards.append((card, number))
            thumbs += added
        self.grid.show_all()
        self._select(next((i for i, (_c, n) in enumerate(self.cards) if n == focused["activeWorkspace"]["id"]), 0))
        self.show()
        self.generation += 1
        for thumb, scale in thumbs:
            self.pool.submit(self._capture, thumb, scale, self.generation)

    def _card(self, number, monitor, windows, width, on_screen, name_monitor):
        scale = (width - 16) / (monitor["width"] / monitor["scale"])
        card = Gtk.EventBox()
        card.get_style_context().add_class("ws-card")
        if on_screen:
            card.get_style_context().add_class("current")
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        head = Gtk.Box(spacing=8)
        head.pack_start(label(str(number), "tile-title"), False, False, 0)
        hint = monitor["name"] if name_monitor else ("Empty" if not windows else "")
        head.pack_start(label(hint, "dim"), False, False, 0)
        box.pack_start(head, False, False, 0)
        area = Gtk.Fixed()
        area.set_size_request(width - 16, int(monitor["height"] / monitor["scale"] * scale))
        added = []
        for window in windows:
            thumb = Thumb(window, self)
            thumb.pixbuf = self.pictures.get(window["stableId"])
            w, h = max(8, int(window["size"][0] * scale)), max(8, int(window["size"][1] * scale))
            thumb.set_size_request(w, h)
            area.put(thumb, int((window["at"][0] - monitor["x"]) * scale), int((window["at"][1] - monitor["y"]) * scale))
            added.append((thumb, min(1.0, (w * 2) / max(1, window["size"][0]))))  # twice as sharp as needed, for HiDPI
        box.pack_start(area, False, False, 0)
        card.add(box)
        card.connect("button-release-event", lambda _w, _e, n=number: self.go_to_workspace(n) or True)
        card.drag_dest_set(Gtk.DestDefaults.ALL, [Gtk.TargetEntry.new(DRAG_TARGET, Gtk.TargetFlags.SAME_APP, 0)], Gdk.DragAction.MOVE)
        card.connect("drag-data-received", lambda _w, _c, _x, _y, data, _i, _t, n=number: self.move_window(data.get_text(), n))
        return card, added

    def _capture(self, thumb, scale, generation):
        info = thumb.window_info
        try:
            data = subprocess.run(["grim", "-s", f"{scale:.3f}", "-t", "ppm", "-T", info["stableId"], "-"],
                                  capture_output=True, timeout=5).stdout
        except (OSError, subprocess.SubprocessError):
            return
        if data:
            GLib.idle_add(self._show_picture, thumb, data, generation)

    def _show_picture(self, thumb, data, generation):
        loader = GdkPixbuf.PixbufLoader()
        try:
            loader.write(data)
            loader.close()
        except GLib.Error:
            return False
        picture = loader.get_pixbuf()
        self.pictures[thumb.window_info["stableId"]] = picture
        if generation == self.generation:
            thumb.pixbuf = picture
            thumb.queue_draw()
        return False

    def go_to_window(self, address):
        self.close_overview()
        subprocess.Popen(["hyprctl", "dispatch", f'hl.dsp.focus({{ window = "address:{address}" }})'], stdout=subprocess.DEVNULL)

    def go_to_workspace(self, number):
        self.close_overview()
        subprocess.Popen(["hyprctl", "dispatch", f"hl.dsp.focus({{ workspace = {number} }})"], stdout=subprocess.DEVNULL)

    def move_window(self, address, number):
        """Stays open, showing the window in its new place."""
        subprocess.run(["hyprctl", "dispatch", f'hl.dsp.window.move({{ workspace = {number}, window = "address:{address}", follow = false }})'],
                       capture_output=True, timeout=2)
        self.open_overview()

    def _select(self, index):
        self.at = index
        for i, (card, _n) in enumerate(self.cards):
            ctx = card.get_style_context()
            (ctx.add_class if i == index else ctx.remove_class)("on")

    def _key(self, _w, event):
        key, count = event.keyval, len(self.cards)
        columns = layout_columns(count)
        steps = {Gdk.KEY_Right: 1, Gdk.KEY_Left: -1, Gdk.KEY_Down: columns, Gdk.KEY_Up: -columns}
        if key == Gdk.KEY_Escape:
            self.close_overview()
        elif key in steps:
            self._select((self.at + steps[key]) % count)
        elif key == Gdk.KEY_Return:
            self.go_to_workspace(self.cards[self.at][1])
        elif Gdk.KEY_1 <= key <= Gdk.KEY_9:
            self.go_to_workspace(key - Gdk.KEY_0)
        return True
