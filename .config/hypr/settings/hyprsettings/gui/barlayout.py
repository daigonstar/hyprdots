"""Bar layout page: a drawing of the bar with a chip per module. Drag a chip to reorder it, to move it to another part
of the bar, or onto the shelf below to take it off the bar (and back). Waits for Save like the other settings; saving
writes waybar/layout.json and restarts the bar."""

from __future__ import annotations

import copy
import subprocess
from pathlib import Path

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
gi.require_version("PangoCairo", "1.0")
from gi.repository import Adw, GLib, Gtk, Pango, PangoCairo  # noqa: E402

from .. import barlayout, theme  # noqa: E402
from . import ui  # noqa: E402

KEY = "Bar layout"
SHELF = "shelf"
CHIP_H = 34
PAD = 8


class Pending:
    """The arrangement being edited, kept on the window until Save or Discard."""

    def __init__(self, store):
        self.store = store
        self.reload()

    def reload(self) -> None:
        self.config = barlayout.read_config()
        self.saved = barlayout.read_layout(self.config)
        self.layout = copy.deepcopy(self.saved)

    def count(self) -> int:
        return 0 if self.layout == self.saved else 1

    def save(self) -> tuple[bool, str]:
        try:
            barlayout.write_layout(self.layout)
            from .. import design
            design.write_bar_theme(self.store)  # hides the parts of the bar this layout leaves empty
        except OSError as e:
            return False, f"Could not save the bar layout: {e}"
        restart_bar()
        self.reload()
        return True, "Bar layout saved. The bar is restarting with it."

    def discard(self) -> None:
        self.reload()

    def shelf(self) -> list[str]:
        placed = {m for z in barlayout.ZONES for m in self.layout[z]}
        return [m for m in barlayout.available(self.config) if m not in placed]


def restart_bar() -> None:
    subprocess.Popen([str(Path.home() / ".config/hypr/scripts/restart.sh"), "waybar"], start_new_session=True,
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def build(win) -> Gtk.Widget:
    try:
        if KEY not in win.pending:
            win.pending[KEY] = Pending(win.store)
    except (OSError, ValueError) as e:
        status = Adw.StatusPage(title="Could not read the bar's config", description=str(e), icon_name="dialog-warning-symbolic")
        return status
    state: Pending = win.pending[KEY]
    scroller, column = ui.page_box("Drag a module to move it along the bar, to another part of it, or down onto the shelf to "
                                   "take it off the bar. Drag it back up to add it again. Saved with the bar below; the bar "
                                   "restarts to show it.")
    column.append(gallery(win, state))
    where = Adw.PreferencesGroup()
    row = Adw.ActionRow(title="Bar position", subtitle="Which edge of the screen the bar sits on.", use_markup=False)
    names = [label for _v, label in barlayout.POSITIONS]
    values = [v for v, _l in barlayout.POSITIONS]
    drop = Gtk.DropDown(model=Gtk.StringList.new(names), valign=Gtk.Align.CENTER)
    drop.set_selected(values.index(state.layout.get("position", "top")))

    def moved(d, _p):
        state.layout["position"] = values[d.get_selected()]
        win.changed()
    drop.connect("notify::selected", moved)
    row.add_suffix(drop)
    where.add(row)
    column.append(where)
    column.append(Editor(win, state))
    actions = Adw.PreferencesGroup()
    reset = Adw.ButtonRow(title="Reset to the default layout", start_icon_name="edit-undo-symbolic")

    def do_reset():
        barlayout.reset_layout()
        from .. import design
        design.write_bar_theme(win.store)
        restart_bar()
        state.reload()
        win.refresh()
        win.toast("The bar is back to its default layout.")
    reset.connect("activated", lambda _r: ui.confirm(win, "Reset the bar layout?",
                                                      "Puts every module back where it started and restarts the bar.",
                                                      "Reset", do_reset, destructive=True))
    actions.add(reset)
    column.append(actions)
    return scroller


def gallery(win, state: Pending) -> Gtk.Widget:
    """Five ready-made layouts. Picking one loads it into the editor below, and its bar style on the Theme page; both
    wait for Save, so it can be adjusted first."""
    from ..schema import BY_ID
    group = Adw.PreferencesGroup(title="Start from a layout",
                                 description="Pick one to load it below, then drag things around if you like and Save.")
    flow = Gtk.FlowBox(selection_mode=Gtk.SelectionMode.NONE, homogeneous=True, min_children_per_line=2,
                       max_children_per_line=5, column_spacing=10, row_spacing=10)
    current_style = win.store.get(BY_ID["theme.bar_style"])[0]
    for key, name, what, _arrangement, _style, _position in barlayout.PRESETS:
        layout, style = barlayout.preset(key, state.config)
        chosen = (layout == state.layout and style == current_style)
        card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        card.append(Gtk.Frame(child=preview(layout, style), css_classes=["card"]))
        card.append(Gtk.Label(label=name + ("  ✓" if chosen else ""), xalign=0.5, css_classes=["heading"]))
        card.append(Gtk.Label(label=what, wrap=True, justify=Gtk.Justification.CENTER, max_width_chars=22,
                              css_classes=["dim-label", "caption"]))
        button = Gtk.Button(child=card, css_classes=["flat"], tooltip_text=f"Load the {name} layout")

        def pick(_b, key=key, name=name):
            layout, style = barlayout.preset(key, state.config)
            state.layout = layout
            win.store.stage(BY_ID["theme.bar_style"], style)
            win.refresh()
            win.toast(f"{name} loaded. Save to put it on your bar.")
        button.connect("clicked", pick)
        flow.append(button)
    group.add(flow)
    return group


def preview(layout: dict, style: str) -> Gtk.DrawingArea:
    """A tiny screen with the bar on it: which parts hold modules, in the preset's style and position."""
    c = theme.colors()
    accent, fg = theme.rgb(c["accent"]), theme.rgb(c["fg"])
    area = Gtk.DrawingArea(content_width=170, content_height=80)

    def draw(_a, cr, w, h):
        cr.set_source_rgba(*fg, 0.06)
        rounded(cr, 2, 2, w - 4, h - 4, 8)
        cr.fill()
        bar_h, inset = 12, 6
        y = h - inset - bar_h if layout.get("position") == "bottom" else inset
        x0, x1 = inset, w - inset
        span = x1 - x0
        if style == "solid":      # one strip across the whole screen
            cr.set_source_rgba(*accent, 0.55)
            cr.rectangle(2, y, w - 4, bar_h)
            cr.fill()
        elif style == "floating":  # one rounded bar with a gap around it
            cr.set_source_rgba(*accent, 0.55)
            rounded(cr, x0, y, span, bar_h, 6)
            cr.fill()
        thirds = {"modules-left": (x0, "left"), "modules-center": (x0 + span / 2, "center"), "modules-right": (x1, "right")}
        for zone, (anchor, side) in thirds.items():
            n = len(layout.get(zone, []))
            if not n:
                continue
            room = span / 3 - 10  # each part keeps to its own third, so the parts never run into each other
            gap = 3 if n < 8 else 2
            dot = max(3.0, min(7.0, (room - gap * (n - 1)) / n))
            width = n * dot + (n - 1) * gap
            start = anchor if side == "left" else anchor - width if side == "right" else anchor - width / 2
            start = max(x0 + 2, min(start, x1 - width - 2)) if side != "left" else start + 3
            if side == "right":
                start -= 3
            if style == "islands":
                cr.set_source_rgba(*accent, 0.55)
                rounded(cr, start - 3, y, width + 6, bar_h, 5)
                cr.fill()
            for i in range(n):
                dx = start + i * (dot + gap)
                if style == "bubbles":
                    cr.set_source_rgba(*accent, 0.55)
                    rounded(cr, dx - 1.5, y, dot + 3, bar_h, 5)
                    cr.fill()
                cr.set_source_rgba(*fg, 0.85)
                cr.arc(dx + dot / 2, y + bar_h / 2, min(2, dot / 3), 0, 6.2832)
                cr.fill()
    area.set_draw_func(draw)
    return area


class Editor(Gtk.Box):
    def __init__(self, win, state: Pending):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        self.win, self.state = win, state
        c = theme.colors()
        self.accent, self.fg = theme.rgb(c["accent"]), theme.rgb(c["fg"])
        self.drag = None   # {"module", "from", "x", "y", "dx", "dy"}
        self.target = None  # (zone, index)
        self.chips: list[tuple[str, str, float, float, float, float]] = []  # zone, module, x, y, w, h
        self.zones: dict[str, tuple[float, float, float, float]] = {}
        self.area = Gtk.DrawingArea(content_height=270, hexpand=True, has_tooltip=True)
        self.area.set_draw_func(self.draw)
        self.area.connect("query-tooltip", self.tooltip)
        g = Gtk.GestureDrag()
        g.connect("drag-begin", self.begin)
        g.connect("drag-update", self.update)
        g.connect("drag-end", self.end)
        self.area.add_controller(g)
        motion = Gtk.EventControllerMotion()
        motion.connect("motion", lambda _c, x, y: self.drag is None and
                       self.area.set_cursor_from_name("grab" if self.hit(x, y) else "default"))
        self.area.add_controller(motion)
        self.append(Gtk.Frame(child=self.area, css_classes=["card"]))

    # ---- layout of the drawing --------------------------------------------------------------------------------
    def place(self, cr, width):
        """Works out every zone and chip rectangle for the current arrangement."""
        self.chips, self.zones = [], {}
        bar_y, shelf_y = 34, 170
        # each part gets room in proportion to how many modules it holds, so a busy side does not overflow
        weights = [max(len([m for m in self.state.layout[z] if not (self.drag and m == self.drag["module"])]), 2) + 1
                   for z in barlayout.ZONES]
        free = width - 2 * PAD - 2 * 10
        x = PAD
        for zone, weight in zip(barlayout.ZONES, weights):
            zone_w = free * weight / sum(weights)
            self.zones[zone] = (x, bar_y, zone_w, CHIP_H + 2 * 8)
            x += zone_w + 10
        self.zones[SHELF] = (PAD, shelf_y, width - 2 * PAD, CHIP_H + 2 * 8)
        for zone in (*barlayout.ZONES, SHELF):
            modules = self.state.shelf() if zone == SHELF else self.state.layout[zone]
            modules = [m for m in modules if not (self.drag and m == self.drag["module"])]
            zx, zy, zw, zh = self.zones[zone]
            widths = [self.chip_width(cr, m, True) for m in modules]
            icons_only = sum(widths) + 6 * len(widths) > zw - 12
            if icons_only:
                widths = [self.chip_width(cr, m, False) for m in modules]
                if modules and sum(widths) + 6 * len(widths) > zw - 12:  # still too many: shrink them to fit
                    widths = [max(20.0, (zw - 12) / len(modules) - 6)] * len(modules)
            x = zx + max(6, (zw - (sum(widths) + 6 * (len(widths) - 1))) / 2)  # centred in its part of the bar
            for m, w in zip(modules, widths):
                self.chips.append((zone, m, x, zy + 8, w, CHIP_H, icons_only))
                x += w + 6

    def chip_text(self, module, with_name):
        name, icon = barlayout.label(module)
        if not with_name:
            return icon or name[:2]
        return f"{icon}  {name}" if icon else name

    def layout_for(self, cr, text):
        lay = PangoCairo.create_layout(cr)
        lay.set_font_description(Pango.FontDescription.from_string(f"{theme.ICON_FONT} 10"))
        lay.set_text(text, -1)
        return lay

    def chip_width(self, cr, module, with_name):
        return self.layout_for(cr, self.chip_text(module, with_name)).get_pixel_size()[0] + 22

    # ---- drawing ----------------------------------------------------------------------------------------------
    def draw(self, _a, cr, width, height):
        self.place(cr, width)
        label = PangoCairo.create_layout(cr)
        label.set_font_description(Pango.FontDescription.from_string("Sans 9"))
        for zone, (x, y, w, h) in self.zones.items():
            title = "Not on the bar" if zone == SHELF else barlayout.ZONE_NAMES[zone]
            label.set_text(title, -1)
            cr.set_source_rgba(*self.fg, 0.55)
            cr.move_to(x + (w - label.get_pixel_size()[0]) / 2, y - 18)
            PangoCairo.show_layout(cr, label)
            rounded(cr, x, y, w, h, 12)
            cr.set_source_rgba(*self.fg, 0.05 if zone == SHELF else 0.08)
            cr.fill_preserve()
            cr.set_source_rgba(*self.accent, 0.9 if self.target and self.target[0] == zone else 0.25)
            cr.set_line_width(2 if self.target and self.target[0] == zone else 1)
            cr.set_dash([5, 4] if zone == SHELF else [])
            cr.stroke()
            cr.set_dash([])
        for zone, module, x, y, w, h, icons_only in self.chips:
            self.draw_chip(cr, module, x, y, w, h, not icons_only, 1.0)
        # the modules of each part by name, in order (the chips may only fit their icons)
        names = PangoCairo.create_layout(cr)
        names.set_font_description(Pango.FontDescription.from_string("Sans 8.5"))
        for zone in (*barlayout.ZONES, SHELF):
            if zone == SHELF and not self.state.shelf():
                continue
            zx, zy, zw, zh = self.zones[zone]
            names.set_width(int((zw - 4) * Pango.SCALE))
            names.set_wrap(Pango.WrapMode.WORD)
            names.set_alignment(Pango.Alignment.CENTER)
            listed = self.state.shelf() if zone == SHELF else self.state.layout[zone]
            names.set_text("  ·  ".join(barlayout.label(m)[0] for m in listed) or "(empty)", -1)
            cr.set_source_rgba(*self.fg, 0.5)
            cr.move_to(zx + 2, zy + zh + 6)
            PangoCairo.show_layout(cr, names)
        if self.target:  # where the dragged chip will land
            zone, index = self.target
            mx = self.insert_x(zone, index)
            zx, zy, zw, zh = self.zones[zone]
            cr.set_source_rgba(*self.accent, 1)
            cr.rectangle(mx - 1.5, zy + 6, 3, zh - 12)
            cr.fill()
        if self.drag:
            m = self.drag["module"]
            w = self.chip_width(cr, m, True)
            self.draw_chip(cr, m, self.drag["x"] - self.drag["dx"], self.drag["y"] - self.drag["dy"], w, CHIP_H, True, 0.9)
        if not self.state.shelf() and not (self.drag and self.target and self.target[0] == SHELF):
            zx, zy, zw, zh = self.zones[SHELF]
            label.set_text("Drag a module here to take it off the bar", -1)
            tw, th = label.get_pixel_size()
            cr.set_source_rgba(*self.fg, 0.4)
            cr.move_to(zx + (zw - tw) / 2, zy + (zh - th) / 2)
            PangoCairo.show_layout(cr, label)

    def draw_chip(self, cr, module, x, y, w, h, with_name, alpha):
        rounded(cr, x, y, w, h, h / 2)
        cr.set_source_rgba(*self.accent, 0.22 * alpha)
        cr.fill_preserve()
        cr.set_source_rgba(*self.accent, 0.8 * alpha)
        cr.set_line_width(1.5)
        cr.stroke()
        lay = self.layout_for(cr, self.chip_text(module, with_name))
        tw, th = lay.get_pixel_size()
        cr.set_source_rgba(*self.fg, alpha)
        cr.move_to(x + (w - tw) / 2, y + (h - th) / 2)
        PangoCairo.show_layout(cr, lay)

    # ---- dragging ---------------------------------------------------------------------------------------------
    def hit(self, x, y):
        for chip in self.chips:
            zone, module, cx, cy, w, h, _i = chip
            if cx <= x <= cx + w and cy <= y <= cy + h:
                return chip
        return None

    def tooltip(self, _area, x, y, _kb, tip):
        chip = self.hit(x, y)
        if not chip:
            return False
        tip.set_text(f"{barlayout.label(chip[1])[0]}  ({chip[1]})")
        return True

    def insert_x(self, zone, index):
        same = [c for c in self.chips if c[0] == zone]
        zx, zy, zw, zh = self.zones[zone]
        if not same:
            return zx + zw / 2
        if index >= len(same):
            last = same[-1]
            return last[2] + last[4] + 3
        return same[index][2] - 3

    def drop_target(self, x, y):
        for zone, (zx, zy, zw, zh) in self.zones.items():
            if zx - 6 <= x <= zx + zw + 6 and zy - 22 <= y <= zy + zh + 14:
                if zone == SHELF:
                    return zone, 0
                same = [c for c in self.chips if c[0] == zone]
                index = sum(1 for c in same if c[2] + c[4] / 2 < x)
                return zone, index
        return None

    def begin(self, gesture, x, y):
        chip = self.hit(x, y)
        if not chip:
            gesture.set_state(Gtk.EventSequenceState.DENIED)
            return
        zone, module, cx, cy, _w, _h, _i = chip
        self.drag = {"module": module, "from": zone, "x": x, "y": y, "dx": x - cx, "dy": y - cy, "sx": x, "sy": y}
        self.area.set_cursor_from_name("grabbing")

    def update(self, _g, ox, oy):
        if not self.drag:
            return
        self.drag["x"], self.drag["y"] = self.drag["sx"] + ox, self.drag["sy"] + oy
        self.target = self.drop_target(self.drag["x"], self.drag["y"])
        self.area.queue_draw()

    def end(self, _g, _ox, _oy):
        drag, target = self.drag, self.target
        self.drag, self.target = None, None
        self.area.set_cursor_from_name("default")
        if drag and target:
            self.move(drag["module"], drag["from"], *target)
        self.area.queue_draw()

    def move(self, module, _from_zone, to_zone, index):
        layout = self.state.layout
        for zone in barlayout.ZONES:  # where it really is now, whatever the last drawing said
            if module in layout[zone]:
                layout[zone].remove(module)
        if to_zone != SHELF:
            layout[to_zone].insert(min(index, len(layout[to_zone])), module)
        self.win.changed()


def rounded(cr, x, y, w, h, r):
    r = min(r, w / 2, h / 2)
    cr.new_sub_path()
    for cx, cy, a in ((x + w - r, y + r, -1.5708), (x + w - r, y + h - r, 0), (x + r, y + h - r, 1.5708), (x + r, y + r, 3.1416)):
        cr.arc(cx, cy, r, a, a + 1.5708)
    cr.close_path()
