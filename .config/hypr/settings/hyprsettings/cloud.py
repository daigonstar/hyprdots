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
ExecStart={exe} mount %i: "{root}/%i" --vfs-cache-mode full --dir-cache-time 5m --poll-interval 1m
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
    add_bookmark(name)
    return True, f"{name} is connected. It is in Thunar's sidebar and at {mount_path(name)}."


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
    vendor = kind if kind in ("nextcloud", "owncloud") else "other"
    made = _run([exe, "config", "create", name, "webdav", f"url={dav_url(kind, server, user)}", f"vendor={vendor}",
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
