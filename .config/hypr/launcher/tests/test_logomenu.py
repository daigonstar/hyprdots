"""The menu under Mac style's menu bar logo: what it lists and the facts its About card shows."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import logomenu  # noqa: E402
import search  # noqa: E402


class About(unittest.TestCase):
    def test_system_name(self):
        self.assertEqual(logomenu.os_name('NAME="Arch Linux"\nPRETTY_NAME="Arch Linux"\nID=arch\n'), "Arch Linux")

    def test_processor(self):
        text = "processor\t: 0\nmodel name\t: AMD Ryzen 9  7950X 16-Core Processor\n"
        self.assertEqual(logomenu.cpu_name(text), "AMD Ryzen 9 7950X 16-Core Processor")

    def test_memory_is_shown_as_sold(self):
        self.assertEqual(logomenu.memory("MemTotal:       32651712 kB\n"), "32 GB")
        self.assertEqual(logomenu.memory("MemTotal:       16303016 kB\n"), "16 GB")
        self.assertEqual(logomenu.memory("nothing here\n"), "Unknown")

    def test_uptime(self):
        self.assertEqual(logomenu.uptime(59), "0 minutes")
        self.assertEqual(logomenu.uptime(3 * 3600 + 120), "3 hours, 2 minutes")
        self.assertEqual(logomenu.uptime(86400 + 3600), "1 day, 1 hour")


class Entries(unittest.TestCase):
    def test_the_menu(self):
        got = logomenu.items("Robert", {"lock": "Super+L"}, "flatpak run x")
        titles = [e["title"] for e in got if e]
        self.assertEqual(titles[0], "About this PC")
        self.assertIn("Force quit…", titles)
        self.assertEqual(titles[-1], "Log out Robert…")
        lock = next(e for e in got if e and e["title"] == "Lock screen")
        self.assertEqual(lock["keys"], "Super+L")
        store = next(e for e in got if e and e["title"] == "App store…")
        self.assertEqual(store["cmd"], ["flatpak", "run", "x"])

    def test_the_risky_ones_ask_first(self):
        asks = {e["title"] for e in logomenu.items("R", {}, "x") if e and e.get("confirm")}
        self.assertEqual(asks, {"Restart…", "Shut down…", "Log out R…"})

    def test_power_commands_are_the_launchers(self):
        for e in logomenu.items("R", {}, "x"):
            if e and e["kind"] == "power":
                self.assertIn(e["cmd"], [cmd for _w, _l, cmd, _c in search.POWER])

    def test_shortcuts(self):
        self.assertEqual(logomenu.shortcut("SUPER + L"), "Super+L")
        self.assertEqual(logomenu.shortcut("SUPER + SHIFT + a"), "Super+Shift+A")


class Windows(unittest.TestCase):
    def test_one_per_app_most_recent_first_and_never_pid_1(self):
        clients = [{"class": "a", "title": "A1", "pid": 10, "focusHistoryID": 2},
                   {"class": "a", "title": "A2", "pid": 10, "focusHistoryID": 0},
                   {"class": "b", "title": "B", "pid": 20, "focusHistoryID": 1},
                   {"class": "x", "title": "X", "pid": 1, "focusHistoryID": 3},
                   {"class": "h", "title": "hidden", "pid": 30, "mapped": False}]
        got = logomenu.windows(clients)
        self.assertEqual([(w["app"], w["title"]) for w in got], [("a", "A2"), ("b", "B")])


if __name__ == "__main__":
    unittest.main()
