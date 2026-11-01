"""Network page: Wi-Fi, addresses, DNS and routes, through whichever network manager is in charge.

Arch setups differ, so this first finds out what runs the network and then speaks its language:
  NetworkManager (with wpa_supplicant or iwd for Wi-Fi)   nmcli; everything, no files written
  systemd-networkd                                         a 10-hyprdots-<iface>.network file in /etc/systemd/network
  ConnMan                                                  connmanctl (static routes are not supported by ConnMan)
  dhcpcd                                                   a marked block at the end of /etc/dhcpcd.conf
  netctl                                                   the interface's profile in /etc/netctl
Wi-Fi goes through NetworkManager or ConnMan when they run it, otherwise iwd (iwctl), otherwise wpa_supplicant
(wpa_cli), or netctl profiles. Files outside your home are written by net_helper.py through pkexec, which asks for
your password once. Reading the state (ip, resolv.conf) works with any of them, and with none.
Every command goes through run(), so tests can replace it."""

from __future__ import annotations

import hashlib
import ipaddress
import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

HELPER = Path(__file__).resolve().parent / "net_helper.py"
NETWORKD_DIR = Path("/etc/systemd/network")
NETCTL_DIR = Path("/etc/netctl")
DHCPCD_CONF = Path("/etc/dhcpcd.conf")
HIDDEN = ("lo", "docker", "br-", "veth", "virbr", "vnet", "tailscale", "zt", "wg", "tun", "tap", "podman", "cni", "flannel")
MANAGER_LABELS = {"nm": "NetworkManager", "networkd": "systemd-networkd", "connman": "ConnMan", "dhcpcd": "dhcpcd",
                  "netctl": "netctl", None: "nothing"}
WIFI_LABELS = {"nm": "NetworkManager", "connman": "ConnMan", "iwd": "iwd", "wpa": "wpa_supplicant", "netctl": "netctl"}
ANSI = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")


def run(args: list[str], input: str | None = None, timeout: int = 40) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(args, input=input, capture_output=True, text=True, timeout=timeout)
    except FileNotFoundError:
        return subprocess.CompletedProcess(args, 127, "", f"{args[0]} is not installed")
    except subprocess.TimeoutExpired:
        return subprocess.CompletedProcess(args, 124, "", f"{args[0]} took too long")


def _err(p: subprocess.CompletedProcess, fallback: str) -> str:
    text = ANSI.sub("", (p.stderr or p.stdout or "").strip())
    text = re.sub(r"^Error: ", "", text.splitlines()[-1] if text else "")
    return text or fallback


def _active(unit: str) -> bool:
    return run(["systemctl", "is-active", "--quiet", unit]).returncode == 0


def _any_active(pattern: str) -> bool:
    p = run(["systemctl", "list-units", "--state=active", "--no-legend", "--plain", pattern])
    return bool(p.stdout.strip())


def privileged(*args: str, input: str | None = None) -> tuple[bool, str]:
    """Runs net_helper.py as root. pkexec asks for the password (and remembers it for a few minutes)."""
    if not shutil.which("pkexec"):
        return False, "pkexec (polkit) is needed to change system network files."
    p = run(["pkexec", sys.executable, str(HELPER), *args], input=input, timeout=120)
    if p.returncode in (126, 127) and not p.stdout:
        return False, "Not changed: the password prompt was cancelled."
    return p.returncode == 0, (p.stdout.strip() or _err(p, "the helper failed"))


# ---- what runs the network -----------------------------------------------------------------------------------
def detect() -> dict:
    """{'manager': nm|networkd|connman|dhcpcd|netctl|None, 'wifi': nm|connman|iwd|wpa|netctl|None}."""
    if shutil.which("nmcli") and _active("NetworkManager.service"):
        return {"manager": "nm", "wifi": "nm"}
    if shutil.which("connmanctl") and _active("connman.service"):
        return {"manager": "connman", "wifi": "connman"}
    manager = None
    if _active("systemd-networkd.service"):
        manager = "networkd"
    elif shutil.which("netctl") and (_any_active("netctl@*") or _any_active("netctl-auto@*") or _any_active("netctl-ifplugd@*")):
        manager = "netctl"
    elif _active("dhcpcd.service") or _any_active("dhcpcd@*"):
        manager = "dhcpcd"
    wifi = None
    if shutil.which("iwctl") and _active("iwd.service"):
        wifi = "iwd"
    elif shutil.which("wpa_cli") and _any_active("wpa_supplicant*"):
        wifi = "wpa"
    elif manager == "netctl":
        wifi = "netctl"
    return {"manager": manager, "wifi": wifi}


# ---- what the interfaces look like right now (works with any manager) -----------------------------------------
def _kind(name: str) -> str:
    base = Path("/sys/class/net") / name
    if (base / "wireless").exists() or (base / "phy80211").exists():
        return "wifi"
    if (base / "device").exists():
        return "ethernet"
    return "other"


def interfaces(show_virtual: bool = False) -> list[dict]:
    """[{name, kind, up, mac, ipv4: [cidr], ipv6: [cidr], gateway, metric}] for real network cards, wired first."""
    try:
        addrs = json.loads(run(["ip", "-j", "addr"]).stdout or "[]")
        routes = json.loads(run(["ip", "-j", "route"]).stdout or "[]")
    except (json.JSONDecodeError, TypeError):  # no ip command, or odd output
        return []
    gw = {}
    for r in routes:
        if r.get("dst") == "default" and r.get("dev") and r.get("dev") not in gw:
            gw[r["dev"]] = (r.get("gateway", ""), r.get("metric", 0))
    out = []
    for a in addrs:
        name = a.get("ifname", "")
        if not show_virtual and (name.startswith(HIDDEN) or _kind(name) == "other"):
            continue
        info = a.get("addr_info", [])
        out.append({"name": name, "kind": _kind(name), "up": a.get("operstate") == "UP", "mac": a.get("address", ""),
                    "ipv4": [f"{i['local']}/{i['prefixlen']}" for i in info if i.get("family") == "inet"],
                    "ipv6": [f"{i['local']}/{i['prefixlen']}" for i in info if i.get("family") == "inet6" and i.get("scope") == "global"],
                    "gateway": gw.get(name, ("", 0))[0], "metric": gw.get(name, ("", 0))[1]})
    out.sort(key=lambda i: (i["kind"] != "ethernet", i["kind"] != "wifi", i["name"]))
    return out


def dns_servers() -> list[str]:
    """The servers this PC actually asks (systemd-resolved's upstream ones when it is in use)."""
    if shutil.which("resolvectl") and _active("systemd-resolved.service"):
        p = run(["resolvectl", "dns"])
        found = []
        for line in p.stdout.splitlines():
            for s in line.partition(":")[2].split():
                if s not in found:
                    found.append(s)
        if found:
            return found
    try:
        text = Path("/etc/resolv.conf").read_text()
    except OSError:
        return []
    return [line.split()[1] for line in text.splitlines() if line.startswith("nameserver") and len(line.split()) > 1]


# ---- checking what people type ---------------------------------------------------------------------------------
def check_config(cfg: dict) -> dict:
    """Validates and tidies an IP config dict; raises ValueError with a message for people.
    cfg: method ('auto'|'manual'), addresses [cidr], gateway, dns [ip], routes [(dest cidr, via, metric|None)],
         metric (int|None, priority of this connection's default route; lower wins), ipv6 ('auto'|'off')."""
    out = dict(cfg)
    out["method"] = cfg.get("method", "auto")
    addrs = []
    for a in cfg.get("addresses", []):
        a = a.strip()
        if not a:
            continue
        if "/" not in a:
            a += "/24"
        try:
            iface = ipaddress.ip_interface(a)
        except ValueError:
            raise ValueError(f"'{a}' is not an address. Write it like 192.168.1.50/24.") from None
        if iface.version != 4:
            raise ValueError(f"'{a}': only IPv4 addresses can be set here; IPv6 is set automatically or switched off.")
        addrs.append(str(iface))
    if out["method"] == "manual" and not addrs:
        raise ValueError("A fixed (static) setup needs at least one address, like 192.168.1.50/24.")
    out["addresses"] = addrs
    gw = cfg.get("gateway", "").strip()
    if gw:
        try:
            gw = str(ipaddress.IPv4Address(gw))
        except ValueError:
            raise ValueError(f"'{gw}' is not a gateway address. Write it like 192.168.1.1.") from None
        if addrs and not any(ipaddress.IPv4Address(gw) in ipaddress.ip_interface(a).network for a in addrs):
            raise ValueError(f"The gateway {gw} is not inside {', '.join(addrs)}, so it could not be reached.")
    out["gateway"] = gw
    dns = []
    for d in cfg.get("dns", []):
        d = d.strip()
        if d:
            try:
                dns.append(str(ipaddress.ip_address(d)))
            except ValueError:
                raise ValueError(f"'{d}' is not a DNS server address. Write it like 1.1.1.1.") from None
    out["dns"] = dns
    routes = []
    for dest, via, metric in cfg.get("routes", []):
        try:
            net = ipaddress.ip_network(dest.strip(), strict=False)
            hop = str(ipaddress.ip_address(via.strip())) if via.strip() else ""
        except ValueError:
            raise ValueError(f"The route '{dest} via {via}' is not valid. Write it like 10.0.0.0/8 via 192.168.1.1.") from None
        if net.version != 4 or (hop and ipaddress.ip_address(hop).version != 4):
            raise ValueError("Only IPv4 routes can be set here.")
        routes.append((str(net), hop, int(metric) if metric not in (None, "") else None))
    out["routes"] = routes
    m = cfg.get("metric")
    out["metric"] = int(m) if m not in (None, "", -1) else None
    if out["metric"] is not None and not 0 <= out["metric"] <= 65535:
        raise ValueError("The priority must be between 0 and 65535.")
    out["ipv6"] = "off" if cfg.get("ipv6") == "off" else "auto"
    return out


def parse_route(text: str) -> tuple[str, str, int | None]:
    """'10.0.0.0/8 via 192.168.1.1 metric 100' or '10.0.0.0/8 192.168.1.1 100' -> (dest, via, metric)."""
    words = [w for w in text.replace(",", " ").split() if w not in ("via", "metric", "->")]
    if not words:
        raise ValueError("Write a route like 10.0.0.0/8 via 192.168.1.1")
    return words[0], words[1] if len(words) > 1 else "", int(words[2]) if len(words) > 2 and words[2].isdigit() else None


def _prefix_mask(cidr: str) -> tuple[str, str]:
    i = ipaddress.ip_interface(cidr)
    return str(i.ip), str(i.network.netmask)


# ==== Wi-Fi ==============================================================================================
def wifi_device() -> str:
    return next((i["name"] for i in interfaces() if i["kind"] == "wifi"), "")


def _nm_split(line: str) -> list[str]:
    """nmcli -t fields are split by ':' with literal colons written as '\\:'."""
    return [p.replace("\\:", ":").replace("\\\\", "\\") for p in re.split(r"(?<!\\):", line)]


def _iwd_table(args: list[str]) -> list[str]:
    p = run(["iwctl", *args])
    lines = [ANSI.sub("", line).rstrip() for line in p.stdout.splitlines()]
    body, dashes = [], 0
    for line in lines:
        if set(line.strip()) == {"-"}:
            dashes += 1
            continue
        if dashes >= 2 and line.strip():
            body.append(line)
    return body


def _dbm_percent(text: str) -> int | None:
    """-50 dBm or better is full strength, -100 is nothing. iwd writes dBm times 100."""
    try:
        dbm = float(text.strip().split()[0])
    except (ValueError, IndexError):
        return None
    dbm = dbm / 100 if dbm < -1000 else dbm
    return int(max(0, min(100, 2 * (dbm + 100))))


def _wpa(iface: str, *args: str) -> subprocess.CompletedProcess:
    """wpa_cli as you; if its control socket is root-only, through the helper."""
    p = run(["wpa_cli", "-i", iface, *args])
    if p.returncode == 0 and "Failed to connect" not in p.stdout:
        return p
    ok, out = privileged("wpa", iface, *args)
    return subprocess.CompletedProcess(args, 0 if ok else 1, out, "" if ok else out)


def wifi_enabled(backend: str) -> bool | None:
    if backend == "nm":
        return run(["nmcli", "radio", "wifi"]).stdout.strip() == "enabled"
    if backend == "connman":
        p = run(["connmanctl", "technologies"])
        block = p.stdout.split("/net/connman/technology/wifi")[-1] if "technology/wifi" in p.stdout else ""
        return "Powered = True" in block.split("/net/connman/technology/")[0] if block else None
    if backend == "iwd":
        dev = wifi_device() or "wlan0"
        p = run(["iwctl", "device", dev, "show"])
        m = re.search(r"Powered\s+(on|off)", ANSI.sub("", p.stdout))
        return (m.group(1) == "on") if m else None
    p = run(["rfkill", "-J", "-o", "TYPE,SOFT,HARD"])
    try:
        rows = [r for r in json.loads(p.stdout).get("rfkilldevices", []) if r.get("type") == "wlan"]
        return any(r.get("soft") == "unblocked" and r.get("hard") == "unblocked" for r in rows) if rows else None
    except (json.JSONDecodeError, AttributeError):
        return None


def set_wifi_enabled(backend: str, on: bool) -> tuple[bool, str]:
    word = "on" if on else "off"
    if backend == "nm":
        p = run(["nmcli", "radio", "wifi", word])
    elif backend == "connman":
        p = run(["connmanctl", "enable" if on else "disable", "wifi"])
    elif backend == "iwd":
        p = run(["iwctl", "device", wifi_device() or "wlan0", "set-property", "Powered", word])
    else:
        p = run(["rfkill", "unblock" if on else "block", "wifi"])
    return (p.returncode == 0, f"Wi-Fi switched {word}.") if p.returncode == 0 else (False, _err(p, f"Could not switch Wi-Fi {word}."))


def scan(backend: str, rescan: bool = True) -> list[dict]:
    """Nearby networks, strongest first: [{ssid, signal 0-100 or None, secure, known, active, id}]."""
    nets: dict[str, dict] = {}

    def put(ssid, signal, secure, known=False, active=False, ident=""):
        if not ssid:
            return
        old = nets.get(ssid)
        if old is None or (signal or 0) > (old["signal"] or 0) or active:
            nets[ssid] = {"ssid": ssid, "signal": signal, "secure": secure, "known": known or bool(old and old["known"]),
                          "active": active or bool(old and old["active"]), "id": ident or (old["id"] if old else "")}

    if backend == "nm":
        known = {_nm_split(line)[0] for line in run(["nmcli", "-t", "-f", "NAME,TYPE", "con", "show"]).stdout.splitlines()
                 if line.endswith(":802-11-wireless")}
        p = run(["nmcli", "-t", "-f", "IN-USE,SSID,SIGNAL,SECURITY", "dev", "wifi", "list", "--rescan", "yes" if rescan else "auto"])
        for line in p.stdout.splitlines():
            use, ssid, signal, sec = (_nm_split(line) + ["", "", "", ""])[:4]
            put(ssid, int(signal) if signal.isdigit() else None, sec not in ("", "--"), ssid in known, use.strip() == "*")
    elif backend == "connman":
        if rescan:
            run(["connmanctl", "scan", "wifi"], timeout=30)
        for line in run(["connmanctl", "services"]).stdout.splitlines():
            parts = line.split()
            if len(parts) < 2 or not parts[-1].startswith("wifi_"):
                continue
            flags = line[:4]
            name = line[4:].rsplit(parts[-1], 1)[0].strip()
            put(name, None, not parts[-1].endswith("_none"), flags.startswith("*"), "O" in flags or "R" in flags, parts[-1])
    elif backend == "iwd":
        dev = wifi_device() or "wlan0"
        if rescan:
            run(["iwctl", "station", dev, "scan"])
            time.sleep(3)
        known = {re.split(r"\s{2,}", line.strip())[0] for line in _iwd_table(["known-networks", "list"])}
        for line in _iwd_table(["station", dev, "get-networks", "rssi-dbms"]):
            active = line.lstrip().startswith(">")
            cols = re.split(r"\s{2,}", line.strip().lstrip(">").strip())
            if len(cols) < 3:
                continue
            put(cols[0], _dbm_percent(cols[2]), cols[1] != "open", cols[0] in known, active)
    elif backend in ("wpa", "netctl"):
        dev = wifi_device()
        if not dev:
            return []
        known, current = {}, ""
        if backend == "wpa":
            if rescan:
                _wpa(dev, "scan")
                time.sleep(3)
            for line in _wpa(dev, "list_networks").stdout.splitlines()[1:]:
                cols = line.split("\t")
                if len(cols) >= 2:
                    known[cols[1]] = cols[0]
                    if len(cols) > 3 and "CURRENT" in cols[3]:
                        current = cols[1]
            results = _wpa(dev, "scan_results").stdout
        else:
            for f in _netctl_profiles():
                if f["kind"] == "wireless" and f.get("essid"):
                    known[f["essid"]] = f["name"]
                    if f["active"]:
                        current = f["essid"]
            ok, results = privileged("iwscan", dev)
            results = results if ok else ""
        for line in results.splitlines():
            cols = line.split("\t")
            if len(cols) < 5 or cols[0].startswith("bssid"):
                continue
            put(cols[4], _dbm_percent(cols[2]), any(k in cols[3] for k in ("WPA", "WEP", "SAE", "RSN")), cols[4] in known, cols[4] == current,
                known.get(cols[4], ""))
    return sorted(nets.values(), key=lambda n: (not n["active"], -(n["signal"] or 0), n["ssid"].lower()))


def connect(backend: str, ssid: str, password: str = "", hidden: bool = False, ident: str = "") -> tuple[bool, str]:
    """Joins a network. A known network needs no password. The password passes to the manager's own command."""
    dev = wifi_device()
    if backend == "nm":
        known = any(_nm_split(line)[0] == ssid and line.endswith(":802-11-wireless")
                    for line in run(["nmcli", "-t", "-f", "NAME,TYPE", "con", "show"]).stdout.splitlines())
        if known and not password:
            p = run(["nmcli", "con", "up", "id", ssid], timeout=90)
        else:
            if known:  # a new password for a saved network: replace the old profile
                run(["nmcli", "con", "delete", "id", ssid])
            args = ["nmcli", "dev", "wifi", "connect", ssid] + (["password", password] if password else [])
            args += (["hidden", "yes"] if hidden else []) + (["ifname", dev] if dev else [])
            p = run(args, timeout=90)
    elif backend == "connman":
        if password or hidden:
            name = "hyprdots-" + hashlib.sha1(ssid.encode()).hexdigest()[:10]
            body = f"[service_{name}]\nType = wifi\nName = {ssid}\n" + (f"Passphrase = {password}\n" if password else "") + \
                   ("Hidden = true\n" if hidden else "")
            ok, msg = privileged("write", f"/var/lib/connman/{name}.config", input=body)
            if not ok:
                return False, msg
            time.sleep(2)
            ident = ident or next((n["id"] for n in scan(backend, rescan=True) if n["ssid"] == ssid), "")
        if not ident:
            return False, f"'{ssid}' is not in range."
        p = run(["connmanctl", "connect", ident], timeout=90)
    elif backend == "iwd":
        dev = dev or "wlan0"
        verb = "connect-hidden" if hidden else "connect"
        p = run(["iwctl"] + (["--passphrase", password] if password else []) + ["station", dev, verb, ssid], timeout=90)
    elif backend == "wpa":
        if not dev:
            return False, "No Wi-Fi card found."
        net_id = ident
        if not net_id or password:
            if net_id:
                _wpa(dev, "remove_network", net_id)
            net_id = _wpa(dev, "add_network").stdout.strip().splitlines()[-1]
            settings = [("ssid", f'"{ssid}"')] + ([("psk", f'"{password}"')] if password else [("key_mgmt", "NONE")])
            settings += [("scan_ssid", "1")] if hidden else []
            for key, value in settings:
                if "OK" not in _wpa(dev, "set_network", net_id, key, value).stdout:
                    _wpa(dev, "remove_network", net_id)
                    return False, "wpa_supplicant did not accept that network (a WPA password is 8 to 63 characters)."
        p = _wpa(dev, "select_network", net_id)
        _wpa(dev, "save_config")
    elif backend == "netctl":
        name = ident or "hyprdots-wifi-" + re.sub(r"[^A-Za-z0-9_-]", "_", ssid)[:40]
        if not ident or password:
            def q(v):
                return "'" + v.replace("'", "'\\''") + "'"
            body = (f"Description='Wi-Fi network {ssid.replace(chr(39), '')} (added by Settings)'\nInterface={dev}\nConnection=wireless\n"
                    f"Security={'wpa' if password else 'none'}\nESSID={q(ssid)}\nIP=dhcp\n" + (f"Key={q(password)}\n" if password else "") +
                    ("Hidden=yes\n" if hidden else ""))
            ok, msg = privileged("write", f"/etc/netctl/{name}", input=body)
            if not ok:
                return False, msg
        ok, msg = privileged("netctl", "switch-to", name)
        return (True, f"Connected to {ssid}.") if ok else (False, msg)
    else:
        return False, "No Wi-Fi service is running (NetworkManager, ConnMan, iwd or wpa_supplicant)."
    if p.returncode != 0:
        return False, _err(p, f"Could not connect to {ssid}.")
    return True, f"Connected to {ssid}."


def disconnect(backend: str, ssid: str = "", ident: str = "") -> tuple[bool, str]:
    dev = wifi_device()
    if backend == "nm":
        p = run(["nmcli", "dev", "disconnect", dev])
    elif backend == "connman":
        p = run(["connmanctl", "disconnect", ident])
    elif backend == "iwd":
        p = run(["iwctl", "station", dev, "disconnect"])
    elif backend == "wpa":
        p = _wpa(dev, "disconnect")
    elif backend == "netctl":
        ok, msg = privileged("netctl", "stop", ident)
        return (True, "Disconnected.") if ok else (False, msg)
    else:
        return False, "No Wi-Fi service is running."
    return (True, "Disconnected.") if p.returncode == 0 else (False, _err(p, "Could not disconnect."))


def forget(backend: str, ssid: str, ident: str = "") -> tuple[bool, str]:
    if backend == "nm":
        p = run(["nmcli", "con", "delete", "id", ssid])
    elif backend == "connman":
        name = "hyprdots-" + hashlib.sha1(ssid.encode()).hexdigest()[:10]
        privileged("remove", f"/var/lib/connman/{name}.config")
        p = run(["connmanctl", "config", ident, "--remove"])
    elif backend == "iwd":
        p = run(["iwctl", "known-networks", ssid, "forget"])
    elif backend == "wpa":
        dev = wifi_device()
        p = _wpa(dev, "remove_network", ident)
        _wpa(dev, "save_config")
    elif backend == "netctl":
        privileged("netctl", "stop", ident)
        ok, msg = privileged("remove", f"/etc/netctl/{ident}")
        return (True, f"Forgot {ssid}.") if ok else (False, msg)
    else:
        return False, "No Wi-Fi service is running."
    return (True, f"Forgot {ssid}.") if p.returncode == 0 else (False, _err(p, f"Could not forget {ssid}."))


# ==== addresses, DNS and routes =============================================================================
def blank_config() -> dict:
    return {"method": "auto", "addresses": [], "gateway": "", "dns": [], "routes": [], "metric": None, "ipv6": "auto",
            "profile": "", "notes": []}


def ip_config(manager: str | None, iface: str) -> dict:
    """The saved setup for an interface (not just what it has right now). 'profile' names where it lives;
    'notes' lists anything this manager cannot do; 'error' means it cannot be edited at all."""
    cfg = blank_config()
    try:
        if manager == "nm":
            return _nm_read(iface, cfg)
        if manager == "networkd":
            return _networkd_read(iface, cfg)
        if manager == "connman":
            return _connman_read(iface, cfg)
        if manager == "dhcpcd":
            return _dhcpcd_read(iface, cfg)
        if manager == "netctl":
            return _netctl_read(iface, cfg)
    except OSError as e:
        cfg["error"] = str(e)
        return cfg
    cfg["error"] = "No network manager is running, so there is nothing to save these settings in."
    return cfg


def set_ip_config(manager: str | None, iface: str, cfg: dict) -> tuple[bool, str]:
    cfg = {**check_config(cfg), "profile": cfg.get("profile", "")}
    if manager == "nm":
        return _nm_write(iface, cfg)
    if manager == "networkd":
        return _networkd_write(iface, cfg)
    if manager == "connman":
        return _connman_write(iface, cfg)
    if manager == "dhcpcd":
        return _dhcpcd_write(iface, cfg)
    if manager == "netctl":
        return _netctl_write(iface, cfg)
    return False, "No network manager is running."


# ---- NetworkManager --------------------------------------------------------------------------------------------
def _nm_connection(iface: str) -> str:
    """UUID of the connection on the interface now, else the saved one bound to it."""
    uuid = run(["nmcli", "-g", "GENERAL.CON-UUID", "dev", "show", iface]).stdout.strip()
    if uuid:
        return uuid
    for line in run(["nmcli", "-t", "-f", "UUID,TYPE", "con", "show"]).stdout.splitlines():
        u = _nm_split(line)[0]
        if run(["nmcli", "-g", "connection.interface-name", "con", "show", u]).stdout.strip() == iface:
            return u
    return ""


def _nm_read(iface: str, cfg: dict) -> dict:
    uuid = _nm_connection(iface)
    if not uuid:
        cfg["error"] = ("This interface has no connection yet. Connect it first (plug in the cable, or join a Wi-Fi "
                        "network), then its settings appear here.")
        return cfg
    fields = ["connection.id", "ipv4.method", "ipv4.addresses", "ipv4.gateway", "ipv4.dns", "ipv4.routes",
              "ipv4.route-metric", "ipv6.method"]
    vals = run(["nmcli", "-g", ",".join(fields), "con", "show", uuid]).stdout.split("\n")
    v = dict(zip(fields, vals + [""] * len(fields)))
    cfg.update({"profile": v["connection.id"], "uuid": uuid,
                "method": "manual" if v["ipv4.method"] == "manual" else "auto",
                "addresses": [a.strip() for a in v["ipv4.addresses"].split(",") if a.strip()],
                "gateway": v["ipv4.gateway"].strip(),
                "dns": [d.strip() for d in v["ipv4.dns"].split(",") if d.strip()],
                "routes": [parse_route(r) for r in v["ipv4.routes"].split(",") if r.strip()],
                "metric": int(v["ipv4.route-metric"]) if v["ipv4.route-metric"].strip().lstrip("-").isdigit()
                and int(v["ipv4.route-metric"]) >= 0 else None,
                "ipv6": "off" if v["ipv6.method"] in ("disabled", "ignore") else "auto"})
    if v["ipv4.method"] not in ("auto", "manual"):
        cfg["notes"].append(f"This connection's IPv4 mode is '{v['ipv4.method']}'; saving here changes it.")
    return cfg


def _nm_write(iface: str, cfg: dict) -> tuple[bool, str]:
    uuid = cfg.get("uuid") or _nm_connection(iface)
    if not uuid:
        return False, "This interface has no connection yet."
    manual = cfg["method"] == "manual"
    args = ["nmcli", "con", "mod", uuid,
            "ipv4.method", "manual" if manual else "auto",
            "ipv4.addresses", ", ".join(cfg["addresses"]) if manual else "",
            "ipv4.gateway", cfg["gateway"] if manual else "",
            "ipv4.dns", ",".join(d for d in cfg["dns"] if ":" not in d),
            "ipv4.ignore-auto-dns", "yes" if cfg["dns"] else "no",
            "ipv4.routes", ", ".join(" ".join(x for x in (dest, via, str(m) if m is not None else "") if x)
                                     for dest, via, m in cfg["routes"]),
            "ipv4.route-metric", str(cfg["metric"]) if cfg["metric"] is not None else "-1",
            "ipv6.method", "disabled" if cfg["ipv6"] == "off" else "auto",
            "ipv6.dns", ",".join(d for d in cfg["dns"] if ":" in d),
            "ipv6.ignore-auto-dns", "yes" if any(":" in d for d in cfg["dns"]) else "no"]
    p = run(args)
    if p.returncode != 0:
        return False, _err(p, "NetworkManager did not accept the change.")
    if run(["nmcli", "-g", "GENERAL.CON-UUID", "dev", "show", iface]).stdout.strip() == uuid:
        p = run(["nmcli", "con", "up", "uuid", uuid], timeout=90)
        if p.returncode != 0:
            return False, "Saved, but reconnecting failed: " + _err(p, "unknown error")
        return True, f"Saved and reconnected {iface}."
    return True, f"Saved. {iface} uses it the next time it connects."


# ---- systemd-networkd ------------------------------------------------------------------------------------------
def _ini(text: str) -> list[tuple[str, list[tuple[str, str]]]]:
    """systemd unit syntax as [(section, [(key, value)])], keeping repeated sections and keys."""
    out = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line[0] in "#;":
            continue
        if line.startswith("[") and line.endswith("]"):
            out.append((line[1:-1], []))
        elif "=" in line and out:
            k, _, v = line.partition("=")
            out[-1][1].append((k.strip(), v.strip()))
    return out


def _networkd_file(iface: str) -> Path | None:
    """The .network file networkd uses for iface: the first one, in name order, whose Name= matches."""
    import fnmatch
    files = {}
    for d in (Path("/usr/lib/systemd/network"), Path("/run/systemd/network"), NETWORKD_DIR):  # later dirs override
        if d.is_dir():
            for f in d.glob("*.network"):
                files[f.name] = f
    for name in sorted(files):
        for section, items in _ini(files[name].read_text(errors="replace")):
            if section == "Match":
                names = " ".join(v for k, v in items if k == "Name").split()
                if names and any(fnmatch.fnmatch(iface, n) for n in names):
                    return files[name]
    return None


def _networkd_read(iface: str, cfg: dict) -> dict:
    f = _networkd_file(iface)
    cfg["profile"] = str(f) if f else ""
    if not f:
        cfg["notes"].append("No .network file matches this interface yet; saving creates one.")
        return cfg
    dhcp = ""
    for section, items in _ini(f.read_text(errors="replace")):
        d = dict(items)
        if section == "Network":
            dhcp = d.get("DHCP", "")
            cfg["addresses"] += [v for k, v in items if k == "Address" and ":" not in v]
            gws = [v for k, v in items if k == "Gateway" and ":" not in v]
            cfg["gateway"] = gws[0] if gws else cfg["gateway"]
            cfg["dns"] += [x for k, v in items if k == "DNS" for x in v.split()]
            if d.get("IPv6AcceptRA", "").lower() in ("no", "false", "0") and dhcp.lower() not in ("yes", "ipv6", "true"):
                cfg["ipv6"] = "off"
            if d.get("LinkLocalAddressing", "").lower() in ("no", "ipv4"):
                cfg["ipv6"] = "off"
        elif section == "Address":
            cfg["addresses"] += [v for k, v in items if k == "Address" and ":" not in v]
        elif section == "Route":
            dest, via = d.get("Destination", ""), d.get("Gateway", "")
            if not dest and via and not cfg["gateway"]:
                cfg["gateway"] = via
                cfg["metric"] = int(d["Metric"]) if d.get("Metric", "").isdigit() else cfg["metric"]
            elif dest and ":" not in dest:
                cfg["routes"].append((dest, via, int(d["Metric"]) if d.get("Metric", "").isdigit() else None))
        elif section in ("DHCPv4", "DHCP") and d.get("RouteMetric", "").isdigit():
            cfg["metric"] = int(d["RouteMetric"])
    cfg["method"] = "manual" if cfg["addresses"] and dhcp.lower() not in ("yes", "ipv4", "true") else "auto"
    if not f.name.startswith("10-hyprdots-"):
        cfg["notes"].append(f"Read from {f}. Saving writes {NETWORKD_DIR}/10-hyprdots-{iface}.network, which takes "
                            "over from it; anything else in that file (VLANs, bridges, link settings) is not carried over.")
    return cfg


def networkd_text(iface: str, cfg: dict) -> str:
    lines = ["# Written by hyprdots Settings (Network page). Edit there, or delete this file to go back.",
             "[Match]", f"Name={iface}", "", "[Network]"]
    if cfg["method"] == "manual":
        lines += [f"Address={a}" for a in cfg["addresses"]]
        lines.append("DHCP=ipv6" if cfg["ipv6"] == "auto" else "DHCP=no")
    else:
        lines.append("DHCP=yes" if cfg["ipv6"] == "auto" else "DHCP=ipv4")
    lines += [f"DNS={d}" for d in cfg["dns"]]
    lines.append("IPv6AcceptRA=yes" if cfg["ipv6"] == "auto" else "IPv6AcceptRA=no")
    if cfg["ipv6"] == "off":
        lines.append("LinkLocalAddressing=ipv4")
    if cfg["dns"]:
        lines += ["", "[DHCPv4]", "UseDNS=no"] + (["RouteMetric=" + str(cfg["metric"])] if cfg["metric"] is not None else [])
    elif cfg["metric"] is not None and cfg["method"] == "auto":
        lines += ["", "[DHCPv4]", f"RouteMetric={cfg['metric']}"]
    if cfg["method"] == "manual" and cfg["gateway"]:
        lines += ["", "[Route]", f"Gateway={cfg['gateway']}"] + ([f"Metric={cfg['metric']}"] if cfg["metric"] is not None else [])
    for dest, via, metric in cfg["routes"]:
        lines += ["", "[Route]", f"Destination={dest}"] + ([f"Gateway={via}"] if via else []) + \
                 ([f"Metric={metric}"] if metric is not None else [])
    return "\n".join(lines) + "\n"


def _networkd_write(iface: str, cfg: dict) -> tuple[bool, str]:
    path = f"{NETWORKD_DIR}/10-hyprdots-{iface}.network"
    ok, msg = privileged("write", path, "--then", "networkd-reload", iface, input=networkd_text(iface, cfg))
    return (True, f"Saved to {path} and applied.") if ok else (False, msg)


# ---- ConnMan -------------------------------------------------------------------------------------------------------
def _connman_service(iface: str) -> str:
    for line in run(["connmanctl", "services"]).stdout.splitlines():
        sid = line.split()[-1] if line.split() else ""
        if sid and f"Interface={iface}," in run(["connmanctl", "services", sid]).stdout.replace(" ", ""):
            return sid
    return ""


def _connman_read(iface: str, cfg: dict) -> dict:
    sid = _connman_service(iface)
    if not sid:
        cfg["error"] = "ConnMan has no connection on this interface yet. Connect it first."
        return cfg
    text = run(["connmanctl", "services", sid]).stdout
    props = {k.strip(): v.strip() for k, _, v in (line.partition(" = ") for line in text.splitlines()) if _}

    def inner(key):
        return dict(p.strip().partition("=")[::2] for p in props.get(key, "").strip("[] ").split(",") if "=" in p)
    v4 = inner("IPv4.Configuration")
    cfg.update({"profile": sid, "service": sid, "method": "manual" if v4.get("Method") == "manual" else "auto",
                "dns": props.get("Nameservers.Configuration", "").strip("[] ").replace(",", " ").split(),
                "ipv6": "off" if inner("IPv6.Configuration").get("Method") == "off" else "auto"})
    if v4.get("Address") and v4.get("Netmask"):
        cfg["addresses"] = [str(ipaddress.ip_interface(f"{v4['Address']}/{v4['Netmask']}"))]
    cfg["gateway"] = v4.get("Gateway", "")
    cfg["notes"].append("ConnMan cannot keep extra routes or a route priority, so those are not offered.")
    cfg["no_routes"] = True
    return cfg


def _connman_write(iface: str, cfg: dict) -> tuple[bool, str]:
    sid = cfg.get("service") or _connman_service(iface)
    if not sid:
        return False, "ConnMan has no connection on this interface."
    if cfg["routes"] or cfg["metric"] is not None:
        return False, "ConnMan cannot keep extra routes or a route priority. Remove them and save again."
    if cfg["method"] == "manual":
        addr, mask = _prefix_mask(cfg["addresses"][0])
        v4 = ["--ipv4", "manual", addr, mask] + ([cfg["gateway"]] if cfg["gateway"] else [])
    else:
        v4 = ["--ipv4", "dhcp"]
    for args in (v4, ["--ipv6", "off" if cfg["ipv6"] == "off" else "auto"], ["--nameservers", *cfg["dns"]]):
        p = run(["connmanctl", "config", sid, *args])
        if p.returncode != 0:
            return False, _err(p, "ConnMan did not accept the change.")
    return True, f"Saved and applied to {iface}."


# ---- dhcpcd ------------------------------------------------------------------------------------------------------
def _dhcpcd_block(text: str, iface: str) -> tuple[str, str]:
    """(conf without our block for iface, our block's body)."""
    begin, end = f"# hyprdots-network {iface} begin", f"# hyprdots-network {iface} end"
    if begin in text and end in text:
        before, _, rest = text.partition(begin)
        body, _, after = rest.partition(end)
        return before.rstrip("\n") + "\n" + after.lstrip("\n"), body
    return text, ""


def _dhcpcd_read(iface: str, cfg: dict) -> dict:
    text = DHCPCD_CONF.read_text(errors="replace") if DHCPCD_CONF.exists() else ""
    cfg["profile"] = str(DHCPCD_CONF)
    _, body = _dhcpcd_block(text, iface)
    if not body:  # someone else's block for this interface
        m = re.search(rf"(?ms)^interface\s+{re.escape(iface)}\s*$(.*?)(?=^interface\s|\Z)", text)
        body = m.group(1) if m else ""
    for line in body.splitlines():
        words = line.split(None, 1)
        if len(words) < 2:
            continue
        if words[0] == "metric" and words[1].strip().isdigit():
            cfg["metric"] = int(words[1])
        if words[0] == "noipv6":
            cfg["ipv6"] = "off"
        if words[0] == "static":
            key, _, value = words[1].partition("=")
            vals = value.split()
            if key == "ip_address":
                cfg["addresses"] = [v for v in vals if ":" not in v]
            elif key == "routers" and vals:
                cfg["gateway"] = vals[0]
            elif key == "domain_name_servers":
                cfg["dns"] = vals
    cfg["method"] = "manual" if cfg["addresses"] else "auto"
    cfg["notes"].append("dhcpcd cannot keep extra routes, so those are not offered.")
    cfg["no_routes"] = True
    return cfg


def _dhcpcd_write(iface: str, cfg: dict) -> tuple[bool, str]:
    if cfg["routes"]:
        return False, "dhcpcd cannot keep extra routes. Remove them and save again."
    text = DHCPCD_CONF.read_text(errors="replace") if DHCPCD_CONF.exists() else ""
    rest, _ = _dhcpcd_block(text, iface)
    body = [f"interface {iface}"]
    if cfg["method"] == "manual":
        body.append(f"static ip_address={' '.join(cfg['addresses'])}")
        if cfg["gateway"]:
            body.append(f"static routers={cfg['gateway']}")
    if cfg["dns"]:
        body.append(f"static domain_name_servers={' '.join(cfg['dns'])}")
    if cfg["metric"] is not None:
        body.append(f"metric {cfg['metric']}")
    if cfg["ipv6"] == "off":
        body.append("noipv6")
    new = rest.rstrip("\n") + "\n\n" if rest.strip() else ""
    if len(body) > 1:  # interface blocks run to the next one, so ours always go last
        new += f"# hyprdots-network {iface} begin\n" + "\n".join(body) + f"\n# hyprdots-network {iface} end\n"
    ok, msg = privileged("write", str(DHCPCD_CONF), "--then", "dhcpcd-rebind", iface, input=new)
    return (True, f"Saved to {DHCPCD_CONF} and applied.") if ok else (False, msg)


# ---- netctl --------------------------------------------------------------------------------------------------------
def _shell_vars(text: str) -> dict:
    import shlex
    out = {}
    for line in text.splitlines():
        m = re.match(r"^\s*([A-Za-z0-9_]+)=(.*)$", line)
        if not m:
            continue
        raw = m.group(2).strip()
        if raw.startswith("("):
            out[m.group(1)] = shlex.split(raw.strip("()"), comments=True)
        else:
            try:
                parts = shlex.split(raw, comments=True)
            except ValueError:
                parts = [raw]
            out[m.group(1)] = parts[0] if parts else ""
    return out


def _netctl_profiles() -> list[dict]:
    active = set()
    for line in run(["netctl", "list"]).stdout.splitlines():
        if line.startswith(("*", "+")):
            active.add(line[1:].strip())
    out = []
    if NETCTL_DIR.is_dir():
        for f in sorted(NETCTL_DIR.iterdir()):
            if f.is_file() and not f.name.startswith("."):
                try:
                    v = _shell_vars(f.read_text(errors="replace"))
                except OSError:
                    continue
                out.append({"name": f.name, "path": f, "kind": v.get("Connection", ""), "iface": v.get("Interface", ""),
                            "essid": v.get("ESSID", ""), "active": f.name in active, "vars": v})
    return out


def _netctl_read(iface: str, cfg: dict) -> dict:
    mine = [p for p in _netctl_profiles() if p["iface"] == iface]
    prof = next((p for p in mine if p["active"]), mine[0] if mine else None)
    if not prof:
        cfg["error"] = "netctl has no profile for this interface. Create one with netctl (see /etc/netctl/examples)."
        return cfg
    v = prof["vars"]
    cfg.update({"profile": prof["name"], "method": "manual" if v.get("IP") == "static" else "auto",
                "addresses": [a for a in v.get("Address", []) if ":" not in a] if isinstance(v.get("Address"), list) else [],
                "gateway": v.get("Gateway", "") if isinstance(v.get("Gateway"), str) else "",
                "dns": v.get("DNS", []) if isinstance(v.get("DNS"), list) else [],
                "routes": [parse_route(r) for r in v.get("Routes", [])] if isinstance(v.get("Routes"), list) else [],
                "ipv6": "off" if v.get("IP6") == "no" else "auto"})
    cfg["notes"].append("netctl has no route priority setting.")
    return cfg


def netctl_text(original: str, cfg: dict) -> str:
    """The profile with its address keys replaced and everything else (Security, Key, ESSID...) kept."""
    keys = ("IP", "Address", "Gateway", "DNS", "Routes", "IP6")
    kept = [line for line in original.splitlines() if not re.match(rf"^\s*({'|'.join(keys)})=", line)]
    new = ["IP=static" if cfg["method"] == "manual" else "IP=dhcp"]
    if cfg["method"] == "manual":
        new.append("Address=(" + " ".join(f"'{a}'" for a in cfg["addresses"]) + ")")
        if cfg["gateway"]:
            new.append(f"Gateway='{cfg['gateway']}'")
    if cfg["dns"]:
        new.append("DNS=(" + " ".join(f"'{d}'" for d in cfg["dns"]) + ")")
    if cfg["routes"]:
        new.append("Routes=(" + " ".join(f"'{d}" + (f" via {v}" if v else "") + "'" for d, v, _m in cfg["routes"]) + ")")
    new.append("IP6=no" if cfg["ipv6"] == "off" else "IP6=stateless")
    return "\n".join(kept + new) + "\n"


def _netctl_write(iface: str, cfg: dict) -> tuple[bool, str]:
    name = cfg.get("profile") or ""
    path = NETCTL_DIR / name
    if not name or not path.is_file():
        return False, "netctl has no profile for this interface."
    if cfg["metric"] is not None:
        return False, "netctl has no route priority setting. Clear it and save again."
    ok, msg = privileged("write", str(path), "--then", "netctl-restart", name, input=netctl_text(path.read_text(errors="replace"), cfg))
    return (True, f"Saved to {path} and restarted it.") if ok else (False, msg)


# ---- everything the page shows, cached briefly (the terminal version redraws often) ------------------------------
_state: dict = {"t": float("-inf"), "data": None}


def state(force: bool = False, rescan: bool = False) -> dict:
    """{'manager', 'wifi', 'interfaces', 'dns', 'wifi_on', 'networks'}; networks from the last scan unless rescan."""
    if not force and not rescan and time.monotonic() - _state["t"] < 10 and _state["data"]:
        return _state["data"]
    d = detect()
    ifaces = interfaces()
    has_wifi = any(i["kind"] == "wifi" for i in ifaces)
    wifi_on = wifi_enabled(d["wifi"]) if d["wifi"] and has_wifi else None
    data = {**d, "interfaces": ifaces, "dns": dns_servers(), "wifi_on": wifi_on,
            "networks": scan(d["wifi"], rescan=rescan) if has_wifi and d["wifi"] and wifi_on is not False else []}
    _state.update(t=time.monotonic(), data=data)
    return data


def invalidate() -> None:
    _state["t"] = float("-inf")


def summary(i: dict) -> str:
    """'connected · 192.168.1.50/24 via 192.168.1.1' for an interface row."""
    if not i["up"] and not i["ipv4"]:
        return "not connected"
    bits = " ".join(i["ipv4"][:2] + ([f"via {i['gateway']}"] if i["gateway"] else []))
    return "connected" + (f" · {bits}" if bits else "")


def config_text(cfg: dict) -> str:
    """One line describing a saved setup, for the terminal version."""
    if cfg.get("error"):
        return cfg["error"]
    if cfg["method"] == "manual":
        text = "fixed " + ", ".join(cfg["addresses"]) + (f" via {cfg['gateway']}" if cfg["gateway"] else "")
    else:
        text = "automatic (DHCP)"
    if cfg["dns"]:
        text += "; DNS " + " ".join(cfg["dns"])
    if cfg["routes"]:
        text += f"; {len(cfg['routes'])} extra route{'s' if len(cfg['routes']) != 1 else ''}"
    if cfg["metric"] is not None:
        text += f"; priority {cfg['metric']}"
    if cfg["ipv6"] == "off":
        text += "; IPv6 off"
    return text
