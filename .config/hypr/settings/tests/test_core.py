import json
import shutil
import subprocess
import tempfile
import threading
import unittest
import http.server
from pathlib import Path

import _paths
from hyprsettings import models, overrides, schema, tomledit
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
            self.assertIn(s.kind, {"choice", "bool", "int", "float", "text", "list", "model", "vision_model"}, s.id)
            if s.kind in ("int", "float"):
                self.assertTrue(s.lo is not None and s.hi is not None and s.lo <= s.default <= s.hi, s.id)
            if s.kind == "choice":
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
        self.assertIn('kb_layout = "gb"', (_paths.HYPR / "input.lua").read_text())


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.dir = _paths.scratch_hypr_dir()
        self.addCleanup(shutil.rmtree, self.dir, True)
        self.store = Store(self.dir)

    def s(self, sid):
        return schema.BY_ID[sid]

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
        self.assertIn("discord", [a["id"] for a in self.store.startup_apps()])
        self.store.set_startup("discord", False)
        self.store.set_startup("solaar", False)
        self.store.set_calendar_sources(["Home|https://example.com/x.ics"])
        self.store.save()
        again = Store(self.dir)
        self.assertEqual(again.disabled_startup(), ["discord", "solaar"])
        self.assertEqual(again.calendar_sources(), ["Home|https://example.com/x.ics"])
        again.set_startup("discord", True)
        again.set_startup("solaar", True)
        again.save()
        self.assertEqual(Store(self.dir).disabled_startup(), [])

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
                                 (("input", "kb_layout"), 'we"ird')], {"terminal": "foo bar"}, ["discord", "a b"])
        path = Path(tempfile.mkdtemp()) / "user_overrides.lua"
        self.addCleanup(shutil.rmtree, path.parent, True)
        overrides.write(path, text)
        code = f"""
        local seen
        hl = {{ config = function(t) seen = t end }}
        local m = dofile("{path}")
        m.apply()
        assert(seen.general.gaps_in == 7 and seen.decoration.blur.enabled == false and seen.input.kb_layout == 'we"ird')
        assert(m.apps.terminal == "foo bar" and m.startup_disabled["discord"] and m.startup_disabled["a b"])
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
        for app in ("discord", "solaar", "coolercontrol", "waybar", "swaync"):
            self.assertIn(app, everything)
        fewer = self.harness(overrides.render([], {}, ["discord", "solaar"]), script)
        self.assertEqual(fewer.returncode, 0, fewer.stderr)
        self.assertNotIn("discord", fewer.stdout)
        self.assertNotIn("solaar", fewer.stdout)
        for kept in ("coolercontrol", "waybar", "swaync", "hypridle"):
            self.assertIn(kept, fewer.stdout)

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

if __name__ == "__main__":
    unittest.main()
