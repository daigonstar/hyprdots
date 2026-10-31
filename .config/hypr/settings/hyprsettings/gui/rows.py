"""One row per schema Setting, picked by its kind. Every row stages into the Store; nothing is written until Save."""

from __future__ import annotations

from typing import Any

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gtk, Pango  # noqa: E402

from ..schema import Setting  # noqa: E402
from ..tui import App as TuiApp  # noqa: E402  (value formatting only; prompt_toolkit is not loaded)
from . import ui  # noqa: E402

APP_KEYS = ("terminal", "file_manager", "browser", "store")


def show(s: Setting, value: Any) -> str:
    return TuiApp._show(s, value)


def setting_row(win, s: Setting) -> Adw.ActionRow:
    store = win.store
    value, source = store.get(s)
    row = Adw.ActionRow(title=s.label, subtitle=s.help, use_markup=False,
                        tooltip_text=(s.tip + "\n\n" if s.tip else "") + f"Takes effect {s.effect}.")
    pill = ui.tag(source)
    undo = Gtk.Button(icon_name="edit-undo-symbolic", valign=Gtk.Align.CENTER, css_classes=["flat"],
                      tooltip_text="Put the default back", visible=source != "default")
    row.add_suffix(pill)
    row.add_suffix(undo)

    def staged():
        src = store.get(s)[1]
        ui.set_tag(pill, src)
        undo.set_visible(src != "default")
        win.changed()

    def reset(_b):
        store.reset(s)
        win.refresh()
    undo.connect("clicked", reset)

    def stage(v) -> bool:
        try:
            store.stage(s, v)
        except ValueError as e:
            win.toast(f"{s.label}: {e}")
            return False
        staged()
        return True

    if s.kind == "bool":
        sw = Gtk.Switch(active=bool(value), valign=Gtk.Align.CENTER)
        sw.connect("notify::active", lambda w, _p: stage(w.get_active()))
        row.add_suffix(sw)
        row.set_activatable_widget(sw)

    elif s.kind in ("model", "vision_model"):
        from . import models_dialog
        text = show(s, value)
        current = Gtk.Label(label=text, css_classes=["dim-label"], ellipsize=Pango.EllipsizeMode.END,
                            width_chars=min(len(text), 22), max_width_chars=28)
        button = Gtk.Button(label="Change…", valign=Gtk.Align.CENTER)
        button.connect("clicked", lambda _b: models_dialog.choose(win, s))
        row.add_suffix(current)
        row.add_suffix(button)
        row.set_activatable_widget(button)

    elif s.kind == "choice" or (s.kind == "text" and s.key in APP_KEYS):
        items = list(store.app_choices(s)) if s.kind == "text" else [(v, label) for v, label in s.choices]
        if all(str(v) != str(value) for v, _ in items):
            items.insert(0, (value, f"{show(s, value)} (current)"))
        custom = s.allow_custom or s.kind == "text"
        labels = [label.split("  (")[0] if s.kind != "text" else label for _, label in items] + (["Something else…"] if custom else [])
        drop = Gtk.DropDown(model=Gtk.StringList.new(labels), valign=Gtk.Align.CENTER)
        index = next((i for i, (v, _) in enumerate(items) if str(v) == str(value)), 0)
        drop.set_selected(index)
        last = [index]

        def picked(d, _p):
            i = d.get_selected()
            if i == last[0]:
                return
            if custom and i == len(items):
                d.set_selected(last[0])  # stays on the old value unless the dialog is answered
                ui.ask(win, s.label, lambda t: stage_custom(t), [("", str(store.get(s)[0]))], body=s.help)
                return
            if stage(items[i][0]):
                last[0] = i
            else:
                d.set_selected(last[0])

        def stage_custom(text):
            store.stage(s, text)  # ValueError goes back to the dialog
            win.refresh()
        drop.connect("notify::selected", picked)
        row.add_suffix(drop)

    elif s.kind in ("int", "float") and s.lo is not None and s.hi is not None:
        digits = 0 if s.kind == "int" else max(1, len(f"{s.step:g}".partition(".")[2]))
        adj = Gtk.Adjustment(value=float(value), lower=s.lo, upper=s.hi, step_increment=s.step, page_increment=s.step * 10)
        spin = Gtk.SpinButton(adjustment=adj, digits=digits, valign=Gtk.Align.CENTER, numeric=True)
        spin.connect("value-changed", lambda w: stage(int(w.get_value()) if s.kind == "int" else round(w.get_value(), digits)))
        if s.unit:
            row.add_suffix(Gtk.Label(label=s.unit, css_classes=["dim-label"]))
        row.add_suffix(spin)

    else:  # text, list and unbounded numbers: typed, applied on Enter or when leaving the box
        text = ", ".join(value) if s.kind == "list" else str(value)
        entry = Gtk.Entry(text=text, valign=Gtk.Align.CENTER, width_chars=24, placeholder_text="(empty)")

        def commit(*_a):
            if entry.get_text() == (", ".join(store.get(s)[0]) if s.kind == "list" else str(store.get(s)[0])):
                return
            if stage(entry.get_text()):
                entry.remove_css_class("error")
            else:
                entry.add_css_class("error")
        entry.connect("activate", commit)
        focus = Gtk.EventControllerFocus()
        focus.connect("leave", commit)
        entry.add_controller(focus)
        row.add_suffix(entry)
    return row
