#!/usr/bin/env python3
"""The first-run welcome: shown once, at the first login after installing, with the keys to know and the few settings
worth a look on a new PC. `welcome.py --force` shows it again."""
import subprocess
import sys
from pathlib import Path

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gtk

APP_ID = "com.hyprdots.welcome"
MARKER = Path.home() / ".local/state/hyprdots/welcomed"
SCRIPTS = Path.home() / ".config/hypr/scripts"
KEYS = (("Super + Space", "Open an app"), ("Super + T", "Terminal"), ("Super + E", "Files"), ("Super + Q", "Close a window"),
        ("Alt + Tab", "Switch windows"), ("Super + Tab", "See all workspaces"), ("Super + W", "Change the wallpaper"),
        ("Super + L", "Lock the screen"), ("Super + K", "Every other key"))
SETUP = (("Screens", "Resolution, refresh rate and how your screens are arranged.", "Displays"),
         ("Keyboard", "This desktop starts with a UK layout. Pick yours under Keyboard.", "Hyprland"),
         ("Look", "Colours come from your wallpaper. Choose which part uses which, and the font.", "Theme"),
         ("Network", "Wi-Fi and wired connections.", "Network"),
         ("Sleep and lock", "When the screen turns off and the PC sleeps.", "Power & lock"))


def open_settings(page):
    subprocess.Popen([str(SCRIPTS / "settings.sh"), f"--page={page}"], start_new_session=True)


def build(window):
    page = Adw.PreferencesPage()
    keys = Adw.PreferencesGroup(title="Keys to know", description="Super is the Windows key. You can change any of these in Settings.")
    for combo, what in KEYS:
        row = Adw.ActionRow(title=what)
        hint = Gtk.Label(label=combo)
        hint.add_css_class("dim-label")
        row.add_suffix(hint)
        keys.add(row)
    page.add(keys)
    setup = Adw.PreferencesGroup(title="Worth a look", description="Some defaults here were set up for one particular PC.")
    for title, text, target in SETUP:
        row = Adw.ActionRow(title=title, subtitle=text, activatable=True)
        row.add_suffix(Gtk.Image.new_from_icon_name("go-next-symbolic"))
        row.connect("activated", lambda _r, t=target: open_settings(t))
        setup.add(row)
    page.add(setup)
    box = Adw.ToolbarView()
    header = Adw.HeaderBar(title_widget=Adw.WindowTitle(title="Welcome to your desktop"))
    box.add_top_bar(header)
    box.set_content(page)
    done = Gtk.Button(label="Get started", halign=Gtk.Align.CENTER, margin_top=8, margin_bottom=12)
    done.add_css_class("suggested-action")
    done.add_css_class("pill")
    done.connect("clicked", lambda _b: window.close())
    box.add_bottom_bar(done)
    return box


def main():
    if MARKER.exists() and "--force" not in sys.argv:
        return 0
    # Written first: if this window ever fails, it should not come back at every login
    MARKER.parent.mkdir(parents=True, exist_ok=True)
    MARKER.touch()
    app = Adw.Application(application_id=APP_ID)

    def activate(app):
        window = Adw.ApplicationWindow(application=app, title="Welcome", default_width=560, default_height=680)
        window.set_content(build(window))
        window.present()
    app.connect("activate", activate)
    return app.run([sys.argv[0]])


if __name__ == "__main__":
    sys.exit(main())
