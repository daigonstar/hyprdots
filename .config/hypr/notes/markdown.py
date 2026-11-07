"""Markdown for the editor: which parts of the text get which look, and what Enter does in a list. Plain functions on
text, no GTK, so the editor stays simple and this can be tested."""
from __future__ import annotations

import re

LINE_RULES = (  # (tag, pattern for a whole line)
    ("h1", re.compile(r"^# .*$", re.M)),
    ("h2", re.compile(r"^## .*$", re.M)),
    ("h3", re.compile(r"^#{3,6} .*$", re.M)),
    ("quote", re.compile(r"^>.*$", re.M)),
    ("rule", re.compile(r"^ {0,3}(?:-{3,}|\*{3,}|_{3,})\s*$", re.M)),
    ("done", re.compile(r"^\s*[-*+] \[[xX]\] .*$", re.M)),
)
MARK_RULES = (  # (tag, pattern, group that gets the tag)
    ("bullet", re.compile(r"^\s*(?:[-*+]|\d+[.)])(?= )", re.M), 0),
    ("box", re.compile(r"^\s*[-*+] (\[[ xX]\])(?= )", re.M), 1),
    ("bold", re.compile(r"(\*\*|__)(?=\S)(.+?)(?<=\S)\1"), 0),
    ("italic", re.compile(r"(?<![*\w])([*_])(?=[^\s*_])(.+?)(?<=[^\s*_])\1(?![*\w])"), 0),
    ("strike", re.compile(r"~~(?=\S)(.+?)(?<=\S)~~"), 0),
    ("code", re.compile(r"`[^`\n]+`"), 0),
    ("link", re.compile(r"\[[^\]\n]+\]\([^)\s]+\)|<?https?://[^\s>)]+>?"), 0),
)
FENCE = re.compile(r"^```.*?(?:^```[^\n]*$|\Z)", re.M | re.S)


def spans(text: str) -> list[tuple[int, int, str]]:
    """(start, end, tag) for everything that looks different. Code blocks win: nothing inside them is formatted."""
    out, fenced = [], []
    for m in FENCE.finditer(text):
        fenced.append((m.start(), m.end()))
        out.append((m.start(), m.end(), "fence"))

    def inside(a, b):
        return any(s <= a and b <= e for s, e in fenced)
    for tag, pattern in LINE_RULES:
        out += [(m.start(), m.end(), tag) for m in pattern.finditer(text) if not inside(m.start(), m.end())]
    for tag, pattern, group in MARK_RULES:
        out += [(m.start(group), m.end(group), tag) for m in pattern.finditer(text) if not inside(m.start(), m.end())]
    return sorted(out)


LIST_ITEM = re.compile(r"^(\s*)(?:([-*+])( \[[ xX]\])?|(\d+)([.)]))( +)(.*)$")


def next_item(line: str) -> tuple[str | None, bool]:
    """What Enter at the end of a list line should do: (text to start the next line with, or None for a plain newline;
    whether to clear this line instead, which ends the list when the item is empty)."""
    m = LIST_ITEM.match(line)
    if not m:
        return None, False
    indent, bullet, box, number, dot, space, rest = m.groups()
    if not rest.strip():
        return "", True
    if bullet:
        return f"{indent}{bullet}{' [ ]' if box else ''}{space}", False
    return f"{indent}{int(number) + 1}{dot}{space}", False


def toggle_box(line: str) -> str | None:
    """A task line with its box ticked or unticked; a plain list item becomes a task; anything else becomes one too."""
    m = re.match(r"^(\s*[-*+] )\[([ xX])\]( .*)?$", line)
    if m:
        return f"{m[1]}[{' ' if m[2] in 'xX' else 'x'}]{m[3] or ''}"
    m = re.match(r"^(\s*)[-*+] (.*)$", line)
    if m:
        return f"{m[1]}- [ ] {m[2]}"
    m = re.match(r"^(\s*)(.*)$", line)
    return f"{m[1]}- [ ] {m[2]}"


def wrap(text: str, mark: str) -> str:
    """Bold or italic on a selection, or off when it already has it."""
    if len(text) >= 2 * len(mark) and text.startswith(mark) and text.endswith(mark):
        return text[len(mark):-len(mark)]
    return f"{mark}{text}{mark}"


def heading(line: str, level: int) -> str:
    """The line as a heading of that level, or plain again when it already is one."""
    m = re.match(r"^(#{1,6}) (.*)$", line)
    body = m[2] if m else line
    if m and len(m[1]) == level:
        return body
    return f"{'#' * level} {body}"
