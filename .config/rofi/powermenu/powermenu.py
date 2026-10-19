#!/usr/bin/env python3
"""Full-screen power menu: a PC (or a laptop when a battery is found) in the middle, the power options in a ring around it.

Keys: arrows / Tab move, Enter picks, l s o r p jump straight to an option, Esc closes. The mouse works too.
Run through powermenu.sh (it preloads gtk4-layer-shell, which has to be loaded before GTK).
--dry-run prints the command instead of running it."""

import math
import re
import subprocess
import sys
import time
from pathlib import Path

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gtk4LayerShell", "1.0")
gi.require_version("PangoCairo", "1.0")
gi.require_version("Gdk", "4.0")
from gi.repository import Gdk, GLib, Gtk, Gtk4LayerShell, Pango, PangoCairo  # noqa: E402

DRY_RUN = "--dry-run" in sys.argv
FONT = "CaskaydiaCove Nerd Font"   # icons
TEXT_FONT = "Sans"
COLORS_FILE = Path.home() / ".config/rofi/colors.rasi"

# key, label, glyph, command, needs confirmation
ACTIONS = [
    ("l", "Lock", "", ["loginctl", "lock-session"], False),
    ("s", "Suspend", "\U000f04b2", ["systemctl", "suspend"], True),
    ("o", "Log out", "\U000f0343", ["hyprctl", "dispatch", "hl.dsp.exit()"], True),
    ("r", "Reboot", "", ["systemctl", "reboot"], True),
    ("p", "Shut down", "", ["systemctl", "poweroff"], True),
]


def theme_colors() -> dict:
    """Wallust colours from the rofi colour file, with a calm fallback."""
    out = {"accent": (0.58, 0.60, 0.70), "soft": (0.66, 0.66, 0.67), "fg": (0.98, 0.97, 0.98), "bg": (0.11, 0.10, 0.11)}
    try:
        text = COLORS_FILE.read_text()
    except OSError:
        return out
    for key, name in (("accent", "color12"), ("soft", "color5"), ("fg", "foreground"), ("bg", "background")):
        m = re.search(rf"^\s*{name}:\s*#([0-9a-fA-F]{{6}})", text, re.M)
        if m:
            out[key] = tuple(int(m[1][i:i + 2], 16) / 255 for i in (0, 2, 4))
    return out


def battery_percent():
    """Percent of the machine's own battery, or None on a desktop (wireless mice and keyboards are scope=Device)."""
    for supply in Path("/sys/class/power_supply").glob("*"):
        try:
            if (supply / "type").read_text().strip() != "Battery":
                continue
            scope = supply / "scope"
            if scope.exists() and scope.read_text().strip() == "Device":
                continue
            return int((supply / "capacity").read_text())
        except (OSError, ValueError):
            continue
    return None


def uptime_text() -> str:
    try:
        seconds = int(float(Path("/proc/uptime").read_text().split()[0]))
    except (OSError, ValueError):
        return ""
    d, rest = divmod(seconds, 86400)
    h, m = divmod(rest, 3600)
    m //= 60
    parts = [f"{d}d"] if d else []
    if h or d:
        parts.append(f"{h}h")
    parts.append(f"{m}m")
    return "up " + " ".join(parts)


class Menu(Gtk.DrawingArea):
    def __init__(self, window):
        super().__init__()
        self.win = window
        self.c = theme_colors()
        self.battery = battery_percent()
        self.focus = 0
        self.hover = None
        self.pending = None        # index waiting for a yes/no
        self.set_hexpand(True)
        self.set_vexpand(True)
        self.set_focusable(True)
        self.set_draw_func(self.draw)

        keys = Gtk.EventControllerKey()
        keys.connect("key-pressed", self.on_key)
        window.add_controller(keys)
        motion = Gtk.EventControllerMotion()
        motion.connect("motion", self.on_motion)
        motion.connect("leave", lambda *_: self.set_hover(None))
        self.add_controller(motion)
        click = Gtk.GestureClick()
        click.connect("released", self.on_click)
        self.add_controller(click)
        GLib.timeout_add_seconds(20, self.tick)

    def tick(self):
        self.queue_draw()
        return True

    # ---- geometry ---------------------------------------------------------------------------------------
    def layout(self):
        w, h = self.get_width(), self.get_height()
        cx, cy = w / 2, h / 2
        ring = min(w, h) * 0.33
        node = min(w, h) * 0.058
        spots = []
        for i in range(len(ACTIONS)):
            a = -math.pi / 2 + 2 * math.pi * i / len(ACTIONS)
            spots.append((cx + ring * math.cos(a), cy + ring * math.sin(a)))
        return cx, cy, ring, node, spots

    def item_at(self, x, y):
        _, _, _, node, spots = self.layout()
        for i, (sx, sy) in enumerate(spots):
            if math.hypot(x - sx, y - sy) <= node * 1.25:
                return i
        return None

    # ---- input ------------------------------------------------------------------------------------------
    def set_hover(self, i):
        if i != self.hover:
            self.hover = i
            if i is not None and self.pending is None:
                self.focus = i
            self.queue_draw()

    def on_motion(self, _ctl, x, y):
        self.set_hover(self.item_at(x, y))

    def on_click(self, _g, _n, x, y):
        if self.pending is not None:
            return self.cancel()
        i = self.item_at(x, y)
        if i is None:
            return self.win.close()
        self.focus = i
        self.choose(i)

    def on_key(self, _ctl, keyval, _code, _state):
        name = Gdk.keyval_name(keyval) or ""
        if self.pending is not None:
            if name in ("Return", "KP_Enter", "y", "Y"):
                self.run(self.pending)
            elif name in ("Escape", "n", "N", "BackSpace"):
                self.cancel()
            return True
        n = len(ACTIONS)
        if name == "Escape" or name == "q":
            self.win.close()
        elif name in ("Right", "Down", "Tab"):
            self.focus = (self.focus + 1) % n
        elif name in ("Left", "Up", "ISO_Left_Tab"):
            self.focus = (self.focus - 1) % n
        elif name in ("Return", "KP_Enter", "space"):
            self.choose(self.focus)
        else:
            for i, a in enumerate(ACTIONS):
                if name.lower() == a[0]:
                    self.focus = i
                    self.choose(i)
        self.queue_draw()
        return True

    def choose(self, i):
        if ACTIONS[i][4]:
            self.pending = i
            self.queue_draw()
        else:
            self.run(i)

    def cancel(self):
        self.pending = None
        self.queue_draw()

    def run(self, i):
        cmd = ACTIONS[i][3]
        if DRY_RUN:
            print(" ".join(cmd), flush=True)
        else:
            subprocess.Popen(cmd, start_new_session=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.win.close()

    # ---- drawing ------------------------------------------------------------------------------------------
    def text(self, cr, s, x, y, size, color, alpha=1.0, bold=False, font=TEXT_FONT, anchor="center"):
        layout = PangoCairo.create_layout(cr)
        layout.set_font_description(Pango.FontDescription(f"{font} {'Bold ' if bold else ''}{size}"))
        layout.set_text(s, -1)
        tw, th = layout.get_pixel_size()
        cr.set_source_rgba(*color, alpha)
        cr.move_to(x - tw / 2 if anchor == "center" else x, y - th / 2)
        PangoCairo.show_layout(cr, layout)

    @staticmethod
    def rounded(cr, x, y, w, h, r):
        cr.new_path()
        cr.arc(x + w - r, y + r, r, -math.pi / 2, 0)
        cr.arc(x + w - r, y + h - r, r, 0, math.pi / 2)
        cr.arc(x + r, y + h - r, r, math.pi / 2, math.pi)
        cr.arc(x + r, y + r, r, math.pi, 3 * math.pi / 2)
        cr.close_path()

    def draw(self, _area, cr, w, h):
        c = self.c
        cr.set_source_rgba(0, 0, 0, 0.55)
        cr.paint()
        cx, cy, ring, node, spots = self.layout()

        # faint guide ring
        cr.set_line_width(1.5)
        cr.set_source_rgba(*c["fg"], 0.10)
        cr.new_path()
        cr.arc(cx, cy, ring, 0, 2 * math.pi)
        cr.stroke()

        self.draw_machine(cr, cx, cy, ring * 0.92)

        for i, (sx, sy) in enumerate(spots):
            key, label, glyph, _cmd, _confirm = ACTIONS[i]
            active = i == self.focus and (self.pending is None or self.pending == i)
            dim = self.pending is not None and self.pending != i
            alpha = 0.25 if dim else 1.0
            r = node * (1.12 if active else 1.0)
            cr.new_path()
            cr.arc(sx, sy, r, 0, 2 * math.pi)
            if active:
                cr.set_source_rgba(*c["accent"], 0.95 * alpha)
            else:
                cr.set_source_rgba(1, 1, 1, 0.10 * alpha)
            cr.fill_preserve()
            cr.set_line_width(2)
            cr.set_source_rgba(*(c["accent"] if active else c["fg"]), (0.9 if active else 0.25) * alpha)
            cr.stroke()
            glyph_color = c["bg"] if active else c["fg"]
            self.text(cr, glyph, sx, sy, max(14, int(node * 0.42)), glyph_color, alpha, font=FONT)
            self.text(cr, label, sx, sy + r + 22, max(11, int(node * 0.22)), c["fg"], (1.0 if active else 0.7) * alpha, bold=active)

    def draw_machine(self, cr, cx, cy, size):
        c = self.c
        laptop = self.battery is not None
        sw = size * (1.05 if laptop else 1.1)           # screen width
        sh = sw * 0.58
        top = cy - (sh + size * (0.10 if laptop else 0.28)) / 2
        left = cx - sw / 2

        # body / bezel
        self.rounded(cr, left, top, sw, sh, sw * 0.04)
        cr.set_source_rgba(*c["fg"], 0.92)
        cr.fill_preserve()
        cr.set_source_rgba(*c["accent"], 0.9)
        cr.set_line_width(3)
        cr.stroke()
        bez = sw * 0.03
        sx, sy, sww, shh = left + bez, top + bez, sw - 2 * bez, sh - 2 * bez
        self.rounded(cr, sx, sy, sww, shh, sw * 0.025)
        cr.set_source_rgba(0.05, 0.05, 0.07, 1)
        cr.fill()

        if laptop:                                       # base with a thumb notch
            bw, bh = sw * 1.16, size * 0.07
            by = top + sh + 2
            cr.move_to(cx - sw / 2, by)
            cr.line_to(cx + sw / 2, by)
            cr.line_to(cx + bw / 2, by + bh)
            cr.line_to(cx - bw / 2, by + bh)
            cr.close_path()
            cr.set_source_rgba(*c["fg"], 0.85)
            cr.fill_preserve()
            cr.set_source_rgba(*c["accent"], 0.9)
            cr.set_line_width(2)
            cr.stroke()
            cr.rectangle(cx - bw * 0.09, by, bw * 0.18, bh * 0.35)
            cr.set_source_rgba(*c["accent"], 0.7)
            cr.fill()
        else:                                            # stand and foot
            ny = top + sh
            cr.rectangle(cx - sw * 0.04, ny, sw * 0.08, size * 0.16)
            cr.set_source_rgba(*c["fg"], 0.85)
            cr.fill()
            self.rounded(cr, cx - sw * 0.18, ny + size * 0.16, sw * 0.36, size * 0.035, size * 0.0175)
            cr.set_source_rgba(*c["fg"], 0.85)
            cr.fill_preserve()
            cr.set_source_rgba(*c["accent"], 0.9)
            cr.set_line_width(2)
            cr.stroke()

        # what the screen says
        mid = sy + shh / 2
        if self.pending is not None:
            _k, label, _g, _cmd, _c = ACTIONS[self.pending]
            self.text(cr, f"{label}?", cx, mid - shh * 0.14, max(16, int(sww * 0.085)), c["fg"], bold=True)
            self.text(cr, "Enter  yes     Esc  no", cx, mid + shh * 0.16, max(10, int(sww * 0.04)), c["accent"])
        else:
            _k, label, glyph, _cmd, _c = ACTIONS[self.focus]
            self.text(cr, time.strftime("%H:%M"), cx, mid - shh * 0.16, max(20, int(sww * 0.15)), c["fg"], bold=True)
            line = uptime_text()
            if self.battery is not None:
                line += f"   {self.battery}%"
            self.text(cr, line.strip(), cx, mid + shh * 0.12, max(10, int(sww * 0.04)), c["fg"], 0.6)
            self.text(cr, label, cx, mid + shh * 0.30, max(11, int(sww * 0.05)), c["accent"], bold=True)


class Window(Gtk.ApplicationWindow):
    def __init__(self, app):
        super().__init__(application=app)
        Gtk4LayerShell.init_for_window(self)
        Gtk4LayerShell.set_namespace(self, "powermenu")
        Gtk4LayerShell.set_layer(self, Gtk4LayerShell.Layer.OVERLAY)
        Gtk4LayerShell.set_keyboard_mode(self, Gtk4LayerShell.KeyboardMode.EXCLUSIVE)
        Gtk4LayerShell.set_exclusive_zone(self, -1)
        for edge in (Gtk4LayerShell.Edge.TOP, Gtk4LayerShell.Edge.BOTTOM, Gtk4LayerShell.Edge.LEFT, Gtk4LayerShell.Edge.RIGHT):
            Gtk4LayerShell.set_anchor(self, edge, True)
        self.set_child(Menu(self))


def main() -> int:
    css = Gtk.CssProvider()
    css.load_from_string("window, window.background { background: transparent; }")
    app = Gtk.Application(application_id="com.hyprdots.powermenu")

    def activate(a):
        Gtk.StyleContext.add_provider_for_display(Gdk.Display.get_default(), css, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
        Window(a).present()
    app.connect("activate", activate)
    return app.run([sys.argv[0]])


if __name__ == "__main__":
    sys.exit(main())
