"""Appearance page: GTK theme, icons, cursor and font. Applied the moment you change them, like the terminal version."""

from __future__ import annotations

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, GLib, Gtk  # noqa: E402

from .. import gtktheme  # noqa: E402
from ..schema import PAGE_INTRO  # noqa: E402
from . import ui  # noqa: E402

LISTS = (("theme", "Theme", "Window and button style for GTK apps.", gtktheme.themes),
         ("icons", "Icons", "Icon set used in file managers and dialogs.", gtktheme.icon_themes),
         ("cursor", "Mouse cursor", "Pointer theme.", gtktheme.cursor_themes),
         ("font", "Font", "Font family for GTK apps.", gtktheme.fonts))


def searchable_dropdown(names: list[str], current: str) -> Gtk.DropDown:
    drop = Gtk.DropDown(model=Gtk.StringList.new(names), valign=Gtk.Align.CENTER, enable_search=len(names) > 12)
    drop.set_expression(Gtk.PropertyExpression.new(Gtk.StringObject, None, "string"))
    if current in names:
        drop.set_selected(names.index(current))
    return drop


def build(win) -> Gtk.Widget:
    scroller, column = ui.page_box(PAGE_INTRO["Appearance"])
    now = gtktheme.current()
    font, size = gtktheme.font_parts(now["font"])

    def apply(**changes):
        ok, msg = gtktheme.apply(**changes)
        win.toast(msg)
        if not ok:
            win.refresh()

    group = Adw.PreferencesGroup(title="GTK look")
    refresh = Gtk.Button(icon_name="view-refresh-symbolic", css_classes=["flat"], tooltip_text="Read the current look again")
    refresh.connect("clicked", lambda _b: win.refresh())
    group.set_header_suffix(refresh)

    for key, label, help_, lister in LISTS:
        names = lister()
        current = font if key == "font" else now[key]
        if current not in names:
            names.insert(0, current)
        row = Adw.ActionRow(title=label, subtitle=f"{help_} {len(names)} installed.", use_markup=False)
        drop = searchable_dropdown(names, current)

        def picked(d, _p, key=key, names=names, current=current):
            name = names[d.get_selected()]
            if name != current:
                apply(**{key: f"{name} {size}" if key == "font" else name})
        drop.connect("notify::selected", picked)
        row.add_suffix(drop)
        group.add(row)
        if key == "cursor":
            group.add(_spin_row("Cursor size", "Pointer size in pixels (24 is normal).", "px", int(now["cursor_size"]), 8, 128, 1, 0,
                                lambda v: apply(cursor_size=int(v))))
    group.add(_spin_row("Font size", "Text size in points (11 is normal).", "pt", float(size or 11), 6, 40, 0.5, 1,
                        lambda v: apply(font=f"{font} {v:g}")))

    dark = Adw.SwitchRow(title="Prefer dark mode", subtitle="Asks apps that support it to use their dark style.", active=bool(now["dark"]))
    dark.connect("notify::active", lambda r, _p: apply(dark=r.get_active()))
    group.add(dark)
    column.append(group)
    return scroller


def _spin_row(title, subtitle, unit, value, lo, hi, step, digits, on_change) -> Adw.ActionRow:
    row = Adw.ActionRow(title=title, subtitle=subtitle, use_markup=False)
    spin = Gtk.SpinButton(adjustment=Gtk.Adjustment(value=value, lower=lo, upper=hi, step_increment=step, page_increment=step * 4),
                          digits=digits, valign=Gtk.Align.CENTER, numeric=True)
    # Wait until the value settles so settings.ini is not rewritten on every arrow click
    pending = {"id": 0}

    def fire():
        pending["id"] = 0
        on_change(spin.get_value())
        return False

    def changed(_w):
        if pending["id"]:
            GLib.source_remove(pending["id"])
        pending["id"] = GLib.timeout_add(600, fire)
    spin.connect("value-changed", changed)
    row.add_suffix(Gtk.Label(label=unit, css_classes=["dim-label"]))
    row.add_suffix(spin)
    return row
