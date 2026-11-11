#!/usr/bin/env python3
"""Notes: a scratchpad that drops down from the top of the screen you are on (Super+I), like a drop-down terminal.

Each tab is a note, saved as you type, so open tabs come back after a crash or a restart. Closing a tab deletes its note
(to the bin, so a slip can be undone): notes are scratch paper that lasts as long as its tab. Save as (Ctrl+Shift+S) is
how you keep one, as a Markdown or text file anywhere. Escape, the key again or a click outside hides the window; pinned,
it stays while you work in other windows.

It runs in the background as the hyprdots-notes service and shows or hides on a signal from notes.sh (SIGUSR1), so it
opens at once. click_away.lua sends SIGUSR2, which hides it unless it is pinned. Colours come from the Theme page through
the quick tray's theme file. notebook.py has the files, markdown.py the formatting."""
import json
import os
import re
import signal
import subprocess
import sys
from pathlib import Path

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
gi.require_version("Gtk4LayerShell", "1.0")
gi.require_version("GLibUnix", "2.0")
from gi.repository import Gdk, Gio, GLib, GLibUnix, Gtk, Gtk4LayerShell as Layer, Pango

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE), str(HERE.parent / "tray"), str(HERE.parent / "settings")]
import markdown  # noqa: E402
import notebook  # noqa: E402
from hyprsettings import livetheme  # noqa: E402

THEME = HERE.parent / "tray/theme.css"
READY = Path(os.environ.get("XDG_RUNTIME_DIR", "/tmp")) / "hyprdots-notes.ready"
WIDTH, HEIGHT = 0.62, 0.55  # of the screen
SAVE_AFTER_MS, FORMAT_AFTER_MS = 700, 120
UNTITLED = "New note"
KEEP_HINT = "Closing a tab deletes it. Ctrl+Shift+S saves a copy to keep"

WELCOME = """# Notes

Scratch paper that drops down with **Super + I**. Each tab is saved as you type, so it is still here after a restart.

- **Closing a tab deletes it.** Save a copy first if you want to keep it: **Ctrl + Shift + S**
- **Ctrl + T** new tab, **Ctrl + W** close this one, **Ctrl + Tab** the next one
- **Esc** or a click outside hides this, unless it is pinned
- **Ctrl + B** bold, **Ctrl + I** italic, **Ctrl + 1, 2, 3** headings
- [ ] **Ctrl + Enter** ticks a box like this one
- **Ctrl + +** and **Ctrl + -** change the text size

Lists carry on when you press Enter, and an empty item ends them.
"""

DEFAULT_COLOURS = {"tray_bg": "rgba(27,26,27,0.96)", "tray_text": "#F9F8F9", "tray_card": "rgba(128,128,128,0.18)",
                   "tray_accent": "#7aa2f7", "tray_on_accent": "#1B1A1B", "tray_muted": "#9a9a9a", "tray_attention": "#e06c75"}
# CSS variables, not @define-color: GTK 4.24 ignores those names here
CSS = """
window.notes { background: transparent; }
.panel { background: var(--tray_solid); color: var(--tray_text); border-radius: 0 0 16px 16px; border: 1px solid var(--tray_accent); border-top: none;
         box-shadow: 0 4px 16px rgba(0,0,0,0.5); margin: 0 12px 14px 12px; }
.panel label, .panel textview, .panel text { color: var(--tray_text); }
.bar { padding: 8px 10px 4px 10px; }
.bar button { background: none; border: none; box-shadow: none; border-radius: 8px; min-height: 30px; min-width: 30px; padding: 2px 8px; color: var(--tray_text); }
.bar button:hover { background: color-mix(in srgb, var(--tray_accent) 25%, transparent); }
.bar button:checked { background: color-mix(in srgb, var(--tray_accent) 45%, transparent); }
.tab { background: var(--tray_card); border-radius: 10px; padding: 0 2px 0 4px; }
.tab.current { background: color-mix(in srgb, var(--tray_accent) 45%, transparent); }
.tab button { min-height: 26px; min-width: 22px; padding: 0 6px; }
.tab button.close { min-width: 18px; padding: 0 4px; opacity: 0.7; }
.tab button.close:hover { opacity: 1; }
.dim { color: var(--tray_muted); font-size: 0.9em; }
textview, textview text { background: none; font-size: 1.05em; }
textview { padding: 4px 18px 14px 18px; caret-color: var(--tray_accent); }
textview text selection { background: color-mix(in srgb, var(--tray_accent) 45%, transparent); }
scrollbar { background: none; }
"""
TOUCH_CSS = """
.bar button { min-height: 46px; min-width: 46px; }
.tab button { min-height: 42px; }
textview, textview text { font-size: 1.3em; }
"""


def theme_colours():
    """The Theme page's colours, for the parts CSS cannot reach (the formatting inside the text)."""
    colours = dict(DEFAULT_COLOURS)
    try:
        text = THEME.read_text(encoding="utf-8")
    except OSError:
        return colours
    colours.update(dict(re.findall(r"@define-color\s+(\w+)\s+([^;]+);", text)))
    return colours


def rgba(text):
    colour = Gdk.RGBA()
    colour.parse(text.strip())
    return colour


def focused_monitor_name():
    try:
        monitors = json.loads(subprocess.run(["hyprctl", "monitors", "-j"], capture_output=True, text=True, timeout=2).stdout)
        return next((m["name"] for m in monitors if m.get("focused")), None)
    except (OSError, subprocess.SubprocessError, ValueError):
        return None


def touch_mode():
    try:
        import touch_mode as touch
        return touch.active()
    except ImportError:
        return False


class Tab:
    """One note: its file, its own text (with its own undo), and what is on disk for it."""

    def __init__(self, path, table, text):
        self.path, self.saved = path, text
        self.buffer = Gtk.TextBuffer(tag_table=table)
        self.buffer.set_text(text)
        self.save_timer = self.format_timer = 0
        self.widget = self.label = None

    def text(self):
        return self.buffer.get_text(self.buffer.get_start_iter(), self.buffer.get_end_iter(), True)

    def title(self):
        return notebook.title_of(self.text()) or UNTITLED


class Notes(Gtk.Application):
    def __init__(self):
        super().__init__(application_id="com.hyprdots.notes", flags=Gio.ApplicationFlags.NON_UNIQUE)
        self.book = notebook.Notebook()
        self.state = self.book.load_state()
        self.tabs, self.tab = [], None
        self.loading = False
        self.pinned = bool(self.state.get("pinned", False))
        self.connect("activate", self._build)

    # ---- the window --------------------------------------------------------------------------------------------
    def _build(self, _app):
        self.hold()
        self.live_theme = livetheme.follow(self)  # follows a theme override switch while open
        win = self.win = Gtk.ApplicationWindow(application=self, title="Notes", css_classes=["notes"])
        Layer.init_for_window(win)
        Layer.set_namespace(win, "hyprdots-notes")
        Layer.set_layer(win, Layer.Layer.OVERLAY)
        Layer.set_anchor(win, Layer.Edge.TOP, True)
        Layer.set_exclusive_zone(win, -1)  # from the very top of the screen, over the bar
        Layer.set_keyboard_mode(win, Layer.KeyboardMode.ON_DEMAND)

        self.css, self.theme_css, self.touch_css = Gtk.CssProvider(), Gtk.CssProvider(), Gtk.CssProvider()
        display = Gdk.Display.get_default()
        for priority, provider in ((800, self.theme_css), (801, self.css), (802, self.touch_css)):
            Gtk.StyleContext.add_provider_for_display(display, provider, priority)
        self.css.load_from_string(CSS)
        self.theme_monitor = Gio.File.new_for_path(str(THEME)).monitor_file(Gio.FileMonitorFlags.NONE, None)
        self.theme_monitor.connect("changed", lambda *_a: self._load_theme())
        self.table = Gtk.TextTagTable()

        panel = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, css_classes=["panel"])
        panel.append(self._bar())
        self.text = Gtk.TextView(wrap_mode=Gtk.WrapMode.WORD_CHAR, hexpand=True, vexpand=True, accepts_tab=True,
                                 top_margin=6, bottom_margin=12)
        panel.append(Gtk.ScrolledWindow(child=self.text, hscrollbar_policy=Gtk.PolicyType.NEVER, vexpand=True))
        self.status = Gtk.Label(xalign=0, css_classes=["dim"], margin_start=20, margin_bottom=10, ellipsize=Pango.EllipsizeMode.END)
        panel.append(self.status)
        win.set_child(panel)

        keys = Gtk.EventControllerKey(propagation_phase=Gtk.PropagationPhase.CAPTURE)
        keys.connect("key-pressed", self._key)
        win.add_controller(keys)
        self._load_theme()
        self._zoom(None)

        if not self.book.tabs() and not self.state.get("welcomed"):
            self.book.new(WELCOME)
            self.state["welcomed"] = True
        for path in self.book.tabs():
            self._add_tab(path)
        if not self.tabs:
            self._add_tab(self.book.new())
        current = next((t for t in self.tabs if t.path.name == self.state.get("current")), self.tabs[-1])
        self.select(current)

        self.folder_monitor = Gio.File.new_for_path(str(self.book.dir)).monitor_directory(Gio.FileMonitorFlags.WATCH_MOVES, None)
        self.folder_monitor.connect("changed", lambda *_a: GLib.timeout_add(150, self._outside_change))
        for number, action in ((signal.SIGUSR1, self.toggle), (signal.SIGUSR2, self.click_away), (signal.SIGTERM, self.quit_saving)):
            GLibUnix.signal_add(GLib.PRIORITY_DEFAULT, number, lambda action=action: action() or True)
        READY.touch()

    def _bar(self):
        bar = Gtk.Box(spacing=6, css_classes=["bar"])
        self.strip = Gtk.Box(spacing=6)
        scroller = Gtk.ScrolledWindow(child=self.strip, hexpand=True, vscrollbar_policy=Gtk.PolicyType.NEVER,
                                      hscrollbar_policy=Gtk.PolicyType.AUTOMATIC, propagate_natural_height=True)
        bar.append(scroller)
        for icon, tip, action in (("tab-new-symbolic", "New tab (Ctrl+T)", self.new_tab),
                                  ("document-save-as-symbolic", "Save a copy to keep (Ctrl+Shift+S)", self.save_as),
                                  ("edit-copy-symbolic", "Copy the whole note", self.copy_all)):
            button = Gtk.Button(icon_name=icon, tooltip_text=tip)
            button.connect("clicked", lambda _b, action=action: action())
            bar.append(button)
        self.pin = Gtk.ToggleButton(icon_name="view-pin-symbolic", active=self.pinned,
                                    tooltip_text="Keep it open while you use other windows (Ctrl+P)")
        self.pin.connect("toggled", lambda b: self._set_pinned(b.get_active()))
        bar.append(self.pin)
        hide = Gtk.Button(icon_name="go-up-symbolic", tooltip_text="Hide (Esc). Your tabs stay")
        hide.connect("clicked", lambda _b: self.hide())
        bar.append(hide)
        return bar

    def _load_theme(self):
        colours = theme_colours()
        solid = rgba(colours["tray_bg"])
        solid.alpha = 1.0  # solid, so notes read well over anything
        names = {**colours, "tray_solid": solid.to_string()}
        self.theme_css.load_from_string(":root {\n" + "".join(f"  --{k}: {v};\n" for k, v in names.items()) + "}\n" + self._theme_font())
        self.touch_css.load_from_string(TOUCH_CSS if touch_mode() else "")
        self._make_tags(colours)
        for tab in self.tabs:
            self._format(tab)

    def _theme_font(self):
        try:
            found = re.search(r"font-family:\s*([^;]+);", THEME.read_text(encoding="utf-8"))
        except OSError:
            found = None
        return f".panel {{ font-family: {found[1]}; }}\n" if found else ""

    def _make_tags(self, c):
        accent, muted = rgba(c["tray_accent"]), rgba(c["tray_muted"])
        looks = {"h1": dict(weight=Pango.Weight.BOLD, scale=1.6, foreground_rgba=accent),
                 "h2": dict(weight=Pango.Weight.BOLD, scale=1.35, foreground_rgba=accent),
                 "h3": dict(weight=Pango.Weight.BOLD, scale=1.15),
                 "bold": dict(weight=Pango.Weight.BOLD), "italic": dict(style=Pango.Style.ITALIC),
                 "strike": dict(strikethrough=True, foreground_rgba=muted),
                 "code": dict(family="monospace", background_rgba=rgba(c["tray_card"])),
                 "fence": dict(family="monospace", paragraph_background_rgba=rgba(c["tray_card"])),
                 "quote": dict(style=Pango.Style.ITALIC, foreground_rgba=muted, left_margin=24),
                 "rule": dict(foreground_rgba=muted), "bullet": dict(foreground_rgba=accent, weight=Pango.Weight.BOLD),
                 "box": dict(foreground_rgba=accent, family="monospace"), "done": dict(strikethrough=True, foreground_rgba=muted),
                 "link": dict(foreground_rgba=accent, underline=Pango.Underline.SINGLE)}
        for name, props in looks.items():
            tag = self.table.lookup(name)
            if tag is None:
                tag = Gtk.TextTag(name=name)
                self.table.add(tag)
            for key, value in props.items():
                tag.set_property(key.replace("_", "-"), value)

    # ---- showing and hiding ------------------------------------------------------------------------------------
    def toggle(self):
        self.hide() if self.win.get_visible() else self.show()

    def show(self):
        """On the screen you are on, sized to it. It takes the keyboard as it opens, so you can type straight away;
        pinned, it gives it back a moment later so you can type in other windows too, and a click on it gets it back."""
        display = Gdk.Display.get_default()
        name, chosen = focused_monitor_name(), None
        for i in range(display.get_monitors().get_n_items()):
            monitor = display.get_monitors().get_item(i)
            if monitor.get_connector() == name or chosen is None:
                chosen = monitor
        if chosen:
            Layer.set_monitor(self.win, chosen)
            geometry = chosen.get_geometry()
            self.win.set_default_size(max(520, int(geometry.width * WIDTH)), max(360, int(geometry.height * HEIGHT)))
        self.touch_css.load_from_string(TOUCH_CSS if touch_mode() else "")
        Layer.set_keyboard_mode(self.win, Layer.KeyboardMode.EXCLUSIVE)
        self.win.set_visible(True)
        self.win.present()
        self.text.grab_focus()
        if self.pinned:
            GLib.timeout_add(400, self._share_keyboard)

    def _share_keyboard(self):
        if self.pinned and self.win.get_visible():
            Layer.set_keyboard_mode(self.win, Layer.KeyboardMode.ON_DEMAND)
        return False

    def hide(self):
        self.save_all()
        self.win.set_visible(False)

    def click_away(self):
        if not self.pinned and self.win.get_visible():
            self.hide()

    def _set_pinned(self, pinned):
        self.pinned = pinned
        if self.win.get_visible():
            Layer.set_keyboard_mode(self.win, Layer.KeyboardMode.ON_DEMAND if pinned else Layer.KeyboardMode.EXCLUSIVE)
        self._save_state()

    def quit_saving(self):
        self.save_all()
        READY.unlink(missing_ok=True)
        self.quit()

    # ---- tabs ----------------------------------------------------------------------------------------------------
    def _add_tab(self, path, select=False):
        tab = Tab(path, self.table, self.book.read(path))
        tab.buffer.connect("changed", lambda _b, tab=tab: self._edited(tab))
        box = Gtk.Box(css_classes=["tab"])
        name = Gtk.Button(tooltip_text=KEEP_HINT)
        tab.label = Gtk.Label(label=tab.title(), max_width_chars=18, ellipsize=Pango.EllipsizeMode.END)
        name.set_child(tab.label)
        name.connect("clicked", lambda _b, tab=tab: self.select(tab))
        close = Gtk.Button(icon_name="window-close-symbolic", css_classes=["close"], tooltip_text="Close this tab and delete the note (Ctrl+W)")
        close.connect("clicked", lambda _b, tab=tab: self.close_tab(tab))
        middle = Gtk.GestureClick(button=2)  # a middle click closes a tab, as in a browser
        middle.connect("released", lambda *_a, tab=tab: self.close_tab(tab))
        box.add_controller(middle)
        box.append(name)
        box.append(close)
        tab.widget = box
        self.strip.append(box)
        self.tabs.append(tab)
        self._format(tab)
        if select:
            self.select(tab)
        return tab

    def select(self, tab):
        if self.tab and self.tab is not tab:
            self._remember_cursor()
            self.tab.widget.remove_css_class("current")
            self.save(self.tab)
        self.tab = tab
        tab.widget.add_css_class("current")
        self.text.set_buffer(tab.buffer)
        cursor = self.state.get("cursors", {}).get(tab.path.name, tab.buffer.get_char_count())
        tab.buffer.place_cursor(tab.buffer.get_iter_at_offset(min(cursor, tab.buffer.get_char_count())))
        GLib.idle_add(self._scroll_to_cursor, tab)
        self.text.grab_focus()
        self._status("Saved")
        self._save_state()

    def _scroll_to_cursor(self, tab):
        if self.text.get_buffer() is tab.buffer:  # another tab may have been picked since
            self.text.scroll_to_mark(tab.buffer.get_insert(), 0.2, False, 0, 0)
        return False

    def new_tab(self):
        self._add_tab(self.book.new(), select=True)

    def close_tab(self, tab):
        """Deletes the note. The last tab closed leaves a fresh empty one, so there is always somewhere to type."""
        for attr in ("save_timer", "format_timer"):
            if getattr(tab, attr):
                GLib.source_remove(getattr(tab, attr))
                setattr(tab, attr, 0)
        self.save(tab)  # so what goes to the bin is all of it
        at = self.tabs.index(tab)
        self.tabs.remove(tab)
        self.strip.remove(tab.widget)
        self.book.close(tab.path)
        self.state.get("cursors", {}).pop(tab.path.name, None)
        if not self.tabs:
            self._add_tab(self.book.new())
        if tab is self.tab:
            self.tab = None
            self.select(self.tabs[min(at, len(self.tabs) - 1)])
        else:
            self._save_state()

    def step(self, by):
        self.select(self.tabs[(self.tabs.index(self.tab) + by) % len(self.tabs)])

    # ---- saving --------------------------------------------------------------------------------------------------
    def _edited(self, tab):
        if self.loading:
            return
        if tab is self.tab:
            self._status("Editing")
        for attr, delay, job in (("save_timer", SAVE_AFTER_MS, self.save), ("format_timer", FORMAT_AFTER_MS, self._format)):
            if getattr(tab, attr):
                GLib.source_remove(getattr(tab, attr))
            setattr(tab, attr, GLib.timeout_add(delay, lambda job=job, attr=attr: (setattr(tab, attr, 0), job(tab)) and False))

    def save(self, tab):
        if tab.save_timer:
            GLib.source_remove(tab.save_timer)
            tab.save_timer = 0
        text = tab.text()
        if tab in self.tabs and (text != tab.saved or not tab.path.exists()):
            try:
                self.book.write(tab.path, text)
            except OSError as e:
                self._status(f"Could not save: {e}")
                return
            tab.saved = text
        if tab is self.tab:
            self._status("Saved")

    def save_all(self):
        self._remember_cursor()
        for tab in self.tabs:
            self.save(tab)
        self._save_state()

    def _outside_change(self):
        """Another program changed or added a note (notes.sh --append, say): show it, unless you have edits here it would
        overwrite."""
        known = {t.path for t in self.tabs}
        for path in self.book.tabs():
            if path not in known:
                self._add_tab(path)
        for tab in self.tabs:
            if not tab.path.exists():
                continue
            disk = self.book.read(tab.path)
            if disk != tab.saved and tab.text() == tab.saved:
                offset = tab.buffer.get_property("cursor-position")
                tab.saved = disk
                self.loading = True
                tab.buffer.set_text(disk)
                self.loading = False
                tab.buffer.place_cursor(tab.buffer.get_iter_at_offset(min(offset, tab.buffer.get_char_count())))
                self._format(tab)
        return False

    def save_as(self):
        """A copy to keep, as Markdown or plain text, anywhere. The tab stays as it is. The file chooser is a normal window,
        which would be under this one, so this hides until it is done."""
        tab = self.tab
        self.save(tab)
        dialog = Gtk.FileDialog(title="Save a copy to keep", initial_name=notebook.file_name(tab.title()),
                                initial_folder=Gio.File.new_for_path(str(Path.home() / "Documents")))
        self.win.set_visible(False)

        def done(dialog, result):
            try:
                target = dialog.save_finish(result)
            except GLib.Error:
                target = None
            if target:
                try:
                    Path(target.get_path()).write_text(tab.text(), encoding="utf-8")
                    subprocess.Popen(["notify-send", "-a", "Notes", "Saved a copy", target.get_path()])
                except OSError as e:
                    subprocess.Popen(["notify-send", "-a", "Notes", "Could not save the copy", str(e)])
            self.show()
        dialog.save(None, None, done)

    def copy_all(self):
        self.win.get_clipboard().set(self.tab.text())
        self._status("Copied the whole note")

    def _status(self, word):
        if not self.tab:
            return
        words = len(self.tab.text().split())
        self.status.set_label(f"{word}  ·  {words} word{'' if words == 1 else 's'}  ·  {KEEP_HINT}")

    def _remember_cursor(self):
        if self.tab:
            self.state.setdefault("cursors", {})[self.tab.path.name] = self.tab.buffer.get_property("cursor-position")

    def _save_state(self):
        names = {t.path.name for t in self.tabs}
        self.state.update(tabs=[t.path.name for t in self.tabs], current=self.tab.path.name if self.tab else "",
                          pinned=self.pinned, cursors={k: v for k, v in self.state.get("cursors", {}).items() if k in names})
        try:
            self.book.save_state(self.state)
        except OSError:
            pass

    # ---- Markdown ----------------------------------------------------------------------------------------------
    def _format(self, tab):
        buffer = tab.buffer
        buffer.remove_all_tags(buffer.get_start_iter(), buffer.get_end_iter())
        for a, b, name in markdown.spans(tab.text()):
            buffer.apply_tag_by_name(name, buffer.get_iter_at_offset(a), buffer.get_iter_at_offset(b))
        if tab.label:
            tab.label.set_label(tab.title())
        return False

    def _line(self):
        """(start, end) of the line the cursor is on."""
        buffer = self.tab.buffer
        start = buffer.get_iter_at_mark(buffer.get_insert())
        start.set_line_offset(0)
        end = start.copy()
        if not end.ends_line():
            end.forward_to_line_end()
        return start, end

    def _replace_line(self, text):
        buffer = self.tab.buffer
        start, end = self._line()
        buffer.begin_user_action()
        buffer.delete(start, end)
        buffer.insert(start, text)
        buffer.end_user_action()

    def _enter(self):
        buffer = self.tab.buffer
        start, end = self._line()
        if not buffer.get_iter_at_mark(buffer.get_insert()).ends_line():
            return False
        prefix, clear = markdown.next_item(buffer.get_text(start, end, True))
        if prefix is None:
            return False
        if clear:
            self._replace_line("")
        else:
            buffer.insert_at_cursor("\n" + prefix)
        self.text.scroll_mark_onscreen(buffer.get_insert())
        return True

    def _wrap_selection(self, mark):
        buffer = self.tab.buffer
        bounds = buffer.get_selection_bounds()
        if not bounds:
            buffer.insert_at_cursor(mark * 2)
            here = buffer.get_iter_at_mark(buffer.get_insert())
            here.backward_chars(len(mark))
            buffer.place_cursor(here)
            return
        a, b = bounds
        text, offset = buffer.get_text(a, b, True), a.get_offset()
        buffer.begin_user_action()
        buffer.delete(a, b)
        buffer.insert(buffer.get_iter_at_offset(offset), markdown.wrap(text, mark))
        buffer.end_user_action()

    def _zoom(self, by):
        """by: a step, 0 to reset, None to apply the saved size."""
        size = self.state.get("zoom", 1.0)
        size = 1.0 if by == 0 else size if by is None else max(0.7, min(2.5, size + by))
        self.state["zoom"] = size
        self.css.load_from_string(CSS + f"textview, textview text {{ font-size: {1.05 * size:.2f}em; }}\n")
        if by is not None:
            self._save_state()

    def _key(self, _controller, keyval, _code, state):
        ctrl = bool(state & Gdk.ModifierType.CONTROL_MASK)
        shift = bool(state & Gdk.ModifierType.SHIFT_MASK)
        alt = bool(state & Gdk.ModifierType.ALT_MASK)
        key = Gdk.keyval_name(keyval) or ""
        if key == "Escape":
            self.hide()
            return True
        if alt and key.isdigit() and key != "0":  # Alt+1..9: that tab
            index = int(key) - 1
            if index < len(self.tabs):
                self.select(self.tabs[index])
            return True
        if ctrl:
            if key in ("Tab", "ISO_Left_Tab"):
                self.step(-1 if shift or key == "ISO_Left_Tab" else 1)
                return True
            if shift and key.lower() == "s":
                self.save_as()
                return True
            handlers = {"t": self.new_tab, "n": self.new_tab, "w": lambda: self.close_tab(self.tab), "s": lambda: self.save(self.tab),
                        "p": lambda: self.pin.set_active(not self.pin.get_active()),
                        "b": lambda: self._wrap_selection("**"), "i": lambda: self._wrap_selection("*"),
                        "plus": lambda: self._zoom(0.1), "equal": lambda: self._zoom(0.1), "minus": lambda: self._zoom(-0.1),
                        "0": lambda: self._zoom(0), "Page_Up": lambda: self.step(-1), "Page_Down": lambda: self.step(1),
                        "1": lambda: self._heading(1), "2": lambda: self._heading(2), "3": lambda: self._heading(3),
                        "Return": self._toggle_box, "KP_Enter": self._toggle_box}
            if key in handlers:
                handlers[key]()
                return True
            return False
        if key in ("Return", "KP_Enter") and not shift and self.text.has_focus():
            return self._enter()
        return False

    def _heading(self, level):
        start, end = self._line()
        self._replace_line(markdown.heading(self.tab.buffer.get_text(start, end, True), level))

    def _toggle_box(self):
        start, end = self._line()
        self._replace_line(markdown.toggle_box(self.tab.buffer.get_text(start, end, True)))


def main():
    READY.unlink(missing_ok=True)
    return Notes().run([sys.argv[0]])


if __name__ == "__main__":
    sys.exit(main())
