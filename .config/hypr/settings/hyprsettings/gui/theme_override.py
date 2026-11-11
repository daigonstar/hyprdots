"""Theme page: the Theme overrides group. Picking a look applies it straight away (no Save needed), without touching
anything else you have changed but not saved. See ../theme_override.py."""

from __future__ import annotations

import threading

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gdk, Gio, GLib, Gtk  # noqa: E402

from .. import theme, theme_override  # noqa: E402
from ..schema import BY_ID  # noqa: E402
from . import ui  # noqa: E402

_provider: Gtk.CssProvider | None = None


def match_scheme() -> None:
    """Dark or light widgets to suit the large panel colour (light for the XP style)."""
    light = theme.luminance(theme.colors()["bg"]) >= 0.4
    Adw.StyleManager.get_default().set_color_scheme(Adw.ColorScheme.FORCE_LIGHT if light else Adw.ColorScheme.FORCE_DARK)


def restyle_window() -> None:
    """This window's own colours, again, after a switch (the provider added last wins over the one from startup)."""
    global _provider
    display = Gdk.Display.get_default()
    if _provider is not None:
        Gtk.StyleContext.remove_provider_for_display(display, _provider)
    _provider = Gtk.CssProvider()
    _provider.load_from_string(ui.css())
    Gtk.StyleContext.add_provider_for_display(display, _provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
    match_scheme()


BUILT_IN = {"luna": "The built-in green hill", "mac": "The built-in gradient", "game": "The built-in pixel landscape", "scifi": "The built-in grid horizon"}


def wallpaper_row(win, key: str, name: str) -> Adw.ActionRow:
    """A look's wallpaper: its built-in one, or a picture of your own (kept in your settings only)."""
    from pathlib import Path
    chosen = theme_override.chosen_wallpaper(win.store, key)
    row = Adw.ActionRow(title=f"{name} wallpaper",
                        subtitle=Path(chosen).name if chosen else BUILT_IN.get(key, "The built-in one"))
    choose = Gtk.Button(label="Choose\u2026", valign=Gtk.Align.CENTER)

    def picked(dialog, result):
        try:
            file = dialog.open_finish(result)
        except GLib.Error:
            return  # cancelled
        if file and file.get_path():
            theme_override.choose_wallpaper(win.store, key, file.get_path())
            win.refresh()

    def open_dialog(_b):
        images = Gtk.FileFilter(name="Pictures")
        images.add_mime_type("image/*")
        filters = Gio.ListStore.new(Gtk.FileFilter)
        filters.append(images)
        start = Path(chosen).parent if chosen else Path.home() / "Pictures/wallpapers"
        dialog = Gtk.FileDialog(title=f"{name} wallpaper", filters=filters, default_filter=images)
        if start.is_dir():
            dialog.set_initial_folder(Gio.File.new_for_path(str(start)))
        dialog.open(win, None, picked)
    choose.connect("clicked", open_dialog)
    row.add_suffix(choose)
    if chosen:
        back = Gtk.Button(icon_name="edit-undo-symbolic", valign=Gtk.Align.CENTER, css_classes=["flat"],
                          tooltip_text="Use the built-in one")
        back.connect("clicked", lambda _b: (theme_override.choose_wallpaper(win.store, key, ""), win.refresh()))
        row.add_suffix(back)
    return row


def group(win, column: Gtk.Box) -> None:
    current = win.store.get(BY_ID["theme.override"])[0]
    box = Adw.PreferencesGroup(title="Theme overrides",
                               description="One click restyles the whole desktop. Your own settings below are kept "
                                           "as they are, and come back exactly when you pick None.")
    first = None
    busy = {"on": False}

    def picked(button, key):
        if not button.get_active() or busy["on"] or key == win.store.get(BY_ID["theme.override"])[0]:
            return
        busy["on"] = True
        win.toast("Switching the desktop's look…")

        def work():
            try:
                problems = theme_override.switch(win.store, key)
            except Exception as e:  # shown, never silently lost
                problems = [str(e)]
            GLib.idle_add(done, problems)

        def done(problems):
            busy["on"] = False
            restyle_window()
            win.refresh()
            if problems:
                ui.message(win, "Some parts were not restyled", "\n".join(problems))
            else:
                name = dict(theme_override.CHOICES)[key]
                win.toast("Back to your own theme." if key == theme_override.NONE else f"{name} is on.")
            return False
        threading.Thread(target=work, daemon=True).start()

    for key, name, what in theme_override.LOOKS:
        check = Gtk.CheckButton(active=key == current, valign=Gtk.Align.CENTER)
        if first is None:
            first = check
        else:
            check.set_group(first)
        check.connect("toggled", picked, key)
        row = Adw.ActionRow(title=name, subtitle=what, activatable_widget=check)
        row.add_prefix(check)
        box.add(row)
    for key, name, _what in theme_override.LOOKS:
        if key != theme_override.NONE:
            box.add(wallpaper_row(win, key, name))
    if current != theme_override.NONE:
        box.add(Adw.ActionRow(title="Your own settings below are not in use",
                              subtitle="They take effect again when you pick None.", sensitive=False))
    column.insert_child_after(box, column.get_first_child())  # under the page's intro, above its settings
