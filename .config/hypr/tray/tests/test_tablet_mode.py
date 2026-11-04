import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import tablet_mode  # noqa: E402


class Keyboards(unittest.TestCase):
    def test_a_type_cover_is_a_keyboard(self):
        self.assertTrue(tablet_mode.has_keyboard({"keyboards": [{"name": "microsoft-surface-type-cover-keyboard"}]}))

    def test_what_only_reports_as_a_keyboard_does_not_count(self):
        self.assertFalse(tablet_mode.has_keyboard({"keyboards": [
            {"name": "surface-pro-3/4-buttons"}, {"name": "video-bus"},
            {"name": "microsoft-corp.-microsoft-docking-station-audio-device-consumer-control"},
            {"name": "microsoft-corp.-microsoft-docking-station-audio-device"}]}))

    def test_nothing_at_all(self):
        self.assertFalse(tablet_mode.has_keyboard({}))


class Asking(unittest.TestCase):
    def test_keeps_asking_for_a_while_after_a_change(self):
        # The kernel lists a new keyboard before Hyprland has it, so the first answer can be the old one
        watch = tablet_mode.InputWatch()
        self.assertEqual([watch.should_ask("a") for _ in range(5)], [True, True, True, False, False])
        self.assertEqual([watch.should_ask("b") for _ in range(5)], [True, True, True, False, False])


class Button(unittest.TestCase):
    def test_sits_above_the_keyboard_while_it_is_up(self):
        layers = {"eDP-1": {"levels": {"0": [{"namespace": "awww-daemon", "h": 1152}], "2": [{"namespace": "osk", "h": 240}]}}}
        self.assertEqual(tablet_mode.button_margin(layers), 240 + tablet_mode.BUTTON_MARGIN)

    def test_clears_a_bar_at_the_bottom_too(self):
        layers = {"eDP-1": {"levels": {"2": [{"namespace": "osk", "h": 240}, {"namespace": "waybar", "y": 1088, "h": 64}]}}}
        self.assertEqual(tablet_mode.button_margin(layers), 240 + 64 + tablet_mode.BUTTON_MARGIN)

    def test_a_hidden_bar_reserves_nothing_beyond_the_keyboard(self):
        with_keyboard = {"eDP-1": {"levels": {"2": [{"namespace": "osk", "h": 240}, {"namespace": "waybar", "h": 72}]}}}
        without = {"eDP-1": {"levels": {"2": [{"namespace": "waybar", "h": 72}]}}}
        self.assertTrue(tablet_mode.bar_is_shown({"reserved": [0, 0, 0, 312]}, with_keyboard))
        self.assertFalse(tablet_mode.bar_is_shown({"reserved": [0, 0, 0, 240]}, with_keyboard))
        self.assertTrue(tablet_mode.bar_is_shown({"reserved": [0, 72, 0, 0]}, without))
        self.assertFalse(tablet_mode.bar_is_shown({"reserved": [0, 0, 0, 0]}, without))

    def test_in_the_corner_when_it_is_not(self):
        self.assertEqual(tablet_mode.button_margin({"eDP-1": {"levels": {"2": [{"namespace": "waybar", "h": 44}]}}}), tablet_mode.BUTTON_MARGIN)


class Sensor(unittest.TestCase):
    def test_reads_both_of_its_lines(self):
        self.assertEqual(tablet_mode.orientation_in("    Accelerometer orientation changed: left-up\n"), "left-up")
        self.assertEqual(tablet_mode.orientation_in("=== Has accelerometer (orientation: normal, tilt: flat)\n"), "normal")

    def test_undefined_is_not_applied(self):
        self.assertIsNone(tablet_mode.orientation_in("=== Has accelerometer (orientation: undefined)\n"))
        self.assertIsNone(tablet_mode.orientation_in("    Waiting for iio-sensor-proxy to appear\n"))


class Screen(unittest.TestCase):
    def test_the_built_in_screen_not_an_external_one(self):
        self.assertEqual(tablet_mode.built_in_screen([{"name": "DP-1"}, {"name": "eDP-1"}])["name"], "eDP-1")
        self.assertIsNone(tablet_mode.built_in_screen([{"name": "DP-1"}]))

    def test_keeps_its_other_settings_when_rotating(self):
        m = {"name": "eDP-1", "width": 2160, "height": 1440, "refreshRate": 59.955, "x": 0, "y": 0, "scale": 1.25}
        self.assertEqual(tablet_mode.monitor_lua(m, 1),
                         'hl.monitor({ output = "eDP-1", mode = "2160x1440@59.95", position = "0x0", scale = 1.25, transform = 1 })')


class Fade(unittest.TestCase):
    def test_nothing_shows_when_the_screen_is_already_that_way(self):
        fade = tablet_mode.ScreenFade()
        with mock.patch.object(tablet_mode, "screen_to_rotate", return_value=None):
            fade.rotate(0)
        self.assertFalse(fade.get_visible())
        self.assertFalse(fade.turning)

    def test_one_turn_at_a_time(self):
        fade = tablet_mode.ScreenFade()
        fade.turning = True
        with mock.patch.object(tablet_mode, "screen_to_rotate") as asked:
            fade.rotate(1)
        asked.assert_not_called()


class Modes(unittest.TestCase):
    def setUp(self):
        self.mode = tablet_mode.TabletMode()
        self.mode.on_screen_keyboard = mock.Mock()
        patcher = mock.patch.object(tablet_mode.touch_mode, "apply")
        self.bar = patcher.start()
        self.addCleanup(patcher.stop)
        self.rotate = self.mode.turn_to = mock.Mock()

    def test_with_a_keyboard_the_screen_ignores_the_sensor(self):
        self.mode.set_tablet(False)
        self.mode.orientation = "left-up"
        self.mode.follow_sensor()
        self.rotate.assert_called_with(0)
        self.mode.on_screen_keyboard.assert_called_once_with(False)

    def test_without_one_it_follows(self):
        self.mode.set_tablet(True)
        self.mode.orientation = "left-up"
        self.mode.follow_sensor()
        self.rotate.assert_called_with(1)
        self.mode.on_screen_keyboard.assert_called_once_with(True)

    def test_rotation_lock_holds_it(self):
        with mock.patch.object(tablet_mode, "ROTATION_LOCK", mock.Mock(exists=lambda: True)):
            self.mode.set_tablet(True)
            self.mode.orientation = "left-up"
            self.mode.follow_sensor()
        self.rotate.assert_not_called()

    def test_touch_mode_follows_tablet_mode(self):
        self.mode.set_tablet(True)
        self.bar.assert_called_with(True)
        self.mode.set_tablet(False)
        self.bar.assert_called_with(False)

    def test_no_change_does_nothing_twice(self):
        self.mode.set_tablet(True)
        self.mode.set_tablet(True)
        self.mode.on_screen_keyboard.assert_called_once_with(True)


if __name__ == "__main__":
    unittest.main()
