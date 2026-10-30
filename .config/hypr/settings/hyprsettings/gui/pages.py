"""Pages made of ordinary settings (Assistant, Assistant Monitor, Calendar, Hyprland, Hyprdots) and the page registry."""

from __future__ import annotations

import shutil
import subprocess

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gio, Gtk  # noqa: E402

from ..schema import PAGE_INTRO, for_page  # noqa: E402
from ..store import STARTUP_ID  # noqa: E402
from ..tui import App as TuiApp, assistant_disabled, state_dir  # noqa: E402
from . import ui  # noqa: E402
from .rows import setting_row  # noqa: E402


def schema_groups(win, page: str, column: Gtk.Box) -> None:
    group, last = None, object()
    for s in for_page(page):
        if group is None or s.group != last:
            group = Adw.PreferencesGroup(title=s.group)
            column.append(group)
            last = s.group
        group.add(setting_row(win, s))


def basic_page(win, page: str) -> Gtk.Widget:
    scroller, column = ui.page_box(PAGE_INTRO.get(page, ""))
    if page == "Calendar":
        calendar_group(win, column)
    else:
        schema_groups(win, page, column)
    if page == "Assistant":
        assistant_group(win, column)
    if page == "Hyprdots":
        startup_group(win, column)
        files_group(win, column)
    return scroller


# ---- Assistant ------------------------------------------------------------------------------------------------
def assistant_group(win, column: Gtk.Box) -> None:
    group = Adw.PreferencesGroup(title="Turn on or off")
    row = Adw.ActionRow(title="Assistant", use_markup=False,
                        subtitle="Off hides the bar button and Super+C shows a hint. Models and packages are left alone. Applies immediately.")
    sw = Gtk.Switch(active=not assistant_disabled(), valign=Gtk.Align.CENTER)
    row.add_suffix(sw)
    row.set_activatable_widget(sw)

    def toggled(w, _p):
        marker = state_dir() / "disabled"
        if w.get_active() == (not assistant_disabled()):
            return
        if w.get_active():
            if not shutil.which("ollama"):
                w.set_active(False)
                return ui.message(win, "Assistant not installed",
                                  "Ollama is not installed. Run ~/.config/hypr/assistant/setup.sh to set it up.")
            marker.unlink(missing_ok=True)
            win.toast("Assistant turned on.")
        else:
            marker.parent.mkdir(parents=True, exist_ok=True)
            marker.touch()
            win.toast("Assistant turned off.")
        subprocess.run(["pkill", "-SIGUSR2", "waybar"], capture_output=True)
    sw.connect("notify::active", toggled)
    group.add(row)
    column.append(group)


# ---- Calendar -----------------------------------------------------------------------------------------------------
def _check_calendar(name: str, link: str) -> tuple[str, str]:
    name, link = name.strip(), link.strip()
    if not link:
        raise ValueError("Enter a link or a path.")
    if "|" in name or "|" in link:
        raise ValueError("The | character cannot be used here.")
    if "://" in link and not link.startswith(("http://", "https://", "webcal://")):
        raise ValueError("Links must start with https:// or webcal://")
    return name or "Calendar", link


def calendar_group(win, column: Gtk.Box) -> None:
    store = win.store
    group = Adw.PreferencesGroup(title="Calendars the assistant and the clock popup can read",
                                 description="Links are private: they are only kept in user_settings.local.toml, which is never committed.")
    sources = store.calendar_sources()
    for i, src in enumerate(sources):
        name, _, link = src.partition("|") if "|" in src else (f"calendar {i + 1}", "", src)
        name = name.strip() or f"calendar {i + 1}"
        row = Adw.ActionRow(title=name, subtitle=TuiApp._mask(link.strip()), use_markup=False)
        if "calendar.sources" in store.staged:
            row.add_suffix(ui.tag("changed"))

        def edit(_b, i=i, name=name, link=link):
            def done(n, l):
                n, l = _check_calendar(n, l)
                current = store.calendar_sources()
                current[i] = f"{n}|{l}"
                store.set_calendar_sources(current)
                win.refresh()
            ui.ask(win, "Edit calendar", done, [("Name", name), ("Link or path", link.strip())])

        def remove(_b, i=i, name=name):
            def yes():
                current = store.calendar_sources()
                store.set_calendar_sources(current[:i] + current[i + 1:])
                win.refresh()
            ui.confirm(win, "Remove calendar?", f"Remove '{name}' from the list? The calendar itself is not touched.", "Remove", yes, destructive=True)
        for icon, tip, fn in (("document-edit-symbolic", "Rename or change the link", edit), ("user-trash-symbolic", "Remove", remove)):
            b = Gtk.Button(icon_name=icon, tooltip_text=tip, valign=Gtk.Align.CENTER, css_classes=["flat"])
            b.connect("clicked", fn)
            row.add_suffix(b)
        group.add(row)

    add = Adw.ButtonRow(title="Add a calendar…", start_icon_name="list-add-symbolic")

    def adding(_r):
        def done(n, l):
            n, l = _check_calendar(n, l)
            store.set_calendar_sources([*store.calendar_sources(), f"{n}|{l}"])
            win.refresh()
        ui.ask(win, "Add a calendar", done, [("Name (for example Personal)", ""), ("Link or path", "")],
               body="Google Calendar: Settings › your calendar › Integrate calendar › Secret address in iCal format. "
                    "A path to a .ics file or folder works too.", ok="Add")
    add.connect("activated", adding)
    group.add(add)
    column.append(group)


# ---- Hyprdots -------------------------------------------------------------------------------------------------------
def startup_group(win, column: Gtk.Box) -> None:
    store = win.store
    apps = store.startup_apps()
    if not apps:
        return
    group = Adw.PreferencesGroup(title="Start with the desktop", description="Takes effect at your next login.")
    off = set(store.disabled_startup())
    for app in apps:
        row = Adw.ActionRow(title=app["label"], subtitle=app["cmd"], use_markup=False, subtitle_selectable=True)
        sw = Gtk.Switch(active=app["id"] not in off, valign=Gtk.Align.CENTER)

        def toggled(w, _p, app_id=app["id"]):
            store.set_startup(app_id, w.get_active())
            win.changed()
        sw.connect("notify::active", toggled)
        row.add_suffix(sw)
        row.set_activatable_widget(sw)
        group.add(row)
    if STARTUP_ID in store.staged:
        group.set_header_suffix(ui.tag("changed"))
    column.append(group)


def files_group(win, column: Gtk.Box) -> None:
    group = Adw.PreferencesGroup(title="Files")
    for path, what in ((win.store.shared_path, "Shared defaults (tracked in the repo)"),
                       (win.store.local_path, "Your settings (private, never committed)")):
        row = Adw.ActionRow(title=path.name, subtitle=what, activatable=True, use_markup=False)
        row.add_suffix(Gtk.Image(icon_name="document-open-symbolic"))

        def open_file(_r, path=path):
            path.touch(exist_ok=True)
            Gio.AppInfo.launch_default_for_uri(path.as_uri(), None)
        row.connect("activated", open_file)
        group.add(row)
    column.append(group)
