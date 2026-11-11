"""The XP style start menu: what the launcher (Super+Space, or the start button) opens while the XP style theme
override is on (settings > Theme). It is that look's own launcher, so the Launcher page's styles do not offer it.

An original recreation of the classic two-column menu, drawn with hyprdots' own CSS and your icon theme:

  - a blue header with your picture (the User page's ~/.face) and your name
  - left, on white: your browser, file manager and terminal (from settings > Hyprdots), then the apps you open
    most, then "All apps", which cascades out a flyout of categories and, beside it, the apps in one
  - right, on light blue: your folders, settings and help
  - along the bottom: a search box (just type: sums, > commands and ? web searches work as in the launcher), then
    Log out and Turn off, which open small panels of choices (lock or log out; sleep, shut down or restart)

Keys: Up and Down move, Right opens a flyout or crosses to the right-hand column, Left goes back, Enter opens,
Esc clears the search, closes a flyout or panel, then the menu. Hovering works as you would expect."""

from __future__ import annotations

import os
import pwd
import sys
from pathlib import Path

import search

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "settings"))  # hyprsettings, as launcher.py does

HOME = Path.home()
SETTINGS = "~/.config/hypr/scripts/settings.sh"
CHEATSHEET = "~/.config/hypr/cheatsheet/cheatsheet.sh"
ICON_FONT = "CaskaydiaCove Nerd Font Propo"

# What each part of the menu is drawn with: gradients that stay the same whatever the wallpaper (it is a fixed look)
HEAD = ("linear-gradient(to bottom, #1868ce 0%, #0e60cb 12%, #1164cf 32%, #1b6cd3 47%, #2476dc 60%, #3482e3 77%, "
        "#428ee9 90%, #4791eb 100%)")
FOOT = ("linear-gradient(to bottom, #4282d6 0%, #3b85e0 5%, #418ae3 10%, #3a7fdc 50%, #2e73d4 80%, #1f5fc7 100%)")


# ---- what goes in it (no GTK here, so it can be tested) ---------------------------------------------------------------
def wanted(theme_options: dict, argv: list[str]) -> bool:
    """The start menu replaces the launcher while the XP style override is on, unless a style was asked for
    (settings' Try it button passes --style)."""
    from hyprsettings import theme_override
    return theme_override.launcher_style(theme_options) == "startmenu" and "--style" not in argv


def user_name() -> str:
    """Your full name from the account (the User page sets it), else your login name."""
    try:
        entry = pwd.getpwuid(os.getuid())
        full = entry.pw_gecos.split(",")[0].strip()
        return full or entry.pw_name
    except (KeyError, OSError):
        return os.environ.get("USER", "")


def picture() -> Path | None:
    face = HOME / ".face"
    return face if face.is_file() else None


def app_for_command(command: str, apps: list) -> object | None:
    """The installed app a command from settings > Hyprdots opens (zen-browser -> Zen Browser), for its name and icon."""
    program = Path(str(command).split()[0]).name.lower() if str(command).strip() else ""
    if not program:
        return None
    for app in apps:
        exe = Path(app.extra.get("exec", "")).name
        if exe == program or app.app_id.lower().removesuffix(".desktop") == program:
            return app
    return None


# (heading, setting key, fallback command, fallback icon)
PINNED = (("Internet", "browser", "zen-browser", "web-browser"),
          ("Files", "file_manager", "thunar", "system-file-manager"),
          ("Terminal", "terminal", "ghostty", "utilities-terminal"))


def pinned(commands: dict, apps: list) -> list[dict]:
    """The three apps along the top of the left column: heading, the app's name under it, its icon and what runs it."""
    out = []
    for heading, key, fallback, icon in PINNED:
        command = str(commands.get(key) or fallback)
        app = app_for_command(command, apps)
        out.append({"title": heading, "subtitle": app.title if app else command.split()[0], "app": app,
                    "icon": icon, "cmd": command.split()})
    return out


def special_dir(name: str, fallback: str) -> Path:
    """An XDG user folder (Documents, Pictures...), from user-dirs.dirs, else ~/fallback."""
    try:
        text = (HOME / ".config/user-dirs.dirs").read_text(encoding="utf-8")
    except OSError:
        text = ""
    for line in text.splitlines():
        if line.startswith(f"XDG_{name}_DIR="):
            value = line.split("=", 1)[1].strip().strip('"').replace("$HOME", str(HOME))
            return Path(value)
    return HOME / fallback


def places() -> list[dict | None]:
    """The right-hand column, top to bottom. None draws a separator. kind 'open' opens a folder, 'run' runs cmd,
    'search' and 'run_prompt' act inside the menu."""
    folder = lambda title, xdg, fallback, icon: {  # noqa: E731
        "title": title, "icon": icon, "kind": "open", "path": special_dir(xdg, fallback)}
    return [
        folder("Documents", "DOCUMENTS", "Documents", "folder-documents"),
        folder("Pictures", "PICTURES", "Pictures", "folder-pictures"),
        folder("Music", "MUSIC", "Music", "folder-music"),
        folder("Downloads", "DOWNLOAD", "Downloads", "folder-download"),
        {"title": "Home", "icon": "user-home", "kind": "open", "path": HOME},
        None,
        {"title": "Settings", "icon": "preferences-system", "kind": "run", "cmd": [SETTINGS]},
        {"title": "Displays", "icon": "preferences-desktop-display", "kind": "run", "cmd": [SETTINGS, "--page=Displays"]},
        {"title": "Default apps", "icon": "applications-system", "kind": "run",
         "cmd": [SETTINGS, "--page=Hyprdots"]},
        None,
        {"title": "Keyboard shortcuts", "icon": "help-browser", "kind": "run", "cmd": [CHEATSHEET]},
        {"title": "Search", "icon": "system-search", "kind": "search"},
        {"title": "Run…", "icon": "system-run", "kind": "run_prompt"},
    ]


def power(word: str) -> list[str]:
    return next(cmd for w, _label, cmd, _confirm in search.POWER if w == word)


# The two panels of choices: (title, [(label, word, colour class, glyph)])
LOG_OUT = ("Log out", [("Lock", "lock", "amber", search.POWER_ICONS["lock"]),
                       ("Log out", "log out", "amber", search.POWER_ICONS["log out"])])
TURN_OFF = ("Turn off the computer", [("Sleep", "sleep", "amber", search.POWER_ICONS["sleep"]),
                                      ("Shut down", "shut down", "red", search.POWER_ICONS["shut down"]),
                                      ("Restart", "reboot", "green", search.POWER_ICONS["reboot"])])


def categories(apps: list) -> list[str]:
    present = {a.category for a in apps}
    return [n for n, _ in search.BUCKETS if n in present] + (["Other"] if "Other" in present else [])


def frequent(apps: list, usage: dict, pinned_ids: set[str], limit: int = 6) -> list:
    return [a for a in search.frequent(apps, usage, limit + len(pinned_ids)) if a.app_id not in pinned_ids][:limit]


OPEN_MARK = Path(os.environ.get("XDG_RUNTIME_DIR", "/tmp")) / "hyprdots-startmenu-open"
BAR_SIGNAL = 12  # theme_override.START_SIGNAL: the bar's start button re-reads its state (start-state.sh)


def mark_open(is_open: bool) -> None:
    """Tells the bar's start button to look pressed in (open) or not."""
    try:
        if is_open:
            OPEN_MARK.touch()
        else:
            OPEN_MARK.unlink(missing_ok=True)
    except OSError:
        pass
    import subprocess
    try:
        subprocess.Popen(["pkill", f"-RTMIN+{BAR_SIGNAL}", "-x", "waybar"], stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL)
    except OSError:
        pass


def step(row: int, count: int, delta: int) -> int:
    """Up and Down wrap round, as the menu's did."""
    return (row + delta) % count if count else 0


def css(font_list: str, scale: float) -> str:
    px = lambda n: f"{max(1, round(n * scale))}px"  # noqa: E731
    return f"""
window, window.background {{ background: transparent; }}
* {{ font-family: {font_list}; font-size: {px(13)}; color: #000000; text-shadow: none; }}
.startmenu {{
    background: #ffffff;
    border: 1px solid #0d4ec4;
    border-bottom: none;
    border-radius: {px(8)} {px(8)} 0px 0px;
    box-shadow: 3px 0px 10px rgba(0, 0, 0, 0.45);
}}
.sm-head {{
    background-image: {HEAD};
    border-radius: {px(7)} {px(7)} 0px 0px;
    padding: {px(7)} {px(9)};
    min-height: {px(56)};
}}
.sm-face {{
    border: 2px solid #e3ecfb;
    border-radius: {px(4)};
    background: #ffffff;
    box-shadow: 1px 1px 3px rgba(0, 0, 0, 0.45);
}}
.sm-name {{ color: #ffffff; font-weight: bold; font-size: {px(17)}; text-shadow: 1px 1px 1px #0a246a; margin-left: {px(10)}; }}
.sm-rule {{ min-height: 2px; background-image: linear-gradient(90deg, transparent, #f8a33c 15%, #f8a33c 85%, transparent); }}
.sm-left {{ background: #ffffff; padding: {px(6)} {px(3)}; }}
.sm-right {{ background: #d3e5fa; border-left: 1px solid #95bdee; padding: {px(6)} {px(3)}; }}
.sm-item {{ padding: {px(4)} {px(7)}; border-radius: 0px; }}
.sm-item.selected, .sm-item.open {{ background: #316ac5; }}
.sm-item.selected label, .sm-item.open label {{ color: #ffffff; }}
.sm-pinned .title {{ font-weight: bold; }}
.sm-sub {{ color: #6d6d6d; font-size: {px(11)}; }}
.sm-right .title {{ color: #00136b; font-weight: bold; }}
.sm-sep {{ min-height: 1px; margin: {px(5)} {px(8)}; background-image: linear-gradient(90deg, transparent, #c5c2b2 15%, #c5c2b2 85%, transparent); }}
.sm-right .sm-sep {{ background-image: linear-gradient(90deg, transparent, #95bdee 15%, #95bdee 85%, transparent); }}
.sm-all {{ font-weight: bold; }}
.sm-arrow {{
    background-image: linear-gradient(to bottom, #5dc55d, #2f8f2f);
    border-radius: {px(3)}; padding: 0px {px(4)}; margin-left: {px(8)};
    font-family: "{ICON_FONT}"; font-size: {px(12)};
}}
.sm-arrow, .sm-item.selected .sm-arrow {{ color: #ffffff; }}
.sm-foot {{ background-image: {FOOT}; padding: {px(6)} {px(8)}; }}
.sm-foot label {{ color: #ffffff; }}
.sm-search {{ background: #ffffff; color: #000000; border: 1px solid #0d3a9c; border-radius: 0px;
    min-height: {px(22)}; box-shadow: none; outline: none; }}
.sm-search text {{ background: none; color: #000000; border: none; box-shadow: none; }}
.sm-search image {{ color: #316ac5; }}
.sm-power {{ all: unset; padding: {px(3)} {px(7)}; border-radius: {px(3)}; }}
.sm-power:hover, .sm-power.selected {{ background: rgba(255, 255, 255, 0.18); }}
.sm-key {{
    font-family: "{ICON_FONT}"; font-size: {px(15)}; color: #ffffff; min-width: {px(22)}; min-height: {px(22)};
    border: 1px solid rgba(255, 255, 255, 0.85); border-radius: {px(3)}; margin-right: {px(5)};
}}
.amber {{ background-image: linear-gradient(to bottom, #fbd27a, #e8a33a 55%, #d0841c); }}
.red {{ background-image: linear-gradient(to bottom, #f49a80, #e0532c 55%, #c4391a); }}
.green {{ background-image: linear-gradient(to bottom, #8fdc7a, #45a934 55%, #2f8a22); }}
.sm-flyout {{
    background: #ffffff;
    border: 1px solid #7f9db9;
    padding: {px(2)};
    box-shadow: 2px 2px 6px rgba(0, 0, 0, 0.4);
    margin-left: {px(-2)};
}}
.sm-flyout .sm-item {{ padding: {px(3)} {px(8)}; }}
.sm-more {{ font-family: "{ICON_FONT}"; color: #000000; margin-left: {px(14)}; }}
.sm-item.selected .sm-more, .sm-item.open .sm-more {{ color: #ffffff; }}
.sm-panel {{ background: #d3e5fa; padding: {px(18)} {px(16)}; }}
.sm-panel-title {{ font-size: {px(15)}; font-weight: bold; color: #00136b; margin-bottom: {px(14)}; }}
.sm-choice {{ all: unset; padding: {px(8)}; border-radius: {px(4)}; }}
.sm-choice:hover, .sm-choice.selected {{ background: rgba(49, 106, 197, 0.18); box-shadow: inset 0 0 0 1px #316ac5; }}
.sm-choice .sm-key {{ font-size: {px(26)}; min-width: {px(44)}; min-height: {px(44)}; margin: 0px 0px {px(6)} 0px; }}
.sm-cancel {{ background-image: linear-gradient(to bottom, #ffffff, #ecebe6 85%, #d6d0c5); border: 1px solid #003c74;
    border-radius: {px(3)}; padding: {px(3)} {px(16)}; color: #000000; box-shadow: none; }}
.sm-cancel:hover {{ box-shadow: inset 0 0 0 2px #f8b330; }}
.glyph {{ font-family: "{ICON_FONT}"; color: #316ac5; }}
.sm-item.selected .glyph {{ color: #ffffff; }}
.sm-empty {{ color: #6d6d6d; margin: {px(16)}; }}

/* ---- motion: the menu rises from the start button, flyouts slide out, closing fades it down ---- */
@keyframes sm-open {{ from {{ transform: translateY({px(36)}); opacity: 0; }} to {{ transform: none; opacity: 1; }} }}
@keyframes sm-fly {{ from {{ transform: translateX({px(-12)}); opacity: 0; }} to {{ transform: none; opacity: 1; }} }}
@keyframes sm-panel-in {{ from {{ transform: scale(0.96); opacity: 0; }} to {{ transform: none; opacity: 1; }} }}
.startmenu {{ animation: sm-open 190ms cubic-bezier(0.2, 0.9, 0.3, 1); }}
.startmenu.closing {{ transition: transform 120ms ease-in, opacity 120ms ease-in; transform: translateY({px(18)}); opacity: 0; }}
.sm-flyout {{ animation: sm-fly 150ms cubic-bezier(0.2, 0.9, 0.3, 1); }}
.closing .sm-flyout, .sm-flyout.closing {{ transition: opacity 100ms ease-in; opacity: 0; }}
.sm-panel .sm-choice {{ animation: sm-panel-in 180ms cubic-bezier(0.2, 0.9, 0.3, 1); }}

/* ---- hover: a soft, lit highlight that glides in, icons lift, the All apps arrow leans forward ---- */
.sm-item {{ border-radius: {px(3)}; transition: background-color 110ms ease-out, box-shadow 110ms ease-out; }}
.sm-item.selected, .sm-item.open {{
    background-color: #316ac5;
    background-image: linear-gradient(to bottom, #4a87e0 0%, #3a74d0 45%, #2c62bf 100%);
    box-shadow: inset 0px 1px rgba(255, 255, 255, 0.28), 0px 1px 2px rgba(10, 36, 106, 0.35);
}}
.sm-item image {{ transition: -gtk-icon-transform 150ms cubic-bezier(0.2, 0.9, 0.3, 1.3); }}
.sm-item.selected image {{ -gtk-icon-transform: scale(1.12); }}
.sm-item.selected .sm-sub {{ color: rgba(255, 255, 255, 0.85); }}
.sm-arrow {{ transition: margin-left 160ms cubic-bezier(0.2, 0.9, 0.3, 1.4); }}
.sm-item.selected .sm-arrow {{ margin-left: {px(14)}; background-image: linear-gradient(to bottom, #78dd78, #36a336); }}
.sm-more {{ transition: margin-left 140ms ease-out; }}
.sm-item.selected .sm-more {{ margin-left: {px(18)}; }}
.sm-power {{ transition: background-color 120ms ease-out; }}
.sm-power .sm-key {{ transition: box-shadow 150ms ease-out; }}
.sm-power:hover .sm-key {{ box-shadow: 0px 0px 8px rgba(255, 255, 255, 0.75); }}
.sm-choice {{ transition: background-color 120ms ease-out, box-shadow 120ms ease-out; }}
.sm-choice .sm-key {{ transition: -gtk-icon-transform 150ms ease-out, box-shadow 150ms ease-out; }}
.sm-choice:hover .sm-key, .sm-choice.selected .sm-key {{ box-shadow: 0px 0px 10px rgba(49, 106, 197, 0.55); }}
.sm-face {{ transition: box-shadow 200ms ease-out; }}
.sm-head:hover .sm-face {{ box-shadow: 0px 0px 6px rgba(255, 255, 255, 0.8); }}
"""


# ---- the window ----------------------------------------------------------------------------------------------------
def build(app, Gtk, Gdk, GLib, Pango, Gtk4LayerShell, opts: dict, run, icon_for, theme_options: dict, font_list: str):
    """Builds and shows the menu. run(result, opts) and icon_for(Gtk, result, size) are the launcher's own."""
    scale = int(opts.get("size", 100)) / 100
    px = lambda n: max(1, round(n * scale))  # noqa: E731
    apps = search.installed_apps()
    usage = search.load_usage() if opts.get("rank", True) else {}
    from hyprsettings.schema import BY_ID
    from hyprsettings.store import Store
    store = Store()
    commands = {key: store.get(BY_ID[f"hyprdots.{key}"])[0] for _h, key, _f, _i in PINNED}
    top = pinned(commands, apps)

    win = Gtk.ApplicationWindow(application=app)
    if Gtk4LayerShell.is_supported():
        Gtk4LayerShell.init_for_window(win)
        Gtk4LayerShell.set_namespace(win, "launcher")
        Gtk4LayerShell.set_layer(win, Gtk4LayerShell.Layer.OVERLAY)
        Gtk4LayerShell.set_keyboard_mode(win, Gtk4LayerShell.KeyboardMode.EXCLUSIVE)
        # no exclusive zone of its own, but it keeps out of the bar's: the menu sits on top of the taskbar
        for edge in (Gtk4LayerShell.Edge.TOP, Gtk4LayerShell.Edge.BOTTOM, Gtk4LayerShell.Edge.LEFT, Gtk4LayerShell.Edge.RIGHT):
            Gtk4LayerShell.set_anchor(win, edge, True)
    else:
        win.set_default_size(1000, 700)

    # The menu and its flyouts float over a see-through layer the size of the screen (less the taskbar): the
    # flyouts open beside the left column, over the right one, as the menu's always did
    backdrop = Gtk.Box(hexpand=True, vexpand=True)
    overlay = Gtk.Overlay(child=backdrop)
    win.set_child(overlay)
    menu = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, css_classes=["startmenu"], width_request=px(470),
                   halign=Gtk.Align.START, valign=Gtk.Align.END)
    overlay.add_overlay(menu)
    flyouts = Gtk.Box(halign=Gtk.Align.START, valign=Gtk.Align.END)
    overlay.add_overlay(flyouts)

    head = Gtk.Box(css_classes=["sm-head"])
    face = picture()
    if face:
        pic = Gtk.Picture.new_for_filename(str(face))
        pic.set_content_fit(Gtk.ContentFit.COVER)
        pic.set_size_request(px(46), px(46))
        pic.set_can_shrink(True)
        frame = Gtk.Frame(child=pic, css_classes=["sm-face"], valign=Gtk.Align.CENTER)
    else:
        image = Gtk.Image(icon_name="avatar-default", pixel_size=px(46))
        frame = Gtk.Frame(child=image, css_classes=["sm-face"], valign=Gtk.Align.CENTER)
    head.append(frame)
    head.append(Gtk.Label(label=user_name(), css_classes=["sm-name"], valign=Gtk.Align.CENTER))
    menu.append(head)
    menu.append(Gtk.Box(css_classes=["sm-rule"]))

    body = Gtk.Stack(transition_type=Gtk.StackTransitionType.CROSSFADE, transition_duration=90, vhomogeneous=False)
    menu.append(body)
    columns = Gtk.Box(height_request=px(470))
    body.add_named(columns, "menu")
    left = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, css_classes=["sm-left"], hexpand=True, width_request=px(250))
    right = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, css_classes=["sm-right"], width_request=px(210))
    columns.append(left)
    columns.append(right)
    panel_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, css_classes=["sm-panel"], height_request=px(470))
    body.add_named(panel_box, "panel")

    foot = Gtk.Box(spacing=px(6), css_classes=["sm-foot"])
    entry = Gtk.SearchEntry(css_classes=["sm-search"], hexpand=True, placeholder_text="Search apps, 12*7, > command")
    foot.append(entry)
    menu.append(foot)

    # Every item you can move to: one list per area. focus = [area, row].
    areas = {"left": [], "right": [], "fly0": [], "fly1": [], "panel": []}
    state = {"focus": ["left", 0], "results": None, "panel": None, "query": ""}

    def quit_menu():
        """Fades the menu down towards the start button, then closes."""
        if menu.has_css_class("closing"):
            return
        menu.add_css_class("closing")
        flyouts.add_css_class("closing")
        mark_open(False)  # the start button pops back up as the menu fades
        GLib.timeout_add(120, lambda: app.quit() or False)

    def spawn(cmd):
        run(search.Result("power", "", extra={"cmd": cmd}), opts)

    def item_box(icon, title, subtitle="", size=32, more=False, classes=()):
        box = Gtk.Box(spacing=px(8), css_classes=["sm-item", *classes])
        if isinstance(icon, str):
            image = Gtk.Image(icon_name=icon, pixel_size=px(size))
        else:
            image = icon
        box.append(image)
        text = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, valign=Gtk.Align.CENTER, hexpand=True)
        text.append(Gtk.Label(label=title, xalign=0, css_classes=["title"], ellipsize=Pango.EllipsizeMode.END))
        if subtitle:
            text.append(Gtk.Label(label=subtitle, xalign=0, css_classes=["sm-sub"], ellipsize=Pango.EllipsizeMode.END))
        box.append(text)
        if more:
            box.append(Gtk.Label(label="\U000f0142", css_classes=["sm-more"]))
        return box

    def add(area, parent, widget, action, hover=None):
        """Makes widget a menu item: it lights up on hover (hover() also runs then), and opens on click or Enter."""
        index = len(areas[area])
        areas[area].append({"widget": widget, "action": action, "hover": hover})
        click = Gtk.GestureClick()
        click.connect("released", lambda *_a: action())
        widget.add_controller(click)
        motion = Gtk.EventControllerMotion()
        motion.connect("enter", lambda *_a: focus(area, index, from_pointer=True))
        widget.add_controller(motion)
        parent.append(widget)

    def separator(parent):
        parent.append(Gtk.Box(css_classes=["sm-sep"]))

    def clear(box):
        child = box.get_first_child()
        while child:
            box.remove(child)
            child = box.get_first_child()

    def focus(area, index, from_pointer=False):
        items = areas[area]
        if not items:
            return
        index = max(0, min(index, len(items) - 1))
        old_area, old_index = state["focus"]
        if old_area in areas and old_index < len(areas[old_area]):
            areas[old_area][old_index]["widget"].remove_css_class("selected")
        state["focus"] = [area, index]
        items[index]["widget"].add_css_class("selected")
        if items[index]["hover"]:
            items[index]["hover"]()
        if not from_pointer:
            GLib.idle_add(scroll_to, items[index]["widget"])

    def scroll_to(widget):
        """Keeps the item you moved to in view in a long flyout or list of results."""
        parent = widget.get_parent()
        while parent is not None and not isinstance(parent, Gtk.ScrolledWindow):
            parent = parent.get_parent()
        if parent is None:
            return False
        ok, rect = widget.compute_bounds(parent.get_child())
        if ok:
            adj = parent.get_vadjustment()
            y = rect.origin.y
            if y < adj.get_value():
                adj.set_value(y)
            elif y + rect.size.height > adj.get_value() + adj.get_page_size():
                adj.set_value(y + rect.size.height - adj.get_page_size())
        return False

    # ---- left column -----------------------------------------------------------------------------------------------
    def run_app(result):
        run(result, opts)
        quit_menu()

    def draw_left():
        clear(left)
        areas["left"].clear()
        close_flyouts()
        if state["results"] is not None:
            draw_results()
            return
        for p in top:
            icon = icon_for(Gtk, p["app"], px(32)) if p["app"] else p["icon"]
            act = (lambda a=p["app"]: run_app(a)) if p["app"] else (lambda c=p["cmd"]: (spawn(c), quit_menu()))
            add("left", left, item_box(icon, p["title"], p["subtitle"], classes=["sm-pinned"]), act, close_flyouts)
        separator(left)
        pinned_ids = {p["app"].app_id for p in top if p["app"]}
        for a in frequent(apps, usage, pinned_ids):
            add("left", left, item_box(icon_for(Gtk, a, px(32)), a.title), lambda a=a: run_app(a), close_flyouts)
        left.append(Gtk.Box(vexpand=True))
        separator(left)
        all_box = Gtk.Box(spacing=px(4), css_classes=["sm-item"], halign=Gtk.Align.CENTER)
        all_box.append(Gtk.Label(label="All apps", css_classes=["sm-all"]))
        all_box.append(Gtk.Label(label="\U000f0142", css_classes=["sm-arrow"]))
        add("left", left, all_box, lambda: open_categories(enter=True), open_categories)

    def draw_results():
        scroller = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER, vexpand=True)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        scroller.set_child(box)
        left.append(scroller)
        if not state["results"]:
            box.append(Gtk.Label(label="Nothing matches", css_classes=["sm-empty"]))
        for r in state["results"][:60]:
            add("left", box, item_box(icon_for(Gtk, r, px(24)), r.title, r.subtitle, size=24),
                lambda r=r: pick_result(r))

    def pick_result(r):
        if r.kind == "power" and r.confirm:
            show_panel(LOG_OUT if r.value == "log out" else TURN_OFF)
            return
        run(r, opts)
        quit_menu()

    # ---- flyouts (All apps) ------------------------------------------------------------------------------------------
    def close_flyouts():
        clear(flyouts)
        areas["fly0"].clear()
        areas["fly1"].clear()

    def flyout(area, names_and_actions):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, css_classes=["sm-flyout"], valign=Gtk.Align.END)
        scroller = Gtk.ScrolledWindow(child=box, hscrollbar_policy=Gtk.PolicyType.NEVER, propagate_natural_height=True,
                                      propagate_natural_width=True, max_content_height=px(900), valign=Gtk.Align.END)
        flyouts.append(scroller)
        for widget, action, hover in names_and_actions:
            add(area, box, widget, action, hover)
        return scroller

    def open_categories(enter=False):
        if not areas["fly0"]:
            close_flyouts()
            # beside the left column, its foot level with the bottom of "All apps"
            flyouts.set_margin_start(max(0, left.get_width() - px(2)))
            flyouts.set_margin_bottom(foot.get_height() + px(6))
            flyout("fly0", [(item_box("folder", name, size=20, more=True), lambda n=name: open_apps(n, enter=True),
                             lambda n=name: open_apps(n)) for name in categories(apps)])
        if enter:
            focus("fly0", 0)

    def open_apps(category, enter=False):
        # a second flyout beside the first, for the hovered category
        while flyouts.get_last_child() is not None and flyouts.get_first_child() is not flyouts.get_last_child():
            flyouts.remove(flyouts.get_last_child())
        areas["fly1"].clear()
        for item in areas["fly0"]:  # the category stays lit while you are in its apps
            (item["widget"].add_css_class if _title(item["widget"]) == category else item["widget"].remove_css_class)("open")
        in_it = [a for a in apps if a.category == category]
        second = flyout("fly1", [(item_box(icon_for(Gtk, a, px(20)), a.title, size=20), lambda a=a: run_app(a), None)
                                 for a in in_it])
        flyouts.add_tick_callback(lambda *_a: line_up(category, second))  # once the first flyout has its size
        if enter:
            focus("fly1", 0)

    def line_up(category, second):
        """The apps flyout opens with its top level with the category you are on (as far as the screen allows)."""
        first = flyouts.get_first_child()
        hovered = next((i["widget"] for i in areas["fly0"] if _title(i["widget"]) == category), None)
        if not (first and hovered) or second.get_parent() is not flyouts:  # gone: another category was opened since
            return GLib.SOURCE_REMOVE
        if not first.get_height():
            return GLib.SOURCE_CONTINUE  # not laid out yet: try again next frame
        ok, rect = hovered.compute_bounds(first)
        if ok:
            height = second.measure(Gtk.Orientation.VERTICAL, -1)[1]
            second.set_margin_bottom(max(0, round(first.get_height() - rect.origin.y - height)))
        return GLib.SOURCE_REMOVE

    def _title(widget):
        box = widget.get_first_child().get_next_sibling() if widget.get_first_child() else None
        label = box.get_first_child() if box else None
        return label.get_label() if isinstance(label, Gtk.Label) else ""

    # ---- right column ------------------------------------------------------------------------------------------------
    def place_action(p):
        if p["kind"] == "open":
            return lambda: (spawn(["xdg-open", str(p["path"])]), quit_menu())
        if p["kind"] == "run":
            return lambda: (spawn(p["cmd"]), quit_menu())
        if p["kind"] == "search":
            return lambda: entry.grab_focus()
        return lambda: (entry.set_text("> "), entry.set_position(-1), entry.grab_focus())

    for p in places():
        if p is None:
            separator(right)
        else:
            add("right", right, item_box(p["icon"], p["title"], size=24), place_action(p), close_flyouts)

    # ---- the panels of choices (Log out, Turn off) -------------------------------------------------------------------
    def show_panel(which):
        title, choices = which
        clear(panel_box)
        areas["panel"].clear()
        close_flyouts()
        panel_box.append(Gtk.Label(label=title, css_classes=["sm-panel-title"], xalign=0))
        buttons = Gtk.Box(spacing=px(10), halign=Gtk.Align.CENTER, vexpand=True, valign=Gtk.Align.CENTER, homogeneous=True)
        panel_box.append(buttons)
        for label, word, colour, glyph in choices:
            choice = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, css_classes=["sm-choice"])
            key = Gtk.Label(label=glyph, css_classes=["sm-key", colour], halign=Gtk.Align.CENTER)
            choice.append(key)
            choice.append(Gtk.Label(label=label))
            add("panel", buttons, choice, lambda w=word: (spawn(power(w)), quit_menu()))
        cancel = Gtk.Button(label="Cancel", css_classes=["sm-cancel"], halign=Gtk.Align.END)
        cancel.connect("clicked", lambda _b: hide_panel())
        panel_box.append(cancel)
        state["panel"] = which
        body.set_visible_child_name("panel")
        focus("panel", 0)

    def hide_panel():
        state["panel"] = None
        body.set_visible_child_name("menu")
        focus("left", 0)

    end = Gtk.Box(spacing=px(2))
    for label, colour, glyph, which in (("Log out", "amber", search.POWER_ICONS["log out"], LOG_OUT),
                                        ("Turn off", "red", search.POWER_ICONS["shut down"], TURN_OFF)):
        button = Gtk.Button(css_classes=["sm-power"], focusable=False)
        inner = Gtk.Box()
        inner.append(Gtk.Label(label=glyph, css_classes=["sm-key", colour]))
        inner.append(Gtk.Label(label=label))
        button.set_child(inner)
        button.connect("clicked", lambda _b, w=which: show_panel(w))
        end.append(button)
    foot.append(end)

    # ---- keys --------------------------------------------------------------------------------------------------------
    def activate():
        area, index = state["focus"]
        if areas[area] and index < len(areas[area]):
            areas[area][index]["action"]()

    def on_key(_ctl, keyval, _code, mods):
        area, index = state["focus"]
        if keyval == Gdk.KEY_Escape:
            if state["panel"]:
                hide_panel()
            elif area in ("fly0", "fly1"):
                close_flyouts()
                focus("left", len(areas["left"]) - 1)
            elif entry.get_text():
                entry.set_text("")
            else:
                quit_menu()
            return True
        if keyval in (Gdk.KEY_Return, Gdk.KEY_KP_Enter):
            if entry.get_text() != state["query"]:  # typing is debounced: act on what is in the box now
                refresh()
            activate()
            return True
        if keyval in (Gdk.KEY_Up, Gdk.KEY_Down):
            focus(area, step(index, len(areas[area]), -1 if keyval == Gdk.KEY_Up else 1))
            return True
        if keyval == Gdk.KEY_Right and not (entry.get_text() and area == "left"):
            if area == "left" and areas[area] and index == len(areas["left"]) - 1 and state["results"] is None:
                open_categories(enter=True)
            elif area == "left":
                focus("right", 0)
            elif area == "fly0":
                areas["fly0"][index]["action"]()
            elif area == "panel":
                focus("panel", index + 1)
            return True
        if keyval == Gdk.KEY_Left and not (entry.get_text() and area == "left"):
            if area == "right":
                focus("left", 0)
            elif area == "fly1":
                focus("fly0", 0)
                areas["fly1"].clear()
            elif area == "fly0":
                close_flyouts()
                focus("left", len(areas["left"]) - 1)
            elif area == "panel":
                focus("panel", index - 1)
            return True
        return False

    keys = Gtk.EventControllerKey(propagation_phase=Gtk.PropagationPhase.CAPTURE)
    keys.connect("key-pressed", on_key)
    win.add_controller(keys)

    def refresh(*_):
        text = entry.get_text()
        state["query"] = text
        state["results"] = search.search(text, apps, usage, opts.get("engine", "duckduckgo"), opts.get("rank", True)) \
            if text.strip() else None
        if state["panel"]:
            hide_panel()
        draw_left()
        focus("left", 0)
    entry.connect("search-changed", refresh)

    click = Gtk.GestureClick()  # a click outside the menu closes it
    click.connect("pressed", lambda _g, _n, x, y: backdrop.pick(x, y, Gtk.PickFlags.DEFAULT) is backdrop and quit_menu())
    backdrop.add_controller(click)

    provider = Gtk.CssProvider()
    provider.load_from_string(css(font_list, scale))
    Gtk.StyleContext.add_provider_for_display(Gdk.Display.get_default(), provider, Gtk.STYLE_PROVIDER_PRIORITY_USER + 1)
    draw_left()
    win.present()
    mark_open(True)
    app.connect("shutdown", lambda *_a: mark_open(False))  # however it closes, the start button comes back up
    entry.grab_focus()
    focus("left", 0, from_pointer=True)
    return win
