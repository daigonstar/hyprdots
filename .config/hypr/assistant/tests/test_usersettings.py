"""Characterisation tests for usersettings.section(): how user_settings.toml and its .local override combine.

The cases live in tests/fixtures/usersettings/<case>/ as plain files, so the Rust settings crate can run the very same
cases and must agree with Python on every value:

    user_settings.toml        the shared file (absent = missing)
    user_settings.local.toml  the private override (absent = missing)
    request.json              {"section": ..., "defaults": {...}} as passed to section()
    expected.json             what section() returns

expected.json records today's behaviour; it is not a wish list. To record it again after a deliberate change:

    HYPRDOTS_RECORD=1 python3 -m unittest tests.test_usersettings
"""

import contextlib
import io
import json
import os
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import usersettings  # noqa: E402

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "usersettings"


def run_case(case):
    request = json.loads((case / "request.json").read_text())
    files = (str(case / "user_settings.toml"), str(case / "user_settings.local.toml"))
    with mock.patch.object(usersettings, "SETTINGS_FILES", files), contextlib.redirect_stderr(io.StringIO()):
        return usersettings.section(request["section"], request["defaults"])


class SettingsCases(unittest.TestCase):
    def test_every_case(self):
        cases = sorted(p for p in FIXTURES.iterdir() if p.is_dir())
        self.assertGreater(len(cases), 10)
        for case in cases:
            with self.subTest(case.name):
                got = run_case(case)
                expected_file = case / "expected.json"
                if os.environ.get("HYPRDOTS_RECORD"):
                    expected_file.write_text(json.dumps(got, indent=2) + "\n")
                expected = json.loads(expected_file.read_text())
                self.assertEqual(got, expected)
                # json.loads turns 1.0 into a float and 1 into an int, so this also pins int versus float
                self.assertEqual({k: type(v) for k, v in got.items()}, {k: type(v) for k, v in expected.items()})


if __name__ == "__main__":
    unittest.main()
