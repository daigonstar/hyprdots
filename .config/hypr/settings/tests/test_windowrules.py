import re
import tempfile
import unittest
from pathlib import Path

import _paths  # noqa: F401
from hyprsettings import windowrules as w

SHIPPED = _paths.HYPR / "window_rules.lua"


class Lua(unittest.TestCase):
    def test_reads_the_shipped_file(self):
        rules = w.read_shipped(SHIPPED)
        self.assertGreaterEqual(len(rules), 3)
        for rule in rules:
            self.assertIn("name", rule)
            self.assertIn("match", rule)
        self.assertEqual(len({r["name"] for r in rules}), len(rules))

    def test_refuses_anything_but_data(self):
        with self.assertRaises(ValueError):
            w.parse_table('return { os.execute("x") }')
        with self.assertRaises(ValueError):
            w.parse_table("nothing here")

    def test_local_file_round_trip(self):
        local = {"off": ["b", "a"], "rules": [{"name": 'we"ird', "match": {"class": "^a\\.b$"}, "size": [800, 600], "float": True, "opacity": "0.9"}]}
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "x.lua"
            w.write_local(path, local)
            got = w.read_local(path)
        self.assertEqual(got["rules"], local["rules"])
        self.assertEqual(sorted(got["off"]), ["a", "b"])

    def test_missing_or_broken_local_file(self):
        self.assertEqual(w.read_local("/nonexistent/x.lua"), {"off": [], "rules": []})
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "x.lua"
            path.write_text("return { broken")
            self.assertEqual(w.read_local(path), {"off": [], "rules": []})


class List(unittest.TestCase):
    SHIPPED = [{"name": "a", "match": {"class": "^a$"}, "float": True}, {"name": "b", "match": {"class": "^b$"}, "pin": True}]

    def test_kinds_and_switches(self):
        local = {"off": ["b"], "rules": [{"name": "a", "match": {"class": "^a$"}, "workspace": "2"}, {"name": "mine", "match": {"class": "^m$"}, "pin": True}]}
        got = {e["rule"]["name"]: (e["kind"], e["on"]) for e in w.entries(self.SHIPPED, local)}
        self.assertEqual(got, {"a": ("changed", True), "b": ("builtin", False), "mine": ("yours", True)})

    def test_remove_puts_a_built_in_back(self):
        local = {"off": ["a"], "rules": [{"name": "a", "match": {}, "pin": True}]}
        w.remove_rule(local, "a")
        self.assertEqual(local, {"off": [], "rules": []})

    def test_set_on_and_put_rule(self):
        local = {"off": [], "rules": []}
        w.set_on(local, "x", False)
        w.set_on(local, "x", False)
        self.assertEqual(local["off"], ["x"])
        w.set_on(local, "x", True)
        self.assertEqual(local["off"], [])
        w.put_rule(local, {"name": "r", "pin": True})
        w.put_rule(local, {"name": "r", "pin": False})
        self.assertEqual(local["rules"], [{"name": "r", "pin": False}])

    def test_unique_names(self):
        self.assertEqual(w.unique_name("com.Foo Bar", set()), "com-foo-bar")
        self.assertEqual(w.unique_name("foo", {"foo", "foo-2"}), "foo-3")


class Patterns(unittest.TestCase):
    def test_round_trips(self):
        for kind, text in (("exact", "vesktop"), ("exact", "com.heroicgameslauncher.hgl"), ("contains", "Picture in"), ("starts", "steam_app_")):
            self.assertEqual(w.from_pattern(w.to_pattern(kind, text)), (kind, text), text)

    def test_shipped_styles(self):
        self.assertEqual(w.from_pattern("^(vesktop)$"), ("exact", "vesktop"))
        self.assertEqual(w.from_pattern("^steam_app_.*$"), ("starts", "steam_app_"))
        self.assertEqual(w.from_pattern("^(discord|WebCord|Vesktop)$"), ("pattern", "^(discord|WebCord|Vesktop)$"))

    def test_exact_really_matches_only_that(self):
        self.assertTrue(re.fullmatch(w.to_pattern("exact", "a.b"), "a.b"))
        self.assertFalse(re.fullmatch(w.to_pattern("exact", "a.b"), "axb"))


class Choices(unittest.TestCase):
    def test_every_shipped_rule_survives_the_wizard_unchanged(self):
        for rule in w.read_shipped(SHIPPED):
            back = w.rule_from_choices(w.choices_from_rule(rule))
            self.assertEqual(self.normal(back), self.normal(rule), rule["name"])

    def normal(self, rule):
        return {**rule, "match": {k: w.from_pattern(v) if k in ("class", "title") else v for k, v in rule["match"].items()}}

    def test_unknown_options_and_formula_sizes_are_kept(self):
        rule = {"name": "x", "match": {"class": "^x$", "xwayland": True}, "float": True, "size": ["(monitor_w*0.8)", "100"], "tag": "+a"}
        back = w.rule_from_choices(w.choices_from_rule(rule))
        self.assertEqual(back["size"], ["(monitor_w*0.8)", "100"])
        self.assertEqual(back["tag"], "+a")
        self.assertTrue(back["match"]["xwayland"])

    def test_new_rule_from_choices(self):
        c = w.choices_from_rule()
        self.assertFalse(w.has_target(c))
        c.update(name="n", **{"class": "mpv"}, workspace="3", silent=True, shape="float", center=True, width=800, height=600, pin=True, opacity=90, awake=True)
        self.assertTrue(w.has_target(c))
        self.assertTrue(w.has_effect(c))
        self.assertEqual(w.rule_from_choices(c), {"name": "n", "match": {"class": "^mpv$"}, "workspace": "3 silent", "float": True, "center": True,
                                                  "size": [800, 600], "pin": True, "opacity": "0.9", "idle_inhibit": "always"})

    def test_float_only_options_need_float(self):
        c = w.choices_from_rule()
        c.update(name="n", **{"class": "mpv"}, shape="fullscreen", center=True, pin=True, width=5, height=5)
        self.assertEqual(set(w.rule_from_choices(c)), {"name", "match", "fullscreen"})

    def test_no_effect_is_not_a_rule(self):
        c = w.choices_from_rule()
        c.update(name="n", **{"class": "mpv"})
        self.assertFalse(w.has_effect(c))


class Words(unittest.TestCase):
    def test_plain_descriptions(self):
        self.assertEqual(w.describe_match({"class": "^(vesktop)$"}), "Vesktop")
        self.assertEqual(w.describe_match({"class": "^(discord|WebCord|Vesktop)$"}), "Discord, WebCord or Vesktop")
        self.assertEqual(w.describe_match({"class": "^com.heroicgameslauncher.hgl$"}), "Heroicgameslauncher")
        self.assertEqual(w.describe_match({"class": "^(com.bitwarden.desktop)$"}), "Bitwarden")
        self.assertEqual(w.app_name("com.anthropic.Claude"), "Claude")
        self.assertEqual(w.describe_match({"class": "^steam_app_.*$"}), "Apps starting with steam_app_")
        self.assertEqual(w.describe_match({"title": "^Lutris$"}), "Windows titled Lutris")
        self.assertEqual(w.summary({"workspace": "2 silent"}), "Opens on workspace 2 without switching to it")
        self.assertEqual(w.summary({"workspace": "special:magic silent"}), "Opens on scratch workspace magic without switching to it")
        self.assertIn("floats at 800 × 600, centred", w.describe_effects({"float": True, "size": [800, 600], "center": True}))
        self.assertEqual(w.describe_effects({"opacity": "0.9"}), ["90% opaque"])


if __name__ == "__main__":
    unittest.main()
