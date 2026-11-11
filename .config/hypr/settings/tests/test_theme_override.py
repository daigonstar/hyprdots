"""Theme overrides: a look is laid over your Theme page settings without changing them, and switching back gives
exactly what you had."""

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _paths import scratch_hypr_dir  # noqa: E402

from hyprsettings import barlayout, design, livetheme, theme, theme_override, theme_parts, tomledit  # noqa: E402
from hyprsettings.schema import BY_ID  # noqa: E402
from hyprsettings.store import Store  # noqa: E402

REAL_AFTER_SWITCH = theme_override.after_switch  # the tests below mock it
OWN = {"role_base": "color0", "role_accent": "color9", "bar_style": "bubbles", "bar_font": "Some Font", "base_opacity": 70}


class Layering(unittest.TestCase):
    def test_none_changes_nothing(self):
        o = {**OWN, "override": "none"}
        self.assertEqual(theme_override.apply(o), o)

    def test_unknown_key_counts_as_none(self):
        self.assertEqual(theme_override.active({"override": "nonsense"}), "none")

    def test_xp_lays_its_values_over_yours_and_leaves_yours_alone(self):
        o = {**OWN, "override": "luna"}
        before = dict(o)
        got = theme_override.apply(o)
        self.assertEqual(o, before)  # the input is not changed
        self.assertEqual(got["role_base"], "#ece9d8")
        self.assertEqual(got["bar_style"], "luna")
        self.assertEqual(got["base_opacity"], 100)
        self.assertIn(got["bar_font"], theme_override.TAHOMA_LIKE)

    def test_every_role_has_a_fixed_colour(self):
        values = theme_override.values("luna")
        for key, *_ in design.ROLES:
            self.assertRegex(values[f"role_{key}"], r"^#[0-9a-f]{6}$")

    def test_font_falls_back_to_what_is_installed(self):
        with mock.patch.object(theme_override, "installed_families", return_value={"Liberation Sans", "Adwaita Sans"}):
            self.assertEqual(theme_override.first_installed(theme_override.TAHOMA_LIKE), "Liberation Sans")
        with mock.patch.object(theme_override, "installed_families", return_value=set()):
            self.assertEqual(theme_override.first_installed(theme_override.TAHOMA_LIKE), "Adwaita Sans")


class Parts(unittest.TestCase):
    luna = theme_override.apply({**OWN, "override": "luna"})

    def test_bar_uses_fixed_colours_and_the_taskbar_style(self):
        css = design.render_waybar(self.luna, empty=[])
        self.assertIn("@define-color theme_base #ece9d8;", css)
        self.assertIn("alpha(#245edb, 1)", css)
        self.assertNotIn("@#", css)
        self.assertIn("#custom-start", css)
        self.assertIn(".modules-center", css)  # the empty centre is not drawn

    def test_bar_without_override_is_unchanged_by_it(self):
        css = design.render_waybar({**OWN, "override": "none"}, empty=[])
        self.assertIn("@define-color theme_base @color0;", css)
        self.assertNotIn("custom-start", css)

    def test_resolved_takes_hex_roles_as_they_are(self):
        self.assertEqual(design.resolved(self.luna)["accent"], "#316ac5")

    def test_light_background_keeps_a_dark_accent(self):
        c = theme.colors(self.luna)
        self.assertEqual(c["accent"], "#316ac5")
        self.assertEqual(c["bg"], "#ece9d8")

    def test_gtk_block_carries_the_override_css_and_loses_it_again(self):
        for version in ("3.0", "4.0"):
            css = theme_parts.gtk_css(self.luna, version)
            self.assertTrue(css.rstrip().endswith(theme_parts.GTK_END))
            self.assertIn("Theme override: XP style", css)
            self.assertNotIn("Theme override", theme_parts.gtk_css({**OWN, "override": "none"}, version))

    def test_gtk_block_is_replaced_in_place(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "gtk.css"
            path.write_text("/* mine */\nwindow { color: red; }\n")
            theme_parts._set_block(path, theme_parts.gtk_css(self.luna, "4.0"))
            theme_parts._set_block(path, theme_parts.gtk_css({**OWN, "override": "none"}, "4.0"))
            text = path.read_text()
            self.assertIn("window { color: red; }", text)
            self.assertNotIn("Theme override", text)
            self.assertEqual(text.count(theme_parts.GTK_END), 1)

    def test_hyprland_options_only_while_on(self):
        on = theme_parts.hypr_lua(self.luna)
        self.assertIn("config = {", on)
        self.assertIn("rounding = 8", on)
        self.assertIn("enabled = false", on)
        self.assertNotIn("config =", theme_parts.hypr_lua({**OWN, "override": "none"}))

    def test_lua_values(self):
        self.assertEqual(theme_parts.lua_value(True), "true")
        self.assertEqual(theme_parts.lua_value(1.0), "1.0")
        self.assertEqual(theme_parts.lua_value('a"b'), '"a\\"b"')
        self.assertEqual(theme_parts.lua_value({"a": {"b": 2}}), "{\n        a = {\n            b = 2,\n        },\n    }")

    def test_notifications_and_launcher_get_extra_css(self):
        self.assertIn("#ffffe1", theme_parts.swaync_css(self.luna))
        self.assertEqual(theme_override.extra({**OWN, "override": "none"}, "launcher"), "")

    def test_lock_screen_font(self):
        from hyprsettings import lockscreen
        self.assertIn("$font = Liberation Sans", lockscreen.render({}, font="Liberation Sans"))
        self.assertIn(f"$font = {lockscreen.FONT}", lockscreen.render({}))


class MacStyle(unittest.TestCase):
    mac = theme_override.apply({**OWN, "override": "mac"})

    def test_light_with_fixed_colours_and_a_free_font(self):
        self.assertEqual(self.mac["role_accent"], "#007aff")
        self.assertIn(self.mac["app_font"], theme_override.look_mac.INTER_LIKE)
        self.assertEqual(theme.colors(self.mac)["accent"], "#007aff")

    def test_every_part_gets_its_css(self):
        for part, want in (("bar", "window#waybar.menubar"), ("swaync", "border-radius: 16px"), ("gtk4", "#ff5f57"),
                           ("launcher", "#007aff")):
            self.assertIn(want, theme_override.extra(self.mac, part))
        self.assertNotIn("XP style", theme_parts.gtk_css(self.mac, "4.0"))

    def test_menu_bar_and_dock(self):
        bar = theme_override.bar(self.mac, "L")
        self.assertEqual(bar["position"], "top")
        self.assertEqual(bar["custom/menu-logo"]["format"], "L")
        dock = bar["dock"]
        self.assertEqual(dock["icon-size"], 48)
        self.assertIn("--style grid", dock["launchpad"])

    def test_blur_rules_go_into_theme_lua(self):
        lua = theme_parts.hypr_lua(self.mac)
        self.assertIn("layer_rules = {", lua)
        self.assertIn('namespace = "^(menubar|dock)$"', lua)
        self.assertNotIn("layer_rules", theme_parts.hypr_lua(Parts.luna))

    def test_launcher(self):
        self.assertEqual(theme_override.launcher_style(self.mac), "spotlight")
        self.assertEqual(theme_override.launcher_style(Parts.luna), "startmenu")
        self.assertIsNone(theme_override.launcher_style({"override": "none"}))

    def test_lua_lists(self):
        self.assertEqual(theme_parts.lua_value([1, "a"]), '{\n        1,\n        "a",\n    }')



class GameUI(unittest.TestCase):
    game = theme_override.apply({**OWN, "override": "game"})

    def test_deep_blue_with_white_text_a_gold_pick_and_a_retro_font(self):
        self.assertEqual((self.game["role_base"], self.game["role_base_text"]), ("#121e78", "#ffffff"))
        self.assertEqual(theme.colors(self.game)["accent"], theme_override.look_game.GOLD)
        self.assertIn(self.game["app_font"], theme_override.look_game.PIXEL_LIKE)
        self.assertEqual(self.game["bar_style"], "game")

    def test_every_part_is_a_menu_window(self):
        frame = f"solid {theme_override.look_game.FRAME}"
        for part in ("bar", "swaync", "tray", "launcher", "gtk4"):
            self.assertIn(frame, theme_override.extra(self.game, part), part)
        self.assertIn(frame, theme_parts.tray_css(self.game))
        self.assertNotIn(frame, theme_parts.tray_css(OWN))  # gone again without the look

    def test_picked_items_get_the_pointer_and_it_exists(self):
        self.assertTrue(theme_override.look_game.POINTER.is_file())
        for part in ("launcher", "gtk3", "gtk4"):
            self.assertIn(f"file://{theme_override.look_game.POINTER}", theme_override.extra(self.game, part))

    def test_keeps_your_bar_layout_and_launcher(self):
        self.assertIsNone(theme_override.bar(self.game, "L"))
        self.assertIsNone(theme_override.launcher_style(self.game))
        self.assertNotIn("game", theme_override.BUTTON_LAYOUTS)

    def test_thick_light_window_borders(self):
        hypr = theme_override.hypr_config(self.game)
        self.assertEqual(hypr["general"]["border_size"], 4)
        self.assertIn("eef1fb", hypr["general"]["col"]["active_border"])
        self.assertIn("border_size = 4", theme_parts.hypr_lua(self.game))

    def test_bar_shape(self):
        self.assertIn("all: unset", design.style_css("game"))

    def test_shipped_wallpaper(self):
        self.assertEqual(theme_override.wallpaper("game").name, "wallpaper.jpg")
        self.assertIn(("game", "Game UI"), theme_override.CHOICES)
        self.assertIn("theme.override_wallpaper_game", BY_ID)




class SciFi(unittest.TestCase):
    hud = theme_override.apply({**OWN, "override": "scifi"})

    def test_dark_with_cyan_and_a_technical_font(self):
        self.assertEqual(theme.colors(self.hud)["accent"], theme_override.look_scifi.CYAN)
        self.assertIn(self.hud["app_font"], theme_override.look_scifi.TECH_LIKE)
        self.assertEqual(self.hud["bar_style"], "scifi")

    def test_every_part_gets_bracket_corners_and_something_that_moves(self):
        for part in ("bar", "swaync", "tray", "launcher"):
            css = theme_override.extra(self.hud, part)
            self.assertIn("background-position: left top, left top, right top", css, part)
            self.assertIn("@keyframes hd-boot", css, part)
            self.assertIn("animation: hd-boot", css, part)
        bar = theme_override.extra(self.hud, "bar")
        self.assertIn("animation: hd-pulse 1.8s ease-in-out infinite", bar)  # a small glow: costs nothing measurable
        self.assertNotIn("hd-scan 7s linear infinite", bar)  # looping, the scan line cost about 6% of a core

    def test_keyframes_use_percentages(self):
        # GTK's CSS reads only percentages in @keyframes: "from" and "to" fail the whole rule set after them
        import re
        for look in ("luna", "mac", "game", "scifi"):
            o = {"override": look}
            for part in ("bar", "swaync", "tray", "launcher", "gtk3", "gtk4"):
                self.assertIsNone(re.search(r"^\s*(from|to)\s*\{", theme_override.extra(o, part), re.M), (look, part))

    def test_apps_only_move_once(self):
        css = theme_override.extra(self.hud, "gtk4")
        self.assertIn("animation:", css)
        self.assertNotIn("infinite", css)

    def test_border_gradient_turns(self):
        lua = theme_parts.hypr_lua(self.hud)
        self.assertIn('"rgba(7c4dffff)"', lua)
        self.assertIn('angle = 45', lua)
        self.assertIn('leaf = "borderangle"', lua)
        self.assertIn('style = "loop"', lua)
        self.assertIn("hd_snap = {", lua)
        for other in ("none", "luna", "mac", "game"):  # no other look leaves the border turning
            self.assertNotIn("animations", theme_parts.hypr_lua(theme_override.apply({**OWN, "override": other})))

    def test_shipped_wallpaper_and_choice(self):
        self.assertEqual(theme_override.wallpaper("scifi").name, "wallpaper.jpg")
        self.assertIn(("scifi", "Sci-fi HUD"), theme_override.CHOICES)
        self.assertIn("theme.override_wallpaper_scifi", BY_ID)


class OpenApps(unittest.TestCase):
    """A switch reaching apps that are already open (hyprsettings/livetheme.py, theme_override.restart_idle_thunar)."""
    luna = theme_override.apply({**OWN, "override": "luna"})

    def test_the_look_skips_our_own_windows_in_gtk4_only(self):
        css4 = theme_parts.gtk_css(self.luna, "4.0")
        self.assertIn(f"{livetheme.SKIP} headerbar", css4)
        self.assertIn(":root {", css4)  # the colours stay for every window
        self.assertNotIn(livetheme.SKIP, theme_parts.gtk_css(self.luna, "3.0"))

    def test_selectors(self):
        self.assertEqual(livetheme.prefix("window.background, windowcontrols button > image { a: b; }"),
                         f"{livetheme.SKIP}.background, {livetheme.SKIP} windowcontrols button > image {{ a: b; }}")
        self.assertEqual(livetheme.prefix("/* note */\nrow:not(.x), :root { a: b; }"),
                         f"/* note */\n{livetheme.SKIP} row:not(.x), :root {{ a: b; }}")

    def test_animation_steps_are_left_alone(self):
        css = "@keyframes a {\n    0% { opacity: 0; }\n    100% { opacity: 1; }\n}\nrow { animation: a 1s; }\n"
        got = livetheme.prefix(css)
        self.assertIn("    0% { opacity: 0; }", got)
        self.assertIn(f"{livetheme.SKIP} row {{", got)

    def test_our_apps_read_the_block_as_it_was(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "gtk.css"
            path.write_text("mine { a: b; }\n\n" + theme_parts.gtk_css(self.luna, "4.0"))
            block = livetheme.current_block(path)
        self.assertNotIn("mine", block)
        self.assertNotIn("hyprdots-live", block)
        self.assertIn("headerbar", block)
        self.assertEqual(livetheme.current_block(Path("/nonexistent")), "")

    def test_thunar_is_restarted_only_with_no_window_open(self):
        self.assertTrue(theme_override.thunar_idle([{"class": "zen"}]))
        self.assertFalse(theme_override.thunar_idle([{"class": "thunar"}, {"class": "zen"}]))


class ButtonLayout(unittest.TestCase):
    def test_a_look_remembers_yours_and_none_puts_it_back(self):
        want, state = theme_override.button_layout_plan("mac", "appmenu:close", {})
        self.assertEqual(want, theme_override.look_mac.BUTTON_LAYOUT)
        self.assertEqual(state, {"button_layout": "appmenu:close"})
        want, state = theme_override.button_layout_plan("luna", theme_override.look_mac.BUTTON_LAYOUT, state)
        self.assertEqual(want, theme_override.BUTTON_LAYOUTS["luna"])
        self.assertEqual(state["button_layout"], "appmenu:close")  # still yours, not the first look's
        want, state = theme_override.button_layout_plan("none", theme_override.BUTTON_LAYOUTS["luna"], state)
        self.assertEqual((want, state), ("appmenu:close", {}))

    def test_nothing_to_do(self):
        self.assertEqual(theme_override.button_layout_plan("none", "appmenu:close", {}), (None, {}))


class Bar(unittest.TestCase):
    def test_generated_config_takes_the_override_bar_and_layout_json_is_kept(self):
        with tempfile.TemporaryDirectory() as d:
            way = Path(d) / "waybar"
            way.mkdir()
            (way / "config").write_text('{"position": "top", "modules-left": ["clock"], "clock": {"on-click": "cal"},'
                                        ' "tray": {}, "pulseaudio": {}}')
            layout = '{"modules-left": ["clock"], "modules-center": [], "modules-right": [], "position": "top"}\n'
            (way / "layout.json").write_text(layout)
            bar = theme_override.bar({"override": "luna"}, "X")
            with mock.patch.dict(os.environ, {"XDG_CONFIG_HOME": d}), \
                    mock.patch.object(barlayout, "override_bar", return_value=bar):
                out = json.loads(barlayout.generate().read_text())
            self.assertEqual(out["position"], "bottom")
            self.assertEqual(out["modules-left"], ["group/startbutton", "wlr/taskbar"])
            self.assertEqual(out["group/startbutton"]["modules"], ["custom/start"])  # the group is what gets hover
            self.assertEqual(out["custom/start"]["exec"], theme_override.START_STATE + " 'X'")  # the logo, then start
            self.assertEqual(out["tray"], {"icon-size": 16, "spacing": 6})
            self.assertEqual((way / "layout.json").read_text(), layout)
            mac = theme_override.bar({"override": "mac"}, "L")
            with mock.patch.dict(os.environ, {"XDG_CONFIG_HOME": d}), \
                    mock.patch.object(barlayout, "override_bar", return_value=mac):
                out = json.loads(barlayout.generate().read_text())
            self.assertEqual(out["name"], "menubar")
            self.assertNotIn("dock", out)
            self.assertEqual(out["clock"], {"on-click": "cal", "format": "{:%a %d %b  %H:%M}"})  # your popup kept
            dock = json.loads((way / "config.dock.json").read_text())  # a bar of its own, so it can hide by itself
            self.assertIn("launchpad", dock)
            with mock.patch.dict(os.environ, {"XDG_CONFIG_HOME": d}), \
                    mock.patch.object(barlayout, "override_bar", return_value=None):
                out = json.loads(barlayout.generate().read_text())
            self.assertEqual(out["position"], "top")
            self.assertNotIn("custom/start", out)
            self.assertFalse((way / "config.dock.json").exists())  # no look, no dock


class Wallpaper(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.mine = Path(self.tmp.name) / "mine.png"
        self.mine.write_bytes(b"x")
        self.other = Path(self.tmp.name) / "other.png"
        self.other.write_bytes(b"x")
        self.luna = theme_override.wallpaper("luna")

    def tearDown(self):
        self.tmp.cleanup()

    def test_shipped_wallpaper_exists(self):
        self.assertIsNotNone(self.luna)

    def test_on_remembers_yours_and_off_puts_it_back(self):
        pic, state = theme_override.wallpaper_plan("none", "luna", self.mine, {})
        self.assertEqual(pic, self.luna)
        self.assertEqual(state, {"wallpaper": str(self.mine)})
        pic, state = theme_override.wallpaper_plan("luna", "none", self.luna, state)
        self.assertEqual(pic, self.mine)
        self.assertEqual(state, {})

    def test_one_you_picked_meanwhile_is_kept(self):
        _pic, state = theme_override.wallpaper_plan("none", "luna", self.mine, {})
        pic, state = theme_override.wallpaper_plan("luna", "none", self.other, state)
        self.assertIsNone(pic)
        self.assertEqual(state, {})

    def test_turning_on_twice_keeps_the_first_wallpaper(self):
        _pic, state = theme_override.wallpaper_plan("none", "luna", self.mine, {})
        _pic, state = theme_override.wallpaper_plan("none", "luna", self.luna, state)
        self.assertEqual(state["wallpaper"], str(self.mine))

    def test_your_own_picture_wins_and_is_put_back_from(self):
        pic, state = theme_override.wallpaper_plan("none", "luna", self.mine, {}, chosen=str(self.other))
        self.assertEqual(pic, self.other)
        pic, state = theme_override.wallpaper_plan("luna", "none", self.other, state, chosen=str(self.other))
        self.assertEqual(pic, self.mine)  # your own XP picture counts as the look's, so yours comes back

    def test_a_missing_picture_falls_back_to_the_built_in_one(self):
        self.assertEqual(theme_override.wallpaper("luna", "/nowhere/gone.png"), self.luna)
        self.assertEqual(theme_override.wallpaper("luna", ""), self.luna)
        self.assertIsNone(theme_override.wallpaper("none", str(self.mine)))

    def test_nothing_remembered(self):
        self.assertEqual(theme_override.wallpaper_plan("luna", "none", self.luna, {}), (None, {}))


def gtk_reports(font):
    return {"theme": "Adwaita", "icons": "Adwaita", "cursor": "Adwaita", "cursor_size": "24", "font": font, "dark": True}


class Switching(unittest.TestCase):
    def setUp(self):
        self.state = tempfile.TemporaryDirectory()
        self.env = mock.patch.dict(os.environ, {"XDG_STATE_HOME": self.state.name})
        self.env.start()
        self.addCleanup(self.env.stop)
        self.addCleanup(self.state.cleanup)
        self.dir = scratch_hypr_dir()
        self.store = Store(self.dir)
        for key in ("role_accent", "bar_style", "bar_font"):
            self.store.stage(BY_ID[f"theme.{key}"], OWN[key])
        with mock.patch.object(design, "refresh_all", return_value=[]):
            self.store.save()
        self.saved = tomledit.read(self.store.local_path)
        self.patches = [mock.patch.object(design, "refresh_all", return_value=[]),
                        mock.patch.object(theme_override, "after_switch")]
        self.refresh, self.after = (p.start() for p in self.patches)

    def tearDown(self):
        for p in self.patches:
            p.stop()

    def test_on_and_off_gives_back_exactly_your_settings(self):
        own = design.theme_options(self.store)
        theme_override.switch(self.store, "luna")
        self.assertEqual(design.theme_options(self.store)["bar_style"], "luna")
        self.assertEqual(design.theme_options(self.store, own=True)["bar_style"], "bubbles")
        self.assertEqual(tomledit.read(self.store.local_path)["theme"]["role_accent"], "color9")
        theme_override.switch(self.store, "none")
        self.assertEqual(design.theme_options(self.store), own)
        self.assertEqual(tomledit.read(self.store.local_path), self.saved)
        self.assertEqual([c.args for c in self.after.call_args_list], [("none", "luna", ""), ("luna", "none", "")])

    def test_app_defaults_stay_yours_while_gtk_uses_the_look(self):
        """Settings you never changed default to what GTK uses now; during the override that is the look's font."""
        from hyprsettings import gtktheme
        with mock.patch.object(gtktheme, "current", return_value=gtk_reports("Mine 11")):
            theme_override.switch(Store(self.dir), "luna")
        with mock.patch.object(gtktheme, "current", return_value=gtk_reports("Liberation Sans 10")):
            own = design.theme_options(Store(self.dir), own=True)
            self.assertEqual((own["app_font"], own["app_font_size"]), ("Mine", 11))
            store = Store(self.dir)
            theme_override.switch(store, "none")
            self.assertEqual(design.theme_options(store)["app_font"], "Mine")

    def test_gtk_copy_is_let_go_back_on_none(self):
        theme_override.before_switch(self.store, "none", "luna")
        self.assertIsNotNone(theme_override.gtk_before())
        with mock.patch.object(theme_override, "restart_bar"), mock.patch.object(theme_override, "reload_hyprland"), \
                mock.patch.object(theme_override, "set_wallpaper"), mock.patch.object(barlayout, "generate"), \
                mock.patch.object(theme_override, "restart_idle_thunar") as thunar:
            REAL_AFTER_SWITCH("luna", "none")
        thunar.assert_called_once()
        self.assertIsNone(theme_override.gtk_before())

    def test_unsaved_changes_are_left_staged(self):
        self.store.stage(BY_ID["theme.bar_font_size"], 20)
        theme_override.switch(self.store, "luna")
        self.assertIn("theme.bar_font_size", self.store.staged)
        self.assertNotIn("bar_font_size", tomledit.read(self.store.local_path)["theme"])

    def test_same_look_again_does_not_redo_the_bar_and_wallpaper(self):
        theme_override.switch(self.store, "none")
        self.after.assert_not_called()

    def test_choosing_a_picture_is_saved_as_yours_and_shown_only_while_on(self):
        with mock.patch.object(theme_override, "set_wallpaper") as shown:
            theme_override.choose_wallpaper(self.store, "luna", "/tmp/x.png")
            shown.assert_not_called()  # XP style is off
        self.assertEqual(tomledit.read(self.store.local_path)["theme"]["override_wallpaper_luna"], "/tmp/x.png")
        with mock.patch.object(theme_override, "set_wallpaper"):
            theme_override.choose_wallpaper(self.store, "luna", "")
        self.assertEqual(tomledit.read(self.store.local_path), self.saved)

    def test_switch_passes_your_picture_on(self):
        with mock.patch.object(theme_override, "set_wallpaper"):
            theme_override.choose_wallpaper(self.store, "luna", "/tmp/x.png")
        theme_override.switch(self.store, "luna")
        self.assertEqual(self.after.call_args.args, ("none", "luna", "/tmp/x.png"))

    def test_unknown_look(self):
        with self.assertRaises(ValueError):
            theme_override.switch(self.store, "nope")

    def test_saving_from_the_terminal_app_switches_too(self):
        self.store.stage(BY_ID["theme.override"], "luna")
        self.store.save()
        self.after.assert_called_once_with("none", "luna", "")
        self.store.stage(BY_ID["theme.override"], "none")
        self.store.save()
        self.assertEqual(self.after.call_args.args, ("luna", "none", ""))
        self.assertEqual(tomledit.read(self.store.local_path), self.saved)


if __name__ == "__main__":
    unittest.main()
