import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import overview  # noqa: E402


def client(number):
    return {"workspace": {"id": number}}


class Workspaces(unittest.TestCase):
    def test_used_and_on_screen_ones_and_a_free_one(self):
        got = overview.workspace_list([{"id": 2, "windows": 1}, {"id": 7, "windows": 0}], [client(5)], [1, 2])
        self.assertEqual(got, [1, 2, 3, 5])

    def test_special_workspaces_are_left_out(self):
        got = overview.workspace_list([{"name": "special:agent", "windows": 1}, {"id": -98, "windows": 1}], [client(-98)], [1])
        self.assertEqual(got, [1, 2])

    def test_columns(self):
        self.assertEqual([overview.layout_columns(n) for n in (1, 2, 4, 5, 9, 16, 30)], [1, 2, 2, 3, 3, 4, 4])


if __name__ == "__main__":
    unittest.main()
