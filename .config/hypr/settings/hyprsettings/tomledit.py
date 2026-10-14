"""Small, careful TOML editor: change one key in one section and leave everything else (comments,
other keys, ordering) as it was. Every write is checked by re-parsing it first."""

from __future__ import annotations

import json
import os
import re
import tomllib
from pathlib import Path
from typing import Any

HEADER = "# Private settings, git-ignored. Overrides user_settings.toml. Managed by hypr-settings; hand edits are kept.\n"
_SECTION = re.compile(r"^\s*\[([^\[\]]+)\]\s*(?:#.*)?$")
_KEY = re.compile(r"^\s*([A-Za-z0-9_-]+)\s*=")


class TomlError(Exception):
    pass


def format_value(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        return repr(value)
    if isinstance(value, str):
        return json.dumps(value, ensure_ascii=False)
    if isinstance(value, (list, tuple)):
        if not value:
            return "[]"
        if all(isinstance(v, str) for v in value) and (len(value) > 2 or sum(len(v) for v in value) > 60):
            return "[\n" + ",\n".join(f"    {format_value(v)}" for v in value) + "\n]"
        return "[" + ", ".join(format_value(v) for v in value) + "]"
    raise TomlError(f"cannot write a {type(value).__name__} to TOML")


def _bracket_depth_change(line: str) -> int:
    """Net [ ] depth change in a line, ignoring brackets inside strings and comments."""
    depth, quote, escaped = 0, "", False
    for ch in line:
        if quote:
            if escaped:
                escaped = False
            elif ch == "\\" and quote == '"':
                escaped = True
            elif ch == quote:
                quote = ""
        elif ch in "\"'":
            quote = ch
        elif ch == "#":
            break
        elif ch == "[":
            depth += 1
        elif ch == "]":
            depth -= 1
    return depth


def _find(lines: list[str], section: str, key: str):
    """(section_start, section_end, key_start, key_end); each None when absent."""
    start = end = None
    for i, line in enumerate(lines):
        m = _SECTION.match(line)
        if m:
            if start is not None:
                end = i
                break
            if m.group(1).strip() == section:
                start = i
    if start is not None and end is None:
        end = len(lines)
    if start is None:
        return None, None, None, None
    i = start + 1
    while i < end:
        m = _KEY.match(lines[i])
        if m and m.group(1) == key:
            j, depth = i, _bracket_depth_change(lines[i].split("=", 1)[1])
            while depth > 0 and j + 1 < end:  # a multi-line array
                j += 1
                depth += _bracket_depth_change(lines[j])
            return start, end, i, j + 1
        i += 1
    return start, end, None, None


def read(path: Path | str) -> dict:
    try:
        with open(path, "rb") as f:
            return tomllib.load(f)
    except FileNotFoundError:
        return {}
    except tomllib.TOMLDecodeError as e:
        raise TomlError(f"{path}: {e}") from e


def _write(path: Path, lines: list[str]) -> None:
    text = "\n".join(lines).rstrip("\n") + "\n"
    try:
        tomllib.loads(text)
    except tomllib.TOMLDecodeError as e:  # never write something the agent could not read back
        raise TomlError(f"refusing to write invalid TOML: {e}") from e
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        backup = path.with_name(path.name + ".bak")
        backup.write_bytes(path.read_bytes())
        backup.chmod(0o600)
    tmp = path.with_name(path.name + f".{os.getpid()}.tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.chmod(0o600)
    os.replace(tmp, path)


def _load_lines(path: Path) -> list[str]:
    if path.exists():
        return path.read_text(encoding="utf-8").splitlines()
    return [HEADER.rstrip("\n")]


def set_value(path: Path | str, section: str, key: str, value: Any) -> None:
    path = Path(path)
    lines = _load_lines(path)
    new = f"{key} = {format_value(value)}".split("\n")
    s_start, s_end, k_start, k_end = _find(lines, section, key)
    if k_start is not None:
        lines[k_start:k_end] = new
    elif s_start is not None:
        at = s_end
        while at > s_start + 1 and not lines[at - 1].strip():  # keep the blank line before the next section
            at -= 1
        lines[at:at] = new
    else:
        if lines and lines[-1].strip():
            lines.append("")
        lines += [f"[{section}]"] + new
    _write(path, lines)


def unset(path: Path | str, section: str, key: str) -> bool:
    """Removes a key; drops the section too if it ends up empty. Returns False if it was not there."""
    path = Path(path)
    if not path.exists():
        return False
    lines = path.read_text(encoding="utf-8").splitlines()
    s_start, s_end, k_start, k_end = _find(lines, section, key)
    if k_start is None:
        return False
    del lines[k_start:k_end]
    body = lines[s_start + 1:s_end - (k_end - k_start)]
    if not any(line.strip() and not line.strip().startswith("#") for line in body):
        del lines[s_start:s_end - (k_end - k_start)]
        while lines and not lines[-1].strip():
            lines.pop()
    _write(path, lines)
    return True
