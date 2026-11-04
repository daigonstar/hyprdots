#!/usr/bin/env python3
"""Keybind cheatsheet: a card over a dimmed screen listing every keybind as key caps, grouped like the
hypr-settings Keybinds page. The Super key is drawn as the logo picked in hypr-settings (Hyprdots page).

Keys: type to search, Esc closes (or clears the search first). Clicking outside the card closes it too.
Run through cheatsheet.sh (it preloads gtk4-layer-shell, which has to be loaded before GTK). Running it again
while it is open closes it. --list prints the rows instead of opening the window."""

import sys
import shutil
from pathlib import Path

HYPR_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HYPR_DIR / "settings"))
from hyprsettings.schema import BY_ID  # noqa: E402
from hyprsettings.store import Store  # noqa: E402
from hyprsettings.theme import ICON_FONT, colors, super_glyph  # noqa: E402


# Combos keybinds.lua sets itself, outside the rebindable list
FIXED = [
    ("SUPER + 1-0", "Go to workspace 1-10"),
    ("SUPER + SHIFT + 1-0", "Move window to workspace 1-10"),
    ("SUPER + Left drag", "Move window"),
    ("SUPER + Right drag", "Resize window"),
    ("Volume keys", "Change volume"),
    ("Brightness keys", "Change screen brightness"),
    ("Media keys", "Play, pause, next, previous"),
]

KEY_NAMES = {
    "control": "Ctrl", "ctrl": "Ctrl", "shift": "Shift", "alt": "Alt", "space": "Space", "return": "Enter",
    "escape": "Esc", "tab": "Tab", "left": "←", "right": "→", "up": "↑", "down": "↓",
    "mouse_down": "Scroll ↓", "mouse_up": "Scroll ↑",
}


# Keys for apps you choose to install: not worth listing without them
OPTIONAL_APPS = {"obsidian": "md.obsidian.Obsidian", "editor": "zeditor", "store": "io.github.kolunmi.Bazaar"}


def installed(app: str) -> bool:
    flatpaks = (Path.home() / ".local/share/flatpak/app" / app, Path("/var/lib/flatpak/app") / app)
    return shutil.which(app) is not None or any(p.exists() for p in flatpaks)


def load():
    """[(group, [(keys, label), ...]), ...] with your changes applied, and the Super logo setting."""
    store = Store(HYPR_DIR)
    groups, index = [], {}
    for row in store.keybind_rows():
        keys, _source = store.get_keybind(row)
        if keys == "none":  # left unbound in hypr-settings
            continue
        if row["id"] in OPTIONAL_APPS and not installed(OPTIONAL_APPS[row["id"]]):
            continue
        group = row["group"] or "Other"
        if group not in index:
            index[group] = len(groups)
            groups.append((group, []))
        groups[index[group]][1].append((keys, row["label"]))
    groups.append(("Fixed", FIXED))
    logo, _source = store.get(BY_ID["look.super_logo"])
    return groups, logo


def caps(keys: str) -> list[str]:
    """'SUPER + SHIFT + left' -> ['SUPER', 'Shift', '←']. SUPER is kept as is and drawn as the logo."""
    out = []
    for part in (p.strip() for p in keys.split("+")):
        if not part:
            continue
        if part.upper() in ("SUPER", "MOD4", "WIN"):
            out.append("SUPER")
        elif part.lower() in KEY_NAMES:
            out.append(KEY_NAMES[part.lower()])
        elif len(part) == 1:
            out.append(part.upper())
        else:
            out.append(part)
    return out


def css(c: dict) -> str:
    return f"""
window, window.background {{ background: transparent; }}
.backdrop {{ background: alpha(black, 0.6); }}
.card {{
    background: {c['bg']};
    border: 2px solid alpha({c['accent']}, 0.55);
    border-radius: 22px;
    padding: 26px 30px 22px 30px;
    box-shadow: 0 18px 60px alpha(black, 0.5);
}}
.logo {{ font-family: "{ICON_FONT}"; font-size: 30px; color: {c['accent']}; }}
.title {{ font-size: 22px; font-weight: 800; color: {c['fg']}; }}
.subtitle {{ color: alpha({c['fg']}, 0.55); }}
entry.search {{
    min-width: 280px; min-height: 36px; border-radius: 12px; padding: 0 12px;
    background: alpha({c['fg']}, 0.07); color: {c['fg']}; border: 1px solid alpha({c['accent']}, 0.35);
    box-shadow: none; outline: none;
}}
entry.search:focus-within {{ border-color: {c['accent']}; }}
.group {{
    background: alpha({c['fg']}, 0.04);
    border-radius: 16px;
    padding: 14px 16px 12px 16px;
}}
.group-title {{
    color: {c['accent']}; font-weight: 800; font-size: 12px; letter-spacing: 2px;
    margin-bottom: 6px;
}}
.row {{ padding: 4px 2px; }}
.label {{ color: {c['fg']}; }}
.cap {{
    font-family: "{ICON_FONT}"; font-weight: 700; font-size: 12px;
    color: {c['fg']};
    background: alpha({c['fg']}, 0.09);
    border: 1px solid alpha({c['fg']}, 0.16);
    border-bottom-width: 3px;
    border-radius: 7px;
    padding: 1px 8px;
    min-width: 14px;
}}
.cap.super {{ color: {c['bg']}; background: {c['accent']}; border-color: shade({c['accent']}, 0.7); font-size: 15px; padding: 0 8px; }}
.plus {{ color: alpha({c['fg']}, 0.35); font-size: 11px; }}
.empty {{ color: alpha({c['fg']}, 0.5); margin: 30px; }}
.hint {{ color: alpha({c['fg']}, 0.4); font-size: 11px; }}
"""


def build_window(app, Gtk, Gtk4LayerShell, Gdk):
    groups, logo = load()

    win = Gtk.ApplicationWindow(application=app)
    if Gtk4LayerShell.is_supported():
        Gtk4LayerShell.init_for_window(win)
        Gtk4LayerShell.set_namespace(win, "cheatsheet")
        Gtk4LayerShell.set_layer(win, Gtk4LayerShell.Layer.OVERLAY)
        Gtk4LayerShell.set_keyboard_mode(win, Gtk4LayerShell.KeyboardMode.EXCLUSIVE)
        Gtk4LayerShell.set_exclusive_zone(win, -1)
        for edge in (Gtk4LayerShell.Edge.TOP, Gtk4LayerShell.Edge.BOTTOM, Gtk4LayerShell.Edge.LEFT, Gtk4LayerShell.Edge.RIGHT):
            Gtk4LayerShell.set_anchor(win, edge, True)
    else:
        win.set_default_size(1200, 800)

    backdrop = Gtk.Box(css_classes=["backdrop"])
    win.set_child(backdrop)

    card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=18, css_classes=["card"],
                   halign=Gtk.Align.CENTER, valign=Gtk.Align.CENTER, hexpand=True, vexpand=True)
    backdrop.append(card)

    # Header: logo, title, search
    header = Gtk.Box(spacing=14)
    header.append(Gtk.Label(label=super_glyph("arch" if logo == "text" else logo), css_classes=["logo"]))
    titles = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, valign=Gtk.Align.CENTER)
    titles.append(Gtk.Label(label="Keybinds", xalign=0, css_classes=["title"]))
    titles.append(Gtk.Label(label="Change them in hypr-settings → Keybinds", xalign=0, css_classes=["subtitle"]))
    header.append(titles)
    search = Gtk.SearchEntry(placeholder_text="Search keybinds", css_classes=["search"],
                             hexpand=True, halign=Gtk.Align.END, valign=Gtk.Align.CENTER)
    header.append(search)
    card.append(header)

    # Groups laid out in columns
    flow = Gtk.FlowBox(selection_mode=Gtk.SelectionMode.NONE, homogeneous=False,
                       min_children_per_line=1, max_children_per_line=3,
                       column_spacing=14, row_spacing=14, valign=Gtk.Align.START)
    rows = []  # (row widget, group box, searchable text)
    group_boxes = []
    for name, binds in groups:
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2, css_classes=["group"], valign=Gtk.Align.START)
        box.append(Gtk.Label(label=name.upper(), xalign=0, css_classes=["group-title"]))
        for keys, label in binds:
            row = Gtk.Box(spacing=16, css_classes=["row"])
            keyline = Gtk.Box(spacing=4, valign=Gtk.Align.CENTER)
            parts = caps(keys)
            for i, part in enumerate(parts):
                if i:
                    keyline.append(Gtk.Label(label="+", css_classes=["plus"]))
                if part == "SUPER":
                    keyline.append(Gtk.Label(label=super_glyph(logo), css_classes=["cap", "super"]))
                else:
                    keyline.append(Gtk.Label(label=part, css_classes=["cap"]))
            row.append(Gtk.Label(label=label, xalign=0, hexpand=True, css_classes=["label"]))
            row.append(keyline)
            box.append(row)
            rows.append((row, box, f"{label} {keys} {' '.join(parts)} {name}".lower()))
        child = Gtk.FlowBoxChild(child=box, focusable=False)
        child.set_size_request(400, -1)
        flow.append(child)
        group_boxes.append((child, box))

    empty = Gtk.Label(label="No keybinds match", css_classes=["empty"], visible=False)

    body = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
    body.append(flow)
    body.append(empty)
    scroll = Gtk.ScrolledWindow(child=body, hscrollbar_policy=Gtk.PolicyType.NEVER,
                                propagate_natural_height=True, propagate_natural_width=True)
    card.append(scroll)
    card.append(Gtk.Label(label="Type to search  ·  Esc to close", css_classes=["hint"]))

    def size_to_monitor(*_):
        surface = win.get_surface()
        display = win.get_display()
        mon = display.get_monitor_at_surface(surface) if surface else None
        if mon is None:
            mons = display.get_monitors()
            mon = mons.get_item(0) if mons.get_n_items() else None
        if mon is not None:
            geo = mon.get_geometry()
            scroll.set_max_content_height(int(geo.height * 0.72))
            card.set_size_request(min(1340, int(geo.width * 0.9)), -1)
    win.connect("realize", size_to_monitor)

    def on_search(_entry):
        q = search.get_text().strip().lower()
        shown_in = set()
        for row, box, text in rows:
            ok = all(word in text for word in q.split())
            row.set_visible(ok)
            if ok:
                shown_in.add(box)
        for child, box in group_boxes:
            child.set_visible(box in shown_in)
        empty.set_visible(not shown_in)
    search.connect("search-changed", on_search)

    def on_key(_ctl, keyval, _code, _state):
        if keyval == Gdk.KEY_Escape:
            if search.get_text():
                search.set_text("")
            else:
                app.quit()
            return True
        return False
    keys = Gtk.EventControllerKey(propagation_phase=Gtk.PropagationPhase.CAPTURE)
    keys.connect("key-pressed", on_key)
    win.add_controller(keys)

    # A click on the dimmed area (not on the card) closes the sheet
    click = Gtk.GestureClick()
    def on_click(_g, _n, x, y):
        picked = backdrop.pick(x, y, Gtk.PickFlags.DEFAULT)
        if picked is backdrop:
            app.quit()
    click.connect("pressed", on_click)
    backdrop.add_controller(click)

    provider = Gtk.CssProvider()
    provider.load_from_string(css(colors()))
    Gtk.StyleContext.add_provider_for_display(Gdk.Display.get_default(), provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
    win.present()
    search.grab_focus()


def main() -> int:
    if "--list" in sys.argv:
        groups, logo = load()
        print(f"super logo: {logo}")
        for name, binds in groups:
            print(f"\n{name}")
            for keys, label in binds:
                print(f"  {' + '.join(caps(keys)):<28} {label}")
        return 0

    import gi
    gi.require_version("Gtk", "4.0")
    gi.require_version("Gdk", "4.0")
    gi.require_version("Gtk4LayerShell", "1.0")
    from gi.repository import Gdk, Gtk, Gtk4LayerShell

    app = Gtk.Application(application_id="com.hyprdots.cheatsheet")

    def activate(a):
        # A second launch reaches the running copy through D-Bus and lands here: close instead of opening twice
        if a.get_windows():
            a.quit()
            return
        build_window(a, Gtk, Gtk4LayerShell, Gdk)
    app.connect("activate", activate)
    return app.run([sys.argv[0]])


if __name__ == "__main__":
    sys.exit(main())
