#!/usr/bin/env python3
"""Keeps the CPU, graphics card and RAM inside safe limits. Runs as root (hyprdots-power.service), installed by
install/power.sh to /usr/local/lib/hyprdots, where only root can change it.

A mode sets CPU boost, the CPU's energy preference and the graphics card's power limit. The heat guard turns boost off
(and the card down to its lowest power limit) when either stays too hot, and puts them back once cooled: a CPU held at
95°C under a game froze this PC, and dropping boost fixed it. It also reports the RAM's speed against its rating, since
RAM run above its rating froze it too. The BIOS owns that one, so it is only reported.

  powerd.py                      the service
  powerd.py set mode=cool guard=on cpu_limit=92 gpu_limit=100
                                 as root (Settings runs it through pkexec): changes /etc/hyprdots/power.json
Settings and the quick tray read /run/hyprdots-power/status.json. Stdlib only: pkexec gives it a bare environment."""
import glob
import json
import os
import re
import signal
import subprocess
import sys
import time

SYS = os.environ.get("HYPRDOTS_SYS", "/sys")
CONFIG = os.environ.get("HYPRDOTS_POWER_CONFIG", "/etc/hyprdots/power.json")
RUN = os.environ.get("HYPRDOTS_POWER_RUN", "/run/hyprdots-power")
MODES = ("full", "balanced", "cool")
DEFAULTS = {"mode": "full", "guard": True, "cpu_limit": 92, "gpu_limit": 100}
LIMITS = {"cpu_limit": (70, 100), "gpu_limit": (70, 110)}
HOT_FOR = 15      # seconds over the limit before the guard steps in
COOL_BY = 15      # degrees under the limit before it lets go
COOL_FOR = 60     # seconds that cool before it lets go
TICK = 2


def read(path, default=""):
    try:
        with open(path) as f:
            return f.read().strip()
    except OSError:
        return default


FAILED = set()  # (path, value) already reported, so a write the kernel refuses is logged once, not every two seconds


def write(path, value):
    """Writes only a change: sysfs writes are not free, and this runs every two seconds."""
    if read(path, None) == str(value):
        return True
    try:
        with open(path, "w") as f:
            f.write(str(value))
        return True
    except OSError as e:
        if (path, str(value)) not in FAILED:
            FAILED.add((path, str(value)))
            print(f"Could not set {path} to {value}: {e.strerror or e}", file=sys.stderr, flush=True)
        return False


def load_config(path=None):
    try:
        with open(path or CONFIG) as f:
            raw = json.load(f)
    except (OSError, ValueError):
        raw = {}
    return validate({**DEFAULTS, **(raw if isinstance(raw, dict) else {})})


def validate(c):
    """Anything that is not one of the known values becomes the default: the file is only ever this program's."""
    out = dict(DEFAULTS)
    if c.get("mode") in MODES:
        out["mode"] = c["mode"]
    if isinstance(c.get("guard"), bool):
        out["guard"] = c["guard"]
    for key, (lo, hi) in LIMITS.items():
        value = c.get(key)
        if isinstance(value, int) and not isinstance(value, bool) and lo <= value <= hi:
            out[key] = value
    return out


# ---- the hardware --------------------------------------------------------------------------------------------------
def hwmon(name, need=None):
    """The hwmon folders called name, with the file need if given."""
    found = []
    for h in sorted(glob.glob(f"{SYS}/class/hwmon/hwmon*")):
        if read(f"{h}/name") == name and (need is None or os.path.exists(f"{h}/{need}")):
            found.append(h)
    return found


def temp_c(path):
    value = read(path)
    return round(int(value) / 1000, 1) if value.lstrip("-").isdigit() else None


def labelled(h, label):
    """temp*_input of the sensor with this label (amdgpu: edge, junction, mem; k10temp: Tctl)."""
    for f in sorted(glob.glob(f"{h}/temp*_label")):
        if read(f).lower() == label:
            return f[:-len("_label")] + "_input"
    return None


class Cpu:
    def __init__(self):
        self.sensor = None
        for name, label in (("k10temp", "tctl"), ("zenpower", "tdie"), ("coretemp", "package id 0")):
            for h in hwmon(name):
                self.sensor = labelled(h, label) or f"{h}/temp1_input"
                break
            if self.sensor:
                break
        amd, intel = f"{SYS}/devices/system/cpu/cpufreq/boost", f"{SYS}/devices/system/cpu/intel_pstate/no_turbo"
        self.boost_file, self.inverted = (amd, False) if os.path.exists(amd) else (intel, True) if os.path.exists(intel) else (None, False)
        # amd-pstate also has a switch for each group of cores, which the main one does not always reach
        self.policy_boost = sorted(glob.glob(f"{SYS}/devices/system/cpu/cpufreq/policy[0-9]*/boost")) if not self.inverted else []
        self.epp_files = sorted(glob.glob(f"{SYS}/devices/system/cpu/cpu[0-9]*/cpufreq/energy_performance_preference"))
        choices = read(f"{SYS}/devices/system/cpu/cpu0/cpufreq/energy_performance_available_preferences").split()
        self.epp_choices = set(choices)
        self.locked = False  # the BIOS has boost off (Core Performance Boost), so the kernel refuses to turn it on
        main = read(self.boost_file) if self.boost_file else None  # how it started, by the main switch
        self.original = {"boost": None if main is None else (main == "0") if self.inverted else (main == "1"),
                         "epp": read(self.epp_files[0]) if self.epp_files else None}

    def temp(self):
        return temp_c(self.sensor) if self.sensor else None

    def boost(self):
        """On only if every switch says so."""
        if not self.boost_file:
            return None
        if self.inverted:
            return read(self.boost_file) == "0"
        return all(read(f) == "1" for f in [self.boost_file, *self.policy_boost])

    def set_boost(self, on):
        if not self.boost_file or (on and self.locked):
            return
        if not write(self.boost_file, ("0" if on else "1") if self.inverted else ("1" if on else "0")) and on:
            self.locked = True
            print("The BIOS has boost turned off, so it stays off until that is changed.", file=sys.stderr, flush=True)
            return
        for f in self.policy_boost:
            write(f, "1" if on else "0")

    def set_epp(self, wanted):
        if wanted in self.epp_choices:
            for f in self.epp_files:
                write(f, wanted)

    def epp(self):
        return read(self.epp_files[0]) if self.epp_files else None


class Gpu:
    """The graphics card with the highest default power limit: on a PC with two, the separate card."""
    def __init__(self):
        cards = hwmon("amdgpu", "power1_cap")
        cards.sort(key=lambda h: int(read(f"{h}/power1_cap_default", "0") or 0))
        self.h = cards[-1] if cards else None
        if self.h:
            self.default = int(read(f"{self.h}/power1_cap_default"))
            self.lowest = int(read(f"{self.h}/power1_cap_min", "0") or 0) or self.default
            self.original = int(read(f"{self.h}/power1_cap") or self.default)
            self.sensor = labelled(self.h, "junction") or labelled(self.h, "edge") or f"{self.h}/temp1_input"

    def temp(self):
        return temp_c(self.sensor) if self.h else None

    def cap(self):
        return int(read(f"{self.h}/power1_cap") or 0) if self.h else None

    def set_cap(self, microwatts):
        if self.h:
            write(f"{self.h}/power1_cap", max(self.lowest, min(self.default, int(microwatts))))


def ram_temp():
    temps = [temp_c(f"{h}/temp1_input") for h in hwmon("spd5118") + hwmon("jc42")]
    temps = [t for t in temps if t is not None]
    return max(temps) if temps else None


def ram_speeds(text=None):
    """{rated, running} in MT/s from dmidecode, the slowest stick's. Rated is the module's own standard speed, so a
    kit sold to run faster (EXPO or XMP) also shows as above it."""
    if text is None:
        try:
            text = subprocess.run(["dmidecode", "-t", "memory"], capture_output=True, text=True, timeout=10).stdout
        except (OSError, subprocess.SubprocessError):
            return {}
    rated, running = [], []
    for block in text.split("\n\n"):
        if "Memory Device" not in block or re.search(r"^\s*Size: No Module", block, re.M):
            continue
        r = re.search(r"^\s*Speed: (\d+) MT/s", block, re.M)
        c = re.search(r"^\s*Configured (?:Memory|Clock) Speed: (\d+) MT/s", block, re.M)
        if r:
            rated.append(int(r[1]))
        if c:
            running.append(int(c[1]))
    if not rated or not running:
        return {}
    return {"rated": min(rated), "running": min(running), "above_rating": min(running) > min(rated)}


# ---- what each mode asks for ---------------------------------------------------------------------------------------
def targets(mode, cpu, gpu):
    """{boost, epp, gpu_cap}: None leaves that one as the PC started."""
    if mode == "cool":
        return {"boost": False, "epp": "power", "gpu_cap": gpu.lowest if gpu.h else None}
    if mode == "balanced":
        return {"boost": True, "epp": "balance_power", "gpu_cap": max(gpu.lowest, gpu.default * 9 // 10) if gpu.h else None}
    return {"boost": True, "epp": cpu.original["epp"], "gpu_cap": gpu.default if gpu.h else None}


class Guard:
    """Steps in after HOT_FOR seconds at or above the limit, and lets go after COOL_FOR seconds COOL_BY degrees under it."""
    def __init__(self):
        self.active, self.hot_since, self.cool_since = False, None, None

    def update(self, temp, limit, now):
        if temp is None:
            return self.active
        if not self.active:
            self.hot_since = (now if self.hot_since is None else self.hot_since) if temp >= limit else None
            if self.hot_since is not None and now - self.hot_since >= HOT_FOR:
                self.active, self.cool_since = True, None
        else:
            self.cool_since = (now if self.cool_since is None else self.cool_since) if temp <= limit - COOL_BY else None
            if self.cool_since is not None and now - self.cool_since >= COOL_FOR:
                self.active, self.hot_since = False, None
        return self.active


class Service:
    def __init__(self):
        self.cpu, self.gpu = Cpu(), Gpu()
        self.cpu_guard, self.gpu_guard = Guard(), Guard()
        self.ram = ram_speeds()
        self.events = []

    def event(self, text):
        self.events = (self.events + [{"time": int(time.time()), "text": text}])[-10:]

    def step(self, config, now):
        cpu, gpu = self.cpu, self.gpu
        want = targets(config["mode"], cpu, gpu)
        cpu_t, gpu_t = cpu.temp(), gpu.temp()
        for guard, temp, limit, part in ((self.cpu_guard, cpu_t, config["cpu_limit"], "CPU"),
                                         (self.gpu_guard, gpu_t, config["gpu_limit"], "graphics card")):
            was = guard.active
            now_active = guard.update(temp, limit, now) if config["guard"] else False
            guard.active = now_active
            if now_active and not was:
                self.event(f"The {part} stayed at {temp:.0f}°C, so it is held back until it cools.")
            elif was and not now_active:
                self.event(f"The {part} has cooled, so it is back to normal.")
        if self.cpu_guard.active:
            want["boost"] = False
        if self.gpu_guard.active and gpu.h:
            want["gpu_cap"] = gpu.lowest
        if want["boost"] is not None:
            cpu.set_boost(want["boost"])
        if want["epp"]:
            cpu.set_epp(want["epp"])
        if want["gpu_cap"]:
            gpu.set_cap(want["gpu_cap"])
        rt = ram_temp()
        return {
            "time": int(now), "config": config, "events": self.events,
            "cpu": {"temp": cpu_t, "boost": cpu.boost(), "epp": cpu.epp(), "held_back": self.cpu_guard.active,
                    "can_boost": cpu.boost_file is not None, "boost_locked": cpu.locked},
            "gpu": {"temp": gpu_t, "cap_w": gpu.cap() // 1000000 if gpu.h else None, "lowest_w": gpu.lowest // 1000000 if gpu.h else None,
                    "default_w": gpu.default // 1000000 if gpu.h else None, "held_back": self.gpu_guard.active},
            "ram": {**self.ram, "temp": rt},
        }

    def restore(self):
        """As the PC started: the service stopping must not leave boost off or the card held back."""
        if self.cpu.original["boost"] is not None:
            self.cpu.set_boost(self.cpu.original["boost"])
        if self.cpu.original["epp"]:
            self.cpu.set_epp(self.cpu.original["epp"])
        if self.gpu.h:
            self.gpu.set_cap(self.gpu.original)


def publish(status):
    os.makedirs(RUN, exist_ok=True)
    tmp = f"{RUN}/status.json.tmp"
    with open(tmp, "w") as f:
        json.dump(status, f)
    os.chmod(tmp, 0o644)
    os.replace(tmp, f"{RUN}/status.json")


def serve():
    service = Service()
    stopping = []
    signal.signal(signal.SIGTERM, lambda *_: stopping.append(1))
    signal.signal(signal.SIGINT, lambda *_: stopping.append(1))
    while not stopping:
        publish(service.step(load_config(), time.time()))
        time.sleep(TICK)
    service.restore()


def set_config(pairs):
    """powerd.py set key=value ...: run as root, writes the config this service reads."""
    config = load_config()
    for pair in pairs:
        key, _, value = pair.partition("=")
        if key == "mode":
            config["mode"] = value
        elif key == "guard":
            config["guard"] = value in ("on", "true", "1")
        elif key in LIMITS and value.isdigit():
            config[key] = int(value)
        else:
            sys.exit(f"Unknown setting: {pair}")
    checked = validate(config)
    if checked != config:
        sys.exit("That value is out of range.")
    os.makedirs(os.path.dirname(CONFIG), exist_ok=True)
    tmp = CONFIG + ".tmp"
    with open(tmp, "w") as f:
        json.dump(checked, f, indent=2)
    os.chmod(tmp, 0o644)
    os.replace(tmp, CONFIG)
    print("Saved.")


if __name__ == "__main__":
    if sys.argv[1:2] == ["set"]:
        if os.geteuid() != 0 and not os.environ.get("HYPRDOTS_POWER_CONFIG"):
            sys.exit("Run this as root.")
        set_config(sys.argv[2:])
    else:
        serve()
