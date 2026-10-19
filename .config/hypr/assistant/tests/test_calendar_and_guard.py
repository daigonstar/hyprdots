"""Tests for the date parser, the iCalendar expander, the loop guard and context trimming."""

import atexit
import datetime as dt
import os
import shutil
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _sandbox  # noqa: E402,F401  (must come before hypr_agent)
import hypr_agent as a  # noqa: E402

_OLD_TZ = os.environ.get("TZ")


def setUpModule():
    os.environ["TZ"] = "Europe/London"  # makes local-time results independent of the machine
    time.tzset()


def tearDownModule():
    if _OLD_TZ is None:
        os.environ.pop("TZ", None)
    else:
        os.environ["TZ"] = _OLD_TZ
    time.tzset()


D = dt.date


class ParseWhen(unittest.TestCase):
    TODAY = D(2026, 10, 14)  # a Wednesday

    def when(self, text, today=None):
        return a._parse_when(text, today or self.TODAY)

    def test_single_days(self):
        self.assertEqual(self.when("today"), (D(2026, 10, 14), D(2026, 10, 15)))
        self.assertEqual(self.when(""), (D(2026, 10, 14), D(2026, 10, 15)))
        self.assertEqual(self.when("Tomorrow?"), (D(2026, 10, 15), D(2026, 10, 16)))
        self.assertEqual(self.when("yesterday"), (D(2026, 10, 13), D(2026, 10, 14)))
        self.assertEqual(self.when("day after tomorrow"), (D(2026, 10, 16), D(2026, 10, 17)))

    def test_weeks_start_on_monday(self):
        self.assertEqual(self.when("this week"), (D(2026, 10, 12), D(2026, 10, 19)))
        self.assertEqual(self.when("next week"), (D(2026, 10, 19), D(2026, 10, 26)))
        self.assertEqual(self.when("last week"), (D(2026, 10, 5), D(2026, 10, 12)))

    def test_weekend(self):
        self.assertEqual(self.when("this weekend"), (D(2026, 10, 17), D(2026, 10, 19)))
        self.assertEqual(self.when("next weekend"), (D(2026, 10, 24), D(2026, 10, 26)))
        self.assertEqual(self.when("weekend", D(2026, 10, 18)), (D(2026, 10, 17), D(2026, 10, 19)))  # on the Sunday

    def test_months_and_rollover(self):
        self.assertEqual(self.when("this month"), (D(2026, 10, 1), D(2026, 11, 1)))
        self.assertEqual(self.when("next month", D(2026, 12, 15)), (D(2027, 1, 1), D(2027, 2, 1)))
        self.assertEqual(self.when("december"), (D(2026, 12, 1), D(2027, 1, 1)))
        self.assertEqual(self.when("january"), (D(2027, 1, 1), D(2027, 2, 1)))  # already past this year
        self.assertEqual(self.when("march 2027"), (D(2027, 3, 1), D(2027, 4, 1)))

    def test_relative_amounts(self):
        self.assertEqual(self.when("in 3 days"), (D(2026, 10, 17), D(2026, 10, 18)))
        self.assertEqual(self.when("in 2 weeks"), (D(2026, 10, 28), D(2026, 10, 29)))
        self.assertEqual(self.when("in 1 month"), (D(2026, 11, 14), D(2026, 11, 15)))
        self.assertEqual(self.when("in 1 month", D(2026, 1, 31)), (D(2026, 2, 28), D(2026, 3, 1)))
        self.assertEqual(self.when("next 7 days"), (D(2026, 10, 14), D(2026, 10, 21)))

    def test_weekdays(self):
        self.assertEqual(self.when("friday"), (D(2026, 10, 16), D(2026, 10, 17)))
        self.assertEqual(self.when("wednesday"), (D(2026, 10, 14), D(2026, 10, 15)))  # today counts
        self.assertEqual(self.when("monday"), (D(2026, 10, 19), D(2026, 10, 20)))
        self.assertEqual(self.when("next friday"), (D(2026, 10, 23), D(2026, 10, 24)))
        self.assertEqual(self.when("on this friday"), (D(2026, 10, 16), D(2026, 10, 17)))

    def test_dates_and_ranges(self):
        self.assertEqual(self.when("2026-10-20"), (D(2026, 10, 20), D(2026, 10, 21)))
        self.assertEqual(self.when("20 Oct"), (D(2026, 10, 20), D(2026, 10, 21)))
        self.assertEqual(self.when("25th December 2026"), (D(2026, 12, 25), D(2026, 12, 26)))
        self.assertEqual(self.when("5 Jan"), (D(2027, 1, 5), D(2027, 1, 6)))  # said in October: next January
        self.assertEqual(self.when("1 Oct"), (D(2026, 10, 1), D(2026, 10, 2)))  # recent past stays this year
        self.assertEqual(self.when("2026-10-20 to 2026-10-25"), (D(2026, 10, 20), D(2026, 10, 26)))
        self.assertEqual(self.when("friday to sunday"), (D(2026, 10, 16), D(2026, 10, 19)))

    def test_nonsense_raises_with_help(self):
        for text in ("blah", "2026-10-25 to 2026-10-20", "32 Oct", "in many days"):
            with self.assertRaises(ValueError, msg=text) as ctx:
                self.when(text)
        self.assertIn("tomorrow", str(ctx.exception))

    def test_helpers(self):
        self.assertEqual(a._add_months(D(2026, 1, 31), 1), D(2026, 2, 28))
        self.assertEqual(a._add_months(D(2028, 1, 31), 1), D(2028, 2, 29))
        self.assertEqual(a._add_months(D(2026, 11, 30), 3), D(2027, 2, 28))
        self.assertEqual(a._add_months(D(2026, 1, 15), -2), D(2025, 11, 15))
        today = self.TODAY
        self.assertEqual([a._relative_day(today + dt.timedelta(days=n), today) for n in (0, 1, -1, 5, -3)],
                         ["today", "tomorrow", "yesterday", "in 5 days", "3 days ago"])

    def test_date_info_reports_weekday_and_distance(self):
        fixed = dt.datetime(2026, 10, 14, 9, 30, tzinfo=dt.timezone.utc)
        with mock.patch.object(a.datetime, "datetime", wraps=dt.datetime) as fake:
            fake.now.return_value = fixed
            out = a.tool_date_info("2026-12-25")
        self.assertIn("Friday 25 December 2026", out)
        self.assertIn("in 72 days", out)
        self.assertIn("date_info failed", a.tool_date_info("blah"))


def ics(*events):
    return "BEGIN:VCALENDAR\r\nVERSION:2.0\r\n" + "".join(f"BEGIN:VEVENT\r\n{e}END:VEVENT\r\n" for e in events) + "END:VCALENDAR\r\n"


def local(y, m, d, hh=0, mm=0):
    return dt.datetime(y, m, d, hh, mm).astimezone()


def instances(text, lo, hi, source="t"):
    notes = {}
    events = a._parse_ics(text, source, notes)
    found = []
    for ev in events:
        found += a._event_instances(ev, lo, hi, set(), notes)
    return sorted(found), notes


class IcsParsing(unittest.TestCase):
    def test_unfold_and_split(self):
        self.assertEqual(a._unfold("SUMMARY:Hello\r\n  world\r\nX:1"), ["SUMMARY:Hello world", "X:1"])
        self.assertEqual(a._split_prop('DTSTART;TZID="Europe/London":20261013T093000'),
                         ("DTSTART", {"TZID": "Europe/London"}, "20261013T093000"))
        self.assertEqual(a._split_prop('ATTENDEE;CN="A: B":mailto:x@y')[2], "mailto:x@y")
        self.assertIsNone(a._split_prop("no separator"))
        self.assertEqual(a._ics_text(r"a\, b\; c\nd"), "a, b; c d")

    def test_durations(self):
        for text, expected in (("PT1H30M", dt.timedelta(hours=1, minutes=30)), ("P1D", dt.timedelta(days=1)),
                               ("P2W", dt.timedelta(weeks=2)), ("-PT15M", -dt.timedelta(minutes=15))):
            self.assertEqual(a._ics_duration(text), expected)
        with self.assertRaises(ValueError):
            a._ics_duration("soon")

    def test_timed_event_with_zone_and_utc(self):
        text = ics("UID:1\r\nSUMMARY:Dentist\r\nDTSTART;TZID=Europe/London:20261020T093000\r\nDTEND;TZID=Europe/London:20261020T103000\r\n",
                   "UID:2\r\nSUMMARY:Call\r\nDTSTART:20260701T120000Z\r\nDURATION:PT45M\r\n")
        found, _ = instances(text, local(2026, 6, 30), local(2026, 10, 30))
        self.assertEqual(found[0], (local(2026, 7, 1, 13, 0), local(2026, 7, 1, 13, 45)))  # 12:00Z is 13:00 BST
        self.assertEqual(found[1], (local(2026, 10, 20, 9, 30), local(2026, 10, 20, 10, 30)))

    def test_windows_zone_names_and_unknown_zones(self):
        text = ics("UID:1\r\nSUMMARY:A\r\nDTSTART;TZID=GMT Standard Time:20261020T090000\r\n",
                   "UID:2\r\nSUMMARY:B\r\nDTSTART;TZID=Mars/Olympus:20261020T090000\r\n")
        found, notes = instances(text, local(2026, 10, 20), local(2026, 10, 21))
        self.assertEqual(len(found), 2)
        self.assertTrue(any("not recognised" in n for n in notes))

    def test_all_day_single_and_multi(self):
        text = ics("UID:1\r\nSUMMARY:Holiday\r\nDTSTART;VALUE=DATE:20261021\r\n",
                   "UID:2\r\nSUMMARY:Trip\r\nDTSTART;VALUE=DATE:20261021\r\nDTEND;VALUE=DATE:20261024\r\n")
        day = lambda n: (local(2026, 10, n), local(2026, 10, n + 1))
        self.assertEqual(len(instances(text, *day(21))[0]), 2)
        self.assertEqual(len(instances(text, *day(23))[0]), 1)   # only the trip is still going
        self.assertEqual(len(instances(text, *day(24))[0]), 0)   # DTEND is exclusive
        self.assertEqual(len(instances(text, *day(20))[0]), 0)

    def test_alarms_and_broken_events_do_not_break_parsing(self):
        text = ics("UID:1\r\nSUMMARY:Ok\r\nDTSTART:20261020T090000Z\r\nBEGIN:VALARM\r\nTRIGGER:-PT10M\r\nEND:VALARM\r\n",
                   "UID:2\r\nSUMMARY:Bad\r\nDTSTART:garbage\r\n", "UID:3\r\nSUMMARY:NoStart\r\n")
        notes = {}
        events = a._parse_ics(text, "t", notes)
        self.assertEqual([e["summary"] for e in events], ["Ok"])
        self.assertTrue(notes)


class Recurrence(unittest.TestCase):
    def occurrences(self, rule, start="DTSTART;TZID=Europe/London:20261005T090000", lo=(2026, 10, 1), hi=(2026, 12, 31), extra=""):
        text = ics(f"UID:r\r\nSUMMARY:R\r\n{start}\r\nDTEND{start[7:]}\r\nRRULE:{rule}\r\n{extra}".replace(
            f"DTEND{start[7:]}", "DURATION:PT1H"))
        found, notes = instances(text, local(*lo), local(*hi))
        return [s for s, _ in found], notes

    def test_weekly_with_count_is_counted_from_the_start(self):
        days = self.occurrences("FREQ=WEEKLY;BYDAY=MO,WE;COUNT=4")[0]
        self.assertEqual(days, [local(2026, 10, d, 9) for d in (5, 7, 12, 14)])
        later = self.occurrences("FREQ=WEEKLY;BYDAY=MO,WE;COUNT=4", lo=(2026, 10, 12))[0]
        self.assertEqual(later, [local(2026, 10, 12, 9), local(2026, 10, 14, 9)])

    def test_daily_interval_until(self):
        days = self.occurrences("FREQ=DAILY;INTERVAL=2;UNTIL=20261011T235959Z", hi=(2026, 12, 1))[0]
        self.assertEqual([d.day for d in days], [5, 7, 9, 11])

    def test_monthly_second_tuesday_and_last_day(self):
        tuesdays = self.occurrences("FREQ=MONTHLY;BYDAY=2TU", start="DTSTART;TZID=Europe/London:20261013T090000",
                                    lo=(2026, 10, 1), hi=(2027, 1, 1))[0]
        self.assertEqual([(d.month, d.day) for d in tuesdays], [(10, 13), (11, 10), (12, 8)])
        last = self.occurrences("FREQ=MONTHLY;BYMONTHDAY=-1", start="DTSTART;TZID=Europe/London:20260131T090000",
                                lo=(2026, 1, 1), hi=(2026, 5, 1))[0]
        self.assertEqual([(d.month, d.day) for d in last], [(1, 31), (2, 28), (3, 31), (4, 30)])

    def test_yearly(self):
        text = ics("UID:b\r\nSUMMARY:Birthday\r\nDTSTART;VALUE=DATE:20200315\r\nRRULE:FREQ=YEARLY\r\n")
        found, _ = instances(text, local(2026, 3, 15), local(2026, 3, 16))
        self.assertEqual(len(found), 1)
        self.assertEqual(len(instances(text, local(2026, 3, 16), local(2026, 3, 17))[0]), 0)

    def test_exdate_removes_one_occurrence(self):
        days = self.occurrences("FREQ=WEEKLY;COUNT=3", extra="EXDATE;TZID=Europe/London:20261012T090000\r\n")[0]
        self.assertEqual([d.day for d in days], [5, 19])

    def test_dst_difference_between_zones(self):
        # 09:00 in New York, weekly. The UK clocks change on 25 Oct, the US ones on 1 Nov.
        days = self.occurrences("FREQ=WEEKLY;COUNT=3", start="DTSTART;TZID=America/New_York:20261018T090000",
                               lo=(2026, 10, 17), hi=(2026, 11, 10))[0]
        self.assertEqual([(d.month, d.day, d.hour) for d in days], [(10, 18, 14), (10, 25, 13), (11, 1, 14)])

    def test_unsupported_rule_shows_first_date_and_says_so(self):
        days, notes = self.occurrences("FREQ=MONTHLY;BYDAY=MO;BYSETPOS=-1")
        self.assertEqual(len(days), 1)
        self.assertTrue(any("cannot expand" in n for n in notes))

    def test_rule_parser_rejects_what_it_cannot_do(self):
        self.assertIsNone(a._parse_rrule("FREQ=SECONDLY"))
        self.assertIsNone(a._parse_rrule("FREQ=WEEKLY;BYDAY=1MO"))
        self.assertIsNone(a._parse_rrule("FREQ=MONTHLY;BYDAY=XX"))
        self.assertEqual(a._parse_rrule("FREQ=WEEKLY;INTERVAL=0")["interval"], 1)


class CalendarTool(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp(prefix="cal-"))
        self.addCleanup(shutil.rmtree, self.dir, True)
        a._ICS_CACHE.clear()

    def write(self, name, text):
        (self.dir / name).write_text(text)

    def source(self, name="Home"):
        return [{"name": name, "kind": "path", "value": str(self.dir)}]

    def test_override_cancel_and_cross_calendar_dedupe(self):
        base = "UID:m\r\nSUMMARY:Standup\r\nDTSTART;TZID=Europe/London:20261005T090000\r\nDURATION:PT30M\r\nRRULE:FREQ=WEEKLY;COUNT=3\r\n"
        moved = ("UID:m\r\nSUMMARY:Standup (moved)\r\nRECURRENCE-ID;TZID=Europe/London:20261012T090000\r\n"
                 "DTSTART;TZID=Europe/London:20261012T140000\r\nDURATION:PT30M\r\n")
        cancelled = "UID:c\r\nSUMMARY:Nope\r\nSTATUS:CANCELLED\r\nDTSTART:20261014T100000Z\r\n"
        self.write("a.ics", ics(base, moved, cancelled))
        found, reports, _ = a._collect(self.source(), local(2026, 10, 1), local(2026, 11, 1))
        self.assertEqual([(o["summary"], o["start"].day, o["start"].hour) for o in found],
                         [("Standup", 5, 9), ("Standup (moved)", 12, 14), ("Standup", 19, 9)])
        self.assertTrue(reports[0]["ok"])
        # the same event in a second calendar is listed once, naming both
        other = self.dir / "b"
        other.mkdir()
        (other / "b.ics").write_text(ics("UID:z\r\nSUMMARY:Standup\r\nDTSTART;TZID=Europe/London:20261005T090000\r\nDURATION:PT30M\r\n"))
        found, _, _ = a._collect(self.source("Home") + [{"name": "Work", "kind": "path", "value": str(other)}],
                                 local(2026, 10, 5), local(2026, 10, 6))
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0]["source"], "Home, Work")

    def test_bad_source_is_reported_not_fatal(self):
        self.write("a.ics", ics("UID:1\r\nSUMMARY:Ok\r\nDTSTART:20261020T090000Z\r\n"))
        sources = self.source() + [{"name": "Gone", "kind": "path", "value": str(self.dir / "missing")}]
        found, reports, _ = a._collect(sources, local(2026, 10, 20), local(2026, 10, 21))
        self.assertEqual(len(found), 1)
        self.assertEqual([(r["name"], r["ok"]) for r in reports], [("Home", True), ("Gone", False)])

    def test_tool_end_to_end(self):
        tomorrow = dt.date.today() + dt.timedelta(days=1)
        stamp = tomorrow.strftime("%Y%m%d")
        self.write("a.ics", ics(f"UID:1\r\nSUMMARY:Dentist\r\nLOCATION:High St\\, Leeds\r\nDTSTART;TZID=Europe/London:{stamp}T093000\r\n"
                                f"DTEND;TZID=Europe/London:{stamp}T103000\r\n",
                                f"UID:2\r\nSUMMARY:Birthday\r\nDTSTART;VALUE=DATE:{stamp}\r\n"))
        with mock.patch.object(a, "_calendar_sources", return_value=self.source()):
            out = a.tool_calendar_events("tomorrow")
            self.assertIn("09:30-10:30  Dentist", out)
            self.assertIn("at High St, Leeds", out)
            self.assertIn("all day  Birthday", out)
            self.assertIn("Sources read: Home", out)
            only = a.tool_calendar_events('{"when": "next 7 days", "query": "dentist"}')
            self.assertIn("Dentist", only)
            self.assertNotIn("Birthday", only)
            self.assertIn("No matching events", a.tool_calendar_events('{"query": "zzz"}'))
            self.assertIn("calendar_events failed", a.tool_calendar_events("blah"))
            self.assertIn("longer than", a.tool_calendar_events("2026-01-01 to 2027-12-31"))

    def test_no_sources_gives_setup_help_and_does_not_invent(self):
        with mock.patch.object(a, "_calendar_sources", return_value=[]):
            out = a.tool_calendar_events("today")
        self.assertIn("no calendar is connected", out)
        self.assertIn("Do not guess", out)

    def test_error_text_never_contains_the_feed_url(self):
        secret = "https://calendar.example.com/private-abc123/basic.ics"
        from urllib.error import URLError
        self.assertNotIn("abc123", a._short_error(URLError(f"cannot reach {secret}")) + a._short_error(RuntimeError(secret)))


class LoopGuardTests(unittest.TestCase):
    def setUp(self):
        a.MUTATED[0] = False
        self.g = a.LoopGuard()

    def run_call(self, name, args, observation):
        blocked = self.g.before(name, args)
        return blocked if blocked is not None else self.g.after(name, args, observation)

    def test_duplicate_calls_are_blocked_and_then_halt(self):
        self.run_call("run_command", "df -h", "Filesystem...")
        first = self.run_call("run_command", "df  -H".replace("H", "h"), "x")  # whitespace and case are normalised
        self.assertTrue(first.startswith("DUPLICATE CALL"))
        self.assertFalse(self.g.halted)
        self.run_call("run_command", "df -h", "x")
        self.assertTrue(self.g.halted)

    def test_a_change_clears_the_duplicate_memory(self):
        self.run_call("run_command", "systemctl status x", "inactive")
        a.MUTATED[0] = True
        self.assertIsNone(self.g.before("run_command", "systemctl status x"))

    def test_tool_caps(self):
        for i in range(a.TOOL_CAPS["web_search"]):
            self.run_call("web_search", f"q{i}", f"result {i}")
        self.assertTrue(self.g.before("web_search", "q99").startswith("BUDGET REACHED"))
        self.assertFalse(self.g.halted)
        self.g.before("web_search", "q10")
        self.g.before("web_search", "q11")
        self.assertTrue(self.g.halted)

    def test_overall_call_budget(self):
        for i in range(a.MAX_TOTAL_CALLS):
            self.g.before("system_info", str(i))
        self.assertTrue(self.g.before("system_info", "one more").startswith("STOP"))
        self.assertTrue(self.g.halted)

    def test_failures_halt_and_misses_nudge(self):
        for i in range(a.LoopGuard.MAX_FAIL_STREAK):
            self.run_call("run_command", f"bad {i}", f"boom {i}\n[exit code 1]")
        self.assertIn("all failed", self.g.reason)
        g2 = a.LoopGuard()
        g2.after("run_command", "ls a", "ls: No such file or directory")
        nudged = g2.after("run_command", "ls b", "ls: No such file or directory")
        self.assertIn("Make the most likely assumption", nudged)

    def test_declines_are_final(self):
        out = self.g.after("run_command", "rm x", "Command was not run (declined)")
        self.assertIn("Do not try to do the same thing another way", out)
        self.g.after("write_file", "y", "Not written (declined)")
        self.assertTrue(self.g.halted)
        self.assertIn("2 action(s) were declined", self.g.footer("ok"))

    def test_stale_results_are_noticed(self):
        page = "same long page " * 30
        for i in range(a.LoopGuard.MAX_STALE_STREAK + 2):
            self.run_call("web_fetch", f"https://x.example/{i}", page)
        self.assertIn("already seen", self.g.reason)

    def test_footer_flags_invented_links_only(self):
        self.g.note_text("Source: https://wiki.hypr.land/Configuring/ and docs at example.org/page")
        self.g.after("web_search", "q", "URL: https://seen.example/a\ntitle")
        answer = ("See https://wiki.hypr.land/Configuring/ and https://seen.example/a, but not https://made-up.example/x "
                  "or the invented deeper page https://wiki.hypr.land/Configuring/Secret-Page.")
        flagged = self.g.footer(answer).split("made them up: ")[1].split("\n")[0]
        self.assertIn("made-up.example/x", flagged)
        self.assertIn("Secret-Page", flagged)          # a deeper path nobody saw is not verified by its parent
        self.assertNotIn("seen.example", flagged)
        self.assertNotIn("Configuring/,", flagged + ",")
        self.assertIn("search results and snippets only", self.g.footer(answer))

    def test_footer_reports_pages_opened(self):
        self.g.after("web_fetch", "u", a.WEB_NOTICE + "URL: https://opened.example/page\ntext")
        self.assertIn("Pages opened: opened.example/page", self.g.footer("done"))
        self.assertEqual(a.LoopGuard().footer("plain answer"), "")

    def test_timeout(self):
        self.g.started -= a.REQUEST_TIMEOUT + 1
        self.assertTrue(self.g.out_of_time())
        self.assertIn("more than", self.g.reason)


class FitContext(unittest.TestCase):
    def messages(self, tool_chars):
        return [
            {"role": "system", "content": "SYSTEM RULES"},
            {"role": "user", "content": "old question"},
            {"role": "assistant", "content": "", "thinking": "long reasoning " * 500, "tool_calls": [{"function": {"name": "x"}}]},
            {"role": "tool", "content": "old output " * (tool_chars // 11), "tool_name": "x"},
            {"role": "assistant", "content": "old answer"},
            {"role": "user", "content": "current question"},
            {"role": "assistant", "content": "", "thinking": "recent thought", "tool_calls": [{"function": {"name": "y"}}]},
            {"role": "tool", "content": "recent output", "tool_name": "y"},
        ]

    def test_small_conversations_are_untouched(self):
        msgs = self.messages(100)
        self.assertIs(a._fit_context(msgs, "current question"), msgs)

    def test_large_ones_shrink_but_keep_the_system_prompt_and_the_request(self):
        with mock.patch.object(a, "NUM_CTX", 1500):
            msgs = self.messages(30000)
            out = a._fit_context(msgs, "current question")
        self.assertLess(sum(a._msg_size(m) for m in out), sum(a._msg_size(m) for m in msgs))
        self.assertEqual(out[0]["content"], "SYSTEM RULES")
        self.assertEqual(out[-1]["content"], "recent output")
        self.assertIn("current question", [m["content"] for m in out])
        self.assertNotEqual(out[1]["role"], "tool")
        self.assertNotIn("thinking", out[2])  # old reasoning goes first
        self.assertEqual(msgs[2]["thinking"][:14], "long reasoning")  # the input list is not modified


class SessionTranscript(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="hypr-agent-run-")
        self.addCleanup(shutil.rmtree, self.dir, ignore_errors=True)
        self.addCleanup(a.end_session)
        env = mock.patch.dict(os.environ, {"XDG_RUNTIME_DIR": self.dir})
        env.start()
        self.addCleanup(env.stop)
        for target in ("atexit.register", "signal.signal"):  # keep the test process's own handlers
            patcher = mock.patch(target)
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_file_lives_for_the_session_only(self):
        stale = os.path.join(self.dir, "hypr_agent_session_999999999.jsonl")
        Path(stale).write_text("{}\n")
        a.start_session()
        path = a.SESSION_FILE[0]
        self.assertTrue(os.path.exists(path))
        self.assertEqual(os.stat(path).st_mode & 0o777, 0o600)
        self.assertFalse(os.path.exists(stale))  # left behind by a session that no longer runs
        a.end_session()
        self.assertFalse(os.path.exists(path))
        self.assertEqual(a.session_transcript(), "")

    def test_turns_reach_the_system_prompt(self):
        a.start_session()
        a.log_turn("which browser do I use?", "Firefox, from your profile.")
        a.log_turn("open it", "", "cancelled by the user")
        context = a.build_context()
        self.assertIn("CONVERSATION SO FAR THIS SESSION", context)
        self.assertIn("1. [", context)
        self.assertIn("User: which browser do I use?", context)
        self.assertIn("You: Firefox, from your profile.", context)
        self.assertIn("(cancelled by the user, no full answer was given)", context)

    def test_long_sessions_keep_the_newest_turns(self):
        a.start_session()
        for n in range(40):
            a.log_turn(f"question {n}", "x" * 2000)
        text = a.session_transcript()
        self.assertLessEqual(len(text), a.SESSION_LOG_CHARS + 100)
        self.assertIn("User: question 39", text)
        self.assertNotIn("User: question 0\n", text)
        self.assertTrue(text.startswith("("))  # says how many earlier turns were left out


def _reply(text):
    return {"message": {"role": "assistant", "content": text}}


class FactCheck(unittest.TestCase):
    DRAFT = "The Ender 3 V3 KE is a CoreXY printer, so the Kobra S1 is only a small step up for you. " * 3
    FIXED = "The Ender 3 V3 KE is a bed slinger and the Kobra S1 is CoreXY, so the S1 is a real upgrade for you. " * 3

    def setUp(self):
        a.HISTORY.clear()
        self.addCleanup(a.HISTORY.clear)
        for name, value in (("FACT_CHECK", True), ("recent_focus_context", lambda: "CONTEXT - none")):
            patcher = mock.patch.object(a, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def run_turn(self, drafts, verdicts):
        with mock.patch.object(a, "_ask", side_effect=[_reply(d) for d in drafts]) as ask, \
                mock.patch.object(a, "chat", side_effect=[_reply(v) for v in verdicts]):
            text = a.process_prompt("is this a worthy upgrade for my ender 3 v3 ke")
        return text, ask

    def test_a_misread_request_sends_the_answer_back_once(self):
        misread = 'TOPIC | SPECIFIC\nMISREAD | "treats the Ender as the new printer" | the user owns the Ender'
        text, ask = self.run_turn([self.DRAFT, self.FIXED], [misread, "TOPIC | SPECIFIC\nBACKED | \"bed slinger\" | fetched"])
        self.assertTrue(text.startswith(self.FIXED.strip()))
        self.assertNotIn("couldn't confirm", text)
        note = ask.call_args_list[1].args[0][-1]
        self.assertEqual(note["role"], "system")  # the model must not think the user wrote the review
        self.assertIn("the user has NOT seen it", note["content"])
        self.assertIn("treats the Ender as the new printer", note["content"])
        saved = [m["content"] for m in a.HISTORY]
        self.assertNotIn(self.DRAFT.strip(), saved)  # the rejected draft and the review are not kept
        self.assertFalse(any("Internal review" in c for c in saved))
        self.assertIn(self.FIXED.strip(), saved)

    def test_a_wrong_fact_is_edited_in_place(self):
        wrong = 'TOPIC | SPECIFIC\nCONTRADICTED | "The Ender 3 V3 KE is a CoreXY printer" | the spec page says bed slinger'
        text, ask = self.run_turn([self.DRAFT], [wrong, self.FIXED])
        self.assertEqual(ask.call_count, 1)  # no second research round
        self.assertTrue(text.startswith(self.FIXED.strip()))
        self.assertNotIn("couldn't confirm", text)
        self.assertIn(self.FIXED.strip(), [m["content"] for m in a.HISTORY])

    def test_a_failed_edit_keeps_the_answer(self):
        wrong = 'TOPIC | SPECIFIC\nCONTRADICTED | "The Ender 3 V3 KE is a CoreXY printer" | bed slinger'
        text, _ = self.run_turn([self.DRAFT], [wrong, "ok"])
        self.assertTrue(text.startswith(self.DRAFT.strip()))

    def test_an_edit_that_invents_figures_is_rejected(self):
        wrong = 'TOPIC | SPECIFIC\nCONTRADICTED | "The Ender 3 V3 KE is a CoreXY printer" | bed slinger'
        invented = self.FIXED + " It prints 350×350×350mm."
        text, _ = self.run_turn([self.DRAFT], [wrong, invented])
        self.assertTrue(text.startswith(self.DRAFT.strip()))

    def test_claims_still_unbacked_are_flagged_under_the_answer(self):
        problem = ('TOPIC | SPECIFIC\nUNBACKED | "The Ender 3 V3 KE is a CoreXY printer" | not in any source\n'
                   'UNBACKED | "the S1 has a resin tank" | not in any source')
        text, ask = self.run_turn([self.DRAFT, self.DRAFT], [problem, problem])
        self.assertEqual(ask.call_count, 2)  # only one research round
        footer = text.split(self.DRAFT.strip())[-1]
        self.assertIn("I couldn't confirm these details", footer)
        self.assertIn("The Ender 3 V3 KE is a CoreXY printer; the S1 has a resin tank", footer)

    def test_one_unchecked_detail_is_noted_without_a_rewrite(self):
        problem = 'TOPIC | SPECIFIC\nUNBACKED | "costs about £300" | no price in the evidence'
        text, ask = self.run_turn([self.DRAFT], [problem])
        self.assertEqual(ask.call_count, 1)
        self.assertTrue(text.startswith(self.DRAFT.strip()))
        self.assertIn("I couldn't confirm these details, so double-check them: costs about £300", text)

    def test_short_replies_and_disabled_checks_skip_the_checker(self):
        with mock.patch.object(a, "_ask", return_value=_reply("Hi! What can I do for you?")), \
                mock.patch.object(a, "chat") as checker:
            a.process_prompt("hello")
        checker.assert_not_called()
        with mock.patch.object(a, "FACT_CHECK", False), mock.patch.object(a, "chat") as checker:
            self.assertEqual(a.fact_check([{"role": "system", "content": ""}], "q", self.DRAFT), [])
        checker.assert_not_called()

    def test_verdict_lines_are_read_in_any_layout(self):
        reply = ("TOPIC | SPECIFIC\nBACKED | \"140 W\" | spec page\n- **UNBACKED** | \"16 GB RAM\" | not mentioned\n"
                 "VERDICT | \"has HDMI 2.1\" | CONTRADICTED by the manual\nUNBACKED | \"Kobra S1 Combo\" | name not in evidence\n1. MISREAD: compares them the wrong way round")
        with mock.patch.object(a, "chat", return_value=_reply(reply)):
            problems = a.fact_check([{"role": "system", "content": ""}], "pros and cons of the Kobra S1 Combo", self.DRAFT)
        self.assertEqual(problems, [('"16 GB RAM"', "unbacked", "not mentioned"), ('"has HDMI 2.1"', "contradicted", ""),
                                    ("compares them the wrong way round", "misread", "")])
        with mock.patch.object(a, "chat", return_value=_reply("TOPIC | GENERAL")):
            self.assertEqual(a.fact_check([{"role": "system", "content": ""}], "why are toddlers loud", self.DRAFT), [])

    def test_figures_that_were_looked_up_are_not_flagged(self):
        messages = [{"role": "system", "content": ""},
                    {"role": "tool", "tool_name": "web_fetch", "content": "Build volume 250*250*250mm, chamber heating 65℃, 2 fans"}]
        reply = ('TOPIC | SPECIFIC\nUNBACKED | "250×250×250mm build volume" | framed oddly\nUNBACKED | "chamber up to 65°C" | x\n'
                 'UNBACKED | "2 extruders" | not mentioned\nCONTRADICTED | "chamber up to 65°C" | evidence says 65')
        with mock.patch.object(a, "chat", return_value=_reply(reply)):
            problems = a.fact_check(messages, "q", self.DRAFT)
        self.assertEqual([p[0] for p in problems], ['"2 extruders"', '"chamber up to 65°C"'])

    def test_evidence_is_tool_output_not_earlier_answers(self):
        messages = [{"role": "system", "content": "prompt"},
                    {"role": "assistant", "content": "earlier claim: it is CoreXY"},
                    {"role": "tool", "tool_name": "web_fetch", "content": "Ender-3 V3 KE: Cartesian (bed slinger)"}]
        evidence = a._evidence(messages)
        self.assertIn("[web_fetch]\nEnder-3 V3 KE: Cartesian", evidence)
        self.assertNotIn("earlier claim", evidence)


if __name__ == "__main__":
    unittest.main()
