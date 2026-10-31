import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import _paths
from hyprsettings import design, displays, gtktheme, theme_parts, tui
from test_tui import TuiBase

MODES = ["2560x1440@164.84Hz", "2560x1440@59.95Hz", "1920x1080@60.00Hz", "1920x1080@74.97Hz"]


def mon(name, x, w=2560, h=1440, **kw):
    return {"name": name, "description": "d", "width": w, "height": h, "refresh": 60.0, "x": x, "y": 0, "scale": 1.0,
            "transform": 0, "vrr": False, "disabled": False, "modes": MODES, **kw}


class DisplaysTest(unittest.TestCase):
    def test_modes_and_placement(self):
        self.assertEqual(displays.resolutions(MODES), [(2560, 1440), (1920, 1080)])
        self.assertEqual(displays.refresh_rates(MODES, (1920, 1080)), [74.97, 60.0])
        a, b = mon("A", 0), mon("B", 0, 1920, 1080)
        self.assertEqual(displays.place_beside(b, a, "right"), (2560, 0))
        self.assertEqual(displays.place_beside(b, a, "left"), (-1920, 0))
        self.assertEqual(displays.place_beside(b, a, "above"), (0, -1080))

    def test_scale_and_rotation_change_logical_size(self):
        self.assertEqual(displays.logical_size(mon("A", 0, scale=2.0)), (1280, 720))
        self.assertEqual(displays.logical_size(mon("A", 0, transform=1)), (1440, 2560))

    def test_growing_a_screen_pushes_its_neighbour(self):
        a, b = mon("A", 0, scale=1.0), mon("B", 1280, 1920, 1080)
        a["scale"] = 1.0
        displays.resolve_overlaps([a, b], "A")
        self.assertEqual(b["x"], 2560)
        self.assertIsNone(displays.overlaps([a, b]))

    def test_overlap_is_reported_and_positions_normalised(self):
        a, b = mon("A", 0), mon("B", 100)
        self.assertIn("overlap", displays.overlaps([a, b]))
        a, b = mon("A", -2560), mon("B", 0)
        displays.normalize_positions([a, b])
        self.assertEqual((a["x"], b["x"]), (0, 2560))

    def test_lua_output(self):
        text = displays.render([mon("DP-1", 0, refresh=164.84, vrr=True, transform=1), mon("DP-2", 2560, disabled=True)])
        self.assertIn('hl.monitor({ output = "DP-1", mode = "2560x1440@164.84", position = "0x0", scale = 1, transform = 1, vrr = 1 })', text)
        self.assertIn('hl.monitor({ output = "DP-2", disabled = true })', text)

    def test_write_backs_up_a_hand_written_file(self):
        d = Path(tempfile.mkdtemp())
        f = d / "monitors.lua"
        f.write_text("-- mine\nhl.monitor({})\n")
        displays.write(f, [mon("A", 0)])
        self.assertIn("-- mine", (d / "monitors.lua.bak").read_text())
        displays.write(f, [mon("A", 0)])                       # our own file is not backed up again
        self.assertIn("-- mine", (d / "monitors.lua.bak").read_text())

    def test_write_keeps_unplugged_screens(self):
        f = Path(tempfile.mkdtemp()) / "monitors.lua"
        displays.write(f, [mon("DP-1", 0), mon("HDMI-A-1", 2560)])
        displays.write(f, [mon("DP-1", 0, refresh=144.0)])     # HDMI unplugged when saving again
        text = f.read_text()
        self.assertIn('output = "HDMI-A-1", mode = "2560x1440@60", position = "2560x0"', text)
        self.assertIn('output = "DP-1", mode = "2560x1440@144"', text)
        self.assertEqual(text.count('output = "DP-1"'), 1)

    def test_laptop_screen_is_never_saved_off(self):
        f = Path(tempfile.mkdtemp()) / "monitors.lua"
        displays.write(f, [mon("eDP-1", 0, disabled=True), mon("DP-1", 2560)])
        self.assertNotIn("eDP-1", f.read_text())
        self.assertIn('output = "DP-1"', f.read_text())

    def test_snap_position(self):
        a, b = mon("A", 0), mon("B", 2560, w=1920, h=1080)
        ms = [a, b]
        self.assertEqual(displays.snap_position(b, ms, -1900, 30), (-1920, 0))      # left, tops lined up
        self.assertEqual(displays.snap_position(b, ms, 300, 1500), (320, 1440))     # below, centred
        self.assertEqual(displays.snap_position(b, ms, 2560, 340), (2560, 360))     # right, bottoms lined up
        self.assertEqual(displays.snap_position(b, ms, 2600, 700), (2560, 700))     # right, wherever it was dropped
        x, y = displays.snap_position(b, ms, 500, 300)                              # dropped on top: moved clear
        self.assertIsNone(displays.overlaps([a, dict(b, x=x, y=y)]))
        self.assertEqual(displays.snap_position(a, [a], 900, 900), (0, 0))
        x, y = displays.snap_position(b, ms, -1900, 1400)                           # dropped near A's bottom corner
        self.assertGreaterEqual(min(y + 1080, 1440) - max(y, 0), 270)              # still shares a quarter of an edge

    def test_plan_change_keeps_one_screen_on(self):
        _after, problem = displays.plan_change([mon("DP-1", 0)], "DP-1", disabled=True)
        self.assertIn("stay on", problem)
        after, problem = displays.plan_change([mon("A", 0), mon("B", 2560)], "A", scale=0.5)
        self.assertIsNone(problem)
        self.assertGreaterEqual(after[1]["x"], 5120)              # B pushed right of the now bigger A


class GtkTest(unittest.TestCase):
    def setUp(self):
        self.home = tempfile.mkdtemp()
        p = mock.patch.dict(os.environ, {"XDG_CONFIG_HOME": self.home})
        p.start()
        self.addCleanup(p.stop)
        patch = mock.patch.object(gtktheme.shutil, "which", return_value=None)
        patch.start()
        self.addCleanup(patch.stop)

    def _write_gtk(self, **o):
        colours = {"accent": "#3388ff", "secondary": "#88aacc", "fg": "#eeeeee", "bg": "#111111", "soft": "#88aacc"}
        with mock.patch.object(theme_parts.theme, "colors", return_value=colours), \
                mock.patch.object(theme_parts.gtktheme, "theme_dir", side_effect=lambda n: Path("/x") if n == "adw-gtk3" else None), \
                mock.patch.object(theme_parts, "flatpak_can_read_gtk"), \
                mock.patch.object(theme_parts.gtktheme, "apply", return_value=(True, "")) as apply:
            theme_parts.write_gtk({**design.DEFAULTS, "icons": "Papirus", **o})
        return apply

    def test_theme_colours_apps(self):
        css4 = Path(self.home) / "gtk-4.0" / "gtk.css"
        css4.parent.mkdir(parents=True)
        css4.write_text("/* mine */\nwindow { padding: 1px; }\n")
        apply = self._write_gtk()
        for _ in range(2):                                         # written again on the next wallpaper: still one block
            apply = self._write_gtk()
        text = css4.read_text()
        self.assertIn("window { padding: 1px; }", text)            # your own CSS is kept
        self.assertEqual(text.count(theme_parts.GTK_MARK), 1)
        self.assertIn("@define-color accent_bg_color #3388ff;", text)
        self.assertIn("--window-bg-color: #111111;", text)
        self.assertNotIn("--", (Path(self.home) / "gtk-3.0" / "gtk.css").read_text().replace("/* hyprdots", ""))
        changes = apply.call_args.kwargs
        self.assertEqual((changes["theme"], changes["dark"], changes["icons"]), ("adw-gtk3-dark", True, "Papirus"))
        self.assertFalse(changes["link_gtk4"])

    def test_flatpak_apps_may_read_the_colours_once(self):
        shown = mock.Mock(stdout="[Context]\nfilesystems=xdg-config/gtk-3.0:ro;\n")
        with mock.patch.object(theme_parts.shutil, "which", return_value="/usr/bin/flatpak"), \
                mock.patch.object(theme_parts.subprocess, "run", return_value=shown) as run:
            theme_parts.flatpak_can_read_gtk()
        self.assertEqual(run.call_args.args[0], ["flatpak", "override", "--user", "--filesystem=xdg-config/gtk-4.0:ro"])

    def test_turning_theme_colours_off(self):
        self._write_gtk()
        apply = self._write_gtk(gtk_colours=False, gtk_theme="Material")
        self.assertFalse((Path(self.home) / "gtk-3.0" / "gtk.css").exists())   # only our block was there
        self.assertEqual(apply.call_args.kwargs["theme"], "Material")

    def test_ini_keeps_other_keys_and_comments(self):
        ini = Path(self.home) / "gtk-3.0" / "settings.ini"
        ini.parent.mkdir()
        ini.write_text("# mine\n[Settings]\ngtk-theme-name=Old\ngtk-error-bell=1\n[Other]\nx=1\n")
        gtktheme.write_ini("3.0", {"gtk-theme-name": "New", "gtk-font-name": "Sans 10"})
        text = ini.read_text()
        self.assertIn("# mine", text)
        self.assertIn("gtk-error-bell=1", text)
        self.assertIn("gtk-theme-name=New", text)
        self.assertLess(text.index("gtk-font-name=Sans 10"), text.index("[Other]"))
        self.assertEqual(gtktheme.read_ini("3.0")["gtk-theme-name"], "New")

    def test_apply_writes_gtk3_and_gtk4(self):
        ok, _ = gtktheme.apply(theme="Adwaita-dark", dark=True)
        self.assertTrue(ok)
        for v in ("3.0", "4.0"):
            ini = gtktheme.read_ini(v)
            self.assertEqual(ini["gtk-theme-name"], "Adwaita-dark")
            self.assertEqual(ini["gtk-application-prefer-dark-theme"], "1")

    def test_font_parts(self):
        self.assertEqual(gtktheme.font_parts("Adwaita Sans 11"), ("Adwaita Sans", "11"))
        self.assertEqual(gtktheme.font_parts("Mono"), ("Mono", "11"))


class PagesTest(TuiBase):
    def test_displays_page_lists_screens_and_change_applies_all(self):
        self.app._mons = [mon("DP-1", 0), mon("DP-2", 2560, 1920, 1080)]
        self.goto("Displays")
        text = self.app.render_plain()
        self.assertIn("DP-1", text)
        self.assertIn("1920x1080 @ 60 Hz", text)
        with mock.patch.object(displays, "apply", return_value=(True, "")) as apply, \
                mock.patch.object(displays, "read", side_effect=lambda: self.app._mons):
            self.app.display_menu("DP-2")
            self.app.handle_key("down"); self.app.handle_key("down"); self.app.handle_key("enter")   # Position
            self.app.handle_key("down"); self.app.handle_key("enter")                                # Left of DP-1
            self.assertEqual(self.app.popup.mode, "confirm")
            self.assertEqual(len(apply.call_args[0][0]), 2)                                         # every screen at once
            self.app.handle_key("n", "n")
            self.assertFalse(self.app.popup)
            self.app._revert.cancel()

    def test_unanswered_change_is_reverted(self):
        self.app._mons = [mon("DP-1", 0), mon("DP-2", 2560)]
        with mock.patch.object(displays, "apply", return_value=(True, "")) as apply, \
                mock.patch.object(displays, "read", side_effect=lambda: self.app._mons), \
                mock.patch.object(tui.threading, "Timer") as timer:
            self.app._display_change("DP-2", scale=2.0)
            self.assertEqual(self.app.popup.mode, "confirm")
            timer.call_args[0][1]()                                                                  # the 10 s run out
            self.assertIsNone(self.app.popup)
            self.assertEqual(apply.call_count, 2)
            self.assertIn("restored", self.app.notice)

    def test_theme_page_apps_start_from_what_gtk_uses_now(self):
        now = {"theme": "adw-gtk3-dark", "icons": "Papirus", "cursor": "Future-cursors", "cursor_size": "32",
               "font": "Inter 10", "dark": True}
        with mock.patch.object(gtktheme, "current", return_value=now):
            self.app.store.reload()
            self.goto("Theme")
            text = " ".join(f"{r.label} {r.value}" for r in self.app.rows())
            for want in ("Colour apps from the theme", "Papirus", "Future-cursors", "Inter"):
                self.assertIn(want, text)
            store, by_id = self.app.store, tui.BY_ID
            self.assertEqual(store.get(by_id["theme.cursor_size"])[0], 32)
            self.assertEqual(store.get(by_id["theme.app_font_size"])[0], 10)
            self.assertEqual(store.get(by_id["theme.gtk_theme"])[0], "Adwaita")  # the style it sets itself is not "yours"


if __name__ == "__main__":
    unittest.main()
