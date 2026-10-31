"""The desktop beyond the bar, built from the Theme page roles (design.py). Each writer uses real colours from the
current wallpaper's palette, so design.refresh_all() runs them again after wallust on every wallpaper change.

- notifications: swaync/theme.css, imported last by swaync/style.css (theme.default.css is the fallback; launch.sh)
- rofi: a marked block appended to wallust's ~/.config/rofi/colors.rasi, which every rofi theme imports
- window borders: hypr/theme.lua, read by window.lua when it exists
- lock screen: hyprlock.local.conf, when you have one (the password line takes the accent)"""

from __future__ import annotations

import subprocess
from pathlib import Path

from . import design

HOME = Path.home()
ROFI_MARK = "/* hyprdots theme"


def swaync_css(o: dict) -> str:
    c = design.resolved(o)
    o = {**design.DEFAULTS, **o}
    base_a = int(o["base_opacity"]) / 100
    tint = design.alpha_rgba(c["surface"], 0.22)
    return f"""/* Notification colours and font, made by hypr-settings from the Theme page (rewritten when the wallpaper changes).
   Imported last by style.css, so these win over the theme's own colour names. Do not edit by hand. */
@define-color text {c['base_text']};
@define-color background {c['base']};
@define-color background-alt {tint};
@define-color selected {c['accent']};
@define-color button-active {c['accent']};
@define-color hover {design.alpha_rgba(c['secondary'], 0.35)};
@define-color hovered {c['secondary']};
@define-color urgent {c['attention']};
@define-color swaync-bg {design.alpha_rgba(c['base'], base_a)};
@define-color swaync-bg-soft {design.alpha_rgba(c['base'], max(0.0, base_a - 0.04))};

* {{
    font-family: {design.font_list(o)};
}}
"""


def write_swaync(o: dict) -> None:
    design.write(HOME / ".config/swaync/theme.css", swaync_css(o))
    subprocess.run(["swaync-client", "--reload-css"], capture_output=True, timeout=10)


def rofi_block(o: dict) -> str:
    c = design.resolved(o)
    o = {**design.DEFAULTS, **o}
    base = design.alpha_rgba(c["base"], int(o["base_opacity"]) / 100)
    pairs = {
        "background": base, "background-color": "transparent", "background-alt": c["surface"],
        "foreground": c["base_text"], "border-color": c["accent"], "selected": c["accent"],
        "normal-background": base, "normal-foreground": c["base_text"],
        "alternate-normal-background": base, "alternate-normal-foreground": c["base_text"],
        "active-background": c["surface"], "active-foreground": c["text"],
        "alternate-active-background": c["surface"], "alternate-active-foreground": c["text"],
        "urgent-background": c["attention"], "urgent-foreground": c["base"],
        "alternate-urgent-background": c["attention"], "alternate-urgent-foreground": c["base"],
        "selected-normal-background": c["accent"], "selected-normal-foreground": c["base"],
        "selected-active-background": c["accent"], "selected-active-foreground": c["base"],
        "selected-urgent-background": c["attention"], "selected-urgent-foreground": c["base"],
        "font": f'"{design.font_of(o)} 13"',
    }
    body = "".join(f"    {k}: {v};\n" for k, v in pairs.items())
    return f"\n{ROFI_MARK}: roles from the settings Theme page, rewritten when the wallpaper changes */\n* {{\n{body}}}\n"


def write_rofi(o: dict) -> None:
    path = HOME / ".config/rofi/colors.rasi"
    text = path.read_text(encoding="utf-8")
    if ROFI_MARK in text:  # replace the previous block, keep what wallust wrote
        text = text[:text.index(ROFI_MARK)].rstrip("\n") + "\n"
    design.write(path, text + rofi_block(o))


def hypr_lua(o: dict) -> str:
    c = design.resolved(o)
    lua = lambda h: f'"rgb({h[1:]})"'  # noqa: E731
    return ("-- Window border colours, made by hypr-settings from the Theme page (rewritten when the wallpaper changes).\n"
            "-- window.lua uses these when this file exists. Do not edit by hand.\n"
            "return {\n"
            f"    active_border = {lua(c['accent'])},\n"
            f"    inactive_border = {lua(c['muted'])},\n"
            f"    group_active = {lua(c['accent'])},\n"
            f"    group_inactive = {lua(c['muted'])},\n"
            "}\n")


def write_hypr(o: dict) -> None:
    design.write(HOME / ".config/hypr/theme.lua", hypr_lua(o))


def write_lock(store) -> None:
    """Only rewrites the lock screen when you have saved your own look (the shipped one stays as it is)."""
    from . import lockscreen
    path = lockscreen.local_path(store.dir)
    if path.exists():
        lockscreen.write(path, lockscreen.render(store.lock_options(), accent=design.resolved(design.theme_options(store))["accent"]))
