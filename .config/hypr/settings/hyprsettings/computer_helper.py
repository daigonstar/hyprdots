#!/usr/bin/env python3
"""Root half of the Computer page, run through pkexec. It only runs a fixed set of commands, each checked first, so
the password prompt never hands out more than that.

  computer_helper.py name STATIC PRETTY      network name and display name ("" clears it); /etc/hosts follows
  computer_helper.py device CHASSIS LOCATION what kind of device, and where it is ("" clears it)
  computer_helper.py timezone ZONE           Europe/London
  computer_helper.py ntp on|off              set the time from the internet
  computer_helper.py time "YYYY-MM-DD HH:MM" set the time by hand (only with ntp off)
  computer_helper.py rtc local|utc           what the hardware clock keeps; local beside Windows
  computer_helper.py locale NAME             the system language: en_GB.UTF-8
Stdlib only: pkexec gives it a bare environment."""
import os
import re
import shutil
import subprocess
import sys
import tempfile

HOSTNAME = re.compile(r"^(?!-)[a-z0-9-]{1,63}(?<!-)$")
CHASSIS = {"desktop", "laptop", "convertible", "tablet", "handset", "server", "embedded", "vm", "container", "watch"}
ZONE = re.compile(r"^[A-Za-z0-9_+-]+(/[A-Za-z0-9_+-]+)*$")
LOCALE = re.compile(r"^[A-Za-z]{2,3}(_[A-Za-z0-9]{2,3})?\.(UTF-8|utf8)(@[A-Za-z]+)?$")
WHEN = re.compile(r"^\d{4}-\d\d-\d\d \d\d:\d\d(:\d\d)?$")
HOSTS = "/etc/hosts"


def fail(msg):
    print(msg)
    sys.exit(1)


def run(*argv):
    """Runs a command; on failure, stops with what it said."""
    try:
        p = subprocess.run(argv, capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.SubprocessError) as e:
        fail(str(e))
    if p.returncode:
        fail((p.stderr or p.stdout).strip() or f"{argv[0]} failed.")
    return p.stdout


def systemd():
    """hostnamectl and timedatectl only work when systemd is running the PC."""
    return os.path.isdir("/run/systemd/system") and shutil.which("hostnamectl")


def write(path, text, mode=0o644):
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path), prefix=".hyprdots-")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(text)
    os.chmod(tmp, mode)
    os.replace(tmp, path)


def hosts_renamed(text, old, new):
    """/etc/hosts with the old name swapped for the new wherever it stands as a whole name. Comments are left alone."""
    if not old or old == new:
        return text
    word = re.compile(r"(?<![A-Za-z0-9.-])" + re.escape(old) + r"(?=$|[\s.])", re.I)
    out = []
    for line in text.splitlines(keepends=True):
        body, hash_, comment = line.partition("#")
        out.append(word.sub(new, body) + hash_ + comment)
    return "".join(out)


def machine_info(**changes):
    """Sets keys in /etc/machine-info without systemd (an empty value removes the key)."""
    path = "/etc/machine-info"
    try:
        lines = open(path, encoding="utf-8").read().splitlines()
    except OSError:
        lines = []
    lines = [line for line in lines if line.split("=", 1)[0].strip() not in changes]
    lines += [f'{k}="{v}"' for k, v in changes.items() if v]
    write(path, "\n".join(lines) + "\n" if lines else "")


def name(static, pretty):
    if not HOSTNAME.match(static):
        fail("Use only lower-case letters, numbers and hyphens for the network name.")
    if len(pretty) > 64 or any(c in pretty for c in '"\\\n'):
        fail("That name cannot be used.")
    try:
        old = open("/etc/hostname", encoding="utf-8").read().split("\n")[0].strip()
    except OSError:
        old = os.uname().nodename
    if systemd():
        run("hostnamectl", "set-hostname", "--static", static)
        run("hostnamectl", "set-hostname", "--transient", static)
        run("hostnamectl", "set-hostname", "--pretty", pretty)
    else:
        write("/etc/hostname", static + "\n")
        machine_info(PRETTY_HOSTNAME=pretty)
        if shutil.which("hostname"):
            run("hostname", static)
    try:
        text = open(HOSTS, encoding="utf-8").read()
    except OSError:
        text = ""
    changed = hosts_renamed(text, old, static)
    if changed != text:
        write(HOSTS, changed)
    print(f"Renamed to {pretty or static}.")


def device(chassis, location):
    if chassis not in CHASSIS:
        fail(f"Unknown kind of device: {chassis}")
    if len(location) > 64 or any(c in location for c in '"\\\n'):
        fail("That location cannot be used.")
    if systemd():
        run("hostnamectl", "set-chassis", chassis)
        run("hostnamectl", "set-location", location)
    else:
        machine_info(CHASSIS=chassis, LOCATION=location)
    print("Saved.")


def need_timedatectl():
    if not systemd() or not shutil.which("timedatectl"):
        fail("This needs systemd's timedatectl, which is not running here.")


def main(argv):
    if not argv:
        fail(__doc__)
    what, args = argv[0], argv[1:]
    if what == "name" and len(args) == 2:
        name(args[0], args[1])
    elif what == "device" and len(args) == 2:
        device(args[0], args[1])
    elif what == "timezone" and len(args) == 1:
        zone = args[0]
        if not ZONE.match(zone) or ".." in zone or not os.path.isfile(os.path.join("/usr/share/zoneinfo", zone)):
            fail(f"Unknown time zone: {zone}")
        need_timedatectl()
        run("timedatectl", "set-timezone", zone)
        print(f"Time zone set to {zone}.")
    elif what == "ntp" and args in (["on"], ["off"]):
        need_timedatectl()
        run("timedatectl", "set-ntp", "true" if args[0] == "on" else "false")
        print("The time is now set from the internet." if args[0] == "on" else "Set the time yourself from now on.")
    elif what == "time" and len(args) == 1:
        if not WHEN.match(args[0]):
            fail("Write the time as YYYY-MM-DD HH:MM.")
        need_timedatectl()
        run("timedatectl", "set-time", args[0])
        print("Time set.")
    elif what == "rtc" and args in (["local"], ["utc"]):
        need_timedatectl()
        run("timedatectl", "set-local-rtc", "1" if args[0] == "local" else "0")
        print("The hardware clock now keeps local time." if args[0] == "local" else "The hardware clock now keeps UTC.")
    elif what == "locale" and len(args) == 1:
        if not LOCALE.match(args[0]):
            fail(f"Not a language this can set: {args[0]}")
        if systemd() and shutil.which("localectl"):
            known = run("localectl", "list-locales").split()
            if known and args[0] not in known:
                fail(f"{args[0]} is not set up on this PC. Uncomment it in /etc/locale.gen and run locale-gen first.")
            run("localectl", "set-locale", f"LANG={args[0]}")
        else:
            write("/etc/locale.conf", f"LANG={args[0]}\n")
        print("Language set. It takes effect the next time you log in.")
    else:
        fail(__doc__)


if __name__ == "__main__":
    main(sys.argv[1:])
