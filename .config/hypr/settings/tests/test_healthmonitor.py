import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import _paths  # noqa: F401
from hyprsettings import healthmonitor


class HealthMonitor(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dots, self.user = Path(tmp.name) / "dots", Path(tmp.name) / "user"
        self.dots.mkdir()
        for unit in healthmonitor.UNITS:
            (self.dots / unit).write_text("[Unit]\n")
        self.calls = []

        def fake(args, **_kw):
            self.calls.append(args[2:])
            return subprocess.CompletedProcess(args, 0, "", "")
        patcher = mock.patch("subprocess.run", side_effect=fake)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_on_links_the_units_then_starts_the_timer(self):
        self.assertEqual(healthmonitor.turn(True, self.dots, self.user), (True, "Health monitor turned on."))
        for unit in healthmonitor.UNITS:
            self.assertEqual((self.user / unit).resolve(), (self.dots / unit).resolve())
        self.assertEqual(self.calls, [["daemon-reload"], ["enable", "--now", "agent-monitor.timer"]])

    def test_off_stops_it_and_reads_as_off(self):
        healthmonitor.turn(True, self.dots, self.user)
        self.calls.clear()
        self.assertEqual(healthmonitor.turn(False), (True, "Health monitor turned off."))
        self.assertEqual(self.calls, [["disable", "--now", "agent-monitor.timer"], ["reset-failed", "agent-monitor.timer"]])

    def test_missing_units_say_so(self):
        (self.dots / "agent-monitor.timer").unlink()
        ok, message = healthmonitor.turn(True, self.dots, self.user)
        self.assertFalse(ok)
        self.assertIn("missing", message)


if __name__ == "__main__":
    unittest.main()
