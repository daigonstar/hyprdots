"""Performance page: CPU, graphics card and RAM limits (the work is in ../power.py)."""

from __future__ import annotations

import threading
import time

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, GLib, Gtk  # noqa: E402

from .. import power  # noqa: E402
from ..schema import PAGE_INTRO  # noqa: E402
from . import ui  # noqa: E402


def _in_background(win, work, done) -> None:
    """pkexec waits for the password, so it must not hold up the window."""
    def run():
        result = work()
        GLib.idle_add(lambda: done(*result) and False)
    threading.Thread(target=run, daemon=True).start()


def _not_installed(column: Gtk.Box) -> None:
    group = Adw.PreferencesGroup(title="Not set up yet")
    row = Adw.ActionRow(title="The power service is not installed", subtitle=f"Run this in a terminal: {power.INSTALL}")
    row.set_subtitle_selectable(True)
    group.add(row)
    column.append(group)


def _mode_group(win, column: Gtk.Box, config: dict) -> None:
    group = Adw.PreferencesGroup(title="Mode")
    first, busy, checks = None, [False], {}
    for key, title, text in power.MODES:
        check = Gtk.CheckButton(active=config["mode"] == key, valign=Gtk.Align.CENTER)
        checks[key] = check
        if first:
            check.set_group(first)
        first = first or check
        row = Adw.ActionRow(title=title, subtitle=text, activatable_widget=check)
        row.add_prefix(check)
        group.add(row)

        def toggled(button, key=key):
            if not button.get_active() or busy[0] or key == config["mode"]:
                return
            busy[0] = True

            def done(ok, message):
                busy[0] = False
                if ok:
                    config["mode"] = key
                    win.toast("Mode changed.")
                else:
                    busy[0] = True  # back to what is really set, without trying to save that
                    checks[config["mode"]].set_active(True)
                    busy[0] = False
                    ui.message(win, "Mode not changed", message)
            _in_background(win, lambda: power.change(mode=key), done)
        check.connect("toggled", toggled)
    column.append(group)


def _guard_group(win, column: Gtk.Box, config: dict) -> None:
    group = Adw.PreferencesGroup(title="Heat guard", description="Holds the CPU or graphics card back when it stays this hot for 15 seconds, "
                                 "and lets go once it has been well under for a minute. You get a notification each time.")
    guard = Adw.SwitchRow(title="Heat guard", active=config["guard"])
    cpu = Adw.SpinRow.new_with_range(70, 100, 1)
    cpu.set_title("CPU limit (°C)")
    cpu.set_subtitle("Boost goes off above this. Most Ryzen CPUs are made to reach 95°C under full load")
    cpu.set_value(config["cpu_limit"])
    gpu = Adw.SpinRow.new_with_range(70, 110, 1)
    gpu.set_title("Graphics card limit (°C)")
    gpu.set_subtitle("Its hottest point, the junction. The card drops to its lowest power limit above this")
    gpu.set_value(config["gpu_limit"])
    apply = Gtk.Button(label="Apply", valign=Gtk.Align.CENTER, css_classes=["suggested-action"])
    footer = Adw.ActionRow(title="Save the guard settings")
    footer.add_suffix(apply)
    for row in (guard, cpu, gpu, footer):
        group.add(row)

    def save(_b):
        wanted = {"guard": guard.get_active(), "cpu_limit": int(cpu.get_value()), "gpu_limit": int(gpu.get_value())}
        apply.set_sensitive(False)

        def done(ok, message):
            apply.set_sensitive(True)
            if ok:
                config.update(wanted)
                win.toast("Heat guard saved.")
            else:
                ui.message(win, "Not saved", message)
        _in_background(win, lambda: power.change(**wanted), done)
    apply.connect("clicked", save)
    column.append(group)


def _live_group(column: Gtk.Box) -> Gtk.Widget:
    group = Adw.PreferencesGroup(title="Right now")
    rows = {key: Adw.ActionRow(title=title) for key, title in (("cpu", "CPU"), ("gpu", "Graphics card"), ("ram", "RAM"), ("last", "Last time the guard stepped in"))}
    for row in rows.values():
        row.set_subtitle_lines(3)
        group.add(row)

    def show(st: dict) -> None:
        cpu, gpu, ram = st.get("cpu", {}), st.get("gpu", {}), st.get("ram", {})
        boost = "unknown" if cpu.get("boost") is None else ("on" if cpu["boost"] else "off")
        if cpu.get("boost_locked"):
            boost = "off in the BIOS (Core Performance Boost), so no mode here can turn it on"
        rows["cpu"].set_subtitle(f"{_deg(cpu.get('temp'))}, boost {boost}" + (", held back to cool down" if cpu.get("held_back") else ""))
        if gpu.get("cap_w"):
            rows["gpu"].set_subtitle(f"{_deg(gpu.get('temp'))} at its hottest point, power limit {gpu['cap_w']}W "
                                     f"(it allows {gpu['lowest_w']}-{gpu['default_w']}W)" + (", held back to cool down" if gpu.get("held_back") else ""))
        else:
            rows["gpu"].set_subtitle("No card whose power limit can be set: only AMD cards are supported")
        rows["ram"].set_subtitle(", ".join(filter(None, [_deg(ram.get("temp")) if ram.get("temp") else "", power.ram_note(ram)])) or "Not reported")
        events = [e for e in st.get("events", []) if "held back" in e["text"]]
        rows["last"].set_subtitle(f"{time.strftime('%H:%M', time.localtime(events[-1]['time']))}: {events[-1]['text']}" if events else "Not since this PC started")

    def tick():
        if not group.get_mapped():
            return True
        st = power.status()
        if st:
            show(st)
        else:
            for row in rows.values():
                row.set_subtitle("The power service is not running")
        return True
    tick()
    source = GLib.timeout_add_seconds(2, tick)
    group.connect("destroy", lambda *_: GLib.source_remove(source))
    column.append(group)
    return group


def _deg(value) -> str:
    return f"{value:.0f}°C" if isinstance(value, (int, float)) else "temperature unknown"


def build(win) -> Gtk.Widget:
    scroller, column = ui.page_box(PAGE_INTRO["Performance"])
    if not power.installed():
        _not_installed(column)
        return scroller
    st = power.status() or {}
    config = dict(st.get("config") or {"mode": "full", "guard": True, "cpu_limit": 92, "gpu_limit": 100})
    _live_group(column)
    _mode_group(win, column, config)
    _guard_group(win, column, config)
    return scroller
