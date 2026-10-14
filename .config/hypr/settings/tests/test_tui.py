import shutil
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

import _paths
from hyprsettings import models, schema, tui
from hyprsettings.store import Store


def type_text(app, text):
    for ch in text:
        app.handle_key(ch, ch)


class TuiBase(unittest.TestCase):
    def setUp(self):
        self.dir = _paths.scratch_hypr_dir()
        self.state = Path(tempfile.mkdtemp(prefix="hypr-state-"))
        self.addCleanup(shutil.rmtree, self.dir, True)
        self.addCleanup(shutil.rmtree, self.state, True)
        for patcher in (mock.patch.object(tui, "state_dir", return_value=self.state),
                        mock.patch.object(tui.shutil, "which", return_value=None),
                        mock.patch.object(tui.subprocess, "run")):
            patcher.start()
            self.addCleanup(patcher.stop)
        self.store = Store(self.dir)
        self.app = tui.App(self.store, (110, 32))

    def goto(self, page):
        self.app.focus = "menu"
        for _ in range(len(schema.PAGES)):
            if schema.PAGES[self.app.page] == page:
                break
            self.app.handle_key("down")
        self.app.handle_key("tab")

    def select(self, label):
        if self.app.focus == "menu":
            self.app.handle_key("tab")
        self.app.sel[self.app.page] = 0
        for _ in range(40):
            row = self.app.current_row()
            if row and row.label == label:
                return row
            self.app.handle_key("down")
        self.fail(f"row {label!r} not found")

    def screen(self):
        return self.app.render_plain()


class Navigation(TuiBase):
    def test_pages_and_rows_render(self):
        text = self.screen()
        for page in schema.PAGES:
            self.assertIn(page, text)
        self.assertIn("Chat model", text)
        self.assertIn("qwen3:14b", text)
        self.goto("Hyprland")
        self.assertIn("Gap between windows", self.screen())
        self.goto("Assistant Monitor")
        self.assertIn("Disk warning", self.screen())
        self.assertIn("85 %", self.screen())

    def test_help_and_selection_text(self):
        self.goto("Hyprland")
        self.select("Corner rounding")
        text = self.screen()
        self.assertIn("How round window corners are", text)
        self.assertIn("Takes effect when Hyprland reloads", text)
        self.app.handle_key("?")
        self.assertIn("Ctrl+S", self.screen())
        self.app.handle_key("x")
        self.assertIsNone(self.app.popup)

    def test_small_terminals_do_not_crash_and_selection_stays_visible(self):
        self.app.size = (60, 16)
        self.goto("Assistant Monitor")
        for _ in range(20):
            self.app.handle_key("down")
        text = self.screen()
        self.assertIn("›", text)
        self.assertTrue(all(len(line) <= 61 for line in text.splitlines()), "a line is wider than the terminal")


class Editing(TuiBase):
    def test_number_input_validation_and_save(self):
        self.goto("Hyprland")
        self.select("Gap between windows")
        self.app.handle_key("enter")
        self.assertEqual(self.app.popup.mode, "input")
        self.app.handle_key("c-u")
        type_text(self.app, "999")
        self.app.handle_key("enter")
        self.assertIsNotNone(self.app.popup, "a bad value must keep the box open")
        self.assertIn("between 0 and 50", self.screen())
        self.app.handle_key("c-u")
        type_text(self.app, "12")
        self.app.handle_key("enter")
        self.assertIsNone(self.app.popup)
        self.assertIn("● changed", self.screen())
        self.assertIn("not saved yet", self.screen())
        self.app.handle_key("c-s")
        self.assertEqual(Store(self.dir).get(schema.BY_ID["hyprland.gaps_in"]), (12, "yours"))
        self.assertIn("gaps_in = 12", (self.dir / "user_overrides.lua").read_text())
        self.assertNotIn("not saved", self.screen())

    def test_toggle_nudge_reset(self):
        self.goto("Hyprland")
        blur = self.select("Background blur")
        self.app.handle_key(" ")
        self.assertEqual(self.store.get(schema.BY_ID["hyprland.blur"]), (False, "changed"))
        self.app.handle_key("r")
        self.assertEqual(self.store.get(schema.BY_ID["hyprland.blur"])[1], "default")
        self.select("Corner rounding")
        for _ in range(3):
            self.app.handle_key("+")
        self.assertEqual(self.store.get(schema.BY_ID["hyprland.rounding"])[0], 21)
        for _ in range(30):
            self.app.handle_key("-")
        self.assertEqual(self.store.get(schema.BY_ID["hyprland.rounding"])[0], 0)       # stops at the minimum
        self.select("Focused window opacity")
        self.app.handle_key("-")
        self.assertEqual(self.store.get(schema.BY_ID["hyprland.active_opacity"])[0], 0.95)

    def test_choice_popup(self):
        self.goto("Hyprland")
        self.select("Tiling layout")
        self.app.handle_key("enter")
        self.assertEqual(self.app.popup.mode, "choose")
        self.assertIn("master", self.screen())
        self.app.handle_key("down")
        self.app.handle_key("enter")
        self.assertEqual(self.store.get(schema.BY_ID["hyprland.layout"]), ("master", "changed"))

    def test_custom_choice_and_escape(self):
        self.goto("Hyprland")
        self.select("Keyboard layout")
        self.app.handle_key("enter")
        for _ in range(len(self.app.popup.items) - 1):
            self.app.handle_key("down")
        self.app.handle_key("enter")                    # "Something else..."
        self.assertEqual(self.app.popup.mode, "input")
        self.app.handle_key("c-u")
        type_text(self.app, "dvorak")
        self.app.handle_key("escape")
        self.assertEqual(self.store.get(schema.BY_ID["hyprland.kb_layout"])[1], "default")
        self.assertFalse(self.store.dirty)

    def test_text_editing_keys(self):
        self.goto("Assistant Monitor")
        self.select("Ignored journal sources")
        self.app.handle_key("enter")
        p = self.app.popup
        self.assertEqual(p.text, "bluetoothd, kwin_wayland, sddm-helper")
        for key in ("home", "right", "delete", "end", "left"):          # drops the 2nd letter, then moves left of the last one
            self.app.handle_key(key)
        self.app.handle_key("backspace")                                 # drops the letter before the cursor
        self.app.handle_key("end")
        type_text(self.app, ", extra")
        self.app.handle_key("enter")
        self.assertEqual(self.store.get(schema.BY_ID["monitor.journal_ignore"])[0], ["buetoothd", "kwin_wayland", "sddm-helpr", "extra"])

    def test_quit_flow(self):
        self.goto("Hyprland")
        self.select("Border thickness")
        self.app.handle_key("+")
        self.app.handle_key("q")
        self.assertEqual(self.app.popup.mode, "confirm")
        self.app.handle_key("c", "c")
        self.assertIsNone(self.app.exit_action)
        self.app.handle_key("q")
        self.app.handle_key("n", "n")
        self.assertEqual(self.app.exit_action, "quit")
        self.assertFalse((self.dir / "user_settings.local.toml").exists())
        self.app.exit_action = None
        self.app.handle_key("q")
        self.app.handle_key("y", "y")
        self.assertEqual(self.app.exit_action, "quit")
        self.assertEqual(Store(self.dir).get(schema.BY_ID["hyprland.border_size"])[0], 3)

    def test_failed_save_is_shown_not_hidden(self):
        self.goto("Hyprland")
        self.select("Border thickness")
        self.app.handle_key("+")
        with mock.patch.object(Store, "save", side_effect=OSError("disk full")):
            self.app.handle_key("c-s")
        self.assertEqual(self.app.popup.title, "Could not save")
        self.assertIn("disk full", self.screen())
        self.assertTrue(self.store.dirty)

    def test_hyprland_reload_offer_after_save(self):
        tui.shutil.which.return_value = "/usr/bin/hyprctl"
        self.goto("Hyprland")
        self.select("Border thickness")
        self.app.handle_key("+")
        self.app.handle_key("c-s")
        self.assertEqual(self.app.popup.title, "Reload Hyprland now?")
        tui.subprocess.run.return_value = mock.Mock(returncode=0, stdout="")
        self.app.handle_key("y", "y")
        calls = [c.args[0] for c in tui.subprocess.run.call_args_list]
        self.assertIn(["hyprctl", "reload"], calls)
        self.assertIn("reloaded", self.app.notice)


class SavePrompts(TuiBase):
    def stage_one(self):
        self.goto("Hyprland")
        self.select("Border thickness")
        self.app.handle_key("+")

    def test_nothing_pending_shows_a_quiet_save_button(self):
        text = self.screen()
        self.assertIn("[ Nothing to save ]", text)
        self.assertNotIn("not saved", text)

    def test_pending_changes_explain_how_to_save_everywhere(self):
        self.stage_one()
        text = self.screen()
        self.assertIn("● 1 change not saved yet", text.splitlines()[0])            # title bar
        self.assertIn("[ Save changes ]", text)                                    # the button
        self.assertIn("1 pending (s)", text)
        self.assertIn("Press Ctrl+S or s (or click [ Save changes ])", text)       # the instructions
        self.assertIn("q quits without saving", text)
        self.goto("Calendar")                                                      # still visible on every page
        self.assertIn("not saved yet", self.screen())
        self.app.focus = "menu"
        self.app.handle_key("s")                                                   # and 's' works from the menu too
        self.assertFalse(self.store.dirty)
        self.assertIn("[ Nothing to save ]", self.screen())

    def test_plural_and_narrow_terminals(self):
        self.stage_one()
        self.app.handle_key("down")
        self.app.handle_key("+")
        self.assertIn("2 changes not saved yet", self.screen())
        self.app.size = (80, 24)
        text = self.screen()
        self.assertIn("Press Ctrl+S or s to save", text)
        self.assertTrue(all(len(line) <= 81 for line in text.splitlines()))

    def test_save_button_and_pages_respond_to_clicks(self):
        from prompt_toolkit.mouse_events import MouseEvent, MouseEventType, MouseButton, MouseModifier
        self.stage_one()
        frags = self.app.render()
        save = next(f for f in frags if f[1].strip() == "[ Save changes ]")
        self.assertEqual(len(save), 3, "the save button needs a mouse handler")
        up = MouseEvent(position=None, event_type=MouseEventType.MOUSE_UP, button=MouseButton.LEFT, modifiers=frozenset())
        down = MouseEvent(position=None, event_type=MouseEventType.MOUSE_DOWN, button=MouseButton.LEFT, modifiers=frozenset())
        save[2](down)
        self.assertTrue(self.store.dirty, "only a full click (button released) should save")
        save[2](up)
        self.assertFalse(self.store.dirty)
        page = next(f for f in self.app.render() if f[1].strip() == "Assistant Monitor")
        page[2](up)
        self.assertEqual(schema.PAGES[self.app.page], "Assistant Monitor")
        row = next(f for f in self.app.render() if "Disk warning" in f[1])
        row[2](up)                                                                 # first click selects
        self.assertEqual(self.app.current_row().label, "Disk warning")
        self.assertIsNone(self.app.popup)
        row = next(f for f in self.app.render() if "Disk warning" in f[1])
        stale_save = next(f for f in self.app.render() if f[1].strip() in ("[ Nothing to save ]", "[ Save changes ]"))
        row[2](up)                                                                 # second click edits
        self.assertEqual(self.app.popup.mode, "input")
        before = self.app.popup
        stale_save[2](up)                                                          # a click that arrives while the box is open
        self.assertIs(self.app.popup, before, "clicks behind an open box are ignored")
        self.assertTrue(all(len(f) == 2 for f in self.app.render()), "no click targets are offered behind an open box")


class KeyboardReachesSave(TuiBase):
    def test_save_is_the_last_menu_entry_and_enter_saves(self):
        self.goto("Hyprland")
        self.select("Border thickness")
        self.app.handle_key("+")
        self.app.handle_key("left")                           # back to the menu
        self.assertEqual(self.app.focus, "menu")
        presses = 0
        while self.app.menu_index != len(schema.PAGES) and presses < 10:
            self.app.handle_key("down")
            presses += 1
        self.assertEqual(self.app.menu_index, len(schema.PAGES), "Down must eventually reach Save")
        text = self.screen()
        self.assertIn("›[ Save changes ]", text)
        self.assertIn("Press Enter to save the 1 pending change.", text)
        self.assertEqual(schema.PAGES[self.app.page], "Hyprdots", "the page on the right stays put")
        self.app.handle_key("enter")
        self.assertFalse(self.store.dirty)
        self.assertEqual(Store(self.dir).get(schema.BY_ID["hyprland.border_size"])[0], 3)

    def test_nothing_to_save_is_explained_and_navigation_wraps(self):
        self.app.focus = "menu"
        self.app.handle_key("up")                              # up from the first page wraps to Save
        self.assertEqual(self.app.menu_index, len(schema.PAGES))
        self.assertIn("Nothing to save yet", self.screen())
        self.app.handle_key("enter")
        self.assertIn("Nothing to save.", self.screen())
        self.app.handle_key("down")                            # and down from Save wraps to the first page
        self.assertEqual((self.app.menu_index, self.app.page), (0, 0))
        self.app.handle_key("tab")
        self.assertEqual(self.app.focus, "list")               # Tab/Enter on a page still enter its list

    def test_down_past_the_last_setting_reaches_save(self):
        self.goto("Hyprland")
        self.select("Border thickness")
        self.app.handle_key("+")
        for _ in range(40):                                   # keep pressing Down inside the list
            if self.app.menu_index == len(schema.PAGES):
                break
            self.app.handle_key("down")
        self.assertEqual((self.app.focus, self.app.menu_index), ("menu", len(schema.PAGES)))
        self.assertIn("Press Enter to save", self.screen())
        self.app.handle_key("enter")
        self.assertFalse(self.store.dirty)

    def test_save_button_mouse_and_keyboard_agree(self):
        self.app.click_page(2)
        self.assertEqual((self.app.menu_index, self.app.page), (2, 2))
        self.app.handle_key("up")
        self.app.handle_key("down")
        self.assertEqual(self.app.page, 2)


class PageClarity(TuiBase):
    def test_monitor_page_is_clearly_the_assistants_not_displays(self):
        self.assertNotIn("Monitor", [p for p in schema.PAGES if p == "Monitor"])
        self.assertIn("Assistant Monitor", self.screen())
        self.goto("Assistant Monitor")
        text = " ".join(self.screen().split())
        self.assertIn("This is NOT about your screens", text)
        self.assertIn("assistant's background health monitor", text)

    def test_every_page_has_an_intro_that_cannot_be_selected(self):
        for index, page in enumerate(schema.PAGES):
            self.app.page, self.app.focus = index, "list"
            rows = self.app.rows()
            self.assertEqual(rows[0].kind, "note", page)
            self.assertTrue(all(not r.selectable for r in rows if r.kind == "note"))
            self.assertTrue(self.app.current_row().selectable)


class Models(TuiBase):
    def setUp(self):
        super().setUp()
        for patcher in (mock.patch.object(models, "installed", return_value=([{"name": "gpt-oss:20b", "size_gb": 13.0},
                                                                              {"name": "qwen3:14b", "size_gb": 9.3},
                                                                              {"name": "codellama:13b", "size_gb": 7.4}], "")),
                        mock.patch.object(models, "capabilities", side_effect=lambda n: {"tools", "thinking"} if "qwen" in n or "gpt" in n else {"completion"}),
                        mock.patch.object(models, "vram_mib", return_value=16000)):
            patcher.start()
            self.addCleanup(patcher.stop)

    def wait_for_caps(self):
        for _ in range(100):
            if len(self.app.caps) >= 3:
                return
            time.sleep(0.02)

    def test_chat_model_picker_shows_models_and_warns_about_tool_support(self):
        self.select("Chat model")
        self.app.handle_key("enter")
        self.wait_for_caps()
        text = self.screen()
        for name in ("gpt-oss:20b", "qwen3:14b", "codellama:13b", "Download another model"):
            self.assertIn(name, text)
        self.assertIn("(current)", text)
        self.assertIn("Download qwen3:8b", text)                                # not installed, so offered
        self.assertNotIn("Download gpt-oss:20b", text)                          # installed, so not offered again
        names = [v for v, _, _ in self.app.popup.items]
        self.app.popup.index = names.index("codellama:13b")
        self.assertIn("WARNING: no tools support", self.screen())
        self.app.popup.index = names.index("gpt-oss:20b")
        self.assertIn("Abilities: thinking, tools.", self.screen())
        self.app.handle_key("enter")
        self.assertEqual(self.store.get(schema.BY_ID["assistant.model"]), ("gpt-oss:20b", "changed"))

    def test_vision_picker_can_turn_images_off(self):
        self.select("Vision model")
        self.app.handle_key("enter")
        self.assertEqual(self.app.popup.items[0][0], "none")
        self.app.handle_key("enter")
        self.assertEqual(self.store.get(schema.BY_ID["assistant.vision_model"]), ("", "changed"))
        self.assertIn("None (image features off)", self.screen())

    def test_same_as_chat_model_is_offered_first_when_the_chat_model_can_see(self):
        models.capabilities.side_effect = lambda n: {"tools", "vision", "thinking"} if n == "qwen3:14b" else {"tools"}
        self.select("Vision model")
        self.app.handle_key("enter")
        self.assertEqual([v for v, _, _ in self.app.popup.items][:2], ["same", "none"])
        self.assertIn("Same as chat model (qwen3:14b)", self.screen())
        self.assertIn("one model does both", self.screen())
        self.app.handle_key("enter")
        self.assertEqual(self.store.get(schema.BY_ID["assistant.vision_model"]), ("same", "changed"))
        self.assertIn("Same as chat model", self.screen())
        self.app.handle_key("c-s")
        self.assertIn('vision_model = "same"', (self.dir / "user_settings.local.toml").read_text())

    def test_same_as_chat_model_warns_when_the_chat_model_cannot_see(self):
        models.capabilities.side_effect = lambda n: {"tools", "thinking"}
        self.select("Vision model")
        self.app.handle_key("enter")
        items = [v for v, _, _ in self.app.popup.items]
        self.assertEqual(items[:2], ["none", "same"])                       # not the first choice
        self.app.popup.index = items.index("same")
        self.assertIn("WARNING: qwen3:14b does not report vision support", self.screen())

    def test_unreachable_ollama_is_explained_in_the_picker(self):
        models.installed.return_value = ([], "Ollama is not reachable at http://x. Start it with: systemctl start ollama")
        self.select("Chat model")
        self.app.handle_key("enter")
        self.assertIn("Ollama is not reachable", self.screen())

    def test_download_flow_stages_the_model_on_success(self):
        def fake_pull(name, on_progress, cancel):
            on_progress("pulling", 0.4)
            return True, f"{name} is ready"
        with mock.patch.object(models, "pull", side_effect=fake_pull):
            self.select("Chat model")
            self.app.handle_key("enter")
            self.app.popup.index = len(self.app.popup.items) - 1
            self.app.handle_key("enter")                           # Download another model...
            type_text(self.app, "qwen3:8b")
            self.app.handle_key("enter")
            for _ in range(200):
                if self.app.popup is None:
                    break
                time.sleep(0.01)
        self.assertEqual(self.store.get(schema.BY_ID["assistant.model"]), ("qwen3:8b", "changed"))
        self.assertIn("Ctrl+S", self.app.notice)

    def test_failed_and_cancelled_downloads_change_nothing(self):
        with mock.patch.object(models, "pull", return_value=(False, "Download failed: no space left")):
            self.select("Chat model")
            self.app.handle_key("enter")
            self.app.start_pull(schema.BY_ID["assistant.model"], "huge:70b")
            for _ in range(200):
                if self.app.popup is None:
                    break
                time.sleep(0.01)
        self.assertFalse(self.store.dirty)
        self.assertTrue(self.app.notice_error)
        self.assertIn("no space left", self.screen())


class OtherPages(TuiBase):
    def test_calendar_add_mask_and_remove(self):
        self.goto("Calendar")
        self.app.handle_key("enter")                              # + Add a calendar...
        type_text(self.app, "Home")
        self.app.handle_key("enter")
        type_text(self.app, "ftp://bad")
        self.app.handle_key("enter")
        self.assertIn("must start with https", self.screen())
        self.app.handle_key("c-u")
        type_text(self.app, "https://calendar.example.com/ical/private-abc123secret/basic.ics")
        self.app.handle_key("enter")
        self.assertEqual(self.store.calendar_sources(), ["Home|https://calendar.example.com/ical/private-abc123secret/basic.ics"])
        shown = self.screen()
        self.assertIn("Home", shown)
        self.assertIn("calendar.example.com  (link hidden)", shown)
        self.assertNotIn("abc123secret", shown)
        self.app.handle_key("c-s")
        self.app.handle_key("up")                                   # back to the source row
        self.app.handle_key("tab"); self.app.handle_key("tab")
        self.app.sel[self.app.page] = 0
        self.app.handle_key("enter")
        self.assertEqual([v for v, _, _ in self.app.popup.items], ["rename", "link", "remove"])
        self.app.handle_key("down"); self.app.handle_key("down"); self.app.handle_key("enter")
        self.app.handle_key("y", "y")
        self.assertEqual(self.store.calendar_sources(), [])

    def test_startup_apps_toggle(self):
        self.goto("Hyprdots")
        self.select("Discord")
        self.assertIn("on", self.app.current_row().value)
        self.app.handle_key(" ")
        self.assertEqual(self.store.disabled_startup(), ["discord"])
        self.assertEqual(self.app.current_row().value, "off")
        self.app.handle_key(" ")
        self.assertEqual(self.store.disabled_startup(), [])
        self.app.handle_key(" ")
        self.app.handle_key("r")
        self.assertEqual(self.store.disabled_startup(), [])

    def test_default_app_choices_include_installed_programs_only(self):
        tui.shutil.which.side_effect = lambda name: "/usr/bin/" + name if name in ("kitty", "foot") else None
        self.goto("Hyprdots")
        self.select("Terminal")
        self.app.handle_key("enter")
        labels = [label for _, label, _ in self.app.popup.items]
        self.assertTrue(any("ghostty" in l and "default" in l for l in labels))       # the default is always offered
        self.assertTrue(any(l.startswith("kitty") for l in labels))
        self.assertFalse(any(l.startswith("alacritty") for l in labels))
        self.assertIn("Something else...", labels)

    def test_assistant_switch_and_raw_files(self):
        tui.shutil.which.return_value = "/usr/bin/ollama"
        self.select("Assistant")                                       # the on/off row on the Assistant page
        self.app.handle_key("enter")
        self.assertTrue((self.state / "disabled").exists())
        self.assertIn("turned OFF", self.screen())
        self.app.handle_key("enter")
        self.assertFalse((self.state / "disabled").exists())
        tui.shutil.which.return_value = None
        (self.state / "disabled").touch()
        self.app.handle_key("enter")
        self.assertEqual(self.app.popup.title, "Assistant not installed")      # cannot turn on without ollama
        self.assertTrue((self.state / "disabled").exists())
        self.app.handle_key("x")
        self.goto("Hyprdots")
        self.select("Open the raw settings files...")
        self.app.handle_key("enter")
        self.assertEqual(self.app.exit_action, "edit")

    def test_calendar_and_assistant_changes_do_not_touch_hyprland_files(self):
        self.goto("Calendar")
        self.app.handle_key("enter")
        type_text(self.app, "X"); self.app.handle_key("enter")
        type_text(self.app, "/home/me/cal"); self.app.handle_key("enter")
        self.app.handle_key("c-s")
        self.assertIn("X|/home/me/cal", (self.dir / "user_settings.local.toml").read_text())


class RealTerminalLoop(TuiBase):
    def test_runs_in_prompt_toolkit_with_scripted_keys(self):
        from prompt_toolkit.input import create_pipe_input
        from prompt_toolkit.output import DummyOutput
        outcome = []
        with create_pipe_input() as pipe:
            # down (Monitor page), Tab (into the list), Space (toggle "Pause while gaming"), Ctrl+S, q
            pipe.send_text("\x1b[B\t \x13q")
            worker = threading.Thread(target=lambda: outcome.append(tui.run(self.store, input=pipe, output=DummyOutput())), daemon=True)
            worker.start()
            worker.join(15)                      # a regression must fail the test, never hang it
            if worker.is_alive():
                pipe.send_text("n")              # would answer an unsaved-changes prompt
                worker.join(5)
                self.fail("the app did not exit after the scripted keys")
        self.assertEqual(outcome, ["quit"])
        self.assertEqual(Store(self.dir).get(schema.BY_ID["monitor.defer_when_busy"]), (False, "yours"))


if __name__ == "__main__":
    unittest.main()
