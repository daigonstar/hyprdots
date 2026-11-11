"""How the launcher starts apps: each in a systemd scope of its own, not inside whatever opened the launcher."""

import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import launcher  # noqa: E402
import search  # noqa: E402


class OwnScope(unittest.TestCase):
    def test_wrapped_in_systemd_run(self):
        with mock.patch("shutil.which", return_value="/usr/bin/systemd-run"):
            got = launcher.own_scope(["gtk-launch", "zen.desktop"])
        self.assertEqual(got[:3], ["systemd-run", "--user", "--scope"])
        self.assertEqual(got[got.index("--") + 1:], ["gtk-launch", "zen.desktop"])

    def test_left_alone_without_systemd(self):
        with mock.patch("shutil.which", return_value=None):
            self.assertEqual(launcher.own_scope(["thunar"]), ["thunar"])

    def test_apps_from_the_launcher_get_one(self):
        with mock.patch("shutil.which", return_value="/usr/bin/systemd-run"), mock.patch("subprocess.Popen") as popen, \
                mock.patch.object(search, "record_use"):
            launcher.run(search.Result("app", "Zen", app_id="zen.desktop"), {"terminal": "ghostty"})
        cmd = popen.call_args.args[0]
        self.assertEqual((cmd[0], cmd[-2:]), ("systemd-run", ["gtk-launch", "zen.desktop"]))


if __name__ == "__main__":
    unittest.main()
