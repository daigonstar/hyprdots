"""What the quick tray reads from the PC: hardware checks and the system monitor numbers, from /proc and /sys.
No GTK here, and the roots can be swapped, so the laptop and desktop cases can both be tested on any machine."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

SYS = Path("/sys")
PROC = Path("/proc")
PORTABLE_CHASSIS = {"8", "9", "10", "11", "14", "30", "31", "32"}  # SMBIOS: portable, laptop, notebook, tablet...
LOCAL_FILESYSTEMS = {"ext2", "ext3", "ext4", "btrfs", "xfs", "f2fs", "ntfs", "ntfs3", "vfat", "exfat", "zfs", "bcachefs"}
VIRTUAL_NET = ("lo", "docker", "br-", "veth", "virbr", "vmnet", "vboxnet", "tun", "tap", "wg")
CPU_SENSORS = ("k10temp", "zenpower", "coretemp")
BATTERY_STEPS = ((3, "sleep"), (5, "critical"), (15, "low"))  # percent, lowest first
PERIPHERAL_LOW = 10


def _read(path: Path, default: str = "") -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace").strip()
    except OSError:
        return default


def _int(path: Path) -> int | None:
    try:
        return int(_read(path))
    except ValueError:
        return None


def batteries(sys: Path = SYS) -> list[dict]:
    """Every battery the kernel knows. Wireless mice and keyboards are listed here too, with scope "Device"."""
    found = []
    root = sys / "class/power_supply"
    for d in sorted(root.iterdir()) if root.is_dir() else []:
        if _read(d / "type") != "Battery":
            continue
        found.append({"name": d.name, "model": _read(d / "model_name") or d.name, "capacity": _int(d / "capacity"),
                      "status": _read(d / "status"), "scope": _read(d / "scope", "System")})
    return found


def system_battery(sys: Path = SYS) -> dict | None:
    return next((b for b in batteries(sys) if b["scope"] != "Device"), None)


def peripherals(sys: Path = SYS) -> list[dict]:
    return [b for b in batteries(sys) if b["scope"] == "Device" and b["capacity"] is not None]


def battery_alert(capacity: int | None, status: str, reached: int | None) -> tuple[str | None, int | None]:
    """What to say about the PC's own battery now, and the step to remember: (alert, reached). Each step speaks once as
    the battery runs down, and plugging in starts over."""
    if capacity is None or status != "Discharging":
        return None, None
    for percent, alert in BATTERY_STEPS:
        if capacity <= percent:
            return (alert, percent) if reached is None or percent < reached else (None, reached)
    return None, None


def peripheral_alert(capacity: int, warned: bool) -> tuple[bool, bool]:
    """(say it now, remember it) for a wireless mouse or keyboard. Readings wobble, so it has to recover before it can
    warn again."""
    if capacity <= PERIPHERAL_LOW:
        return not warned, True
    return False, warned and capacity <= PERIPHERAL_LOW + 5


def is_laptop(sys: Path = SYS) -> bool:
    """A portable case, or a battery that powers the PC itself. A battery in a wireless mouse does not count."""
    return _read(sys / "class/dmi/id/chassis_type") in PORTABLE_CHASSIS or system_battery(sys) is not None


def backlight(sys: Path = SYS) -> bool:
    root = sys / "class/backlight"
    return root.is_dir() and any(root.iterdir())


def has_bluetooth(sys: Path = SYS) -> bool:
    root = sys / "class/bluetooth"
    return root.is_dir() and any(root.iterdir())


def cpu_times(proc: Path = PROC) -> tuple[int, int]:
    """(busy, total) jiffies since boot."""
    fields = [int(x) for x in _read(proc / "stat").splitlines()[0].split()[1:9]]
    idle = fields[3] + fields[4]
    return sum(fields) - idle, sum(fields)


def percent_between(before: tuple[int, int], after: tuple[int, int]) -> float:
    total = after[1] - before[1]
    return max(0.0, min(100.0, 100 * (after[0] - before[0]) / total)) if total > 0 else 0.0


def memory(proc: Path = PROC) -> tuple[int, int]:
    """(used, total) bytes. Used leaves out what the kernel can take back (caches), like `free` does."""
    info = {}
    for line in _read(proc / "meminfo").splitlines():
        key, _, rest = line.partition(":")
        info[key] = int(rest.split()[0]) * 1024 if rest.split() else 0
    total = info.get("MemTotal", 0)
    return total - info.get("MemAvailable", 0), total


def net_bytes(proc: Path = PROC) -> tuple[int, int]:
    """(received, sent) bytes since boot on real network cards, so containers are not counted twice."""
    rx = tx = 0
    for line in _read(proc / "net/dev").splitlines()[2:]:
        name, _, rest = line.partition(":")
        if name.strip().startswith(VIRTUAL_NET):
            continue
        fields = rest.split()
        rx += int(fields[0])
        tx += int(fields[8])
    return rx, tx


def cpu_temp(sys: Path = SYS) -> float | None:
    root = sys / "class/hwmon"
    for d in sorted(root.iterdir()) if root.is_dir() else []:
        if _read(d / "name") in CPU_SENSORS:
            milli = _int(d / "temp1_input")
            if milli is not None:
                return milli / 1000
    return None


def main_gpu(sys: Path = SYS) -> Path | None:
    """The card with the most video memory, so a graphics card wins over the CPU's built-in graphics."""
    best, best_vram = None, 0
    root = sys / "class/drm"
    for d in sorted(root.glob("card[0-9]*")) if root.is_dir() else []:
        vram = _int(d / "device/mem_info_vram_total")
        if vram and vram > best_vram and (d / "device/gpu_busy_percent").exists():
            best, best_vram = d / "device", vram
    return best


def gpu(sys: Path = SYS) -> dict | None:
    """busy %, memory used, memory total and temperature, or None when this PC's GPU cannot report them."""
    dev = main_gpu(sys)
    if dev is not None:
        temp = None
        for hw in sorted((dev / "hwmon").glob("hwmon*")):
            milli = _int(hw / "temp1_input")
            temp = milli / 1000 if milli is not None else None
        return {"busy": _int(dev / "gpu_busy_percent") or 0, "used": _int(dev / "mem_info_vram_used") or 0,
                "total": _int(dev / "mem_info_vram_total") or 0, "temp": temp}
    return _nvidia()


def _nvidia() -> dict | None:
    if not shutil.which("nvidia-smi"):
        return None
    query = "--query-gpu=utilization.gpu,memory.used,memory.total,temperature.gpu"
    try:
        out = subprocess.run(["nvidia-smi", query, "--format=csv,noheader,nounits"], capture_output=True, text=True,
                             timeout=3).stdout
        busy, used, total, temp = (float(x) for x in out.splitlines()[0].split(","))
    except (OSError, subprocess.SubprocessError, ValueError, IndexError):
        return None
    return {"busy": int(busy), "used": int(used * 1048576), "total": int(total * 1048576), "temp": temp}


def disks(proc: Path = PROC, limit: int = 4) -> list[dict]:
    """Mounted local drives, once each (a btrfs drive is mounted many times)."""
    seen, found = set(), []
    for line in _read(proc / "mounts").splitlines():
        device, mount, fstype, *_ = line.split()
        mount = mount.replace("\\040", " ")
        if fstype not in LOCAL_FILESYSTEMS or device in seen or mount.startswith(("/boot", "/efi")):
            continue
        seen.add(device)
        try:
            st = os.statvfs(mount)
        except OSError:
            continue
        total = st.f_blocks * st.f_frsize
        if total:
            found.append({"mount": mount, "used": total - st.f_bavail * st.f_frsize, "total": total,
                          "removable": mount.startswith("/run/media/")})
    # Removable drives first, so one you can eject never falls off the list
    return sorted(found, key=lambda d: (not d["removable"], -d["used"] / d["total"]))[:limit]


def uptime(proc: Path = PROC) -> float:
    try:
        return float(_read(proc / "uptime").split()[0])
    except (ValueError, IndexError):
        return 0.0


def parse_volume(text: str) -> tuple[int, bool] | None:
    """`wpctl get-volume` -> (percent, muted). None when there is no such device."""
    parts = text.split()
    if len(parts) < 2 or parts[0] != "Volume:":
        return None
    try:
        return round(float(parts[1]) * 100), "[MUTED]" in parts
    except ValueError:
        return None


def parse_network(text: str) -> dict:
    """`nmcli -t -f TYPE,STATE,CONNECTION dev`. Unmanaged ethernet entries are containers, not your network socket."""
    found = {"wifi": False, "wifi_name": "", "ethernet": False, "ethernet_on": False}
    for line in text.splitlines():
        kind, state, *rest = line.split(":") + [""]
        if state in ("unmanaged", "unavailable") and kind == "ethernet":
            continue
        on = state == "connected"
        if kind == "wifi":
            found["wifi"] = True
            if on:
                found["wifi_name"] = rest[0]
        elif kind == "ethernet":
            found["ethernet"] = True
            found["ethernet_on"] = found["ethernet_on"] or on
    return found


def fmt_bytes(n: float) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:.0f} {unit}" if unit in ("B", "KB") else f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} TB"


def fmt_uptime(seconds: float) -> str:
    minutes = int(seconds // 60)
    days, hours, minutes = minutes // 1440, minutes // 60 % 24, minutes % 60
    return f"{days}d {hours}h" if days else f"{hours}h {minutes}m" if hours else f"{minutes}m"
