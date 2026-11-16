"""Computer page: this PC's name, what kind of device it is, what is inside it, its clock and its language. Like
Windows' "About" and "Rename this PC" and a Mac's About, Sharing and Date & Time.

Everything is read straight from files (/etc/hostname, /etc/machine-info, /sys/class/dmi), so the page works even
when systemd's services are not answering. Changes go through computer_helper.py as root, by pkexec, which asks for
your password once and remembers it for a few minutes."""

from __future__ import annotations

import json
import os
import platform
import re
import shutil
import socket
import subprocess
import sys
import unicodedata
from pathlib import Path

HELPER = Path(__file__).resolve().parent / "computer_helper.py"
ROOT = Path("/")  # tests point this at a folder of fake system files

# What hostnamectl calls each kind of device, and what this page calls it
CHASSIS = (
    ("desktop", "Desktop"), ("laptop", "Laptop"), ("convertible", "Laptop that folds into a tablet"), ("tablet", "Tablet"),
    ("handset", "Handheld"), ("server", "Server"), ("embedded", "Small board (Raspberry Pi and the like)"),
    ("vm", "Virtual machine"), ("container", "Container"), ("watch", "Watch"),
)
CHASSIS_GLYPH = {"desktop": "\U000f0379", "laptop": "\U000f0322", "convertible": "\U000f0322", "tablet": "\U000f04f6",
                 "handset": "\U000f011c", "server": "\U000f048b", "embedded": "\U000f061a", "vm": "\U000f0aae",
                 "container": "\U000f0868", "watch": "\U000f05ad"}
# SMBIOS chassis type numbers (/sys/class/dmi/id/chassis_type)
DMI_CHASSIS = {**dict.fromkeys((3, 4, 5, 6, 7, 13, 15, 16, 24, 35, 36), "desktop"), **dict.fromkeys((8, 9, 10, 14), "laptop"),
               **dict.fromkeys((11,), "handset"), **dict.fromkeys((17, 23, 25, 28, 29), "server"), 30: "tablet",
               31: "convertible", 32: "convertible"}
# What makers leave in the fields when they did not fill them in
PLACEHOLDERS = re.compile(r"^(to be filled.*|system (product name|manufacturer|version)|default string|not applicable|none|"
                          r"o\.?e\.?m\.?|x\.x|0+|123456789|type1.*|base board.*|unknown)$", re.I)
HOSTNAME = re.compile(r"^(?!-)[a-z0-9-]{1,63}(?<!-)$")


# ---- small readers -------------------------------------------------------------------------------------------------
def _read(path: str) -> str:
    try:
        return (ROOT / path.lstrip("/")).read_text(encoding="utf-8", errors="replace").strip()
    except OSError:
        return ""


def _run(argv: list[str], timeout: float = 5) -> str:
    """A command's output, or "" when it is missing or fails."""
    if not shutil.which(argv[0]):
        return ""
    try:
        done = subprocess.run(argv, capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.SubprocessError):
        return ""
    return done.stdout if done.returncode == 0 else ""


def _shell_vars(text: str) -> dict[str, str]:
    """KEY=value lines, as in /etc/machine-info and /etc/locale.conf. Quotes are taken off."""
    out = {}
    for line in text.splitlines():
        key, eq, value = line.strip().partition("=")
        if eq and key and not key.startswith("#"):
            value = value.strip()
            if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
                value = value[1:-1].replace('\\"', '"')
            out[key.strip()] = value
    return out


def _dmi(name: str) -> str:
    value = " ".join(_read(f"/sys/class/dmi/id/{name}").split())
    return "" if PLACEHOLDERS.match(value) else value


# ---- name ----------------------------------------------------------------------------------------------------------
def network_name(name: str) -> str:
    """The name other computers use, made from the name you typed, the way a Mac does it: "Dee's Desktop" ->
    "dees-desktop". Letters without accents, numbers and hyphens only, at most 63 of them."""
    text = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode().lower()
    text = re.sub(r"['’`]", "", text)
    text = re.sub(r"[^a-z0-9]+", "-", text).strip("-")
    return text[:63].rstrip("-")


def check_network_name(name: str) -> str:
    """Why a network name will not do, or "" when it is fine."""
    if not name:
        return "The network name cannot be empty."
    if len(name) > 63:
        return "The network name can be 63 characters at most."
    if not HOSTNAME.match(name):
        return "Use only lower-case letters, numbers and hyphens, and do not start or end with a hyphen."
    return ""


def check_pretty_name(name: str) -> str:
    if len(name) > 64:
        return "Keep the name to 64 characters or fewer."
    if "\n" in name or '"' in name or "\\" in name:
        return "The name cannot have quotes, backslashes or line breaks in it."
    return ""


def identity() -> dict:
    """This PC's names and kind: static (network) name, pretty name, chassis, location."""
    info = _shell_vars(_read("/etc/machine-info"))
    static = _read("/etc/hostname").split("\n")[0].strip() or socket.gethostname()
    chassis = info.get("CHASSIS", "")
    return {"static": static, "running": socket.gethostname(), "pretty": info.get("PRETTY_HOSTNAME", ""),
            "chassis": chassis or guess_chassis(), "chassis_set": bool(chassis), "location": info.get("LOCATION", "")}


def display_name(ident: dict | None = None) -> str:
    ident = ident or identity()
    return ident["pretty"] or ident["static"]


def guess_chassis() -> str:
    """What kind of device this is when nobody said: from the firmware, a battery, or a virtual machine."""
    if _read("/sys/class/dmi/id/product_name").lower().startswith(("virtualbox", "vmware", "kvm", "qemu", "standard pc")) or \
            "hypervisor" in _read("/proc/cpuinfo").split("flags", 1)[-1].split("\n", 1)[0]:
        return "vm"
    try:
        kind = DMI_CHASSIS.get(int(_read("/sys/class/dmi/id/chassis_type")))
    except ValueError:
        kind = None
    if kind:
        return kind
    supplies = ROOT / "sys/class/power_supply"
    if supplies.is_dir() and any(_read(str(p.relative_to(ROOT) / "type")) == "Battery" and
                                 _read(str(p.relative_to(ROOT) / "scope")) != "Device" for p in supplies.iterdir()):
        return "laptop"
    return "desktop"


def chassis_label(key: str) -> str:
    return dict(CHASSIS).get(key, key.capitalize() or "Unknown")


def mdns_running() -> bool:
    """Avahi answers for name.local, so other computers on the network can find this one by name."""
    return (ROOT / "run/avahi-daemon/socket").exists()


# ---- what is inside it ---------------------------------------------------------------------------------------------
def vendor_name(vendor: str) -> str:
    """The name a maker goes by: "ASUSTeK COMPUTER INC." -> "ASUS", "LENOVO" -> "Lenovo"."""
    known = {"asustek": "ASUS", "lenovo": "Lenovo", "micro-star": "MSI", "gigabyte": "Gigabyte", "dell": "Dell", "hewlett": "HP",
             "hp": "HP", "asrock": "ASRock", "microsoft": "Microsoft", "apple": "Apple", "acer": "Acer", "samsung": "Samsung",
             "framework": "Framework", "system76": "System76", "tuxedo": "TUXEDO", "razer": "Razer", "intel": "Intel"}
    first = vendor.split()[0].lower().rstrip(",") if vendor else ""
    if first in known:
        return known[first]
    return re.sub(r",?\s+(computer\s+)?(inc\.?|corporation|corp\.?|co\.,? ltd\.?|ltd\.?|gmbh|technology.*)$", "", vendor, flags=re.I)


def model() -> str:
    """Maker and model, from the firmware: the PC's own if it says, else the motherboard's."""
    vendor, product, version = _dmi("sys_vendor"), _dmi("product_name"), _dmi("product_version")
    # Lenovo puts a type code (20XW0055UK) in the name and the name you know (ThinkPad X1 Carbon Gen 9) in the version
    if product and " " not in product and re.search(r"\d", product) and " " in version and re.search(r"[A-Za-z]{3}", version):
        product = version
    if not product:
        vendor, product = _dmi("board_vendor"), _dmi("board_name")
    if not product:
        return ""
    vendor = vendor_name(vendor)
    return product if vendor and product.lower().startswith(vendor.lower()) else " ".join(filter(None, [vendor, product]))


def firmware() -> str:
    parts = [_dmi("bios_vendor"), _dmi("bios_version")]
    date = _dmi("bios_date")
    m = re.match(r"(\d\d)/(\d\d)/(\d{4})", date)
    text = " ".join(filter(None, parts))
    return f"{text} ({m[3]}-{m[1]}-{m[2]})" if text and m else text


def os_name(text: str | None = None) -> str:
    text = _read("/etc/os-release") if text is None else text
    return _shell_vars(text).get("PRETTY_NAME") or platform.system()


def cpu_name(text: str | None = None) -> str:
    text = _read("/proc/cpuinfo") if text is None else text
    names = [" ".join(line.split(":", 1)[1].split()) for line in text.splitlines() if line.lower().startswith("model name")]
    if not names:
        return platform.processor() or "Unknown"
    name = re.sub(r"\s*\d+-Core Processor$|\(R\)|\(TM\)|\s+(CPU\s+)?@.*", "", names[0]).strip()
    threads = len(names)
    return f"{name}, {threads} threads" if threads > 1 else name


def memory(text: str | None = None) -> str:
    """Installed memory, rounded the way it is sold (31.2 GiB usable -> 32 GB)."""
    text = _read("/proc/meminfo") if text is None else text
    for line in text.splitlines():
        if line.startswith("MemTotal:"):
            gib = int(line.split()[1]) / 1024 / 1024
            sizes = [1, 2, 3, 4, 6, 8, 12, 16, 24, 32, 48, 64, 96, 128, 192, 256, 384, 512, 768, 1024]
            return f"{next((s for s in sizes if s >= gib * 0.97), round(gib))} GB"
    return "Unknown"


def size_label(size_bytes: int) -> str:
    """A disk's size as it says on the box: 1000204886016 -> "1 TB", 512110190592 -> "512 GB"."""
    gb = size_bytes / 1e9
    if gb >= 1000:
        tb = gb / 1000
        return f"{tb:.0f} TB" if abs(tb - round(tb)) < 0.1 else f"{tb:.1f} TB"
    return f"{gb:.0f} GB"


def disks() -> list[str]:
    """The drives built in to this PC, biggest first: "1 TB NVMe SSD". USB sticks and RAM disks are left out."""
    found = []
    block = ROOT / "sys/block"
    if not block.is_dir():
        return found
    for dev in sorted(block.iterdir()):
        name = dev.name
        if name.startswith(("loop", "ram", "zram", "dm-", "md", "sr", "fd", "nbd")) or _read(f"/sys/block/{name}/removable") == "1":
            continue
        try:
            size = int(_read(f"/sys/block/{name}/size") or 0) * 512
        except ValueError:
            continue
        if size < 1e9 or "/usb" in os.path.realpath(dev):
            continue
        if name.startswith("nvme"):
            kind = "NVMe SSD"
        elif name.startswith("mmcblk"):
            kind = "eMMC"
        else:
            kind = "hard drive" if _read(f"/sys/block/{name}/queue/rotational") == "1" else "SSD"
        found.append((size, f"{size_label(size)} {kind}"))
    return [text for _, text in sorted(found, key=lambda f: -f[0])]


def graphics(lspci: str | None = None) -> list[str]:
    """Graphics cards, by name: "AMD Radeon RX 7900 XTX". lspci -mm, so it needs pciutils, else the driver's name."""
    lspci = _run(["lspci", "-mm"]) if lspci is None else lspci
    cards = []
    for line in lspci.splitlines():
        fields = re.findall(r'"([^"]*)"', line)
        if len(fields) >= 3 and re.search(r"VGA|3D|Display", fields[0]):
            vendor, device = fields[1], fields[2]
            vendor = re.sub(r"Advanced Micro Devices, Inc\. \[AMD/ATI\]|Advanced Micro Devices.*", "AMD", vendor)
            vendor = re.sub(r"\s*Corporation$|\s*Inc\.?$", "", vendor)
            bracket = re.findall(r"\[([^\]]+)\]", device)  # the marketing name is in brackets: Navi 31 [Radeon RX 7900 XTX]
            name = bracket[-1] if bracket else device
            cards.append(name if name.lower().startswith(vendor.lower()) else f"{vendor} {name}")
    if cards or lspci:
        return cards
    drivers = []
    drm = ROOT / "sys/class/drm"
    for card in sorted(drm.glob("card[0-9]")) if drm.is_dir() else []:
        driver = os.path.basename(os.path.realpath(card / "device/driver"))
        if driver and driver != "driver":
            drivers.append({"amdgpu": "AMD graphics", "radeon": "AMD graphics", "i915": "Intel graphics", "xe": "Intel graphics",
                            "nvidia": "NVIDIA graphics", "nouveau": "NVIDIA graphics"}.get(driver, f"{driver} graphics"))
    return drivers


def desktop_version() -> str:
    try:
        tag = json.loads(_run(["hyprctl", "version", "-j"]) or "{}").get("tag", "")
    except ValueError:
        tag = ""
    return f"Hyprland {tag.lstrip('v').split('-')[0]}" if tag else ("Hyprland" if os.environ.get("HYPRLAND_INSTANCE_SIGNATURE") else "")


def uptime(seconds: float | None = None) -> str:
    if seconds is None:
        try:
            seconds = float(_read("/proc/uptime").split()[0])
        except (ValueError, IndexError):
            return ""
    minutes = int(seconds // 60)
    days, minutes = divmod(minutes, 1440)
    hours, minutes = divmod(minutes, 60)
    parts = [f"{days} day{'s' if days != 1 else ''}"] if days else []
    parts += [f"{hours} hour{'s' if hours != 1 else ''}"] if hours else []
    parts += [] if days else [f"{minutes} minute{'s' if minutes != 1 else ''}"]
    return ", ".join(parts)


def specs() -> list[tuple[str, str]]:
    """(label, value) for the About list, leaving out what this PC does not say."""
    rows = [("Model", model()), ("Processor", cpu_name()), ("Graphics", ", ".join(graphics())), ("Memory", memory()),
            ("Storage", ", ".join(disks())), ("System", os_name()), ("Kernel", platform.release()),
            ("Desktop", desktop_version()), ("Firmware", firmware()), ("Up for", uptime())]
    return [(k, v) for k, v in rows if v]


def specs_text(name: str, rows: list[tuple[str, str]]) -> str:
    """The About list as plain text, for pasting into a forum post or a support chat."""
    width = max((len(k) for k, _ in rows), default=0)
    return "\n".join([name, *(f"{k.ljust(width)}  {v}" for k, v in rows)]) + "\n"


# ---- clock ---------------------------------------------------------------------------------------------------------
def clock() -> dict:
    """Time zone, whether the time is set from the internet and whether that works, and whether the hardware clock
    keeps local time (needed beside Windows)."""
    shown = _shell_vars(_run(["timedatectl", "show"]))
    zone = shown.get("Timezone") or _zone_from_link()
    adjtime = _read("/etc/adjtime").splitlines()
    local_rtc = shown.get("LocalRTC", "yes" if len(adjtime) >= 3 and adjtime[2].strip() == "LOCAL" else "no") == "yes"
    return {"zone": zone, "ntp": shown.get("NTP") == "yes", "can_ntp": shown.get("CanNTP", "no") == "yes",
            "synced": shown.get("NTPSynchronized") == "yes", "local_rtc": local_rtc, "managed": bool(shown)}


def _zone_from_link() -> str:
    try:
        target = os.readlink(ROOT / "etc/localtime")
    except OSError:
        return _read("/etc/timezone") or "UTC"
    return target.split("zoneinfo/", 1)[1] if "zoneinfo/" in target else "UTC"


def zones() -> list[str]:
    listed = _run(["timedatectl", "list-timezones"]).split()
    if listed:
        return listed
    import zoneinfo
    return sorted(z for z in zoneinfo.available_timezones() if "/" in z or z == "UTC")


# ---- language ------------------------------------------------------------------------------------------------------
def current_locale() -> str:
    return _shell_vars(_read("/etc/locale.conf")).get("LANG", "") or os.environ.get("LANG", "")


def _canonical(name: str) -> str:
    """locale -a writes en_US.utf8; the system files write en_US.UTF-8."""
    return re.sub(r"\.utf-?8", ".UTF-8", name, flags=re.I)


def locales() -> list[str]:
    """The languages this PC has set up (generated). Others are added in /etc/locale.gen."""
    listed = _run(["localectl", "list-locales"]).split() or [_canonical(n) for n in _run(["locale", "-a"]).split()]
    return sorted({n for n in listed if not n.startswith(("C.", "POSIX")) and "." in n and "utf" in n.lower()})


def locale_label(name: str) -> str:
    """"en_GB.UTF-8" -> "English, United Kingdom (en_GB.UTF-8)", from the locale's own description when it has one."""
    base = name.split(".")[0].split("@")[0]
    ident = _read(f"/usr/share/i18n/locales/{base}")
    title = re.search(r'^title\s+"([^"]+)"', ident, re.M)
    language = re.search(r'^language\s+"([^"]+)"', ident, re.M)
    territory = re.search(r'^territory\s+"([^"]+)"', ident, re.M)
    if language and territory:
        text = f"{language[1]}, {territory[1]}"
    elif title:
        text = re.sub(r"\s+locale\b", "", title[1])
    else:
        return name
    return f"{text} ({name})"


# ---- changing things ------------------------------------------------------------------------------------------------
def helper(*args: str, timeout: float = 120) -> tuple[bool, str]:
    """Runs computer_helper.py as root. pkexec asks for your password (and remembers it for a few minutes)."""
    if not shutil.which("pkexec"):
        return False, "pkexec (polkit) is needed to change this."
    try:
        p = subprocess.run(["pkexec", sys.executable, str(HELPER), *args], capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.SubprocessError) as e:
        return False, str(e)
    if p.returncode in (126, 127):
        return False, "Not changed: the password prompt was cancelled."
    return p.returncode == 0, (p.stdout.strip() or p.stderr.strip() or ("Done." if p.returncode == 0 else "Not changed."))


def rename(pretty: str, static: str | None = None) -> tuple[bool, str]:
    """Gives the PC a new name. The network name is made from it unless you give one."""
    pretty = pretty.strip()
    static = network_name(pretty) if static is None else static.strip().lower()
    problem = check_pretty_name(pretty) or check_network_name(static)
    if problem:
        return False, problem
    # When the name you typed is already a plain network name, there is no separate display name to keep
    return helper("name", static, "" if pretty == static else pretty)


def set_device(chassis: str, location: str) -> tuple[bool, str]:
    if chassis not in dict(CHASSIS):
        return False, f"Unknown kind of device: {chassis}"
    return helper("device", chassis, location.strip())
