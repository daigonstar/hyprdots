"""The menu under the logo at the left of Mac style's menu bar (launcher.sh --logo-menu). An original take on the
system menu a Mac keeps there, drawn with hyprdots' own CSS:

  About this PC          a card with this PC's name, system, processor, memory and uptime
  Settings…              hypr-settings
  App store…             the store from settings > Hyprdots
  Recent items        >  the apps you open most
  Force quit…         >  your open windows; pick one twice to end it straight away
  Sleep / Restart… / Shut down…
  Lock screen / Log out <name>…

Restart, Shut down, Log out and Force quit ask first: the item says "Click again to…". Keys: Up and Down move,
Right opens a submenu, Left closes it, Enter picks, Esc closes. Running it again while it is open closes it."""

from __future__ import annotations

import json
import os
import platform
import socket
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "settings"))
import search  # noqa: E402
import startmenu  # noqa: E402

SETTINGS = "~/.config/hypr/scripts/settings.sh"
ICON_FONT = "CaskaydiaCove Nerd Font Propo"


# ---- what is in it (no GTK, so it can be tested) ---------------------------------------------------------------------
def os_name(text: str | None = None) -> str:
    """PRETTY_NAME from /etc/os-release (Arch Linux), else the kernel's name."""
    if text is None:
        try:
            text = Path("/etc/os-release").read_text(encoding="utf-8")
        except OSError:
            text = ""
    for line in text.splitlines():
        if line.startswith("PRETTY_NAME="):
            return line.split("=", 1)[1].strip().strip('"')
    return platform.system()


def cpu_name(text: str | None = None) -> str:
    if text is None:
        try:
            text = Path("/proc/cpuinfo").read_text(encoding="utf-8", errors="replace")
        except OSError:
            text = ""
    for line in text.splitlines():
        if line.lower().startswith("model name"):
            return " ".join(line.split(":", 1)[1].split())
    return platform.processor() or "Unknown"


def memory(text: str | None = None) -> str:
    """Installed memory, rounded the way it is sold (31.2 GiB usable -> 32 GB)."""
    if text is None:
        try:
            text = Path("/proc/meminfo").read_text(encoding="utf-8")
        except OSError:
            return "Unknown"
    for line in text.splitlines():
        if line.startswith("MemTotal:"):
            gib = int(line.split()[1]) / 1024 / 1024
            sizes = [2, 4, 6, 8, 12, 16, 24, 32, 48, 64, 96, 128, 192, 256, 384, 512]
            return f"{next((s for s in sizes if s >= gib * 0.97), round(gib))} GB"
    return "Unknown"


def uptime(seconds: float | None = None) -> str:
    if seconds is None:
        try:
            seconds = float(Path("/proc/uptime").read_text().split()[0])
        except (OSError, ValueError, IndexError):
            return ""
    minutes = int(seconds // 60)
    days, minutes = divmod(minutes, 1440)
    hours, minutes = divmod(minutes, 60)
    parts = [f"{days} day{'s' if days != 1 else ''}"] if days else []
    parts += [f"{hours} hour{'s' if hours != 1 else ''}"] if hours else []
    parts += [] if days else [f"{minutes} minute{'s' if minutes != 1 else ''}"]
    return ", ".join(parts)


def about() -> list[tuple[str, str]]:
    return [("System", os_name()), ("Kernel", platform.release()), ("Processor", cpu_name()),
            ("Memory", memory()), ("Up for", uptime())]


def shortcut(keys: str) -> str:
    """A keybind as the menu shows it: SUPER + L -> Super+L."""
    return "+".join(part.strip().capitalize() if len(part.strip()) > 1 else part.strip().upper()
                    for part in str(keys).split("+") if part.strip())


def windows(clients: list | None = None) -> list[dict]:
    """Open windows to force quit: title, app and pid, one per app process, most recently used first."""
    if clients is None:
        try:
            clients = json.loads(subprocess.run(["hyprctl", "clients", "-j"], capture_output=True, text=True,
                                                timeout=5).stdout or "[]")
        except (OSError, subprocess.SubprocessError, ValueError):
            clients = []
    seen, out = set(), []
    for c in sorted(clients, key=lambda c: c.get("focusHistoryID", 99)):
        pid = c.get("pid")
        if not isinstance(pid, int) or pid <= 1 or pid in seen or not c.get("mapped", True):
            continue
        seen.add(pid)
        out.append({"app": c.get("class") or c.get("initialClass") or "?", "title": c.get("title") or "", "pid": pid})
    return out


def items(name: str, keys: dict[str, str], store_cmd: str) -> list[dict | None]:
    """The menu, top to bottom. None is a line between groups. kind: about | run | recent | force | power."""
    power = lambda word: next(cmd for w, _l, cmd, _c in search.POWER if w == word)  # noqa: E731
    return [
        {"title": "About this PC", "kind": "about"},
        None,
        {"title": "Settings…", "kind": "run", "cmd": [SETTINGS]},
        {"title": "App store…", "kind": "run", "cmd": store_cmd.split(), "keys": keys.get("store", "")},
        None,
        {"title": "Recent items", "kind": "recent"},
        None,
        {"title": "Force quit…", "kind": "force"},
        None,
        {"title": "Sleep", "kind": "power", "cmd": power("sleep")},
        {"title": "Restart…", "kind": "power", "cmd": power("reboot"), "confirm": "restart"},
        {"title": "Shut down…", "kind": "power", "cmd": power("shut down"), "confirm": "shut down"},
        None,
        {"title": "Lock screen", "kind": "power", "cmd": power("lock"), "keys": keys.get("lock", "")},
        {"title": f"Log out {name}…", "kind": "power", "cmd": power("log out"), "confirm": "log out"},
    ]


def css(font_list: str) -> str:
    return f"""
window, window.background {{ background: transparent; }}
* {{ font-family: {font_list}; font-size: 13px; color: #1d1d1f; text-shadow: none; }}
.menu {{
    background: rgba(246, 246, 246, 0.97);  /* nearly solid: Hyprland's blur behind layers is not reliable */
    border: 1px solid rgba(0, 0, 0, 0.12);
    border-radius: 10px;
    padding: 5px;
    box-shadow: 0px 10px 30px rgba(0, 0, 0, 0.25);
}}
@keyframes drop {{ from {{ transform: translateY(-6px); opacity: 0; }} to {{ transform: none; opacity: 1; }} }}
.menu {{ animation: drop 140ms cubic-bezier(0.2, 0.9, 0.3, 1); }}
.menu.closing {{ transition: opacity 90ms ease-in; opacity: 0; }}
.entry {{ padding: 3px 10px; border-radius: 5px; min-height: 20px; transition: background-color 80ms ease-out; }}
.entry.selected, .entry.open {{ background: #007aff; }}
.entry.selected label, .entry.open label {{ color: #ffffff; }}
.keys, .more {{ color: rgba(29, 29, 31, 0.5); margin-left: 24px; }}
.more {{ font-family: "{ICON_FONT}"; }}
.line {{ min-height: 1px; background: rgba(0, 0, 0, 0.1); margin: 5px 10px; }}
.ask label {{ font-weight: bold; }}
.empty {{ color: rgba(29, 29, 31, 0.5); padding: 3px 10px; }}
.about {{ padding: 22px 26px 18px 26px; }}
.about-logo {{ font-family: "{ICON_FONT}"; font-size: 64px; color: #1d1d1f; margin-bottom: 8px; }}
.about-name {{ font-size: 20px; font-weight: bold; }}
.about-key {{ color: rgba(29, 29, 31, 0.6); }}
.about-button {{ all: unset; background: rgba(0, 0, 0, 0.06); border-radius: 6px; padding: 3px 14px; margin-top: 12px; }}
.about-button:hover {{ background: #007aff; color: #ffffff; }}
"""


# ---- the window --------------------------------------------------------------------------------------------------------
def build(app, Gtk, Gdk, GLib, Pango, Gtk4LayerShell, logo: str, font_list: str, run_cmd):
    from hyprsettings.schema import BY_ID
    from hyprsettings.store import Store
    store = Store()
    keys = {}
    for row in store.keybind_rows():
        if row["id"] in ("store", "lock"):
            keys[row["id"]] = shortcut(store.get_keybind(row)[0])
    entries = items(startmenu.user_name(), keys, str(store.get(BY_ID["hyprdots.store"])[0]))
    apps = search.installed_apps()
    usage = search.load_usage()

    win = Gtk.ApplicationWindow(application=app)
    if Gtk4LayerShell.is_supported():
        Gtk4LayerShell.init_for_window(win)
        Gtk4LayerShell.set_namespace(win, "logomenu")
        Gtk4LayerShell.set_layer(win, Gtk4LayerShell.Layer.OVERLAY)
        Gtk4LayerShell.set_keyboard_mode(win, Gtk4LayerShell.KeyboardMode.EXCLUSIVE)
        for edge in (Gtk4LayerShell.Edge.TOP, Gtk4LayerShell.Edge.BOTTOM, Gtk4LayerShell.Edge.LEFT, Gtk4LayerShell.Edge.RIGHT):
            Gtk4LayerShell.set_anchor(win, edge, True)  # all the screen below the menu bar, so a click elsewhere closes it
    else:
        win.set_default_size(900, 600)

    backdrop = Gtk.Box(hexpand=True, vexpand=True)
    overlay = Gtk.Overlay(child=backdrop)
    win.set_child(overlay)
    menu = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, css_classes=["menu"], halign=Gtk.Align.START,
                   valign=Gtk.Align.START, margin_start=6, margin_top=3, width_request=250)
    overlay.add_overlay(menu)
    flyout = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, css_classes=["menu"], halign=Gtk.Align.START,
                     valign=Gtk.Align.START, visible=False, width_request=230)
    overlay.add_overlay(flyout)
    state = {"area": "menu", "row": 0, "armed": None, "open": None}
    rows = {"menu": [], "flyout": []}

    def close():
        """A quick fade, then gone."""
        if menu.has_css_class("closing"):
            return
        menu.add_css_class("closing")
        flyout.add_css_class("closing")
        GLib.timeout_add(90, lambda: app.quit() or False)

    def entry_box(title, keys_text="", more=False):
        box = Gtk.Box(css_classes=["entry"])
        box.append(Gtk.Label(label=title, xalign=0, hexpand=True, ellipsize=Pango.EllipsizeMode.END,
                             max_width_chars=34))
        if keys_text:
            box.append(Gtk.Label(label=keys_text, css_classes=["keys"]))
        if more:
            box.append(Gtk.Label(label="\U000f0142", css_classes=["more"]))
        return box

    def add(area, parent, widget, act, hover=None):
        index = len(rows[area])
        rows[area].append({"widget": widget, "act": act, "hover": hover})
        click = Gtk.GestureClick()
        click.connect("released", lambda *_a: act())
        widget.add_controller(click)
        motion = Gtk.EventControllerMotion()
        motion.connect("enter", lambda *_a: select(area, index))
        widget.add_controller(motion)
        parent.append(widget)

    def select(area, index):
        if not rows[area]:
            return
        index = max(0, min(index, len(rows[area]) - 1))
        old_area, old = state["area"], state["row"]
        if old < len(rows[old_area]):
            rows[old_area][old]["widget"].remove_css_class("selected")
        state["area"], state["row"] = area, index
        rows[area][index]["widget"].add_css_class("selected")
        hover = rows[area][index]["hover"]
        if hover:
            hover()
        elif area == "menu":
            hide_flyout()

    def ask(widget, key, title, then):
        """The first pick asks on the item itself; the second does it."""
        if state["armed"] == key:
            then()
            return
        state["armed"] = key
        widget.add_css_class("ask")
        widget.get_first_child().set_label(title)

    # ---- the submenus ----------------------------------------------------------------------------------------------
    def hide_flyout():
        if state["open"] is None:
            return
        state["open"] = None
        flyout.set_visible(False)
        for r in rows["menu"]:
            r["widget"].remove_css_class("open")
        if state["area"] == "flyout":
            state["area"] = "menu"

    def show_flyout(kind, beside):
        if state["open"] == kind:
            return
        state["open"] = kind
        rows["flyout"].clear()
        child = flyout.get_first_child()
        while child:
            flyout.remove(child)
            child = flyout.get_first_child()
        if kind == "recent":
            for a in search.frequent(apps, usage, 8) or apps[:8]:
                add("flyout", flyout, entry_box(a.title), lambda a=a: (run_cmd(a), close()))
        else:
            open_windows = windows()
            if not open_windows:
                flyout.append(Gtk.Label(label="No windows are open", xalign=0, css_classes=["empty"]))
            for w in open_windows:
                label = f"{w['app']} — {w['title']}" if w["title"] else w["app"]
                box = entry_box(label)
                add("flyout", flyout, box, lambda w=w, box=box: ask(
                    box, ("kill", w["pid"]), f"Click again to force quit {w['app']}",
                    lambda: (kill(w["pid"]), close())))
        for r in rows["menu"]:
            (r["widget"].add_css_class if r["widget"] is beside else r["widget"].remove_css_class)("open")
        ok, rect = beside.compute_bounds(overlay)
        flyout.set_margin_start(round(menu.get_margin_start() + menu.get_width() - 4))
        flyout.set_margin_top(round(rect.origin.y - 5) if ok else 0)
        flyout.set_visible(True)

    def kill(pid):
        try:
            os.kill(pid, 9)
        except OSError:
            pass

    # ---- About this PC ---------------------------------------------------------------------------------------------
    def show_about():
        child = menu.get_first_child()
        while child:
            menu.remove(child)
            child = menu.get_first_child()
        hide_flyout()
        rows["menu"].clear()
        card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, css_classes=["about"], spacing=3)
        card.append(Gtk.Label(label=logo or "\U000f0035", css_classes=["about-logo"]))
        card.append(Gtk.Label(label=socket.gethostname(), css_classes=["about-name"]))
        grid = Gtk.Grid(column_spacing=12, row_spacing=3, halign=Gtk.Align.CENTER, margin_top=10)
        for i, (key, value) in enumerate(about()):
            grid.attach(Gtk.Label(label=key, xalign=1, css_classes=["about-key"]), 0, i, 1, 1)
            grid.attach(Gtk.Label(label=value, xalign=0, wrap=True, max_width_chars=30), 1, i, 1, 1)
        card.append(grid)
        more = Gtk.Button(label="More in Settings…", css_classes=["about-button"], halign=Gtk.Align.CENTER)
        more.connect("clicked", lambda _b: (run_cmd([SETTINGS]), close()))
        card.append(more)
        menu.append(card)
        menu.set_size_request(340, -1)

    # ---- the menu --------------------------------------------------------------------------------------------------
    for e in entries:
        if e is None:
            menu.append(Gtk.Box(css_classes=["line"]))
            continue
        box = entry_box(e["title"], e.get("keys", ""), more=e["kind"] in ("recent", "force"))
        if e["kind"] == "about":
            add("menu", menu, box, show_about)
        elif e["kind"] in ("recent", "force"):
            add("menu", menu, box, lambda k=e["kind"], b=box: (show_flyout(k, b), select("flyout", 0)),
                hover=lambda k=e["kind"], b=box: show_flyout(k, b))
        elif e.get("confirm"):
            add("menu", menu, box, lambda e=e, b=box: ask(b, e["title"], f"Click again to {e['confirm']}",
                                                          lambda: (run_cmd(e["cmd"]), close())))
        else:
            add("menu", menu, box, lambda e=e: (run_cmd(e["cmd"]), close()))

    def on_key(_c, keyval, _code, _mods):
        area, row = state["area"], state["row"]
        if keyval == Gdk.KEY_Escape:
            if area == "flyout":
                hide_flyout()
                select("menu", next(i for i, r in enumerate(rows["menu"]) if r["hover"]))
            else:
                close()
        elif keyval in (Gdk.KEY_Up, Gdk.KEY_Down) and rows[area]:
            select(area, (row + (1 if keyval == Gdk.KEY_Down else -1)) % len(rows[area]))
        elif keyval == Gdk.KEY_Right and area == "menu" and rows[area] and rows[area][row]["hover"]:
            rows[area][row]["act"]()
        elif keyval == Gdk.KEY_Left and area == "flyout":
            opened = next((i for i, r in enumerate(rows["menu"]) if r["widget"].has_css_class("open")), 0)
            hide_flyout()
            select("menu", opened)
        elif keyval in (Gdk.KEY_Return, Gdk.KEY_KP_Enter, Gdk.KEY_space) and rows[area]:
            rows[area][row]["act"]()
        else:
            return False
        return True

    keys_ctl = Gtk.EventControllerKey()
    keys_ctl.connect("key-pressed", on_key)
    win.add_controller(keys_ctl)
    click = Gtk.GestureClick()  # a click outside the menu closes it
    click.connect("pressed", lambda _g, _n, x, y: backdrop.pick(x, y, Gtk.PickFlags.DEFAULT) is backdrop and close())
    backdrop.add_controller(click)

    provider = Gtk.CssProvider()
    provider.load_from_string(css(font_list))
    Gtk.StyleContext.add_provider_for_display(Gdk.Display.get_default(), provider, Gtk.STYLE_PROVIDER_PRIORITY_USER + 1)
    win.present()
    return win


def main(run_result) -> int:
    """run_result(result, opts) is the launcher's run(), so apps open the way the launcher opens them."""
    import gi
    gi.require_version("Gtk", "4.0")
    gi.require_version("Gdk", "4.0")
    gi.require_version("Gtk4LayerShell", "1.0")
    from gi.repository import Gdk, GLib, Gtk, Gtk4LayerShell, Pango
    from hyprsettings import design, theme
    from hyprsettings.schema import BY_ID
    from hyprsettings.store import Store
    store = Store()
    o = design.theme_options(store)
    logo_key = store.get(BY_ID["look.super_logo"])[0]
    logo = "" if logo_key == "text" else theme.super_glyph(logo_key)
    opts = {"terminal": store.get(BY_ID["hyprdots.terminal"])[0]}

    def run_cmd(what):
        if isinstance(what, list):
            run_result(search.Result("power", "", extra={"cmd": what}), opts)
        else:
            run_result(what, opts)

    app = Gtk.Application(application_id="com.hyprdots.logomenu")

    def activate(a):
        if a.get_windows():  # clicked again while open: close
            a.quit()
            return
        build(a, Gtk, Gdk, GLib, Pango, Gtk4LayerShell, logo, design.font_list(o), run_cmd)
    app.connect("activate", activate)
    return app.run([sys.argv[0]])
