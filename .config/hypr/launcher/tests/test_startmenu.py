"""The XP style start menu: when it is used, and what goes in it."""

import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import search  # noqa: E402
import startmenu  # noqa: E402


def app(title, exe, app_id=None, category="Other"):
    return search.Result("app", title, app_id=app_id or f"{exe}.desktop", category=category, extra={"exec": f"/usr/bin/{exe}"})


class Wanted(unittest.TestCase):
    def test_only_while_xp_style_is_on(self):
        self.assertTrue(startmenu.wanted({"override": "luna"}, ["launcher.py"]))
        self.assertFalse(startmenu.wanted({"override": "none"}, ["launcher.py"]))
        self.assertFalse(startmenu.wanted({}, ["launcher.py"]))

    def test_a_style_try_out_still_shows_that_style(self):
        self.assertFalse(startmenu.wanted({"override": "luna"}, ["launcher.py", "--style", "grid"]))


class Pinned(unittest.TestCase):
    apps = [app("Zen Browser", "zen-browser"), app("Thunar File Manager", "thunar"), app("Ghostty", "ghostty", "com.mitchellh.ghostty.desktop")]

    def test_your_apps_from_settings(self):
        got = startmenu.pinned({"browser": "zen-browser", "file_manager": "thunar", "terminal": "ghostty"}, self.apps)
        self.assertEqual([p["title"] for p in got], ["Internet", "Files", "Terminal"])
        self.assertEqual([p["subtitle"] for p in got], ["Zen Browser", "Thunar File Manager", "Ghostty"])

    def test_command_with_arguments_and_a_path(self):
        self.assertIs(startmenu.app_for_command("/usr/bin/thunar --daemon", self.apps), self.apps[1])

    def test_not_installed_shows_the_command(self):
        got = startmenu.pinned({"browser": "librewolf"}, self.apps)[0]
        self.assertIsNone(got["app"])
        self.assertEqual((got["subtitle"], got["cmd"]), ("librewolf", ["librewolf"]))

    def test_empty_command(self):
        self.assertIsNone(startmenu.app_for_command("  ", self.apps))


class Places(unittest.TestCase):
    def test_folders_follow_user_dirs(self):
        with tempfile.TemporaryDirectory() as d:
            home = Path(d)
            (home / ".config").mkdir()
            (home / ".config/user-dirs.dirs").write_text('XDG_DOCUMENTS_DIR="$HOME/Docs"\n# comment\n')
            with mock.patch.object(startmenu, "HOME", home):
                self.assertEqual(startmenu.special_dir("DOCUMENTS", "Documents"), home / "Docs")
                self.assertEqual(startmenu.special_dir("MUSIC", "Music"), home / "Music")

    def test_every_item_does_something(self):
        items = [p for p in startmenu.places() if p is not None]
        self.assertIn(None, startmenu.places())  # separators
        for p in items:
            self.assertIn(p["kind"], ("open", "run", "search", "run_prompt"))
            self.assertTrue(p["icon"])
            if p["kind"] == "run":
                self.assertTrue(p["cmd"])


class Lists(unittest.TestCase):
    def test_frequent_leaves_out_the_pinned_ones(self):
        apps = [app("A", "a"), app("B", "b"), app("C", "c")]
        usage = {"a.desktop": {"count": 9, "last": 0}, "b.desktop": {"count": 5, "last": 0}}
        with mock.patch.object(search, "frequent", return_value=apps[:2]):
            got = startmenu.frequent(apps, usage, {"a.desktop"})
        self.assertEqual([a.title for a in got], ["B"])

    def test_categories_in_the_launcher_order(self):
        apps = [app("x", "x", category="Games"), app("y", "y", category="Internet"), app("z", "z")]
        self.assertEqual(startmenu.categories(apps), ["Internet", "Games", "Other"])

    def test_up_and_down_wrap_round(self):
        self.assertEqual(startmenu.step(0, 5, -1), 4)
        self.assertEqual(startmenu.step(4, 5, 1), 0)
        self.assertEqual(startmenu.step(0, 0, 1), 0)

    def test_power_choices_are_real_commands(self):
        for _title, choices in (startmenu.LOG_OUT, startmenu.TURN_OFF):
            for _label, word, colour, _glyph in choices:
                self.assertTrue(startmenu.power(word))
                self.assertIn(colour, ("amber", "red", "green"))

    def test_the_start_button_is_told(self):
        with tempfile.TemporaryDirectory() as d, mock.patch.object(startmenu, "OPEN_MARK", Path(d) / "open"), \
                mock.patch("subprocess.Popen") as popen:
            startmenu.mark_open(True)
            self.assertTrue((Path(d) / "open").exists())
            startmenu.mark_open(False)
            self.assertFalse((Path(d) / "open").exists())
        self.assertEqual(popen.call_args.args[0], ["pkill", "-RTMIN+12", "-x", "waybar"])

    def test_the_bar_listens_on_the_same_signal(self):
        from hyprsettings import theme_override
        self.assertEqual(startmenu.BAR_SIGNAL, theme_override.START_SIGNAL)
        self.assertEqual(theme_override.bar({"override": "luna"})["custom/start"]["signal"], startmenu.BAR_SIGNAL)

    def test_css_scales(self):
        self.assertIn("font-size: 13px", startmenu.css('"Sans"', 1.0))
        self.assertIn("font-size: 26px", startmenu.css('"Sans"', 2.0))


if __name__ == "__main__":
    unittest.main()
