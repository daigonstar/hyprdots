"""Performance page: the mode and heat guard of hyprdots-power.service (install/power/powerd.py). The service runs as
root; this reads what it publishes, and changes its settings through pkexec, which asks for your password."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

SERVICE = Path("/usr/local/lib/hyprdots/powerd.py")
STATUS = Path("/run/hyprdots-power/status.json")
INSTALL = "sudo ~/hyprdots/install/power.sh"

MODES = (
    ("full", "Full speed", "As the PC was made to run: boost on and the graphics card at its full power. The heat guard still steps in."),
    ("balanced", "Balanced", "Boost on, but the CPU favours saving power, and the graphics card is held a little below full power."),
    ("cool", "Cool and stable", "Boost off and the graphics card at its lowest power limit. Slower, much cooler, and steadier in long games."),
)


def installed() -> bool:
    return SERVICE.exists()


def status() -> dict | None:
    """What the service last published, or None if it is not running. It writes every two seconds."""
    try:
        return json.loads(STATUS.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def change(**settings) -> tuple[bool, str]:
    """Saves settings through the service's own code, as root. Values: mode, guard (bool), cpu_limit, gpu_limit."""
    if not shutil.which("pkexec"):
        return False, "pkexec (polkit) is needed to change this."
    args = [f"{k}={('on' if v else 'off') if isinstance(v, bool) else v}" for k, v in settings.items()]
    try:
        p = subprocess.run(["pkexec", "/usr/bin/python3", str(SERVICE), "set", *args], capture_output=True, text=True, timeout=120)
    except (OSError, subprocess.SubprocessError) as e:
        return False, str(e)
    if p.returncode in (126, 127):
        return False, "Not changed: the password prompt was cancelled."
    return p.returncode == 0, (p.stdout.strip() or p.stderr.strip() or "Not changed.")


def ram_note(ram: dict) -> str:
    """A word about the RAM's speed, or "" when there is nothing to say."""
    if not ram.get("rated"):
        return ""
    if ram.get("above_rating"):
        return (f"Running at {ram['running']} MT/s, above its standard {ram['rated']} MT/s. That is fine for a kit sold to run "
                "faster (EXPO or XMP), but if you set it by hand and get freezes, put it back in the BIOS.")
    return f"Running at {ram['running']} MT/s, within its rating."
