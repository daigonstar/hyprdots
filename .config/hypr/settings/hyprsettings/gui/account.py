"""User page: your name, picture and password (the work is in ../account.py)."""

from __future__ import annotations

import threading

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gdk, Gio, GLib, Gtk  # noqa: E402

from .. import account, design  # noqa: E402
from ..schema import PAGE_INTRO  # noqa: E402
from . import ui  # noqa: E402

AVATAR_SIZE = 96


def _show_picture(avatar: Adw.Avatar, remove: Gtk.Widget) -> None:
    path = account.picture_path()
    texture = None
    if path.exists():
        try:
            texture = Gdk.Texture.new_from_filename(str(path))
        except GLib.Error:
            pass
    avatar.set_custom_image(texture)
    remove.set_visible(texture is not None)


def _refresh_desktop(win) -> None:
    """The lock screen is a generated file that names the picture."""
    design.refresh_all(win.store)


def _pick_picture(win, avatar: Adw.Avatar, remove: Gtk.Widget) -> None:
    images = Gtk.FileFilter(name="Pictures")
    images.add_pixbuf_formats()
    filters = Gio.ListStore.new(Gtk.FileFilter)
    filters.append(images)
    dialog = Gtk.FileDialog(title="Choose a picture", filters=filters)

    def chosen(d, result):
        try:
            file = d.open_finish(result)
        except GLib.Error:  # you cancelled
            return
        try:
            problem = account.set_picture(file.get_path())
        except ValueError as e:
            return ui.message(win, "Could not use that picture", str(e))
        _show_picture(avatar, remove)
        _refresh_desktop(win)
        win.toast("Picture saved." if not problem else "Picture saved, but the login screen could not be told about it.")

    dialog.open(win, None, chosen)


def _picture_group(win, column: Gtk.Box, name: str) -> Adw.Avatar:
    group = Adw.PreferencesGroup()
    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10, halign=Gtk.Align.CENTER)
    avatar = Adw.Avatar(size=AVATAR_SIZE, text=name or account.username(), show_initials=True)
    box.append(avatar)
    buttons = Gtk.Box(spacing=8, halign=Gtk.Align.CENTER)
    choose = Gtk.Button(label="Choose a picture…")
    remove = Gtk.Button(label="Remove")
    remove.add_css_class("flat")
    choose.connect("clicked", lambda _b: _pick_picture(win, avatar, remove))

    def removed(_b):
        problem = account.remove_picture()
        _show_picture(avatar, remove)
        _refresh_desktop(win)
        win.toast("Picture removed." if not problem else "Picture removed, but the login screen could not be told.")

    remove.connect("clicked", removed)
    buttons.append(choose)
    buttons.append(remove)
    box.append(buttons)
    group.add(box)
    column.append(group)
    _show_picture(avatar, remove)
    return avatar


def _details_group(win, column: Gtk.Box, avatar: Adw.Avatar) -> None:
    group = Adw.PreferencesGroup(title="Details")
    group.add(Adw.ActionRow(title="Username", subtitle=account.username()))
    name = Adw.EntryRow(title="Your name", text=account.real_name(), show_apply_button=True)

    def applied(row):
        try:
            problem = account.set_real_name(row.get_text())
        except ValueError as e:
            return ui.message(win, "Could not change your name", str(e))
        if problem:
            return ui.message(win, "Could not change your name", problem)
        avatar.set_text(row.get_text().strip() or account.username())
        win.toast("Name saved.")

    name.connect("apply", applied)
    group.add(name)
    column.append(group)


def _change_password(win) -> None:
    def submit(current, new, again):
        if not current or not new:
            raise ValueError("Fill in your current password and a new one.")
        if new != again:
            raise ValueError("The two new passwords are not the same.")

        def work():
            worked, message = account.change_password(current, new)
            GLib.idle_add(done, worked, message)

        threading.Thread(target=work, daemon=True).start()

    def done(worked, message):
        if worked:
            ui.message(win, "Password changed", " ".join(filter(None, ["Use it the next time you log in or unlock.", account.keyring_note()])))
        else:
            ui.message(win, "Password not changed", message)
        return False

    ui.ask(win, "Change password", submit, [("Current password", "", True), ("New password", "", True), ("New password again", "", True)], ok="Change password")


def _password_group(win, column: Gtk.Box) -> None:
    group = Adw.PreferencesGroup(title="Password")
    row = Adw.ActionRow(title="Password", subtitle="Used to log in, unlock the screen and approve changes to the system")
    button = Gtk.Button(label="Change…", valign=Gtk.Align.CENTER)
    button.connect("clicked", lambda _b: _change_password(win))
    row.add_suffix(button)
    group.add(row)
    column.append(group)


def build(win) -> Gtk.Widget:
    scroller, column = ui.page_box(PAGE_INTRO["User"])
    avatar = _picture_group(win, column, account.real_name())
    _details_group(win, column, avatar)
    _password_group(win, column)
    return scroller
