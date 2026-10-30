"""File types page: which app opens each kind of file. Written straight to ~/.config/mimeapps.list."""

from __future__ import annotations

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gio, Gtk  # noqa: E402

from .. import mimeapps  # noqa: E402
from ..schema import PAGE_INTRO  # noqa: E402
from . import ui  # noqa: E402

_APPS: dict | None = None  # installed apps, read once per window (Refresh reads them again)


def apps() -> dict:
    global _APPS
    if _APPS is None:
        _APPS = mimeapps.installed_apps()
    return _APPS


def app_icon(app_id: str | None) -> Gtk.Image:
    icon = None
    if app_id:
        try:
            info = Gio.DesktopAppInfo.new(app_id)
            icon = info.get_icon() if info else None
        except TypeError:
            icon = None
    image = Gtk.Image.new_from_gicon(icon) if icon else Gtk.Image(icon_name="application-x-executable-symbolic")
    image.set_pixel_size(28)
    return image


def chooser_row(win, title: str, subtitle: str, mimes: list[str]) -> Adw.ActionRow:
    installed = apps()
    options = mimeapps.candidates(mimes, installed)
    main, mixed = mimeapps.category_state(mimes, installed)
    row = Adw.ActionRow(title=title, subtitle=subtitle + ("  ·  some of these types use another app" if mixed else ""), use_markup=False)
    icon = app_icon(main)
    row.add_prefix(icon)
    if not options:
        row.add_suffix(Gtk.Label(label="No installed app can open these", css_classes=["dim-label"]))
        return row
    ids = [i for i, _ in options]
    names = [n for _, n in options]
    if main not in ids:
        ids.insert(0, None)
        names.insert(0, "Nothing chosen")
    drop = Gtk.DropDown(model=Gtk.StringList.new(names), valign=Gtk.Align.CENTER, enable_search=len(names) > 12)
    drop.set_expression(Gtk.PropertyExpression.new(Gtk.StringObject, None, "string"))
    drop.set_selected(ids.index(main))

    def picked(d, _p):
        app_id = ids[d.get_selected()]
        if app_id is None:
            return
        ok, why = mimeapps.set_default(app_id, mimes)
        if ok:
            win.toast(f"{title} now open with {installed[app_id]['name']}.")
            row.remove(icon_holder[0])
            icon_holder[0] = app_icon(app_id)
            row.add_prefix(icon_holder[0])
        else:
            win.toast(why)
    icon_holder = [icon]
    drop.connect("notify::selected", picked)
    row.add_suffix(drop)
    return row


def build(win) -> Gtk.Widget:
    scroller, column = ui.page_box(PAGE_INTRO["File types"])
    group = Adw.PreferencesGroup(title="Opens with")
    refresh = Gtk.Button(icon_name="view-refresh-symbolic", css_classes=["flat"], tooltip_text="Look for newly installed apps")

    def reread(_b):
        global _APPS
        _APPS = None
        win.refresh()
    refresh.connect("clicked", reread)
    group.set_header_suffix(refresh)
    for label, what, mimes in mimeapps.CATEGORIES:
        group.add(chooser_row(win, label, what, mimes))
    column.append(group)

    other = Adw.PreferencesGroup(title="Something else")
    button = Adw.ButtonRow(title="Choose the app for another file type…", start_icon_name="list-add-symbolic")

    def ask_type(_r):
        def got(text):
            mime = mimeapps.resolve_type(text)
            if not mimeapps.candidates([mime], apps()):
                raise ValueError(f"No installed app says it can open {mime}.")
            dialog = Adw.Dialog(title=mime, content_width=520)
            view = Adw.ToolbarView()
            view.add_top_bar(Adw.HeaderBar())
            box = Adw.PreferencesGroup(margin_top=12, margin_bottom=18, margin_start=18, margin_end=18)
            box.add(chooser_row(win, mime, "Pick the app below", [mime]))
            view.set_content(box)
            dialog.set_child(view)
            dialog.present(win)
        ui.ask(win, "File ending or type", got, [("For example .mkv, .epub or application/pdf", "")])
    button.connect("activated", ask_type)
    other.add(button)
    column.append(other)
    return scroller
