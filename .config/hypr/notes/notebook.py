"""Where the notes live while their tabs are open: one Markdown file per tab in ~/.local/state/hyprdots/notes (or the
folder in NOTES_DIR), saved as you type, so open tabs survive a crash or a restart. Closing a tab deletes its file, to the
bin so a slip can be undone. Save as is how a note is kept. Plain files only, no GTK, so this can be tested and used from
scripts (notes.sh --append)."""
from __future__ import annotations

import json
import os
import re
import subprocess
import time
from pathlib import Path

STATE_HOME = Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local/state"))
INBOX = "inbox"  # the tab notes.sh --append writes to


def default_dir() -> Path:
    return Path(os.environ["NOTES_DIR"]) if os.environ.get("NOTES_DIR") else STATE_HOME / "hyprdots/notes"


def title_of(text: str) -> str:
    """What a note is about: its first line that is not empty, without the Markdown marks around it."""
    for line in text.splitlines():
        line = re.sub(r"^\s*(?:#{1,6}\s+|[-*+]\s+(?:\[[ xX]\]\s+)?|\d+[.)]\s+|>\s*)", "", line).strip(" *_`#")
        if line:
            return line[:80]
    return ""


def file_name(title: str) -> str:
    """A name for Save as, from the note's title: no slashes or characters other systems refuse."""
    name = re.sub(r'[/\\:*?"<>|\x00-\x1f]+', " ", title).strip().strip(".").strip()
    return (re.sub(r"\s+", " ", name)[:60] or "Note") + ".md"


class Notebook:
    def __init__(self, folder: Path | str | None = None):
        self.dir = Path(folder) if folder else default_dir()
        self.state_path = self.dir / ".tabs.json"
        self.dir.mkdir(parents=True, exist_ok=True)

    # ---- tabs ------------------------------------------------------------------------------------------------------
    def tabs(self) -> list[Path]:
        """Open tabs in the order you left them. A note file the order does not mention (one notes.sh made while the window
        was not running, say) still gets a tab, at the end, so nothing is ever hidden."""
        state = self.load_state()
        files = {p.name: p for p in self.dir.glob("*.md") if p.is_file()}
        ordered = [files.pop(name) for name in state.get("tabs", []) if name in files]
        return ordered + sorted(files.values(), key=lambda p: p.stat().st_mtime)

    def new(self, text: str = "", name: str | None = None) -> Path:
        path = self.dir / (name or f"{time.strftime('%Y%m%d-%H%M%S')}-{os.getpid() % 1000:03d}{time.monotonic_ns() % 1000:03d}.md")
        self.write(path, text)
        return path

    def read(self, path: Path) -> str:
        try:
            return path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            return ""

    def write(self, path: Path, text: str) -> None:
        """Atomic: a crash or power cut leaves the old version or the new one, never half of one."""
        tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
        tmp.write_text(text, encoding="utf-8")
        os.replace(tmp, path)

    def close(self, path: Path) -> None:
        """Closing a tab deletes its note. An empty one is simply removed; one with something in it goes to the bin."""
        if not path.exists():
            return
        if not self.read(path).strip():
            path.unlink(missing_ok=True)
            return
        try:
            subprocess.run(["gio", "trash", str(path)], check=True, capture_output=True, timeout=5)
        except (OSError, subprocess.SubprocessError):
            path.unlink(missing_ok=True)

    def append(self, text: str) -> Path:
        """For scripts: adds a line to the Inbox tab, made if it is missing, without the window open."""
        path = self.dir / f"{INBOX}.md"
        old = self.read(path) if path.exists() else "# Inbox\n"
        self.write(path, old + ("" if old.endswith("\n") else "\n") + text.rstrip("\n") + "\n")
        return path

    # ---- where you were ----------------------------------------------------------------------------------------
    def load_state(self) -> dict:
        try:
            data = json.loads(self.state_path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except (OSError, ValueError):
            return {}

    def save_state(self, state: dict) -> None:
        tmp = self.state_path.with_name(self.state_path.name + f".{os.getpid()}.tmp")
        tmp.write_text(json.dumps(state, indent=1), encoding="utf-8")
        os.replace(tmp, self.state_path)
