"""install/power/powerd.py against a made-up /sys: what each mode sets, and when the heat guard steps in and lets go."""
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

POWERD = Path(__file__).resolve().parents[1] / "power/powerd.py"

DMIDECODE = """Handle 0x0010, DMI type 17
Memory Device
\tSize: 16 GB
\tSpeed: 4800 MT/s
\tConfigured Memory Speed: 5300 MT/s

Handle 0x0011, DMI type 17
Memory Device
\tSize: No Module Installed
\tSpeed: Unknown
"""


class Power(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        sys_ = self.root / "sys"
        self.files = {
            "class/hwmon/hwmon0/name": "k10temp", "class/hwmon/hwmon0/temp1_label": "Tctl", "class/hwmon/hwmon0/temp1_input": "60000",
            "class/hwmon/hwmon1/name": "amdgpu", "class/hwmon/hwmon1/power1_cap": "236000000",
            "class/hwmon/hwmon1/power1_cap_default": "236000000", "class/hwmon/hwmon1/power1_cap_min": "212000000",
            "class/hwmon/hwmon1/temp2_label": "junction", "class/hwmon/hwmon1/temp2_input": "70000",
            "class/hwmon/hwmon2/name": "amdgpu", "class/hwmon/hwmon2/power1_cap": "15000000", "class/hwmon/hwmon2/power1_cap_default": "15000000",
            "class/hwmon/hwmon3/name": "spd5118", "class/hwmon/hwmon3/temp1_input": "54000",
            "devices/system/cpu/cpufreq/boost": "1",
            "devices/system/cpu/cpufreq/policy0/boost": "1", "devices/system/cpu/cpufreq/policy1/boost": "0",
            "devices/system/cpu/cpu0/cpufreq/energy_performance_preference": "balance_performance",
            "devices/system/cpu/cpu1/cpufreq/energy_performance_preference": "balance_performance",
            "devices/system/cpu/cpu0/cpufreq/energy_performance_available_preferences": "default performance balance_performance balance_power power",
        }
        for name, text in self.files.items():
            (sys_ / name).parent.mkdir(parents=True, exist_ok=True)
            (sys_ / name).write_text(text)
        self.sys = sys_
        os.environ.update(HYPRDOTS_SYS=str(sys_), HYPRDOTS_POWER_CONFIG=str(self.root / "power.json"), HYPRDOTS_POWER_RUN=str(self.root / "run"))
        for key in ("HYPRDOTS_SYS", "HYPRDOTS_POWER_CONFIG", "HYPRDOTS_POWER_RUN"):
            self.addCleanup(os.environ.pop, key)
        spec = importlib.util.spec_from_file_location("powerd", POWERD)
        self.p = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.p)
        self.p.ram_speeds = lambda text=None: {}  # no dmidecode in tests

    def get(self, name):
        return (self.sys / name).read_text()

    def put(self, name, text):
        (self.sys / name).write_text(text)

    def service(self, **config):
        return self.p.Service(), self.p.validate({**self.p.DEFAULTS, **config})

    def test_modes(self):
        s, c = self.service(mode="cool")
        status = s.step(c, 0)
        self.assertEqual(self.get("devices/system/cpu/cpufreq/boost"), "0")
        self.assertEqual(self.get("devices/system/cpu/cpu1/cpufreq/energy_performance_preference"), "power")
        self.assertEqual(self.get("class/hwmon/hwmon1/power1_cap"), "212000000", "the separate card, at its lowest")
        self.assertEqual(self.get("class/hwmon/hwmon2/power1_cap"), "15000000", "the built-in one is left alone")
        self.assertEqual(status["gpu"]["cap_w"], 212)
        self.assertEqual(self.get("devices/system/cpu/cpufreq/policy0/boost"), "0")
        s.step(self.p.validate({"mode": "full"}), 1)
        self.assertEqual(self.get("devices/system/cpu/cpufreq/boost"), "1")
        self.assertEqual(self.get("devices/system/cpu/cpufreq/policy1/boost"), "1", "every group of cores, not only the main switch")
        self.assertEqual(self.get("devices/system/cpu/cpu0/cpufreq/energy_performance_preference"), "balance_performance")
        self.assertEqual(self.get("class/hwmon/hwmon1/power1_cap"), "236000000")

    def test_guard_steps_in_after_staying_hot_and_lets_go_once_cool(self):
        s, c = self.service(mode="full", cpu_limit=92)
        self.put("class/hwmon/hwmon0/temp1_input", "95000")
        s.step(c, 0)
        s.step(c, 10)
        self.assertEqual(self.get("devices/system/cpu/cpufreq/boost"), "1", "not for a short spike")
        status = s.step(c, 16)
        self.assertEqual(self.get("devices/system/cpu/cpufreq/boost"), "0")
        self.assertTrue(status["cpu"]["held_back"])
        self.assertIn("95°C", status["events"][-1]["text"])
        self.put("class/hwmon/hwmon0/temp1_input", "85000")
        s.step(c, 100)
        self.assertEqual(self.get("devices/system/cpu/cpufreq/boost"), "0", "not cool enough yet")
        self.put("class/hwmon/hwmon0/temp1_input", "70000")
        s.step(c, 200)
        s.step(c, 230)
        self.assertEqual(self.get("devices/system/cpu/cpufreq/boost"), "0", "not cool for long enough")
        status = s.step(c, 261)
        self.assertEqual(self.get("devices/system/cpu/cpufreq/boost"), "1")
        self.assertIn("cooled", status["events"][-1]["text"])

    def test_guard_off_never_steps_in(self):
        s, c = self.service(guard=False)
        self.put("class/hwmon/hwmon0/temp1_input", "99000")
        for t in range(0, 60, 2):
            s.step(c, t)
        self.assertEqual(self.get("devices/system/cpu/cpufreq/boost"), "1")

    def test_hot_graphics_card_goes_to_its_lowest_limit(self):
        s, c = self.service(gpu_limit=100)
        self.put("class/hwmon/hwmon1/temp2_input", "104000")
        s.step(c, 0)
        s.step(c, 20)
        self.assertEqual(self.get("class/hwmon/hwmon1/power1_cap"), "212000000")

    def test_boost_off_in_the_bios_is_noticed_and_not_retried(self):
        s, c = self.service(mode="cool")
        s.step(c, 0)
        tries = []
        real = self.p.write

        def refuse(path, value):
            if path.endswith("cpufreq/boost") and value == "1":
                tries.append(value)
                return False
            return real(path, value)
        self.p.write = refuse
        for t in range(1, 6):
            status = s.step(self.p.validate({"mode": "full"}), t)
        self.assertEqual(len(tries), 1, "one try, then it is left alone")
        self.assertTrue(status["cpu"]["boost_locked"])
        self.assertEqual(self.get("devices/system/cpu/cpu0/cpufreq/energy_performance_preference"), "balance_performance", "the rest still applies")

    def test_stopping_puts_the_pc_back(self):
        s, c = self.service(mode="cool")
        s.step(c, 0)
        s.restore()
        self.assertEqual(self.get("devices/system/cpu/cpufreq/boost"), "1")
        self.assertEqual(self.get("class/hwmon/hwmon1/power1_cap"), "236000000")

    def test_ram_above_its_rating_is_reported(self):
        spec = importlib.util.spec_from_file_location("fresh", POWERD)
        fresh = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(fresh)
        self.assertEqual(fresh.ram_speeds(DMIDECODE), {"rated": 4800, "running": 5300, "above_rating": True})

    def test_a_bad_config_falls_back_to_safe_values(self):
        Path(os.environ["HYPRDOTS_POWER_CONFIG"]).write_text('{"mode": "turbo", "cpu_limit": 150, "guard": "yes"}')
        self.assertEqual(self.p.load_config(), self.p.DEFAULTS)

    def test_set_writes_the_config_and_refuses_nonsense(self):
        env = dict(os.environ)
        ok = subprocess.run([sys.executable, str(POWERD), "set", "mode=balanced", "guard=off", "cpu_limit=88"], env=env, capture_output=True, text=True)
        self.assertEqual(ok.returncode, 0, ok.stderr)
        self.assertEqual(json.loads(Path(env["HYPRDOTS_POWER_CONFIG"]).read_text()), {"mode": "balanced", "guard": False, "cpu_limit": 88, "gpu_limit": 100})
        for bad in ("mode=turbo", "cpu_limit=150", "colour=red"):
            self.assertNotEqual(subprocess.run([sys.executable, str(POWERD), "set", bad], env=env, capture_output=True).returncode, 0, bad)

    def test_status_is_published_for_everyone_to_read(self):
        s, c = self.service()
        self.p.publish(s.step(c, 0))
        path = Path(os.environ["HYPRDOTS_POWER_RUN"]) / "status.json"
        self.assertEqual(oct(path.stat().st_mode & 0o777), "0o644")
        status = json.loads(path.read_text())
        self.assertEqual((status["cpu"]["temp"], status["gpu"]["temp"], status["ram"]["temp"]), (60.0, 70.0, 54.0))


if __name__ == "__main__":
    unittest.main()
