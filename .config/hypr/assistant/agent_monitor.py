#!/usr/bin/env python3
"""Periodic PC health check. Flags problems via notify-send and saves a report
that hypr_agent.py reads, so the assistant knows what was flagged.

Usage: agent_monitor.py          run checks, notify about NEW problems
       agent_monitor.py --print  run checks, print the report, no notifications
"""
import json
import os
import re
import shutil
import subprocess
import sys
import time
from collections import Counter
from pathlib import Path

STATE_DIR = Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local/state")) / "hypr_agent"
REPORT_PATH = STATE_DIR / "health.txt"
SEEN_PATH = STATE_DIR / "notified.json"

# Thresholds come from ~/.config/hypr/user_settings.toml [monitor]
import usersettings
CFG = usersettings.section("monitor", {
    "renotify_hours": 6,
    "journal_window": "30 minutes ago",
    "disk_warn": 85,
    "disk_crit": 95,
    "mem_warn_pct": 10,
    "swap_warn_pct": 50,
    "temp_warn": 85,
    "temp_crit": 95,
    "updates_warn": 50,
    "journal_ignore": ["bluetoothd", "kwin_wayland", "sddm-helper"],
})
RENOTIFY_SECONDS = CFG["renotify_hours"] * 3600
JOURNAL_WINDOW = CFG["journal_window"]
DISK_WARN, DISK_CRIT = CFG["disk_warn"], CFG["disk_crit"]
MEM_WARN_PCT, SWAP_WARN_PCT = CFG["mem_warn_pct"], CFG["swap_warn_pct"]
SWAP_RAM_PCT = 30  # swap is only flagged while less than this % of RAM is available
TEMP_WARN, TEMP_CRIT = CFG["temp_warn"], CFG["temp_crit"]
UPDATES_WARN = CFG["updates_warn"]
JOURNAL_IGNORE = set(CFG["journal_ignore"])

def run(cmd, timeout=60):
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return r.stdout.strip()
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return ""

def check_failed_units():
    findings = []
    for scope, cmd in (("system", ["systemctl", "--failed"]), ("user", ["systemctl", "--user", "--failed"])):
        for line in run(cmd + ["--no-legend", "--plain"]).splitlines():
            unit = line.split()[0] if line.split() else ""
            if unit:
                findings.append(("warn", f"unit:{scope}:{unit}", f"Failed {scope} unit: {unit}"))
    return findings

def check_disks():
    findings, seen = [], set()
    for line in Path("/proc/mounts").read_text().splitlines():
        dev, mount, fstype = line.split()[:3]
        if not dev.startswith("/dev/") or fstype in ("squashfs", "iso9660") or dev in seen:
            continue
        seen.add(dev)
        try:
            usage = shutil.disk_usage(mount)
        except OSError:
            continue
        pct = usage.used * 100 // usage.total
        free_gb = usage.free / 1e9
        if pct >= DISK_CRIT:
            findings.append(("crit", f"disk:{mount}", f"{mount} is {pct}% full ({free_gb:.1f} GB free)"))
        elif pct >= DISK_WARN:
            findings.append(("warn", f"disk:{mount}", f"{mount} is {pct}% full ({free_gb:.1f} GB free)"))
    return findings

def check_memory():
    info = {}
    for line in Path("/proc/meminfo").read_text().splitlines():
        key, _, rest = line.partition(":")
        info[key] = int(rest.split()[0])
    findings = []
    avail_pct = info["MemAvailable"] * 100 // info["MemTotal"]
    if avail_pct < MEM_WARN_PCT:
        findings.append(("warn", "mem:low", f"Only {avail_pct}% of RAM available"))
    if info.get("SwapTotal"):
        swap_pct = (info["SwapTotal"] - info["SwapFree"]) * 100 // info["SwapTotal"]
        # Heavily used swap is only a problem when RAM is short too; idle swap with free RAM is harmless
        if swap_pct > SWAP_WARN_PCT and avail_pct < SWAP_RAM_PCT:
            findings.append(("warn", "mem:swap", f"Swap is {swap_pct}% used"))
    return findings

def check_temps():
    findings = []
    for hwmon in Path("/sys/class/hwmon").glob("hwmon*"):
        name = (hwmon / "name").read_text().strip() if (hwmon / "name").exists() else hwmon.name
        if name not in ("amdgpu", "k10temp", "nvme"):
            continue
        for temp_file in hwmon.glob("temp*_input"):
            try:
                celsius = int(temp_file.read_text()) / 1000
            except (OSError, ValueError):
                continue
            if celsius >= TEMP_CRIT:
                findings.append(("crit", f"temp:{name}", f"{name} is at {celsius:.0f}°C"))
            elif celsius >= TEMP_WARN:
                findings.append(("warn", f"temp:{name}", f"{name} is at {celsius:.0f}°C"))
    return findings

def check_journal():
    out = run(["journalctl", "-p", "3", "--since", JOURNAL_WINDOW, "--no-pager", "-o", "json"])
    counts, sample = Counter(), {}
    for line in out.splitlines():
        try:
            entry = json.loads(line)
        except ValueError:
            continue
        ident = entry.get("SYSLOG_IDENTIFIER") or entry.get("_COMM") or "unknown"
        if ident in JOURNAL_IGNORE:
            continue
        counts[ident] += 1
        msg = entry.get("MESSAGE")
        if isinstance(msg, str):
            sample.setdefault(ident, re.sub(r"\s+", " ", msg)[:140])
    return [
        ("warn", f"journal:{ident}", f"{ident} logged {n} error(s) in the last 30 min, e.g. {sample.get(ident, '')}")
        for ident, n in counts.most_common(3)
    ]

def check_coredumps():
    out = run(["coredumpctl", "list", "--since", "-1h", "--no-legend", "--no-pager"])
    findings = []
    for line in out.splitlines():
        parts = line.split()
        if parts:
            findings.append(("warn", f"crash:{parts[-1]}", f"Crash in the last hour: {parts[-1]}"))
    return findings[:3]

def check_reboot_needed():
    if not Path(f"/usr/lib/modules/{os.uname().release}").exists():
        return [("warn", "reboot", "The running kernel was replaced by an update. Reboot to load the new one.")]
    return []

def check_updates():
    lines = [l for l in run(["checkupdates"], timeout=90).splitlines() if l.strip()]
    findings = []
    critical = [l.split()[0] for l in lines if l.split()[0] in ("linux", "linux-lts", "linux-zen", "mesa", "hyprland", "systemd", "glibc", "linux-firmware")]
    if len(lines) >= UPDATES_WARN:
        findings.append(("info", "updates:many", f"{len(lines)} updates pending"))
    if critical:
        findings.append(("info", "updates:core", f"Core updates pending: {', '.join(critical)}"))
    return findings

CHECKS = [check_failed_units, check_disks, check_memory, check_temps, check_journal,
          check_coredumps, check_reboot_needed, check_updates]

def collect():
    findings = []
    for check in CHECKS:
        try:
            findings.extend(check())
        except Exception as e:
            findings.append(("info", f"monitor:{check.__name__}", f"Monitor check {check.__name__} failed: {e}"))
    return findings

def write_report(findings):
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y-%m-%d %H:%M:%S")
    if findings:
        body = "\n".join(f"[{sev.upper()}] {msg}" for sev, _, msg in findings)
    else:
        body = "No problems found."
    REPORT_PATH.write_text(f"Health check at {stamp}\n{body}\n")
    return body

def notify_new(findings):
    try:
        seen = json.loads(SEEN_PATH.read_text())
    except (OSError, ValueError):
        seen = {}
    now = time.time()
    current = {key for _, key, _ in findings}
    # Forget resolved problems so they are reported again if they come back
    seen = {k: t for k, t in seen.items() if k in current}
    for sev, key, msg in findings:
        if sev == "info" or now - seen.get(key, 0) < RENOTIFY_SECONDS:
            continue
        seen[key] = now
        urgency = "critical" if sev == "crit" else "normal"
        subprocess.run(["notify-send", "-a", "PC Health", "-u", urgency, "-i", "dialog-warning",
                        "--", "PC health: attention needed", f"{msg}\n\nAsk the agent: why is this happening?"])
    SEEN_PATH.write_text(json.dumps(seen))

def main():
    findings = collect()
    body = write_report(findings)
    if "--print" in sys.argv:
        print(body)
    else:
        notify_new(findings)

if __name__ == "__main__":
    main()
