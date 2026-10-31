"""The desktop's shared look (Theme page): colour roles picked from the wallpaper's wallust palette, and the font.

Apps (GTK) take the large panel colours and the accent too (theme_parts.write_gtk).

A role names a palette slot (color0-color15, foreground, background), not a fixed colour, so everything keeps following
the wallpaper. The bar is the first part of the desktop built on these roles; others are meant to follow.

The bar reads them from ~/.config/waybar/theme.css (git-ignored). theme.default.css in the repo is render_waybar() of
the defaults; waybar/launch.sh copies it into place when theme.css is missing, because GTK refuses the whole style
sheet if an @import is missing."""

from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

PALETTE = [f"color{i}" for i in range(16)] + ["foreground", "background"]

# key, label, what it colours, default slot
ROLES = [
    ("base", "Large panels", "Behind the notification centre, launchers and pickers, the cheatsheet and settings windows.",
     "background"),
    ("base_text", "Text on large panels", "Text and icons on those large panels.", "foreground"),
    ("surface", "Bar panels and cards", "The bar's panels, notification cards and buttons.", "color2"),
    ("surface_alt", "Tray panel", "The panel behind the tray icons.", "color3"),
    ("text", "Text on bar panels", "Clock, icons and labels on the bar and on cards.", "color12"),
    ("accent", "Accent", "The workspace you are on, the focused window's border, selections and highlights.", "color10"),
    ("secondary", "Workspaces", "Workspaces that have windows on them.", "color6"),
    ("muted", "Muted", "Empty workspaces and the borders of windows you are not using.", "color4"),
    ("icons", "Shortcut icons", "The settings, keybinds, drive and wallpaper buttons in the drawer.", "color15"),
    ("attention", "Attention", "Unread and urgent notifications.", "color14"),
]
DEFAULTS = {**{f"role_{k}": slot for k, _l, _h, slot in ROLES}, "surface_opacity": 80, "base_opacity": 90,
            "bar_font": "CaskaydiaCove Nerd Font", "bar_font_size": 15, "bar_style": "islands",
            "gtk_colours": True, "gtk_theme": "Adwaita", "app_font": "Adwaita Sans", "app_font_size": 11, "icons": "Adwaita",
            "cursor": "Adwaita", "cursor_size": 24}
STYLES = (("islands", "Islands"), ("solid", "Solid strip"), ("floating", "Floating bar"), ("bubbles", "Bubbles"),
          ("minimal", "Minimal"))
SHADOW = "0px 0px 2px rgba(0, 0, 0, 0.6)"


def style_css(style: str) -> str:
    """The bar's shape: what the panels behind the modules look like. waybar tags the bar window .top or .bottom."""
    zones = (".modules-left", ".modules-center", ".modules-right")
    bare = ", ".join(zones) + " {\n    padding: 0px 4px;\n    margin: 0px;\n    background: none;\n    border-radius: 0px;\n    box-shadow: none;\n}\n"
    if style == "solid":
        return ("window#waybar {\n    all: unset;\n    background: @theme_surface_fill;\n}\n" + bare.replace("0px 4px", "4px 6px"))
    if style == "floating":
        return ("window#waybar {\n    all: unset;\n}\n"
                "window#waybar > box {\n    margin: 6px 10px 0px 10px;\n    padding: 3px 6px;\n    border-radius: 16px;\n"
                "    background: @theme_surface_fill;\n    box-shadow: 0px 2px 6px rgba(0, 0, 0, 0.45);\n}\n"
                "window#waybar.bottom > box {\n    margin: 0px 10px 6px 10px;\n}\n" + bare)
    if style == "bubbles":
        kids = ", ".join(f"{z} > widget > *" for z in zones)
        return ("window#waybar {\n    all: unset;\n}\n" + bare.replace("margin: 0px;", "margin: 5px 0px;")
                + f"{kids} {{\n    background: @theme_surface_fill;\n    border-radius: 99px;\n    margin: 0px 3px;\n"
                  f"    padding-left: 8px;\n    padding-right: 8px;\n    box-shadow: {SHADOW};\n}}\n")
    if style == "minimal":
        return ("window#waybar {\n    all: unset;\n}\n" + bare.replace("margin: 0px;", "margin: 5px 0px;")
                + "* {\n    text-shadow: 0px 1px 3px rgba(0, 0, 0, 0.75);\n}\n")
    # islands: three rounded panels (the original look)
    out = "window#waybar {\n    all: unset;\n}\n"
    for zone, radius in ((".modules-center", 20), (".modules-left", 10), (".modules-right", 10)):
        out += (f"{zone} {{\n    padding: 5px;\n    margin: 5px 0 5px 0;\n    border-radius: {radius}px;\n"
                f"    background: @theme_surface_fill;\n    box-shadow: {SHADOW};\n}}\n")
    return out
ICON_FALLBACK = "CaskaydiaCove Nerd Font"  # always listed after your font, so bar icons still draw
WAYBAR_COLORS = Path.home() / ".config/waybar/colors/colors.css"


def palette() -> dict[str, str]:
    """Slot -> #hex of the current wallpaper's palette (from wallust's Waybar colours), for the swatches."""
    try:
        text = WAYBAR_COLORS.read_text(encoding="utf-8")
    except OSError:
        return {}
    found = dict(re.findall(r"@define-color\s+([\w-]+)\s+(#[0-9a-fA-F]{6})", text))
    return {slot: found[slot] for slot in PALETTE if slot in found}


def fonts() -> list[str]:
    """Installed font families, Nerd Fonts (which include the bar's icons) first."""
    try:
        out = subprocess.run(["fc-list", ":", "family"], capture_output=True, text=True, timeout=10).stdout
    except (OSError, subprocess.SubprocessError):
        return []
    names = sorted({n.strip() for line in out.splitlines() for n in line.split(",")[:1] if n.strip()}, key=str.lower)
    return [n for n in names if "Nerd Font" in n] + [n for n in names if "Nerd Font" not in n]


def empty_zones() -> list[str]:
    """Parts of the bar (modules-left/-center/-right) your layout leaves empty: they are hidden, or they would show as
    a small blank panel."""
    try:
        from . import barlayout
        layout = barlayout.read_layout(barlayout.read_config())
        return [z for z in barlayout.ZONES if not layout[z]]
    except (OSError, ValueError):
        return []


def render_waybar(o: dict, empty: list[str] | None = None) -> str:
    o = {**DEFAULTS, **o}
    empty = empty_zones() if empty is None else empty
    lines = ["/* The bar's colours and font, made by hypr-settings from the Theme page. Each role points at a slot of\n"
             "   wallust's palette (colors/colors.css), so the bar still follows your wallpaper. Do not edit by hand. */\n\n"]
    for key, _label, _help, _slot in ROLES:
        lines.append(f"@define-color theme_{key} @{o[f'role_{key}']};\n")
    lines.append(f"@define-color theme_surface_fill alpha(@{o['role_surface']}, {int(o['surface_opacity']) / 100:g});\n\n")
    font = str(o["bar_font"]).replace('"', "")
    fallback = "" if font == ICON_FALLBACK else f', "{ICON_FALLBACK}"'
    lines.append(f'* {{\n    font-family: "{font}"{fallback};\n    font-size: {int(o["bar_font_size"])}px;\n}}\n')
    lines.append(f"\n/* Bar style: {dict(STYLES).get(o['bar_style'], o['bar_style'])} */\n" + style_css(o["bar_style"]))
    if empty:
        lines.append("\n/* Empty in your layout, so not drawn */\n" + ", ".join("." + z for z in empty)
                     + " {\n    background: none;\n    box-shadow: none;\n    padding: 0px;\n    margin: 0px;\n}\n")
    return "".join(lines)


def theme_options(store) -> dict:
    from .schema import SETTINGS
    return {s.key: store.get(s)[0] for s in SETTINGS if s.section == "theme"}


def write_bar_theme(store) -> None:
    """Writes theme.css from the Theme page settings and the current layout, then has the bar re-read its style."""
    write(waybar_theme_path(), render_waybar(theme_options(store)))
    reload_bar()


def waybar_theme_path() -> Path:
    return Path.home() / ".config/waybar/theme.css"


def write(path: Path, text: str) -> None:
    tmp = path.with_name(path.name + f".{os.getpid()}.tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def reload_bar() -> None:
    """Makes the bar re-read its style without restarting. Its config has reload_style_on_change, which watches
    style.css (not the files it imports), so writing style.css back unchanged is enough. A restart (SIGUSR2) would
    recreate every module, and could take down apps the bar started, such as this settings window."""
    style = Path.home() / ".config/waybar/style.css"
    try:
        style.write_text(style.read_text(encoding="utf-8"), encoding="utf-8")
    except OSError:
        pass


# ---- the rest of the desktop ----------------------------------------------------------------------------------------
def resolved(o: dict) -> dict[str, str]:
    """Role -> #hex for parts that need real colours rather than palette names (they are rewritten whenever the
    wallpaper changes, by refresh_all from wallust.sh). Missing palette entries fall back to a calm grey."""
    o = {**DEFAULTS, **o}
    pal = palette()
    return {key: pal.get(o[f"role_{key}"], "#888888") for key, *_ in ROLES}


def alpha_rgba(hex_colour: str, a: float) -> str:
    r, g, b = (round(c * 255) for c in rgb(hex_colour))
    return f"rgba({r}, {g}, {b}, {a:g})"


def rgb(hex_colour: str) -> tuple:
    return tuple(int(hex_colour[i:i + 2], 16) / 255 for i in (1, 3, 5))


def font_of(o: dict) -> str:
    return str({**DEFAULTS, **o}["bar_font"]).replace('"', "")


def font_list(o: dict) -> str:
    """CSS font-family value: your font, then the Nerd Font for icons (once)."""
    font = font_of(o)
    return f'"{font}"' + ("" if font == ICON_FALLBACK else f', "{ICON_FALLBACK}"')


def refresh_all(store=None) -> list[str]:
    """Writes every part of the desktop from the Theme page settings and the current wallpaper palette. Returns
    what could not be written (empty when all went well)."""
    from . import lockscreen, theme_parts
    from .store import Store
    store = store or Store()
    o = theme_options(store)
    problems = []
    for name, job in (("bar", lambda: write_bar_theme(store)), ("notifications", lambda: theme_parts.write_swaync(o)),
                      ("rofi", lambda: theme_parts.write_rofi(o)), ("window borders", lambda: theme_parts.write_hypr(o)),
                      ("lock screen", lambda: theme_parts.write_lock(store)), ("apps", lambda: theme_parts.write_gtk(o))):
        try:
            job()
        except OSError as e:
            problems.append(f"{name}: {e}")
    return problems


if __name__ == "__main__" and sys.argv[1:] == ["refresh"]:
    for line in refresh_all():
        print("Could not update", line, file=sys.stderr)
