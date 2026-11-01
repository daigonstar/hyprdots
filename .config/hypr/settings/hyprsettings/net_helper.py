#!/usr/bin/env python3
"""Root half of the Network page, run through pkexec. It only writes the few network files the page owns and
runs a fixed set of network commands, so the password prompt never hands out more than that.

  net_helper.py write PATH [--then ACTION ARG]   file content on stdin
  net_helper.py remove PATH
  net_helper.py wpa IFACE COMMAND [ARGS...]      wpa_cli when its socket is root-only
  net_helper.py netctl switch-to|stop|restart PROFILE
  net_helper.py iwscan IFACE                     iw scan, printed like wpa_cli scan_results
Stdlib only: pkexec gives it a bare environment."""
import os
import re
import shutil
import subprocess
import sys

ALLOWED = [re.compile(p) for p in (
    r"^/etc/systemd/network/10-hyprdots-[A-Za-z0-9_.:@-]{1,15}\.network$",
    r"^/etc/dhcpcd\.conf$",
    r"^/etc/netctl/[A-Za-z0-9_.@-]+$",
    r"^/var/lib/connman/hyprdots-[0-9a-f]{10}\.config$",
)]
SECRET = ("/etc/netctl/", "/var/lib/connman/")  # may hold Wi-Fi passwords
BACKUPS = "/var/backups/hyprdots-network"
IFACE = re.compile(r"^[A-Za-z0-9_.:@-]{1,15}$")
WPA_COMMANDS = {"scan", "scan_results", "list_networks", "add_network", "set_network", "select_network", "remove_network",
                "save_config", "disconnect", "reconnect", "status"}


def fail(msg):
    print(msg)
    sys.exit(1)


def allowed(path):
    path = os.path.normpath(path)
    if not any(p.match(path) for p in ALLOWED) or "/examples" in path:
        fail(f"Not a file the Network page may change: {path}")
    return path


def run(args):
    p = subprocess.run(args, capture_output=True, text=True, timeout=90)
    if p.returncode != 0:
        fail((p.stderr or p.stdout).strip() or f"{args[0]} failed")
    return p.stdout


def then(action, arg):
    if not IFACE.match(arg) and action != "netctl-restart":
        fail("bad interface name")
    if action == "networkd-reload":
        run(["networkctl", "reload"])
        run(["networkctl", "reconfigure", arg])
    elif action == "dhcpcd-rebind":
        if subprocess.run(["dhcpcd", "-n", arg], capture_output=True).returncode != 0:
            run(["systemctl", "restart", "dhcpcd.service"])
    elif action == "netctl-restart":
        netctl("restart", arg)
    else:
        fail(f"unknown action {action}")


def write(path, rest):
    path = allowed(path)
    data = sys.stdin.read()
    if os.path.exists(path) and "hyprdots" not in os.path.basename(path):
        os.makedirs(BACKUPS, mode=0o700, exist_ok=True)
        backup = os.path.join(BACKUPS, path.strip("/").replace("/", "_"))
        if not os.path.exists(backup):  # the first original is the one worth keeping
            shutil.copy2(path, backup)
    mode = os.stat(path).st_mode & 0o777 if os.path.exists(path) else (0o600 if path.startswith(SECRET) else 0o644)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".hyprdots-tmp"
    with open(os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, mode), "w") as f:
        f.write(data)
    os.chmod(tmp, mode)
    os.replace(tmp, path)
    if rest[:1] == ["--then"] and len(rest) == 3:
        then(rest[1], rest[2])
    print("Saved.")


def netctl(verb, profile):
    if verb not in ("switch-to", "stop", "restart") or not re.match(r"^[A-Za-z0-9_.@-]+$", profile):
        fail("bad netctl request")
    run(["netctl", verb, profile])


def iwscan(iface):
    """iw's scan, flattened to bssid, frequency, signal, flags, ssid lines."""
    out, cur = [], None
    for line in run(["iw", "dev", iface, "scan"]).splitlines():
        if line.startswith("BSS "):
            if cur:
                out.append(cur)
            cur = {"bssid": line.split()[1].split("(")[0], "freq": "", "signal": "", "flags": "", "ssid": ""}
        elif cur is not None:
            s = line.strip()
            if s.startswith("freq:"):
                cur["freq"] = s.split()[1]
            elif s.startswith("signal:"):
                cur["signal"] = s.split()[1].split(".")[0]
            elif s.startswith("SSID:"):
                cur["ssid"] = s[5:].strip()
            elif s.startswith(("RSN:", "WPA:")):
                cur["flags"] += "[WPA]"
    if cur:
        out.append(cur)
    print("bssid\tfrequency\tsignal level\tflags\tssid")
    for c in out:
        print("\t".join((c["bssid"], c["freq"], c["signal"], c["flags"], c["ssid"])))


def main(argv):
    if os.geteuid() != 0:
        fail("net_helper.py must run as root (through pkexec).")
    if not argv:
        fail(__doc__)
    cmd, args = argv[0], argv[1:]
    if cmd == "write" and args:
        write(args[0], args[1:])
    elif cmd == "remove" and len(args) == 1:
        path = allowed(args[0])
        if path == "/etc/dhcpcd.conf":
            fail("dhcpcd.conf is never removed")
        if os.path.exists(path):
            os.remove(path)
        print("Removed.")
    elif cmd == "wpa" and len(args) >= 2 and IFACE.match(args[0]) and args[1] in WPA_COMMANDS:
        print(run(["wpa_cli", "-i", args[0], *args[1:]]), end="")
    elif cmd == "netctl" and len(args) == 2:
        netctl(*args)
        print("Done.")
    elif cmd == "iwscan" and len(args) == 1 and IFACE.match(args[0]):
        iwscan(args[0])
    else:
        fail("unknown request")


if __name__ == "__main__":
    main(sys.argv[1:])
