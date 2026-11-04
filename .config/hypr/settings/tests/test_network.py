"""Network page backend: checking input, the files written for each manager, and reading each Wi-Fi tool's output.
No real network is touched: network.run is replaced by a fake that answers from a table."""

import subprocess
import unittest
from unittest import mock

import _paths  # noqa: F401
from hyprsettings import network


class WifiDevice(unittest.TestCase):
    def pick(self, *cards):
        found = [{"name": name, "kind": kind, "up": up} for name, kind, up in cards]
        with mock.patch.object(network, "interfaces", return_value=found):
            return network.wifi_device()

    def test_the_card_in_use_beats_an_idle_one_listed_first(self):
        self.assertEqual(self.pick(("enp1", "ethernet", True), ("mlan0", "wifi", False), ("wlan4", "wifi", True)), "wlan4")

    def test_an_idle_card_when_none_is_in_use(self):
        self.assertEqual(self.pick(("wlan0", "wifi", False)), "wlan0")

    def test_no_card(self):
        self.assertEqual(self.pick(("enp1", "ethernet", True)), "")


class Fake:
    """Stands in for network.run: answers by the first matching command prefix and records every call."""
    def __init__(self, answers=None):
        self.answers = answers or {}
        self.calls = []

    def __call__(self, args, input=None, timeout=40):
        self.calls.append(args)
        for prefix, out in self.answers.items():
            if tuple(args[:len(prefix)]) == prefix:
                return subprocess.CompletedProcess(args, 0, out, "")
        return subprocess.CompletedProcess(args, 0, "", "")


def cfg(**kw):
    return {**network.blank_config(), **kw}


class CheckConfig(unittest.TestCase):
    def test_static_needs_an_address_and_gets_a_default_prefix(self):
        with self.assertRaisesRegex(ValueError, "at least one address"):
            network.check_config(cfg(method="manual"))
        self.assertEqual(network.check_config(cfg(method="manual", addresses=["192.168.1.5"]))["addresses"], ["192.168.1.5/24"])

    def test_gateway_must_be_reachable(self):
        with self.assertRaisesRegex(ValueError, "not inside"):
            network.check_config(cfg(method="manual", addresses=["192.168.1.5/24"], gateway="10.0.0.1"))

    def test_bad_values_are_explained(self):
        for bad in (cfg(dns=["one.one"]), cfg(method="manual", addresses=["300.1.1.1/24"]), cfg(routes=[("nowhere", "", None)]),
                    cfg(metric=70000)):
            with self.assertRaises(ValueError):
                network.check_config(bad)

    def test_routes_are_tidied(self):
        out = network.check_config(cfg(routes=[network.parse_route("10.1.2.3/8 via 192.168.1.254 metric 50")]))
        self.assertEqual(out["routes"], [("10.0.0.0/8", "192.168.1.254", 50)])
        self.assertEqual(network.parse_route("172.16.0.0/12 192.168.1.1"), ("172.16.0.0/12", "192.168.1.1", None))


class Files(unittest.TestCase):
    def test_networkd_static_file(self):
        text = network.networkd_text("eno1", network.check_config(cfg(
            method="manual", addresses=["192.168.1.50/24"], gateway="192.168.1.1", dns=["1.1.1.1"], metric=100,
            routes=[("10.0.0.0/8", "192.168.1.254", None)], ipv6="off")))
        for line in ("Name=eno1", "Address=192.168.1.50/24", "DHCP=no", "DNS=1.1.1.1", "Gateway=192.168.1.1", "Metric=100",
                     "Destination=10.0.0.0/8", "Gateway=192.168.1.254", "LinkLocalAddressing=ipv4"):
            self.assertIn(line, text.splitlines())

    def test_networkd_dhcp_file(self):
        text = network.networkd_text("wlan0", network.check_config(cfg(metric=600)))
        self.assertIn("DHCP=yes", text)
        self.assertIn("RouteMetric=600", text)
        self.assertNotIn("Address=", text)

    def test_networkd_file_reads_back(self):
        want = network.check_config(cfg(method="manual", addresses=["192.168.1.50/24"], gateway="192.168.1.1", dns=["9.9.9.9"],
                                        routes=[("10.0.0.0/8", "192.168.1.254", 20)], metric=100))
        path = mock.Mock(name="file")
        path.read_text.return_value = network.networkd_text("eno1", want)
        path.name = "10-hyprdots-eno1.network"
        with mock.patch.object(network, "_networkd_file", return_value=path):
            got = network.ip_config("networkd", "eno1")
        for key in ("method", "addresses", "gateway", "dns", "routes", "metric", "ipv6"):
            self.assertEqual(got[key], want[key], key)

    def test_netctl_keeps_the_wifi_lines(self):
        original = "Description='home'\nInterface=wlan0\nConnection=wireless\nSecurity=wpa\nESSID='Home'\nKey='secret pw'\nIP=dhcp\n"
        text = network.netctl_text(original, network.check_config(cfg(method="manual", addresses=["10.0.0.9/24"],
                                                                        gateway="10.0.0.1", dns=["10.0.0.1"])))
        self.assertIn("Key='secret pw'", text)
        self.assertIn("IP=static", text)
        self.assertIn("Address=('10.0.0.9/24')", text)
        self.assertNotIn("IP=dhcp", text)
        self.assertEqual(network._shell_vars(text)["Address"], ["10.0.0.9/24"])

    def test_dhcpcd_block_is_replaced_not_stacked(self):
        conf = "hostname\noption rapid_commit\n"
        fake = Fake()
        sent = {}

        def helper(*args, input=None):
            sent["text"] = input
            return True, "Saved."
        with mock.patch.object(network, "privileged", side_effect=helper), \
                mock.patch.object(network.Path, "read_text", side_effect=lambda *a, **k: conf), \
                mock.patch.object(network.Path, "exists", return_value=True), mock.patch.object(network, "run", fake):
            network.set_ip_config("dhcpcd", "eno1", cfg(method="manual", addresses=["192.168.1.9/24"], gateway="192.168.1.1"))
            conf = sent["text"]
            network.set_ip_config("dhcpcd", "eno1", cfg(method="manual", addresses=["192.168.1.10/24"], gateway="192.168.1.1"))
        text = sent["text"]
        self.assertEqual(text.count("interface eno1"), 1)
        self.assertIn("static ip_address=192.168.1.10/24", text)
        self.assertTrue(text.startswith("hostname\noption rapid_commit\n"))


class NetworkManager(unittest.TestCase):
    def test_static_setup_becomes_one_nmcli_command_then_reconnects(self):
        fake = Fake({("nmcli", "-g", "GENERAL.CON-UUID"): "uuid-1\n"})
        with mock.patch.object(network, "run", fake):
            ok, _ = network.set_ip_config("nm", "eno1", cfg(method="manual", addresses=["192.168.1.50/24"], gateway="192.168.1.1",
                                                             dns=["1.1.1.1", "2606:4700::1111"], routes=[("10.0.0.0/8", "192.168.1.254", 5)]))
        self.assertTrue(ok)
        mod = next(c for c in fake.calls if c[:3] == ["nmcli", "con", "mod"])
        args = dict(zip(mod[4::2], mod[5::2]))
        self.assertEqual(args["ipv4.method"], "manual")
        self.assertEqual(args["ipv4.addresses"], "192.168.1.50/24")
        self.assertEqual(args["ipv4.dns"], "1.1.1.1")
        self.assertEqual(args["ipv6.dns"], "2606:4700::1111")
        self.assertEqual(args["ipv4.routes"], "10.0.0.0/8 192.168.1.254 5")
        self.assertIn(["nmcli", "con", "up", "uuid", "uuid-1"], fake.calls)

    def test_going_back_to_dhcp_clears_the_fixed_address(self):
        fake = Fake({("nmcli", "-g", "GENERAL.CON-UUID"): "uuid-1\n"})
        with mock.patch.object(network, "run", fake):
            network.set_ip_config("nm", "eno1", cfg(uuid="uuid-1"))
        mod = next(c for c in fake.calls if c[:3] == ["nmcli", "con", "mod"])
        args = dict(zip(mod[4::2], mod[5::2]))
        self.assertEqual((args["ipv4.method"], args["ipv4.addresses"], args["ipv4.gateway"]), ("auto", "", ""))

    def test_wifi_list_with_colons_in_names(self):
        fake = Fake({("nmcli", "-t", "-f", "NAME,TYPE"): "Cafe\\: Free:802-11-wireless\n",
                     ("nmcli", "-t", "-f", "IN-USE,SSID,SIGNAL,SECURITY"): "*:Home:80:WPA2\n :Cafe\\: Free:40:\n :Home:30:WPA2\n"})
        with mock.patch.object(network, "run", fake):
            nets = network.scan("nm", rescan=False)
        self.assertEqual([(n["ssid"], n["active"], n["known"], n["secure"]) for n in nets],
                         [("Home", True, False, True), ("Cafe: Free", False, True, False)])


class OtherWifiTools(unittest.TestCase):
    def test_iwd_table(self):
        table = ("\x1b[1;90m   Available networks\x1b[0m\n\x1b[90m-----------\n\x1b[0m\x1b[1;90m   Network name   Security   Signal\n"
                 "\x1b[0m\x1b[90m-----------\n\x1b[0m  \x1b[1;90m> \x1b[0m Home Net        psk        -5500\n"
                 "      Cafe            open       -8200\n")
        fake = Fake({("iwctl", "station", "wlan0", "get-networks"): table, ("iwctl", "known-networks"): ""})
        with mock.patch.object(network, "run", fake), mock.patch.object(network, "wifi_device", return_value="wlan0"):
            nets = network.scan("iwd", rescan=False)
        self.assertEqual([(n["ssid"], n["active"], n["secure"], n["signal"]) for n in nets],
                         [("Home Net", True, True, 90), ("Cafe", False, False, 36)])

    def test_wpa_supplicant(self):
        fake = Fake({("wpa_cli", "-i", "wlan0", "list_networks"): "network id / ssid / bssid / flags\n0\tHome\tany\t[CURRENT]\n",
                     ("wpa_cli", "-i", "wlan0", "scan_results"): "bssid / frequency / signal level / flags / ssid\n"
                                                                 "aa:bb\t2412\t-60\t[WPA2-PSK-CCMP][ESS]\tHome\n"
                                                                 "cc:dd\t5180\t-75\t[ESS]\tCafe\n"})
        with mock.patch.object(network, "run", fake), mock.patch.object(network, "wifi_device", return_value="wlan0"):
            nets = network.scan("wpa", rescan=False)
        self.assertEqual([(n["ssid"], n["active"], n["known"], n["secure"], n["signal"], n["id"]) for n in nets],
                         [("Home", True, True, True, 80, "0"), ("Cafe", False, False, False, 50, "")])

    def test_connman_services(self):
        out = "*AO Home Net             wifi_aabb_486f6d65_managed_psk\n    Cafe                 wifi_ccdd_43616665_managed_none\n" \
              "*AO Wired                ethernet_aabb_cable\n"
        with mock.patch.object(network, "run", Fake({("connmanctl", "services"): out})):
            nets = network.scan("connman", rescan=False)
        self.assertEqual([(n["ssid"], n["active"], n["known"], n["secure"]) for n in nets],
                         [("Home Net", True, True, True), ("Cafe", False, False, False)])


if __name__ == "__main__":
    unittest.main()
