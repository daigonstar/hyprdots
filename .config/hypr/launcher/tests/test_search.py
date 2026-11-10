import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import search  # noqa: E402


class StepTest(unittest.TestCase):
    """Ten results, four across: rows 0-3, 4-7 and a short last row 8-9."""

    def test_left_and_right_run_on_through_the_rows(self):
        self.assertEqual(search.step(3, 10, 4, "right"), 4)
        self.assertEqual(search.step(4, 10, 4, "left"), 3)

    def test_left_and_right_stop_at_the_ends(self):
        self.assertEqual(search.step(0, 10, 4, "left"), 0)
        self.assertEqual(search.step(9, 10, 4, "right"), 9)

    def test_up_and_down_keep_to_the_column(self):
        self.assertEqual(search.step(1, 10, 4, "down"), 5)
        self.assertEqual(search.step(5, 10, 4, "up"), 1)

    def test_up_from_the_top_row_stays_put(self):
        self.assertEqual(search.step(2, 10, 4, "up"), 2)

    def test_down_into_a_shorter_last_row_lands_on_its_end(self):
        self.assertEqual(search.step(7, 10, 4, "down"), 9)

    def test_down_from_the_last_row_stays_put(self):
        self.assertEqual(search.step(8, 10, 4, "down"), 8)

    def test_a_single_column_is_a_list(self):
        self.assertEqual(search.step(2, 5, 1, "down"), 3)
        self.assertEqual(search.step(2, 5, 1, "right"), 3)

    def test_no_results(self):
        self.assertEqual(search.step(0, 0, 1, "right"), 0)


class LettersTest(unittest.TestCase):
    def test_initial_files_anything_else_under_hash(self):
        self.assertEqual(search.initial("ghostty"), "G")
        self.assertEqual(search.initial("7-Zip"), "#")
        self.assertEqual(search.initial(""), "#")

    def test_first_with_initial(self):
        results = [search.Result("app", t) for t in ("Ark", "Bazaar", "btop", "Vim")]
        self.assertEqual(search.first_with_initial(results, "B"), 1)
        self.assertIsNone(search.first_with_initial(results, "Z"))


class WordingTest(unittest.TestCase):
    def test_mode_follows_what_was_typed(self):
        for query, label in (("", "APPS"), ("  ", "APPS"), ("fire", "SEARCH"), ("12*7", "SUM"), ("> htop", "RUN"), ("? arch", "WEB")):
            self.assertEqual(search.mode_label(query), label, query)

    def test_action_says_what_enter_does(self):
        self.assertEqual(search.action_text(search.Result("app", "Ghostty")), "Open Ghostty")
        self.assertEqual(search.action_text(search.Result("calc", "84")), "Copy 84")
        self.assertEqual(search.action_text(search.Result("power", "Sleep")), "Sleep")


if __name__ == "__main__":
    unittest.main()
