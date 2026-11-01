"""Events kept on this PC: written as iCalendar that the popup's icalendar library and the assistant both read."""

import datetime
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import localcal  # noqa: E402

DAY = datetime.date(2026, 11, 3)


class LocalCalendar(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        for patcher in (mock.patch.object(localcal, "PATH", os.path.join(tmp.name, "cal", "local.ics")),
                        mock.patch.object(localcal, "reload_popup")):
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_round_trip_with_awkward_text(self):
        title = "Dentist, then lunch; with Zoë " + "é" * 50
        localcal.add(title, DAY, localcal.parse_time("2pm"), localcal.parse_time("15:30"), "WEEKLY", notes="line 1\nline 2")
        ev, = localcal.events()
        self.assertEqual((ev["title"], ev["notes"], ev["repeat"], ev["all_day"]), (title, "line 1\nline 2", "WEEKLY", False))
        self.assertEqual((ev["start"], ev["end"]), (datetime.datetime(2026, 11, 3, 14), datetime.datetime(2026, 11, 3, 15, 30)))
        with open(localcal.PATH, "rb") as f:
            raw = f.read()
        self.assertTrue(all(len(line) <= 75 for line in raw.split(b"\r\n")))

    def test_all_day_spans_and_overnight_events(self):
        localcal.add("Holiday", DAY, end_day=DAY + datetime.timedelta(days=2))
        localcal.add("Late", DAY, localcal.parse_time("22:00"), localcal.parse_time("01:00"))
        hol, late = sorted(localcal.events(), key=lambda e: e["title"])
        self.assertEqual((hol["start"], hol["end"]), (DAY, DAY + datetime.timedelta(days=3)))
        self.assertEqual(late["end"], datetime.datetime(2026, 11, 4, 1))

    def test_remove(self):
        keep = localcal.add("Keep", DAY)
        gone = localcal.add("Gone", DAY)
        self.assertTrue(localcal.remove(gone))
        self.assertFalse(localcal.remove(gone))
        self.assertEqual([e["uid"] for e in localcal.events()], [keep])

    def test_mistakes_are_explained(self):
        for args in (("", DAY), ("x", DAY, None, None, "HOURLY"), ("x", DAY, None, None, "", "", DAY - datetime.timedelta(days=1))):
            with self.assertRaises(ValueError):
                localcal.add(*args)
        for bad in ("25:00", "noon", "9:75"):
            with self.assertRaises(ValueError):
                localcal.parse_time(bad)
        self.assertEqual(localcal.parse_time("12am"), datetime.time(0))
        self.assertEqual(localcal.parse_date("3 Nov", today=datetime.date(2026, 11, 10)), datetime.date(2027, 11, 3))
        self.assertEqual(localcal.parse_date("2026-11-03"), DAY)

    def test_icalendar_reads_the_file(self):
        try:
            import icalendar
            import recurring_ical_events
        except ImportError:
            self.skipTest("python-recurring-ical-events is not installed")
        localcal.add("Gym", DAY, localcal.parse_time("7"), None, "WEEKLY")
        with open(localcal.PATH, "rb") as f:
            cal = icalendar.Calendar.from_ical(f.read())
        found = recurring_ical_events.of(cal).between(DAY, DAY + datetime.timedelta(days=21))
        self.assertEqual(len(found), 3)


if __name__ == "__main__":
    unittest.main()
