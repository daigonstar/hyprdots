"""The install list: nothing personal is forced, and the choices do what they say."""
import os
import re
import subprocess
import tempfile
import unittest
from pathlib import Path

INSTALL = Path(__file__).resolve().parents[1]
PERSONAL = {"discord", "vesktop", "zed", "steam", "zen-browser-bin", "openrgb", "coolercontrol", "solaar", "docker", "freerdp", "winboat", "cava", "sif-git", "github-cli"}


def packages(path):
    out = []
    for line in path.read_text().splitlines():
        line = line.split("#")[0].strip()
        if line:
            out.append(line)
    return out


class Lists(unittest.TestCase):
    def test_nothing_personal_is_forced(self):
        self.assertEqual(PERSONAL & set(packages(INSTALL / "required.txt")), set())

    def test_each_personal_app_is_offered(self):
        offered = {p for f in (INSTALL / "apps").glob("*.txt") for p in packages(f)}
        self.assertEqual({p for p in PERSONAL if p != "zen-browser-bin"} - offered, set())

    def test_every_group_explains_itself(self):
        for f in (INSTALL / "apps").glob("*.txt"):
            text = f.read_text()
            self.assertRegex(text, r"(?m)^# title: \S", f.name)
            self.assertRegex(text, r"(?m)^# about: \S", f.name)
            self.assertTrue(packages(f), f.name)

    def test_nothing_in_two_places(self):
        seen = set(packages(INSTALL / "required.txt"))
        for f in (INSTALL / "apps").glob("*.txt"):
            for p in packages(f):
                self.assertNotIn(p, seen, f"{p} in {f.name}")
                seen.add(p)


class Choosing(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.home = tmp.name
        self.state = Path(self.home) / ".local/state/hyprdots/apps"

    def run_apps(self, *args, text=None, **env):
        full = {k: v for k, v in os.environ.items() if not k.startswith(("HYPR_", "XDG_STATE"))}
        # The settings code finds its folder from where it lives, not from HOME, so without this a test would change your real settings
        full.update(HOME=self.home, HYPR_SETTINGS_DIR=str(Path(self.home) / ".config/hypr"), **env)
        return subprocess.run(["bash", str(INSTALL / "apps.sh"), *args], env=full, input=text, stdin=None if text is not None else subprocess.DEVNULL,
                              capture_output=True, text=True, timeout=30)

    def lines(self, result, kind):
        return re.findall(rf"(?m)^{kind} (.+)$", result.stdout)

    def test_no_terminal_gives_only_the_defaults(self):
        got = self.run_apps("--print")
        self.assertEqual(got.returncode, 0, got.stderr)
        self.assertEqual(self.lines(got, "group"), ["store"])
        self.assertEqual(self.lines(got, "pacman"), ["firefox"])
        self.assertEqual(self.lines(got, "browser"), ["firefox firefox.desktop"])

    def test_chosen_groups_only(self):
        got = self.run_apps("--print", HYPR_APPS="gaming dev", HYPR_BROWSER="zen")
        self.assertEqual(self.lines(got, "group"), ["dev", "gaming"])
        self.assertIn("steam", self.lines(got, "pacman"))
        self.assertIn("zen-browser-bin", self.lines(got, "pacman"))
        self.assertIn("net.lutris.Lutris", self.lines(got, "flatpak"))
        self.assertNotIn("discord", self.lines(got, "pacman"))
        self.assertEqual(self.lines(got, "browser"), ["zen-browser zen.desktop"])

    def test_none_and_all(self):
        none = self.run_apps("--print", HYPR_APPS="none", HYPR_BROWSER="none")
        self.assertEqual((none.returncode, none.stdout), (0, ""))
        everything = self.run_apps("--print", HYPR_APPS="all")
        self.assertEqual(len(self.lines(everything, "group")), len(list((INSTALL / "apps").glob("*.txt"))))

    def test_a_typo_is_reported_not_fatal(self):
        got = self.run_apps("--print", HYPR_APPS="gamming chat")
        self.assertEqual(got.returncode, 0)
        self.assertIn("gamming", got.stderr)
        self.assertEqual(self.lines(got, "group"), ["chat"])

    def test_the_menu(self):
        groups = sorted(f.stem for f in (INSTALL / "apps").glob("*.txt"))
        chat, store = groups.index("chat") + 1, groups.index("store") + 1
        got = self.run_apps("--print", text=f"2\n{chat} {store}\n99 x\n\n", HYPR_APPS_MENU="1")
        self.assertEqual(got.returncode, 0, got.stderr)
        self.assertEqual(self.lines(got, "group"), ["chat"])
        self.assertIn("zen-browser-bin", self.lines(got, "pacman"))
        self.assertIn("Skipping 99", got.stderr)

    def test_the_menu_remembers_your_last_choice(self):
        self.run_apps("--print", HYPR_APPS="office")
        self.assertIn("group=office", self.state.read_text())
        got = self.run_apps("--print", text="\n\n", HYPR_APPS_MENU="1")
        self.assertEqual(self.lines(got, "group"), ["office"])

    def test_set_browser_reaches_the_keybind(self):
        hypr = Path(self.home) / ".config/hypr"
        hypr.mkdir(parents=True)
        for name in ("user_settings.toml", "autostart.lua", "keybinds.lua"):
            (hypr / name).write_text((INSTALL.parent / ".config/hypr" / name).read_text())
        got = self.run_apps("--set-browser", "firefox", "firefox.desktop")
        self.assertEqual(got.returncode, 0, got.stderr)
        self.assertIn('browser = "firefox"', (hypr / "user_settings.local.toml").read_text())
        self.assertIn('browser = "firefox"', (hypr / "user_overrides.lua").read_text())

    def test_set_keyboard_reaches_hyprland(self):
        hypr = Path(self.home) / ".config/hypr"
        hypr.mkdir(parents=True)
        for name in ("user_settings.toml", "autostart.lua", "keybinds.lua"):
            (hypr / name).write_text((INSTALL.parent / ".config/hypr" / name).read_text())
        got = self.run_apps("--set-keyboard", "de")
        self.assertEqual(got.returncode, 0, got.stderr)
        self.assertIn('kb_layout = "de"', (hypr / "user_settings.local.toml").read_text())
        self.assertIn('kb_layout = "de"', (hypr / "user_overrides.lua").read_text())

    def test_a_dry_run_saves_nothing(self):
        self.run_apps("--print", "--dry-run", HYPR_APPS="office")
        self.assertFalse(self.state.exists())


if __name__ == "__main__":
    unittest.main()
