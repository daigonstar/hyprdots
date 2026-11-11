"""The Health monitor's on/off: agent-monitor.timer, a systemd user timer, run from the units in ~/.config/systemd/user
(linked from the dots, as the installer does). Off stops and disables the timer; its settings stay as they are."""

from __future__ import annotations

import subprocess
from pathlib import Path

TIMER = "agent-monitor.timer"
UNITS = ("agent-monitor.service", "agent-monitor.timer")


def _systemctl(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["systemctl", "--user", *args], capture_output=True, text=True, timeout=30)


def is_on() -> bool:
    try:
        return _systemctl("is-enabled", "--quiet", TIMER).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def turn(on: bool, dots: Path | None = None, user_dir: Path | None = None) -> tuple[bool, str]:
    """Starts or stops the timer. Turning it on links its units first, for an install that said no to it."""
    try:
        if on:
            dots = dots or (Path.home() / ".config/hypr").resolve().parent / "systemd/user"  # the dots' own copy
            user_dir = user_dir or Path.home() / ".config/systemd/user"
            user_dir.mkdir(parents=True, exist_ok=True)
            for unit in UNITS:
                source, link = (dots / unit).resolve(), user_dir / unit
                if not source.exists():
                    return False, f"{unit} is missing from the dots."
                if not link.exists():
                    link.unlink(missing_ok=True)
                    link.symlink_to(source)
            _systemctl("daemon-reload")
            done = _systemctl("enable", "--now", TIMER)
        else:
            # disable also removes the link, as the unit lives in the dots; turning it on links it again
            done = _systemctl("disable", "--now", TIMER)
            _systemctl("reset-failed", TIMER)  # the timer gone from under it reads as failed, not off
    except (OSError, subprocess.SubprocessError) as e:
        return False, str(e)
    if done.returncode != 0:
        return False, done.stderr.strip() or "systemctl did not say why."
    return True, "Health monitor turned on." if on else "Health monitor turned off."
