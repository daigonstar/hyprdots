"""GTK look and feel: theme, icons, cursor, font and dark mode. Replaces nwg-look.

A choice is written to gtk-3.0 and gtk-4.0 settings.ini and to gsettings (what GTK apps, Electron and the
portal read), then applied right away. Only the keys this module owns are touched; everything else in
settings.ini stays as it was."""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path

GSCHEMA = "org.gnome.desktop.interface"
# our name -> (settings.ini key, gsettings key)
KEYS = {
    "theme": ("gtk-theme-name", "gtk-theme"),
    "icons": ("gtk-icon-theme-name", "icon-theme"),
    "cursor": ("gtk-cursor-theme-name", "cursor-theme"),
    "cursor_size": ("gtk-cursor-theme-size", "cursor-size"),
    "font": ("gtk-font-name", "font-name"),
}
DARK_KEY = "gtk-application-prefer-dark-theme"
DEFAULTS = {"theme": "Adwaita", "icons": "Adwaita", "cursor": "Adwaita", "cursor_size": "24", "font": "Sans 11"}
_GTK4_LINKS = ("gtk.css", "gtk-dark.css", "assets")


def config_home() -> Path:
    return Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))


def data_dirs() -> list[Path]:
    home = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local/share"))
    system = [Path(p) for p in os.environ.get("XDG_DATA_DIRS", "/usr/local/share:/usr/share").split(":") if p]
    return [home, *system]


def _names(subdir: str, legacy: str, wanted) -> list[str]:
    found = set()
    for base in [*(d / subdir for d in data_dirs()), Path.home() / legacy]:
        try:
            for entry in base.iterdir():
                if entry.is_dir() and wanted(entry):
                    found.add(entry.name)
        except OSError:
            pass
    return sorted(found, key=str.lower)


def themes() -> list[str]:
    return _names("themes", ".themes", lambda p: (p / "gtk-3.0").is_dir() or (p / "gtk-4.0").is_dir())


def icon_themes() -> list[str]:
    return _names("icons", ".icons", lambda p: (p / "index.theme").is_file() and not (p / "cursors").is_dir()
                  and p.name not in ("default", "hicolor", "locolor"))


def cursor_themes() -> list[str]:
    return _names("icons", ".icons", lambda p: (p / "cursors").is_dir())


def fonts() -> list[str]:
    try:
        out = subprocess.run(["fc-list", ":", "family"], capture_output=True, text=True, timeout=10).stdout
    except (OSError, subprocess.SubprocessError):
        return []
    return sorted({f.split(",")[0].strip() for f in out.splitlines() if f.strip()}, key=str.lower)


def theme_dir(name: str) -> Path | None:
    for base in [*(d / "themes" for d in data_dirs()), Path.home() / ".themes"]:
        if (base / name).is_dir():
            return base / name
    return None


# ---- settings.ini ---------------------------------------------------------------------------------------
def _ini(version: str) -> Path:
    return config_home() / f"gtk-{version}" / "settings.ini"


def read_ini(version: str = "3.0") -> dict[str, str]:
    values, in_settings = {}, False
    try:
        lines = _ini(version).read_text(encoding="utf-8").splitlines()
    except OSError:
        return values
    for line in lines:
        s = line.strip()
        if s.startswith("["):
            in_settings = s == "[Settings]"
        elif in_settings and "=" in s and not s.startswith(("#", ";")):
            k, _, v = s.partition("=")
            values[k.strip()] = v.strip()
    return values


def write_ini(version: str, updates: dict[str, str]) -> None:
    path = _ini(version)
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        lines = []
    if "[Settings]" not in (line.strip() for line in lines):
        lines = ["[Settings]", *lines]
    out, in_settings, pending = [], False, dict(updates)
    for line in lines:
        s = line.strip()
        if s.startswith("["):
            if in_settings:                      # leaving [Settings]: add keys that were not there
                out.extend(f"{k}={v}" for k, v in pending.items())
                pending = {}
            in_settings = s == "[Settings]"
        elif in_settings and "=" in s and not s.startswith(("#", ";")) and s.partition("=")[0].strip() in pending:
            key = s.partition("=")[0].strip()
            out.append(f"{key}={pending.pop(key)}")
            continue
        out.append(line)
    if pending:
        if in_settings:
            out.extend(f"{k}={v}" for k, v in pending.items())
        else:
            out.append("[Settings]")
            out.extend(f"{k}={v}" for k, v in pending.items())
    tmp = path.with_name(path.name + f".{os.getpid()}.tmp")
    tmp.write_text("\n".join(out) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def _gsettings_get(key: str) -> str | None:
    if not shutil.which("gsettings"):
        return None
    try:
        r = subprocess.run(["gsettings", "get", GSCHEMA, key], capture_output=True, text=True, timeout=5)
    except (OSError, subprocess.SubprocessError):
        return None
    return r.stdout.strip().strip("'") if r.returncode == 0 else None


def current() -> dict:
    """What is in use now: settings.ini first (that is what this app writes), gsettings as the fallback."""
    ini = read_ini("3.0")
    out = {}
    for name, (ini_key, gkey) in KEYS.items():
        out[name] = ini.get(ini_key) or _gsettings_get(gkey) or DEFAULTS[name]
    dark = ini.get(DARK_KEY)
    out["dark"] = dark == "1" if dark is not None else (_gsettings_get("color-scheme") == "prefer-dark")
    return out


def font_parts(font: str) -> tuple[str, str]:
    """'Adwaita Sans 11' -> ('Adwaita Sans', '11')."""
    m = re.match(r"^(.*?)\s+(\d+(?:\.\d+)?)$", font.strip())
    return (m[1], m[2]) if m else (font.strip(), "11")


# ---- applying ---------------------------------------------------------------------------------------------
def _link_gtk4_theme(theme: str) -> None:
    """libadwaita apps ignore gtk-theme-name; they only follow ~/.config/gtk-4.0/gtk.css. Point it at the theme, or clear it."""
    folder = config_home() / "gtk-4.0"
    src = (theme_dir(theme) or Path("/nonexistent")) / "gtk-4.0"
    for name in _GTK4_LINKS:
        link = folder / name
        if link.is_symlink():
            link.unlink()
        elif link.exists():
            continue                              # the user's own file: never replace it
        if src.is_dir() and (src / name).exists():
            folder.mkdir(parents=True, exist_ok=True)
            link.symlink_to(src / name)


def apply(**changes) -> tuple[bool, str]:
    """Applies any of theme, icons, cursor, cursor_size, font, dark. Returns (ok, message)."""
    ini = {}
    gset: list[tuple[str, str]] = []
    for name, value in changes.items():
        if name == "dark":
            ini[DARK_KEY] = "1" if value else "0"
            gset.append(("color-scheme", "prefer-dark" if value else "default"))
        elif name in KEYS:
            ini[KEYS[name][0]] = str(value)
            gset.append((KEYS[name][1], str(value)))
    try:
        for version in ("3.0", "4.0"):
            write_ini(version, ini)
        if "theme" in changes:
            _link_gtk4_theme(str(changes["theme"]))
    except OSError as e:
        return False, f"Could not write the GTK settings: {e}"
    problems = []
    if shutil.which("gsettings"):
        for key, value in gset:
            args = ["gsettings", "set", GSCHEMA, key, value]
            if key == "cursor-size":
                args[-1] = str(int(float(value)))
            try:
                r = subprocess.run(args, capture_output=True, text=True, timeout=10)
                if r.returncode:
                    problems.append(r.stderr.strip() or key)
            except (OSError, subprocess.SubprocessError) as e:
                problems.append(str(e))
    if ("cursor" in changes or "cursor_size" in changes) and shutil.which("hyprctl"):
        now = current()
        try:
            subprocess.run(["hyprctl", "setcursor", now["cursor"], str(int(float(now["cursor_size"])))], capture_output=True, timeout=10)
        except (OSError, subprocess.SubprocessError, ValueError):
            pass
    if problems:
        return False, "Saved, but gsettings said: " + problems[0]
    return True, "Applied. Apps that are already open may need a restart to pick it up."
