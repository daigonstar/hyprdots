"""Pages made of ordinary settings (Assistant, Assistant Monitor, Calendar, Hyprland, Hyprdots) and the page registry."""

from __future__ import annotations

import datetime
import shutil
import subprocess
import threading

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gio, GLib, Gtk  # noqa: E402

from ..schema import PAGE_INTRO, for_page  # noqa: E402
from ..store import CUSTOM_STARTUP_ID, STARTUP_ID  # noqa: E402
from ..tui import App as TuiApp, assistant_disabled, localcal, refresh_calendars, state_dir  # noqa: E402
from . import ui  # noqa: E402
from .rows import setting_row  # noqa: E402


def schema_groups(win, page: str, column: Gtk.Box) -> None:
    group, last = None, object()
    for s in for_page(page):
        if s.group == "Theme overrides":  # its own group, applied with one click (theme_override.group)
            continue
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
    if page == "Assistant Monitor":
        health_monitor_group(win, column)
    if page == "Hyprdots":
        startup_group(win, column)
        files_group(win, column)
    if page == "Power & lock":
        lock_preview_button(win, column)
    if page == "Launcher":
        launcher_buttons(win, column)
    if page == "Theme":
        from . import theme_override
        theme_override.group(win, column)
    return scroller


# ---- Launcher --------------------------------------------------------------------------------------------------------
def launcher_buttons(win, column: Gtk.Box) -> None:
    """Try it (opens the launcher in the style picked here, saved or not) and Clear history."""
    import os
    from pathlib import Path
    script = Path(win.store.dir) / "launcher" / "launcher.sh"
    look = next((g for g in _children(column) if isinstance(g, Adw.PreferencesGroup) and g.get_title() == "Look"), None)
    if look is not None:
        button = Gtk.Button(label="Try it", valign=Gtk.Align.CENTER, css_classes=["pill"],
                            tooltip_text="Open the launcher with the choices below, even before you save. Esc closes it.")

        def try_it(_b):
            from ..schema import for_page
            args = []
            for s in for_page("Launcher"):
                value = win.store.get(s)[0]
                args += ["--style", str(value)] if s.key == "style" else ["--set", f"{s.key}={value}"]
            subprocess.Popen([str(script), *args], start_new_session=True, stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL)
        button.connect("clicked", try_it)
        look.set_header_suffix(button)

    group = Adw.PreferencesGroup(title="History")
    column.append(group)
    row = Adw.ActionRow(title="Forget which apps you open",
                        subtitle="Empties Frequent and puts results back in plain order, until you use some apps again.")
    clear = Gtk.Button(label="Clear history", valign=Gtk.Align.CENTER, css_classes=["destructive-action", "pill"])

    def do_clear():
        state = Path(os.environ.get("XDG_STATE_HOME") or Path.home() / ".local/state") / "hyprdots" / "launcher-usage.json"
        state.unlink(missing_ok=True)
        win.toast("Launcher history cleared.")
    clear.connect("clicked", lambda _b: ui.confirm(win, "Clear the launcher history?",
                                                   "Frequent will be empty until you open some apps again.", "Clear", do_clear))
    row.add_suffix(clear)
    group.add(row)


# ---- Power & lock ----------------------------------------------------------------------------------------------------
PREVIEW_SECONDS = 10


def lock_preview_button(win, column: Gtk.Box) -> None:
    """A Preview button on the Lock screen section: shows the lock screen with the choices as they stand (saved or
    not), with a grace period so moving the mouse brings you straight back."""
    group = next((g for g in _children(column) if isinstance(g, Adw.PreferencesGroup) and g.get_title() == "Lock screen"), None)
    if group is None:
        return
    button = Gtk.Button(label="Preview", valign=Gtk.Align.CENTER, css_classes=["pill"],
                        tooltip_text="Show the lock screen with these choices, including ones you have not saved yet")

    def preview():
        import os
        from pathlib import Path
        from .. import lockscreen
        if subprocess.run(["pidof", "hyprlock", "gtklock"], capture_output=True).returncode == 0:
            return win.toast("The screen is already locked.")
        path = Path(os.environ.get("XDG_RUNTIME_DIR") or "/tmp") / "hyprlock-preview.conf"
        lockscreen.write(path, lockscreen.render(win.store.lock_options()))
        subprocess.Popen(["hyprlock", "-c", str(path), "--grace", str(PREVIEW_SECONDS)], start_new_session=True,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL)
    button.connect("clicked", lambda _b: ui.confirm(
        win, "Preview the lock screen?",
        f"Your screen locks for real. Move the mouse or press a key within {PREVIEW_SECONDS} seconds to come straight back; "
        "after that, unlock with your password as usual.", "Preview", preview))
    group.set_header_suffix(button)


def _children(box: Gtk.Widget):
    child = box.get_first_child()
    while child:
        yield child
        child = child.get_next_sibling()


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


def health_monitor_group(win, column: Gtk.Box) -> None:
    """On and off, at the top of the page: the settings below only matter while it is on."""
    from .. import healthmonitor
    group = Adw.PreferencesGroup(title="Turn on or off")
    row = Adw.ActionRow(title="Health monitor", use_markup=False,
                        subtitle="Checks every few minutes for failed services, full disks, heat and waiting updates, and tells you. "
                                 "Off stops it straight away and keeps these settings for when you turn it back on.")
    sw = Gtk.Switch(active=healthmonitor.is_on(), valign=Gtk.Align.CENTER)
    row.add_suffix(sw)
    row.set_activatable_widget(sw)

    def toggled(w, _p):
        if w.get_active() == healthmonitor.is_on():
            return
        ok, message = healthmonitor.turn(w.get_active())
        if not ok:
            w.set_active(healthmonitor.is_on())
            return ui.message(win, "Not changed", message)
        win.toast(message)
    sw.connect("notify::active", toggled)
    group.add(row)
    column.insert_child_after(group, column.get_first_child())  # under the page's intro, above its settings


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

    refresh = Adw.ButtonRow(title="Refresh calendars now", start_icon_name="view-refresh-symbolic",
                            tooltip_text="Download every calendar again, so changes you made show up in the clock popup straight away")

    def refreshing(row):
        if "calendar.sources" in store.staged:
            win.toast("Save your calendar changes first, then refresh.")
            return
        row.set_sensitive(False)
        row.set_title("Refreshing…")

        def done(ok, msg):
            row.set_sensitive(True)
            row.set_title("Refresh calendars now")
            win.toast(msg)
        threading.Thread(target=lambda: GLib.idle_add(done, *refresh_calendars()), daemon=True).start()
    refresh.connect("activated", refreshing)
    group.add(refresh)
    column.append(group)
    column.append(local_events_group(win))


def local_events_group(win) -> Adw.PreferencesGroup:
    """Events kept on this PC. Applied straight away, like the clock popup's own + Add event."""
    group = Adw.PreferencesGroup(title="Events on this PC",
                                 description="Shown in the clock popup and readable by the assistant, but never sent anywhere. "
                                             "Past events are hidden here.")
    for ev in TuiApp._local_events():
        row = Adw.ActionRow(title=ev["title"], subtitle=localcal.describe(ev) + (f"\n{ev['notes']}" if ev["notes"] else ""),
                            use_markup=False)
        b = Gtk.Button(icon_name="user-trash-symbolic", tooltip_text="Remove", valign=Gtk.Align.CENTER, css_classes=["flat"])

        def remove(_b, ev=ev):
            def yes():
                localcal.remove(ev["uid"])
                win.refresh()
            more = " Every repeat of it goes too." if ev["repeat"] else ""
            ui.confirm(win, "Remove event?", f"Remove '{ev['title']}' ({localcal.describe(ev)})?{more}", "Remove", yes, destructive=True)
        b.connect("clicked", remove)
        row.add_suffix(b)
        group.add(row)
    add = Adw.ButtonRow(title="Add an event…", start_icon_name="list-add-symbolic")
    add.connect("activated", lambda _r: add_event(win))
    group.add(add)
    return group


def add_event(win) -> None:
    dialog = Adw.Dialog(title="Add an event", content_width=440)
    view = Adw.ToolbarView()
    header = Adw.HeaderBar(show_end_title_buttons=False, show_start_title_buttons=False)
    cancel = Gtk.Button(label="Cancel")
    cancel.connect("clicked", lambda _b: dialog.close())
    save = Gtk.Button(label="Add", css_classes=["suggested-action"])
    header.pack_start(cancel)
    header.pack_end(save)
    view.add_top_bar(header)

    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14, margin_top=12, margin_bottom=18, margin_start=18, margin_end=18)
    what = Adw.PreferencesGroup()
    title = Adw.EntryRow(title="Name")
    notes = Adw.EntryRow(title="Notes (optional)")
    what.add(title)
    what.add(notes)
    box.append(what)

    cal = Gtk.Calendar(css_classes=["card"])
    box.append(cal)

    when = Adw.PreferencesGroup()
    all_day = Adw.SwitchRow(title="All day")
    start = Adw.EntryRow(title="Starts", text="09:00")
    end = Adw.EntryRow(title="Ends", text="10:00")
    repeat = Adw.ComboRow(title="Repeat", model=Gtk.StringList.new(list(localcal.REPEATS.values())))
    for row in (all_day, start, end, repeat):
        when.add(row)
    all_day.connect("notify::active", lambda w, _p: (start.set_sensitive(not w.get_active()), end.set_sensitive(not w.get_active())))
    box.append(when)
    error = Gtk.Label(wrap=True, xalign=0, css_classes=["error-text"], visible=False)
    box.append(error)

    def add(*_a):
        d = cal.get_date()
        day = datetime.date(d.get_year(), d.get_month(), d.get_day_of_month())
        try:
            if all_day.get_active():
                localcal.add(title.get_text(), day, repeat=list(localcal.REPEATS)[repeat.get_selected()], notes=notes.get_text())
            else:
                localcal.add(title.get_text(), day, localcal.parse_time(start.get_text()), localcal.parse_time(end.get_text()),
                             list(localcal.REPEATS)[repeat.get_selected()], notes.get_text())
        except (ValueError, OSError) as e:
            error.set_label(str(e))
            error.set_visible(True)
            return
        dialog.close()
        win.toast(f"Added '{title.get_text().strip()}'.")
        win.refresh()
    save.connect("clicked", add)
    title.connect("entry-activated", add)
    view.set_content(Gtk.ScrolledWindow(child=box, propagate_natural_height=True, hscrollbar_policy=Gtk.PolicyType.NEVER))
    dialog.set_child(view)
    dialog.present(win)
    title.grab_focus()


# ---- Hyprdots -------------------------------------------------------------------------------------------------------
def startup_group(win, column: Gtk.Box) -> None:
    store = win.store
    apps = store.startup_apps()
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

    for i, app in enumerate(store.custom_startup()):
        row = Adw.ActionRow(title=app["label"], subtitle=app["cmd"], use_markup=False, subtitle_selectable=True)
        row.add_suffix(ui.tag("yours"))

        def remove(_b, i=i, label=app["label"]):
            def yes():
                store.remove_startup(i)
                win.changed()
                win.refresh()
            ui.confirm(win, "Remove startup app?", f"Stop starting '{label}' when you log in? The app itself is not uninstalled.",
                       "Remove", yes, destructive=True)
        b = Gtk.Button(icon_name="user-trash-symbolic", tooltip_text="Remove from startup", valign=Gtk.Align.CENTER, css_classes=["flat"])
        b.connect("clicked", remove)
        row.add_suffix(b)
        group.add(row)

    add = Adw.ButtonRow(title="Add a startup app…", start_icon_name="list-add-symbolic")

    def adding(_r):
        def done(label, cmd):
            store.add_startup(label, cmd)  # a ValueError brings the dialog back with the message
            win.changed()
            win.refresh()
        ui.ask(win, "Add a startup app", done, [("Name (for example Signal)", ""), ("Command (for example signal-desktop)", "")],
               body="It starts in the background each time you log in, once the bar's tray is ready.", ok="Add")
    add.connect("activated", adding)
    group.add(add)
    if STARTUP_ID in store.staged or CUSTOM_STARTUP_ID in store.staged:
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
