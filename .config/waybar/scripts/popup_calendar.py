#!/usr/bin/env python3
"""Popup calendar for the waybar clock (GTK3 + layer-shell, no extra packages).

Run it to open the calendar under the bar; run it again (or click outside,
press Escape / q) to close it. Colours come from waybar's wallust theme.
Keys: arrows / h l = month, k j or PageUp/PageDown = year, t or Home = today,
r = refresh events.

Settings and calendar links live in ~/.config/hypr/user_settings.toml
([calendar]); put private iCal links (Google Calendar "Secret address in iCal
format") in ~/.config/hypr/user_settings.local.toml, which is git-ignored.
Needs python-recurring-ical-events (pulls in python-icalendar).
"""
import calendar
import datetime
import hashlib
import os
import sys
import threading
import time
import urllib.request

import gi
gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
gi.require_version("GtkLayerShell", "0.1")
from gi.repository import Gdk, GLib, Gtk, GtkLayerShell

COLORS = os.path.expanduser("~/.config/waybar/colors/colors.css")
sys.path.insert(0, os.path.expanduser("~/.config/hypr/assistant"))
import usersettings  # noqa: E402

CFG = usersettings.section("calendar", {
    "sources": [],
    "refresh_minutes": 15,
    "max_events_listed": 6,
    "first_weekday": 0,
    "time_format": "%H:%M",
    "date_format": "%A, %d %B %Y",
    "margin_top": 8,
    "margin_left": 12,
})
WEEKDAYS = ("Mo", "Tu", "We", "Th", "Fr", "Sa", "Su")
LOCAL_SETTINGS = "~/.config/hypr/user_settings.local.toml"
CACHE_DIR = os.path.join(os.environ.get("XDG_CACHE_HOME", os.path.expanduser("~/.cache")), "popup-calendar")
REFRESH_SECONDS = CFG["refresh_minutes"] * 60
MAX_LISTED = CFG["max_events_listed"]
TIME_FMT = CFG["time_format"]
FIRST_WEEKDAY = CFG["first_weekday"] % 7
LOCK = os.path.join(os.environ.get("XDG_RUNTIME_DIR", "/tmp"), "waybar-calendar.pid")

CSS = """
@define-color foreground #F9F8F9;
@define-color background #1B1A1B;
@define-color color0 #808080;
@define-color color1 #808080;
@define-color color2 #808080;
@define-color color3 #808080;
@define-color color4 #808080;
@define-color color5 #808080;
@define-color color6 #808080;
@define-color color7 #808080;
@define-color color8 #808080;
@define-color color9 #808080;
@define-color color10 #808080;
@define-color color11 #808080;
@define-color color12 #808080;
@define-color color13 #808080;
@define-color color14 #808080;
@define-color color15 #808080;
@import url("file://%(colors)s");
window { background: transparent; }
#card {
    background: alpha(@background, 0.92);
    border: 1px solid alpha(@color10, 0.8);
    border-radius: 16px;
    padding: 18px 20px;
    box-shadow: 0 4px 18px rgba(0,0,0,0.5);
}
#time { font-size: 34px; font-weight: 700; color: @foreground; }
#date { font-size: 13px; color: @color8; }
#month { font-size: 16px; font-weight: 700; color: @foreground; }
.nav {
    background: transparent; border: none; box-shadow: none;
    color: @color7; border-radius: 8px; padding: 2px 10px; font-size: 15px;
}
.nav:hover { background: alpha(@color10, 0.5); }
.wd { font-size: 12px; font-weight: 700; color: @color10; }
.day {
    font-size: 14px; color: @color7;
    min-width: 36px; min-height: 32px; border-radius: 10px;
}
.day.other { color: alpha(@color8, 0.4); }
.day.weekend { color: @color11; }
.day.today { background: @color9; color: @foreground; font-weight: 700; }
.day.selected { background: alpha(@color10, 0.55); }
.day.today.selected { background: @color9; box-shadow: inset 0 0 0 2px @color12; }
.dot { font-size: 7px; color: @color12; min-height: 8px; }
.dot.off { color: transparent; }
#events-title { font-size: 12px; font-weight: 700; color: @color10; }
.ev-time { font-size: 12px; color: @color8; }
.ev-title { font-size: 13px; color: @foreground; }
.ev-note { font-size: 12px; color: @color4; }
.sep { background: alpha(@color10, 0.5); min-height: 1px; }
"""


def build_css():
    return (CSS % {"colors": COLORS}).encode()


def read_sources():
    sources = []
    for entry in CFG["sources"]:
        name, _, url = str(entry).rpartition("|")
        url = url.strip()
        if url.startswith("webcal://"):
            url = "https://" + url[len("webcal://"):]
        if url.startswith(("http://", "https://")):
            sources.append((name.strip(), url))
    return sources


def fetch_source(url, force=False):
    """Returns cached .ics bytes, downloading when stale. Raises on failure with no cache."""
    os.makedirs(CACHE_DIR, mode=0o700, exist_ok=True)
    path = os.path.join(CACHE_DIR, hashlib.sha256(url.encode()).hexdigest()[:16] + ".ics")
    fresh = os.path.exists(path) and time.time() - os.path.getmtime(path) < REFRESH_SECONDS
    if force or not fresh:
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "popup-calendar"})
            with urllib.request.urlopen(req, timeout=20) as resp:
                data = resp.read()
            tmp = path + ".tmp"
            with open(tmp, "wb") as f:
                f.write(data)
            os.replace(tmp, path)
        except Exception:
            if not os.path.exists(path):
                raise
    with open(path, "rb") as f:
        return f.read()


def load_events(force=False):
    """Returns ({date: [(sort_key, time_text, title, calname)]}, status_text)."""
    sources = read_sources()
    if not sources:
        return {}, "no_sources"
    try:
        import icalendar
        import recurring_ical_events
    except ImportError:
        return {}, "no_libs"

    today = datetime.date.today()
    window_start = today.replace(day=1) - datetime.timedelta(days=62)
    window_end = today + datetime.timedelta(days=400)
    days = {}
    failed = 0
    for name, url in sources:
        try:
            cal = icalendar.Calendar.from_ical(fetch_source(url, force))
            found = recurring_ical_events.of(cal).between(window_start, window_end)
        except Exception:
            failed += 1
            continue
        for ev in found:
            if str(ev.get("STATUS", "")).upper() == "CANCELLED":
                continue
            start = ev.get("DTSTART").dt
            end_prop = ev.get("DTEND")
            end = end_prop.dt if end_prop else start
            title = str(ev.get("SUMMARY", "(no title)"))
            if isinstance(start, datetime.datetime):
                start = start.astimezone() if start.tzinfo else start
                end = end.astimezone() if isinstance(end, datetime.datetime) and end.tzinfo else end
                first, last = start.date(), end.date() if isinstance(end, datetime.datetime) else start.date()
                if isinstance(end, datetime.datetime) and end.time() == datetime.time(0) and last > first:
                    last -= datetime.timedelta(days=1)
                for offset in range((last - first).days + 1):
                    day = first + datetime.timedelta(days=offset)
                    if offset == 0 and offset == (last - first).days:
                        text = start.strftime(TIME_FMT) + (end.strftime("–" + TIME_FMT) if isinstance(end, datetime.datetime) and end != start else "")
                    elif offset == 0:
                        text = start.strftime(TIME_FMT) + " →"
                    else:
                        text = "continues"
                    days.setdefault(day, []).append((start.strftime("%H:%M") if offset == 0 else "00:00", text, title, name))
            else:
                first = start
                last = (end - datetime.timedelta(days=1)) if isinstance(end, datetime.date) and end > start else start
                for offset in range((last - first).days + 1):
                    day = first + datetime.timedelta(days=offset)
                    days.setdefault(day, []).append(("00:00", "All day", title, name))
    for items in days.values():
        items.sort(key=lambda e: (e[1] != "All day", e[0], e[2]))
    status = "sync_failed" if failed == len(sources) else ("partial" if failed else "ok")
    return days, status


class CalendarPopup(Gtk.Window):
    def __init__(self):
        super().__init__(title="calendar")
        today = datetime.date.today()
        self.year, self.month = today.year, today.month
        self.selected = today
        self.events = {}
        self.status = "loading"

        GtkLayerShell.init_for_window(self)
        GtkLayerShell.set_layer(self, GtkLayerShell.Layer.OVERLAY)
        GtkLayerShell.set_anchor(self, GtkLayerShell.Edge.TOP, True)
        GtkLayerShell.set_anchor(self, GtkLayerShell.Edge.LEFT, True)
        GtkLayerShell.set_margin(self, GtkLayerShell.Edge.TOP, CFG["margin_top"])
        GtkLayerShell.set_margin(self, GtkLayerShell.Edge.LEFT, CFG["margin_left"])
        GtkLayerShell.set_keyboard_mode(self, GtkLayerShell.KeyboardMode.ON_DEMAND)
        self.set_app_paintable(True)
        self.set_visual(self.get_screen().get_rgba_visual())

        self.card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        self.card.set_name("card")
        self.add(self.card)

        self.time_label = Gtk.Label(xalign=0)
        self.time_label.set_name("time")
        self.date_label = Gtk.Label(xalign=0)
        self.date_label.set_name("date")
        self.card.pack_start(self.time_label, False, False, 0)
        self.card.pack_start(self.date_label, False, False, 0)

        header = Gtk.Box(spacing=4)
        prev_btn = Gtk.Button(label="‹")
        next_btn = Gtk.Button(label="›")
        for b, d in ((prev_btn, -1), (next_btn, 1)):
            b.get_style_context().add_class("nav")
            b.set_relief(Gtk.ReliefStyle.NONE)
            b.set_can_focus(False)
            b.connect("clicked", lambda _b, delta=d: self.shift(delta))
        self.month_label = Gtk.Label()
        self.month_label.set_name("month")
        header.pack_start(prev_btn, False, False, 0)
        header.pack_start(self.month_label, True, True, 0)
        header.pack_start(next_btn, False, False, 0)
        self.card.pack_start(header, False, False, 6)

        self.grid = Gtk.Grid(column_spacing=2, row_spacing=2)
        self.grid.set_halign(Gtk.Align.CENTER)
        self.card.pack_start(self.grid, False, False, 0)

        sep = Gtk.Box()
        sep.get_style_context().add_class("sep")
        self.card.pack_start(sep, False, False, 4)
        self.events_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=5)
        self.card.pack_start(self.events_box, False, False, 0)

        self.connect("key-press-event", self.on_key)
        self.connect("focus-out-event", lambda *_: self.close_popup())
        self.connect("button-press-event", lambda *_: False)

        self.render()
        self.tick()
        GLib.timeout_add_seconds(1, self.tick)
        self.refresh_events()

    def refresh_events(self, force=False):
        def work():
            days, status = load_events(force)
            GLib.idle_add(self.set_events, days, status)
        threading.Thread(target=work, daemon=True).start()

    def set_events(self, days, status):
        self.events, self.status = days, status
        self.render()

    def label(self, text, *classes):
        lbl = Gtk.Label(label=text)
        for c in classes:
            lbl.get_style_context().add_class(c)
        return lbl

    def render(self):
        for child in self.grid.get_children():
            self.grid.remove(child)
        self.month_label.set_text(f"{calendar.month_name[self.month]} {self.year}")

        for col, name in enumerate(WEEKDAYS[FIRST_WEEKDAY:] + WEEKDAYS[:FIRST_WEEKDAY]):
            self.grid.attach(self.label(name, "wd"), col, 0, 1, 1)

        today = datetime.date.today()
        weeks = calendar.Calendar(firstweekday=FIRST_WEEKDAY).monthdatescalendar(self.year, self.month)
        for row, week in enumerate(weeks, start=1):
            for col, day in enumerate(week):
                classes = ["day"]
                if day.month != self.month:
                    classes.append("other")
                elif day.weekday() >= 5:
                    classes.append("weekend")
                if day == today:
                    classes.append("today")
                if day == self.selected:
                    classes.append("selected")
                self.grid.attach(self.day_cell(day, classes), col, row, 1, 1)
        self.grid.show_all()
        self.render_events()

    def day_cell(self, day, classes):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        box.pack_start(self.label(str(day.day), *classes), False, False, 0)
        dot = self.label("●", "dot")
        if not self.events.get(day):
            dot.get_style_context().add_class("off")
        box.pack_start(dot, False, False, 0)
        cell = Gtk.EventBox()
        cell.add(box)
        cell.connect("button-press-event", lambda *_a, d=day: self.select(d))
        return cell

    def select(self, day):
        self.selected = day
        if (day.year, day.month) != (self.year, self.month):
            self.year, self.month = day.year, day.month
        self.render()
        return True

    def render_events(self):
        for child in self.events_box.get_children():
            self.events_box.remove(child)
        today = datetime.date.today()
        if self.selected == today:
            title = "Today"
        elif self.selected == today + datetime.timedelta(days=1):
            title = "Tomorrow"
        else:
            title = self.selected.strftime("%A, %d %B")
        head = self.label(title)
        head.set_name("events-title")
        head.set_xalign(0)
        self.events_box.pack_start(head, False, False, 0)

        notes = {
            "no_sources": f"Add a link under [calendar] sources in {LOCAL_SETTINGS} to see events.",
            "no_libs": "Install python-recurring-ical-events to see events.",
            "loading": "Loading events…",
            "sync_failed": "Couldn't sync calendars (showing cached data if any).",
            "partial": "Some calendars failed to sync.",
        }
        items = self.events.get(self.selected, [])
        for _key, when, text, _cal in items[:MAX_LISTED]:
            row = Gtk.Box(spacing=10)
            t = self.label(when, "ev-time")
            t.set_xalign(0)
            t.set_size_request(86, -1)
            name = self.label(text, "ev-title")
            name.set_xalign(0)
            name.set_ellipsize(3)
            name.set_max_width_chars(28)
            row.pack_start(t, False, False, 0)
            row.pack_start(name, True, True, 0)
            self.events_box.pack_start(row, False, False, 0)
        if len(items) > MAX_LISTED:
            self.events_box.pack_start(self.note(f"+{len(items) - MAX_LISTED} more"), False, False, 0)
        if not items and self.status in ("ok", "partial"):
            self.events_box.pack_start(self.note("No events"), False, False, 0)
        if self.status in notes:
            self.events_box.pack_start(self.note(notes[self.status]), False, False, 0)
        self.events_box.show_all()

    def note(self, text):
        lbl = self.label(text, "ev-note")
        lbl.set_xalign(0)
        lbl.set_line_wrap(True)
        lbl.set_max_width_chars(34)
        return lbl

    def tick(self):
        now = datetime.datetime.now()
        self.time_label.set_text(now.strftime(TIME_FMT))
        self.date_label.set_text(now.strftime(CFG["date_format"]))
        return True

    def shift(self, delta, years=False):
        months = (self.year * 12 + self.month - 1) + (delta * 12 if years else delta)
        self.year, self.month = divmod(months, 12)
        self.month += 1
        self.render()

    def on_key(self, _w, event):
        key = Gdk.keyval_name(event.keyval)
        if key in ("Escape", "q"):
            self.close_popup()
        elif key in ("Left", "h"):
            self.shift(-1)
        elif key in ("Right", "l"):
            self.shift(1)
        elif key in ("Up", "k", "Page_Up"):
            self.shift(-1, years=True)
        elif key in ("Down", "j", "Page_Down"):
            self.shift(1, years=True)
        elif key in ("t", "Home"):
            today = datetime.date.today()
            self.year, self.month = today.year, today.month
            self.selected = today
            self.render()
        elif key == "r":
            self.status = "loading"
            self.render_events()
            self.refresh_events(force=True)
        return True

    def close_popup(self):
        try:
            os.remove(LOCK)
        except OSError:
            pass
        Gtk.main_quit()


def toggle_existing():
    """Second launch closes the open popup instead of stacking another."""
    try:
        with open(LOCK) as f:
            pid = int(f.read().strip())
        os.kill(pid, 0)
    except (OSError, ValueError):
        return False
    os.kill(pid, 15)
    try:
        os.remove(LOCK)
    except OSError:
        pass
    return True


def main():
    if toggle_existing():
        return 0
    with open(LOCK, "w") as f:
        f.write(str(os.getpid()))

    provider = Gtk.CssProvider()
    provider.load_from_data(build_css())
    Gtk.StyleContext.add_provider_for_screen(
        Gdk.Screen.get_default(), provider, Gtk.STYLE_PROVIDER_PRIORITY_USER)

    win = CalendarPopup()
    win.connect("destroy", lambda *_: Gtk.main_quit())
    win.show_all()
    try:
        Gtk.main()
    finally:
        try:
            os.remove(LOCK)
        except OSError:
            pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
