import unittest

import _paths  # noqa: F401

try:
    from hyprsettings.gui import app
except (ImportError, ValueError):  # no GTK 4 here (CI's settings job)
    app = None


@unittest.skipUnless(app, "needs GTK 4 and libadwaita")
class Sidebar(unittest.TestCase):
    def test_every_page_shows_once(self):
        order = [page for _, page in app.sidebar_order()]
        self.assertEqual(sorted(order), sorted(app.PAGES))
        self.assertEqual(len(order), len(set(order)))

    def test_sections_only_name_real_pages(self):
        for _, pages in app.SECTIONS:
            for page in pages:
                self.assertIn(page, app.PAGES)

    def test_search_finds_a_page_by_a_setting_on_it(self):
        self.assertIn("gap", app.search_text("Hyprland"))
        self.assertIn("default apps", app.search_text("Hyprdots"))

    def test_search_words_reach_the_hand_built_pages(self):
        for words, page in (("wifi", "Network"), ("wi-fi", "Network"), ("resolution", "Displays"), ("temperature", "Performance")):
            self.assertIn(app._plain(words), app.search_text(page), words)

    def test_keywords_only_name_real_pages(self):
        for page in app.KEYWORDS:
            self.assertIn(page, app.PAGES)


if __name__ == "__main__":
    unittest.main()
