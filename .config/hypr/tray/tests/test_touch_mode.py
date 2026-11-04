import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import touch_mode  # noqa: E402


class GtkBlock(unittest.TestCase):
    MINE = "/* hyprdots theme: colours */\n@define-color accent #fff;\n/* end */\n\nbutton { color: red; }\n"

    def test_going_in_keeps_what_was_there(self):
        text = touch_mode.with_block(self.MINE, True)
        self.assertTrue(text.startswith(self.MINE))
        self.assertIn(touch_mode.GTK_CSS, text)

    def test_coming_out_leaves_it_as_it_was(self):
        self.assertEqual(touch_mode.with_block(touch_mode.with_block(self.MINE, True), False), self.MINE)

    def test_going_in_twice_adds_it_once(self):
        text = touch_mode.with_block(touch_mode.with_block(self.MINE, True), True)
        self.assertEqual(text.count(touch_mode.GTK_MARK), 1)

    def test_an_empty_file_stays_empty(self):
        self.assertEqual(touch_mode.with_block(touch_mode.with_block("", True), False), "")


if __name__ == "__main__":
    unittest.main()
