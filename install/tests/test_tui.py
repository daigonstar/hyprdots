"""The full-screen installer. The logic is tested directly, then the real hyprinstall.sh --dry-run is driven through a real
terminal with key presses, in a throwaway home."""
import fcntl
import os
import pty
import re
import select
import shutil
import signal
import socket
import struct
import sys
import tempfile
import termios
import time
import unittest
from pathlib import Path

INSTALL = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(INSTALL))
import tui  # noqa: E402

BROWSERS = [("firefox", "Firefox"), ("zen", "Zen"), ("none", "None")]
GROUPS = [("chat", False, "Chat", "Discord"), ("gaming", False, "Gaming", "Steam"), ("store", True, "App store", "Bazaar")]
SYNCS = [("none", "None"), ("opencloud", "OpenCloud"), ("nextcloud", "Nextcloud")]


def wizard(monitors=("DP-1",), gpus=("amd",), **kw):
    return tui.Wizard(list(gpus), list(monitors), "gb", 16, BROWSERS, GROUPS, **kw)


def go_to(wiz, key):
    while wiz.page.key != key:
        wiz.press("enter")


class Detection(unittest.TestCase):
    def test_gpus(self):
        self.assertEqual(tui.detect_gpus("03:00.0 VGA compatible controller [0300]: Advanced Micro Devices [1002:747e]"), ["amd"])
        self.assertEqual(tui.detect_gpus("00:02.0 VGA: Intel Corporation UHD [8086:9a49]\n01:00.0 3D controller: NVIDIA [10de:1f95]"), ["nvidia", "intel"])
        self.assertEqual(tui.detect_gpus("00:1f.3 Audio device: Intel Corporation [8086:a348]"), [])

    def test_layout(self):
        self.assertEqual(tui.detect_layout("   X11 Layout: de\n"), "de")
        self.assertEqual(tui.detect_layout("   VC Keymap: uk\n"), "gb")
        self.assertEqual(tui.detect_layout("   X11 Layout: nonsense\n"), "us")
        self.assertEqual(tui.detect_layout(""), "us")

    def test_recommended_tier(self):
        self.assertEqual([tui.recommended_tier(g) for g in (0, 4, 8, 16)], ["light", "light", "balanced", "full"])


class Questions(unittest.TestCase):
    def test_defaults_give_a_minimal_install(self):
        env = wizard().env()
        self.assertEqual(env, {"HYPR_KB_LAYOUT": "gb", "HYPR_GPU": "amd", "HYPR_BROWSER": "firefox", "HYPR_APPS": "store", "HYPR_ASSISTANT": "none", "HYPR_HEALTH": "yes"})

    def test_ticking_and_choosing(self):
        wiz = wizard()
        go_to(wiz, "apps")
        wiz.press("down")
        wiz.press("space")
        go_to(wiz, "assistant")
        wiz.press("down")
        env = wiz.env()
        self.assertEqual(env["HYPR_APPS"], "gaming store")
        self.assertEqual(env["HYPR_ASSISTANT"], "light")

    def test_all_and_none(self):
        wiz = wizard()
        go_to(wiz, "apps")
        wiz.press("all")
        self.assertEqual(wiz.env()["HYPR_APPS"], "chat gaming store")
        wiz.press("none")
        self.assertEqual(wiz.env()["HYPR_APPS"], "none")

    def test_no_gpu_ticked_means_no_drivers(self):
        self.assertEqual(wizard(gpus=()).env()["HYPR_GPU"], "none")

    def test_login_screen_is_only_asked_with_two_screens(self):
        self.assertNotIn("login", [p.key for p in wizard().pages])
        wiz = wizard(monitors=("DP-1", "DP-2"))
        go_to(wiz, "login")
        wiz.press("down")
        self.assertEqual(wiz.env()["HYPR_LOGIN_MONITOR"], "DP-2")

    def test_going_back_keeps_your_answers(self):
        wiz = wizard()
        go_to(wiz, "browser")
        wiz.press("down")
        wiz.press("back")
        wiz.press("enter")
        self.assertEqual(wiz.env()["HYPR_BROWSER"], "zen")

    def test_the_last_page_starts_and_quitting_needs_a_yes(self):
        wiz = wizard()
        self.assertIsNone(wiz.press("quit"))
        self.assertIsNone(wiz.press("down"))
        wiz.press("quit")
        self.assertEqual(wiz.press("y"), "quit")
        wiz = wizard()
        go_to(wiz, "review")
        self.assertEqual(wiz.press("enter"), "install")

    def test_a_click_ticks(self):
        wiz = wizard()
        go_to(wiz, "apps")
        wiz.click(0)
        self.assertIn("chat", wiz.answer("apps"))
        wiz.click(99)

    def test_summary_is_in_words(self):
        rows = dict(wizard().summary())
        self.assertEqual(rows["Keyboard"], "English (UK)")
        self.assertEqual(rows["Hearthling"], "No assistant")
        self.assertEqual(rows["Extra apps"], "App store")

    def test_one_sync_client_after_the_browser_none_unless_picked(self):
        wiz = wizard(syncs=SYNCS)
        keys = [p.key for p in wiz.pages]
        self.assertEqual(keys.index("sync"), keys.index("browser") + 1)
        self.assertEqual(wiz.env()["HYPR_SYNC"], "none")
        self.assertEqual(dict(wiz.summary())["Sync client"], "None")
        go_to(wiz, "sync")
        wiz.press("down")
        self.assertEqual(wiz.env()["HYPR_SYNC"], "opencloud")
        self.assertEqual(dict(wiz.summary())["Sync client"], "OpenCloud")

    def test_list_apps_reads_the_sync_clients(self):
        browsers, syncs, groups = tui.list_apps()
        self.assertEqual([i for i, _ in syncs], ["none", "opencloud", "nextcloud", "owncloud"])
        self.assertTrue(browsers and groups)


class Following(unittest.TestCase):
    def test_marks_are_not_shown_and_move_the_bar(self):
        p = tui.Progress()
        self.assertEqual(p.fraction(), 0)
        p.feed("::step desktop")
        low = p.fraction()
        p.feed("::items 4")
        p.feed("::item hyprland")
        p.feed("::item waybar")
        self.assertGreater(p.fraction(), low)
        self.assertEqual(p.running, "waybar")
        self.assertEqual(p.title(), "Installing the desktop")
        self.assertEqual(p.tail, [])

    def test_output_and_warnings(self):
        p = tui.Progress()
        p.feed("hello \x1b world")
        p.feed("2026-11-03 [WARN] Boot splash failed")
        self.assertEqual(p.tail[0], "hello   world")
        self.assertEqual(p.warnings, ["Boot splash failed"])

    def test_never_goes_past_full(self):
        p = tui.Progress()
        p.feed("::step finish")
        p.feed("::items 1")
        p.feed("::item a")
        p.feed("::item b")
        self.assertLessEqual(p.fraction(), 1.0)
        p.feed("::items nonsense")
        p.feed("::step nothing-we-know")

    def test_the_log_keeps_the_whole_run(self):
        p = tui.Progress()
        for i in range(500):
            p.feed(f"line {i}")
        self.assertEqual(len(p.tail), 500)
        self.assertEqual(p.tail[0], "line 0")

    def test_wrap(self):
        self.assertEqual(tui.wrap("one two three", 7), ["one two", "three"])


class LogViewing(unittest.TestCase):
    def setUp(self):
        self.lines = [f"line {i}" for i in range(100)]
        self.view = tui.LogView(self.lines)

    def test_opens_on_the_newest_and_follows(self):
        self.assertEqual(self.view.visible(10)[1][-1], "line 99")
        self.lines.append("line 100")
        self.assertEqual(self.view.visible(10)[1][-1], "line 100")

    def test_scrolling_up_stops_following(self):
        self.view.press("pageup", 10)
        first, shown = self.view.visible(10)
        self.assertEqual(first, 80)
        self.lines.append("new")
        self.assertEqual(self.view.visible(10)[0], 80)

    def test_returning_to_the_end_follows_again(self):
        self.view.press("up", 10)
        self.view.press("end", 10)
        self.lines.append("new")
        self.assertEqual(self.view.visible(10)[1][-1], "new")

    def test_stays_in_bounds(self):
        self.view.press("home", 10)
        self.assertEqual(self.view.visible(10)[0], 0)
        self.view.press("up", 10)
        self.assertEqual(self.view.visible(10)[0], 0)
        for _ in range(50):
            self.view.press("pagedown", 10)
        self.assertEqual(self.view.visible(10)[0], 90)
        self.view.press("left", 10)
        self.assertEqual(self.view.left, 0)

    def test_short_and_empty_logs(self):
        self.assertEqual(tui.LogView([]).visible(10), (0, []))
        self.assertEqual(tui.LogView(["a"]).visible(10), (0, ["a"]))


class Terminal:
    """A program on a real terminal: keys go in, and what it draws comes out."""

    def __init__(self, args, home, cols=100, rows=30, cwd=None):
        self.out = b""
        self.pid, self.fd = pty.fork()
        if self.pid == 0:
            os.environ.update(HOME=home, TERM="xterm-256color", ESCDELAY="25")
            for name in ("HYPR_APPS", "HYPR_BROWSER", "HYPR_GPU", "HYPR_ASSISTANT", "HYPR_SETTINGS_DIR", "UPDATE_BRANCH", "XDG_STATE_HOME"):
                os.environ.pop(name, None)
            os.environ["HYPR_SETTINGS_DIR"] = os.path.join(home, ".config/hypr")
            os.chdir(cwd or "/")
            os.execvp(args[0], args)
        fcntl.ioctl(self.fd, termios.TIOCSWINSZ, struct.pack("HHHH", rows, cols, 0, 0))

    def pump(self, wait=0.1):
        while select.select([self.fd], [], [], wait)[0]:
            try:
                data = os.read(self.fd, 65536)
            except OSError:
                return False
            if not data:
                return False
            self.out += data
            wait = 0.02
        return True

    def text(self):
        return re.sub(rb"\x1b\[[0-9;?]*[A-Za-z]|\x1b[()][A-Z0-9]|\x1b[=>]", b"", self.out).decode("utf-8", "replace")

    def wait_for(self, what, timeout=60):
        end = time.monotonic() + timeout
        start = len(self.text()) if False else 0
        while time.monotonic() < end:
            alive = self.pump()
            if what in self.text()[start:]:
                return True
            if not alive:
                break
        raise AssertionError(f"never saw {what!r}. Saw the end of:\n{self.text()[-1500:]}")

    def keys(self, *keys):
        for key in keys:
            os.write(self.fd, key.encode())
            time.sleep(0.05)
            self.pump(0.05)

    def close(self):
        try:
            os.kill(self.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        try:
            os.waitpid(self.pid, 0)
        except ChildProcessError:
            pass
        os.close(self.fd)


ENTER, ESC, DOWN, SPACE = "\r", "\x1b", "\x1bOB", " "  # the Down arrow as a terminal sends it in keypad mode

# Stands in for sudo: asks through SUDO_ASKPASS as the real one does, three tries. The real one is never given a password here.
FAKE_SUDO = """#!/bin/sh
echo "LECTURE-ON-THE-TERMINAL" > /dev/tty 2>/dev/null
[ "$1" = -A ] || { echo "not asked to use askpass"; exit 3; }
for try in 1 2 3; do
    answer=$("$SUDO_ASKPASS" "[sudo] password: ") || { echo "sudo: no password was provided"; exit 1; }
    [ "$answer" = "$FAKE_PASSWORD" ] && { echo "sudo accepted"; exit 0; }
    echo "Sorry, try again."
done
exit 1
"""
FAKE_INSTALLER = """#!/bin/sh
echo "::stage system"
sudo pacman -Syu || { echo "password step failed"; exit 7; }
echo "after the password"
sleep 30
"""
DRIVER = """
import curses, sys
sys.path.insert(0, {install!r})
import tui
tui.INSTALLER = {installer!r}
wiz = tui.Wizard(["amd"], ["DP-1"], "gb", 16, [("none", "None")], [])
print("exit", curses.wrapper(lambda s: tui.follow(tui.Screen(s), wiz, [])))
"""


class PasswordOverlay(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)
        sudo, installer = self.dir / "fake-sudo", self.dir / "installer.sh"
        sudo.write_text(FAKE_SUDO)
        installer.write_text(FAKE_INSTALLER)
        sudo.chmod(0o755)
        installer.chmod(0o755)
        driver = self.dir / "driver.py"
        driver.write_text(DRIVER.format(install=str(INSTALL), installer=str(installer)))
        os.environ.update(HYPRINSTALL_REAL_SUDO=str(sudo), FAKE_PASSWORD="hunter2")
        self.addCleanup(os.environ.pop, "HYPRINSTALL_REAL_SUDO")
        self.addCleanup(os.environ.pop, "FAKE_PASSWORD")
        self.term = Terminal([sys.executable, str(driver)], str(self.dir))
        self.addCleanup(self.term.close)

    def test_wrong_then_right_and_it_is_never_shown(self):
        self.term.wait_for("needs your password")
        after_lecture = self.term.out.split(b"LECTURE-ON-THE-TERMINAL")[-1]
        self.assertRegex(after_lecture, rb"\x1b\[[23]?J", "the screen is wiped, so what sudo wrote does not stay behind the box")
        self.term.keys(*"wrong", ENTER)
        self.term.wait_for("did not work")
        self.term.keys(*"hunter2", ENTER)
        self.term.wait_for("after the password")
        self.assertNotIn("hunter2", self.term.text())
        self.assertNotIn("wrong", self.term.text().replace("Too many wrong tries", ""))
        self.assertIn("\u2022", self.term.text())

    def test_esc_stops_the_install(self):
        self.term.wait_for("needs your password")
        self.term.keys(ESC)
        self.term.wait_for("The install stopped")
        self.assertNotIn("after the password", self.term.text())

    def test_the_socket_folder_is_private_and_removed(self):
        broker = tui.PasswordBroker()
        folder = broker.folder
        self.assertEqual(os.stat(folder).st_mode & 0o777, 0o700)
        broker.close()
        self.assertFalse(os.path.exists(folder))


class PasswordTyping(unittest.TestCase):
    def box(self):
        a, b = socket.socketpair()
        self.addCleanup(b.close)
        box = tui.PasswordBox(a)
        self.addCleanup(box.close)
        return box

    def test_keys(self):
        box = self.box()
        for key in b"ab":
            box.press(key)
        self.assertIsNone(box.press(127))
        self.assertEqual(bytes(box.typed), b"a")
        self.assertEqual(box.press(10), "send")
        self.assertEqual(box.press(27), "cancel")

    def test_enter_on_nothing_waits_and_timeouts_are_ignored(self):
        box = self.box()
        self.assertIsNone(box.press(10))
        self.assertIsNone(box.press(-1))
        self.assertEqual(bytes(box.typed), b"")

    def test_backspace_takes_a_whole_letter(self):
        box = self.box()
        for key in "aé".encode():
            box.press(key)
        self.assertEqual(box.letters(), 2)
        box.press(127)
        self.assertEqual(bytes(box.typed), b"a")


@unittest.skipUnless(shutil.which("pacman"), "the installer needs pacman")
class RealRun(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.home = tmp.name
        self.installer = str(INSTALL.parent / "hyprinstall.sh")

    def start(self, *args, **kw):
        term = Terminal(["bash", self.installer, *args], self.home, **kw)
        self.addCleanup(term.close)
        return term

    def log(self):
        return (Path(self.home) / ".local/share/hyprinstall/hyprinstall.log").read_text()

    def test_a_whole_run_with_choices(self):
        term = self.start("--dry-run")
        term.wait_for("PREVIEW")
        term.keys(ENTER)
        term.wait_for("Keyboard layout")
        term.keys(ENTER)
        term.wait_for("Graphics drivers")
        term.keys(ENTER)
        term.wait_for("Web browser")
        term.keys(DOWN, ENTER)  # Zen
        term.wait_for("Sync client")
        term.keys(DOWN, ENTER)  # OpenCloud
        term.wait_for("Extra apps")
        groups = sorted(p.stem for p in (INSTALL / "apps").glob("*.txt"))
        term.keys(*[DOWN] * groups.index("gaming"), SPACE, ENTER)
        term.wait_for("Hearthling")
        while "Ready to install" not in term.text():
            term.keys(ENTER)
        term.keys(ENTER)
        term.wait_for("only a preview", timeout=180)  # curses redraws only what changed, so whole titles may never be sent as one
        log = self.log()
        self.assertRegex(log, r"Optional apps:.*gaming")
        self.assertIn("browser: zen-browser", log)
        self.assertIn("sync client: opencloud", log)
        self.assertIn("opencloud-desktop", log)
        self.assertNotIn("com.nextcloud.desktopclient.nextcloud", log)
        self.assertIn("steam", log)
        self.assertNotIn("discord", log)
        self.assertNotIn("winboat", log)
        self.assertIn("--set-browser", log)
        self.assertIn("--set-keyboard", log)
        self.assertNotIn("[ERROR]", log)
        self.assertFalse((Path(self.home) / ".local/state/hyprdots/apps").exists(), "a preview must not save choices")

    def finish_preview(self, term):
        term.wait_for("PREVIEW")
        while "Ready to install" not in term.text():
            term.keys(ENTER)
            term.pump(0.1)
        term.keys(ENTER)

    def test_the_log_opens_scrolls_and_returns_during_and_after_a_run(self):
        term = self.start("--dry-run")
        self.finish_preview(term)
        term.keys("l")
        term.wait_for("Log of this run")
        term.keys("g", "G", "\x1bOA")
        term.keys("l")  # back to the progress screen, while it is still going or just finished
        term.wait_for("only a preview", timeout=120)
        marker = len(term.text())
        term.keys("l")
        term.pump(0.3)
        shown = term.text()[marker:]
        self.assertIn("Log of this run", shown)
        self.assertIn("finished", shown)
        self.assertIn("line", shown)
        term.keys("g")
        term.pump(0.3)
        self.assertIn("Starting hyprinstall", term.text()[marker:], "Home goes to the start of this run")
        marker = len(term.text())
        term.keys("\x1b")
        term.pump(0.3)
        term.keys(ENTER)
        term.wait_for("Finished")

    def test_quitting_changes_nothing(self):
        term = self.start("--dry-run")
        term.wait_for("PREVIEW")
        term.keys("q")
        term.wait_for("Press y")
        term.keys("y")
        term.wait_for("Nothing was installed")
        self.assertNotIn("Optional apps", self.log())

    def test_a_small_window_asks_to_be_bigger(self):
        term = self.start("--dry-run", cols=40, rows=10)
        term.wait_for("make the window")

    def test_plain_still_works(self):
        term = self.start("--dry-run", "--plain")
        term.wait_for("Starting hyprinstall")
        self.assertNotIn("PREVIEW", term.text())


if __name__ == "__main__":
    unittest.main()
