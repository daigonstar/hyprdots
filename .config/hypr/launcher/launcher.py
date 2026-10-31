#!/usr/bin/env python3
"""App launcher (Super+Space): type to search apps, do sums, run commands (>), search the web (?) or lock, sleep,
reboot and shut down. Five styles, picked on the settings Launcher page:

  spotlight   a search bar in the middle of the screen, results below it
  grid        full screen grid of big icons
  categories  categories on the left, apps on the right (the default)
  compact     a small list under the bar
  dock        a strip of large icons along the bottom

Colours and font come from the settings Theme page. Keys: type to search, arrows to move, Enter to open, Tab to switch
category, Esc clears the search or closes. Running it again while it is open closes it.
Run through launcher.sh (it preloads gtk4-layer-shell). --style NAME overrides the setting for a try-out."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "settings"))
import search  # noqa: E402
from hyprsettings import design  # noqa: E402
from hyprsettings.schema import BY_ID  # noqa: E402
from hyprsettings.store import Store  # noqa: E402

STYLES = ("spotlight", "grid", "categories", "compact", "dock")
ICON_FONT = "CaskaydiaCove Nerd Font"


def settings() -> dict:
    store = Store()
    get = lambda key, fallback: store.get(BY_ID[key])[0] if key in BY_ID else fallback  # noqa: E731
    out = {"style": get("launcher.style", "categories"), "engine": get("launcher.search_engine", "duckduckgo"),
           "rank": get("launcher.rank_by_use", True), "terminal": get("hyprdots.terminal", "ghostty")}
    for i, arg in enumerate(sys.argv):
        if arg == "--style" and i + 1 < len(sys.argv) and sys.argv[i + 1] in STYLES:
            out["style"] = sys.argv[i + 1]
    return out


def css(style: str) -> str:
    store = Store()
    o = design.theme_options(store)
    c = design.resolved(o)
    o = {**design.DEFAULTS, **o}
    panel = design.alpha_rgba(c["base"], max(int(o["base_opacity"]), 99) / 100)
    dim = {"categories": 0.45, "compact": 0.12, "dock": 0.25}.get(style, 0.35)
    shade = design.alpha_rgba(c["base"], 0.93) if style == "grid" else f"rgba(0, 0, 0, {dim})"
    return f"""
window, window.background {{ background: transparent; }}
* {{ font-family: {design.font_list(o)}; color: {c['base_text']}; }}
.backdrop {{ background: {shade}; }}
.panel {{
    background: {panel};
    border: 1px solid {design.alpha_rgba(c['accent'], 0.35)};
    border-radius: 22px;
    box-shadow: 0 18px 60px rgba(0, 0, 0, 0.5);
    padding: 16px;
}}
.panel.flat {{ border-radius: 0px; border-width: 0px; box-shadow: none; background: transparent; padding: 32px 90px; }}
entry.search, text.search {{
    min-height: 46px; border-radius: 14px; padding: 0 14px; font-size: 17px;
    background: {design.alpha_rgba(c['base_text'], 0.07)}; border: 1px solid {design.alpha_rgba(c['accent'], 0.30)};
    box-shadow: none; outline: none;
}}
entry.search:focus-within {{ border-color: {c['accent']}; }}
.item {{ border-radius: 12px; padding: 6px 10px; border: 1px solid transparent; background: none; }}
.item.tile {{ padding: 12px 6px; }}
.item:hover {{ background: {design.alpha_rgba(c['accent'], 0.12)}; }}
.item.selected {{ background: {design.alpha_rgba(c['accent'], 0.22)}; border-color: {design.alpha_rgba(c['accent'], 0.8)}; }}
.title {{ font-weight: 600; }}
.subtitle {{ opacity: 0.6; font-size: 12px; }}
.glyph {{ font-family: "{ICON_FONT}"; color: {c['accent']}; }}
.section {{ opacity: 0.55; font-size: 12px; font-weight: 700; letter-spacing: 1px; margin: 4px 6px; }}
.sidebar {{ background: {design.alpha_rgba(c['base_text'], 0.04)}; border-radius: 16px; padding: 8px; }}
.cat {{ border-radius: 10px; padding: 8px 12px; }}
.cat.active {{ background: {c['accent']}; }}
.cat.active label {{ color: {c['base']}; }}
.hint {{ opacity: 0.45; font-size: 11px; }}
.empty {{ opacity: 0.5; margin: 30px; }}
flowbox, flowboxchild, list, row {{ background: none; padding: 0; }}
"""


# ---- one result as a row or a tile ---------------------------------------------------------------------------------
def icon_for(Gtk, result, size: int):
    if result.kind == "app" and result.gicon is not None:
        image = Gtk.Image.new_from_gicon(result.gicon)
        image.set_pixel_size(size)
        return image
    if result.kind == "app":
        image = Gtk.Image(icon_name="application-x-executable")
        image.set_pixel_size(size)
        return image
    label = Gtk.Label(label=result.glyph or "\U000f0349", css_classes=["glyph"])
    label.set_markup(f'<span size="{int(size * 0.7)}pt">{result.glyph or chr(0xf0349)}</span>')
    return label


def row_widget(Gtk, Pango, result, size: int):
    box = Gtk.Box(spacing=12, css_classes=["item"])
    box.append(icon_for(Gtk, result, size))
    text = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, valign=Gtk.Align.CENTER, hexpand=True)
    text.append(Gtk.Label(label=result.title, xalign=0, css_classes=["title"], ellipsize=Pango.EllipsizeMode.END))
    if result.subtitle:
        text.append(Gtk.Label(label=result.subtitle, xalign=0, css_classes=["subtitle"], ellipsize=Pango.EllipsizeMode.END))
    box.append(text)
    return box


def tile_widget(Gtk, Pango, result, size: int, width: int):
    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8, css_classes=["item", "tile"], width_request=width)
    box.append(icon_for(Gtk, result, size))
    box.append(Gtk.Label(label=result.title, css_classes=["title"], ellipsize=Pango.EllipsizeMode.END,
                         max_width_chars=14, justify=Gtk.Justification.CENTER))
    return box


# ---- the launcher -----------------------------------------------------------------------------------------------------
def build(app, Gtk, Gdk, GLib, Pango, Gtk4LayerShell):
    opts = settings()
    style = opts["style"] if opts["style"] in STYLES else "categories"
    apps = search.installed_apps()
    usage = search.load_usage() if opts["rank"] else {}
    state = {"results": [], "index": 0, "category": "All apps", "armed": None, "widgets": []}

    win = Gtk.ApplicationWindow(application=app)
    if Gtk4LayerShell.is_supported():
        Gtk4LayerShell.init_for_window(win)
        Gtk4LayerShell.set_namespace(win, "launcher")
        Gtk4LayerShell.set_layer(win, Gtk4LayerShell.Layer.OVERLAY)
        Gtk4LayerShell.set_keyboard_mode(win, Gtk4LayerShell.KeyboardMode.EXCLUSIVE)
        Gtk4LayerShell.set_exclusive_zone(win, -1)
        for edge in (Gtk4LayerShell.Edge.TOP, Gtk4LayerShell.Edge.BOTTOM, Gtk4LayerShell.Edge.LEFT, Gtk4LayerShell.Edge.RIGHT):
            Gtk4LayerShell.set_anchor(win, edge, True)
    else:
        win.set_default_size(1200, 800)

    backdrop = Gtk.Box(css_classes=["backdrop"])
    win.set_child(backdrop)
    entry = Gtk.SearchEntry(css_classes=["search"], hexpand=True,
                            placeholder_text="Search apps, work out a sum, > run a command, ? search the web")

    # where the panel sits, how big it is, and what kind of view it uses
    layout = {
        "spotlight": dict(halign=Gtk.Align.CENTER, valign=Gtk.Align.START, width=680, margin_top=0.2, view="list", icon=34, rows=8),
        "compact": dict(halign=Gtk.Align.START, valign=Gtk.Align.START, width=440, margin_top=56, margin_start=12, view="list", icon=28, rows=9),
        "grid": dict(halign=Gtk.Align.FILL, valign=Gtk.Align.FILL, width=-1, margin_top=40, view="grid", icon=64, tile=150, flat=True),
        "categories": dict(halign=Gtk.Align.CENTER, valign=Gtk.Align.CENTER, width=1100, height=0.72, view="grid", icon=52, tile=128),
        "dock": dict(halign=Gtk.Align.CENTER, valign=Gtk.Align.END, width=0.86, margin_bottom=18, view="row", icon=56, tile=112),
    }[style]

    panel = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12, css_classes=["panel"] + (["flat"] if layout.get("flat") else []),
                    halign=layout["halign"], valign=layout["valign"], hexpand=True, vexpand=True)
    backdrop.append(panel)
    header = Gtk.Box(spacing=10)
    header.append(entry)
    if style in ("grid", "dock"):
        entry.set_halign(Gtk.Align.CENTER)
        entry.set_hexpand(False)
        entry.set_size_request(560, -1)
        header.set_halign(Gtk.Align.CENTER)
    panel.append(header)

    body = Gtk.Box(spacing=12, vexpand=True)
    panel.append(body)
    sidebar = None
    if style == "categories":
        sidebar = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2, css_classes=["sidebar"], width_request=210)
        body.append(sidebar)

    if layout["view"] == "list":
        view = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
    elif layout["view"] == "row":
        view = Gtk.Box(spacing=6)
    else:
        view = Gtk.FlowBox(selection_mode=Gtk.SelectionMode.NONE, homogeneous=True, valign=Gtk.Align.START,
                           min_children_per_line=3, max_children_per_line=12, column_spacing=6, row_spacing=6)
    scroller = Gtk.ScrolledWindow(child=view, hexpand=True, vexpand=True,
                                  hscrollbar_policy=Gtk.PolicyType.AUTOMATIC if layout["view"] == "row" else Gtk.PolicyType.NEVER,
                                  vscrollbar_policy=Gtk.PolicyType.NEVER if layout["view"] == "row" else Gtk.PolicyType.AUTOMATIC,
                                  propagate_natural_height=layout["view"] != "grid", propagate_natural_width=layout["view"] == "row")
    body.append(scroller)
    hint = Gtk.Label(css_classes=["hint"], label="Enter opens  ·  arrows move  ·  Esc closes"
                     + ("  ·  Tab switches category" if style == "categories" else ""))
    panel.append(hint)

    def size_panel(*_):
        surface = win.get_surface()
        display = win.get_display()
        mon = display.get_monitor_at_surface(surface) if surface else None
        if mon is None and display.get_monitors().get_n_items():
            mon = display.get_monitors().get_item(0)
        if mon is None:
            return
        g = mon.get_geometry()
        w = layout.get("width", -1)
        panel.set_size_request(int(g.width * w) if isinstance(w, float) else w, int(g.height * layout["height"]) if "height" in layout else -1)
        top = layout.get("margin_top", 0)
        panel.set_margin_top(int(g.height * top) if isinstance(top, float) else top)
        panel.set_margin_start(layout.get("margin_start", 0))
        panel.set_margin_bottom(layout.get("margin_bottom", 0))
        if layout["view"] == "list":
            scroller.set_max_content_height(layout["rows"] * (layout["icon"] + 26))
        if layout["view"] == "row":
            scroller.set_min_content_height(layout["icon"] + 60)
    win.connect("realize", size_panel)

    # ---- categories sidebar ----
    def categories():
        present = {a.category for a in apps}
        names = (["Frequent"] if search.frequent(apps, usage) else []) + ["All apps"]
        names += [n for n, _ in search.BUCKETS if n in present] + (["Other"] if "Other" in present else [])
        return names

    def draw_sidebar():
        if sidebar is None:
            return
        child = sidebar.get_first_child()
        while child:
            sidebar.remove(child)
            child = sidebar.get_first_child()
        sidebar.append(Gtk.Label(label="CATEGORIES", xalign=0, css_classes=["section"]))
        for name in categories():
            active = name == state["category"] and not entry.get_text().strip()
            button = Gtk.Button(css_classes=["flat", "cat"] + (["active"] if active else []))
            inner = Gtk.Box(spacing=10)
            inner.append(Gtk.Label(label=search.CATEGORY_ICONS.get(name, ""), css_classes=["glyph"]))
            inner.append(Gtk.Label(label=name, xalign=0))
            button.set_child(inner)
            button.connect("clicked", lambda _b, name=name: pick_category(name))
            sidebar.append(button)

    def pick_category(name):
        state["category"] = name
        entry.set_text("")
        refresh()

    # ---- results ----
    def results_for(query):
        if query.strip():
            return search.search(query, apps, usage, opts["engine"], opts["rank"])
        if style == "categories":
            cat = state["category"]
            if cat == "Frequent":
                return search.frequent(apps, usage, 24)
            return apps if cat == "All apps" else [a for a in apps if a.category == cat]
        if style == "grid":
            return apps
        recent = search.frequent(apps, usage, {"spotlight": 8, "compact": 9, "dock": 16}[style])
        return recent or apps[:{"spotlight": 8, "compact": 9, "dock": 16}[style]]

    def refresh(*_):
        state["armed"] = None
        state["results"] = results_for(entry.get_text())
        state["index"] = 0
        child = view.get_first_child()
        while child:
            view.remove(child)
            child = view.get_first_child()
        state["widgets"] = []
        if not state["results"]:
            view.append(Gtk.Label(label="Nothing matches", css_classes=["empty"], hexpand=True))
        for i, r in enumerate(state["results"][:200]):
            if layout["view"] == "list":
                w = row_widget(Gtk, Pango, r, layout["icon"])
            else:
                w = tile_widget(Gtk, Pango, r, layout["icon"], layout["tile"])
            click = Gtk.GestureClick()
            click.connect("released", lambda _g, _n, _x, _y, i=i: (select(i), activate()))
            w.add_controller(click)
            motion = Gtk.EventControllerMotion()
            motion.connect("enter", lambda _c, _x, _y, i=i: select(i, scroll=False))
            w.add_controller(motion)
            view.append(w)
            state["widgets"].append(w)
        draw_sidebar()
        select(0)

    def select(i, scroll=True):
        widgets = state["widgets"]
        if not widgets:
            return
        i = max(0, min(i, len(widgets) - 1))
        widgets[state["index"]].remove_css_class("selected") if state["index"] < len(widgets) else None
        state["index"] = i
        widgets[i].add_css_class("selected")
        if scroll:
            GLib.idle_add(scroll_to, widgets[i])

    def scroll_to(widget):
        ok, rect = widget.compute_bounds(view)
        if not ok:
            return False
        vertical = layout["view"] != "row"
        adj = scroller.get_vadjustment() if vertical else scroller.get_hadjustment()
        start, length = (rect.origin.y, rect.size.height) if vertical else (rect.origin.x, rect.size.width)
        if start < adj.get_value():
            adj.set_value(start - 8)
        elif start + length > adj.get_value() + adj.get_page_size():
            adj.set_value(start + length - adj.get_page_size() + 8)
        return False

    def columns():
        widgets = state["widgets"]
        if layout["view"] != "grid" or len(widgets) < 2:
            return 1
        ok, first = widgets[0].compute_bounds(view)
        return max(1, sum(1 for w in widgets if w.compute_bounds(view)[1].origin.y == first.origin.y))

    def activate():
        if not state["results"]:
            return
        r = state["results"][state["index"]]
        if r.kind == "power" and r.confirm and state["armed"] != r.value:
            state["armed"] = r.value  # first Enter: ask, by showing it on the item itself
            title = state["widgets"][state["index"]]
            for label in _labels(title):
                if label.has_css_class("subtitle") or label.has_css_class("title"):
                    label.set_label(f"Press Enter again to {r.title.lower()}") if label.has_css_class("title") else None
            return
        run(r, opts)
        app.quit()

    def _labels(widget):
        out, stack = [], [widget]
        while stack:
            w = stack.pop()
            if isinstance(w, Gtk.Label):
                out.append(w)
            child = w.get_first_child()
            while child:
                stack.append(child)
                child = child.get_next_sibling()
        return out

    entry.connect("search-changed", refresh)
    entry.connect("activate", lambda _e: activate())

    def on_key(_ctl, keyval, _code, mods):
        cols = columns()
        if keyval == Gdk.KEY_Escape:
            if entry.get_text():
                entry.set_text("")
            else:
                app.quit()
            return True
        if keyval in (Gdk.KEY_Down, Gdk.KEY_Up):
            step = cols if layout["view"] == "grid" else 1
            select(state["index"] + (step if keyval == Gdk.KEY_Down else -step))
            return True
        if layout["view"] in ("grid", "row") and keyval in (Gdk.KEY_Left, Gdk.KEY_Right) and not entry.get_text():
            select(state["index"] + (1 if keyval == Gdk.KEY_Right else -1))
            return True
        if layout["view"] in ("grid", "row") and keyval in (Gdk.KEY_Left, Gdk.KEY_Right) and entry.get_position() == len(entry.get_text()) and keyval == Gdk.KEY_Right:
            select(state["index"] + 1)
            return True
        if style == "categories" and keyval in (Gdk.KEY_Tab, Gdk.KEY_ISO_Left_Tab):
            names = categories()
            here = names.index(state["category"]) if state["category"] in names else 0
            back = keyval == Gdk.KEY_ISO_Left_Tab or (mods & Gdk.ModifierType.SHIFT_MASK)
            pick_category(names[(here + (-1 if back else 1)) % len(names)])
            return True
        return False
    keys = Gtk.EventControllerKey(propagation_phase=Gtk.PropagationPhase.CAPTURE)
    keys.connect("key-pressed", on_key)
    win.add_controller(keys)

    click = Gtk.GestureClick()  # a click outside the panel closes the launcher
    click.connect("pressed", lambda _g, _n, x, y: backdrop.pick(x, y, Gtk.PickFlags.DEFAULT) is backdrop and app.quit())
    backdrop.add_controller(click)

    provider = Gtk.CssProvider()
    provider.load_from_string(css(style))
    Gtk.StyleContext.add_provider_for_display(Gdk.Display.get_default(), provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
    if usage and style == "categories" and not entry.get_text():
        state["category"] = "All apps"
    refresh()
    win.present()
    entry.grab_focus()
    return win


def run(r, opts) -> None:
    """Does what the chosen result is for, detached from the launcher."""
    def spawn(cmd):
        subprocess.Popen(cmd, start_new_session=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         stdin=subprocess.DEVNULL)
    if r.kind == "app":
        search.record_use(r.app_id)
        spawn(["gtk-launch", r.app_id])
    elif r.kind == "calc":
        spawn(["wl-copy", r.value])
    elif r.kind == "web":
        spawn(["xdg-open", r.value])
    elif r.kind == "command":
        shell = os.environ.get("SHELL", "/bin/sh")
        spawn([*str(opts["terminal"]).split(), "-e", shell, "-c", f'{r.value}; exec "{shell}"'])
    elif r.kind == "power":
        spawn([os.path.expanduser(part) for part in r.extra["cmd"]])


def main() -> int:
    if "--list" in sys.argv:  # what the launcher would show, without a window
        for r in search.search(" ".join(a for a in sys.argv[1:] if a != "--list"), search.installed_apps(), search.load_usage()):
            print(r.kind, r.title)
        return 0
    import gi
    gi.require_version("Gtk", "4.0")
    gi.require_version("Gdk", "4.0")
    gi.require_version("Gtk4LayerShell", "1.0")
    from gi.repository import Gdk, GLib, Gtk, Gtk4LayerShell, Pango

    app = Gtk.Application(application_id="com.hyprdots.launcher")

    def activate(a):
        if a.get_windows():  # opened again while open: close
            a.quit()
            return
        build(a, Gtk, Gdk, GLib, Pango, Gtk4LayerShell)
    app.connect("activate", activate)
    return app.run([sys.argv[0]])


if __name__ == "__main__":
    sys.exit(main())
