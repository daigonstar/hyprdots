#!/usr/bin/env python3
"""The dock of a theme override that has one (Mac style), drawn by hyprdots itself so it can move like a Mac's:

  - hidden until the pointer touches the bottom edge of a screen (a strip two pixels high along each one), then it
    rises on that screen, over your windows
  - the apps you have open, one tile per app with a dot under it, then the button for every app (the full screen
    library); a click brings the app's latest window forward, a middle click closes it
  - icons swell as the pointer passes along the dock, the nearest most
  - once the pointer moves up off it, it sinks away and is gone, also from an empty workspace

waybar/launch.sh starts it (through dock.sh, which preloads gtk4-layer-shell) when barlayout has written
config.dock.json, the look's settings for it (theme_override.bar()["dock"]). It asks Hyprland for open windows and where
the pointer is only while it is showing."""

from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import sys
from pathlib import Path

CONFIG = Path(__file__).resolve().parent.parent / "config.dock.json"
ICON_FONT = "CaskaydiaCove Nerd Font Propo"
CHECK_MS = 120        # while it shows, where the pointer is gets checked this often
AWAY_CHECKS = 3       # checks in a row above the dock before it sinks away (about a third of a second)
OUT_MS = 200          # how long sinking away takes (matches the CSS)
REFRESH_MS = 1500     # open apps are re-read this often while it shows
SWELL = (1.0, 1.12, 1.3, 1.55)  # icon size by closeness to the pointer: far, two away, next to it, under it


# ---- deciding (no GTK, so it can be tested) --------------------------------------------------------------------------
def settings(config: dict) -> dict:
    icon = int(config.get("icon-size", 48))
    return {"icon": icon, "gap": int(config.get("margin-bottom", 6)), "launchpad": str(config.get("launchpad", "")),
            "height": round(icon * SWELL[-1]) + 36 + int(config.get("margin-bottom", 6))}


def group(clients: list[dict], order: list[str]) -> tuple[list[dict], list[str]]:
    """One entry per app (window class), the window to bring forward being its most recently used. Apps keep the
    place they first took, new ones join at the end, as on a Mac's dock. Returns (apps, the order to keep)."""
    best: dict[str, dict] = {}
    for c in clients:
        cls = c.get("class") or c.get("initialClass") or ""
        if not cls or not c.get("mapped", True) or c.get("hidden"):
            continue
        if cls not in best or c.get("focusHistoryID", 99) < best[cls].get("focusHistoryID", 99):
            best[cls] = c
    order = [cls for cls in order if cls in best] + sorted((cls for cls in best if cls not in order),
                                                          key=lambda cls: best[cls].get("focusHistoryID", 99))
    apps = [{"class": cls, "title": best[cls].get("title", ""), "address": best[cls].get("address", ""),
             "pid": best[cls].get("pid")} for cls in order]
    return apps, order


def monitor_at(x: float, y: float, monitors: list[dict]) -> dict | None:
    for m in monitors:
        if m["x"] <= x < m["x"] + m["w"] and m["y"] <= y < m["y"] + m["h"]:
            return m
    return None


def near_dock(x: float, y: float, monitors: list[dict], zone: int) -> bool:
    """True while the pointer is low enough on its screen to be on (or reaching for) the dock. The pointer is asked
    for rather than followed with enter and leave, which fire as the dock moves under a still pointer."""
    m = monitor_at(x, y, monitors)
    return m is not None and y >= m["y"] + m["h"] - zone


def logical(monitors: list[dict]) -> list[dict]:
    """Hyprland's monitors (pixels, scale, rotation) as boxes in the layout's own units, where the pointer lives."""
    out = []
    for m in monitors:
        w, h = m["width"], m["height"]
        if int(m.get("transform", 0)) % 2:  # turned on its side
            w, h = h, w
        scale = float(m.get("scale") or 1)
        out.append({"x": m["x"], "y": m["y"], "w": w / scale, "h": h / scale})
    return out


def swell(index: int, hovered: int | None) -> float:
    if hovered is None:
        return SWELL[0]
    distance = abs(index - hovered)
    return SWELL[max(0, len(SWELL) - 1 - distance)] if distance < len(SWELL) else SWELL[0]


def desktop_index(entries: list[tuple[str, str, str]]) -> dict[str, str]:
    """(desktop id, StartupWMClass, executable) per app -> lookup of lower-case names to the desktop id."""
    index: dict[str, str] = {}
    for app_id, wm_class, exe in entries:
        stem = app_id.removesuffix(".desktop")
        for key in (wm_class, stem, stem.split(".")[-1], Path(exe).name if exe else ""):
            if key:
                index.setdefault(key.lower(), app_id)
    return index


def find_app(window_class: str, index: dict[str, str]) -> str | None:
    cls = window_class.lower()
    return index.get(cls) or index.get(cls.split(".")[-1]) or index.get(cls.replace(" ", "-"))


# ---- talking to Hyprland ---------------------------------------------------------------------------------------------
def hypr(request: str):
    path = Path(os.environ.get("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}")) / "hypr" / \
        os.environ.get("HYPRLAND_INSTANCE_SIGNATURE", "") / ".socket.sock"
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
        s.settimeout(1)
        s.connect(str(path))
        s.sendall(request.encode())
        data = b""
        while chunk := s.recv(65536):
            data += chunk
    return data.decode()


def clients() -> list[dict]:
    try:
        return json.loads(hypr("j/clients"))
    except (OSError, ValueError):
        return []


def dispatch(expr: str) -> None:
    try:
        hypr(f"dispatch {expr}")
    except OSError:
        pass


def spawn(command: str) -> None:
    env = {k: v for k, v in os.environ.items() if k != "LD_PRELOAD"}  # the preload is for this process only
    cmd = ["sh", "-c", os.path.expanduser(command)]
    if shutil.which("systemd-run"):  # its own scope, not part of waybar.service (see launcher.own_scope)
        cmd = ["systemd-run", "--user", "--scope", "--collect", "--quiet", "--", *cmd]
    subprocess.Popen(cmd, start_new_session=True, env=env,
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def css(cfg: dict) -> str:
    icon = cfg["icon"]
    sizes = "".join(f".tile.s{i} image {{ -gtk-icon-size: {round(icon * s)}px; }}\n" for i, s in enumerate(SWELL))
    return f"""
window, window.background {{ background: transparent; }}
.stage {{ background: transparent; }}
.shelf {{
    background: rgba(246, 246, 246, 0.66);
    border: 1px solid rgba(255, 255, 255, 0.6);
    border-radius: 20px;
    padding: 6px 8px 3px 8px;
    margin-bottom: {cfg['gap']}px;
    box-shadow: 0px 6px 22px rgba(0, 0, 0, 0.28);
}}
.shelf.in {{ animation: rise 280ms cubic-bezier(0.2, 0.9, 0.25, 1.06); }}
.shelf.out {{ transition: transform {OUT_MS}ms cubic-bezier(0.5, 0, 0.75, 0), opacity {OUT_MS}ms ease-in;
    transform: translateY({cfg['height']}px); opacity: 0; }}
@keyframes rise {{ from {{ transform: translateY({cfg['height']}px); opacity: 0.3; }} to {{ transform: none; opacity: 1; }} }}
.tile {{ padding: 0px 3px; }}
.tile image {{ transition: -gtk-icon-size 130ms ease-out; }}
{sizes}.tile.pressed image {{ opacity: 0.6; }}
.dot {{ min-width: 4px; min-height: 4px; border-radius: 99px; margin-top: 3px; background: transparent; }}
.dot.on {{ background: rgba(29, 29, 31, 0.75); }}
.sep {{ min-width: 1px; background: rgba(0, 0, 0, 0.15); margin: 6px 5px 10px 5px; }}
.grid {{ font-family: "{ICON_FONT}"; color: #1d1d1f; transition: font-size 130ms ease-out; }}
"""


# ---- running it -----------------------------------------------------------------------------------------------------
def main() -> int:
    import gi
    gi.require_version("Gtk", "4.0")
    gi.require_version("Gdk", "4.0")
    gi.require_version("Gtk4LayerShell", "1.0")
    from gi.repository import Gdk, Gio, GLib, Gtk, Gtk4LayerShell

    try:
        cfg = settings(json.loads(CONFIG.read_text(encoding="utf-8")))
    except (OSError, ValueError):
        return 0  # no dock in this look
    try:
        from gi.repository import GioUnix
        DesktopAppInfo = GioUnix.DesktopAppInfo
    except ImportError:
        DesktopAppInfo = Gio.DesktopAppInfo
    infos = [i for i in Gio.AppInfo.get_all() if isinstance(i, DesktopAppInfo)]
    index = desktop_index([(i.get_id() or "", i.get_startup_wm_class() or "", i.get_executable() or "") for i in infos])
    by_id = {i.get_id(): i for i in infos}
    state = {"shown": False, "order": [], "tiles": [], "refresh": 0, "check": 0, "away": 0, "hovered": None,
             "apps": [], "monitors": []}

    app = Gtk.Application(application_id="com.hyprdots.dock")
    win = shelf = None

    def icon_for(window_class):
        info = by_id.get(find_app(window_class, index) or "")
        image = Gtk.Image.new_from_gicon(info.get_icon()) if info and info.get_icon() else \
            Gtk.Image(icon_name="application-x-executable")
        name = info.get_display_name() if info else window_class
        return image, name

    def set_swell(hovered):
        state["hovered"] = hovered
        for i, tile in enumerate(state["tiles"]):
            for k in range(len(SWELL)):
                tile.remove_css_class(f"s{k}")
            tile.add_css_class(f"s{SWELL.index(swell(i, hovered))}")

    def tile(child, tooltip, on_click, running=True, on_middle=None):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, css_classes=["tile", "s0"], valign=Gtk.Align.END,
                      tooltip_text=tooltip)
        box.append(child)
        box.append(Gtk.Box(css_classes=["dot"] + (["on"] if running else []), halign=Gtk.Align.CENTER))
        i = len(state["tiles"])
        state["tiles"].append(box)
        motion = Gtk.EventControllerMotion()
        motion.connect("enter", lambda *_a: set_swell(i))
        box.add_controller(motion)
        click = Gtk.GestureClick(button=0)
        click.connect("pressed", lambda *_a: box.add_css_class("pressed"))

        def released(gesture, *_a):
            box.remove_css_class("pressed")
            if gesture.get_current_button() == 2 and on_middle:
                on_middle()
            elif gesture.get_current_button() == 1:
                on_click()
        click.connect("released", released)
        box.add_controller(click)
        shelf.append(box)

    def fill():
        apps, state["order"] = group(clients(), state["order"])
        if [a["class"] for a in apps] == [a["class"] for a in state["apps"]] and state["tiles"]:
            state["apps"] = apps  # same apps: keep the tiles (and the swell under the pointer)
            return
        state["apps"] = apps
        child = shelf.get_first_child()
        while child:
            shelf.remove(child)
            child = shelf.get_first_child()
        state["tiles"] = []
        for a in apps:
            image, name = icon_for(a["class"])
            tile(image, name, lambda a=a: (dispatch(f'hl.dsp.focus({{ window = "address:{a["address"]}" }})'), sink()),
                 on_middle=lambda a=a: dispatch(f'hl.dsp.window.close({{ window = "address:{a["address"]}" }})'))
        if apps:
            shelf.append(Gtk.Box(css_classes=["sep"]))
        grid = Gtk.Image(icon_name="view-app-grid-symbolic")
        if not Gtk.IconTheme.get_for_display(Gdk.Display.get_default()).has_icon("view-app-grid-symbolic"):
            grid = Gtk.Image(icon_name="view-grid-symbolic")
        tile(grid, "All apps", lambda: (spawn(cfg["launchpad"]), sink()), running=False)
        set_swell(state["hovered"])

    def refresh():
        if not state["shown"]:
            state["refresh"] = 0
            return False
        fill()
        return True

    def show(monitor):
        if state["shown"]:
            if shelf.has_css_class("out"):
                rise()
            return
        state["shown"], state["away"] = True, 0
        try:
            state["monitors"] = logical(json.loads(hypr("j/monitors")))
        except (OSError, ValueError):
            state["monitors"] = []
        Gtk4LayerShell.set_monitor(win, monitor)
        fill()
        win.set_visible(True)
        rise()
        state["refresh"] = state["refresh"] or GLib.timeout_add(REFRESH_MS, refresh)
        state["check"] = state["check"] or GLib.timeout_add(CHECK_MS, check)

    def rise():
        shelf.remove_css_class("out")
        shelf.remove_css_class("in")
        GLib.idle_add(lambda: shelf.add_css_class("in") or False)  # a fresh rise each time

    def check():
        if not state["shown"]:
            state["check"] = 0
            return False
        try:
            pos = json.loads(hypr("j/cursorpos"))
            near = near_dock(pos["x"], pos["y"], state["monitors"], cfg["height"])
        except (OSError, ValueError, KeyError):
            near = False
        if near and shelf.has_css_class("out"):  # caught on its way down: back up
            rise()
        state["away"] = 0 if near else state["away"] + 1
        if state["away"] == AWAY_CHECKS:
            sink()
        return True

    def sink():
        if not state["shown"] or shelf.has_css_class("out"):
            return
        set_swell(None)
        shelf.remove_css_class("in")
        shelf.add_css_class("out")
        GLib.timeout_add(OUT_MS, gone)

    def gone():
        if shelf.has_css_class("out"):  # not called back by the pointer in the meantime
            win.set_visible(False)
            state["shown"] = False
        return False

    def strip(monitor):
        edge = Gtk.Window(application=app, default_height=2)
        Gtk4LayerShell.init_for_window(edge)
        Gtk4LayerShell.set_namespace(edge, "dock-edge")
        Gtk4LayerShell.set_layer(edge, Gtk4LayerShell.Layer.TOP)
        Gtk4LayerShell.set_monitor(edge, monitor)
        Gtk4LayerShell.set_exclusive_zone(edge, -1)
        Gtk4LayerShell.set_keyboard_mode(edge, Gtk4LayerShell.KeyboardMode.NONE)
        for side in (Gtk4LayerShell.Edge.BOTTOM, Gtk4LayerShell.Edge.LEFT, Gtk4LayerShell.Edge.RIGHT):
            Gtk4LayerShell.set_anchor(edge, side, True)
        box = Gtk.Box(height_request=2, css_classes=["edge"])
        edge.set_child(box)
        motion = Gtk.EventControllerMotion()
        motion.connect("enter", lambda *_a: show(monitor))
        box.add_controller(motion)
        edge.present()
        return edge

    strips = []

    def strips_for_monitors(*_a):
        for edge in strips:
            edge.destroy()
        strips.clear()
        monitors = Gdk.Display.get_default().get_monitors()
        for i in range(monitors.get_n_items()):
            strips.append(strip(monitors.get_item(i)))

    def activate(_a):
        nonlocal win, shelf
        provider = Gtk.CssProvider()
        provider.load_from_string(css(cfg) + ".edge { background: rgba(0, 0, 0, 0.004); }")
        Gtk.StyleContext.add_provider_for_display(Gdk.Display.get_default(), provider,
                                                  Gtk.STYLE_PROVIDER_PRIORITY_USER + 1)
        strips_for_monitors()
        Gdk.Display.get_default().get_monitors().connect("items-changed", strips_for_monitors)
        win = Gtk.Window(application=app, default_height=cfg["height"])
        Gtk4LayerShell.init_for_window(win)
        Gtk4LayerShell.set_namespace(win, "dock")
        Gtk4LayerShell.set_layer(win, Gtk4LayerShell.Layer.TOP)
        Gtk4LayerShell.set_exclusive_zone(win, -1)  # over windows, taking no room from them
        Gtk4LayerShell.set_keyboard_mode(win, Gtk4LayerShell.KeyboardMode.NONE)
        for side in (Gtk4LayerShell.Edge.BOTTOM, Gtk4LayerShell.Edge.LEFT, Gtk4LayerShell.Edge.RIGHT):
            Gtk4LayerShell.set_anchor(win, side, True)
        stage = Gtk.Box(css_classes=["stage"], height_request=cfg["height"], valign=Gtk.Align.END, hexpand=True)
        shelf = Gtk.Box(css_classes=["shelf"], halign=Gtk.Align.CENTER, valign=Gtk.Align.END, hexpand=True)
        stage.append(shelf)
        win.set_child(stage)
        settle = Gtk.EventControllerMotion()  # off the icons but still at the dock: they settle back
        settle.connect("leave", lambda *_a: set_swell(None))
        shelf.add_controller(settle)
        win.set_visible(False)
        app.hold()

    app.connect("activate", activate)
    return app.run([sys.argv[0]])


if __name__ == "__main__":
    sys.exit(main())
