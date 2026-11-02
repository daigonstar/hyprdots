import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from hyprsettings import theme_parts  # noqa: E402


class KdeGlobals(unittest.TestCase):
    def test_colour_groups_are_replaced_and_the_rest_kept(self):
        text = "[General]\nfont=x\n\n[Colors:View]\nBackgroundNormal=1,2,3\n\n[KDE]\nSingleClick=false\n"
        got = theme_parts.with_kde_colours(text, "[Colors:Window]\nBackgroundNormal=4,5,6\n")
        self.assertNotIn("1,2,3", got)
        self.assertIn("font=x", got)
        self.assertIn("SingleClick=false", got)
        self.assertIn("[Colors:Window]", got)

    def test_removed_when_apps_are_not_coloured(self):
        text = "[Colors:View]\nBackgroundNormal=1,2,3\n\n[KDE]\nSingleClick=false\n"
        self.assertEqual(theme_parts.with_kde_colours(text, None).strip(), "[KDE]\nSingleClick=false")

    def test_empty_file(self):
        self.assertEqual(theme_parts.with_kde_colours("", "[Colors:Window]\n"), "[Colors:Window]\n")

    def test_groups_kde_needs_are_present_with_rgb_triples(self):
        out = theme_parts.kde_colours({})
        for group in ("Window", "View", "Button", "Selection", "Header", "Tooltip", "Complementary"):
            self.assertIn(f"[Colors:{group}]", out)
        for line in out.splitlines():
            if "=" in line:
                self.assertRegex(line.split("=")[1], r"^\d+,\d+,\d+$")


if __name__ == "__main__":
    unittest.main()
