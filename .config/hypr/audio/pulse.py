"""Everything the Sound app reads and changes about the PC's sound, through pactl (PipeWire's PulseAudio side): outputs
and inputs, the apps playing and recording, sound cards and their profiles, and a live input level.

No GTK here: the parse_* functions turn pactl's JSON into small dicts, so they can be tested on any machine with
pactl output saved from a real PC (tests/fixtures)."""

from __future__ import annotations

import json
import os
import struct
import subprocess
import threading

TIMEOUT = 5
MAX_VOLUME = 153  # percent (pavucontrol goes this far too); above 100 is software gain
OURS = "hyprdots"  # node and client names of the app's own filters and meters start with this
PEAK_STREAMS = {"Peak detect", "pavucontrol peak", "Peak meter"}  # other mixers' level meters, not apps


# ---- parsing --------------------------------------------------------------------------------------------------------
def _load(text: str) -> list:
    try:
        data = json.loads(text)
    except ValueError:
        return []
    return [d for d in data if isinstance(d, dict)] if isinstance(data, list) else []


def _volume(d: dict) -> int:
    levels = []
    for channel in (d.get("volume") or {}).values():
        try:
            levels.append(int(str(channel.get("value_percent", "0")).rstrip("%")))
        except (ValueError, AttributeError):
            pass
    return round(sum(levels) / len(levels)) if levels else 0


def parse_devices(text: str) -> list[dict]:
    """pactl -f json list sinks (or sources) -> [{index, name, description, volume (0-150), mute, monitor, ours,
    card, ports [(name, description, available)], port, state, icon, form}]."""
    found = []
    for d in _load(text):
        if "name" not in d:
            continue
        props = d.get("properties") or {}
        name = d["name"]
        ports = [(p.get("name", ""), p.get("description") or p.get("name", ""), p.get("availability") != "not available")
                 for p in d.get("ports") or [] if isinstance(p, dict)]
        found.append({
            "index": d.get("index"), "name": name, "description": d.get("description") or name,
            "volume": _volume(d), "mute": bool(d.get("mute")),
            "monitor": props.get("device.class") == "monitor" or name.endswith(".monitor"),
            "ours": name.startswith(OURS), "card": props.get("device.name", ""), "ports": ports,
            "port": d.get("active_port") or "", "state": d.get("state", ""),
            "icon": props.get("device.icon_name", ""), "form": props.get("device.form_factor", ""),
        })
    return found


def outputs(sinks: list[dict]) -> list[dict]:
    """Real outputs: not the app's own equaliser."""
    return [s for s in sinks if not s["ours"]]


def inputs(sources: list[dict]) -> list[dict]:
    """Real microphones and line-ins: not the monitors of outputs, not the app's own clean microphone."""
    return [s for s in sources if not s["monitor"] and not s["ours"]]


def parse_streams(text: str, device_key: str) -> list[dict]:
    """pactl -f json list sink-inputs (device_key "sink") or source-outputs ("source") -> apps playing or recording:
    [{index, app, title, icon, volume, mute, device (index), corked}]. Level meters and the app's own streams are left
    out: they are not something you would want to turn down."""
    found = []
    for s in _load(text):
        props = s.get("properties") or {}
        app = props.get("application.name") or props.get("application.process.binary") or props.get("node.name") or "App"
        title = props.get("media.name") or ""
        node = props.get("node.name") or ""
        if node.startswith(OURS) or app.startswith(OURS) or title in PEAK_STREAMS or props.get("stream.monitor") == "true":
            continue
        if title.lower() in {"playback", "recordstream", "record stream", app.lower(), "audio stream"}:
            title = ""
        found.append({"index": s.get("index"), "app": app, "title": title,
                      "icon": props.get("application.icon_name") or props.get("application.process.binary") or "",
                      "volume": _volume(s), "mute": bool(s.get("mute")), "device": s.get(device_key),
                      "corked": bool(s.get("corked"))})
    return found


def parse_cards(text: str) -> list[dict]:
    """pactl -f json list cards -> [{name, description, icon, profile, profiles [(name, description)]}], with only
    the profiles that can be used now (plus the one in use), best first, Off last."""
    found = []
    for c in _load(text):
        props = c.get("properties") or {}
        active = c.get("active_profile") or ""
        profiles = []
        for name, p in (c.get("profiles") or {}).items():
            if not isinstance(p, dict) or (not p.get("available", True) and name != active):
                continue
            profiles.append((name, p.get("description") or name, int(p.get("priority") or 0)))
        profiles.sort(key=lambda p: (p[0] == "off", -p[2]))
        found.append({"name": c.get("name", ""), "description": props.get("device.description") or c.get("name", ""),
                      "icon": props.get("device.icon_name", ""), "profile": active,
                      "profiles": [(n, d) for n, d, _p in profiles]})
    return found


def current(default: str, filter_node: str, filter_on: bool, filter_device: str | None) -> str:
    """The device in use: the default one, or the one behind the app's filter when that is the default."""
    if default == filter_node and filter_on and filter_device:
        return filter_device
    return default


def stand_in(devices: list[dict], default: str, filter_node: str, filter_on: bool, in_use: str) -> dict:
    """{device in use: the filter in front of it} while that filter is the default. The volume keys, the bar and the
    volume pop-up all change the default, so the device's row shows and sets the filter's volume, not the card's own
    level underneath, which nothing else shows."""
    if not filter_on or default != filter_node or in_use == filter_node:
        return {}
    found = next((d for d in devices if d["name"] == filter_node), None)
    return {in_use: found} if found else {}


def peak(chunk: bytes) -> float:
    """0-1: the loudest sample in a piece of s16le audio."""
    count = len(chunk) // 2
    if not count:
        return 0.0
    samples = struct.unpack(f"<{count}h", chunk[:count * 2])
    return min(1.0, max(abs(s) for s in samples) / 32768)


def meter_level(value: float) -> float:
    """A peak (0-1) as the meter shows it: in dB from -60 to 0, so quiet speech still moves it."""
    if value <= 0.001:
        return 0.0
    import math
    return max(0.0, min(1.0, (20 * math.log10(value) + 60) / 60))


# ---- reading --------------------------------------------------------------------------------------------------------
def pactl(*args: str, timeout: float = TIMEOUT) -> str:
    try:
        return subprocess.run(["pactl", *args], capture_output=True, text=True, timeout=timeout).stdout
    except (OSError, subprocess.SubprocessError):
        return ""


def sinks() -> list[dict]:
    return parse_devices(pactl("-f", "json", "list", "sinks"))


def sources() -> list[dict]:
    return parse_devices(pactl("-f", "json", "list", "sources"))


def defaults() -> tuple[str, str]:
    return pactl("get-default-sink").strip(), pactl("get-default-source").strip()


def snapshot() -> dict:
    """Everything the pages show, read in one go (off the main loop: each pactl call takes a moment)."""
    default_sink, default_source = defaults()
    return {"sinks": sinks(), "sources": sources(), "default_sink": default_sink, "default_source": default_source,
            "playing": parse_streams(pactl("-f", "json", "list", "sink-inputs"), "sink"),
            "recording": parse_streams(pactl("-f", "json", "list", "source-outputs"), "source"),
            "cards": parse_cards(pactl("-f", "json", "list", "cards"))}


# ---- changing -------------------------------------------------------------------------------------------------------
def _percent(value: int) -> str:
    return f"{max(0, min(MAX_VOLUME, int(value)))}%"


def set_volume(kind: str, name: str, percent: int) -> None:
    pactl(f"set-{kind}-volume", str(name), _percent(percent))


def set_mute(kind: str, name: str, mute: bool) -> None:
    pactl(f"set-{kind}-mute", str(name), "1" if mute else "0")


def set_default(kind: str, name: str) -> None:
    pactl(f"set-default-{kind}", name)


def set_port(kind: str, name: str, port: str) -> None:
    pactl(f"set-{kind}-port", name, port)


def set_stream_volume(kind: str, index: int, percent: int) -> None:
    """kind: "sink-input" (an app playing) or "source-output" (an app recording)."""
    pactl(f"set-{kind}-volume", str(index), _percent(percent))


def set_stream_mute(kind: str, index: int, mute: bool) -> None:
    pactl(f"set-{kind}-mute", str(index), "1" if mute else "0")


def move_stream(kind: str, index: int, device: str) -> None:
    pactl(f"move-{kind}", str(index), device)


def set_profile(card: str, profile: str) -> None:
    pactl("set-card-profile", card, profile)


# ---- watching -------------------------------------------------------------------------------------------------------
class Watcher:
    """Runs `pactl subscribe` and calls changed() (from its own thread) whenever a device, app or card changes, so
    the window can re-read at once instead of every few seconds."""

    def __init__(self, changed):
        self.changed, self.proc = changed, None

    def start(self):
        try:
            self.proc = subprocess.Popen(["pactl", "subscribe"], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                         text=True)
        except OSError:
            return
        threading.Thread(target=self._read, daemon=True).start()

    def _read(self):
        for line in self.proc.stdout:
            if "'change'" in line or "'new'" in line or "'remove'" in line:
                if not any(k in line for k in (" client ", " module ")):
                    self.changed()

    def stop(self):
        if self.proc:
            self.proc.terminate()


class Meter:
    """A live level for one input: parec at a low rate, the peak of each 40 ms. level(value 0-1) is called from its
    own thread. It shows in no app list (its name starts with hyprdots)."""

    RATE, CHUNK = 8000, 640  # 40 ms of s16le mono

    def __init__(self, level):
        self.level, self.proc, self.source = level, None, None

    def watch(self, source: str | None):
        if source == self.source and self.proc:
            return
        self.stop()
        self.source = source
        if not source:
            return
        env = {**os.environ, "PULSE_PROP": "application.id=hyprdots.meter media.role=phone"}
        try:
            self.proc = subprocess.Popen(
                ["parec", "--raw", "--format=s16le", "--channels=1", f"--rate={self.RATE}", "--latency-msec=40",
                 "--client-name=hyprdots-meter", "--stream-name=hyprdots-meter", "-d", source],
                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, env=env)
        except OSError:
            self.proc = None
            return
        proc = self.proc
        threading.Thread(target=self._read, args=(proc,), daemon=True).start()

    def _read(self, proc):
        while proc.poll() is None:
            chunk = proc.stdout.read(self.CHUNK)
            if not chunk:
                break
            self.level(peak(chunk))

    def stop(self):
        if self.proc:
            self.proc.terminate()
            self.proc = None
        self.source = None


class Loopback:
    """Hear yourself: plays an input straight to an output, to check how a microphone sounds. Stops with the app."""

    def __init__(self):
        self.proc = None

    def start(self, source: str, sink: str) -> bool:
        self.stop()
        try:
            self.proc = subprocess.Popen(["pw-loopback", "-n", "hyprdots-hear-yourself", "-C", source, "-P", sink,
                                          "-c", "1", "-m", "[ MONO ]", "-l", "40"],
                                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except OSError:
            self.proc = None
        return self.proc is not None

    def running(self) -> bool:
        return bool(self.proc and self.proc.poll() is None)

    def stop(self):
        if self.proc:
            self.proc.terminate()
            self.proc = None
