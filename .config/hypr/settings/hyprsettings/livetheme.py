"""Lets hyprdots' own long-running GTK 4 apps (Settings, Sound, Notes, the assistant) follow a theme change while they
are open.

GTK reads ~/.config/gtk-4.0/gtk.css once, when an app starts, and never again. So an app left open through a theme
override switch kept the old look, or a mix of both. Here:

- theme_parts writes a look's extra CSS into gtk.css with every selector limited to windows *without* the class
  LIVE_CLASS (prefix()), so the copy GTK read at startup stops applying to our marked windows;
- follow(app) marks the app's windows with that class and loads the current block itself, through a CSS provider it
  replaces whenever gtk.css changes (a provider added later wins over GTK's startup one).

Other apps keep GTK's own behaviour: they pick up the new look when they are reopened. Needs only GTK and GLib, so any
app can import it."""

from __future__ import annotations

import os
import re
from pathlib import Path

LIVE_CLASS = "hyprdots-live"
SKIP = f"window:not(.{LIVE_CLASS})"
MARK, END = "/* hyprdots theme: ", "/* hyprdots theme end */"


def gtk4_css_path() -> Path:
    return Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config") / "gtk-4.0" / "gtk.css"


# ---- the selectors ---------------------------------------------------------------------------------------------------
def _split_selectors(text: str) -> list[str]:
    """Splits a selector list on its top-level commas (not those inside :not(...) and the like)."""
    parts, depth, start = [], 0, 0
    for i, ch in enumerate(text):
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        elif ch == "," and depth == 0:
            parts.append(text[start:i])
            start = i + 1
    parts.append(text[start:])
    return [p.strip() for p in parts if p.strip()]


def _limit(selector: str) -> str:
    """One selector, limited to windows without LIVE_CLASS: window... gets the :not() on itself, anything else is put
    inside such a window."""
    m = re.match(r"^window(?![-\w])", selector)
    if m:
        return SKIP + selector[len("window"):]
    if selector.startswith(":root"):
        return selector  # the variables: our own provider sets them again over these
    return f"{SKIP} {selector}"


def _keyframes(css: str) -> tuple[str, list[str]]:
    """css with each @keyframes block swapped for a marker, and the blocks: their steps (0% { }) are not selectors."""
    blocks, out, i = [], [], 0
    while True:
        start = css.find("@keyframes", i)
        open_ = css.find("{", start) if start >= 0 else -1
        if open_ < 0:
            out.append(css[i:])
            return "".join(out), blocks
        depth, j = 0, open_
        while j < len(css):
            depth += {"{": 1, "}": -1}.get(css[j], 0)
            j += 1
            if depth == 0:
                break
        out.append(css[i:start] + f"/*hd-keyframes-{len(blocks)}*/")
        blocks.append(css[start:j])
        i = j


def prefix(css: str) -> str:
    """Every rule of css limited to windows without LIVE_CLASS. Comments, @define-color, @keyframes and other @ lines
    are kept as they are."""
    css, blocks = _keyframes(css)
    out = _prefix_rules(css)
    for n, block in enumerate(blocks):
        out = out.replace(f"/*hd-keyframes-{n}*/", block, 1)
    return out


def _prefix_rules(css: str) -> str:
    out, i = [], 0
    for m in re.finditer(r"([^{}]*)\{([^{}]*)\}", css):
        head = m.group(1)
        lead = head[:len(head) - len(head.lstrip())]
        selectors = head.strip()
        out.append(css[i:m.start()])
        # comments and @ lines stand before the selector in the same stretch of text: keep them as they are
        keep = ""
        while True:
            c = re.match(r"(\s*/\*.*?\*/\s*|\s*@[^;{]*;\s*)", selectors, re.S)
            if not c:
                break
            keep += c.group(1)
            selectors = selectors[c.end():]
        limited = ", ".join(_limit(s) for s in _split_selectors(selectors))
        out.append(f"{lead}{keep}{limited} {{{m.group(2)}}}")
        i = m.end()
    out.append(css[i:])
    return "".join(out)


def unprefix(css: str) -> str:
    """prefix() undone: the block as our own marked windows should have it."""
    return css.replace(f"{SKIP} ", "").replace(SKIP, "window")


def current_block(path: Path | None = None) -> str:
    """The hyprdots block of gtk.css (colours and the look), as our own windows should have it. Empty without one."""
    try:
        text = (path or gtk4_css_path()).read_text(encoding="utf-8")
    except OSError:
        return ""
    start = text.find(MARK)
    if start < 0:
        return ""
    end = text.find(END, start)
    return unprefix(text[start:end if end >= 0 else len(text)])


# ---- in an app ---------------------------------------------------------------------------------------------------------
class Follower:
    """Keeps the app's windows marked and its provider in step with gtk.css."""

    def __init__(self, app):
        from gi.repository import Gdk, Gio, GLib, Gtk  # only here: the functions above are used without GTK
        self.Gtk, self.GLib = Gtk, GLib
        self.display = Gdk.Display.get_default()
        self.provider = None
        self.timer = 0
        app.connect("window-added", lambda _a, w: w.add_css_class(LIVE_CLASS))
        for w in app.get_windows():
            w.add_css_class(LIVE_CLASS)
        self.monitor = Gio.File.new_for_path(str(gtk4_css_path())).monitor_file(Gio.FileMonitorFlags.WATCH_MOVES, None)
        self.monitor.connect("changed", lambda *_: self.soon())
        self.load()

    def soon(self):
        """gtk.css is written in a few steps: read it once they are done."""
        if self.timer:
            self.GLib.source_remove(self.timer)
        self.timer = self.GLib.timeout_add(250, self._load_now)

    def _load_now(self):
        self.timer = 0
        self.load()
        return False

    def load(self):
        Gtk = self.Gtk
        if self.provider is not None:
            Gtk.StyleContext.remove_provider_for_display(self.display, self.provider)
        self.provider = Gtk.CssProvider()
        self.provider.load_from_string(current_block())
        Gtk.StyleContext.add_provider_for_display(self.display, self.provider, Gtk.STYLE_PROVIDER_PRIORITY_USER)


def follow(app) -> Follower | None:
    """Call once, before the app's first window opens. Keep the result alive as long as the app runs."""
    try:
        return Follower(app)
    except Exception:  # a theme helper must never stop an app from opening
        return None
