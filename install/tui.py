#!/usr/bin/env python3
"""The installer's full-screen interface. It asks every question up front, then runs the installer again with the answers and
shows its progress, so nothing stops to ask halfway through a long install. The one exception is your password, which sudo
asks for through an overlay when it needs it (install/askpass). Python's own curses only, since this runs on a bare system. hyprinstall.sh --plain skips it.

Wizard and Progress hold the logic and do not touch the terminal, so they can be tested without one."""
import curses
import glob
import locale
import os
import re
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
INSTALLER = os.path.join(HERE, "..", "hyprinstall.sh")
LOG = os.path.expanduser("~/.local/share/hyprinstall/hyprinstall.log")
MIN_W, MIN_H = 60, 20
ASKPASS_DIR = os.path.join(HERE, "askpass")
RETRY_WINDOW = 15  # seconds: asked again this soon after an answer means sudo did not accept it
KEEP_LINES = 50000  # of this run's output, for the log view

LAYOUTS = (("us", "English (US)"), ("gb", "English (UK)"), ("de", "German"), ("fr", "French"), ("es", "Spanish"), ("it", "Italian"),
           ("pt", "Portuguese"), ("br", "Portuguese (Brazil)"), ("nl", "Dutch"), ("se", "Swedish"), ("no", "Norwegian"), ("dk", "Danish"),
           ("fi", "Finnish"), ("pl", "Polish"), ("cz", "Czech"), ("hu", "Hungarian"), ("ro", "Romanian"), ("tr", "Turkish"),
           ("ru", "Russian"), ("ua", "Ukrainian"), ("gr", "Greek"), ("jp", "Japanese"), ("kr", "Korean"), ("latam", "Spanish (Latin America)"))
GPUS = (("amd", "AMD"), ("nvidia", "NVIDIA"), ("intel", "Intel"))
TIERS = (("none", "No assistant", "You can add it later by running .config/hypr/assistant/setup.sh."),
         ("light", "Light", "About a 3 GB download. Needs 4 GB of GPU memory, or runs slowly on the CPU."),
         ("balanced", "Balanced", "About an 8 GB download. Needs 8 GB of GPU memory."),
         ("full", "Full", "About a 19 GB download. Needs 16 GB of GPU memory. Hearthling works best with this one."))
# Keys the installer reports as it reaches each stage, what to call them, and roughly how much of the time each takes
STAGES = (("system", "Updating your system", 12), ("drivers", "Installing graphics drivers", 8), ("desktop", "Installing the desktop", 40),
          ("apps", "Installing your apps", 15), ("flatpak", "Installing store apps", 10), ("services", "Turning on services", 1),
          ("assistant", "Setting up Hearthling", 5), ("config", "Linking your configuration", 3), ("login", "Setting up the login screen", 3),
          ("finish", "Finishing up", 3))


# ---- what this PC has ------------------------------------------------------------------------------------------------
def _run(*cmd):
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=10).stdout
    except (OSError, subprocess.SubprocessError):
        return ""


def detect_gpus(lspci=None):
    """The same matching as the installer's plain mode: PCI vendor id, or the name as a whole word."""
    text = _run("lspci", "-nn") if lspci is None else lspci
    lines = "\n".join(line for line in text.splitlines() if re.search(r"vga|3d controller|display controller", line, re.I))
    found = []
    for vendor, pattern in (("nvidia", r"\[10de:|\bnvidia\b"), ("amd", r"\[1002:|\b(amd|ati)\b|advanced micro"), ("intel", r"\[8086:|\bintel\b")):
        if re.search(pattern, lines, re.I):
            found.append(vendor)
    return found


def detect_layout(localectl=None):
    text = _run("localectl", "status") if localectl is None else localectl
    match = re.search(r"X11 Layout:\s*(\w+)", text) or re.search(r"VC Keymap:\s*([a-z]+)", text)
    known = {code for code, _ in LAYOUTS}
    code = match[1] if match else ""
    code = {"uk": "gb"}.get(code, code)
    return code if code in known else "us"


def detect_monitors():
    names = set()
    for status in glob.glob("/sys/class/drm/card*-*/status"):
        try:
            with open(status, encoding="utf-8") as f:
                connected = f.read().strip() == "connected"
        except OSError:
            continue
        name = os.path.basename(os.path.dirname(status))
        if connected and "-Writeback-" not in name:
            names.add(re.sub(r"^card\d+-", "", name))
    return sorted(names)


def video_memory_gb():
    best = 0
    for path in glob.glob("/sys/class/drm/card*/device/mem_info_vram_total"):
        try:
            with open(path, encoding="utf-8") as f:
                best = max(best, int(f.read()))
        except (OSError, ValueError):
            pass
    gb = round(best / 2 ** 30)
    if not gb:
        out = _run("nvidia-smi", "--query-gpu=memory.total", "--format=csv,noheader,nounits").split()
        gb = round(max((int(x) for x in out if x.isdigit()), default=0) / 1024)
    return gb


def recommended_tier(gb):
    return "full" if gb >= 14 else "balanced" if gb >= 7 else "light"


def is_laptop():
    try:
        with open("/sys/class/dmi/id/chassis_type", encoding="utf-8") as f:
            return f.read().strip() in {"8", "9", "10", "11", "14", "30", "31", "32"}
    except OSError:
        return False


def list_apps():
    """(browsers, groups) from install/apps.sh, which owns them. browsers: [(id, name)], groups: [(id, default, title, about)]."""
    browsers, groups = [], []
    for line in _run("bash", os.path.join(HERE, "apps.sh"), "--list").splitlines():
        parts = line.split("|")
        if parts[0] == "browser" and len(parts) == 3:
            browsers.append((parts[1], parts[2]))
        elif parts[0] == "group" and len(parts) == 5:
            groups.append((parts[1], parts[2] == "yes", parts[3], parts[4]))
    return browsers, groups


# ---- the questions ---------------------------------------------------------------------------------------------------
class Page:
    """One screen. kind: info (text only), radio (one choice) or check (any number). options: [(id, label, about)]."""

    def __init__(self, key, title, intro, kind, options=(), picked=()):
        self.key, self.title, self.intro, self.kind = key, title, intro, kind
        self.options = list(options)
        self.at = 0
        self.picked = set(picked)
        if kind == "radio" and picked:
            ids = [o[0] for o in self.options]
            self.at = ids.index(next(iter(picked))) if next(iter(picked)) in ids else 0

    def value(self):
        if self.kind == "radio":
            return self.options[self.at][0]
        return [o[0] for o in self.options if o[0] in self.picked]


class Wizard:
    """Moves between pages. press() takes a key name and returns "install", "quit" or None."""

    def __init__(self, gpus, monitors, layout, memory_gb, browsers, groups, laptop=False, dry_run=False):
        self.dry_run, self.at, self.confirm_quit = dry_run, 0, False
        rec = recommended_tier(memory_gb)
        tiers = [(i, n + ("  (suits this PC)" if i == rec else ""), a) for i, n, a in TIERS]
        about_pc = f"This looks like a {'laptop' if laptop else 'desktop'}" + \
            (f" with {' and '.join(dict(GPUS)[g] for g in gpus)} graphics." if gpus else ".")
        welcome = ["This sets up the Hyprland desktop. It asks a few questions first, then does the rest without you.",
                   "", about_pc, "",
                   "If you already have configs for Hyprland, the bar and so on, they are moved to ~/.config-backup, not deleted.",
                   "Your personal files are not touched."]
        if dry_run:
            welcome += ["", "PREVIEW: this is a dry run, so nothing will be installed or changed."]
        self.pages = [
            Page("welcome", "Welcome", welcome, "info"),
            Page("keyboard", "Keyboard layout", ["Used on the desktop and the login screen."], "radio",
                 [(c, f"{n}", "") for c, n in LAYOUTS], {layout}),
            Page("gpu", "Graphics drivers", ["Ticked ones were found in this PC. Tick two for a laptop with hybrid graphics."], "check",
                 [(c, n, "") for c, n in GPUS], gpus),
            Page("browser", "Web browser", ["Super+B opens this one."], "radio", [(i, n, "") for i, n in browsers],
                 {browsers[0][0]} if browsers else ()),
            Page("apps", "Extra apps", ["The desktop works without any of these. You can add more later with install/apps.sh."], "check",
                 [(i, t, a) for i, _d, t, a in groups], [i for i, d, _t, _a in groups if d]),
            Page("assistant", "Hearthling", ["An optional AI helper that runs on this PC. Nothing is sent to the cloud."], "radio", tiers, {"none"}),
        ]
        if len(monitors) > 1:
            self.pages.append(Page("login", "Login screen", ["Which screen should show the login screen?"], "radio",
                                   [(m, m, "") for m in monitors], {monitors[0]}))
        self.pages += [
            Page("health", "PC health monitor", ["Runs in the background and sends a notification about failed services, full disks and heat."],
                 "radio", [("yes", "Yes, keep an eye on it", ""), ("no", "No thanks", "")], {"yes"}),
            Page("review", "Ready to install", [], "info"),
        ]

    @property
    def page(self):
        return self.pages[self.at]

    def press(self, key):
        page = self.page
        if self.confirm_quit:
            self.confirm_quit = False
            return "quit" if key == "y" else None
        if key == "quit":
            self.confirm_quit = True
        elif key == "up" and page.options:
            page.at = (page.at - 1) % len(page.options)
        elif key == "down" and page.options:
            page.at = (page.at + 1) % len(page.options)
        elif key == "space" and page.kind == "check":
            self._toggle(page, page.options[page.at][0])
        elif key == "all" and page.kind == "check":
            page.picked = {o[0] for o in page.options}
        elif key == "none" and page.kind == "check":
            page.picked = set()
        elif key == "back":
            self.at = max(0, self.at - 1)
        elif key == "enter":
            if self.at == len(self.pages) - 1:
                return "install"
            self.at += 1
        return None

    def click(self, index):
        """A mouse click on a row of the list."""
        page = self.page
        if 0 <= index < len(page.options):
            page.at = index
            if page.kind == "check":
                self._toggle(page, page.options[index][0])

    @staticmethod
    def _toggle(page, option):
        page.picked.symmetric_difference_update({option})

    def answer(self, key):
        return next((p.value() for p in self.pages if p.key == key), None)

    def env(self):
        """The answers, in the form the installer takes for an unattended run."""
        env = {"HYPR_KB_LAYOUT": self.answer("keyboard"), "HYPR_GPU": " ".join(self.answer("gpu")) or "none",
               "HYPR_BROWSER": self.answer("browser") or "none", "HYPR_APPS": " ".join(self.answer("apps")) or "none",
               "HYPR_ASSISTANT": self.answer("assistant"), "HYPR_HEALTH": self.answer("health")}
        if self.answer("login"):
            env["HYPR_LOGIN_MONITOR"] = self.answer("login")
        return env

    def summary(self):
        names = {p.key: dict((o[0], o[1]) for o in p.options) for p in self.pages}
        apps = [names["apps"][a] for a in self.answer("apps")]
        rows = [("Keyboard", names["keyboard"][self.answer("keyboard")]),
                ("Graphics", ", ".join(names["gpu"][g] for g in self.answer("gpu")) or "No drivers"),
                ("Browser", names["browser"].get(self.answer("browser"), "None")),
                ("Extra apps", ", ".join(apps) or "None"),
                ("Hearthling", names["assistant"][self.answer("assistant")].split("  ")[0])]
        if self.answer("login"):
            rows.append(("Login screen", self.answer("login")))
        rows.append(("Health monitor", "Yes" if self.answer("health") == "yes" else "No"))
        return rows


# ---- following the install ---------------------------------------------------------------------------------------------
class Progress:
    """Reads the installer's output. Lines starting :: are progress marks from hyprinstall.sh; the rest is what it printed."""

    def __init__(self):
        self.stage, self.seen, self.items, self.item_at = None, [], 0, 0
        self.running, self.tail, self.warnings = "", [], []
        self.started = time.monotonic()

    def feed(self, line):
        line = "".join(c if 32 <= ord(c) < 127 else " " for c in line).strip()
        if not line:
            return
        if line.startswith("::"):
            kind, _, value = line[2:].partition(" ")
            if kind == "step":
                self.stage, self.items, self.item_at, self.running = value, 0, 0, ""
                self.seen.append(value)
            elif kind == "items":
                self.items, self.item_at = int(value) if value.isdigit() else 0, 0
            elif kind == "item":
                self.item_at += 1
                self.running = value
            elif kind == "run":
                self.running = value
            return
        if "[WARN]" in line or line.startswith("WARN"):
            self.warnings.append(line.split("[WARN]")[-1].strip())
        self.tail.append(line)
        del self.tail[:-KEEP_LINES]

    def fraction(self):
        """How far along, weighted by how long each stage tends to take. Stages that are skipped count as done."""
        total = sum(w for _k, _t, w in STAGES)
        done = 0.0
        keys = [k for k, _t, _w in STAGES]
        reached = keys.index(self.stage) if self.stage in keys else -1
        for i, (_key, _title, weight) in enumerate(STAGES):
            if i < reached:
                done += weight
            elif i == reached:
                done += weight * (min(self.item_at / self.items, 1.0) if self.items else 0.0)
        return done / total

    def title(self):
        return dict((k, t) for k, t, _w in STAGES).get(self.stage, "Getting started")

    def elapsed(self):
        seconds = int(time.monotonic() - self.started)
        return f"{seconds // 60}:{seconds % 60:02d}"


class LogView:
    """Scrolling through this run's output. It stays on the newest line until you scroll away, and follows again when you
    return to the end. Reads the same list the install keeps adding to, so the install carries on while you look."""

    def __init__(self, lines):
        self.lines, self.top, self.left, self.follow = lines, 0, 0, True

    def press(self, key, height):
        last = max(0, len(self.lines) - height)
        if self.follow:
            self.top = last
        moves = {"up": -1, "down": 1, "pageup": -height, "pagedown": height}
        if key in moves:
            self.top = max(0, min(last, self.top + moves[key]))
        elif key == "home":
            self.top = 0
        elif key == "end":
            self.top = last
        elif key == "left":
            self.left = max(0, self.left - 20)
        elif key == "right":
            self.left += 20
        self.follow = self.top >= last

    def visible(self, height):
        """(index of the first line shown, the lines)."""
        last = max(0, len(self.lines) - height)
        self.top = last if self.follow else min(self.top, last)
        return self.top, self.lines[self.top:self.top + height]


class PasswordBroker:
    """Where sudo's askpass helper asks for the password. A socket in a private folder, so the password is never in a file,
    an argument or the log."""

    def __init__(self):
        self.folder = tempfile.mkdtemp(prefix="hyprinstall-")  # mode 700
        self.path = os.path.join(self.folder, "askpass")
        self.server = socket.socket(socket.AF_UNIX)
        self.server.bind(self.path)
        self.server.listen(4)
        self.server.setblocking(False)
        self.answered = None  # when the last password was sent

    def env(self):
        return {"SUDO_ASKPASS": os.path.join(ASKPASS_DIR, "askpass.py"), "HYPRINSTALL_ASKPASS_SOCKET": self.path,
                "PATH": ASKPASS_DIR + os.pathsep + os.environ.get("PATH", "")}

    def request(self):
        """A PasswordBox if sudo is waiting for a password, else None."""
        try:
            link, _ = self.server.accept()
        except BlockingIOError:
            return None
        link.settimeout(2)
        try:
            link.recv(4096)  # its prompt: says nothing the box does not
        except OSError:
            link.close()
            return None
        retry = self.answered is not None and time.monotonic() - self.answered < RETRY_WINDOW
        return PasswordBox(link, retry)

    def reply(self, box, cancelled=False):
        try:
            if not cancelled:
                box.link.sendall(bytes(box.typed))
                self.answered = time.monotonic()
        except OSError:
            pass
        box.close()

    def close(self):
        self.server.close()
        shutil.rmtree(self.folder, ignore_errors=True)


class PasswordBox:
    """The overlay's typing, without the terminal. getch gives UTF-8 a byte at a time, so that is how it is kept."""

    def __init__(self, link, retry=False):
        self.link, self.retry, self.typed = link, retry, bytearray()

    def press(self, key):
        """A key from getch. Returns "send", "cancel" or None."""
        if key in (10, 13, curses.KEY_ENTER):
            return "send" if self.typed else None  # an empty answer would look like cancelling
        if key == 27:
            return "cancel"
        if key in (curses.KEY_BACKSPACE, 127, 8):
            while self.typed and self.typed[-1] & 0xC0 == 0x80:  # the rest of a multi-byte letter
                self.typed.pop()
            if self.typed:
                self.typed.pop()
        elif key == 21:  # Ctrl+U
            self.typed[:] = b"\0" * len(self.typed)
            self.typed.clear()
        elif 32 <= key <= 255 and key != 127:
            self.typed.append(key)
        return None

    def letters(self):
        return len(self.typed.decode("utf-8", "replace"))

    def close(self):
        self.typed[:] = b"\0" * len(self.typed)  # do not leave it sitting in memory
        self.typed.clear()
        self.link.close()


def run_installer(wizard, args, broker):
    env = {**os.environ, **wizard.env(), **broker.env(), "HYPRINSTALL_TUI": "1", "HYPRINSTALL_RESTARTED": "1"}
    return subprocess.Popen(["bash", INSTALLER, *args], stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, env=env)


# ---- drawing --------------------------------------------------------------------------------------------------------
ACCENT, DIM, GOOD, BAD = 1, 2, 3, 4


def wrap(text, width):
    lines = []
    for paragraph in text.split("\n"):
        line = ""
        for word in paragraph.split(" "):
            if line and len(line) + 1 + len(word) > width:
                lines.append(line)
                line = word
            else:
                line = f"{line} {word}" if line else word
        lines.append(line)
    return lines


class Screen:
    def __init__(self, stdscr):
        self.s = stdscr
        self.rows = {}  # screen line -> option index, for the mouse
        curses.curs_set(0)
        stdscr.keypad(True)
        curses.mousemask(curses.BUTTON1_CLICKED | curses.BUTTON1_PRESSED | curses.BUTTON4_PRESSED | curses.BUTTON5_PRESSED)
        if curses.has_colors():
            curses.start_color()
            curses.use_default_colors()
            for pair, colour in ((ACCENT, curses.COLOR_CYAN), (DIM, -1), (GOOD, curses.COLOR_GREEN), (BAD, curses.COLOR_RED)):
                curses.init_pair(pair, colour, -1)

    def put(self, y, x, text, attr=0):
        h, w = self.s.getmaxyx()
        if 0 <= y < h and 0 <= x < w:
            try:
                self.s.addnstr(y, x, text, w - x - 1, attr)
            except curses.error:
                pass

    def accent(self):
        return curses.color_pair(ACCENT) | curses.A_BOLD if curses.has_colors() else curses.A_BOLD

    def frame(self, title, right="", keys=""):
        self.s.erase()
        h, w = self.s.getmaxyx()
        self.put(0, 2, "hyprdots installer", self.accent())
        self.put(0, max(2, w - len(right) - 2), right, curses.A_DIM)
        self.s.hline(1, 0, curses.ACS_HLINE, w)
        self.put(3, 2, title, curses.A_BOLD)
        self.s.hline(h - 2, 0, curses.ACS_HLINE, w)
        self.put(h - 1, 2, keys, curses.A_DIM)

    def too_small(self):
        h, w = self.s.getmaxyx()
        if h >= MIN_H and w >= MIN_W:
            return False
        self.s.erase()
        self.put(0, 0, f"Please make the window at least {MIN_W}x{MIN_H}.")
        self.s.refresh()
        return True

    def wizard(self, wiz):
        if self.too_small():
            return
        page = wiz.page
        h, w = self.s.getmaxyx()
        keys = {"radio": "Up/Down choose   Enter next   Esc back   q quit",
                "check": "Up/Down move   Space tick   a all   n none   Enter next   Esc back",
                "info": "Enter continue   Esc back   q quit"}[page.kind]
        if page.key == "review":
            keys = ("Enter start the preview" if wiz.dry_run else "Enter start installing") + "   Esc change something   q quit"
        self.frame(page.title, f"Step {wiz.at + 1} of {len(wiz.pages)}", keys)
        y = 5
        for text in page.intro:
            for line in wrap(text, w - 6):
                self.put(y, 3, line)
                y += 1
        if page.key == "review":
            for label, value in wiz.summary():
                lines = wrap(value, w - 22)
                self.put(y, 3, label, self.accent())
                for line in lines:
                    self.put(y, 20, line)
                    y += 1
            y += 1
            self.put(y, 3, "Nothing has been changed yet.", curses.A_BOLD)
        elif page.options:
            self.options(page, y + 1, h)
        if wiz.confirm_quit:
            self.put(h - 3, 3, "Quit? Nothing has been installed. Press y to quit, anything else to stay.", curses.A_BOLD)
        self.s.refresh()

    def options(self, page, top, h):
        about = page.options[page.at][2]
        room = h - top - (5 if any(o[2] for o in page.options) else 3)
        first = max(0, min(page.at - room // 2, len(page.options) - room))
        self.rows = {}
        for row, i in enumerate(range(first, min(first + room, len(page.options)))):
            option = page.options[i]
            if page.kind == "check":
                mark = "[x]" if option[0] in page.picked else "[ ]"
            else:
                mark = "(*)" if i == page.at else "( )"
            here = i == page.at
            self.put(top + row, 3, ("> " if here else "  ") + mark + " " + option[1], self.accent() if here else 0)
            self.rows[top + row] = i
        if first > 0:
            self.put(top - 1, 5, "more above", curses.A_DIM)
        if first + room < len(page.options):
            self.put(top + room, 5, "more below", curses.A_DIM)
        if about:
            self.put(h - 4, 3, wrap(about, self.s.getmaxyx()[1] - 6)[0], curses.A_DIM)

    def log_view(self, view, prog, finished):
        if self.too_small():
            return
        h, w = self.s.getmaxyx()
        height = self.log_height()
        first, lines = view.visible(height)
        state = "still running" if finished is None else "finished" if finished == 0 else "stopped"
        where = f"line {first + len(lines)} of {len(view.lines)}" if view.lines else "nothing yet"
        self.frame("Log of this run", f"{where}  ({state})",
                   "Up/Down PgUp/PgDn scroll   Home/End jump   Left/Right sideways   l or Esc back")
        for row, line in enumerate(lines):
            attr = curses.A_NORMAL
            if "[ERROR]" in line or "[FAIL]" in line:
                attr = curses.color_pair(BAD) | curses.A_BOLD if curses.has_colors() else curses.A_BOLD
            elif "[WARN]" in line:
                attr = curses.A_BOLD
            self.put(5 + row, 2, line[view.left:view.left + w - 4], attr)
        if not lines:
            self.put(5, 2, "Nothing has been printed yet.", curses.A_DIM)
        self.s.refresh()

    def password(self, box, doing):
        """The overlay, over whatever is on screen. The password itself is never drawn, only a dot for each letter."""
        h, w = self.s.getmaxyx()
        width = min(66, w - 4)
        lines = [("The installer needs your password", self.accent()), ("", 0)]
        lines += [(line, 0) for line in wrap(f"Your administrator password is needed to carry on: {doing}.", width - 6)]
        lines.append(("", 0))
        if box.retry:
            bad = curses.color_pair(BAD) | curses.A_BOLD if curses.has_colors() else curses.A_BOLD
            lines += [(line, bad) for line in wrap("That did not work. Too many wrong tries can lock your account for a few minutes.", width - 6)]
            lines.append(("", 0))
        lines.append(("Password: " + ("\u2022" * box.letters())[:width - 18], curses.A_BOLD))
        lines += [("", 0), ("Enter continue   Esc stop the install", curses.A_DIM)]
        top, left = max(0, (h - len(lines) - 2) // 2), max(0, (w - width) // 2)
        self.put(top, left, "\u250c" + "\u2500" * (width - 2) + "\u2510", self.accent())
        for row, (text, attr) in enumerate(lines, top + 1):
            self.put(row, left, "\u2502" + " " * (width - 2) + "\u2502", self.accent())
            self.put(row, left + 3, text[:width - 6], attr)
        self.put(top + len(lines) + 1, left, "\u2514" + "\u2500" * (width - 2) + "\u2518", self.accent())
        self.s.refresh()

    def log_height(self):
        return max(1, self.s.getmaxyx()[0] - 7)

    def progress(self, prog, finished=None, dry_run=False, confirm=False):
        if self.too_small():
            return
        h, w = self.s.getmaxyx()
        if finished is None:
            title, keys = ("Previewing" if dry_run else "Installing") + ": " + prog.title(), "l show the log   q cancel"
        elif finished == 0:
            title = "Preview finished" if dry_run else "All done"
            keys = "l show the log   Enter finish" if dry_run else "l show the log   r go to the login screen now   Enter finish"
        else:
            title, keys = "The install stopped", "l show the log   Enter finish"
        self.frame(title, prog.elapsed(), keys)
        width = w - 12
        fraction = 1.0 if finished == 0 else prog.fraction()
        filled = int(width * fraction)
        self.put(5, 3, "[")
        self.put(5, 4, "#" * filled, self.accent())
        self.put(5, 4 + filled, "-" * (width - filled), curses.A_DIM)
        self.put(5, 4 + width, f"] {int(fraction * 100):3d}%")
        y = 7
        if finished is None and prog.running:
            self.put(y, 3, prog.running[:w - 6], curses.A_DIM)
            y += 2
        elif finished == 0:
            message = ["Nothing was changed: that was only a preview."] if dry_run else \
                ["The desktop is installed. Log in through the login screen to start it.", "A first-run welcome will show you around."]
            if prog.warnings:
                message.append(f"{len(prog.warnings)} thing(s) need a look: press l to read the log.")
            for line in message:
                self.put(y, 3, line, curses.color_pair(GOOD) if curses.has_colors() else 0)
                y += 1
            y += 1
        elif finished:
            self.put(y, 3, f"Something went wrong (code {finished}). Press l to read the whole log. It is also saved in:", curses.color_pair(BAD) if curses.has_colors() else 0)
            self.put(y + 1, 3, LOG)
            self.put(y + 2, 3, "Running ./hyprinstall.sh again is safe: it carries on past what is already done.")
            y += 4
        for line in prog.tail[-max(0, h - y - 3):]:
            self.put(y, 3, line[:w - 6], curses.A_DIM)
            y += 1
        if confirm:
            self.put(h - 3, 3, "Stop the install? The current step may finish first. Press y to stop.", curses.A_BOLD)
        self.s.refresh()


KEYS = {curses.KEY_UP: "up", ord("k"): "up", curses.KEY_DOWN: "down", ord("j"): "down", ord(" "): "space", ord("a"): "all", ord("n"): "none",
        27: "back", curses.KEY_LEFT: "back", curses.KEY_BACKSPACE: "back", 127: "back", ord("h"): "back", 10: "enter", 13: "enter", curses.KEY_ENTER: "enter",
        curses.KEY_RIGHT: "enter", ord("l"): "enter", ord("q"): "quit", ord("y"): "y", 3: "quit"}


def ask(screen, wiz):
    while True:
        screen.wizard(wiz)
        key = screen.s.getch()
        if key == curses.KEY_RESIZE:
            continue
        if key == curses.KEY_MOUSE:
            try:
                _i, _x, y, _z, _state = curses.getmouse()
            except curses.error:
                continue
            if y in screen.rows:
                wiz.click(screen.rows[y])
            continue
        result = wiz.press(KEYS.get(key, ""))
        if result:
            return result


LOG_KEYS = {curses.KEY_UP: "up", ord("k"): "up", curses.KEY_DOWN: "down", ord("j"): "down", curses.KEY_PPAGE: "pageup", curses.KEY_NPAGE: "pagedown",
            ord(" "): "pagedown", curses.KEY_HOME: "home", ord("g"): "home", curses.KEY_END: "end", ord("G"): "end", curses.KEY_LEFT: "left", curses.KEY_RIGHT: "right"}


def wheel(view, height):
    """A mouse wheel on the log."""
    try:
        state = curses.getmouse()[4]
    except curses.error:
        return
    for _ in range(3):
        if state & curses.BUTTON4_PRESSED:
            view.press("up", height)
        elif state & curses.BUTTON5_PRESSED:
            view.press("down", height)


def follow(screen, wiz, args):
    """Runs the install and shows it. Returns the installer's exit code."""
    prog = Progress()
    broker = PasswordBroker()
    try:
        return follow_with(screen, wiz, args, prog, broker)
    finally:
        broker.close()


def follow_with(screen, wiz, args, prog, broker):
    child = run_installer(wiz, args, broker)
    stream = child.stdout.fileno()
    os.set_blocking(stream, False)
    screen.s.timeout(100)
    buffer, confirm, code, view, box = b"", False, None, None, None
    while True:
        if code is None:
            # Ask whether it has ended before reading, so that this read gets the last of its output. Do not wait for the
            # stream to close: a helper it leaves behind can hold that open long after it has finished.
            ended = child.poll()
            try:
                data = os.read(stream, 65536)
            except BlockingIOError:
                data = b""
            buffer += data
            *lines, buffer = re.split(rb"[\r\n]", buffer)
            for line in lines:
                prog.feed(line.decode("utf-8", "replace"))
            if ended is not None and not data:
                code = ended
                prog.feed(buffer.decode("utf-8", "replace"))
            if not box:
                box = broker.request()
                if box:  # sudo may have just written straight to the terminal (its first-time lecture), so draw it all again
                    screen.s.clearok(True)
        if box and code is not None:  # the install ended while asking
            broker.reply(box, cancelled=True)
            box = None
        if box:
            # Takes every key until it is answered. The install keeps being read underneath, in case it has more to say.
            if view:
                screen.log_view(view, prog, code)
            else:
                screen.progress(prog, code, wiz.dry_run, False)
            screen.password(box, prog.title())
            action = box.press(screen.s.getch())
            if action == "send":
                broker.reply(box)
                box = None
            elif action == "cancel":
                broker.reply(box, cancelled=True)
                box = None
                child.send_signal(signal.SIGTERM)
            continue
        if view:
            screen.log_view(view, prog, code)
            key = screen.s.getch()
            if key in (ord("l"), ord("q"), 27, 10, 13, curses.KEY_ENTER):
                view = None
            elif key == curses.KEY_MOUSE:
                wheel(view, screen.log_height())
            elif key in LOG_KEYS:
                view.press(LOG_KEYS[key], screen.log_height())
            continue
        screen.progress(prog, code, wiz.dry_run, confirm)
        key = screen.s.getch()
        if key == ord("l"):
            view, confirm = LogView(prog.tail), False
        elif code is None and confirm:
            confirm = False
            if key == ord("y"):
                child.send_signal(signal.SIGTERM)  # pacman, if it is mid-way, is left to finish rather than break the system
        elif code is None and key in (ord("q"), 3):
            confirm = True
        elif code is not None and key in (10, 13, curses.KEY_ENTER, ord("q")):
            return code
        elif code == 0 and key == ord("r") and not wiz.dry_run:
            restart_login_screen(screen, prog, broker)
            return code


def restart_login_screen(screen, prog, broker):
    """sudo's permission may have lapsed by the time you press r, so this can ask too."""
    env = {**os.environ, **broker.env()}
    proc = subprocess.Popen(["sudo", "systemctl", "restart", "sddm"], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env=env)
    box = None
    while proc.poll() is None:
        box = box or broker.request()
        if not box:
            screen.s.getch()  # waits up to 100 ms
            continue
        screen.progress(prog, 0)
        screen.password(box, "going to the login screen")
        action = box.press(screen.s.getch())
        if action:
            broker.reply(box, cancelled=action == "cancel")
            box = None
    if box:
        broker.reply(box, cancelled=True)


def interface(stdscr, wiz, args):
    screen = Screen(stdscr)
    if ask(screen, wiz) == "quit":
        return None
    return follow(screen, wiz, args)


def main(argv):
    dry = "--dry-run" in argv
    browsers, groups = list_apps()
    wiz = Wizard(detect_gpus(), detect_monitors(), detect_layout(), video_memory_gb(), browsers, groups, is_laptop(), dry)
    locale.setlocale(locale.LC_ALL, "")
    os.environ.setdefault("ESCDELAY", "25")
    code = curses.wrapper(interface, wiz, [a for a in argv if a in ("--dry-run", "--verbose")])
    if code is None:
        print("Nothing was installed.")
        return 0
    print("Finished." if code == 0 else f"The install stopped. See {LOG}")
    return code


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
