import importlib.util
import json
import os
import shutil
import subprocess
import tempfile
import threading
import unittest
import unittest.mock
import http.server
from pathlib import Path

import _paths
from hyprsettings import account, displays, lockscreen, models, overrides, schema, tomledit
from hyprsettings.store import RESET, Store

LUA = shutil.which("lua5.4") or shutil.which("lua")


class TomlEdit(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.dir, True)
        self.path = self.dir / "local.toml"

    def test_edits_keep_everything_else(self):
        self.path.write_text('# mine\n[calendar]\nsources = [\n    "A|http://x",\n    "B|http://y"\n]\n\n[assistant]\nmodel = "old"  # why\n\n[monitor]\ndisk_warn = 80\n')
        tomledit.set_value(self.path, "assistant", "model", "qwen3:14b")
        tomledit.set_value(self.path, "assistant", "accent", "35")
        tomledit.set_value(self.path, "hyprland", "gaps_in", 8)
        text = self.path.read_text()
        self.assertIn("# mine", text)
        self.assertIn('"A|http://x"', text)
        self.assertIn("disk_warn = 80", text)
        data = tomledit.read(self.path)
        self.assertEqual(data["assistant"], {"model": "qwen3:14b", "accent": "35"})
        self.assertEqual(data["hyprland"], {"gaps_in": 8})
        self.assertEqual(data["calendar"]["sources"], ["A|http://x", "B|http://y"])
        self.assertIn("\n\n[monitor]", text)  # blank line before the next section survives

    def test_multiline_array_replaced_whole(self):
        self.path.write_text('[calendar]\nsources = [\n    "A|1",\n    "B|2"\n]\nother = 1\n')
        tomledit.set_value(self.path, "calendar", "sources", ["Only|1"])
        self.assertEqual(tomledit.read(self.path)["calendar"], {"sources": ["Only|1"], "other": 1})

    def test_brackets_inside_strings_do_not_confuse_it(self):
        self.path.write_text('[a]\nlist = ["x]", "y[" ]\nnext = 1\n')
        tomledit.set_value(self.path, "a", "list", ["z"])
        self.assertEqual(tomledit.read(self.path)["a"], {"list": ["z"], "next": 1})

    def test_unset_drops_empty_section_and_reports_missing(self):
        self.path.write_text('[assistant]\nmodel = "x"\n\n[monitor]\ndisk_warn = 80\n')
        self.assertTrue(tomledit.unset(self.path, "assistant", "model"))
        self.assertNotIn("assistant", tomledit.read(self.path))
        self.assertFalse(tomledit.unset(self.path, "assistant", "model"))
        self.assertFalse(tomledit.unset(self.dir / "missing.toml", "a", "b"))

    def test_value_formats_round_trip(self):
        values = {"s": 'quote " and \\ slash', "b": True, "i": -3, "f": 0.25, "l": ["a", "b", "c"], "e": [], "u": "ünï"}
        for key, value in values.items():
            tomledit.set_value(self.path, "t", key, value)
        self.assertEqual(tomledit.read(self.path)["t"], values)

    def test_backup_permissions_and_no_partial_writes(self):
        tomledit.set_value(self.path, "a", "k", 1)
        tomledit.set_value(self.path, "a", "k", 2)
        self.assertEqual(tomledit.read(self.path.with_name("local.toml.bak"))["a"]["k"], 1)
        self.assertEqual(oct(self.path.stat().st_mode & 0o777), "0o600")
        self.assertEqual([p.name for p in self.dir.iterdir() if p.name.endswith(".tmp")], [])

    def test_refuses_to_write_invalid_toml(self):
        self.path.write_text("[a]\nk = 1\n")
        with self.assertRaises(tomledit.TomlError):
            tomledit.set_value(self.path, "a b\n[x", "k", 1)  # a section name that would corrupt the file
        with self.assertRaises(tomledit.TomlError):
            tomledit.format_value(object())
        self.assertEqual(tomledit.read(self.path), {"a": {"k": 1}})


class Schema(unittest.TestCase):
    def test_integrity(self):
        ids = [s.id for s in schema.SETTINGS]
        self.assertEqual(len(ids), len(set(ids)))
        for s in schema.SETTINGS:
            self.assertIn(s.page, schema.PAGES)
            self.assertTrue(s.label and s.help, s.id)
            self.assertIn(s.kind, {"choice", "bool", "int", "float", "text", "list", "model", "vision_model", "mode_model", "palette", "font"}, s.id)
            if s.kind in ("int", "float"):
                self.assertTrue(s.lo is not None and s.hi is not None and s.lo <= s.default <= s.hi, s.id)
            if s.kind == "choice" and s.id not in schema.INSTALLED_CHOICES:
                self.assertIn(s.default, [v for v, _ in s.choices] if not s.allow_custom else [v for v, _ in s.choices] + [s.default], s.id)
            if s.section == "hyprland":
                self.assertTrue(s.lua, s.id)

    def test_every_assistant_and_monitor_key_exists_in_the_shared_file(self):
        shared = tomledit.read(_paths.HYPR / "user_settings.toml")
        for s in schema.SETTINGS:
            if s.section in ("assistant", "monitor"):
                self.assertIn(s.key, shared[s.section], f"{s.id} is not a real setting: the app would write a key nothing reads")

    def test_hyprland_defaults_match_the_tracked_config(self):
        window = (_paths.HYPR / "window.lua").read_text()
        for key, value in (("gaps_in", 5), ("gaps_out", 10), ("border_size", 2), ("rounding", 18)):
            self.assertIn(f"{key} = {value}", window, key)
        self.assertIn('layout = "dwindle"', window)
        self.assertIn('kb_layout = "us"', (_paths.HYPR / "input.lua").read_text())


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.dir = _paths.scratch_hypr_dir()
        self.addCleanup(shutil.rmtree, self.dir, True)
        self.store = Store(self.dir)

    def s(self, sid):
        return schema.BY_ID[sid]

    def test_mode_models_default_to_the_chat_model(self):
        for mode in ("external", "gaming"):
            s = self.s(f"assistant_modes.{mode}")
            self.assertEqual((s.kind, self.store.get(s)), ("mode_model", ("", "default")))
            self.assertIn(mode, tomledit.read(_paths.HYPR / "user_settings.toml")["assistant_modes"])
        gaming = self.s("assistant_modes.gaming")
        self.store.stage(gaming, "qwen3:4b")
        self.store.save()
        self.assertEqual(tomledit.read(self.dir / "user_settings.local.toml")["assistant_modes"], {"gaming": "qwen3:4b"})
        self.store.stage(gaming, "same")                                    # "Same as chat model" in the picker
        self.assertEqual(self.store.get(gaming), ("", "default"))

    def test_default_then_yours_then_reset(self):
        model = self.s("assistant.model")
        self.assertEqual(self.store.get(model)[1], "default")
        self.store.stage(model, "qwen3:8b")
        self.assertEqual(self.store.get(model), ("qwen3:8b", "changed"))
        self.assertEqual(self.store.save(), ["next time the assistant starts"])
        self.assertEqual(Store(self.dir).get(model), ("qwen3:8b", "yours"))
        self.store.reset(model)
        self.store.save()
        self.assertEqual(Store(self.dir).get(model)[1], "default")
        self.assertNotIn("assistant", tomledit.read(self.dir / "user_settings.local.toml"))

    def test_setting_the_default_again_removes_the_override(self):
        gaps = self.s("hyprland.gaps_in")
        self.store.stage(gaps, 9)
        self.store.save()
        self.store.stage(gaps, 5)
        self.assertIs(self.store.staged[gaps.id], RESET)

    def test_shared_file_defaults_are_what_the_user_sees(self):
        shared = (self.dir / "user_settings.toml").read_text().replace('num_ctx = 16384', 'num_ctx = 8192')
        (self.dir / "user_settings.toml").write_text(shared)
        self.assertEqual(Store(self.dir).get(self.s("assistant.num_ctx")), (8192, "default"))

    def test_validation(self):
        gaps, ctx = self.s("hyprland.gaps_in"), self.s("assistant.num_ctx")
        for bad in ("abc", "-1", "51", "2.5", ""):
            with self.assertRaises(ValueError, msg=bad):
                self.store.stage(gaps, bad)
        self.store.stage(gaps, "12")
        self.assertEqual(self.store.get(gaps)[0], 12)
        with self.assertRaises(ValueError):
            self.store.stage(self.s("assistant.model"), "  ")
        with self.assertRaises(ValueError):
            self.store.stage(self.s("hyprdots.terminal"), "")
        with self.assertRaises(ValueError):
            self.store.stage(self.s("hyprland.layout"), "bogus")
        with self.assertRaises(ValueError):
            self.store.stage(self.s("hyprland.sensitivity"), "5")
        self.store.stage(ctx, "12000")                       # custom values are allowed for context
        self.assertEqual(self.store.get(ctx)[0], 12000)
        self.store.stage(self.s("assistant.vision_model"), " SAME ")
        self.assertEqual(self.store.get(self.s("assistant.vision_model"))[0], "same")
        self.store.stage(self.s("assistant.vision_model"), "none")
        self.assertEqual(self.store.get(self.s("assistant.vision_model"))[0], "")
        self.store.stage(self.s("monitor.units_ignore"), "a*, b ,, c")
        self.assertEqual(self.store.get(self.s("monitor.units_ignore"))[0], ["a*", "b", "c"])

    def test_bad_values_in_the_file_fall_back_with_a_warning(self):
        (self.dir / "user_settings.local.toml").write_text('[hyprland]\ngaps_in = "wide"\n[assistant]\nshow_thinking = 3\n')
        store = Store(self.dir)
        self.assertEqual(store.get(self.s("hyprland.gaps_in")), (5, "default"))
        self.assertTrue(any("gaps_in" in w for w in store.warnings))

    def test_unreadable_file_is_reported_not_fatal(self):
        (self.dir / "user_settings.local.toml").write_text("[broken\n")
        store = Store(self.dir)
        self.assertTrue(store.warnings)
        self.assertEqual(store.get(self.s("hyprland.gaps_in"))[1], "default")

    def test_startup_apps_and_calendar(self):
        with unittest.mock.patch("shutil.which", return_value="/usr/bin/vesktop"):
            self.assertIn("vesktop", [a["id"] for a in self.store.startup_apps()])
        self.store.set_startup("vesktop", False)
        self.store.set_startup("solaar", False)
        self.store.set_calendar_sources(["Home|https://example.com/x.ics"])
        self.store.save()
        again = Store(self.dir)
        self.assertEqual(again.disabled_startup(), ["solaar", "vesktop"])
        self.assertEqual(again.calendar_sources(), ["Home|https://example.com/x.ics"])
        again.set_startup("vesktop", True)
        again.set_startup("solaar", True)
        again.save()
        self.assertEqual(Store(self.dir).disabled_startup(), [])

    def test_your_own_startup_apps_can_be_added_and_removed(self):
        with unittest.mock.patch("shutil.which", side_effect=lambda p: f"/usr/bin/{p}" if p in ("signal-desktop", "steam") else None):
            self.store.add_startup("Signal", "signal-desktop --start-in-tray")
            self.store.add_startup("Steam", "steam -silent")
            for label, cmd, problem in (("", "steam", "name"), ("Steam", "steam", "already"), ("Vesktop", "steam", "already"),
                                        ("A|B", "steam", "|"), ("Nope", "not-a-real-program", "cannot find"), ("Empty", "  ", "command")):
                with self.assertRaises(ValueError) as e:
                    self.store.add_startup(label, cmd)
                self.assertIn(problem, str(e.exception))
        self.store.save()
        again = Store(self.dir)
        self.assertEqual(again.custom_startup(), [{"label": "Signal", "cmd": "signal-desktop --start-in-tray"},
                                                  {"label": "Steam", "cmd": "steam -silent"}])
        self.assertIn('{ label = "Signal", cmd = "signal-desktop --start-in-tray" }', again.overrides_path.read_text())
        again.remove_startup(0)
        again.remove_startup(9)  # out of range: nothing happens
        again.save()
        self.assertEqual([a["label"] for a in Store(self.dir).custom_startup()], ["Steam"])
        last = Store(self.dir)
        last.remove_startup(0)
        last.save()
        self.assertEqual(Store(self.dir).custom_startup(), [])
        self.assertNotIn("startup_custom", (self.dir / "user_settings.local.toml").read_text())
        self.assertIn("M.startup_extra = {}", (self.dir / "user_overrides.lua").read_text())

    def test_a_startup_app_by_path_is_accepted(self):
        script = self.dir / "start-me.sh"
        script.write_text("#!/bin/sh\n")
        script.chmod(0o755)
        self.store.add_startup("Mine", f"{script} --now")
        self.assertEqual(self.store.custom_startup()[0]["cmd"], f"{script} --now")

    def test_overrides_file_only_contains_real_changes(self):
        self.store.stage(self.s("hyprland.gaps_in"), 9)
        self.store.stage(self.s("hyprland.blur"), False)
        self.store.stage(self.s("hyprdots.terminal"), "kitty")
        self.store.stage(self.s("assistant.model"), "qwen3:8b")      # not a Hyprland setting
        self.store.save()
        lua = (self.dir / "user_overrides.lua").read_text()
        self.assertIn("gaps_in = 9", lua)
        self.assertIn("enabled = false", lua)
        self.assertIn('terminal = "kitty"', lua)
        self.assertNotIn("qwen", lua)
        self.assertNotIn("rounding", lua)


SAFE_RIG = r"""
-- Stands in for Hyprland: its require records a failure and returns an empty table, without the path a real load returns
local dir = arg[1]
package.path = dir .. "/?.lua"
hooks, binds = {}, 0
hl = {
    on = function(_, fn) hooks[#hooks + 1] = fn end,
    bind = function() binds = binds + 1 end,
    unbind = function() binds = 0 end,
    dsp = {exec_cmd = function() end, exit = function() end},
    notification = {create = function(o) print("NOTICE " .. o.text) end},
}
local lua_require = require
require = function(name)
    local ok, value, where = pcall(lua_require, name)
    if not ok and tostring(value):find("not found") then error(value, 2) end
    if not ok then return {} end
    return value, where
end
local safe = lua_require("safe_config")
safe.load("keybinds")
local has, optional = pcall(require, "not_there")
print("optional", has)
print("value", require("settings").value)
safe.finish()
for _, fn in ipairs(hooks) do fn() end
print("binds", binds)
"""


@unittest.skipUnless(LUA, "needs lua")
class SafeConfig(unittest.TestCase):
    """safe_config.lua falls back to the last copy that worked. Tested for real in a nested Hyprland when it was written."""
    GOOD = {"keybinds": 'hl.bind("a")\nhl.bind("b")\n', "settings": "return {value = 'good'}\n"}

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)
        shutil.copy(Path(_paths.__file__).parents[2] / "safe_config.lua", self.dir)
        (self.dir / "rig.lua").write_text(SAFE_RIG)
        self.write(self.GOOD)

    def write(self, files):
        for name, text in files.items():
            (self.dir / f"{name}.lua").write_text(text)

    def run_rig(self):
        env = {"HOME": str(self.dir), "XDG_STATE_HOME": str(self.dir / "state"), "PATH": "/usr/bin:/bin"}
        done = subprocess.run([LUA, str(self.dir / "rig.lua"), str(self.dir)], capture_output=True, text=True, env=env, timeout=10)
        self.assertEqual(done.returncode, 0, done.stderr)
        return done.stdout

    def saved(self, name):
        return (self.dir / "state/hyprdots/last_good" / f"{name}.lua").read_text()

    def test_clean_load_is_saved_and_a_missing_optional_file_is_no_problem(self):
        out = self.run_rig()
        self.assertIn("binds\t2", out)
        self.assertNotIn("NOTICE", out)
        self.assertEqual(self.saved("keybinds"), self.GOOD["keybinds"])

    def test_a_broken_file_uses_its_copy_without_overwriting_it(self):
        self.run_rig()
        self.write({"settings": "oops("})
        out = self.run_rig()
        self.assertIn("value\tgood", out)
        self.assertIn("NOTICE Safe mode: settings", out)
        self.assertEqual(self.saved("settings"), self.GOOD["settings"])

    def test_keybinds_failing_part_way_are_not_doubled(self):
        self.run_rig()
        self.write({"keybinds": 'hl.bind("a")\nerror("boom")\n'})
        self.assertIn("binds\t2", self.run_rig())

    def test_keybinds_with_no_copy_still_give_a_way_out(self):
        self.write({"keybinds": "oops("})
        self.assertIn("binds\t2", self.run_rig())  # the two emergency keys


FAKE_PASSWD = """#!/bin/sh
echo "Changing password for you."
printf "Current password: "; read -r current
[ "$current" = old ] || { echo "passwd: Authentication token manipulation error"; exit 10; }
printf "New password: "; read -r new
[ "$new" = short ] && { echo "BAD PASSWORD: The password is shorter than 8 characters"; exit 10; }
printf "Retype new password: "; read -r again
[ "$new" = "$again" ] || exit 10
echo "$new" > "$PASSWD_RESULT"
echo "passwd: password updated successfully"
"""


class Account(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)
        fake = self.dir / "passwd"
        fake.write_text(FAKE_PASSWD)
        fake.chmod(0o755)
        env = {"PATH": f"{self.dir}:{os.environ['PATH']}", "PASSWD_RESULT": str(self.dir / "changed"), "HOME": str(self.dir)}
        patcher = unittest.mock.patch.dict(os.environ, env)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_password_changes_with_the_right_current_one(self):
        self.assertEqual(account.change_password("old", "new secret")[0], True)
        self.assertEqual((self.dir / "changed").read_text(), "new secret\n")

    def test_a_wrong_current_password_says_so_and_never_repeats_it(self):
        worked, message = account.change_password("wrong secret", "new secret")
        self.assertFalse(worked)
        self.assertIn("current password", message)
        self.assertNotIn("secret", message)

    def test_a_refused_new_password_gives_the_reason(self):
        worked, message = account.change_password("old", "short")
        self.assertFalse(worked)
        self.assertIn("shorter than 8", message)

    def test_a_stuck_passwd_does_not_hang_the_page(self):
        (self.dir / "passwd").write_text("#!/bin/sh\nsleep 30\n")
        self.assertFalse(account.change_password("old", "new", timeout=0.5)[0])

    @unittest.skipUnless(importlib.util.find_spec("gi"), "needs PyGObject")
    def test_picture_is_cropped_to_a_square(self):
        import gi
        gi.require_version("GdkPixbuf", "2.0")
        from gi.repository import GdkPixbuf
        wide = GdkPixbuf.Pixbuf.new(GdkPixbuf.Colorspace.RGB, False, 8, 400, 100)
        wide.savev(str(self.dir / "wide.png"), "png", [], [])
        with unittest.mock.patch.object(account, "_accounts", return_value="") as told:
            account.set_picture(self.dir / "wide.png")
        saved = GdkPixbuf.Pixbuf.new_from_file(str(self.dir / ".face"))
        self.assertEqual((saved.get_width(), saved.get_height()), (256, 256))
        told.assert_called_once_with("SetIconFile", str(self.dir / ".face"))

    @unittest.skipUnless(importlib.util.find_spec("gi"), "needs PyGObject")
    def test_a_file_that_is_not_a_picture_is_refused_and_keeps_the_old_one(self):
        (self.dir / "notes.txt").write_text("not a picture")
        (self.dir / ".face").write_text("the old one")
        with self.assertRaises(ValueError):
            account.set_picture(self.dir / "notes.txt")
        self.assertEqual((self.dir / ".face").read_text(), "the old one")

    def test_a_name_cannot_break_the_account_file(self):
        with self.assertRaises(ValueError):
            account.set_real_name("Robb, the second")

    def test_lock_screen_shows_the_picture_only_when_there_is_one(self):
        o = dict(lockscreen.DEFAULTS, show_user=True)
        self.assertNotIn("image {", lockscreen.render(o))
        self.assertIn("path = /home/x/.face", lockscreen.render({**o, "picture": "/home/x/.face"}))


class DataSafety(unittest.TestCase):
    def test_nan_and_inf_are_not_numbers(self):
        store = Store(_paths.scratch_hypr_dir())
        self.addCleanup(shutil.rmtree, store.dir, True)
        setting = next(s for s in schema.SETTINGS if s.kind == "float" and s.lo is None) if any(s.kind == "float" and s.lo is None for s in schema.SETTINGS) else next(s for s in schema.SETTINGS if s.kind == "float")
        for text in ("nan", "inf", "-inf"):
            with self.assertRaises(ValueError):
                store.coerce(setting, text)

    def test_no_answer_from_hyprland_leaves_the_saved_screens_alone(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "monitors.lua"
            path.write_text("your screens\n")
            displays.write(path, [])
            self.assertEqual(path.read_text(), "your screens\n")


class ConfigProblem(unittest.TestCase):
    def test_reports_the_error_and_stays_quiet_when_it_cannot_check(self):
        fake = subprocess.CompletedProcess([], 1, "noise\n======== Config parsing result:\n\nkeybinds.lua:1: bad\n", "")
        with unittest.mock.patch("subprocess.run", return_value=fake):
            self.assertEqual(overrides.config_problem(), "keybinds.lua:1: bad")
        with unittest.mock.patch("subprocess.run", side_effect=FileNotFoundError):
            self.assertEqual(overrides.config_problem(), "")


class Overrides(unittest.TestCase):
    def test_lua_values_are_escaped(self):
        self.assertEqual(overrides.lua_value('a"b\\c\nd'), '"a\\"b\\\\c\\nd"')
        self.assertEqual(overrides.lua_value(True), "true")
        self.assertEqual(overrides.lua_value(0.5), "0.5")
        with self.assertRaises(TypeError):
            overrides.lua_value(None)

    @unittest.skipUnless(LUA, "lua is not installed")
    def run_lua(self, code):
        return subprocess.run([LUA, "-e", code], capture_output=True, text=True, timeout=20)

    @unittest.skipUnless(LUA, "lua is not installed")
    def test_generated_file_is_valid_lua_and_applies(self):
        text = overrides.render([(("general", "gaps_in"), 7), (("decoration", "blur", "enabled"), False),
                                 (("input", "kb_layout"), 'we"ird')], {"terminal": "foo bar"}, ["vesktop", "a b"])
        path = Path(tempfile.mkdtemp()) / "user_overrides.lua"
        self.addCleanup(shutil.rmtree, path.parent, True)
        overrides.write(path, text)
        code = f"""
        local seen
        hl = {{ config = function(t) seen = t end }}
        local m = dofile("{path}")
        m.apply()
        assert(seen.general.gaps_in == 7 and seen.decoration.blur.enabled == false and seen.input.kb_layout == 'we"ird')
        assert(m.apps.terminal == "foo bar" and m.startup_disabled["vesktop"] and m.startup_disabled["a b"])
        """
        result = self.run_lua(code)
        self.assertEqual(result.returncode, 0, result.stderr)

    @unittest.skipUnless(LUA, "lua is not installed")
    def test_empty_overrides_do_nothing(self):
        path = Path(tempfile.mkdtemp()) / "o.lua"
        self.addCleanup(shutil.rmtree, path.parent, True)
        overrides.write(path, overrides.render([], {}, []))
        self.assertEqual(self.run_lua(f'hl = {{ config = function() error("must not be called") end }}; dofile("{path}").apply()').returncode, 0)

    def harness(self, overrides_text, script):
        """Runs a real tracked Lua file against a stub of Hyprland's API."""
        d = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, d, True)
        if overrides_text is not None:
            (d / "user_overrides.lua").write_text(overrides_text)
        stub = f"""
        package.path = "{d}/?.lua;" .. package.path
        local function proxy(name) return setmetatable({{}}, {{ __call = function(_, ...) return {{ name = name, args = {{...}} }} end,
                                                              __index = function(_, k) return proxy(name .. "." .. k) end }}) end
        binds, execs = {{}}, {{}}
        hl = {{ dsp = proxy("dsp"), bind = function(keys, action) binds[keys] = action end,
               exec_cmd = function(c) execs[#execs + 1] = c end, on = function(_, cb) cb() end }}
        {script}
        """
        return subprocess.run([LUA, "-e", stub], capture_output=True, text=True, timeout=20)

    @unittest.skipUnless(LUA, "lua is not installed")
    def test_keybinds_use_overrides_and_fall_back(self):
        keybinds = _paths.HYPR / "keybinds.lua"
        check = f'dofile("{keybinds}"); print(binds["SUPER + T"].args[1], binds["SUPER + B"].args[1], binds["SUPER + E"].args[1])'
        plain = self.harness(None, check)
        self.assertEqual(plain.stdout.split(), ["ghostty", "zen-browser", "thunar"], plain.stderr)
        custom = self.harness(overrides.render([], {"terminal": "kitty", "browser": "firefox"}, []), check)
        self.assertEqual(custom.stdout.split(), ["kitty", "firefox", "thunar"], custom.stderr)
        broken = self.harness("this is not lua (", check)
        self.assertEqual(broken.stdout.split(), ["ghostty", "zen-browser", "thunar"], broken.stderr)

    @unittest.skipUnless(LUA, "lua is not installed")
    def test_autostart_skips_disabled_apps_only(self):
        autostart = _paths.HYPR / "autostart.lua"
        script = f'dofile("{autostart}"); print(table.concat(execs, "\\n"))'
        everything = self.harness(None, script).stdout
        for app in ("vesktop", "solaar", "coolercontrol", "desktop-services.sh login"):
            self.assertIn(app, everything)
        fewer = self.harness(overrides.render([], {}, ["vesktop", "solaar"]), script)
        self.assertEqual(fewer.returncode, 0, fewer.stderr)
        self.assertNotIn("vesktop", fewer.stdout)
        self.assertNotIn("solaar", fewer.stdout)
        for kept in ("coolercontrol", "desktop-services.sh login"):
            self.assertIn(kept, fewer.stdout)

    @unittest.skipUnless(LUA, "lua is not installed")
    def test_autostart_starts_your_own_apps_too(self):
        autostart = _paths.HYPR / "autostart.lua"
        script = f'dofile("{autostart}"); print(table.concat(execs, "\\n"))'
        mine = [{"label": "Signal", "cmd": "signal-desktop --start-in-tray"}, {"label": 'We"ird', "cmd": "echo 'a b'"}]
        got = self.harness(overrides.render([], {}, ["vesktop"], None, mine), script)
        self.assertEqual(got.returncode, 0, got.stderr)
        self.assertIn("after-tray.sh signal-desktop --start-in-tray", got.stdout)
        self.assertIn("after-tray.sh echo 'a b'", got.stdout)
        self.assertNotIn("vesktop", got.stdout)
        self.assertIn("coolercontrol", got.stdout)
        plain = self.harness(overrides.render([], {}, []), script)  # none of your own: just the usual list
        self.assertEqual(plain.returncode, 0, plain.stderr)
        self.assertNotIn("signal-desktop", plain.stdout)

    def test_desktop_parts_come_back_after_a_crash(self):
        units = _paths.HYPR / "systemd"
        for name in ("waybar.service.d/hyprdots.conf", "swaync.service.d/hyprdots.conf", "hypridle.service.d/hyprdots.conf",
                     "hyprdots-tray.service", "hyprdots-usb.service"):
            text = (units / name).read_text()
            self.assertIn("Restart=on-failure", text, name)
            self.assertIn("KillMode=process", text, name)  # apps opened from it must survive it restarting
            self.assertIn("OnFailure=hyprdots-part-failed@", text, name)
            self.assertLess(text.index("StartLimitBurst"), text.index("[Service]"), name)  # ignored in [Service]
        for name in ("waybar", "swaync", "hypridle"):
            self.assertIn("ExecStart=\nExecStart=", (units / f"{name}.service.d/hyprdots.conf").read_text())
        # Hyprland waits for its own session target at startup; a second one holds up every login
        self.assertFalse((units / "hyprdots-session.target").exists())
        script = (_paths.HYPR / "scripts/desktop-services.sh").read_text()
        self.assertLess(script.index("wait_for_session\n        stop_strays"), script.index("systemctl --user restart $(units_of)"))
        for part in ("waybar", "swaync", "hypridle", "hyprdots-tray", "hyprdots-usb", "hyprdots-tablet"):
            self.assertIn(part, script)

    def test_startup_markers_match_the_lua_file(self):
        apps = overrides.startup_apps(_paths.HYPR / "autostart.lua")
        self.assertGreaterEqual(len(apps), 5)
        self.assertTrue(all(a["id"] and a["label"] and a["cmd"] for a in apps))
        self.assertEqual(overrides.startup_apps(Path("/nonexistent")), [])


class _FakeOllama(http.server.BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def _send(self, body, code=200):
        data = body if isinstance(body, bytes) else json.dumps(body).encode()
        self.send_response(code)
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        self._send({"models": [{"name": "b:1", "size": 2_000_000_000}, {"name": "A:2", "size": 5_300_000_000}]})

    def do_POST(self):
        payload = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        if self.path == "/api/show":
            self._send({"capabilities": ["completion", "tools", "vision"]} if payload["model"] == "A:2" else {})
        elif self.path == "/api/pull":
            if payload["model"] == "bad":
                self._send(b'{"error": "pull model manifest: file does not exist"}\n')
            else:
                self._send(b'{"status": "pulling"}\n{"status": "pulling", "total": 100, "completed": 50}\n{"status": "success"}\n')


class Models(unittest.TestCase):
    def setUp(self):
        self.server = http.server.HTTPServer(("127.0.0.1", 0), _FakeOllama)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)
        patcher = unittest.mock.patch.dict("os.environ", {"OLLAMA_HOST": f"http://127.0.0.1:{self.server.server_port}"})
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_installed_capabilities_and_pull(self):
        listing, err = models.installed()
        self.assertEqual((err, [m["name"] for m in listing], listing[0]["size_gb"]), ("", ["A:2", "b:1"], 5.3))
        self.assertEqual(models.capabilities("A:2"), {"completion", "tools", "vision"})
        self.assertEqual(models.capabilities("b:1"), set())
        seen = []
        ok, msg = models.pull("x", lambda status, frac: seen.append((status, frac)), threading.Event())
        self.assertTrue(ok)
        self.assertIn(("pulling", 0.5), seen)
        ok, msg = models.pull("bad", lambda *a: None, threading.Event())
        self.assertFalse(ok)
        self.assertIn("does not exist", msg)
        cancelled = threading.Event()
        cancelled.set()
        self.assertEqual(models.pull("x", lambda *a: None, cancelled), (False, "Cancelled"))

    def test_unreachable_ollama_is_explained(self):
        with unittest.mock.patch.dict("os.environ", {"OLLAMA_HOST": "http://127.0.0.1:9"}):
            listing, err = models.installed()
        self.assertEqual(listing, [])
        self.assertIn("not reachable", err)

    def test_tier_recommendation(self):
        self.assertEqual([models.recommend_tier(v) for v in (0, 6000, 8000, 16000)], ["light", "light", "balanced", "full"])


import unittest.mock  # noqa: E402

class IdleSleepLock(unittest.TestCase):
    def test_sleep_waits_for_the_lock_when_locking_before_sleep(self):
        from hyprsettings import idle
        self.assertIn("inhibit_sleep = 3", idle.render(5, 0, 0, True))
        self.assertNotIn("inhibit_sleep = 3", idle.render(5, 0, 0, False))  # it would hold off sleep for a lock that never comes


if __name__ == "__main__":
    unittest.main()
