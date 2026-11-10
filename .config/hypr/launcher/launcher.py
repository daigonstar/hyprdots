#!/usr/bin/env python3
"""App launcher (Super+Space): type to search apps, do sums, run commands (>), search the web (?) or lock, sleep,
reboot and shut down. Nine styles, picked on the settings Launcher page:

  categories  a rail of categories beside the search and apps (the default)
  spotlight   just a search pill; results drop out as a separate card when you type, or press Down for recent apps
  grid        a full screen library with an A to Z down the side (Alt+letter jumps)
  compact     a slim numbered list under the bar (Alt+1 to 9 opens one)
  dock        a floating strip of icons along the bottom; search only appears when you type
  orbit       a ring of apps circling the search box; arrows spin it (stage.py)
  carousel    cards in a row, the picked one facing you and the rest turned away in 3D (stage.py)
  terminal    a green screen: type at the prompt, results as lines of text
  bubbles     apps float as bubbles, the ones you open most bigger and nearer the middle (stage.py)

Colours and font come from the settings Theme page. Keys: type to search, arrows to move, Enter to open, Tab to switch
category, Esc clears the search or closes. Left and Right walk the results; with Ctrl or Shift, or when there is only
one result to choose, they edit the search text. Running it again while it is open closes it.
Run through launcher.sh (it preloads gtk4-layer-shell). --style NAME overrides the setting for a try-out."""

from __future__ import annotations

import os
import socket
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

STYLES = ("spotlight", "grid", "categories", "compact", "dock", "orbit", "carousel", "terminal", "bubbles")
STAGED = ("orbit", "carousel", "bubbles")  # drawn by stage.py
FULL_SCREEN = ("grid",) + STAGED
ICON_FONT = "CaskaydiaCove Nerd Font Propo"


# how each style arrives, and the keys its footer lists
ARRIVE = {"categories": "translateY(12px) scale(0.985)", "spotlight": "scale(0.96)", "grid": "scale(1.025)",
          "compact": "translateY(-18px)", "dock": "translateY(44px)", "orbit": "scale(0.6) rotate(-35deg)",
          "carousel": "translateY(40px) scale(1.06)", "terminal": "scale(1, 0.02)", "bubbles": "scale(0.82)"}
KEYS = {"categories": [("Enter", "open"), ("\u2190\u2192\u2191\u2193", "move"), ("Tab", "category"), ("Esc", "close")],
        "spotlight": [("Enter", "open"), ("\u2191\u2193", "move"), ("Esc", "close")],
        "grid": [("Enter", "open"), ("\u2190\u2192\u2191\u2193", "move"), ("Alt A-Z", "jump"), ("Esc", "close")],
        "compact": [("Enter", "open"), ("Alt 1-9", "pick"), ("Esc", "close")],
        "dock": [("\u2190\u2192", "move"), ("Enter", "open"), ("Type", "to search"), ("Esc", "close")],
        "orbit": [("\u2190\u2192", "spin"), ("Enter", "open"), ("Esc", "close")],
        "carousel": [("\u2190\u2192", "flip"), ("Enter", "open"), ("Esc", "close")],
        "terminal": [("[ENTER]", "run"), ("[\u2191\u2193]", "select"), ("[ESC]", "exit")],
        "bubbles": [("\u2190\u2192\u2191\u2193", "drift"), ("Enter", "open"), ("Esc", "close")]}
PLACEHOLDER = {"categories": "Search apps, work out a sum, > run a command, ? search the web",
               "spotlight": "Search, 12*7, > command, ? web", "grid": "Search the library", "compact": "open\u2026", "dock": "Search",
               "orbit": "Search\u2026", "carousel": "Search", "terminal": "", "bubbles": "Pop a bubble\u2026"}

LOOK = {"size": 100, "icon_size": 100, "transparency": 0, "dim": 35, "rounding": 22, "outline": True, "hints": True}


def settings() -> dict:
    """The Launcher page settings. --style NAME and --set key=value (what settings' Try it passes) override them."""
    store = Store()
    get = lambda key, fallback: store.get(BY_ID[key])[0] if key in BY_ID else fallback  # noqa: E731
    out = {"style": get("launcher.style", "categories"), "engine": get("launcher.search_engine", "duckduckgo"),
           "rank": get("launcher.rank_by_use", True), "terminal": get("hyprdots.terminal", "ghostty")}
    out.update({k: get(f"launcher.{k}", v) for k, v in LOOK.items()})
    for i, arg in enumerate(sys.argv[:-1]):
        value = sys.argv[i + 1]
        if arg == "--style" and value in STYLES:
            out["style"] = value
        elif arg == "--set" and "=" in value:
            key, _, raw = value.partition("=")
            if key in LOOK:
                out[key] = raw.lower() in ("1", "true", "yes") if isinstance(LOOK[key], bool) else int(float(raw))
    return out


def css(style: str, opts: dict) -> str:
    store = Store()
    o = design.theme_options(store)
    c = design.resolved(o)
    o = {**design.DEFAULTS, **o}
    solid = 1 - min(max(int(opts["transparency"]), 0), 90) / 100
    panel = design.alpha_rgba(c["base"], solid)
    shade = design.alpha_rgba(c["base"], min(solid, 0.95)) if style in FULL_SCREEN else f"rgba(0, 0, 0, {int(opts['dim']) / 100:g})"
    scale = int(opts["size"]) / 100
    px = lambda n: f"{max(1, round(n * scale))}px"  # noqa: E731
    rounding = int(opts["rounding"])
    inner = lambda n: f"{round(n * rounding / 22)}px"  # noqa: E731  (inner corners follow the outer ones)
    outline = design.alpha_rgba(c["accent"], 0.35) if opts["outline"] else "transparent"
    return f"""
window, window.background {{ background: transparent; }}
* {{ font-family: {design.font_list(o)}; color: {c['base_text']}; font-size: {px(14)}; }}
.backdrop {{ background: {shade}; }}
@keyframes arrive {{ from {{ opacity: 0; transform: {ARRIVE[style]}; }} to {{ opacity: 1; transform: none; }} }}
.surface {{
    background-color: {panel};
    background-image: radial-gradient(ellipse at top right, {design.alpha_rgba(c['accent'], 0.13)}, transparent 62%);
    border: 1px solid {outline};
    border-radius: {rounding}px;
    box-shadow: 0 18px 60px rgba(0, 0, 0, 0.5);
}}
.panel {{ animation: arrive 170ms cubic-bezier(0.2, 0.8, 0.2, 1); }}
.main {{ padding: 16px 18px 12px 18px; }}
entry.search, text.search {{
    min-height: {px(44)}; padding: 0 4px; font-size: {px(19)}; font-weight: 500;
    background: none; border: none; border-radius: 0px; box-shadow: none; outline: none;
}}
entry.search image {{ color: {c['accent']}; -gtk-icon-size: {px(20)}; margin-right: 6px; }}
.rule {{ min-height: 2px; background-image: linear-gradient(90deg, {c['accent']}, {design.alpha_rgba(c['accent'], 0.12)} 55%, transparent); }}
.mode {{
    color: {c['accent']}; background: {design.alpha_rgba(c['accent'], 0.15)}; border-radius: 99px; padding: 3px 11px;
    font-size: {px(11)}; font-weight: 700; letter-spacing: 1px;
}}
.item {{ border-radius: {inner(10)}; padding: 7px 12px; background: none; transition: background-color 110ms ease-out, box-shadow 110ms ease-out; }}
.item.tile {{ padding: 12px 6px; }}
.item:hover {{ background: {design.alpha_rgba(c['base_text'], 0.06)}; }}
.item.selected {{ background: {design.alpha_rgba(c['accent'], 0.14)}; box-shadow: inset 3px 0 0 {c['accent']}; }}
.item.tile.selected {{ box-shadow: inset 0 -3px 0 {c['accent']}; }}
.item image {{ transition: -gtk-icon-transform 130ms ease-out; }}
.item.tile.selected image {{ -gtk-icon-transform: scale(1.12); }}
.item.selected .title {{ color: {c['accent']}; }}
.title {{ font-weight: 600; }}
.subtitle {{ opacity: 0.6; font-size: {px(12)}; }}
.glyph {{ font-family: "{ICON_FONT}"; color: {c['accent']}; }}
.section {{ opacity: 0.55; font-size: {px(11)}; font-weight: 700; letter-spacing: 2px; margin: 6px 12px 10px 12px; }}
.sidebar {{ background: {design.alpha_rgba(c['base_text'], 0.045)}; border-right: 1px solid {design.alpha_rgba(c['base_text'], 0.08)}; padding: 14px 8px; }}
.cat {{ border-radius: {inner(8)}; padding: 8px 12px; transition: background-color 110ms ease-out; }}
.cat.active {{ background: {design.alpha_rgba(c['accent'], 0.14)}; box-shadow: inset 3px 0 0 {c['accent']}; }}
.cat.active label {{ color: {c['accent']}; font-weight: 700; }}
.count {{ opacity: 0.45; font-size: {px(11)}; }}
.action {{ opacity: 0.75; font-size: {px(12)}; }}
.key {{
    font-size: {px(10)}; padding: 0 5px; margin-left: 8px; border-radius: 5px;
    border: 1px solid {design.alpha_rgba(c['base_text'], 0.22)}; border-bottom-width: 2px;
}}
.hint {{ opacity: 0.5; font-size: {px(11)}; }}
.empty {{ opacity: 0.5; margin: 30px; }}
flowbox, flowboxchild, list, row {{ background: none; padding: 0; }}
""" + style_css(style, c, px, inner, rounding)


def style_css(style: str, c: dict, px, inner, rounding: int) -> str:
    """What makes each style its own, on top of the shared rules above. Spacing still scales with Size, corners with
    Corners, and every colour comes from the Theme page."""
    tint = design.alpha_rgba
    accent = c["accent"]
    if style == "spotlight":
        return f"""
.head.surface {{ border-radius: {round(rounding * 1.5)}px; padding: 6px 14px 6px 20px; }}
entry.search, text.search {{ font-size: {px(21)}; min-height: {px(52)}; }}
.main {{ padding: 8px; }}
.item {{ border-radius: {inner(12)}; padding: 8px 12px; }}
.item.selected {{ background: {tint(accent, 0.18)}; box-shadow: none; }}
.item.selected .title {{ color: {c['base_text']}; }}
.tail {{ opacity: 0; font-size: {px(15)}; transition: opacity 110ms ease-out; }}
.item.selected .tail {{ opacity: 0.75; color: {accent}; }}
.action {{ margin-left: 8px; }}
"""
    if style == "compact":
        return f"""
.panel.surface {{
    border-radius: 0 0 {rounding}px {rounding}px; border-top: 2px solid {accent}; background-image: none;
    box-shadow: 0 10px 28px rgba(0, 0, 0, 0.45);
}}
.main {{ padding: 8px 8px 8px 8px; }}
.prompt {{ margin-left: 6px; font-size: {px(18)}; font-weight: 700; }}
entry.search, text.search {{ min-height: {px(32)}; font-size: {px(14)}; }}
entry.search image:first-child {{ -gtk-icon-size: 1px; min-width: 0; margin: 0; opacity: 0; }}
.mode {{ background: none; padding: 0 6px; opacity: 0.7; font-size: {px(10)}; }}
.item {{ padding: 3px 8px; border-radius: {inner(6)}; }}
.tail {{ opacity: 0.4; font-size: {px(11)}; }}
.item.selected .tail {{ opacity: 0.9; color: {accent}; }}
.action {{ margin-left: 8px; }}
"""
    if style == "grid":
        stagger = "".join(f".in{n} {{ animation: tile-in 240ms cubic-bezier(0.2, 0.8, 0.2, 1) backwards; animation-delay: {n * 28}ms; }}\n" for n in range(8))
        return f"""
@keyframes tile-in {{ from {{ opacity: 0; transform: translateY(14px); }} to {{ opacity: 1; transform: none; }} }}
{stagger}
.main {{ padding: 36px 56px 18px 90px; }}
.heading {{ font-size: {px(34)}; font-weight: 800; }}
entry.search, text.search {{ min-height: {px(40)}; font-size: {px(15)}; }}
entry.search {{ background: {tint(c['base_text'], 0.07)}; border-radius: 99px; padding: 0 14px; }}
text.search {{ background: none; }}
.item.tile, .item.tile:hover, .item.tile.selected {{ background: none; box-shadow: none; padding: 12px 6px; }}
.item.tile image, .item.tile .glyph {{ padding: 12px; border-radius: {inner(22)}; transition: background-color 130ms ease-out, box-shadow 130ms ease-out; }}
.item.tile:hover image, .item.tile:hover .glyph {{ background: {tint(c['base_text'], 0.07)}; }}
.item.tile.selected image, .item.tile.selected .glyph {{ background: {tint(accent, 0.24)}; box-shadow: 0 0 22px {tint(accent, 0.4)}; -gtk-icon-transform: none; }}
flowbox {{ padding: 26px 18px; }}
.alphabet {{ margin-left: 8px; }}
.letter {{ min-height: 0; min-width: {px(24)}; padding: 1px 0; border-radius: 6px; }}
.letter label {{ font-size: {px(12)}; font-weight: 700; opacity: 0.5; }}
.letter:hover label {{ opacity: 1; }}
.letter.current {{ background: {tint(accent, 0.2)}; }}
.letter.current label {{ opacity: 1; color: {accent}; }}
"""
    if style == "dock":
        dot = f"radial-gradient(circle, {accent} 62%, transparent 68%)"
        return f"""
.head {{ opacity: 0; transition: opacity 120ms ease-out; padding: 2px 16px; }}
.head.surface {{ border-radius: {round(rounding * 1.5)}px; }}
.panel.typing .head {{ opacity: 1; }}
.main {{ padding: 8px 14px 8px 14px; }}
.action {{ opacity: 1; color: {accent}; font-size: {px(13)}; font-weight: 700; }}
.item.tile {{ padding: 16px 8px 13px 8px; }}
.item.tile:hover {{ background: none; }}
.item.tile.selected {{
    background-color: transparent; box-shadow: none; background-image: {dot};
    background-size: {px(6)} {px(6)}; background-position: center 94%; background-repeat: no-repeat;
}}
.item.tile.selected image {{ -gtk-icon-transform: scale(1.28) translateY(-5px); }}
"""
    if style == "orbit":
        return f"""
.main {{ padding: 20px 40px 16px 40px; }}
.ring {{ border: 1px dashed {tint(accent, 0.35)}; border-radius: 9999px; box-shadow: inset 0 0 90px {tint(accent, 0.08)}, 0 0 60px {tint(accent, 0.06)}; }}
.head {{ background: {tint(c['base'], 0.85)}; border: 1px solid {tint(accent, 0.45)}; border-radius: 99px; padding: 2px 14px; box-shadow: 0 0 40px {tint(accent, 0.18)}; }}
entry.search, text.search {{ font-size: {px(17)}; min-height: {px(40)}; }}
.action {{ color: {accent}; font-size: {px(22)}; font-weight: 800; opacity: 1; margin-top: 6px; }}
.item.tile, .item.tile:hover, .item.tile.selected {{ background: none; box-shadow: none; padding: 6px; }}
.item.tile.selected image {{ -gtk-icon-transform: none; -gtk-icon-shadow: 0 0 18px {accent}; }}
"""
    if style == "carousel":
        return f"""
.main {{ padding: 30px 40px 18px 40px; background-image: linear-gradient(180deg, transparent 58%, {tint(accent, 0.07)} 74%, transparent 100%); }}
entry.search {{ background: {tint(c['base_text'], 0.07)}; border-radius: 99px; padding: 0 14px; }}
text.search {{ background: none; }}
.item.tile {{
    background-color: {tint(c['base'], 0.96)}; background-image: linear-gradient(160deg, {tint(c['base_text'], 0.09)}, transparent 55%);
    border: 1px solid {tint(c['base_text'], 0.12)}; border-radius: {inner(20)}; padding: 26px 18px 18px 18px;
    box-shadow: 0 24px 50px rgba(0, 0, 0, 0.55);
}}
.item.tile:hover {{ background-color: {tint(c['base'], 0.96)}; }}
.item.tile.selected {{ border-color: {accent}; box-shadow: 0 0 0 1px {accent}, 0 28px 60px rgba(0, 0, 0, 0.6), 0 0 50px {tint(accent, 0.3)}; }}
.item.tile.selected image {{ -gtk-icon-transform: none; }}
.item.tile .title {{ font-size: {px(15)}; }}
.action {{ color: {accent}; font-size: {px(26)}; font-weight: 800; opacity: 1; }}
"""
    if style == "terminal":
        mono = '"CaskaydiaCove Nerd Font Mono", "JetBrains Mono", monospace'
        glow = tint(accent, 0.75)
        return f"""
.panel.surface {{
    background-color: {c['base']};
    background-image: repeating-linear-gradient(180deg, rgba(0, 0, 0, 0.3) 0px, rgba(0, 0, 0, 0.3) 1px, transparent 1px, transparent 3px),
                      radial-gradient(ellipse at center, {tint(accent, 0.09)}, transparent 50%, rgba(0, 0, 0, 0.65));
    border: 2px solid {tint(accent, 0.45)}; border-radius: {rounding + 8}px;
    box-shadow: 0 0 0 7px rgba(0, 0, 0, 0.7), 0 0 0 8px {tint(accent, 0.25)}, 0 0 80px {tint(accent, 0.2)}, 0 24px 80px rgba(0, 0, 0, 0.7);
}}
.panel.terminal label, .panel.terminal text, .panel.terminal entry {{ font-family: {mono}; color: {accent}; text-shadow: 0 0 6px {glow}; }}
.main {{ padding: 18px 24px 14px 24px; }}
.boot {{ opacity: 0.7; font-size: {px(12)}; }}
.prompt {{ font-weight: 700; }}
entry.search, text.search {{ min-height: {px(28)}; font-size: {px(15)}; caret-color: {accent}; }}
entry.search image {{ -gtk-icon-size: 1px; min-width: 0; margin: 0; opacity: 0; }}
.mode {{ background: none; padding: 0; letter-spacing: 0; }}
.item {{ padding: 1px 6px; border-radius: 0; transition: none; }}
.item:hover {{ background: {tint(accent, 0.12)}; }}
.item.selected {{ background: {accent}; box-shadow: 0 0 16px {glow}; }}
.panel.terminal .item.selected label {{ color: {c['base']}; text-shadow: none; }}
.lead {{ opacity: 0; }}
.item.selected .lead {{ opacity: 1; }}
.subtitle {{ opacity: 0.55; font-size: {px(14)}; }}
.key {{ border: none; padding: 0; margin-left: 14px; font-size: {px(12)}; }}
.hint {{ font-size: {px(12)}; }}
.action {{ font-size: {px(12)}; }}
"""
    if style == "bubbles":
        return f"""
.main {{ padding: 30px 40px 18px 40px; }}
entry.search {{ background: {tint(c['base_text'], 0.08)}; border-radius: 99px; padding: 0 16px; }}
text.search {{ background: none; }}
.item.tile {{
    padding: 12px; border-radius: 9999px; transition: border-color 150ms ease-out, box-shadow 150ms ease-out;
    background-color: {tint(c['base'], 0.55)};
    background-image: radial-gradient(circle at 32% 28%, {tint(c['base_text'], 0.22)}, {tint(c['base_text'], 0.03)} 45%, {tint(accent, 0.14)});
    border: 1px solid {tint(c['base_text'], 0.16)}; box-shadow: inset 0 0 20px {tint(accent, 0.16)};
}}
.item.tile:hover {{ border-color: {tint(accent, 0.6)}; background-color: {tint(c['base'], 0.55)}; }}
.item.tile.selected {{ border-color: {accent}; box-shadow: 0 0 34px {tint(accent, 0.6)}, inset 0 0 22px {tint(accent, 0.35)}; }}
.item.tile.selected image {{ -gtk-icon-transform: none; }}
.burst {{ border: 3px solid {accent}; border-radius: 9999px; box-shadow: 0 0 24px {tint(accent, 0.6)}; }}
.droplet {{ min-width: {px(9)}; min-height: {px(9)}; border-radius: 9999px; background: {accent}; box-shadow: 0 0 10px {accent}; }}
.caption {{ color: {accent}; font-weight: 800; font-size: {px(15)}; background: {tint(c['base'], 0.85)}; border-radius: 99px; padding: 3px 12px; }}
"""
    return f"""
.head {{ padding: 0; }}
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


def row_widget(Gtk, Pango, result, size: int, dense: bool = False, tail: str = ""):
    box = Gtk.Box(spacing=8 if dense else 12, css_classes=["item"])
    box.append(icon_for(Gtk, result, size))
    text = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, valign=Gtk.Align.CENTER, hexpand=True)
    text.append(Gtk.Label(label=result.title, xalign=0, css_classes=["title"], ellipsize=Pango.EllipsizeMode.END))
    if result.subtitle and not dense:
        text.append(Gtk.Label(label=result.subtitle, xalign=0, css_classes=["subtitle"], ellipsize=Pango.EllipsizeMode.END))
    box.append(text)
    if tail:
        box.append(Gtk.Label(label=tail, css_classes=["tail"]))
    return box


def terminal_row(Gtk, Pango, result):
    """One line of text, as a shell would list it: a marker, the name in a column, then what it is."""
    box = Gtk.Box(spacing=8, css_classes=["item"])
    box.append(Gtk.Label(label=">", css_classes=["lead"]))
    box.append(Gtk.Label(label=result.title.lower().replace(" ", "-"), xalign=0, width_chars=26, max_width_chars=26,
                         css_classes=["title"], ellipsize=Pango.EllipsizeMode.END))
    box.append(Gtk.Label(label=result.subtitle or result.kind, xalign=0, hexpand=True, css_classes=["subtitle"],
                         ellipsize=Pango.EllipsizeMode.END))
    return box


def tile_widget(Gtk, Pango, result, size: int, width: int, labelled: bool = True):
    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8, css_classes=["item", "tile"], width_request=width)
    icon = icon_for(Gtk, result, size)
    icon.set_halign(Gtk.Align.CENTER)
    box.append(icon)
    if labelled:
        box.append(Gtk.Label(label=result.title, css_classes=["title"], ellipsize=Pango.EllipsizeMode.END,
                             max_width_chars=14, justify=Gtk.Justification.CENTER))
    return box


# ---- the launcher -----------------------------------------------------------------------------------------------------
def build(app, Gtk, Gdk, GLib, Pango, Gtk4LayerShell):
    opts = settings()
    style = opts["style"] if opts["style"] in STYLES else "categories"
    apps = search.installed_apps()
    usage = search.load_usage() if opts["rank"] else {}
    state = {"results": [], "index": 0, "category": "All apps", "armed": None, "widgets": [], "query": None,
             "pointer": None, "pointer_live": False, "revealed": False, "opened": False}

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
                            placeholder_text=PLACEHOLDER[style])

    # where the panel sits, how big it is, and what kind of view it uses
    layout = {
        "spotlight": dict(halign=Gtk.Align.CENTER, valign=Gtk.Align.START, width=640, margin_top=0.22, view="list", icon=32, rows=8, row=26,
                          detached=True, reveal=True),
        "compact": dict(halign=Gtk.Align.START, valign=Gtk.Align.START, width=380, margin_top=56, margin_start=12, view="list", icon=20, rows=9, row=12,
                        dense=True),
        "grid": dict(halign=Gtk.Align.FILL, valign=Gtk.Align.FILL, width=-1, view="grid", icon=72, tile=170),
        "categories": dict(halign=Gtk.Align.CENTER, valign=Gtk.Align.CENTER, width=1100, height=0.72, view="grid", icon=52, tile=128),
        "dock": dict(halign=Gtk.Align.CENTER, valign=Gtk.Align.END, width=-1, max_width=0.86, margin_bottom=18, view="row", icon=56, tile=84,
                     detached=True, icons_only=True),
        "orbit": dict(halign=Gtk.Align.FILL, valign=Gtk.Align.FILL, width=-1, view="stage", icon=58, tile=-1, icons_only=True,
                      centre=True, click_to_focus=True),
        "carousel": dict(halign=Gtk.Align.FILL, valign=Gtk.Align.FILL, width=-1, view="stage", icon=128, tile=210, click_to_focus=True),
        "terminal": dict(halign=Gtk.Align.CENTER, valign=Gtk.Align.CENTER, width=820, view="list", icon=0, rows=15, row=24),
        "bubbles": dict(halign=Gtk.Align.FILL, valign=Gtk.Align.FILL, width=-1, view="stage", icon=46, tile=-1, icons_only=True),
    }[style]
    scale, icons = int(opts["size"]) / 100, int(opts["icon_size"]) / 100
    for key in ("width", "tile"):  # fractions of the screen stay as they are
        if isinstance(layout.get(key), int) and layout[key] > 0:
            layout[key] = round(layout[key] * scale * (icons if key == "tile" else 1))
    if isinstance(layout.get("height"), float):
        layout["height"] = min(0.92, layout["height"] * scale)
    layout["icon"] = round(layout["icon"] * scale * icons)

    # Detached styles (spotlight, dock) keep the search apart from the card of results. The rest are one piece.
    detached = layout.get("detached", False)
    panel = Gtk.Box(orientation=Gtk.Orientation.VERTICAL if detached else Gtk.Orientation.HORIZONTAL, spacing=10 if detached else 0,
                    css_classes=["panel", style] + ([] if detached or style in FULL_SCREEN else ["surface"]),
                    overflow=Gtk.Overflow.VISIBLE if detached else Gtk.Overflow.HIDDEN,
                    halign=layout["halign"], valign=layout["valign"], hexpand=True, vexpand=True)
    backdrop.append(panel)
    sidebar = None
    if style == "categories":
        sidebar = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2, css_classes=["sidebar"], width_request=round(210 * scale))
        panel.append(sidebar)
    main = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12 if style in ("categories", "grid") + STAGED else 6,
                   css_classes=["main"] + (["surface"] if detached else []), hexpand=True, vexpand=True)

    header = Gtk.Box(spacing=10, css_classes=["head"] + (["surface"] if detached else []))
    heading = Gtk.Label(css_classes=["heading"], xalign=0, hexpand=True) if style == "grid" else None
    if heading:
        header.append(heading)
    if style == "compact":
        header.append(Gtk.Label(label="\U000f0142", css_classes=["glyph", "prompt"]))
    if style == "terminal":
        header.append(Gtk.Label(label=f"{os.environ.get('USER', 'you')}@{socket.gethostname()}:~$ launch", css_classes=["prompt"]))
    header.append(entry)
    mode = Gtk.Label(css_classes=["mode"], valign=Gtk.Align.CENTER)  # says what Enter will do with what you typed
    header.append(mode)
    if style in ("grid", "dock", "carousel", "bubbles", "orbit"):
        entry.set_hexpand(False)
        entry.set_size_request(round((300 if style == "orbit" else 420) * scale), -1)
    if style in ("dock", "carousel", "bubbles", "orbit"):
        header.set_halign(Gtk.Align.CENTER)
    boot = None
    if detached:
        panel.append(header)
        panel.append(main)
    else:
        panel.append(main)
        if style == "terminal":  # a few lines of start-up chatter, typed out on open
            boot = Gtk.Label(css_classes=["boot"], xalign=0)
            main.append(boot)
        if not layout.get("centre"):
            main.append(header)
    if style == "categories":
        main.append(Gtk.Box(css_classes=["rule"]))

    # what Enter does: in the footer, or as the name above the icons on the dock, which has no labels of its own
    centred = style in ("dock", "orbit", "carousel")
    action = Gtk.Label(css_classes=["action"], xalign=0.5 if centred else 0, hexpand=True, ellipsize=Pango.EllipsizeMode.END)
    if style == "dock":
        main.append(action)
    body = Gtk.Box(spacing=12, vexpand=True)
    main.append(body)
    if style == "carousel":
        main.append(action)

    stage = None
    if layout["view"] == "stage":
        import gi
        gi.require_version("Gsk", "4.0")
        gi.require_version("Graphene", "1.0")
        from gi.repository import Graphene, Gsk
        import stage as staging
        stage = staging.Stage(Gtk, Gsk, Graphene, style)
        view, scroller = stage.fixed, stage.widget
    elif layout["view"] == "list":
        view = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=1 if style == "terminal" else 2)
    elif layout["view"] == "row":
        view = Gtk.Box(spacing=6, halign=Gtk.Align.CENTER)
    else:
        view = Gtk.FlowBox(selection_mode=Gtk.SelectionMode.NONE, homogeneous=True, valign=Gtk.Align.START,
                           min_children_per_line=3, max_children_per_line=12, column_spacing=6, row_spacing=6)
    if stage is None:
        scroller = Gtk.ScrolledWindow(child=view, hexpand=True, vexpand=True,
                                      hscrollbar_policy=Gtk.PolicyType.AUTOMATIC if layout["view"] == "row" else Gtk.PolicyType.NEVER,
                                      vscrollbar_policy=Gtk.PolicyType.NEVER if layout["view"] == "row" else Gtk.PolicyType.AUTOMATIC,
                                      propagate_natural_height=layout["view"] != "grid", propagate_natural_width=layout["view"] == "row")
    if layout.get("centre"):  # orbit: the search and the picked name sit in the middle of the ring
        overlay = Gtk.Overlay(child=scroller, hexpand=True, vexpand=True)
        middle = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4, halign=Gtk.Align.CENTER, valign=Gtk.Align.CENTER)
        middle.append(header)
        middle.append(action)
        overlay.add_overlay(middle)
        body.append(overlay)
    else:
        body.append(scroller)
    alphabet, letters = None, {}
    if style == "grid":
        alphabet = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, css_classes=["alphabet"], valign=Gtk.Align.CENTER)
        for letter in sorted({search.initial(a.title) for a in apps}):
            button = Gtk.Button(label=letter, css_classes=["flat", "letter"], focusable=False, focus_on_click=False)
            button.connect("clicked", lambda _b, letter=letter: jump(letter))
            alphabet.append(button)
            letters[letter] = button
        body.append(alphabet)

    footer = Gtk.Box(spacing=5, halign=Gtk.Align.CENTER if centred else Gtk.Align.FILL)
    if not centred:
        footer.append(action)
    for key, word in KEYS[style]:
        footer.append(Gtk.Label(label=key, css_classes=["key"]))
        footer.append(Gtk.Label(label=word, css_classes=["hint"]))
    main.append(footer)
    footer.set_visible(bool(opts["hints"]))

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
            scroller.set_max_content_height(layout["rows"] * (layout["icon"] + layout["row"]))
        if "max_width" in layout:
            scroller.set_max_content_width(int(g.width * layout["max_width"]))
    win.connect("realize", size_panel)

    # ---- categories sidebar ----
    def categories():
        present = {a.category for a in apps}
        names = (["Frequent"] if search.frequent(apps, usage) else []) + ["All apps"]
        names += [n for n, _ in search.BUCKETS if n in present] + (["Other"] if "Other" in present else [])
        return names

    def apps_in(category):
        if category == "Frequent":
            return search.frequent(apps, usage, 24)
        return apps if category == "All apps" else [a for a in apps if a.category == category]

    def draw_sidebar():
        if sidebar is None:
            return
        child = sidebar.get_first_child()
        while child:
            sidebar.remove(child)
            child = sidebar.get_first_child()
        sidebar.append(Gtk.Label(label="APPS", xalign=0, css_classes=["section"]))
        for name in categories():
            active = name == state["category"] and not entry.get_text().strip()
            button = Gtk.Button(css_classes=["flat", "cat"] + (["active"] if active else []), focusable=False, focus_on_click=False)
            inner = Gtk.Box(spacing=10)
            inner.append(Gtk.Label(label=search.CATEGORY_ICONS.get(name, ""), css_classes=["glyph"]))
            inner.append(Gtk.Label(label=name, xalign=0, hexpand=True))
            inner.append(Gtk.Label(label=str(len(apps_in(name))), css_classes=["count"]))
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
            return apps_in(state["category"])
        if style in ("grid", "orbit", "carousel", "terminal"):
            return apps
        if style == "bubbles":  # most used first, so they float in the middle
            return sorted(apps, key=lambda a: -search.popularity(a.app_id, usage))
        recent = search.frequent(apps, usage, {"spotlight": 8, "compact": 9, "dock": 16}[style])
        return recent or apps[:{"spotlight": 8, "compact": 9, "dock": 16}[style]]

    def refresh(*_):
        state["armed"] = None
        state["query"] = entry.get_text()
        state["results"] = results_for(state["query"])
        state["index"] = 0
        state["pointer_live"] = False
        typed = bool(state["query"].strip())
        mode.set_label(f"[{search.mode_label(state['query'])}]" if style == "terminal" else search.mode_label(state["query"]))
        (panel.add_css_class if typed else panel.remove_css_class)("typing")
        if layout.get("reveal"):
            main.set_visible(typed or state["revealed"])
        if alphabet:
            alphabet.set_visible(not typed)
        if heading:
            count = len(state["results"])
            heading.set_label(f"{count} result{'' if count == 1 else 's'}" if typed else "Library")
        child = None if stage else view.get_first_child()  # the stage clears its own
        while child:
            view.remove(child)
            child = view.get_first_child()
        state["widgets"] = []
        if not state["results"] and stage is None:
            view.append(Gtk.Label(label="Nothing matches", css_classes=["empty"], hexpand=True))
        top = max((search.popularity(r.app_id, usage) for r in state["results"]), default=0) if style == "bubbles" else 0
        for i, r in enumerate(state["results"][:64 if style == "bubbles" else 200]):
            if style == "terminal":
                w = terminal_row(Gtk, Pango, r)
            elif style == "bubbles":  # the more you open it, the bigger it floats
                size = round(layout["icon"] * (1 + 0.7 * (search.popularity(r.app_id, usage) / top if top else 0)))
                w = tile_widget(Gtk, Pango, r, size, size + 24, labelled=False)
            elif layout["view"] == "list":
                tail = str(i + 1) if style == "compact" and i < 9 else "\u21b5" if style == "spotlight" else ""
                w = row_widget(Gtk, Pango, r, layout["icon"], dense=layout.get("dense", False), tail=tail)
            else:
                w = tile_widget(Gtk, Pango, r, layout["icon"], layout["tile"], labelled=not layout.get("icons_only"))
                if style == "grid" and not state["opened"] and i < 48:  # the first screenful comes in row by row
                    w.add_css_class(f"in{i // 6}")
            click = Gtk.GestureClick()
            if layout.get("click_to_focus"):  # spinning styles: the first click turns it to you, the next opens it
                click.connect("released", lambda _g, _n, _x, _y, i=i: activate() if i == state["index"] else select(i))
            else:
                click.connect("released", lambda _g, _n, _x, _y, i=i: (select(i), activate()))
            w.add_controller(click)
            if not layout.get("click_to_focus"):  # hovering a ring that turns under the pointer would chase it round
                motion = Gtk.EventControllerMotion()
                motion.connect("motion", lambda _c, _x, _y, i=i: state["pointer_live"] and i != state["index"] and select(i, scroll=False))
                w.add_controller(motion)
            if stage is None:
                view.append(w)
            state["widgets"].append(w)
        if stage:
            stage.set_items(state["widgets"])
            if not state["widgets"]:
                stage.focus(0, "Nothing matches")
                action.set_label("Nothing matches")
        state["opened"] = True
        draw_sidebar()
        select(0)

    def sync():
        """Typing is debounced, so a quick arrow or Enter must not act on the results of the previous letter."""
        if entry.get_text() != state["query"]:
            refresh()

    def select(i, scroll=True):
        widgets = state["widgets"]
        if not widgets:
            action.set_label("")
            return
        i = max(0, min(i, len(widgets) - 1))
        widgets[state["index"]].remove_css_class("selected") if state["index"] < len(widgets) else None
        state["index"] = i
        widgets[i].add_css_class("selected")
        action.set_label(search.action_text(state["results"][i]))
        if stage:
            stage.focus(i, state["results"][i].title)
            return
        if letters:
            current = search.initial(state["results"][i].title)
            for letter, button in letters.items():
                (button.add_css_class if letter == current else button.remove_css_class)("current")
        if scroll:
            GLib.idle_add(scroll_to, widgets[i])

    def scroll_to(widget):
        ok, rect = widget.compute_bounds(scroller.get_child())  # the viewport, so view's own padding is counted
        if not ok:
            return False
        vertical = layout["view"] != "row"
        adj = scroller.get_vadjustment() if vertical else scroller.get_hadjustment()
        start, length = (rect.origin.y, rect.size.height) if vertical else (rect.origin.x, rect.size.width)
        start += adj.get_value()  # the viewport's coordinates move as it scrolls
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

    def hidden():
        """Spotlight starts as just the search pill. The first arrow or Enter opens its card."""
        return layout.get("reveal") and not main.get_visible()

    def reveal():
        state["revealed"] = True
        main.set_visible(True)

    def jump(letter):
        if entry.get_text():
            entry.set_text("")
        sync()
        found = search.first_with_initial(state["results"], letter)
        if found is not None:
            state["pointer_live"] = False
            select(found)

    def activate():
        sync()
        if hidden():
            reveal()
            return
        if not state["results"]:
            return
        r = state["results"][state["index"]]
        if r.kind == "power" and r.confirm and state["armed"] != r.value:
            state["armed"] = r.value  # first Enter: ask, by showing it on the item itself
            title = state["widgets"][state["index"]]
            for label in _labels(title):
                if label.has_css_class("subtitle") or label.has_css_class("title"):
                    label.set_label(f"Press Enter again to {r.title.lower()}") if label.has_css_class("title") else None
            action.set_label(f"Press Enter again to {r.title.lower()}")
            return
        if style == "bubbles":  # pop it first; the app opens once the burst has gone
            if not state.get("popping"):
                state["popping"] = True
                stage.pop(state["index"], lambda: (run(r, opts), app.quit()))
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

    entry.connect("search-changed", lambda _e: sync())
    entry.connect("activate", lambda _e: activate())

    arrows = {Gdk.KEY_Left: "left", Gdk.KEY_KP_Left: "left", Gdk.KEY_Right: "right", Gdk.KEY_KP_Right: "right",
              Gdk.KEY_Up: "up", Gdk.KEY_KP_Up: "up", Gdk.KEY_Down: "down", Gdk.KEY_KP_Down: "down"}

    def on_arrow(direction, mods):
        """True when the arrow moved through the results, False to leave it to the search box's text cursor."""
        if mods & (Gdk.ModifierType.CONTROL_MASK | Gdk.ModifierType.SHIFT_MASK | Gdk.ModifierType.ALT_MASK):
            return False  # word jumps and selecting text
        sync()
        if hidden():
            reveal()
            return True
        count = len(state["widgets"])
        if direction in ("left", "right"):
            # one result (a > command, a ? search): nothing to walk, so edit. A list is walked with up and down, so
            # sideways only moves it when there is no text for the cursor to move through.
            if count < 2 or (layout["view"] == "list" and entry.get_text()):
                return False
        state["pointer_live"] = False
        if style == "bubbles":
            select(stage.step(state["index"], direction))
        else:
            select(search.step(state["index"], count, columns(), direction))
        return True

    def on_key(_ctl, keyval, _code, mods):
        if keyval == Gdk.KEY_Escape:
            if entry.get_text() or state["revealed"]:
                state["revealed"] = False
                entry.set_text("")
                state["query"] = None  # so spotlight's card folds away even when the text was already empty
                sync()
            else:
                app.quit()
            return True
        if mods & Gdk.ModifierType.ALT_MASK:
            code = Gdk.keyval_to_unicode(keyval)
            ch = chr(code).lower() if code else ""
            if style == "compact" and ch and ch in "123456789":
                sync()
                if int(ch) <= len(state["widgets"]):
                    select(int(ch) - 1)
                    activate()
                return True
            if style == "grid" and ch.isascii() and ch.isalpha():
                jump(ch.upper())
                return True
        if keyval in arrows:
            return on_arrow(arrows[keyval], mods)
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

    def pointer_moved(_ctl, x, y):  # GTK also reports the pointer when things slide under a resting mouse: ignore those
        if state["pointer"] not in (None, (x, y)):
            state["pointer_live"] = True
        state["pointer"] = (x, y)
    pointer = Gtk.EventControllerMotion(propagation_phase=Gtk.PropagationPhase.CAPTURE)
    pointer.connect("motion", pointer_moved)
    win.add_controller(pointer)

    click = Gtk.GestureClick()  # a click outside the panel closes the launcher
    click.connect("pressed", lambda _g, _n, x, y: backdrop.pick(x, y, Gtk.PickFlags.DEFAULT) is backdrop and app.quit())
    backdrop.add_controller(click)

    provider = Gtk.CssProvider()
    provider.load_from_string(css(style, opts))
    Gtk.StyleContext.add_provider_for_display(Gdk.Display.get_default(), provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
    if usage and style == "categories" and not entry.get_text():
        state["category"] = "All apps"
    refresh()
    if boot is not None:
        text = (f"HYPRDOTS LAUNCHER v1.0   {len(apps)} programs found\n"
                "type a name, 12*7 for sums, > for a shell, ? for the web")
        typed = {"n": 0}

        def type_on():
            typed["n"] += 3
            boot.set_label(text[:typed["n"]] + ("\u2588" if typed["n"] < len(text) else ""))
            return typed["n"] < len(text)
        GLib.timeout_add(12, type_on)
    win.present()
    entry.grab_focus()
    return win


def run(r, opts) -> None:
    """Does what the chosen result is for, detached from the launcher."""
    # launcher.sh preloads gtk4-layer-shell for this window only; apps must not inherit it (Electron apps such as
    # Vesktop crash on start with it loaded)
    env = dict(os.environ)
    preload = ":".join(p for p in env.get("LD_PRELOAD", "").split(":") if p and "gtk4-layer-shell" not in p)
    if preload:
        env["LD_PRELOAD"] = preload
    else:
        env.pop("LD_PRELOAD", None)

    def spawn(cmd):
        subprocess.Popen(cmd, start_new_session=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         stdin=subprocess.DEVNULL, env=env)
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
