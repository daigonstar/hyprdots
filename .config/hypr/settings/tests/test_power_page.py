import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import _paths
from hyprsettings import power


class PowerPage(unittest.TestCase):
    def test_ram_notes(self):
        self.assertEqual(power.ram_note({}), "")
        self.assertIn("within its rating", power.ram_note({"rated": 4800, "running": 4800, "above_rating": False}))
        self.assertIn("put it back in the BIOS", power.ram_note({"rated": 4800, "running": 5300, "above_rating": True}))

    def test_change_runs_the_installed_service_as_root(self):
        done = mock.Mock(returncode=0, stdout="Saved.\n", stderr="")
        with mock.patch("shutil.which", return_value="/usr/bin/pkexec"), mock.patch("subprocess.run", return_value=done) as run:
            self.assertEqual(power.change(mode="cool", guard=False, cpu_limit=88), (True, "Saved."))
        self.assertEqual(run.call_args[0][0], ["pkexec", "/usr/bin/python3", "/usr/local/lib/hyprdots/powerd.py", "set",
                                               "mode=cool", "guard=off", "cpu_limit=88"])

    def test_a_cancelled_password_says_so(self):
        with mock.patch("shutil.which", return_value="/usr/bin/pkexec"), mock.patch("subprocess.run", return_value=mock.Mock(returncode=126, stdout="", stderr="")):
            self.assertEqual(power.change(mode="cool")[0], False)

    def test_status_is_none_without_the_service(self):
        with mock.patch.object(power, "STATUS", Path(tempfile.gettempdir()) / "no-such-status.json"):
            self.assertIsNone(power.status())


if __name__ == "__main__":
    unittest.main()
