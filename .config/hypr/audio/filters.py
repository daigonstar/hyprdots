"""The Sound app's two PipeWire filters: an equaliser for the output you use, and a cleaned-up microphone. No GTK
here, so the parts that make text can be tested anywhere.

Most headsets (the Arctis 7 included) have no equaliser of their own, so this one is a PipeWire filter: an output
called Equaliser that passes everything through ten bands and on to the real output. It runs as its own small
PipeWire process (a systemd user service, hyprdots-eq), so it comes back after a login. Moving a slider changes the
running filter at once (pw-cli set-param); the config file is rewritten as well, for the next start.

The microphone filter is the same idea the other way round: RNNoise (the noise-suppression-for-voice package) between
your microphone and a new input, Clean microphone, which takes out keyboards, fans and background noise."""

from __future__ import annotations

import json
import math
import os
import shutil
import subprocess
import time
from pathlib import Path

import pulse

STATE = Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local/state")) / "hyprdots"
EQ_CONF = STATE / "eq.conf"
MIC_CONF = STATE / "clean-mic.conf"
EQ_UNIT, MIC_UNIT = "hyprdots-eq.service", "hyprdots-clean-mic.service"
EQ_NODE, MIC_NODE = "hyprdots_eq", "hyprdots_clean_mic"
RNNOISE = Path("/usr/lib/ladspa/librnnoise_ladspa.so")
TIMEOUT = 5

# (Hz, label): ten peaking bands an octave apart, like a graphic equaliser
BANDS = [(31, "31"), (62, "62"), (125, "125"), (250, "250"), (500, "500"), (1000, "1k"), (2000, "2k"), (4000, "4k"),
         (8000, "8k"), (16000, "16k")]
Q = 1.41
GAIN_LIMIT = 12
PRESETS = {
    "Flat": [0, 0, 0, 0, 0, 0, 0, 0, 0, 0],
    "Bass boost": [6, 5, 4, 2, 0, 0, 0, 0, 0, 0],
    "Footsteps": [-4, -3, -2, 0, 0, 1, 3, 5, 3, 0],  # less rumble, more of the 2-4 kHz where steps and reloads are
    "Voice": [-6, -4, -2, 0, 1, 3, 4, 3, 1, 0],  # chat and podcasts: speech forward, boom out
    "Music": [4, 3, 1, 0, -1, -1, 0, 2, 3, 3],  # a gentle V
    "Treble": [0, 0, 0, 0, 0, 0, 1, 3, 5, 6],
    "Arctis warm": [3, 3, 2, 1, 0, 0, -1, -1, 1, 2],
}
CUSTOM = "Custom"

HEADER = """context.properties = { log.level = 0 }
context.spa-libs = { audio.convert.* = audioconvert/libspa-audioconvert support.* = support/libspa-support }
context.modules = [
  { name = libpipewire-module-rt args = { nice.level = -11 } flags = [ ifexists nofail ] }
  { name = libpipewire-module-protocol-native }
  { name = libpipewire-module-client-node }
  { name = libpipewire-module-adapter }
"""


# ---- the equaliser ----------------------------------------------------------------------------------------------------
def clamp(gains: list) -> list[float]:
    gains = [float(g) for g in gains][:len(BANDS)]
    gains += [0.0] * (len(BANDS) - len(gains))
    return [max(-GAIN_LIMIT, min(GAIN_LIMIT, round(g, 1))) for g in gains]


HEADROOM = 0.5  # how much of the biggest boost the level comes down by


def headroom_db(gains: list) -> float:
    """dB the level comes down in front of the bands. All of the biggest boost would never clip, but then a boost only
    makes the rest quieter; half of it keeps a boost sounding like one and still leaves room for loud bass."""
    return round(max(0.0, *clamp(gains)) * HEADROOM, 1)


def preamp(gains: list) -> float:
    """The linear gain in front of the bands."""
    return round(10 ** (-headroom_db(gains) / 20), 4)


def preset_of(gains: list) -> str:
    gains = clamp(gains)
    return next((name for name, g in PRESETS.items() if clamp(g) == gains), CUSTOM)


def _band(i: int) -> str:
    return f"b{i + 1}"


def eq_params(gains: list) -> dict[str, float]:
    """The filter's controls, as pw-cli set-param takes them."""
    gains = clamp(gains)
    return {"pre:Mult": preamp(gains), **{f"{_band(i)}:Gain": g for i, g in enumerate(gains)}}


def _string(text: str) -> str:
    return json.dumps(str(text))  # SPA JSON takes JSON strings


def eq_conf(gains: list, target: str, description: str) -> str:
    """A PipeWire config for `pipewire -c`: a stereo sink that runs the bands and plays into target (a sink's name)."""
    gains = clamp(gains)
    # linear (out = in x Mult) has one input; a mixer has eight, which leaves the filter unable to map the two channels
    # onto the graph, and it plays silence
    nodes = [f'          {{ type = builtin name = pre label = linear control = {{ "Mult" = {preamp(gains)} "Add" = 0.0 }} }}']
    for i, ((freq, _label), gain) in enumerate(zip(BANDS, gains)):
        nodes.append(f'          {{ type = builtin name = {_band(i)} label = bq_peaking '
                     f'control = {{ "Freq" = {float(freq)} "Q" = {Q} "Gain" = {gain} }} }}')
    links = ['          { output = "pre:Out" input = "b1:In" }'] + [
        f'          {{ output = "{_band(i)}:Out" input = "{_band(i + 1)}:In" }}' for i in range(len(BANDS) - 1)]
    return (HEADER + "  { name = libpipewire-module-filter-chain\n    args = {\n"
            f"      node.description = {_string(description)}\n      media.name = {_string(description)}\n"
            "      filter.graph = {\n        nodes = [\n" + "\n".join(nodes) + "\n        ]\n        links = [\n"
            + "\n".join(links) + "\n        ]\n"
            f'        inputs = [ "pre:In" ]\n        outputs = [ "{_band(len(BANDS) - 1)}:Out" ]\n      }}\n'
            "      audio.channels = 2\n      audio.position = [ FL FR ]\n"
            f"      capture.props = {{ node.name = {_string(EQ_NODE)} media.class = Audio/Sink }}\n"
            f"      playback.props = {{ node.name = {_string(EQ_NODE + '.out')} node.passive = true "
            f"target.object = {_string(target)} node.dont-reconnect = true }}\n"
            "    }\n  }\n]\n")


def set_param_text(params: dict[str, float]) -> str:
    return "{ params = [ " + " ".join(f"{_string(k)} {v}" for k, v in params.items()) + " ] }"


def response(gains: list, freq: float, rate: int = 48000) -> float:
    """The EQ's gain in dB at freq, for drawing its curve: the same peaking biquads PipeWire runs, and the preamp."""
    gains = clamp(gains)
    total = 20 * math.log10(preamp(gains))
    w = 2 * math.pi * freq / rate
    for (f0, _l), gain in zip(BANDS, gains):
        if not gain:
            continue
        a = 10 ** (gain / 40)
        w0 = 2 * math.pi * f0 / rate
        alpha = math.sin(w0) / (2 * Q)
        c = math.cos(w0)
        b0, b1, b2 = 1 + alpha * a, -2 * c, 1 - alpha * a
        a0, a1, a2 = 1 + alpha / a, -2 * c, 1 - alpha / a
        z1, z2 = complex(math.cos(-w), math.sin(-w)), complex(math.cos(-2 * w), math.sin(-2 * w))
        h = (b0 + b1 * z1 + b2 * z2) / (a0 + a1 * z1 + a2 * z2)
        total += 20 * math.log10(max(abs(h), 1e-9))
    return total


# ---- the clean microphone ---------------------------------------------------------------------------------------------
def can_clean_mic() -> bool:
    return RNNOISE.exists()


def mic_conf(source: str, threshold: int = 50) -> str:
    """RNNoise between source (a microphone's name) and a new source called Clean microphone. threshold is how sure
    it has to be that you are speaking (0-99): higher cuts more, and can clip the start of words."""
    threshold = max(0, min(99, int(threshold)))
    return (HEADER + "  { name = libpipewire-module-filter-chain\n    args = {\n"
            '      node.description = "Clean microphone"\n      media.name = "Clean microphone"\n'
            "      filter.graph = {\n        nodes = [\n"
            f'          {{ type = ladspa name = rnnoise plugin = {_string(RNNOISE)} label = noise_suppressor_mono '
            f'control = {{ "VAD Threshold (%)" = {float(threshold)} }} }}\n'
            "        ]\n      }\n      audio.channels = 1\n      audio.position = [ MONO ]\n"
            f"      capture.props = {{ node.name = {_string(MIC_NODE + '.in')} node.passive = true "
            f"target.object = {_string(source)} node.dont-reconnect = true }}\n"
            f"      playback.props = {{ node.name = {_string(MIC_NODE)} media.class = Audio/Source }}\n"
            "    }\n  }\n]\n")


# ---- the headset's own outputs and microphone ------------------------------------------------------------------------
def _key(product: str) -> str:
    return product.strip().replace(" ", "_").lower()


def headset_parts(sinks: list[dict], sources: list[dict], product: str) -> dict:
    """{game, chat, mic}: a headset's own outputs and microphone (from pulse.parse_devices), by name, or None. A
    headset with one output has it as game. The Arctis has a stereo Game output and a mono Chat one, which the ChatMix
    dial balances."""
    key = _key(product)
    mine = [s for s in sinks if key and key in s["name"].lower()]
    chat = next((s["name"] for s in mine if "chat" in s["name"].lower()), None)
    game = next((s["name"] for s in mine if s["name"] != chat and "game" in s["name"].lower()), None) \
        or next((s["name"] for s in mine if s["name"] != chat), None)
    mic = next((s["name"] for s in sources if key and key in s["name"].lower() and not s["monitor"]), None)
    return {"game": game, "chat": chat, "mic": mic}


# ---- running the filters ----------------------------------------------------------------------------------------------
def _systemctl(*args: str) -> subprocess.CompletedProcess | None:
    try:
        return subprocess.run(["systemctl", "--user", *args], capture_output=True, text=True, timeout=15)
    except (OSError, subprocess.SubprocessError):
        return None


def installed(unit: str) -> bool:
    """The unit from the dots (desktop-services.sh links them in). Without it, filters still run, until logout."""
    out = _systemctl("cat", unit)
    return bool(out and out.returncode == 0)


def running(unit: str) -> bool:
    out = _systemctl("is-active", unit)
    return bool(out and out.stdout.strip() == "active")


def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + f".{os.getpid()}.tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def start(unit: str, conf: Path, text: str) -> bool:
    """Writes the config and (re)starts its filter, kept on after a login when the unit is installed."""
    write(conf, text)
    if installed(unit):
        _systemctl("enable", unit)
        out = _systemctl("restart", unit)
    else:
        _systemctl("stop", unit)
        _systemctl("reset-failed", unit)
        try:
            out = subprocess.run(["systemd-run", "--user", f"--unit={unit}", "--collect", "-p", "BindsTo=pipewire.service",
                                  "-p", "After=pipewire.service", "/usr/bin/pipewire", "-c", str(conf)],
                                 capture_output=True, text=True, timeout=15)
        except (OSError, subprocess.SubprocessError):
            return False
    return bool(out and out.returncode == 0)


def stop(unit: str) -> None:
    if installed(unit):
        _systemctl("disable", "--now", unit)
    else:
        _systemctl("stop", unit)


def node_id(node_name: str) -> int | None:
    try:
        out = subprocess.run(["pw-dump"], capture_output=True, text=True, timeout=TIMEOUT).stdout
        for obj in json.loads(out):
            if obj.get("info", {}).get("props", {}).get("node.name") == node_name:
                return obj["id"]
    except (OSError, subprocess.SubprocessError, ValueError, KeyError, TypeError):
        pass
    return None


def wait_for(node_name: str, seconds: float = 4.0) -> int | None:
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        found = node_id(node_name)
        if found is not None:
            return found
        time.sleep(0.2)
    return None


def set_live(node_name: str, params: dict[str, float]) -> bool:
    """Changes a running filter's controls without restarting it (no gap in the sound)."""
    found = node_id(node_name)
    if found is None or not shutil.which("pw-cli"):
        return False
    try:
        out = subprocess.run(["pw-cli", "set-param", str(found), "Props", set_param_text(params)],
                             capture_output=True, text=True, timeout=TIMEOUT)
    except (OSError, subprocess.SubprocessError):
        return False
    return out.returncode == 0


def eq_on(gains: list, target: str, description: str) -> bool:
    """Starts the equaliser in front of target and makes it the sound output, so what is playing moves onto it."""
    if not start(EQ_UNIT, EQ_CONF, eq_conf(gains, target, description)):
        return False
    if wait_for(EQ_NODE) is None:
        return False
    pulse.set_default("sink", EQ_NODE)
    return True


def eq_change(gains: list, target: str, description: str) -> bool:
    """A slider moved: change the running filter, and keep the change for its next start."""
    write(EQ_CONF, eq_conf(gains, target, description))
    return set_live(EQ_NODE, eq_params(gains))


def eq_off(target: str | None) -> None:
    was_default = pulse.defaults()[0] == EQ_NODE
    stop(EQ_UNIT)
    if target and was_default:
        pulse.set_default("sink", target)


def mic_on(source: str, threshold: int) -> bool:
    if not can_clean_mic() or not start(MIC_UNIT, MIC_CONF, mic_conf(source, threshold)):
        return False
    if wait_for(MIC_NODE) is None:
        return False
    pulse.set_default("source", MIC_NODE)
    return True


def mic_off(source: str | None) -> None:
    was_default = pulse.defaults()[1] == MIC_NODE
    stop(MIC_UNIT)
    if source and was_default:
        pulse.set_default("source", source)
