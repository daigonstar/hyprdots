from pathlib import Path
from unittest import mock
import tempfile
import json
import unittest

import _paths
from hyprsettings import barlayout


class Recording(unittest.TestCase):
    CONFIG = {"custom/recording": {}}

    def test_old_layout_gains_the_dot_before_power(self):
        got = barlayout.with_recording({"modules-left": [], "modules-center": [], "modules-right": ["clock", "custom/power", "custom/noti"]}, self.CONFIG)
        self.assertEqual(got["modules-right"], ["clock", "custom/recording", "custom/power", "custom/noti"])

    def test_placed_anywhere_is_left_alone(self):
        layout = {"modules-left": ["custom/recording"], "modules-center": [], "modules-right": []}
        self.assertEqual(barlayout.with_recording(layout, self.CONFIG), layout)

    def test_config_without_it(self):
        layout = {"modules-left": [], "modules-center": [], "modules-right": []}
        self.assertEqual(barlayout.with_recording(layout, {}), layout)

    def test_the_tracked_config_defines_it(self):
        self.assertIn("custom/recording", barlayout.read_config(_paths.HYPR.parent / "waybar" / "config"))



class SavedLayouts(unittest.TestCase):
    def test_the_old_workspaces_module_becomes_the_one_that_works(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "layout.json"
            path.write_text(json.dumps({"modules-center": ["hyprland/window", "hyprland/workspaces"]}))
            with mock.patch.object(barlayout, "layout_path", return_value=path):
                layout = barlayout.read_layout(barlayout.read_config())
        self.assertEqual(layout["modules-center"], ["hyprland/window", "group/workspaces"])


if __name__ == "__main__":
    unittest.main()
