import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import notifications  # noqa: E402
from gi.repository import GLib  # noqa: E402


def notify(actions=(), hints=None, summary="Hello", body="World", icon="dialog-information"):
    return GLib.Variant("(susssasa{sv}i)", ("App", 7, icon, summary, body, list(actions), hints or {}, -1))


class Parsing(unittest.TestCase):
    def test_fields(self):
        got = notifications.parse_notify(notify())
        self.assertEqual((got["app"], got["replaces"], got["icon"], got["summary"], got["body"]),
                         ("App", 7, "dialog-information", "Hello", "World"))
        self.assertFalse(got["critical"])
        self.assertFalse(got["transient"])

    def test_markup_is_removed(self):
        got = notifications.parse_notify(notify(body="<b>Tom &amp; Sam</b> said <a href='x'>hi</a>"))
        self.assertEqual(got["body"], "Tom & Sam said hi")

    def test_urgency_and_transient(self):
        got = notifications.parse_notify(notify(hints={"urgency": GLib.Variant("y", 2), "transient": GLib.Variant("b", True)}))
        self.assertTrue(got["critical"])
        self.assertTrue(got["transient"])

    def test_image_path_wins_over_app_icon(self):
        got = notifications.parse_notify(notify(hints={"image-path": GLib.Variant("s", "/tmp/a.png")}))
        self.assertEqual(got["icon"], "/tmp/a.png")

    def test_image_data(self):
        image = GLib.Variant("(iiibiiay)", (1, 1, 3, False, 8, 3, [1, 2, 3]))
        got = notifications.parse_notify(notify(hints={"image-data": image}))
        self.assertEqual(got["image"][:4], (1, 1, 3, False))
        self.assertEqual(got["image"][4].get_data(), bytes([1, 2, 3]))


class Ago(unittest.TestCase):
    def test_time_ago(self):
        self.assertEqual(notifications.time_ago(0, 30), "now")
        self.assertEqual(notifications.time_ago(0, 300), "5m")
        self.assertEqual(notifications.time_ago(0, 7200), "2h")
        self.assertEqual(notifications.time_ago(0, 172800), "2d")


if __name__ == "__main__":
    unittest.main()
