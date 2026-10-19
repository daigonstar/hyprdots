"""Key combos for Hyprland binds: turns what a person types ("win shift t") into the form keybinds.lua uses
("SUPER + SHIFT + T") and spots two binds that would share a combo."""

from __future__ import annotations

import re

MODIFIERS = {"super": "SUPER", "win": "SUPER", "windows": "SUPER", "mod": "SUPER", "meta": "SUPER", "mod4": "SUPER",
             "ctrl": "CTRL", "control": "CTRL", "alt": "ALT", "mod1": "ALT", "shift": "SHIFT"}
ORDER = ["SUPER", "CTRL", "ALT", "SHIFT"]
_KEY = re.compile(r"^[A-Za-z0-9_:.,;'/\\\[\]=`-]+$")
_FKEY = re.compile(r"^f\d{1,2}$", re.I)

# Combos keybinds.lua sets itself (workspace numbers, mouse drag, media keys). They are not in the rebindable
# list, so nothing else may take them or one of the two would silently stop working.
RESERVED = (
    {f"super + {d}" for d in "1234567890"}
    | {f"super + shift + {d}" for d in "1234567890"}
    | {"super + mouse:272", "super + mouse:273"}
    | {k.lower() for k in ("XF86AudioRaiseVolume", "XF86AudioLowerVolume", "XF86AudioMute", "XF86AudioMicMute",
                           "XF86MonBrightnessUp", "XF86MonBrightnessDown", "XF86AudioNext", "XF86AudioPause",
                           "XF86AudioPlay", "XF86AudioPrev")}
)


def normalize(text: str) -> str:
    """'win + shift + t' -> 'SUPER + SHIFT + T'. 'none' means unbound. Raises ValueError with a plain message."""
    text = (text or "").strip()
    if text.lower() in ("none", "unbound"):
        return "none"
    if not text:
        raise ValueError("type a key, for example T, F5, left or SPACE")
    parts = [p.strip() for p in (re.split(r"\s*\+\s*", text) if "+" in text else text.split())]
    if not all(parts):
        raise ValueError("a key is missing: write it like SUPER + SHIFT + T")
    *mods, key = parts
    found: list[str] = []
    for m in mods:
        name = MODIFIERS.get(m.lower())
        if not name:
            raise ValueError(f"'{m}' is not a modifier (use Super, Ctrl, Alt or Shift)")
        if name not in found:
            found.append(name)
    if key.lower() in MODIFIERS:
        raise ValueError("add a key after the modifiers, for example SUPER + T")
    if not _KEY.match(key):
        raise ValueError(f"'{key}' is not a key name (examples: T, F5, left, SPACE, RETURN, XF86AudioPlay)")
    if len(key) == 1 or _FKEY.match(key):
        key = key.upper()
    return " + ".join([*sorted(found, key=ORDER.index), key])


def canon(text: str) -> str:
    """Comparison form: CONTROL and CTRL are the same, case never matters."""
    try:
        return normalize(text).lower()
    except ValueError:
        return (text or "").strip().lower()


def is_reserved(text: str) -> bool:
    return canon(text) in RESERVED
