import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import markdown  # noqa: E402
import notebook  # noqa: E402


class Book(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.book = notebook.Notebook(Path(tmp.name) / "notes")

    def test_new_write_read(self):
        path = self.book.new("milk\n")
        self.assertEqual(self.book.read(path), "milk\n")
        self.assertNotEqual(self.book.new().name, path.name)

    def test_tabs_keep_their_order_and_stray_notes_get_one_at_the_end(self):
        a, b = self.book.new("a"), self.book.new("b")
        self.book.save_state({"tabs": [b.name, a.name]})
        time.sleep(0.02)
        stray = self.book.new("from a script")
        self.assertEqual(self.book.tabs(), [b, a, stray])

    def test_closing_deletes_the_note(self):
        full, empty = self.book.new("keep me?"), self.book.new("   \n")
        self.book.close(full)
        self.book.close(empty)
        self.assertFalse(full.exists())
        self.assertFalse(empty.exists())
        self.assertEqual(self.book.tabs(), [])
        self.book.close(full)  # already gone: nothing happens

    def test_tabs_survive_a_restart(self):
        a = self.book.new("still here")
        again = notebook.Notebook(self.book.dir)
        self.assertEqual([p.read_text() for p in again.tabs()], ["still here"])

    def test_state_and_hidden_files_are_not_tabs(self):
        self.book.save_state({"tabs": []})
        self.book.new("x")
        self.assertEqual(len(self.book.tabs()), 1)

    def test_append_makes_the_inbox(self):
        path = self.book.append("first thought")
        self.book.append("second")
        self.assertEqual(self.book.read(path), "# Inbox\nfirst thought\nsecond\n")

    def test_a_broken_state_file_is_ignored(self):
        self.book.state_path.write_text("{broken")
        self.assertEqual(self.book.load_state(), {})

    def test_writes_leave_no_temp_files(self):
        path = self.book.new("x")
        self.book.write(path, "y")
        self.assertEqual([p.name for p in self.book.dir.iterdir()], [path.name])

    def test_title_and_save_as_name(self):
        self.assertEqual(notebook.title_of("\n\n## Plan for **Monday**\nmore"), "Plan for **Monday")
        self.assertEqual(notebook.title_of("- [ ] buy milk"), "buy milk")
        self.assertEqual(notebook.title_of("   \n"), "")
        self.assertEqual(notebook.file_name('a/b: "c"?'), "a b c.md")
        self.assertEqual(notebook.file_name(""), "Note.md")


class Formatting(unittest.TestCase):
    def tags(self, text):
        return [(text[a:b], tag) for a, b, tag in markdown.spans(text)]

    def test_headings_and_inline(self):
        got = self.tags("# Title\nsome **bold** and *it* and `code` ~~gone~~\n")
        for item in (("# Title", "h1"), ("**bold**", "bold"), ("*it*", "italic"), ("`code`", "code"), ("~~gone~~", "strike")):
            self.assertIn(item, got)

    def test_lists_and_tasks(self):
        got = self.tags("- one\n- [x] done\n- [ ] todo\n2. two\n")
        self.assertIn(("-", "bullet"), got)
        self.assertIn(("2.", "bullet"), got)
        self.assertIn(("[ ]", "box"), got)
        self.assertIn(("- [x] done", "done"), got)

    def test_code_blocks_are_left_alone(self):
        got = self.tags("```\n# not a heading **no**\n```\nafter **yes**")
        self.assertIn(("```\n# not a heading **no**\n```", "fence"), got)
        self.assertNotIn(("# not a heading **no**", "h1"), got)
        self.assertNotIn(("**no**", "bold"), got)
        self.assertIn(("**yes**", "bold"), got)

    def test_an_unclosed_code_block_runs_to_the_end(self):
        self.assertEqual(self.tags("```\nstill typing"), [("```\nstill typing", "fence")])

    def test_links(self):
        got = self.tags("see [docs](https://x.org) or https://y.org/a")
        self.assertIn(("[docs](https://x.org)", "link"), got)
        self.assertIn(("https://y.org/a", "link"), got)

    def test_snake_case_is_not_italic(self):
        self.assertEqual(self.tags("a_b_c and 2*3*4"), [])


class Editing(unittest.TestCase):
    def test_enter_continues_lists(self):
        self.assertEqual(markdown.next_item("- milk"), ("- ", False))
        self.assertEqual(markdown.next_item("  * milk"), ("  * ", False))
        self.assertEqual(markdown.next_item("- [x] milk"), ("- [ ] ", False))
        self.assertEqual(markdown.next_item("9. nine"), ("10. ", False))
        self.assertEqual(markdown.next_item("- "), ("", True))
        self.assertEqual(markdown.next_item("plain"), (None, False))

    def test_toggle_box(self):
        self.assertEqual(markdown.toggle_box("- [ ] a"), "- [x] a")
        self.assertEqual(markdown.toggle_box("  - [x] a"), "  - [ ] a")
        self.assertEqual(markdown.toggle_box("- a"), "- [ ] a")
        self.assertEqual(markdown.toggle_box("a"), "- [ ] a")

    def test_wrap_and_heading(self):
        self.assertEqual(markdown.wrap("x", "**"), "**x**")
        self.assertEqual(markdown.wrap("**x**", "**"), "x")
        self.assertEqual(markdown.heading("Title", 2), "## Title")
        self.assertEqual(markdown.heading("## Title", 2), "Title")
        self.assertEqual(markdown.heading("# Title", 3), "### Title")


if __name__ == "__main__":
    unittest.main()
