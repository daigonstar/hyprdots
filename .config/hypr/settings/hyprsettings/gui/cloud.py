"""Cloud drives page: rclone accounts mounted as folders. Applied straight away; anything slow (rclone, systemctl,
signing in) runs in the background so the window never freezes."""

from __future__ import annotations

import threading
from typing import Callable

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, GLib, Gtk  # noqa: E402

from .. import cloud  # noqa: E402
from ..schema import BY_ID, PAGE_INTRO  # noqa: E402
from . import ui  # noqa: E402
from .rows import setting_row  # noqa: E402

STATES = {"active": ("connected", "yours"), "activating": ("starting", "changed"), "reloading": ("starting", "changed"),
          "failed": ("failed", "bad")}


def build(win) -> Gtk.Widget:
    scroller, column = ui.page_box(PAGE_INTRO["Cloud drives"])
    if not cloud.rclone():
        column.append(Adw.StatusPage(title="rclone is not installed", icon_name="folder-remote-symbolic",
                                     description="Cloud drives need rclone and fuse3: sudo pacman -S rclone fuse3"))
        return scroller

    group = Adw.PreferencesGroup(title="Accounts")
    refresh = Gtk.Button(icon_name="view-refresh-symbolic", css_classes=["flat"], tooltip_text="Check which drives are connected")
    refresh.connect("clicked", lambda _b: (cloud.invalidate(), win.refresh()))
    group.set_header_suffix(refresh)
    loading = Adw.ActionRow(title="Checking your accounts…")
    loading.add_prefix(Adw.Spinner())
    group.add(loading)
    column.append(group)

    more = Adw.PreferencesGroup()
    add = Adw.ButtonRow(title="Add an account…", start_icon_name="list-add-symbolic")
    add.connect("activated", lambda _r: add_account(win))
    folder = Adw.ButtonRow(title="Open the Cloud folder", start_icon_name="folder-open-symbolic")
    folder.connect("activated", lambda _r: open_folder(win, None))
    more.add(add)
    more.add(folder)
    column.append(more)
    column.append(cache_group(win))

    def loaded(accounts):
        group.remove(loading)
        if not accounts:
            group.add(Adw.ActionRow(title="No accounts yet", subtitle="Add one below.", use_markup=False))
        for acct in accounts:
            group.add(account_row(win, acct))
        return False
    threading.Thread(target=lambda: GLib.idle_add(loaded, cloud.accounts()), daemon=True).start()
    return scroller


def cache_group(win) -> Adw.PreferencesGroup:
    """File cache settings. Size and age only matter when keeping a local copy, so they grey out while streaming."""
    group = Adw.PreferencesGroup(title="How files are opened",
                                 description="Hover over an option for the trade-offs. Saved with the bar below; the drives "
                                             "then restart to use it.")
    mode = BY_ID["cloud.cache_mode"]
    mode_row = setting_row(win, mode)
    sized = [setting_row(win, BY_ID["cloud.cache_size_gb"]), setting_row(win, BY_ID["cloud.cache_days"])]
    for row in (mode_row, *sized):
        group.add(row)

    def follow(*_a):
        keeping = win.store.get(mode)[0] == "full"
        for row in sized:
            row.set_sensitive(keeping)
    drop = next(w for w in _walk(mode_row) if isinstance(w, Gtk.DropDown))
    drop.connect("notify::selected", follow)  # runs after the row has staged the new value
    follow()
    return group


def _walk(w):
    yield w
    child = w.get_first_child()
    while child:
        yield from _walk(child)
        child = child.get_next_sibling()


def restart_after_save(win, then=None) -> None:
    """After the cache settings are saved: offer to restart connected drives so they use them now."""
    names = cloud.connected()
    if not names:
        win.toast("Saved. Cloud drives use the new cache settings when they next connect.")
        return then and then(quiet=True)

    def go():
        run_task(win, "Restarting cloud drives", lambda st, c: cloud.restart_connected(st))
        if then:
            then(quiet=True)

    def later():
        win.toast("Saved. The cloud drives use the new cache settings from your next login.")
        if then:
            then(quiet=True)
    ui.confirm(win, "Restart cloud drives now?",
               f"The new cache settings apply when {', '.join(names)} restart. Anything open from a cloud drive is interrupted; "
               "files still waiting to upload are kept and carry on afterwards. Otherwise they apply at your next login.",
               "Restart", go, no="Later", on_no=later)


def account_row(win, acct: dict) -> Adw.ActionRow:
    name = acct["name"]
    connected = acct["state"] in ("active", "activating", "reloading")
    row = Adw.ActionRow(title=name, subtitle=f"{cloud.type_label(acct['type'])}  ·  {cloud.mount_path(name)}", use_markup=False)
    text, kind = STATES.get(acct["state"], ("off", "default"))
    pill = Gtk.Label(label=text, css_classes=["tag", kind], valign=Gtk.Align.CENTER)
    row.add_suffix(pill)

    for icon, tip, fn in (("folder-open-symbolic", "Open in the file manager", lambda: open_folder(win, name)),
                          ("user-trash-symbolic", "Remove this account", lambda: remove(win, name))):
        b = Gtk.Button(icon_name=icon, tooltip_text=tip, valign=Gtk.Align.CENTER, css_classes=["flat"])
        b.connect("clicked", lambda _b, fn=fn: fn())
        row.add_suffix(b)

    sw = Gtk.Switch(active=connected, valign=Gtk.Align.CENTER,
                    tooltip_text="Connected, and reconnects at every login" if connected else "Connect, and reconnect at every login")

    def toggled(w, _p):
        if w.get_active() == connected:
            return
        if w.get_active():
            run_task(win, f"Connecting {name}", lambda st, c: cloud.connect(name))
        else:
            run_task(win, f"Disconnecting {name}", lambda st, c: cloud.disconnect(name))
    sw.connect("notify::active", toggled)
    row.add_suffix(sw)
    return row


def open_folder(win, name: str | None) -> None:
    ok, msg = cloud.open_folder(name, str(win.store.get(BY_ID["hyprdots.file_manager"])[0]))
    win.toast(msg)


def remove(win, name: str) -> None:
    ui.confirm(win, "Remove this account?",
               f"Forget '{name}' on this computer? Your files in the cloud are not touched; you would sign in again to bring it back.",
               "Remove", lambda: run_task(win, f"Removing {name}", lambda st, c: cloud.remove(name)), destructive=True)


def run_task(win, title: str, fn: Callable[[Callable[[str], None], threading.Event], tuple[bool, str]], body: str = "") -> None:
    """Runs slow work in the background behind a dialog with a spinner, its latest status and Cancel."""
    cancel = threading.Event()
    dialog = Adw.AlertDialog(heading=title, body=body)
    box = Gtk.Box(spacing=10, halign=Gtk.Align.CENTER)
    box.append(Adw.Spinner())
    status = Gtk.Label(label="working…", wrap=True, css_classes=["dim-label"])
    box.append(status)
    dialog.set_extra_child(box)
    dialog.add_response("cancel", "Cancel")
    dialog.set_close_response("cancel")
    finished = {"done": False}
    # force_close() below also sends the Cancel response; only a real Cancel may stop the work
    dialog.connect("response", lambda _d, _r: finished["done"] or cancel.set())
    dialog.present(win)

    def set_status(text: str) -> None:
        GLib.idle_add(lambda: status.set_label(text) or False)

    def done(ok: bool, msg: str) -> bool:
        finished["done"] = True
        if not cancel.is_set():
            dialog.force_close()
        cloud.invalidate()
        win.refresh()
        if ok:
            win.toast(msg)
        elif not cancel.is_set():
            ui.message(win, "That did not work", msg)
        return False

    def work():
        try:
            ok, msg = fn(set_status, cancel)
        except Exception as e:  # never leave the dialog spinning
            ok, msg = False, str(e)
        GLib.idle_add(done, ok, msg)
    threading.Thread(target=work, daemon=True).start()


# ---- adding an account -------------------------------------------------------------------------------------------
def add_account(win) -> None:
    dialog = Adw.Dialog(title="Add an account", content_width=480)
    view = Adw.ToolbarView()
    view.add_top_bar(Adw.HeaderBar())
    group = Adw.PreferencesGroup(margin_top=12, margin_bottom=18, margin_start=18, margin_end=18,
                                 description="Google Drive, OneDrive and Dropbox sign in through your browser. Nextcloud, ownCloud "
                                             "and other WebDAV servers need the address, your username and a password.")
    for kind, label, how in cloud.PROVIDERS:
        row = Adw.ActionRow(title=label, subtitle="Sign in with your browser" if how == "oauth" else "Address, username, password",
                            activatable=True, use_markup=False)
        row.add_suffix(Gtk.Image(icon_name="go-next-symbolic"))
        row.connect("activated", lambda _r, kind=kind, label=label, how=how: (dialog.close(), ask_name(win, kind, label, how)))
        group.add(row)
    view.set_content(group)
    dialog.set_child(view)
    dialog.present(win)


def ask_name(win, kind: str, label: str, how: str) -> None:
    def got(name):
        name = name.strip()
        cloud.check_name(name)  # ValueError brings the dialog back with the reason
        if how == "oauth":
            run_task(win, f"Adding {label}", lambda st, c: cloud.setup_oauth(name, kind, st, c),
                     "A browser window opens for you to sign in. Cancel stops waiting.")
        else:
            ask_dav(win, name, kind, label)
    ui.ask(win, f"Name for this {label} drive", got, [("Folder name: letters, numbers, - and _ only", cloud.suggest_name(kind))])


def _plain_http_ok(address: str) -> bool:
    host = address.split("//", 1)[1].split("/", 1)[0].split(":")[0]
    return host == "localhost" or host.startswith(("127.", "10.", "192.168.")) or host.endswith(".local")


def ask_dav(win, name: str, kind: str, label: str) -> None:
    example = {"nextcloud": "https://cloud.example.com", "owncloud": "https://owncloud.example.com",
               "webdav": "https://dav.example.com/files/me/"}[kind]
    hint = "The full address of the WebDAV folder." if kind == "webdav" else "Just the address you open in your browser."

    def got(server, user, password):
        server, user = server.strip(), user.strip()
        if not server.startswith(("http://", "https://")) or len(server) < 9:
            raise ValueError(f"The address starts with https://, for example {example}")
        if server.startswith("http://") and not _plain_http_ok(server):
            raise ValueError("Use https:// so your password is not sent in the clear.")
        if not user:
            raise ValueError("Enter your username.")
        if not password:
            raise ValueError("Enter your password.")
        run_task(win, f"Adding {label}", lambda st, c: cloud.setup_dav(name, kind, server, user, password, st, c))
    ui.ask(win, f"Sign in to {label}", got, [("Address", "https://"), ("Username", ""), ("Password", "", True)],
           body=f"{hint} With two-factor sign-in, create an app password (Settings › Security) and use that.", ok="Add")
