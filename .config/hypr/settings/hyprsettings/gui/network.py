"""Network page: Wi-Fi, and each connection's addresses, DNS and routes. Applied straight away, through whichever
network manager runs this PC (see ..network). Anything slow runs in the background so the window never freezes."""

from __future__ import annotations

import shutil
import subprocess
import threading

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, GLib, Gtk  # noqa: E402

from .. import network  # noqa: E402
from ..schema import BY_ID, PAGE_INTRO  # noqa: E402
from . import ui  # noqa: E402
from .cloud import run_task  # noqa: E402

KIND_ICONS = {"ethernet": "network-wired-symbolic", "wifi": "network-wireless-symbolic"}


def _signal_icon(signal: int | None) -> str:
    if signal is None:
        return "network-wireless-symbolic"
    level = "excellent" if signal >= 75 else "good" if signal >= 50 else "ok" if signal >= 25 else "weak"
    return f"network-wireless-signal-{level}-symbolic"


def build(win) -> Gtk.Widget:
    scroller, column = ui.page_box(PAGE_INTRO["Network"])
    group = Adw.PreferencesGroup(title="Connections")
    refresh = Gtk.Button(icon_name="view-refresh-symbolic", css_classes=["flat"], tooltip_text="Look again")
    refresh.connect("clicked", lambda _b: (network.invalidate(), win.refresh()))
    group.set_header_suffix(refresh)
    loading = Adw.ActionRow(title="Looking at your network…")
    loading.add_prefix(Adw.Spinner())
    group.add(loading)
    column.append(group)

    def loaded(st):
        group.remove(loading)
        group.set_description(f"Run by {network.MANAGER_LABELS[st['manager']]}"
                              + (f", Wi-Fi by {network.WIFI_LABELS[st['wifi']]}" if st["wifi"] and st["wifi"] != st["manager"] else "")
                              + ". Click a connection to set its address, DNS and routes.")
        if not st["interfaces"]:
            group.add(Adw.ActionRow(title="No network cards found", use_markup=False))
        for i in st["interfaces"]:
            group.add(interface_row(win, st, i))
        if st["manager"] is None:
            column.append(Adw.StatusPage(
                title="No network manager is running", icon_name="network-offline-symbolic",
                description="Settings here are saved through NetworkManager, systemd-networkd, ConnMan, dhcpcd or netctl. "
                            "Start one (sudo systemctl enable --now NetworkManager) and look again."))
        if any(i["kind"] == "wifi" for i in st["interfaces"]):
            column.append(wifi_group(win, st))
        column.append(dns_group(st))
        column.append(tools_group(win))
        return False
    threading.Thread(target=lambda: GLib.idle_add(loaded, network.state()), daemon=True).start()
    return scroller


def interface_row(win, st: dict, i: dict) -> Adw.ActionRow:
    label = {"ethernet": "Wired", "wifi": "Wi-Fi"}.get(i["kind"], "Network")
    row = Adw.ActionRow(title=f"{label} ({i['name']})", subtitle=network.summary(i), activatable=True, use_markup=False)
    row.add_prefix(Gtk.Image(icon_name=KIND_ICONS.get(i["kind"], "network-wired-symbolic")))
    row.add_suffix(Gtk.Label(label="connected" if i["up"] and i["ipv4"] else "off", valign=Gtk.Align.CENTER,
                             css_classes=["tag", "yours" if i["up"] and i["ipv4"] else "default"]))
    row.add_suffix(Gtk.Image(icon_name="go-next-symbolic"))
    row.connect("activated", lambda _r: open_settings(win, st["manager"], i["name"]))
    return row


# ---- Wi-Fi -----------------------------------------------------------------------------------------------------
def wifi_group(win, st: dict) -> Adw.PreferencesGroup:
    backend = st["wifi"]
    group = Adw.PreferencesGroup(title="Wi-Fi")
    if not backend:
        group.set_description("No Wi-Fi service is running. Install and start iwd (sudo systemctl enable --now iwd), "
                              "or use NetworkManager, then look again.")
        return group
    scan = Gtk.Button(icon_name="view-refresh-symbolic", css_classes=["flat"], tooltip_text="Scan for networks")
    group.set_header_suffix(scan)
    power = Adw.SwitchRow(title="Wi-Fi", active=bool(st["wifi_on"]))
    group.add(power)

    def toggled(w, _p):
        if w.get_active() != bool(st["wifi_on"]):
            run_task(win, "Switching Wi-Fi " + ("on" if w.get_active() else "off"),
                     lambda s, c: _then_invalidate(network.set_wifi_enabled(backend, w.get_active())))
    power.connect("notify::active", toggled)
    if st["wifi_on"] is False:
        return group

    rows: list[Gtk.Widget] = []

    def fill(networks):
        for r in rows:
            group.remove(r)
        rows.clear()
        if not networks:
            rows.append(Adw.ActionRow(title="No networks found", subtitle="Scan again with the button above.", use_markup=False))
        for n in networks[:30]:
            rows.append(network_row(win, backend, n))
        hidden = Adw.ButtonRow(title="Join a hidden network…", start_icon_name="list-add-symbolic")
        hidden.connect("activated", lambda _r: join(win, backend, None))
        rows.append(hidden)
        for r in rows:
            group.add(r)
        scan.set_sensitive(True)
        return False

    def rescan(_b=None):
        scan.set_sensitive(False)
        for r in rows:
            group.remove(r)
        rows.clear()
        spin = Adw.ActionRow(title="Scanning…")
        spin.add_prefix(Adw.Spinner())
        rows.append(spin)
        group.add(spin)
        threading.Thread(target=lambda: GLib.idle_add(fill, network.state(rescan=True)["networks"]), daemon=True).start()
    scan.connect("clicked", rescan)
    fill(st["networks"])
    return group


def network_row(win, backend: str, n: dict) -> Adw.ActionRow:
    sub = " · ".join(x for x in ("connected" if n["active"] else "saved" if n["known"] else "",
                                 "secured" if n["secure"] else "open",
                                 f"{n['signal']}%" if n["signal"] is not None else "") if x)
    row = Adw.ActionRow(title=n["ssid"], subtitle=sub, activatable=not n["active"], use_markup=False)
    row.add_prefix(Gtk.Image(icon_name=_signal_icon(n["signal"])))
    if n["secure"]:
        row.add_suffix(Gtk.Image(icon_name="channel-secure-symbolic", css_classes=["dim-label"]))
    if n["active"]:
        b = Gtk.Button(label="Disconnect", valign=Gtk.Align.CENTER, css_classes=["flat"])
        b.connect("clicked", lambda _b: run_task(win, f"Disconnecting from {n['ssid']}",
                                                 lambda s, c: _then_invalidate(network.disconnect(backend, n["ssid"], n["id"]))))
        row.add_suffix(b)
    if n["known"]:
        b = Gtk.Button(icon_name="user-trash-symbolic", tooltip_text="Forget this network", valign=Gtk.Align.CENTER, css_classes=["flat"])
        b.connect("clicked", lambda _b: ui.confirm(
            win, "Forget this network?", f"Forget '{n['ssid']}' and its password? You can join it again later.", "Forget",
            lambda: run_task(win, f"Forgetting {n['ssid']}", lambda s, c: _then_invalidate(network.forget(backend, n["ssid"], n["id"]))),
            destructive=True))
        row.add_suffix(b)
    row.connect("activated", lambda _r: join(win, backend, n))
    return row


def join(win, backend: str, n: dict | None) -> None:
    """Joins n (asking for its password when it is secured and not saved), or a hidden network when n is None."""
    def go(ssid, password, hidden=False):
        run_task(win, f"Connecting to {ssid}",
                 lambda s, c: _then_invalidate(network.connect(backend, ssid, password, hidden, n["id"] if n else "")))

    if n is None:
        def hidden(ssid, password):
            if not ssid.strip():
                raise ValueError("Enter the network's name.")
            if password and not 8 <= len(password) <= 63:
                raise ValueError("A Wi-Fi password is 8 to 63 characters.")
            go(ssid.strip(), password, True)
        ui.ask(win, "Join a hidden network", hidden, [("Network name", ""), ("Password (leave empty if open)", "", True)], ok="Join")
    elif n["secure"] and not n["known"]:
        def got(password):
            if not 8 <= len(password) <= 63:
                raise ValueError("A Wi-Fi password is 8 to 63 characters.")
            go(n["ssid"], password)
        ui.ask(win, f"Join {n['ssid']}", got, [("Password", "", True)], ok="Join")
    else:
        go(n["ssid"], "")


def _then_invalidate(result):
    network.invalidate()
    return result


# ---- DNS and tools ---------------------------------------------------------------------------------------------
def dns_group(st: dict) -> Adw.PreferencesGroup:
    group = Adw.PreferencesGroup(title="DNS in use", description="Set your own per connection: click it above.")
    row = Adw.ActionRow(title=", ".join(st["dns"]) or "none", subtitle="The servers this PC asks to look up names",
                        use_markup=False, subtitle_selectable=True)
    group.add(row)
    return group


def tools_group(win) -> Adw.PreferencesGroup:
    """VPNs, bridges and the like are left to the manager's own tools."""
    group = Adw.PreferencesGroup(title="More", description="VPNs, bridges, VLANs and other rare setups are made with your "
                                                           "network manager's own tools.")
    term = str(win.store.get(BY_ID["hyprdots.terminal"])[0])
    for cmd, title, sub, in_term in (("nm-connection-editor", "Network connections", "NetworkManager's full editor", False),
                                     ("nmtui", "nmtui", "NetworkManager in a terminal", True),
                                     ("iwctl", "iwctl", "iwd in a terminal", True),
                                     ("connmanctl", "connmanctl", "ConnMan in a terminal", True)):
        if not shutil.which(cmd) or (cmd == "iwctl" and shutil.which("nmtui")):
            continue
        row = Adw.ActionRow(title=title, subtitle=sub, activatable=True, use_markup=False)
        row.add_suffix(Gtk.Image(icon_name="adw-external-link-symbolic"))
        row.connect("activated", lambda _r, cmd=cmd, in_term=in_term: subprocess.Popen(
            ([term, "-e", cmd] if in_term else [cmd]), start_new_session=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL))
        group.add(row)
    return group


# ---- one connection's addresses, DNS and routes -------------------------------------------------------------------
def open_settings(win, manager: str | None, iface: str) -> None:
    def loaded(cfg):
        if cfg.get("error"):
            ui.message(win, iface, cfg["error"])
        else:
            settings_dialog(win, manager, iface, cfg)
        return False
    threading.Thread(target=lambda: GLib.idle_add(loaded, network.ip_config(manager, iface)), daemon=True).start()


def settings_dialog(win, manager: str | None, iface: str, cfg: dict) -> None:
    dialog = Adw.Dialog(title=iface, content_width=500, content_height=640)
    view = Adw.ToolbarView()
    header = Adw.HeaderBar(show_end_title_buttons=False, show_start_title_buttons=False)
    cancel = Gtk.Button(label="Cancel")
    cancel.connect("clicked", lambda _b: dialog.close())
    save = Gtk.Button(label="Apply", css_classes=["suggested-action"])
    header.pack_start(cancel)
    header.pack_end(save)
    view.add_top_bar(header)
    page = Adw.PreferencesPage()

    top = Adw.PreferencesGroup(title="Address", description=(f"Saved in {cfg['profile']}" if cfg["profile"] else None))
    method = Adw.ComboRow(title="Get an address", model=Gtk.StringList.new(["Automatically (DHCP)", "Fixed (static)"]),
                          selected=1 if cfg["method"] == "manual" else 0)
    addresses = Adw.EntryRow(title="IP address, like 192.168.1.50/24", text=", ".join(cfg["addresses"]))
    gateway = Adw.EntryRow(title="Gateway (your router), like 192.168.1.1", text=cfg["gateway"])
    for w in (method, addresses, gateway):
        top.add(w)

    def follow(*_a):
        fixed = method.get_selected() == 1
        addresses.set_sensitive(fixed)
        gateway.set_sensitive(fixed)
    method.connect("notify::selected", follow)
    follow()
    page.add(top)

    more = Adw.PreferencesGroup(title="DNS and priority")
    dns = Adw.EntryRow(title="DNS servers (empty: from the router)", text=" ".join(cfg["dns"]))
    metric = Adw.EntryRow(title="Route priority (empty: automatic; lower wins)",
                          text="" if cfg["metric"] is None else str(cfg["metric"]))
    ipv6 = Adw.ComboRow(title="IPv6", model=Gtk.StringList.new(["Automatic", "Off"]), selected=1 if cfg["ipv6"] == "off" else 0)
    more.add(dns)
    if not cfg.get("no_routes") and manager != "netctl":
        more.add(metric)
    more.add(ipv6)
    page.add(more)

    routes = list(cfg["routes"])
    rgroup = Adw.PreferencesGroup(title="Extra routes", description="Send traffic for some networks a different way, for "
                                                                    "example 10.0.0.0/8 via 192.168.1.254.")
    rrows: list[Gtk.Widget] = []

    def draw_routes():
        for r in rrows:
            rgroup.remove(r)
        rrows.clear()
        for idx, (dest, via, m) in enumerate(routes):
            row = Adw.ActionRow(title=dest, subtitle=(f"via {via}" if via else "on this link") + (f" · metric {m}" if m is not None else ""),
                                use_markup=False)
            b = Gtk.Button(icon_name="user-trash-symbolic", valign=Gtk.Align.CENTER, css_classes=["flat"], tooltip_text="Remove")
            b.connect("clicked", lambda _b, idx=idx: (routes.pop(idx), draw_routes()))
            row.add_suffix(b)
            rrows.append(row)
        add = Adw.ButtonRow(title="Add a route…", start_icon_name="list-add-symbolic")

        def adding(_r):
            def done(dest, via, m):
                r = network.check_config({"routes": [(dest, via, m.strip() or None)]})["routes"][0]
                routes.append(r)
                draw_routes()
            ui.ask(win, "Add a route", done, [("Network, like 10.0.0.0/8", ""), ("Via (gateway), like 192.168.1.254", ""),
                                              ("Metric (optional)", "")], ok="Add")
        add.connect("activated", adding)
        rrows.append(add)
        for r in rrows:
            rgroup.add(r)
    if not cfg.get("no_routes"):
        draw_routes()
        page.add(rgroup)

    info = Adw.PreferencesGroup()
    for note in cfg["notes"]:
        info.add(Gtk.Label(label=note, wrap=True, xalign=0, css_classes=["dim-label"], margin_bottom=6))
    error = Gtk.Label(wrap=True, xalign=0, css_classes=["error-text"], visible=False)
    info.add(error)
    page.add(info)

    def apply(_b):
        new = {**cfg, "method": "manual" if method.get_selected() == 1 else "auto",
               "addresses": [a for a in addresses.get_text().replace(",", " ").split()],
               "gateway": gateway.get_text(), "dns": dns.get_text().replace(",", " ").split(),
               "routes": routes, "metric": metric.get_text().strip() or None, "ipv6": "off" if ipv6.get_selected() == 1 else "auto"}
        try:
            if new["metric"] is not None and not str(new["metric"]).isdigit():
                raise ValueError("The route priority is a whole number, like 100.")
            network.check_config(new)
        except ValueError as e:
            error.set_label(str(e))
            error.set_visible(True)
            return
        dialog.close()
        run_task(win, f"Applying to {iface}", lambda s, c: _then_invalidate(network.set_ip_config(manager, iface, new)),
                 body="The connection may drop for a moment while it restarts.")
    save.connect("clicked", apply)
    view.set_content(page)
    dialog.set_child(view)
    dialog.present(win)
