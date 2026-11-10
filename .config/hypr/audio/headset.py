"""What the headset app knows about a wireless headset, through headsetcontrol (github.com/Sapd/HeadsetControl).

No GTK here, so the parsing and the charging guess can be tested on any machine. headset_app.py is the window, and
the quick tray uses read() and the battery history for its chip.

Most headsets only take settings (sidetone, lights...) and never report them back, so the values the app shows are
the ones last set here, kept in a small file. Some, like the Arctis 7, do not say whether they are charging either:
charging() guesses it from the battery level over time, which is why every reading is remembered for a while."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
from pathlib import Path

CACHE = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache")) / "hyprdots/headset.json"
TIMEOUT = 5
HISTORY_SECONDS = 3 * 3600  # how long readings are kept for the charging guess
RISING = 2  # percent the battery has to climb (or fall) before the guess trusts it
TREND_SECONDS = 20 * 60  # ...within this long

# capability name (headsetcontrol's capabilities_str) -> (label, what it does)
CONTROLS = {
    "sidetone": ("Sidetone", "How much of your own voice you hear in the headset."),
    "inactive time": ("Turn off after", "Minutes without sound before the headset switches itself off. 0 never does."),
    "lights": ("Lights", "The lights on the headset."),
    "equalizer preset": ("EQ preset", "One of the headset's built-in sound profiles."),
    "voice prompts": ("Voice prompts", "The spoken prompts, such as \"battery low\"."),
    "rotate to mute": ("Flip to mute", "Mutes the microphone when you raise its arm."),
    "microphone mute led brightness": ("Mute light", "How bright the microphone's mute light is."),
    "microphone volume": ("Microphone volume", "The headset's own microphone level."),
    "bluetooth when powered on": ("Bluetooth at power on", "Turns Bluetooth on when the headset starts."),
}
# capability -> headsetcontrol flag
FLAGS = {"sidetone": "-s", "inactive time": "-i", "lights": "-l", "equalizer preset": "-p", "voice prompts": "-v",
         "rotate to mute": "-r", "microphone mute led brightness": "--microphone-mute-led-brightness",
         "microphone volume": "--microphone-volume", "bluetooth when powered on": "--bt-when-powerd-on"}
# (low, high, step) for sliders; on/off controls are not here
RANGES = {"sidetone": (0, 128, 1), "inactive time": (0, 90, 5), "equalizer preset": (0, 3, 1),
          "microphone mute led brightness": (0, 3, 1), "microphone volume": (0, 128, 1)}
DEFAULTS = {"sidetone": 0, "inactive time": 10, "lights": 1, "equalizer preset": 0, "voice prompts": 1,
            "rotate to mute": 1, "microphone mute led brightness": 2, "microphone volume": 128,
            "bluetooth when powered on": 1}


def available() -> bool:
    return shutil.which("headsetcontrol") is not None


def _caps(device: dict) -> list[str]:
    """Capability names, lower case. Newer versions spell them in capabilities_str, older ones only as CAP_*."""
    names = device.get("capabilities_str")
    if not names:
        names = [c.removeprefix("CAP_").replace("_", " ") for c in device.get("capabilities", [])]
    return [str(n).lower().replace("_", " ") for n in names]


def parse(text: str) -> list[dict]:
    """headsetcontrol -o json -> one dict per headset:
    {name, product, id, capabilities, battery (0-100 or None), charging (True/None), status, chatmix, minutes_left}.
    minutes_left is headsetcontrol's own estimate (4.2 and later), None when it has none.
    battery is None when the headset is off or out of range: the dongle answers, the headset does not."""
    try:
        data = json.loads(text)
    except ValueError:
        return []
    found = []
    for device in data.get("devices", []) if isinstance(data, dict) else []:
        if not isinstance(device, dict):
            continue
        caps = _caps(device)
        battery = device.get("battery") if isinstance(device.get("battery"), dict) else {}
        state = str(battery.get("status", "")).upper()
        level = battery.get("level")
        level = level if isinstance(level, int) and 0 <= level <= 100 and state != "BATTERY_UNAVAILABLE" else None
        charging = True if state == "BATTERY_CHARGING" else None
        chatmix = device.get("chatmix")
        left = battery.get("time_to_empty_min")
        found.append({
            "name": (device.get("product") or device.get("device") or "Headset").strip(),
            "product": device.get("product") or device.get("device") or "",
            "id": f"{device.get('id_vendor', '')}:{device.get('id_product', '')}".replace("0x", ""),
            "capabilities": caps,
            "battery": level if "battery" in caps or level is not None else None,
            "charging": charging,
            "status": {"BATTERY_UNAVAILABLE": "off", "BATTERY_CHARGING": "charging", "BATTERY_AVAILABLE": "on",
                       "BATTERY_HIDERROR": "error", "BATTERY_TIMEOUT": "error"}.get(state, "on" if level is not None else "unknown"),
            "chatmix": chatmix if isinstance(chatmix, int) and 0 <= chatmix <= 128 else None,
            "minutes_left": left if isinstance(left, int) and left > 0 and level is not None else None,
        })
    return found


def chatmix_text(level: int | None) -> str:
    """headsetcontrol's 0-128: 0 all chat, 64 even, 128 all game (the Arctis dial)."""
    if level is None:
        return "Unknown"
    if abs(level - 64) <= 2:
        return "Even"
    game = round(100 * level / 128)
    return f"Game {game}% · Chat {100 - game}%"


def time_left_text(minutes: int | None) -> str:
    if not minutes:
        return ""
    hours, mins = divmod(minutes, 60)
    return f"About {hours} h {mins:02d} min left" if hours else f"About {mins} min left"


def run(*args: str, timeout: float = TIMEOUT) -> subprocess.CompletedProcess | None:
    try:
        return subprocess.run(["headsetcontrol", *args], capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.SubprocessError):
        return None


def read() -> list[dict]:
    """Every headset headsetcontrol can see right now; [] without it or without permission to the device."""
    out = run("-o", "json")
    return parse(out.stdout) if out and out.stdout else []


def set_control(capability: str, value: int) -> tuple[bool, str]:
    """Sends one setting. (worked, what headsetcontrol said when it did not)."""
    flag = FLAGS.get(capability)
    if not flag:
        return False, f"Unknown control: {capability}"
    out = run(flag, str(int(value)))
    if out is None:
        return False, "headsetcontrol is not installed"
    text = (out.stderr or out.stdout).strip()
    return out.returncode == 0 and "error" not in text.lower() and "failed" not in text.lower(), text


# ---- what is remembered: the settings last sent, and battery readings ------------------------------------------------
def load(path: Path = CACHE) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def save(data: dict, path: Path = CACHE) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(path.name + f".{os.getpid()}.tmp")
        tmp.write_text(json.dumps(data, indent=1), encoding="utf-8")
        os.replace(tmp, path)
    except OSError:
        pass


def save_own(data: dict, keys=("settings", "eq", "mic"), path: Path = CACHE) -> None:
    """Saves only these parts of data over what is on disk, so the window and the quick tray (which both write this
    file) do not undo each other's changes."""
    disk = load(path)
    disk.update({k: data[k] for k in keys if k in data})
    save(disk, path)


def record(product: str, level: int | None, path: Path = CACHE, now: float | None = None) -> list:
    """Adds a battery reading to the file as it is now, and returns that headset's history."""
    data = add_reading(load(path), product, level, now)
    save(data, path)
    return data["history"][product]


def remember_setting(data: dict, product: str, capability: str, value: int) -> dict:
    data.setdefault("settings", {}).setdefault(product, {})[capability] = int(value)
    return data


def setting(data: dict, product: str, capability: str) -> int:
    return int(data.get("settings", {}).get(product, {}).get(capability, DEFAULTS.get(capability, 0)))


def add_reading(data: dict, product: str, level: int | None, now: float | None = None) -> dict:
    """Keeps (time, level) readings for the last few hours. A None (headset off) is kept too: it breaks the trend,
    since the battery cannot be watched while the headset is off."""
    now = time.time() if now is None else now
    history = [r for r in data.setdefault("history", {}).get(product, []) if now - r[0] <= HISTORY_SECONDS]
    if not history or history[-1][1] != level or now - history[-1][0] >= 300:
        history.append([round(now), level])
    data["history"][product] = history
    return data


def charging(history: list, reported: bool | None = None, now: float | None = None) -> str:
    """'charging', 'discharging', 'full' or 'unknown', from what the headset said, or else from how its battery moved
    since it was last switched on. Needs RISING percent of change within TREND_SECONDS to call it either way."""
    if reported:
        return "charging"
    now = time.time() if now is None else now
    run_ = []
    for at, level in reversed(history):  # the latest readings, back to when the headset was last off
        if level is None:
            break
        if now - at > TREND_SECONDS and len(run_) >= 2:
            break
        if now - at > TREND_SECONDS and run_:  # only one recent reading: compare it with the one before
            run_.append((at, level))
            break
        run_.append((at, level))
    if not run_:
        return "unknown"
    latest = run_[0][1]
    if latest >= 100:
        return "full"
    oldest = run_[-1][1]
    if latest - oldest >= RISING:
        return "charging"
    if oldest - latest >= RISING:
        return "discharging"
    return "unknown"


CHARGING_TEXT = {"charging": "Charging", "discharging": "On battery", "full": "Full",
                 "unknown": "Not sure yet: watching the level"}


def peripheral(devices: list[dict] | None = None, path: Path = CACHE, now: float | None = None) -> dict | None:
    """The first headset as the quick tray lists wireless mice and keyboards, with the reading remembered so the
    charging guess carries on while the headset window is closed. None when there is no headset or it is off."""
    devices = read() if devices is None else devices
    if not devices:
        return None
    d = devices[0]
    product = d["product"] or d["name"]
    history = record(product, d["battery"], path, now)
    if d["battery"] is None:
        return None
    return {"model": d["name"], "capacity": d["battery"], "headset": True,
            "charging": charging(history, d["charging"], now)}
