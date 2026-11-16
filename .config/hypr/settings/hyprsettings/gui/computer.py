"""Computer page: name, kind of device, what is inside, clock and language (the work is in ../computer.py).
Changes apply straight away, through pkexec, so they wait for the password without holding up the window."""

from __future__ import annotations

import re
import threading
import time

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gdk, GLib, Gtk  # noqa: E402

from .. import computer  # noqa: E402
from ..schema import PAGE_INTRO  # noqa: E402
from . import ui  # noqa: E402


def _in_background(win, work, then_refresh: bool = True) -> None:
    """Runs a root change off the main thread, says how it went, then shows the page again as it really is now."""
    def run():
        ok, message = work()

        def done():
            if ok:
                win.toast(message)
            else:
                ui.message(win, "Not changed", message)
            if then_refresh and win.page == "Computer":
                win.refresh()
            return False
        GLib.idle_add(done)
    threading.Thread(target=run, daemon=True).start()


def _ticking(widget: Gtk.Widget, seconds: int, tick) -> None:
    """Calls tick every few seconds while the page is open."""
    tick()
    source = GLib.timeout_add_seconds(seconds, lambda: (tick() if widget.get_mapped() else None) or True)
    widget.connect("destroy", lambda *_: GLib.source_remove(source))


# ---- the card at the top ---------------------------------------------------------------------------------------------
def _hero(column: Gtk.Box, ident: dict) -> None:
    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4, halign=Gtk.Align.CENTER, margin_top=6)
    box.append(Gtk.Label(label=computer.CHASSIS_GLYPH.get(ident["chassis"], computer.CHASSIS_GLYPH["desktop"]),
                         css_classes=["glyph", "computer-glyph"]))
    box.append(Gtk.Label(label=computer.display_name(ident), css_classes=["title-1"], wrap=True, justify=Gtk.Justification.CENTER))
    under = " · ".join(filter(None, [computer.model(), computer.os_name()]))
    if under:
        box.append(Gtk.Label(label=under, css_classes=["dim-label"], wrap=True, justify=Gtk.Justification.CENTER))
    column.append(box)


# ---- name ------------------------------------------------------------------------------------------------------------
def _name_group(win, column: Gtk.Box, ident: dict) -> None:
    group = Adw.PreferencesGroup(title="Name", description="How this PC shows itself: in the quick tray, your terminal "
                                 "prompt, and to other computers, phones and printers on your network.")
    pretty = Adw.EntryRow(title="Computer name", text=computer.display_name(ident), show_apply_button=True)
    pretty.set_tooltip_text("Any name you like, with spaces and capitals: Dee's Desktop")
    static = Adw.EntryRow(title="Network name", text=ident["static"], show_apply_button=True)
    static.set_tooltip_text("Lower-case letters, numbers and hyphens: dees-desktop")
    made = Gtk.Label(css_classes=["dim-label", "caption"], valign=Gtk.Align.CENTER)
    pretty.add_suffix(made)

    def typed(row):
        # Shows the network name the new name would give, the way a Mac does under its Sharing name
        new = computer.network_name(row.get_text())
        made.set_label(f"→ {new}" if row.get_text().strip() != computer.display_name(ident) and new else "")
    pretty.connect("changed", typed)

    def pretty_applied(row):
        text = row.get_text().strip()
        problem = computer.check_pretty_name(text) or computer.check_network_name(computer.network_name(text))
        if problem:
            return ui.message(win, "Cannot use that name", problem)
        _in_background(win, lambda: computer.rename(text))
    pretty.connect("apply", pretty_applied)

    def static_applied(row):
        text = row.get_text().strip().lower()
        problem = computer.check_network_name(text)
        if problem:
            return ui.message(win, "Cannot use that network name", problem)
        _in_background(win, lambda: computer.rename(computer.display_name(ident), text))
    static.connect("apply", static_applied)

    found = Adw.ActionRow(title="Found on your network as")
    found.set_subtitle_selectable(True)
    if computer.mdns_running():
        found.set_subtitle(f"{ident['static']}.local")
    else:
        found.set_subtitle(f"{ident['static']}, by computers that ask your router. Install and start avahi so others can use "
                           f"{ident['static']}.local")
    for row in (pretty, static, found):
        group.add(row)
    if ident["running"] != ident["static"]:
        later = Adw.ActionRow(title="Still running as " + ident["running"], subtitle="Some apps keep the old name until you log out")
        group.add(later)
    column.append(group)


# ---- device ----------------------------------------------------------------------------------------------------------
def _device_group(win, column: Gtk.Box, ident: dict) -> None:
    group = Adw.PreferencesGroup(title="Device")
    keys = [k for k, _ in computer.CHASSIS]
    kind = Adw.ComboRow(title="Kind of device", model=Gtk.StringList.new([label for _, label in computer.CHASSIS]))
    kind.set_subtitle("Worked out from the hardware" if not ident["chassis_set"] else "Set by you")
    kind.set_selected(keys.index(ident["chassis"]) if ident["chassis"] in keys else 0)
    location = Adw.EntryRow(title="Where it is", text=ident["location"], show_apply_button=True)
    location.set_tooltip_text("Optional, for when you have more than one: Office, Living room")

    def picked(row, _param):
        chosen = keys[row.get_selected()]
        if chosen != ident["chassis"] or not ident["chassis_set"]:
            _in_background(win, lambda: computer.set_device(chosen, ident["location"]))
    kind.connect("notify::selected", picked)
    location.connect("apply", lambda row: _in_background(win, lambda: computer.set_device(keys[kind.get_selected()], row.get_text())))
    group.add(kind)
    group.add(location)
    column.append(group)


# ---- about -----------------------------------------------------------------------------------------------------------
def _about_group(win, column: Gtk.Box, ident: dict) -> None:
    group = Adw.PreferencesGroup(title="About this PC")
    copy = Gtk.Button(icon_name="edit-copy-symbolic", tooltip_text="Copy these details", valign=Gtk.Align.CENTER, css_classes=["flat"])
    group.set_header_suffix(copy)
    rows = computer.specs()
    shown = {}
    for label, value in rows:
        row = Adw.ActionRow(title=label, subtitle=value, subtitle_selectable=True, css_classes=["property"])
        shown[label] = row
        group.add(row)

    def copied(_b):
        Gdk.Display.get_default().get_clipboard().set(computer.specs_text(computer.display_name(ident), computer.specs()))
        win.toast("Details copied.")
    copy.connect("clicked", copied)
    if "Up for" in shown:
        _ticking(group, 30, lambda: shown["Up for"].set_subtitle(computer.uptime()))
    column.append(group)


# ---- date and time ---------------------------------------------------------------------------------------------------
def _clock_group(win, column: Gtk.Box) -> None:
    clock = computer.clock()
    group = Adw.PreferencesGroup(title="Date and time")
    now = Adw.ActionRow(title="Now")
    _ticking(now, 1, lambda: now.set_subtitle(time.strftime("%A %-d %B %Y, %H:%M:%S")))
    group.add(now)
    if not clock["managed"]:
        group.set_description("systemd's time service is not answering, so these can only be looked at here.")

    auto = Adw.SwitchRow(title="Set the time from the internet", active=clock["ntp"], sensitive=clock["can_ntp"])
    auto.set_subtitle(("In step with the internet's clocks" if clock["synced"] else "Waiting to reach a time server")
                      if clock["ntp"] else ("Off: set it yourself below" if clock["can_ntp"] else "No time service (systemd-timesyncd) is installed"))
    auto.connect("notify::active", lambda row, _p: row.get_active() != clock["ntp"] and
                 _in_background(win, lambda: computer.helper("ntp", "on" if row.get_active() else "off")))
    group.add(auto)

    zones = computer.zones()
    if clock["zone"] not in zones:
        zones = [clock["zone"], *zones]
    zone = Adw.ComboRow(title="Time zone", model=Gtk.StringList.new([z.replace("_", " ") for z in zones]), enable_search=True,
                        sensitive=clock["managed"])
    zone.set_expression(Gtk.PropertyExpression.new(Gtk.StringObject, None, "string"))
    zone.set_selected(zones.index(clock["zone"]))
    zone.connect("notify::selected", lambda row, _p: zones[row.get_selected()] != clock["zone"] and
                 _in_background(win, lambda: computer.helper("timezone", zones[row.get_selected()])))
    group.add(zone)

    manual = Adw.ActionRow(title="Set the date and time", subtitle="Only when it is not set from the internet")
    change = Gtk.Button(label="Change…", valign=Gtk.Align.CENTER, sensitive=clock["managed"] and not clock["ntp"])
    manual.add_suffix(change)

    def ask_time(_b):
        def submit(text):
            text = " ".join(text.split())
            if not re.match(r"^\d{4}-\d\d-\d\d \d\d:\d\d(:\d\d)?$", text):
                raise ValueError("Write it as YYYY-MM-DD HH:MM, for example 2026-11-16 14:30.")
            _in_background(win, lambda: computer.helper("time", text))
        ui.ask(win, "Set the date and time", submit, [("Date and time (YYYY-MM-DD HH:MM)", time.strftime("%Y-%m-%d %H:%M"))], ok="Set")
    change.connect("clicked", ask_time)
    group.add(manual)

    rtc = Adw.SwitchRow(title="Windows is on this PC too", active=clock["local_rtc"], sensitive=clock["managed"],
                        subtitle="Keeps the hardware clock in local time like Windows does, so the clock is not hours out after "
                                 "switching between them. Leave off otherwise")
    rtc.connect("notify::active", lambda row, _p: row.get_active() != clock["local_rtc"] and
                _in_background(win, lambda: computer.helper("rtc", "local" if row.get_active() else "utc")))
    group.add(rtc)
    column.append(group)


# ---- language --------------------------------------------------------------------------------------------------------
def _language_group(win, column: Gtk.Box) -> None:
    group = Adw.PreferencesGroup(title="Language and region", description="For menus, dates, numbers and money in apps. "
                                 "Takes effect the next time you log in.")
    names = computer.locales()
    current = computer.current_locale()
    if current and current not in names:
        names = [current, *names]
    if not names:
        group.add(Adw.ActionRow(title="Language", subtitle=current or "Not set"))
        column.append(group)
        return
    row = Adw.ComboRow(title="Language", model=Gtk.StringList.new([computer.locale_label(n) for n in names]), enable_search=True)
    row.set_expression(Gtk.PropertyExpression.new(Gtk.StringObject, None, "string"))
    row.set_selected(names.index(current) if current in names else 0)
    row.connect("notify::selected", lambda r, _p: names[r.get_selected()] != current and
                _in_background(win, lambda: computer.helper("locale", names[r.get_selected()])))
    group.add(row)
    more = Adw.ActionRow(title="Missing a language?", subtitle="Uncomment it in /etc/locale.gen, then run: sudo locale-gen")
    more.set_subtitle_selectable(True)
    group.add(more)
    column.append(group)


def build(win) -> Gtk.Widget:
    scroller, column = ui.page_box(PAGE_INTRO["Computer"])
    ident = computer.identity()
    _hero(column, ident)
    _name_group(win, column, ident)
    _device_group(win, column, ident)
    _about_group(win, column, ident)
    _clock_group(win, column)
    _language_group(win, column)
    return scroller
