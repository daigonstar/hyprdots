"""Bar layout page: which modules sit on the left, in the centre and on the right of the bar, in what order.

The tracked waybar/config stays as it is. Your arrangement is saved to waybar/layout.json (git-ignored), and
waybar/launch.sh builds the config the bar really runs, config.generated.json, from the two. Without a layout.json,
or if anything goes wrong building it, the bar runs the tracked config.

    python3 -m hyprsettings.barlayout generate     (what launch.sh runs)"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ZONES = ("modules-left", "modules-center", "modules-right")
ZONE_NAMES = {"modules-left": "Left", "modules-center": "Centre", "modules-right": "Right"}
# Keys of the bar's config that are bar settings, not module definitions
NOT_MODULES = {"layer", "position", "height", "width", "spacing", "margin", "margin-top", "margin-bottom", "margin-left",
               "margin-right", "output", "name", "mode", "exclusive", "passthrough", "fixed-center", "gtk-layer-shell",
               "ipc", "include", "start_hidden", "modifier-reset", "reload_style_on_change", "id", *ZONES}

# Old definitions nothing uses (see AUDIT.md); kept in the config but not offered
UNUSED: set[str] = set()  # modules defined in the config but kept off the Bar layout page
# Friendly names and icons for the editor (anything else shows its own name)
KNOWN = {
    "clock": ("Clock", "\U000f0954"), "custom/assistant": ("Hearthling", "\U000f0674"), "hyprland/window": ("Window title", "\U000f05b5"),
    "hyprland/workspaces": ("Workspaces", "\U000f0570"), "cava": ("Music bars", "\U000f075a"), "pulseaudio": ("Sound", "\U000f057e"),
    "bluetooth": ("Bluetooth", "\U000f00af"), "custom/updates": ("Updates", "\U000f03d7"), "battery": ("Battery", "\U000f0079"),
    "network": ("Network", "\U000f0200"), "custom/power": ("Power menu", "\U000f0425"), "custom/noti": ("Notifications", "\U000f009a"),
    "custom/recording": ("Recording dot", "\U000f044a"),
    "tray": ("Tray", "\U000f00a1"), "cpu": ("CPU", "\U000f04e9"), "memory": ("Memory", "\U000f035b"),
    "temperature": ("Temperature", "\U000f050f"),
    "mpris": ("Now playing", "\U000f0386"), "idle_inhibitor": ("Keep awake", "\U000f0176"),
    "hyprland/language": ("Keyboard layout", "\U000f030c"), "disk": ("Disk space", "\U000f02ca"),
    "backlight": ("Screen brightness", "\U000f00e0"), "privacy": ("Privacy", "\U000f036c"), "group/expand": ("System drawer", "\U000f0141"), "group/expand2": ("Shortcuts drawer", "\U000f0142"),
}


# Ready-made layouts on the Bar layout page: key, name, what it is, arrangement, bar style (Theme page), position.
# "classic" is the config's own arrangement. Modules a config does not define are left out when a preset is applied.
STATUS = ["pulseaudio", "bluetooth", "network", "battery", "custom/updates", "custom/recording"]
PRESETS = [
    ("classic", "Classic", "Clock on the left, workspaces in the middle, status on the right, as three panels.",
     None, "islands", "top"),
    ("two_sides", "Two sides", "Workspaces and the window title on the left, everything else on the right, nothing between.",
     {"modules-left": ["group/expand2", "hyprland/workspaces", "hyprland/window"], "modules-center": [],
      "modules-right": ["cava", "group/expand", *STATUS, "clock", "custom/assistant", "custom/noti", "custom/power"]},
     "islands", "top"),
    ("centre_pill", "Centre pill", "Everything in one panel in the middle of the bar; the sides stay clear.",
     {"modules-left": [], "modules-center": ["group/expand2", "clock", "custom/assistant", "hyprland/workspaces", *STATUS,
                                             "custom/noti", "custom/power", "group/expand"], "modules-right": []},
     "islands", "top"),
    ("full_strip", "Full strip", "The classic arrangement as one solid bar across the whole screen.",
     None, "solid", "top"),
    ("bottom_dock", "Bottom dock", "A dock at the bottom: workspaces in the middle, every module in its own pill.",
     {"modules-left": ["clock", "custom/assistant", "group/expand2"], "modules-center": ["hyprland/workspaces"],
      "modules-right": ["group/expand", *STATUS, "custom/noti", "custom/power"]},
     "bubbles", "bottom"),
]


def preset(key: str, config: dict) -> tuple[dict, str]:
    """(layout, bar style) for a preset, with only the modules this config has."""
    _k, _name, _what, arrangement, style, position = next(p for p in PRESETS if p[0] == key)
    if arrangement is None:
        arrangement = {z: config.get(z, []) for z in ZONES}
    allowed = set(available(config))
    layout = {z: [m for m in arrangement.get(z, []) if m in allowed] for z in ZONES}
    return {**layout, "position": position}, style


def waybar_dir() -> Path:
    return Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config") / "waybar"


# ---- reading the bar's config (JSON with // and /* */ comments and trailing commas) -------------------------------
def strip_jsonc(text: str) -> str:
    out, i, n = [], 0, len(text)
    while i < n:
        c = text[i]
        if c == '"':  # copy a whole string, escapes included, so // inside strings (URLs) survive
            j = i + 1
            while j < n and text[j] != '"':
                j += 2 if text[j] == "\\" else 1
            out.append(text[i:j + 1])
            i = j + 1
        elif text.startswith("//", i):
            i = text.find("\n", i)
            i = n if i < 0 else i
        elif text.startswith("/*", i):
            i = text.find("*/", i + 2)
            i = n if i < 0 else i + 2
        elif c == ",":  # drop a trailing comma before ] or } (comments in between allowed)
            j = i + 1
            while j < n:
                if text[j].isspace():
                    j += 1
                elif text.startswith("//", j):
                    j = text.find("\n", j)
                    j = n if j < 0 else j
                elif text.startswith("/*", j):
                    j = text.find("*/", j + 2)
                    j = n if j < 0 else j + 2
                else:
                    break
            if j >= n or text[j] not in "]}":
                out.append(c)
            i += 1
        else:
            out.append(c)
            i += 1
    return "".join(out)


def read_config(path: Path | None = None) -> dict:
    """The tracked bar config (first bar when it lists several)."""
    data = json.loads(strip_jsonc((path or waybar_dir() / "config").read_text(encoding="utf-8")))
    return data[0] if isinstance(data, list) else data


POSITIONS = (("top", "Top of the screen"), ("bottom", "Bottom of the screen"))


def default_layout(config: dict) -> dict:
    return {**{z: list(config.get(z, [])) for z in ZONES}, "position": config.get("position", "top")}


def in_groups(config: dict) -> set[str]:
    """Modules that live inside a drawer (group), so they move with it rather than on their own."""
    out = set()
    for key, value in config.items():
        if key.startswith("group/") and isinstance(value, dict):
            out.update(value.get("modules", []))
    return out


def available(config: dict) -> list[str]:
    """Every module the config defines that can sit on the bar by itself."""
    inside = in_groups(config)
    return [k for k, v in config.items()
            if k not in NOT_MODULES and k not in UNUSED and isinstance(v, dict) and k not in inside]


def label(module: str) -> tuple[str, str]:
    name, icon = KNOWN.get(module, (None, ""))
    if name is None:
        name = module.split("/", 1)[-1].replace("-", " ").replace("_", " ").capitalize()
    return name, icon


# ---- your layout ----------------------------------------------------------------------------------------------------
def layout_path() -> Path:
    return waybar_dir() / "layout.json"


def read_layout(config: dict) -> dict[str, list[str]]:
    """Your arrangement, checked against the config: unknown modules are dropped. The default when there is none."""
    try:
        saved = json.loads(layout_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default_layout(config)
    allowed = set(available(config))
    position = saved.get("position") if saved.get("position") in dict(POSITIONS) else config.get("position", "top")
    return {**{z: [m for m in saved.get(z, []) if m in allowed] for z in ZONES}, "position": position}


def write_layout(layout: dict[str, list[str]]) -> None:
    path = layout_path()
    tmp = path.with_name(path.name + f".{os.getpid()}.tmp")
    tmp.write_text(json.dumps({**{z: layout[z] for z in ZONES}, "position": layout.get("position", "top")}, indent=2) + "\n",
                   encoding="utf-8")
    os.replace(tmp, path)


def reset_layout() -> None:
    for p in (layout_path(), waybar_dir() / "config.generated.json"):
        p.unlink(missing_ok=True)


def with_recording(layout: dict, config: dict) -> dict:
    """The REC dot in a layout saved before it existed, or the tray's Record tile would give no sign on the bar. It only
    shows while recording, so it costs a layout nothing."""
    if "custom/recording" not in config or any("custom/recording" in layout.get(z, []) for z in ZONES):
        return layout
    right = list(layout.get("modules-right", []))
    right.insert(right.index("custom/power") if "custom/power" in right else len(right), "custom/recording")
    return {**layout, "modules-right": right}


def generate() -> Path:
    """Writes config.generated.json: the tracked config with your layout. Raises if either cannot be read."""
    config = read_config()
    merged = {**config, **with_recording(read_layout(config), config)}
    out = waybar_dir() / "config.generated.json"
    tmp = out.with_name(out.name + f".{os.getpid()}.tmp")
    tmp.write_text(json.dumps(merged, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    os.replace(tmp, out)
    return out


if __name__ == "__main__" and sys.argv[1:] == ["generate"]:
    print(generate())
