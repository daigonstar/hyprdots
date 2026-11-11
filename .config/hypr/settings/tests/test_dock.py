"""Mac style's dock (waybar/scripts/dock.py): which apps it shows, in what order, and how icons swell."""

import importlib.util
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[3] / "waybar" / "scripts" / "dock.py"
spec = importlib.util.spec_from_file_location("dock", SCRIPT)
dock = importlib.util.module_from_spec(spec)
spec.loader.exec_module(dock)


def window(cls, address, recent, **more):
    return {"class": cls, "address": address, "focusHistoryID": recent, "title": f"{cls} window", **more}


class Apps(unittest.TestCase):
    def test_one_tile_per_app_bringing_its_latest_window(self):
        apps, _order = dock.group([window("zen", "0x1", 3), window("zen", "0x2", 0), window("thunar", "0x3", 1)], [])
        self.assertEqual([(a["class"], a["address"]) for a in apps], [("zen", "0x2"), ("thunar", "0x3")])

    def test_apps_keep_their_place_and_new_ones_join_at_the_end(self):
        _apps, order = dock.group([window("a", "0x1", 0), window("b", "0x2", 1)], [])
        apps, order = dock.group([window("c", "0x3", 0), window("b", "0x2", 1), window("a", "0x1", 2)], order)
        self.assertEqual(order, ["a", "b", "c"])
        apps, order = dock.group([window("c", "0x3", 0), window("a", "0x1", 1)], order)  # b closed
        self.assertEqual([a["class"] for a in apps], ["a", "c"])

    def test_hidden_and_unmapped_windows_are_left_out(self):
        apps, _ = dock.group([window("a", "0x1", 0, hidden=True), window("b", "0x2", 1, mapped=False),
                              window("", "0x3", 2)], [])
        self.assertEqual(apps, [])


class Swell(unittest.TestCase):
    def test_the_nearest_swells_most(self):
        sizes = [dock.swell(i, 3) for i in range(7)]
        self.assertEqual(sizes, [1.0, 1.12, 1.3, 1.55, 1.3, 1.12, 1.0])

    def test_no_pointer_no_swell(self):
        self.assertEqual(dock.swell(2, None), 1.0)

    def test_room_for_the_biggest_icon(self):
        cfg = dock.settings({"icon-size": 48, "margin-bottom": 6, "launchpad": "x"})
        self.assertGreaterEqual(cfg["height"], round(48 * dock.SWELL[-1]) + 6)
        self.assertIn(f"-gtk-icon-size: {round(48 * 1.55)}px", dock.css(cfg))


class Pointer(unittest.TestCase):
    """Two screens side by side: 2560x1440 at scale 1, then 1920x1080 at scale 1.5 (1280x720 in layout units)."""
    monitors = dock.logical([{"x": 0, "y": 0, "width": 2560, "height": 1440, "scale": 1.0, "transform": 0},
                             {"x": 2560, "y": 0, "width": 1920, "height": 1080, "scale": 1.5, "transform": 0}])

    def test_screens_in_layout_units(self):
        self.assertEqual(self.monitors[1], {"x": 2560, "y": 0, "w": 1280.0, "h": 720.0})
        (m,) = dock.logical([{"x": 0, "y": 0, "width": 1920, "height": 1080, "scale": 1, "transform": 1}])
        self.assertEqual((m["w"], m["h"]), (1080, 1920))  # on its side

    def test_on_the_dock_and_off_it(self):
        self.assertTrue(dock.near_dock(1200, 1439, self.monitors, 116))
        self.assertTrue(dock.near_dock(1200, 1440 - 116, self.monitors, 116))
        self.assertFalse(dock.near_dock(1200, 1440 - 117, self.monitors, 116))
        self.assertTrue(dock.near_dock(3000, 719, self.monitors, 116))  # bottom of the smaller screen
        self.assertFalse(dock.near_dock(-5, 1439, self.monitors, 116))  # off every screen


class Icons(unittest.TestCase):
    index = dock.desktop_index([("zen.desktop", "zen", "/usr/bin/zen-browser"),
                                ("com.mitchellh.ghostty.desktop", "", "ghostty"),
                                ("thunar.desktop", "Thunar", "thunar")])

    def test_by_window_class_desktop_id_or_program(self):
        self.assertEqual(dock.find_app("zen", self.index), "zen.desktop")
        self.assertEqual(dock.find_app("com.mitchellh.ghostty", self.index), "com.mitchellh.ghostty.desktop")
        self.assertEqual(dock.find_app("Thunar", self.index), "thunar.desktop")
        self.assertEqual(dock.find_app("zen-browser", self.index), "zen.desktop")
        self.assertIsNone(dock.find_app("nothing", self.index))


if __name__ == "__main__":
    unittest.main()
