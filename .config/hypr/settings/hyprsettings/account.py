"""User page: your name, picture and password. Passwords only pass through here on their way to passwd: never stored or logged."""

from __future__ import annotations

import os
import pty
import pwd
import re
import select
import subprocess
import time
from pathlib import Path

PICTURE_SIZE = 256
FACE = ".face"  # the usual place for it: the tray and lock screen read it, and other apps know it too


def username() -> str:
    return pwd.getpwuid(os.getuid()).pw_name


def real_name() -> str:
    """The name you go by, from the first part of the account's GECOS field. Empty if you never set one."""
    return pwd.getpwuid(os.getuid()).pw_gecos.split(",")[0].strip()


def picture_path() -> Path:
    return Path.home() / FACE


def _accounts(method: str, value: str) -> str:
    """AccountsService changes your own details without a password. Returns what went wrong, or ""."""
    try:
        done = subprocess.run(["busctl", "call", "org.freedesktop.Accounts", f"/org/freedesktop/Accounts/User{os.getuid()}",
                               "org.freedesktop.Accounts.User", method, "s", value], capture_output=True, text=True, timeout=20)
    except (OSError, subprocess.SubprocessError) as e:
        return str(e)
    return "" if done.returncode == 0 else done.stderr.strip()


def set_real_name(name: str) -> str:
    name = name.strip()
    if re.search(r"[,:\n]", name):
        raise ValueError("A name cannot contain a comma or a colon.")
    return _accounts("SetRealName", name)


def set_picture(source: str | Path) -> str:
    """Crops the middle of a picture to a square, and saves it as ~/.face. Also tells AccountsService, for the login screen."""
    import gi
    gi.require_version("GdkPixbuf", "2.0")
    from gi.repository import GdkPixbuf, GLib
    try:
        image = GdkPixbuf.Pixbuf.new_from_file(str(source)).apply_embedded_orientation()
    except GLib.Error as e:
        raise ValueError("That file cannot be opened as a picture.") from e
    side = min(image.get_width(), image.get_height())
    square = image.new_subpixbuf((image.get_width() - side) // 2, (image.get_height() - side) // 2, side, side)
    small = square.scale_simple(PICTURE_SIZE, PICTURE_SIZE, GdkPixbuf.InterpType.BILINEAR)
    target = picture_path()
    tmp = target.with_name(f"{FACE}.{os.getpid()}.tmp")
    small.savev(str(tmp), "png", [], [])
    os.replace(tmp, target)
    return _accounts("SetIconFile", str(target))


def remove_picture() -> str:
    picture_path().unlink(missing_ok=True)
    return _accounts("SetIconFile", "")


def _reason(output: str) -> str:
    bad = re.search(r"bad password: (.+)", output, re.I)
    if bad:
        return f"That new password was refused: {bad[1].strip()}."
    text = output.lower()
    if "locked" in text or "denied" in text:
        return "Too many wrong tries, so this is locked for a few minutes."
    if "authentication" in text:
        return "Your current password was not right."
    return "The password was not changed."


def change_password(current: str, new: str, timeout: float = 30) -> tuple[bool, str]:
    """Answers passwd's questions through a terminal, the only way it takes them. Returns (worked, what to tell you)."""
    main, other = pty.openpty()
    try:
        process = subprocess.Popen(["passwd"], stdin=other, stdout=other, stderr=other, start_new_session=True,
                                   env={**os.environ, "LC_ALL": "C"})
    except OSError as e:
        os.close(main)
        os.close(other)
        return False, f"Could not run passwd: {e}"
    os.close(other)
    answers = [(re.compile(r"current.*password:\s*$", re.I), current), (re.compile(r"retype.*password:\s*$", re.I), new),
               (re.compile(r"new password:\s*$", re.I), new)]
    output, pending, stop = "", "", time.monotonic() + timeout
    try:
        while time.monotonic() < stop:
            ready, _, _ = select.select([main], [], [], 0.2)
            if ready:
                try:
                    data = os.read(main, 4096)
                except OSError:  # the other end closed: passwd finished
                    break
                if not data:
                    break
                text = data.decode("utf-8", "replace")
                output += text
                pending += text
                for prompt, answer in answers:
                    if prompt.search(pending):
                        os.write(main, answer.encode() + b"\n")
                        pending = ""
                        break
            elif process.poll() is not None:
                break
        else:
            process.kill()
            return False, "passwd did not answer, so the password was not changed."
        code = process.wait(timeout=5)
    finally:
        os.close(main)
    return (True, "Password changed.") if code == 0 else (False, _reason(output))


def keyring_note() -> str:
    """The saved-passwords keyring opens with your login password, and passwd does not change it."""
    if (Path.home() / ".local/share/keyrings/login.keyring").exists():
        return "Your saved-passwords keyring still uses the old password, so apps may ask for it once at your next login."
    return ""
