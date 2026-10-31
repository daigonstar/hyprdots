import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import _paths
from hyprsettings import mimeapps
from test_tui import TuiBase

APPS = {"viewer.desktop": {"name": "Viewer", "mimes": ["image/png", "image/jpeg"], "hidden": False},
        "editor.desktop": {"name": "Editor", "mimes": ["image/svg+xml"], "hidden": False},
        "hidden.desktop": {"name": "Hidden", "mimes": ["image/png"], "hidden": True}}


class MimeTest(unittest.TestCase):
    def setUp(self):
        self.home = Path(tempfile.mkdtemp())
        env = {"XDG_CONFIG_HOME": str(self.home / "cfg"), "XDG_DATA_HOME": str(self.home / "data"),
               "XDG_DATA_DIRS": str(self.home / "sys"), "XDG_CONFIG_DIRS": str(self.home / "none")}
        p = mock.patch.dict(os.environ, env)
        p.start()
        self.addCleanup(p.stop)
        self.apps_dir = self.home / "sys" / "applications"
        (self.apps_dir / "sub").mkdir(parents=True)

    def desktop(self, name, body):
        (self.apps_dir / name).write_text("[Desktop Entry]\nType=Application\n" + body)

    def test_scan_ids_and_hidden(self):
        self.desktop("a.desktop", "Name=A\nMimeType=image/png;image/jpeg;\n")
        self.desktop("sub/b.desktop", "Name=B\nNoDisplay=true\n")
        self.desktop("c.desktop", "Name=C\nHidden=true\n")
        apps = mimeapps.installed_apps()
        self.assertEqual(apps["a.desktop"]["mimes"], ["image/png", "image/jpeg"])
        self.assertTrue(apps["sub-b.desktop"]["hidden"])
        self.assertNotIn("c.desktop", apps)

    def test_default_lookup_order_and_missing_apps(self):
        (self.apps_dir / "mimeinfo.cache").write_text("[MIME Cache]\nimage/png=viewer.desktop;\n")
        self.assertEqual(mimeapps.default_for("image/png", APPS), "viewer.desktop")
        (self.home / "cfg").mkdir()
        (self.home / "cfg" / "mimeapps.list").write_text("[Default Applications]\nimage/png=gone.desktop;editor.desktop\n")
        self.assertEqual(mimeapps.default_for("image/png", APPS), "editor.desktop")     # uninstalled entries are skipped
        self.assertIsNone(mimeapps.default_for("video/mp4", APPS))

    def test_candidates_and_state(self):
        names = mimeapps.candidates(["image/png", "image/svg+xml"], APPS)
        self.assertEqual(names, [("viewer.desktop", "Viewer"), ("editor.desktop", "Editor")])   # hidden app left out
        (self.home / "cfg").mkdir()
        (self.home / "cfg" / "mimeapps.list").write_text("[Default Applications]\nimage/png=viewer.desktop\nimage/svg+xml=editor.desktop\n")
        self.assertEqual(mimeapps.category_state(["image/png", "image/svg+xml"], APPS), ("viewer.desktop", True))

    def test_resolve_type(self):
        self.assertEqual(mimeapps.resolve_type(".png"), "image/png")
        self.assertEqual(mimeapps.resolve_type("Video/MP4"), "video/mp4")
        with self.assertRaises(ValueError):
            mimeapps.resolve_type(".zzzzqq")
        with self.assertRaises(ValueError):
            mimeapps.resolve_type("not valid!")


class MimePageTest(TuiBase):
    def test_page_lists_categories_and_sets_default(self):
        self.app._apps = APPS
        self.goto("File types")
        text = self.app.render_plain()
        for want in ("Web links", "Images", "(nothing chosen)"):
            self.assertIn(want, text)
        with mock.patch.object(mimeapps, "set_default", return_value=(True, "")) as setter, \
                mock.patch.object(mimeapps, "default_for", return_value=None):
            idx = [c[0] for c in mimeapps.CATEGORIES].index("Images")
            self.app.mime_menu("Images", "", mimeapps.CATEGORIES[idx][2])
            self.assertEqual(self.app.popup.mode, "choose")
            self.app.handle_key("enter")
            self.assertEqual(setter.call_args[0][0], "viewer.desktop")
            self.assertIn("Viewer", self.app.notice)

    def test_no_candidates_explains(self):
        self.app._apps = {}
        self.app.mime_menu("PDF documents", "", ["application/pdf"])
        self.assertEqual(self.app.popup.mode, "message")


if __name__ == "__main__":
    unittest.main()
