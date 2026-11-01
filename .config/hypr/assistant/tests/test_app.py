"""Tests for the GTK window's pure parts: how answers split into text and code blocks, the Pango markup it
builds, and the approval hook. Skipped when GTK 4 and libadwaita are not installed.

    cd ~/hyprdots/.config/hypr/assistant && python3 -m unittest discover -s tests -v
"""

import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _sandbox  # noqa: E402,F401  (must come before hypr_agent)

try:
    import hypr_assistant_app as app
except (ImportError, ValueError) as e:  # no GTK 4 / libadwaita
    app = None
    SKIP = str(e)


@unittest.skipIf(app is None, "GTK 4 / libadwaita not available")
class Blocks(unittest.TestCase):
    def test_fenced_code_becomes_a_code_block(self):
        blocks = app.parse_blocks("Try this:\n\n```bash\nfree -h\n```\n\nThen look again.")
        self.assertEqual([b[0] for b in blocks], ["text", "code", "text"])
        self.assertEqual(blocks[1][1:], ("bash", "free -h"))

    def test_dollar_lines_become_one_bash_block(self):
        blocks = app.parse_blocks("Run:\n$ sudo pacman -Syu\n$ reboot")
        self.assertEqual(blocks[-1], ("code", "bash", "sudo pacman -Syu\nreboot"))

    def test_unclosed_fence_still_shows_the_code(self):
        blocks = app.parse_blocks("```ini\n[Unit]\nAfter=network.target")
        self.assertEqual(blocks, [("code", "ini", "[Unit]\nAfter=network.target")])

    def test_fence_inside_code_with_a_language_is_kept(self):
        blocks = app.parse_blocks("```md\n```bash\nls\n```")
        self.assertEqual(blocks[0][0], "code")
        self.assertIn("```bash", blocks[0][2])


@unittest.skipIf(app is None, "GTK 4 / libadwaita not available")
class Markup(unittest.TestCase):
    def test_text_is_escaped(self):
        out = app.inline_markup("a < b & **c**")
        self.assertIn("a &lt; b &amp; <b>c</b>", out)

    def test_inline_code_is_not_formatted(self):
        out = app.inline_markup("`**x** <y>`")
        self.assertIn("**x** &lt;y&gt;", out)
        self.assertNotIn("<b>", out)

    def test_links(self):
        out = app.inline_markup("see [the wiki](https://wiki.archlinux.org/a?b=1&c=2) or https://example.org.")
        self.assertIn('<a href="https://wiki.archlinux.org/a?b=1&amp;c=2">the wiki</a>', out)
        self.assertIn('<a href="https://example.org">https://example.org</a>.', out)

    def test_markup_is_valid_pango(self):
        import re
        from gi.repository import Pango
        for text in ("**bold** and `code` & <tags>", "[x](https://a.b/c) https://d.e/f", "un**closed"):
            # <a> is a GtkLabel extension that Pango itself does not know
            Pango.parse_markup(re.sub(r"</?a[^>]*>", "", app.inline_markup(text)), -1, "\0")
        for code, lang in (('echo "hi" # note', "bash"), ("x = 'a' -- c", "lua"), ("<b>&", "")):
            Pango.parse_markup(app.highlight(code, lang), -1, "\0")


@unittest.skipIf(app is None, "GTK 4 / libadwaita not available")
class Confirm(unittest.TestCase):
    def test_allow_mode_skips_ordinary_prompts_only(self):
        with mock.patch.object(app.agent, "AUTO_APPROVE", [True]), mock.patch.object(app.APP, "turn", None):
            self.assertTrue(app.gui_confirm("Run it?"))
            self.assertFalse(app.gui_confirm("Run it?", sensitive=True))
            self.assertFalse(app.gui_confirm("Run it?", auto_ok=False))

    def test_no_open_question_means_no(self):
        with mock.patch.object(app.APP, "turn", None):
            self.assertFalse(app.gui_confirm("Run it?"))


@unittest.skipIf(app is None, "GTK 4 / libadwaita not available")
class Attachments(unittest.TestCase):
    def setUp(self):
        import tempfile
        self.dir = Path(tempfile.mkdtemp(dir=_sandbox.FAKE_HOME))

    def file(self, name, data):
        path = self.dir / name
        path.write_bytes(data if isinstance(data, bytes) else data.encode())
        return app.Attachment("file", str(path), name)

    def test_text_file_goes_into_the_question(self):
        prompt = app.attachment_prompt("why won't this start?", [self.file("my.service", "[Unit]\nAfter=x\n")], {})
        self.assertTrue(prompt.startswith("why won't this start?"))
        self.assertIn("```service\n[Unit]\nAfter=x", prompt)

    def test_binary_file_is_passed_by_path_only(self):
        prompt = app.attachment_prompt("what is it?", [self.file("blob.bin", b"\x00\x01\x02" * 50)], {})
        self.assertIn("blob.bin", prompt)
        self.assertIn("Inspect it with your tools", prompt)
        self.assertNotIn("```", prompt)

    def test_text_limit_is_shared_by_all_files(self):
        big = "x" * (app.TEXT_CHARS + 500)
        prompt = app.attachment_prompt("", [self.file("a.txt", big), self.file("b.txt", "hello")], {})
        self.assertIn("[cut here", prompt)
        self.assertIn("text limit was reached", prompt)
        self.assertLess(len(prompt), app.TEXT_CHARS + 1500)

    def test_key_files_are_never_read(self):
        ssh = Path(_sandbox.FAKE_HOME) / ".ssh"
        ssh.mkdir(exist_ok=True)
        (ssh / "id_ed25519").write_text("PRIVATE KEY")
        a = app.Attachment("file", str(ssh / "id_ed25519"), "id_ed25519")
        prompt = app.attachment_prompt("", [a], {})
        self.assertNotIn("PRIVATE KEY", prompt)
        self.assertIn("protected location", prompt)

    def test_image_notes(self):
        img = app.Attachment("image", "/tmp/x.png", "x.png", str(self.dir / "shot.png"))
        seen = app.attachment_prompt("", [img], {img: "Vision Analysis: a cat"})
        self.assertTrue(seen.startswith("Describe the attached image."))
        self.assertIn("ask_about_image", seen)
        failed = app.attachment_prompt("hm", [img], {img: "Vision Analysis Failed: timeout"})
        self.assertIn("could not be read: Vision Analysis Failed: timeout", failed)

    def test_big_pictures_are_scaled_to_png(self):
        from gi.repository import GdkPixbuf
        src = self.dir / "big.jpg"
        GdkPixbuf.Pixbuf.new(GdkPixbuf.Colorspace.RGB, False, 8, 4000, 1000).savev(str(src), "jpeg", [], [])
        with mock.patch.object(app, "UPLOAD_DIR", str(self.dir / "uploads")):
            out = app.save_image(str(src), "big")
        fmt, width, height = GdkPixbuf.Pixbuf.get_file_info(out)
        self.assertEqual((fmt.get_name(), width, height), ("png", app.IMAGE_MAX_SIDE, 400))

    def test_not_a_picture(self):
        from gi.repository import GLib
        bad = self.dir / "fake.png"
        bad.write_text("not an image")
        with self.assertRaises(GLib.Error):
            app.save_image(str(bad), "fake")


if __name__ == "__main__":
    unittest.main()
