"""Lock screen look (Power & lock page): builds the hyprlock config from the [lockscreen] settings.

Saving writes hyprlock.local.conf (git-ignored); scripts/lock-screen.sh uses it when it exists, and the shipped
hyprlock.conf otherwise. The shipped file is render(DEFAULTS), so both always look the same out of the box.
The grace period is a hyprlock command-line option, so it travels in a "# grace=" line that lock-screen.sh reads."""

from __future__ import annotations

import os
from pathlib import Path

DEFAULTS = {"background": "wallpaper", "darken": 35, "clock_format": "24h", "clock_weight": 200, "clock_size": 140,
            "clock_position": "centre", "show_date": True, "show_user": False, "password": "underline", "grace": 0,
            "fade": True}
FONT = "Adwaita Sans"
WALLPAPER = "~/.config/rofi/.current_wallpaper"  # the wallpaper picker keeps this link pointing at your wallpaper


def local_path(hypr_dir: Path | str) -> Path:
    return Path(hypr_dir) / "hyprlock.local.conf"


def render(o: dict, header: str = "", accent: str | None = None) -> str:
    """accent: a #hex for the password line and box (the Theme page's accent); white when not given."""
    o = {**DEFAULTS, **o}
    line = f"rgba({accent[1:]}ee)" if accent else "$soft"
    shadow = "    shadow_passes = 2\n    shadow_size = 6\n    shadow_color = rgba(00000088)\n"
    up = 140 if o["clock_position"] == "top" else 0  # "Higher up" moves the clock and date into the upper third
    parts = [header or "# Lock screen (hyprlock), made by hypr-settings from the Power & lock page.\n",
             "# Clear what you typed: Esc, Ctrl+U or Ctrl+Backspace.\n",
             f"# grace={int(o['grace'])}\n\n",
             f"$font = {FONT}\n$text = rgba(ffffffee)\n$soft = rgba(ffffffbb)\n\n",
             "general {\n    hide_cursor = true\n}\n\n"]
    if o["fade"]:
        parts.append("animations {\n    enabled = true\n    bezier = linear, 1, 1, 0, 0\n"
                     "    animation = fadeIn, 1, 5, linear\n    animation = fadeOut, 1, 5, linear\n"
                     "    animation = inputFieldDots, 1, 2, linear\n}\n\n")
    else:
        parts.append("animations {\n    enabled = false\n}\n\n")

    blur = {"wallpaper": 0, "wallpaper_blur": 3, "screenshot_blur": 3}[o["background"]]
    path = "screenshot" if o["background"] == "screenshot_blur" else WALLPAPER
    parts.append(f"background {{\n    monitor =\n    path = {path}\n    blur_passes = {blur}\n}}\n\n")
    if int(o["darken"]) > 0:  # a dark layer: hyprlock's own brightness option only works together with blur
        alpha = round(255 * min(int(o["darken"]), 95) / 100)
        parts.append(f"shape {{\n    monitor =\n    size = 100%, 100%\n    color = rgba(000000{alpha:02x})\n    rounding = 0\n"
                     "    border_size = 0\n    position = 0, 0\n    halign = center\n    valign = center\n}\n\n")

    clock = "$TIME12" if o["clock_format"] == "12h" else "$TIME"
    parts.append(f"label {{\n    monitor =\n    text = <span font_weight=\"{int(o['clock_weight'])}\">{clock}</span>\n"
                 f"    color = $text\n    font_size = {int(o['clock_size'])}\n    font_family = $font\n{shadow}"
                 f"    position = 0, {80 + up + (int(o['clock_size']) - 140) // 3}\n    halign = center\n    valign = center\n}}\n\n")
    if o["show_date"]:
        parts.append("label {\n    monitor =\n    text = cmd[update:60000] date +\"%A %-d %B\"\n    color = $soft\n"
                     f"    font_size = 20\n    font_family = $font\n{shadow}    position = 0, {-40 + up}\n"
                     "    halign = center\n    valign = center\n}\n\n")

    if o["password"] == "box":
        y_field, y_user = -150 + up, -215 + up
        parts.append("input-field {\n    monitor =\n    size = 340, 54\n    outline_thickness = 2\n"
                     f"    inner_color = rgba(00000055)\n    outer_color = {line}\n    check_color = rgba(7fd17fee)\n"
                     "    fail_color = rgba(ff8a8aee)\n    font_color = $text\n    fade_on_empty = false\n    rounding = 14\n"
                     "    font_family = $font\n    placeholder_text = <span foreground=\"##ffffff88\">Password</span>\n"
                     "    fail_text = $PAMFAIL\n    dots_spacing = 0.3\n    dots_center = true\n"
                     f"    position = 0, {y_field}\n    halign = center\n    valign = center\n}}\n\n")
        user_pos, user_valign = f"0, {y_user}", "center"
    else:
        parts.append("input-field {\n    monitor =\n    size = 320, 44\n    outline_thickness = 0\n"
                     "    inner_color = rgba(00000000)\n    outer_color = rgba(00000000)\n    check_color = rgba(00000000)\n"
                     "    fail_color = rgba(00000000)\n    font_color = $text\n    fade_on_empty = false\n    rounding = 0\n"
                     "    font_family = $font\n    placeholder_text =\n"
                     "    fail_text = <span foreground=\"##ff8a8a\">$PAMFAIL</span>\n    dots_size = 0.22\n"
                     "    dots_spacing = 0.45\n    dots_center = true\n    position = 0, 96\n    halign = center\n"
                     "    valign = bottom\n}\n\n"
                     f"shape {{\n    monitor =\n    size = 320, 2\n    color = {line}\n    rounding = 0\n    border_size = 0\n"
                     "    position = 0, 90\n    halign = center\n    valign = bottom\n}\n\n")
        user_pos, user_valign = "0, 150", "bottom"
    if o["show_user"]:
        parts.append(f"label {{\n    monitor =\n    text = $USER\n    color = $soft\n    font_size = 15\n    font_family = $font\n"
                     f"{shadow}    position = {user_pos}\n    halign = center\n    valign = {user_valign}\n}}\n\n")
    return "".join(parts).rstrip("\n") + "\n"


def write(path: Path | str, text: str) -> Path:
    path = Path(path)
    tmp = path.with_name(path.name + f".{os.getpid()}.tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)
    return path
