"""Which app opens which kind of file.

Reads the standard desktop-entry files and mimeapps.list directly (fast, no subprocess), and sets a default with
`xdg-mime default`, which writes ~/.config/mimeapps.list, so every toolkit and browser sees the change."""

from __future__ import annotations

import mimetypes
import os
import subprocess
from pathlib import Path

# (label, what it is, mime types set together; the first one is the one shown)
CATEGORIES = [
    ("Web links", "Links clicked in other apps", ["x-scheme-handler/https", "x-scheme-handler/http", "text/html", "application/xhtml+xml"]),
    ("Email links", "mailto: addresses", ["x-scheme-handler/mailto"]),
    ("Folders", "Opening a folder", ["inode/directory"]),
    ("Text files", ".txt, .md, .log, source code", ["text/plain", "text/markdown", "text/x-log", "application/json", "application/xml",
                                                  "text/x-python", "text/x-shellscript", "text/x-csrc", "text/css", "application/x-yaml"]),
    ("PDF documents", ".pdf", ["application/pdf"]),
    ("Word processor documents", ".docx, .odt, .rtf", ["application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                                                      "application/vnd.oasis.opendocument.text", "application/msword", "application/rtf"]),
    ("Spreadsheets", ".xlsx, .ods, .csv", ["application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                                           "application/vnd.oasis.opendocument.spreadsheet", "application/vnd.ms-excel", "text/csv"]),
    ("Presentations", ".pptx, .odp", ["application/vnd.openxmlformats-officedocument.presentationml.presentation",
                                      "application/vnd.oasis.opendocument.presentation", "application/vnd.ms-powerpoint"]),
    ("Images", ".png, .jpg, .gif, .webp, .svg", ["image/png", "image/jpeg", "image/gif", "image/webp", "image/svg+xml", "image/bmp",
                                                  "image/tiff", "image/avif", "image/heif"]),
    ("Video", ".mp4, .mkv, .webm, .avi", ["video/mp4", "video/x-matroska", "video/webm", "video/quicktime", "video/x-msvideo",
                                          "video/mpeg", "video/ogg"]),
    ("Music and audio", ".mp3, .flac, .ogg, .wav", ["audio/mpeg", "audio/flac", "audio/x-flac", "audio/ogg", "audio/x-wav", "audio/wav",
                                                    "audio/mp4", "audio/aac", "audio/opus", "audio/x-opus+ogg"]),
    ("Archives", ".zip, .tar, .7z, .rar", ["application/zip", "application/x-tar", "application/x-compressed-tar", "application/x-7z-compressed",
                                           "application/vnd.rar", "application/gzip", "application/x-xz", "application/x-bzip2",
                                           "application/zstd"]),
    ("E-books", ".epub", ["application/epub+zip"]),
    ("Torrents", ".torrent and magnet links", ["application/x-bittorrent", "x-scheme-handler/magnet"]),
    ("Disk images", ".iso", ["application/x-iso9660-image", "application/x-cd-image"]),
    ("3D models", ".stl, .3mf, .obj", ["model/stl", "application/vnd.ms-package.3dmanufacturing-3dmodel+xml", "model/obj"]),
]


def _dirs(var: str, default: str) -> list[Path]:
    return [Path(p) for p in os.environ.get(var, default).split(":") if p]


def config_home() -> Path:
    return Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))


def data_home() -> Path:
    return Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local/share"))


def application_dirs() -> list[Path]:
    dirs = [data_home(), *_dirs("XDG_DATA_DIRS", "/usr/local/share:/usr/share")]
    dirs += [Path("/var/lib/flatpak/exports/share"), Path.home() / ".local/share/flatpak/exports/share"]
    out = []
    for d in dirs:
        if (d / "applications") not in out:
            out.append(d / "applications")
    return out


def _parse_desktop(path: Path) -> dict | None:
    entry, in_entry = {}, False
    try:
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            s = line.strip()
            if s.startswith("["):
                in_entry = s == "[Desktop Entry]"
            elif in_entry and "=" in s and not s.startswith("#"):
                k, _, v = s.partition("=")
                entry.setdefault(k.strip(), v.strip())
    except OSError:
        return None
    return entry or None


def installed_apps() -> dict[str, dict]:
    """desktop id -> {name, mimes}. Earlier directories win, hidden entries are skipped."""
    apps: dict[str, dict] = {}
    for base in application_dirs():
        if not base.is_dir():
            continue
        for path in base.rglob("*.desktop"):
            app_id = str(path.relative_to(base)).replace("/", "-")
            if app_id in apps:
                continue
            e = _parse_desktop(path)
            if not e or e.get("Type", "Application") != "Application" or e.get("Hidden") == "true":
                continue
            mimes = [m for m in e.get("MimeType", "").split(";") if m]
            apps[app_id] = {"name": e.get("Name", app_id[:-8]), "mimes": mimes, "hidden": e.get("NoDisplay") == "true"}
    return apps


def _list_files() -> list[Path]:
    cfg = [config_home(), *_dirs("XDG_CONFIG_DIRS", "/etc/xdg")]
    files = [d / "mimeapps.list" for d in cfg]
    files += [d / "mimeapps.list" for d in application_dirs()]
    return files


def _read_list(path: Path, section: str) -> dict[str, list[str]]:
    out, on = {}, False
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return out
    for line in lines:
        s = line.strip()
        if s.startswith("["):
            on = s == f"[{section}]"
        elif on and "=" in s and not s.startswith("#"):
            k, _, v = s.partition("=")
            out[k.strip()] = [x for x in v.split(";") if x]
    return out


def default_for(mime: str, apps: dict[str, dict]) -> str | None:
    """The desktop id that opens this type now, following the standard lookup order."""
    for f in _list_files():
        for app_id in _read_list(f, "Default Applications").get(mime, []):
            if app_id in apps:
                return app_id
    for base in application_dirs():
        for app_id in _read_list(base / "mimeinfo.cache", "MIME Cache").get(mime, []):
            if app_id in apps:
                return app_id
    return None


def candidates(mimes: list[str], apps: dict[str, dict]) -> list[tuple[str, str]]:
    """Apps that can open the first type, then those that can open only the others. [(id, name)]"""
    first = [(i, a["name"]) for i, a in apps.items() if mimes[0] in a["mimes"] and not a["hidden"]]
    rest = [(i, a["name"]) for i, a in apps.items()
            if mimes[0] not in a["mimes"] and not a["hidden"] and any(m in a["mimes"] for m in mimes[1:])]
    key = lambda x: x[1].lower()
    return sorted(first, key=key) + sorted(rest, key=key)


def category_state(mimes: list[str], apps: dict[str, dict]) -> tuple[str | None, bool]:
    """(default app id for the main type, True if the other types in the group use something different)."""
    main = default_for(mimes[0], apps)
    mixed = any(default_for(m, apps) not in (main, None) for m in mimes[1:])
    return main, mixed


def set_default(app_id: str, mimes: list[str]) -> tuple[bool, str]:
    try:
        r = subprocess.run(["xdg-mime", "default", app_id, *mimes], capture_output=True, text=True, timeout=20)
    except (OSError, subprocess.SubprocessError) as e:
        return False, f"Could not run xdg-mime: {e}"
    return (True, "") if r.returncode == 0 else (False, (r.stderr or r.stdout).strip()[:300] or "xdg-mime failed")


def resolve_type(text: str) -> str:
    """'.mkv' or 'mkv' -> 'video/x-matroska'; 'image/png' stays as it is. ValueError if unknown."""
    text = text.strip()
    if "/" in text and " " not in text:
        return text.lower()
    ext = text.lstrip(".").lower()
    if not ext or not ext.isalnum():
        raise ValueError("type a file ending like .mkv, or a type like video/mp4")
    mime, _ = mimetypes.guess_type(f"x.{ext}")
    if not mime:
        raise ValueError(f"I do not know what kind of file .{ext} is. Type its full type instead, like video/mp4.")
    return mime
