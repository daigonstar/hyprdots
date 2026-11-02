import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import sysinfo  # noqa: E402


def tree(root: Path, files: dict[str, str]) -> Path:
    for name, text in files.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
    return root


class Hardware(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)

    def test_desktop_with_a_wireless_mouse_is_not_a_laptop(self):
        tree(self.root, {"class/dmi/id/chassis_type": "3\n", "class/power_supply/hidpp_battery_0/type": "Battery\n",
                         "class/power_supply/hidpp_battery_0/scope": "Device\n",
                         "class/power_supply/hidpp_battery_0/capacity": "57\n",
                         "class/power_supply/hidpp_battery_0/model_name": "G502\n"})
        self.assertFalse(sysinfo.is_laptop(self.root))
        self.assertIsNone(sysinfo.system_battery(self.root))
        self.assertEqual([b["model"] for b in sysinfo.peripherals(self.root)], ["G502"])

    def test_system_battery_makes_a_laptop_even_with_an_odd_chassis(self):
        tree(self.root, {"class/dmi/id/chassis_type": "3\n", "class/power_supply/BAT0/type": "Battery\n",
                         "class/power_supply/BAT0/capacity": "80\n", "class/power_supply/AC/type": "Mains\n"})
        self.assertTrue(sysinfo.is_laptop(self.root))
        self.assertEqual(sysinfo.system_battery(self.root)["capacity"], 80)
        self.assertEqual(sysinfo.peripherals(self.root), [])

    def test_portable_chassis_is_a_laptop(self):
        tree(self.root, {"class/dmi/id/chassis_type": "10\n"})
        self.assertTrue(sysinfo.is_laptop(self.root))

    def test_missing_sysfs_means_a_plain_desktop(self):
        self.assertFalse(sysinfo.is_laptop(self.root))
        self.assertFalse(sysinfo.backlight(self.root))
        self.assertFalse(sysinfo.has_bluetooth(self.root))
        self.assertIsNone(sysinfo.cpu_temp(self.root))

    def test_graphics_card_wins_over_built_in_graphics(self):
        tree(self.root, {"class/drm/card0/device/mem_info_vram_total": "536870912\n",
                         "class/drm/card0/device/gpu_busy_percent": "0\n",
                         "class/drm/card1/device/mem_info_vram_total": "17163091968\n",
                         "class/drm/card1/device/mem_info_vram_used": "1073741824\n",
                         "class/drm/card1/device/gpu_busy_percent": "8\n",
                         "class/drm/card1/device/hwmon/hwmon3/temp1_input": "52000\n"})
        self.assertEqual(sysinfo.gpu(self.root), {"busy": 8, "used": 1073741824, "total": 17163091968, "temp": 52.0})


class Alerts(unittest.TestCase):
    def run_down(self, levels, status="Discharging"):
        said, reached = [], None
        for level in levels:
            alert, reached = sysinfo.battery_alert(level, status, reached)
            said.append(alert)
        return said

    def test_each_step_speaks_once_on_the_way_down(self):
        self.assertEqual(self.run_down([20, 15, 14, 5, 4, 3, 2]), [None, "low", None, "critical", None, "sleep", None])

    def test_opening_at_a_low_level_says_the_lowest_only(self):
        self.assertEqual(self.run_down([4, 4]), ["critical", None])

    def test_charging_stays_quiet_and_starts_over(self):
        self.assertEqual(self.run_down([3, 2], "Charging"), [None, None])
        alert, reached = sysinfo.battery_alert(10, "Discharging", None)
        self.assertEqual(alert, "low")
        self.assertEqual(sysinfo.battery_alert(10, "Charging", reached), (None, None))
        self.assertEqual(sysinfo.battery_alert(10, "Discharging", None)[0], "low")

    def test_unknown_capacity(self):
        self.assertEqual(sysinfo.battery_alert(None, "Discharging", 15), (None, None))

    def test_peripheral_warns_once_and_must_recover(self):
        said, warned = [], False
        for level in (12, 10, 9, 11, 10, 20, 8):
            now, warned = sysinfo.peripheral_alert(level, warned)
            said.append(now)
        self.assertEqual(said, [False, True, False, False, False, False, True])


class Numbers(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)

    def test_cpu_percent(self):
        tree(self.root, {"stat": "cpu  100 0 100 700 100 0 0 0 0 0\ncpu0 1 1 1 1\n"})
        self.assertEqual(sysinfo.cpu_times(self.root), (200, 1000))
        self.assertEqual(sysinfo.percent_between((200, 1000), (300, 1200)), 50.0)
        self.assertEqual(sysinfo.percent_between((200, 1000), (200, 1000)), 0.0)

    def test_memory_leaves_out_caches(self):
        tree(self.root, {"meminfo": "MemTotal: 1000 kB\nMemFree: 100 kB\nMemAvailable: 400 kB\n"})
        self.assertEqual(sysinfo.memory(self.root), (600 * 1024, 1000 * 1024))

    def test_net_skips_containers(self):
        head = "Inter-|   Receive  |  Transmit\n face |bytes packets|bytes packets\n"
        row = " 1 0 0 0 0 0 0 0 2 0 0 0 0 0 0 0\n"
        tree(self.root, {"net/dev": head + "    lo:" + row + "docker0:" + row + "  eno1:" + row})
        self.assertEqual(sysinfo.net_bytes(self.root), (1, 2))

    def test_parse_volume(self):
        self.assertEqual(sysinfo.parse_volume("Volume: 0.42\n"), (42, False))
        self.assertEqual(sysinfo.parse_volume("Volume: 0.00 [MUTED]\n"), (0, True))
        self.assertIsNone(sysinfo.parse_volume("Translate ID failed\n"))

    def test_parse_network_ignores_container_ethernet(self):
        got = sysinfo.parse_network("ethernet:connected:Wired connection 1\nbridge:connected (externally):docker0\n"
                                    "wifi:disconnected:\nethernet:unmanaged:\n")
        self.assertEqual(got, {"wifi": True, "wifi_name": "", "ethernet": True, "ethernet_on": True})
        self.assertFalse(sysinfo.parse_network("ethernet:unmanaged:\n")["ethernet"])
        self.assertEqual(sysinfo.parse_network("wifi:connected:Home\n")["wifi_name"], "Home")

    def test_formats(self):
        self.assertEqual(sysinfo.fmt_bytes(512), "512 B")
        self.assertEqual(sysinfo.fmt_bytes(1536), "2 KB")
        self.assertEqual(sysinfo.fmt_bytes(3 * 1024 ** 3), "3.0 GB")
        self.assertEqual(sysinfo.fmt_uptime(90060), "1d 1h")
        self.assertEqual(sysinfo.fmt_uptime(3720), "1h 2m")
        self.assertEqual(sysinfo.fmt_uptime(120), "2m")


if __name__ == "__main__":
    unittest.main()
