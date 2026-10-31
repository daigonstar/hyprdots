"""Cloud accounts for the file manager: Google Drive, OneDrive, Dropbox, Nextcloud, ownCloud, any WebDAV.

rclone does the talking to each service and mounts it as an ordinary folder under ~/Cloud, so Thunar
(or any other program) just sees folders. Each mount is a systemd *user* service, so a connected
account comes back on its own at login and a disconnected one stays off.

Passwords and tokens never touch the settings files: they live in rclone's own config
(~/.config/rclone/rclone.conf)."""

from __future__ import annotations

import os
import re
import shlex
import shutil
import subprocess
import threading
import time
import urllib.parse
from pathlib import Path
from typing import Callable

# (rclone type or alias, label, how you sign in)
PROVIDERS = [
    ("drive", "Google Drive", "oauth"),
    ("onedrive", "Microsoft OneDrive", "oauth"),
    ("dropbox", "Dropbox", "oauth"),
    ("nextcloud", "Nextcloud", "dav"),
    ("owncloud", "ownCloud", "dav"),
    ("webdav", "Other WebDAV server", "dav"),
]
TYPE_LABELS = {"drive": "Google Drive", "onedrive": "OneDrive", "dropbox": "Dropbox", "webdav": "WebDAV",
               "sftp": "SFTP", "s3": "S3", "b2": "Backblaze B2", "box": "Box", "mega": "Mega", "pcloud": "pCloud"}
NAME_OK = re.compile(r"^[A-Za-z0-9_-]{1,30}$")
TEMPLATE = "rclone-mount@.service"

# Flags for every mount. They make the first visit to a drive fast:
#   --vfs-refresh      lists the folders in the background right after mounting, so Thunar hits the cache
#   --dir-cache-time   keeps listings for an hour (--poll-interval still picks up remote changes)
#   --attr-timeout     lets the kernel cache file attributes, so repeated stat calls never reach rclone
#   --contimeout       gives up on an unreachable server after 15s instead of a minute, so Thunar is not left waiting
BASE_FLAGS = "--dir-cache-time 1h --poll-interval 1m --vfs-refresh --attr-timeout 30s --contimeout 15s"


def mount_flags(mode: str = "full", size_gb: int = 10, days: int = 30) -> str:
    """rclone mount flags for the File cache settings on the Cloud drives page.
    full:   reads fetch only the parts an app asks for and keep them on disk, capped by size and age
    writes: reads stream from the server and keep nothing; saved files are staged briefly before upload"""
    if mode == "writes":
        cache = "--vfs-cache-mode writes --vfs-cache-max-age 1h"
    else:
        cache = f"--vfs-cache-mode full --vfs-cache-max-size {int(size_gb)}G --vfs-cache-max-age {int(days) * 24}h"
    return f"{cache} {BASE_FLAGS}"


def cache_settings() -> tuple[str, int, int]:
    """(mode, size in GB, days) as saved in the settings files."""
    from .schema import BY_ID
    from .store import Store
    store = Store()
    return tuple(store.get(BY_ID[f"cloud.{k}"])[0] for k in ("cache_mode", "cache_size_gb", "cache_days"))


_cache: dict = {"t": float("-inf"), "data": []}


# ---- environment -----------------------------------------------------------------------------------
def rclone() -> str | None:
    return shutil.which("rclone")


def fuse_cmd() -> str | None:
    return shutil.which("fusermount3") or shutil.which("fusermount")


def mount_root() -> Path:
    return Path(os.environ.get("HYPR_CLOUD_DIR") or Path.home() / "Cloud")


def mount_path(name: str) -> Path:
    return mount_root() / name


def bookmarks_enabled() -> bool:
    """Thunar probes every sidebar bookmark when it starts, so a slow drive slows Thunar down.
    Set HYPR_CLOUD_BOOKMARKS=0 (for example in ~/.config/environment.d/) to keep drives out of the sidebar."""
    return os.environ.get("HYPR_CLOUD_BOOKMARKS", "1").strip().lower() not in ("0", "no", "off", "false")


def type_label(kind: str) -> str:
    return TYPE_LABELS.get(kind, kind or "unknown")


def unit(name: str) -> str:
    return f"rclone-mount@{name}.service"


def _run(cmd: list[str], timeout: float = 20, text_in: str | None = None) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, input=text_in)
    except (OSError, subprocess.SubprocessError) as e:
        return subprocess.CompletedProcess(cmd, 127, "", str(e))


def _sc(*args: str, timeout: float = 20) -> subprocess.CompletedProcess:
    return _run(["systemctl", "--user", *args], timeout=timeout)


def _last(text: str) -> str:
    lines = [ln.strip() for ln in (text or "").splitlines() if ln.strip()]
    return lines[-1] if lines else "no details given"


# ---- accounts ------------------------------------------------------------------------------------------
def remotes() -> list[tuple[str, str]]:
    exe = rclone()
    if not exe:
        return []
    out = []
    for line in _run([exe, "listremotes", "--long"]).stdout.splitlines():
        name, _, kind = line.partition(":")
        if name.strip():
            out.append((name.strip(), kind.strip()))
    return out


def invalidate() -> None:
    _cache["t"] = float("-inf")


def accounts(force: bool = False) -> list[dict]:
    """[{name, type, state, enabled}] with a short cache so redrawing the screen stays cheap."""
    now = time.monotonic()
    if not force and now - _cache["t"] < 4:
        return _cache["data"]
    data = []
    found = remotes()
    for name, kind in found:  # one query per account, so a missing unit can never shift another row
        state = _sc("is-active", unit(name), timeout=10).stdout.strip() or "inactive"
        enabled = _sc("is-enabled", unit(name), timeout=10).stdout.strip() == "enabled"
        data.append({"name": name, "type": kind, "state": state, "enabled": enabled})
    _cache.update(t=now, data=data)
    return data


def check_name(name: str) -> None:
    if not NAME_OK.match(name):
        raise ValueError("use 1 to 30 letters, numbers, - or _ (no spaces)")
    if name.lower() in {n.lower() for n, _ in remotes()}:
        raise ValueError(f"an account called '{name}' already exists")


def suggest_name(kind: str) -> str:
    base = {"drive": "gdrive"}.get(kind, kind)
    taken = {n.lower() for n, _ in remotes()}
    name, i = base, 2
    while name.lower() in taken:
        name, i = f"{base}{i}", i + 1
    return name


# ---- Thunar sidebar entry ----------------------------------------------------------------------------
def _bookmarks_file() -> Path:
    return Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config") / "gtk-3.0" / "bookmarks"


def add_bookmark(name: str) -> None:
    uri = mount_path(name).as_uri()
    path = _bookmarks_file()
    try:
        lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
        if not any(ln.split(" ", 1)[0] == uri for ln in lines):
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("\n".join([*lines, f"{uri} {name}"]) + "\n", encoding="utf-8")
    except OSError:
        pass  # the sidebar entry is a convenience; the folder works without it


def remove_bookmark(name: str) -> None:
    uri = mount_path(name).as_uri()
    path = _bookmarks_file()
    try:
        if path.exists():
            keep = [ln for ln in path.read_text(encoding="utf-8").splitlines() if ln.split(" ", 1)[0] != uri]
            path.write_text("\n".join(keep) + ("\n" if keep else ""), encoding="utf-8")
    except OSError:
        pass


# ---- mounting ------------------------------------------------------------------------------------------
def _unit_text(exe: str, fuse: str) -> str:
    root = str(mount_root()).replace("%", "%%")  # % is special in systemd units
    return f"""[Unit]
Description=Cloud drive %i (rclone mount)
After=network-online.target
Wants=network-online.target

[Service]
Type=notify
ExecStartPre=-{fuse} -uz "{root}/%i"
ExecStartPre=/usr/bin/env mkdir -p "{root}/%i"
ExecStart={exe} mount %i: "{root}/%i" {mount_flags(*cache_settings())}
ExecStop={fuse} -u "{root}/%i"
Restart=on-failure
RestartSec=15

[Install]
WantedBy=default.target
"""


def ensure_unit(exe: str, fuse: str) -> None:
    d = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config") / "systemd" / "user"
    path = d / TEMPLATE
    text = _unit_text(exe, fuse)
    if not path.exists() or path.read_text(encoding="utf-8") != text:
        d.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        _sc("daemon-reload")


def block_trash(name: str) -> str:
    """Puts an empty file named .Trash-<uid> at the top of the drive, so no trash folder can be made there.

    The desktop's trash service reads every .trashinfo in every drive's trash when the first Thunar window of a
    session opens, one server round trip each on a cloud drive; that is what made Thunar take seconds to open.
    With the file in place there is nothing to read, and deleting on the drive asks to delete permanently instead.
    Nothing is lost: Google Drive keeps deleted files in its own trash, and Nextcloud/ownCloud in their trash bin.
    Returns a note for the user when an existing trash still holds files (those are never deleted here)."""
    path = mount_path(name) / f".Trash-{os.getuid()}"
    try:
        if path.is_file():
            return ""
        if path.is_dir():
            if any(p.is_file() for p in path.rglob("*")):
                return (f" Its trash folder still holds files, which slows Thunar down; empty {path} and connect again "
                        "to stop that.")
            shutil.rmtree(path)
        path.touch()
    except OSError as e:
        return f" Could not replace its trash folder ({e.strerror or e}); Thunar may open slowly until {path} is removed."
    return ""


def refresh_unit() -> bool:
    """Rewrites the mount unit after the cache settings change. True when it changed; drives that are connected use
    it from their next restart (restart_connected, or the next login)."""
    exe, fuse = rclone(), fuse_cmd()
    if not exe or not fuse:
        return False
    d = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config") / "systemd" / "user"
    before = (d / TEMPLATE).read_text(encoding="utf-8") if (d / TEMPLATE).exists() else ""
    ensure_unit(exe, fuse)
    return (d / TEMPLATE).read_text(encoding="utf-8") != before


def connected() -> list[str]:
    return [a["name"] for a in accounts(force=True) if a["state"] in ("active", "activating", "reloading")]


def restart_connected(status: Callable[[str], None] = lambda _t: None) -> tuple[bool, str]:
    """Restarts every connected drive so it picks up the current unit. Files waiting to upload stay in the cache
    and carry on uploading afterwards."""
    names = connected()
    failed = []
    for name in names:
        status(f"Restarting {name}...")
        if _sc("restart", unit(name), timeout=90).returncode != 0:
            failed.append(name)
    invalidate()
    if failed:
        return False, f"Could not restart {', '.join(failed)}. Details: journalctl --user -u {unit(failed[0])}"
    return True, f"Restarted {', '.join(names)} with the new cache settings." if names else "No drive was connected."


def connect(name: str) -> tuple[bool, str]:
    exe, fuse = rclone(), fuse_cmd()
    if not exe:
        return False, "rclone is not installed."
    if not fuse:
        return False, "fuse3 is not installed (it provides fusermount3)."
    try:
        ensure_unit(exe, fuse)
    except OSError as e:
        return False, f"Could not write the systemd unit: {e}"
    r = _sc("enable", "--now", unit(name), timeout=90)
    invalidate()
    if r.returncode != 0:
        return False, f"Could not connect {name}: {_last(r.stderr)}. Details: journalctl --user -u {unit(name)}"
    note = block_trash(name)
    if bookmarks_enabled():
        add_bookmark(name)
        return True, f"{name} is connected. It is in Thunar's sidebar and at {mount_path(name)}.{note}"
    remove_bookmark(name)  # tidy up an entry left from before the sidebar entry was switched off
    return True, f"{name} is connected at {mount_path(name)}.{note}"


def disconnect(name: str) -> tuple[bool, str]:
    r = _sc("disable", "--now", unit(name), timeout=60)
    invalidate()
    if r.returncode != 0:
        return False, f"Could not disconnect {name}: {_last(r.stderr)}"
    return True, f"{name} is disconnected and will not start at login."


def remove(name: str) -> tuple[bool, str]:
    _sc("disable", "--now", unit(name), timeout=60)
    exe = rclone()
    r = _run([exe, "config", "delete", name]) if exe else None
    remove_bookmark(name)
    try:
        mount_path(name).rmdir()  # only succeeds when empty, so nothing of yours is ever deleted
    except OSError:
        pass
    invalidate()
    if r is not None and r.returncode != 0:
        return False, f"Could not remove {name}: {_last(r.stderr)}"
    return True, f"{name} was removed. The files in the cloud are untouched."


def open_folder(name: str | None, file_manager: str) -> tuple[bool, str]:
    path = mount_path(name) if name else mount_root()
    if name and not os.path.ismount(path):
        return False, f"{name} is not connected yet. Connect it first."
    try:
        path.mkdir(parents=True, exist_ok=True)
        subprocess.Popen([*shlex.split(file_manager or "thunar"), str(path)], start_new_session=True,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL)
    except (OSError, ValueError) as e:
        return False, f"Could not open the file manager: {e}"
    return True, f"Opened {path}."


# ---- creating accounts -----------------------------------------------------------------------------------
def _discard(name: str) -> None:
    exe = rclone()
    if exe:
        _run([exe, "config", "delete", name])


def setup_oauth(name: str, kind: str, status: Callable[[str], None], cancel: threading.Event) -> tuple[bool, str]:
    """Google Drive, OneDrive, Dropbox: rclone opens the browser for sign-in."""
    exe = rclone()
    if not exe:
        return False, "rclone is not installed."
    status("Waiting for you to sign in in your browser...")
    args = [exe, "config", "create", name, kind] + (["scope=drive"] if kind == "drive" else [])
    try:
        proc = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, stdin=subprocess.PIPE, text=True)
        try:  # any extra question rclone asks gets its default answer (an empty line)
            proc.stdin.write("\n" * 40)
            proc.stdin.close()
        except OSError:
            pass
    except OSError as e:
        return False, f"Could not start rclone: {e}"
    captured: list[str] = []
    threading.Thread(target=lambda: captured.extend(proc.stdout or []), daemon=True).start()
    deadline = time.monotonic() + 300
    while proc.poll() is None:
        if cancel.is_set() or time.monotonic() > deadline:
            proc.terminate()
            _discard(name)
            return False, "Cancelled." if cancel.is_set() else "Sign-in took too long, so it was stopped."
        time.sleep(0.3)
    if proc.returncode != 0:
        _discard(name)
        return False, f"Sign-in failed: {_last(''.join(captured))}"
    status("Signed in. Mounting the drive...")
    return connect(name)


def dav_url(kind: str, server: str, user: str) -> str:
    server = server.strip().rstrip("/")
    if kind in ("nextcloud", "owncloud") and "remote.php" not in server:
        return f"{server}/remote.php/dav/files/{urllib.parse.quote(user)}/"
    return server


def setup_dav(name: str, kind: str, server: str, user: str, password: str,
              status: Callable[[str], None], cancel: threading.Event) -> tuple[bool, str]:
    """Nextcloud, ownCloud and other WebDAV servers."""
    exe = rclone()
    if not exe:
        return False, "rclone is not installed."
    status("Saving the account...")
    obscured = _run([exe, "obscure", "-"], text_in=password).stdout.strip()
    if not obscured:
        return False, "rclone could not protect the password."
    url = dav_url(kind, server, user)
    vendor = kind if kind in ("nextcloud", "owncloud") else "other"
    if kind == "owncloud" and "/remote.php/dav/files/" in url:
        # rclone only uploads in chunks for Nextcloud, and ownCloud 10 speaks the same chunking. Without it every
        # file goes up in one request, and proxies such as Cloudflare (100 MB limit) refuse big ones forever.
        vendor = "nextcloud"
    made = _run([exe, "config", "create", name, "webdav", f"url={url}", f"vendor={vendor}",
                 f"user={user}", f"pass={obscured}"])
    if made.returncode != 0:
        _discard(name)
        return False, f"Could not save the account: {_last(made.stderr)}"
    status("Checking the address and password...")
    check = _run([exe, "lsd", f"{name}:", "--max-depth", "1"], timeout=40)
    if check.returncode != 0:
        _discard(name)
        return False, f"The server did not accept those details: {_last(check.stderr)}"
    if cancel.is_set():
        _discard(name)
        return False, "Cancelled."
    status("Mounting the drive...")
    return connect(name)
