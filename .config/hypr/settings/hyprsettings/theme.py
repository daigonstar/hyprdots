"""Wallust colours shared by the GTK windows (settings, keybind cheatsheet), plus the Super key logo."""

from __future__ import annotations

import re
from pathlib import Path

COLORS_FILE = Path.home() / ".config/rofi/colors.rasi"
ICON_FONT = "CaskaydiaCove Nerd Font Propo"
LOGOS = {"arch": "", "tux": ""}


def super_glyph(logo: str) -> str:
    """What to draw for the Super key: a Nerd Font logo, or the word for logo == 'text'."""
    return "SUPER" if logo == "text" else LOGOS.get(logo, LOGOS["arch"])


def colors(o: dict | None = None) -> dict:
    """The GTK windows' colours (settings, cheatsheet, power menu) from the Theme page roles: accent, secondary,
    text and background of large panels. Falls back to wallust's rofi colours, then to a calm grey set. A too-dark
    accent is blended towards the text colour until it reads on a dark background, so it keeps the wallpaper's hue."""
    out = {"accent": "#949ab3", "soft": "#a8a8ab", "fg": "#faf7fa", "bg": "#1c1a1c"}
    try:
        from . import design
        if o is None:
            from .store import Store
            o = design.theme_options(Store())
        c = design.resolved(o)
        out.update(accent=c["accent"], soft=c["secondary"], fg=c["base_text"], bg=c["base"])
    except (OSError, ValueError, KeyError, ImportError):
        try:
            text = COLORS_FILE.read_text()
        except OSError:
            return out
        for key, name in (("accent", "color12"), ("soft", "color5"), ("fg", "foreground"), ("bg", "background")):
            m = re.search(rf"^\s*{name}:\s*(#[0-9a-fA-F]{{6}})", text, re.M)
            if m:
                out[key] = m[1]
    for key in ("accent", "soft"):
        if luminance(out["bg"]) >= 0.4:  # a light background (a theme override): a dark accent already reads
            break
        for _ in range(6):
            if luminance(out[key]) >= 0.28:
                break
            out[key] = mix(out[key], out["fg"], 0.35)
    return out


def rgb(hex_colour: str) -> tuple:
    return tuple(int(hex_colour[i:i + 2], 16) / 255 for i in (1, 3, 5))


def luminance(hex_colour: str) -> float:
    lin = [c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4 for c in rgb(hex_colour)]
    return 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2]


def mix(a: str, b: str, t: float) -> str:
    return "#" + "".join(f"{round((x + (y - x) * t) * 255):02x}" for x, y in zip(rgb(a), rgb(b)))
