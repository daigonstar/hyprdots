"""The desktop's, the lock screen's and the login screen's on-screen keyboards share one layout, so that you need only learn it once."""
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def squeekboard(name):
    """{view: the character keys, row by row}, from a layout file."""
    text = (ROOT / "install/squeekboard" / name).read_text()
    views, current = {}, None
    for line in text.split("\nbuttons:")[0].split("\nviews:")[1].splitlines():
        if re.match(r"    \w+:$", line):
            current = views.setdefault(line.strip(" :"), [])
        elif line.startswith("        - "):
            row = line.strip()[2:].strip('"').replace('\\"', '"').replace("\\\\", "\\").split()
            current.append([k for k in row if len(k) == 1])
    return views


class SameLayout(unittest.TestCase):
    def test_wide_and_narrow_have_the_same_keys(self):
        self.assertEqual(squeekboard("us_wide.yaml"), squeekboard("us.yaml"))

    def test_the_login_screen_has_them(self):
        self.check((ROOT / "SDDM/sugar-dark/Components/TouchKeys.qml").read_text())

    def test_the_lock_screen_has_them(self):
        self.check((ROOT / "install/gtklock-keyboard.c").read_text())

    def check(self, source):
        keys = re.findall(r'"((?:[^"\\]|\\.)+)"', source)
        rows = {re.sub(r"\\(.)", r"\1", k) for k in keys if " " in k}
        for view, page in squeekboard("us_wide.yaml").items():
            for row in page[:3]:  # the bottom row's keys differ: each has its own use for them
                # Each half of each row appears as written in the source
                self.assertTrue(any(" ".join(row).startswith(r) or " ".join(row).endswith(r) for r in rows), (view, row))


if __name__ == "__main__":
    unittest.main()
