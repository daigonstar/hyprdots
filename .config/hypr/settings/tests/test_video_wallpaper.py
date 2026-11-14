"""Video wallpapers (hypr/scripts/video-wallpaper.sh): a still frame stands in for the video everywhere, and the video
plays only while that still is the wallpaper. Runs the script with a stand-in player, in a scratch home."""

import os
import shutil
import subprocess
import tempfile
import time
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "video-wallpaper.sh"
PLAYER = "hd-test-player"  # not mpvpaper: the script is told to use this, so a real video wallpaper is never touched


@unittest.skipUnless(shutil.which("ffmpeg"), "needs ffmpeg")
class VideoWallpaper(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.home, self.bin = root / "home", root / "bin"
        (self.home / ".config/rofi").mkdir(parents=True)
        self.bin.mkdir()
        self.log = root / "player.log"
        fake = self.bin / PLAYER
        fake.write_text(f'#!/bin/sh\nprintf "%s\\n" "$@" > "{self.log}"\nsleep 30 & wait\n')
        fake.chmod(0o755)
        self.video = root / "clip one.mp4"  # a space in the name, on purpose
        subprocess.run(["ffmpeg", "-loglevel", "error", "-f", "lavfi", "-i", "testsrc=size=64x36:rate=10",
                        "-t", "2", str(self.video)], check=True)
        self.env = {**os.environ, "HOME": str(self.home), "XDG_CACHE_HOME": str(root / "cache"), "WALLPAPER_HOLDS_DIR": str(root / "holds"),
                    "VIDEO_PLAYER": PLAYER, "PATH": f"{self.bin}:{os.environ['PATH']}"}

    def tearDown(self):
        subprocess.run(["pkill", "-x", PLAYER], capture_output=True)
        self.tmp.cleanup()

    def run_script(self, *args):
        return subprocess.run(["bash", str(SCRIPT), *args], env=self.env, capture_output=True, text=True, timeout=30)

    def running(self):
        return subprocess.run(["pgrep", "-x", PLAYER], capture_output=True).returncode == 0

    def wait_for(self, want, seconds=5.0):
        end = time.monotonic() + seconds
        while time.monotonic() < end and self.running() != want:
            time.sleep(0.1)
        return self.running()

    def test_still_is_made_once_and_kept(self):
        first = self.run_script("still", str(self.video)).stdout.strip()
        self.assertTrue(first.endswith(".png") and Path(first).stat().st_size > 0)
        self.assertEqual(self.run_script("still", str(self.video)).stdout.strip(), first)

    def link(self, name, target):
        path = self.home / ".config/rofi" / name
        if path.is_symlink():
            path.unlink()
        path.symlink_to(target)

    def test_plays_only_while_its_still_is_the_wallpaper(self):
        still = self.run_script("still", str(self.video)).stdout.strip()
        self.link(".current_video", self.video)
        self.link(".current_wallpaper", still)
        self.run_script("sync")
        self.assertTrue(self.wait_for(True))
        args = self.log.read_text().splitlines()
        self.assertEqual(args[-1], str(self.video))
        self.assertIn("-p", args)
        self.assertIn("*", args)
        self.assertIn("no-audio", args[args.index("-o") + 1])

        picture = self.home / "pic.png"
        picture.write_bytes(b"x")
        self.link(".current_wallpaper", picture)  # a picture (or a theme override's wallpaper) took over
        self.run_script("sync")
        self.assertFalse(self.wait_for(False))

        self.link(".current_wallpaper", still)  # back again, as a theme override switching off does
        self.run_script("sync")
        self.assertTrue(self.wait_for(True))
        self.run_script("stop")  # game mode
        self.assertFalse(self.wait_for(False))

    def test_nothing_plays_without_a_video(self):
        self.run_script("sync")
        self.assertFalse(self.running())

    def playing_video(self):
        still = self.run_script("still", str(self.video)).stdout.strip()
        self.link(".current_video", self.video)
        self.link(".current_wallpaper", still)
        self.run_script("sync")
        self.assertTrue(self.wait_for(True))

    def dead_pid(self):
        done = subprocess.Popen(["true"])
        done.wait()
        return str(done.pid)

    def test_a_hold_stops_it_and_keeps_it_stopped(self):
        self.playing_video()
        me = str(os.getpid())  # alive for the whole test
        self.run_script("hold", "model", me)
        self.assertFalse(self.wait_for(False))
        self.run_script("sync")                    # a wallpaper change or login must not bring it back mid-job
        self.assertFalse(self.wait_for(False))
        self.assertEqual(self.run_script("held").stdout.split(), ["model"])
        self.run_script("release", "model", me)
        self.assertTrue(self.wait_for(True))
        self.assertEqual(self.run_script("held").stdout.strip(), "")

    def test_it_comes_back_only_when_every_hold_is_gone(self):
        self.playing_video()
        me = str(os.getpid())
        self.run_script("hold", "model", me)
        self.run_script("hold", "game", me)
        self.run_script("release", "model", me)
        self.assertFalse(self.wait_for(False))
        self.assertEqual(self.run_script("held").stdout.split(), ["game"])
        self.run_script("release", "game")         # without a PID: all of that reason's holds
        self.assertTrue(self.wait_for(True))

    def test_a_holder_that_has_exited_does_not_keep_it_off(self):
        self.playing_video()
        self.run_script("hold", "game", self.dead_pid())   # the game crashed without releasing
        self.run_script("sync")
        self.assertTrue(self.wait_for(True))
        self.assertEqual(self.run_script("held").stdout.strip(), "")

    def test_two_games_two_holds(self):
        self.playing_video()
        me = str(os.getpid())
        self.run_script("hold", "game", me)
        self.run_script("hold", "game", str(os.getppid()))
        self.run_script("release", "game", me)
        self.assertFalse(self.wait_for(False))             # the other game is still open
        self.run_script("release", "game", str(os.getppid()))
        self.assertTrue(self.wait_for(True))

    def test_a_hold_does_not_start_a_video_that_was_not_playing(self):
        me = str(os.getpid())
        self.run_script("hold", "model", me)
        self.run_script("release", "model", me)
        self.assertFalse(self.running())

    def test_bad_arguments_are_refused(self):
        for args in (("hold", "Model!", "1"), ("hold", "model", "abc"), ("release", "../x"), ("release", "model", "1; ls")):
            self.assertEqual(self.run_script(*args).returncode, 2, args)
        holds = Path(self.tmp.name) / "holds"
        self.assertFalse(holds.exists() and any(holds.iterdir()))


class GameHolds(unittest.TestCase):
    """game-autoworkspace.py keeps a video wallpaper stopped while a game window is open."""

    def setUp(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location("game_autoworkspace", SCRIPT.with_name("game-autoworkspace.py"))
        self.g = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.g)
        self.calls = []
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        for name, value in (("wallpaper", lambda *a: self.calls.append(a)), ("pause_wallpaper_for_games", lambda: True),
                            ("process_looks_like_game", lambda pid: True), ("route_to_workspace_3", lambda addr: None),
                            ("get_active_workspace_id", lambda: 1), ("log", lambda msg: None),
                            ("find_client_by_address", lambda addr: {"address": addr, "class": "steam_app_1", "pid": 4242}),
                            ("HOLDS_DIR", str(Path(self.tmp.name) / "holds"))):
            old = getattr(self.g, name)
            setattr(self.g, name, value)
            self.addCleanup(setattr, self.g, name, old)
        self.g.tracked_games.clear()
        self.g.game_pids.clear()

    def test_opening_a_game_holds_and_closing_it_releases(self):
        self.g.handle_open_window("abc,3,steam_app_1,Game")
        self.assertEqual(self.calls, [("hold", "game", "4242")])
        self.g.handle_close_window("abc")
        self.assertEqual(self.calls[1:], [("release", "game", "4242")])

    def test_each_game_has_its_own_hold(self):
        for address, pid in (("a1", 11), ("a2", 22)):
            self.g.find_client_by_address = lambda addr, pid=pid: {"address": addr, "class": "steam_app_1", "pid": pid}
            self.g.handle_open_window(f"{address},3,steam_app_1,Game")
        self.g.handle_close_window("a1")
        self.assertEqual(self.calls, [("hold", "game", "11"), ("hold", "game", "22"), ("release", "game", "11")])

    def test_the_setting_can_turn_it_off(self):
        self.g.pause_wallpaper_for_games = lambda: False
        self.g.handle_open_window("abc,3,steam_app_1,Game")
        self.g.handle_close_window("abc")
        self.assertEqual(self.calls, [])

    def test_a_launcher_window_is_not_a_game(self):
        self.g.handle_open_window("abc,3,steam,Steam")
        self.assertEqual(self.calls, [])

    def test_a_game_the_restarted_daemon_forgot_still_gets_cleaned_up(self):
        holds = Path(self.g.HOLDS_DIR)
        self.g.handle_close_window("zzz")                     # nothing held: no work
        self.assertEqual(self.calls, [])
        holds.mkdir(parents=True)
        (holds / "game.999999").touch()
        self.g.handle_close_window("zzz")
        self.assertEqual(self.calls, [("sync",)])

    def test_the_setting_is_read_from_the_settings_files(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location("game_autoworkspace2", SCRIPT.with_name("game-autoworkspace.py"))
        fresh = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(fresh)
        self.assertIn(fresh.pause_wallpaper_for_games(), (True, False))


if __name__ == "__main__":
    unittest.main()
