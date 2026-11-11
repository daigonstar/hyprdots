"""The wallpaper picker (wallpicker.py): what it finds, how it sorts it into categories, and its thumbnails."""

import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import wallpicker as wp  # noqa: E402


class Finding(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        for name in ("Bliss night.png", "b.JPG", "loop.gif", "Neb video.mp4", "clip.webm", "notes.txt"):
            (self.dir / name).write_bytes(b"x")
        (self.dir / "unfinished.gif").write_bytes(b"")  # an empty download: left out
        (self.dir / "sub").mkdir()
        (self.dir / "sub" / "deep.webp").write_bytes(b"x")

    def tearDown(self):
        self.tmp.cleanup()

    def test_kinds_and_subfolders(self):
        walls = wp.scan(self.dir)
        self.assertEqual({w.path.name: w.kind for w in walls},
                         {"Bliss night.png": "still", "b.JPG": "still", "deep.webp": "still", "loop.gif": "gif",
                          "Neb video.mp4": "video", "clip.webm": "video"})

    def test_categories(self):
        walls = wp.scan(self.dir)
        self.assertEqual(len(wp.in_category(walls, "All")), 6)
        self.assertEqual({w.kind for w in wp.in_category(walls, "Pictures")}, {"still"})
        self.assertEqual({w.kind for w in wp.in_category(walls, "Animated")}, {"gif", "video"})

    def test_search_any_word_order(self):
        walls = wp.scan(self.dir)
        self.assertEqual([w.path.name for w in wp.matching(walls, "night bliss")], ["Bliss night.png"])
        self.assertEqual(len(wp.matching(walls, "")), 6)

    def test_surprise_is_never_the_one_showing(self):
        walls = wp.scan(self.dir)
        for _ in range(20):
            self.assertNotEqual(wp.surprise(walls, walls[0].path).path, walls[0].path)
        self.assertIsNone(wp.surprise([], None))

    def test_clicks(self):
        self.assertFalse(wp.wants_set(1, selected=False))  # see it first
        self.assertTrue(wp.wants_set(1, selected=True))
        self.assertTrue(wp.wants_set(2, selected=False))  # a double-click sets it straight away

    def test_what_it_starts_does_not_get_the_gtk_preload(self):
        with mock.patch.dict("os.environ", {"LD_PRELOAD": "/usr/lib/libgtk4-layer-shell.so", "HOME": "/home/x"}):
            env = wp.clean_env()
        self.assertNotIn("LD_PRELOAD", env)
        self.assertEqual(env["HOME"], "/home/x")

    def test_apply_goes_through_wallpaper_sh(self):
        cmd = wp.apply_command(wp.Wall(self.dir / "loop.gif", "gif"))
        self.assertEqual(cmd[-2:], ["--apply", str(self.dir / "loop.gif")])
        self.assertTrue(cmd[cmd.index("--apply") - 1].endswith("rofi/wallpaper/wallpaper.sh"))


class Current(unittest.TestCase):
    def test_a_playing_video_counts_as_the_video(self):
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            cache = d / "cache"
            stills = cache / "video-wallpapers"
            stills.mkdir(parents=True)
            video = d / "Neb video.mp4"
            video.write_bytes(b"x")
            still = stills / "Neb video-123.png"
            still.write_bytes(b"x")
            cur, cur_video = d / "cur", d / "cur_video"
            cur.symlink_to(still)
            cur_video.symlink_to(video)
            with mock.patch.object(wp, "CURRENT", cur), mock.patch.object(wp, "CURRENT_VIDEO", cur_video), \
                    mock.patch.object(wp, "CACHE", cache / "wallpicker"):
                self.assertEqual(wp.current(), video)
                cur.unlink()
                pic = d / "pic.png"
                pic.write_bytes(b"x")
                cur.symlink_to(pic)
                self.assertEqual(wp.current(), pic)


@unittest.skipUnless(shutil.which("ffmpeg"), "needs ffmpeg")
class Thumbnails(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.video = self.dir / "clip.mp4"
        subprocess.run(["ffmpeg", "-loglevel", "error", "-f", "lavfi", "-i", "testsrc=size=320x240:rate=10", "-t", "2",
                        str(self.video)], check=True)
        self.short = self.dir / "short.mp4"  # under a second: its still comes from the first frame
        subprocess.run(["ffmpeg", "-loglevel", "error", "-f", "lavfi", "-i", "testsrc=size=320x240:rate=10", "-t", "0.5",
                        str(self.short)], check=True)
        self.picture = self.dir / "tall.png"
        subprocess.run(["ffmpeg", "-loglevel", "error", "-f", "lavfi", "-i", "testsrc=size=200x600", "-frames:v", "1",
                        str(self.picture)], check=True)

    def tearDown(self):
        self.tmp.cleanup()

    def size(self, path):
        out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "stream=width,height", "-of", "csv=p=0",
                              str(path)], capture_output=True, text=True).stdout.strip().splitlines()[0]
        return tuple(int(n) for n in out.split(","))

    def test_every_kind_fills_the_screen_shape(self):
        with mock.patch.object(wp, "CACHE", self.dir / "cache"):
            for wall in (wp.Wall(self.video, "video"), wp.Wall(self.short, "video"), wp.Wall(self.picture, "still")):
                out = wp.make(wp.thumb_command(wall, wp.thumb_path(wall, 384, 216), 384, 216), wp.thumb_path(wall, 384, 216))
                self.assertIsNotNone(out, wall.path.name)
                self.assertEqual(self.size(out), (384, 216), wall.path.name)

    def test_preview_loops_and_is_kept(self):
        with mock.patch.object(wp, "CACHE", self.dir / "cache"):
            wall = wp.Wall(self.video, "video")
            out = wp.make(wp.preview_command(wall, wp.preview_path(wall, 384, 216), 384, 216), wp.preview_path(wall, 384, 216))
            self.assertEqual(out.suffix, ".gif")
            self.assertEqual(self.size(out), (384, 216))
            stamp = out.stat().st_mtime_ns
            wp.make(wp.preview_command(wall, out, 384, 216), out)  # made once, then reused
            self.assertEqual(out.stat().st_mtime_ns, stamp)

    def test_a_changed_file_gets_a_new_thumbnail(self):
        wall = wp.Wall(self.picture, "still")
        first = wp.thumb_path(wall, 384, 216)
        self.picture.touch()
        import os
        os.utime(self.picture, ns=(1, 1))
        self.assertNotEqual(wp.thumb_path(wall, 384, 216), first)


if __name__ == "__main__":
    unittest.main()
