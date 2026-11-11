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
        self.env = {**os.environ, "HOME": str(self.home), "XDG_CACHE_HOME": str(root / "cache"),
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


if __name__ == "__main__":
    unittest.main()
