"""Runs the real update.sh against a throwaway remote and home: an update must not cost you a setting or a file."""
import os
import pty
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]


def git(cwd, *args):
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=True).stdout


class Update(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        self.home, self.dev, self.pc = root / "home", root / "dev", root / "pc"
        self.home.mkdir()
        bare = root / "remote.git"
        git(root, "init", "-q", "--bare", "-b", "main", str(bare))
        self.env = {**os.environ, "HOME": str(self.home), "SKIP_PACKAGES": "1", "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
                    "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t", "UPDATE_BRANCH": "main", "XDG_STATE_HOME": str(self.home / ".local/state")}
        self.env.pop("HYPRLAND_INSTANCE_SIGNATURE", None)
        self.env.pop("XDG_CONFIG_HOME", None)
        git(root, "clone", "-q", str(bare), str(self.dev))
        for name in ("hypr", "waybar", "swaync", "rofi", "wallust", "ghostty", "fastfetch"):
            (self.dev / ".config" / name).mkdir(parents=True)
        (self.dev / ".config/starship.toml").write_text("default\n")
        (self.dev / ".config/hypr/user_settings.toml").write_text("a = 1\nb = 2\nc = 3\nd = 4\ne = 5\nf = 6\n")
        (self.dev / ".config/hypr/keybinds.lua").write_text("shipped\n")
        (self.dev / ".config/waybar/config").write_text("shipped\n")
        (self.dev / ".gitignore").write_text("/.config/hypr/user_overrides.lua\n/.config/hypr/user_settings.local.toml\n/.config/waybar/layout.json\n")
        shutil.copy(REPO / "update.sh", self.dev / "update.sh")
        self.publish("first")
        git(root, "clone", "-q", str(bare), str(self.pc))
        (self.home / ".config").mkdir()
        os.symlink(self.pc / ".config/hypr", self.home / ".config/hypr")

    def publish(self, message):
        git(self.dev, "add", "-A")
        subprocess.run(["git", "commit", "-qm", message], cwd=self.dev, env=self.env, check=True)
        git(self.dev, "push", "-q", "origin", "main")

    def update(self, *extra, **env):
        return subprocess.run(["bash", str(self.pc / "update.sh"), *extra], cwd=self.pc, env={**self.env, **env}, capture_output=True, text=True,
                              stdin=subprocess.DEVNULL, timeout=120)

    def read(self, name):
        return (self.pc / name).read_text()

    def test_settings_and_your_own_files_survive(self):
        files = {".config/hypr/user_overrides.lua": "mine", ".config/hypr/user_settings.local.toml": "[a]\nb = 1\n", ".config/waybar/layout.json": "{}",
                 ".config/hypr/user_settings.local.toml.bak": "old", ".config/hypr/my-script.sh": "mine", ".config/hypr/notes/idea.txt": "mine"}
        for name, text in files.items():
            (self.pc / name).parent.mkdir(parents=True, exist_ok=True)
            (self.pc / name).write_text(text)
        (self.dev / ".config/hypr/keybinds.lua").write_text("new\n")
        self.publish("second")
        result = self.update()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.read(".config/hypr/keybinds.lua"), "new\n")
        for name, text in files.items():
            self.assertEqual(self.read(name), text, name)

    def test_a_hand_edit_is_put_back_on_top_of_the_update(self):
        (self.pc / ".config/hypr/user_settings.toml").write_text("a = 1\nb = 2\nc = 3\nd = 4\ne = 5\nf = 99\n")
        (self.dev / ".config/hypr/user_settings.toml").write_text("a = 111\nb = 2\nc = 3\nd = 4\ne = 5\nf = 6\n")
        self.publish("second")
        result = self.update()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.read(".config/hypr/user_settings.toml"), "a = 111\nb = 2\nc = 3\nd = 4\ne = 5\nf = 99\n")

    def test_a_clashing_edit_gives_way_and_is_saved(self):
        (self.pc / ".config/hypr/keybinds.lua").write_text("mine\n")
        (self.dev / ".config/hypr/keybinds.lua").write_text("new\n")
        self.publish("second")
        result = self.update()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.read(".config/hypr/keybinds.lua"), "new\n")
        self.assertIn("clash", result.stderr)
        saved = list((self.home / ".local/state/hyprdots/update-backups").glob("*/.config/hypr/keybinds.lua"))
        self.assertEqual([p.read_text() for p in saved], ["mine\n"])

    def test_local_commits_stop_the_update_and_change_nothing(self):
        (self.pc / ".config/hypr/keybinds.lua").write_text("committed here\n")
        git(self.pc, "add", "-A")
        subprocess.run(["git", "commit", "-qm", "local"], cwd=self.pc, env=self.env, check=True)
        (self.pc / ".config/waybar/config").write_text("edited\n")
        (self.dev / ".config/hypr/user_settings.toml").write_text("new\n")
        self.publish("second")
        before = git(self.pc, "rev-parse", "HEAD")
        result = self.update()
        self.assertEqual(result.returncode, 3)
        self.assertEqual(git(self.pc, "rev-parse", "HEAD"), before)
        self.assertEqual(self.read(".config/waybar/config"), "edited\n")
        self.assertEqual(self.update(UPDATE_DISCARD_COMMITS="1").returncode, 0)
        self.assertEqual(self.read(".config/hypr/user_settings.toml"), "new\n")

    def test_a_failed_fetch_changes_nothing(self):
        (self.pc / ".config/hypr/keybinds.lua").write_text("mine\n")
        git(self.pc, "remote", "set-url", "origin", "/nonexistent")
        result = self.update()
        self.assertEqual(result.returncode, 2)
        self.assertEqual(self.read(".config/hypr/keybinds.lua"), "mine\n")

    def test_moves_to_the_chosen_branch_rather_than_overwriting_the_current_one(self):
        git(self.pc, "switch", "-qc", "other", "origin/main")
        result = self.update()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(git(self.pc, "branch", "--show-current").strip(), "main")
        self.assertIn("other", git(self.pc, "branch", "--list", "other"))

    def test_your_own_configs_are_not_replaced(self):
        (self.home / ".config/starship.toml").write_text("my prompt\n")
        (self.home / ".config/ghostty").mkdir()
        (self.home / ".config/ghostty/config").write_text("my terminal\n")
        result = self.update()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual((self.home / ".config/starship.toml").read_text(), "my prompt\n")
        self.assertEqual((self.home / ".config/ghostty/config").read_text(), "my terminal\n")
        self.assertEqual(list((self.home / ".config").glob("*.bak.*")), [])

    def test_moving_to_an_older_stable_is_allowed_and_your_own_commits_still_stop_it(self):
        git(self.dev, "push", "-q", "origin", "main:stable")
        (self.dev / ".config/hypr/keybinds.lua").write_text("newest\n")
        self.publish("newest")
        self.assertEqual(self.update().returncode, 0)
        self.assertEqual(self.read(".config/hypr/keybinds.lua"), "newest\n")
        done = self.update(UPDATE_BRANCH="stable")
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(self.read(".config/hypr/keybinds.lua"), "shipped\n")
        self.assertIn("Nothing new", done.stdout)

    def test_lists_what_changed(self):
        (self.dev / ".config/hypr/keybinds.lua").write_text("new\n")
        self.publish("Popups close when you click away")
        done = self.update()
        self.assertIn("What's new (1):\n- Popups close when you click away", done.stdout)
        saved = Path(self.env["XDG_STATE_HOME"]) / "hyprdots/last-update.txt"
        self.assertEqual(saved.read_text(), "- Popups close when you click away\n")

    def promote(self, checks, answer="y\n"):
        fake = self.home / "bin"
        fake.mkdir(exist_ok=True)
        (fake / "gh").write_text(f"#!/bin/sh\nprintf '%s\\n' '{checks}'\n")
        (fake / "gh").chmod(0o755)
        shutil.copy(REPO / "install/promote.sh", self.dev / "promote.sh")
        return subprocess.run(["bash", "promote.sh"], cwd=self.dev, env={**self.env, "PATH": f"{fake}:{os.environ['PATH']}"},
                              capture_output=True, text=True, input=answer, timeout=30)

    def stable(self):
        return subprocess.run(["git", "rev-parse", "--verify", "-q", "origin/stable"], cwd=self.dev, capture_output=True, text=True).stdout.strip()

    def test_promote_only_moves_stable_on_a_passed_version(self):
        for checks in ("completed failure", "in_progress ", "none"):
            self.assertNotEqual(self.promote(checks).returncode, 0, checks)
            self.assertEqual(self.stable(), "")
        self.assertNotEqual(self.promote("completed success", "n\n").returncode, 0)
        self.assertEqual(self.stable(), "")
        done = self.promote("completed success")
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertNotEqual(self.stable(), "")

    def test_promote_still_asks_after_a_long_list(self):
        for n in range(45):
            subprocess.run(["git", "commit", "-q", "--allow-empty", "-m", f"change {n}"], cwd=self.dev, env=self.env, check=True)
        git(self.dev, "push", "-q", "origin", "main")
        done = self.promote("completed success")
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertIn("...and 6 more", done.stdout)
        self.assertNotEqual(self.stable(), "")

    def test_no_menu_in_a_terminal_until_there_is_a_stable_branch(self):
        main, other = pty.openpty()
        self.addCleanup(os.close, main)
        env = {k: v for k, v in self.env.items() if k != "UPDATE_BRANCH"}
        done = subprocess.run(["bash", str(self.pc / "update.sh")], cwd=self.pc, env=env, stdin=other, capture_output=True, text=True, timeout=60)
        os.close(other)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertNotIn("Which version", done.stdout)
        self.assertFalse((self.pc / ".update-branch").exists())

    def test_gpu_check_only_names_cards_without_their_drivers(self):
        fake = self.home / "bin"
        fake.mkdir(exist_ok=True)
        (fake / "lspci").write_text("#!/bin/sh\necho '03:00.0 VGA compatible controller [0300]: NVIDIA Corporation [10de:2684]'\necho '13:00.0 VGA compatible controller [0300]: Advanced Micro Devices [1002:164e]'\n")
        script = REPO / ".config/hypr/scripts/gpu-check.sh"

        def run(installed):
            (fake / "pacman").write_text(f"#!/bin/sh\ncase \" {installed} \" in *\" $2 \"*) exit 0;; esac\necho \"$2\"\nexit 127\n")
            for tool in ("lspci", "pacman"):
                (fake / tool).chmod(0o755)
            return subprocess.run(["bash", str(script)], env={**self.env, "PATH": f"{fake}:{os.environ['PATH']}"}, capture_output=True, text=True).stdout.split()

        self.assertEqual(run("nvidia-utils vulkan-radeon"), [])
        self.assertEqual(run("vulkan-radeon"), ["nvidia"])
        self.assertEqual(run(""), ["nvidia", "amd"])

    def test_a_file_of_yours_with_a_new_shipped_name_is_saved(self):
        (self.pc / ".config/hypr/new.lua").write_text("mine\n")
        (self.dev / ".config/hypr/new.lua").write_text("shipped\n")
        self.publish("second")
        self.assertEqual(self.update().returncode, 0)
        self.assertEqual(self.read(".config/hypr/new.lua"), "shipped\n")
        saved = list((self.home / ".local/state/hyprdots/update-backups").glob("*/.config/hypr/new.lua"))
        self.assertEqual([p.read_text() for p in saved], ["mine\n"])


if __name__ == "__main__":
    unittest.main()
