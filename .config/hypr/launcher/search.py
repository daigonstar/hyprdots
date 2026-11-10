"""What the launcher shows for what you type: installed apps (ranked by match and by how often you open them),
plus a calculator, commands (>), web search (?) and power actions. No GTK here, so it can be tested on its own:

    python3 search.py "fire"        prints the results for a query"""

from __future__ import annotations

import ast
import json
import math
import operator
import os
import sys
import time
import urllib.parse
from dataclasses import dataclass, field
from pathlib import Path

import gi

gi.require_version("Gio", "2.0")
from gi.repository import Gio  # noqa: E402

try:  # GLib 2.86 moved DesktopAppInfo to GioUnix; older systems only have it in Gio
    gi.require_version("GioUnix", "2.0")
    from gi.repository import GioUnix  # noqa: E402
    DesktopAppInfo = GioUnix.DesktopAppInfo
except (ValueError, ImportError):
    DesktopAppInfo = Gio.DesktopAppInfo

STATE = Path(os.environ.get("XDG_STATE_HOME") or Path.home() / ".local/state") / "hyprdots" / "launcher-usage.json"

# Desktop-file categories -> the launcher's categories (same buckets as the old rofi launcher)
BUCKETS = [
    ("Internet", "Network WebBrowser Email Chat InstantMessaging News RemoteAccess P2P FileTransfer VideoConference Feed"),
    ("Games", "Game ActionGame AdventureGame ArcadeGame BoardGame CardGame PuzzleGame StrategyGame SimulationGame SportsGame LogicGame Emulator"),
    ("Multimedia", "AudioVideo Audio Video Player Recorder DiscBurning Music TV Mixer Sequencer"),
    ("Graphics", "Graphics 2DGraphics 3DGraphics VectorGraphics RasterGraphics Photography Scanning Viewer"),
    ("Office", "Office WordProcessor Spreadsheet Presentation Calendar ContactManagement Database Chart Finance Dictionary"),
    ("Development", "Development IDE Building Debugger GUIDesigner Profiling RevisionControl Translation ProjectManagement"),
    ("Utility", "Utility Accessibility Archiving Compression FileTools FileManager TextEditor TextTools Calculator Clock"),
    ("System", "System Filesystem Monitor TerminalEmulator ConsoleOnly Security"),
    ("Settings", "Settings DesktopSettings HardwareSettings PackageManager"),
]
CATEGORY_ICONS = {"Frequent": "\U000f0d8e", "All apps": "\U000f003b", "Internet": "\U000f059f", "Games": "\U000f0297",
                  "Multimedia": "\U000f075a", "Graphics": "\U000f03d8", "Office": "\U000f0219", "Development": "\U000f0169",
                  "Utility": "\U000f0ad7", "System": "\U000f035b", "Settings": "\U000f0493", "Other": "\U000f01d8"}
SEARCH_ENGINES = {"duckduckgo": "https://duckduckgo.com/?q={}", "google": "https://www.google.com/search?q={}",
                  "brave": "https://search.brave.com/search?q={}", "startpage": "https://www.startpage.com/do/search?q={}"}
POWER = [  # word, label, command, needs a second Enter
    ("lock", "Lock the screen", ["~/.config/hypr/scripts/lock.sh"], False),
    ("sleep", "Sleep", ["systemctl", "suspend"], True),
    ("log out", "Log out", ["hyprctl", "dispatch", "hl.dsp.exit()"], True),
    ("reboot", "Restart the PC", ["systemctl", "reboot"], True),
    ("shut down", "Shut down", ["systemctl", "poweroff"], True),
]
POWER_ICONS = {"lock": "\U000f033e", "sleep": "\U000f04b2", "log out": "\U000f0343", "reboot": "\U000f0709", "shut down": "\U000f0425"}


@dataclass
class Result:
    kind: str                 # app | calc | command | web | power
    title: str
    subtitle: str = ""
    app_id: str = ""          # desktop id for apps
    gicon: object = None      # Gio.Icon for apps
    glyph: str = ""           # Nerd Font icon for everything else
    value: str = ""           # what Enter acts on: answer, command, URL, power word
    confirm: bool = False
    score: float = 0.0
    category: str = "Other"
    extra: dict = field(default_factory=dict)


# ---- apps ---------------------------------------------------------------------------------------------------------
def bucket(categories: str) -> str:
    cats = set(filter(None, (categories or "").split(";")))
    for name, members in BUCKETS:
        if cats & set(members.split()):
            return name
    return "Other"


def installed_apps() -> list[Result]:
    out, seen = [], set()
    for info in Gio.AppInfo.get_all():
        if not info.should_show() or not isinstance(info, DesktopAppInfo):
            continue
        app_id = info.get_id() or ""
        name = info.get_display_name() or info.get_name() or app_id
        if not app_id or name.lower() in seen:
            continue
        seen.add(name.lower())
        keywords = " ".join(info.get_keywords() or [])
        out.append(Result("app", name, info.get_generic_name() or info.get_description() or "", app_id=app_id,
                          gicon=info.get_icon(), category=bucket(info.get_categories() or ""),
                          extra={"keywords": keywords.lower(), "generic": (info.get_generic_name() or "").lower(),
                                 "exec": (info.get_executable() or "").lower()}))
    return sorted(out, key=lambda r: r.title.lower())


def match(query: str, app: Result) -> float:
    """0 when it does not match; higher is better."""
    q, name = query.lower(), app.title.lower()
    if name.startswith(q):
        return 100 - min(len(name) - len(q), 30) * 0.2
    words = name.replace("-", " ").split()
    if any(w.startswith(q) for w in words):
        return 80
    if q in name:
        return 60
    extra = app.extra
    if any(w.startswith(q) for w in (extra["keywords"] + " " + extra["generic"]).split()) or extra["exec"].startswith(q):
        return 45
    if q in extra["keywords"] or q in extra["generic"]:
        return 35
    it = iter(name)  # letters in order, loosely ("ffx" finds Firefox)
    if len(q) >= 2 and all(ch in it for ch in q):
        return 20
    return 0


# ---- how often you open things ----------------------------------------------------------------------------------
def load_usage() -> dict:
    try:
        return json.loads(STATE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def record_use(app_id: str) -> None:
    usage = load_usage()
    entry = usage.get(app_id, {"count": 0, "last": 0})
    usage[app_id] = {"count": entry["count"] + 1, "last": time.time()}
    try:
        STATE.parent.mkdir(parents=True, exist_ok=True)
        tmp = STATE.with_suffix(".tmp")
        tmp.write_text(json.dumps(usage), encoding="utf-8")
        os.replace(tmp, STATE)
    except OSError:
        pass


def clear_usage() -> None:
    STATE.unlink(missing_ok=True)


def popularity(app_id: str, usage: dict) -> float:
    """Opens, fading over about a month, so what you use now beats what you used a lot once."""
    entry = usage.get(app_id)
    if not entry:
        return 0.0
    days = (time.time() - entry.get("last", 0)) / 86400
    return entry.get("count", 0) * math.exp(-days / 30)


def frequent(apps: list[Result], usage: dict, limit: int = 12) -> list[Result]:
    ranked = sorted((a for a in apps if popularity(a.app_id, usage) > 0), key=lambda a: -popularity(a.app_id, usage))
    return ranked[:limit]


# ---- extras --------------------------------------------------------------------------------------------------------
_OPS = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul, ast.Div: operator.truediv,
        ast.FloorDiv: operator.floordiv, ast.Mod: operator.mod, ast.Pow: operator.pow,
        ast.USub: operator.neg, ast.UAdd: operator.pos}


def calculate(text: str):
    """A sum typed in the search box, worked out safely (numbers and + - * / // % ^ ( ) only). None if it is not one."""
    expr = text.strip().replace("^", "**").replace("×", "*").replace("÷", "/").replace(",", "")
    if not expr or not any(op in expr for op in "+-*/%()") or not any(ch.isdigit() for ch in expr):
        return None

    def ev(node):
        if isinstance(node, ast.Expression):
            return ev(node.body)
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
            return node.value
        if isinstance(node, ast.BinOp) and type(node.op) in _OPS:
            left, right = ev(node.left), ev(node.right)
            if isinstance(node.op, ast.Pow) and abs(right) > 100:
                raise ValueError
            return _OPS[type(node.op)](left, right)
        if isinstance(node, ast.UnaryOp) and type(node.op) in _OPS:
            return _OPS[type(node.op)](ev(node.operand))
        raise ValueError
    try:
        value = ev(ast.parse(expr, mode="eval"))
    except (SyntaxError, ValueError, ZeroDivisionError, OverflowError, TypeError):
        return None
    if isinstance(value, float):
        value = round(value, 10)
        if value.is_integer():
            value = int(value)
    return f"{value:,}" if isinstance(value, int) and abs(value) >= 10000 else str(value)


def extras(query: str, engine: str) -> list[Result]:
    q = query.strip()
    out = []
    if q.startswith(">") and q[1:].strip():
        cmd = q[1:].strip()
        out.append(Result("command", f"Run {cmd}", "In your terminal", glyph="\U000f018d", value=cmd, score=1000))
    elif q.startswith("?") and q[1:].strip():
        terms = q[1:].strip()
        url = SEARCH_ENGINES.get(engine, SEARCH_ENGINES["duckduckgo"]).format(urllib.parse.quote_plus(terms))
        out.append(Result("web", f"Search the web for {terms}", url.split('/')[2], glyph="\U000f0349", value=url, score=1000))
    else:
        answer = calculate(q)
        if answer is not None:
            out.append(Result("calc", answer, "Enter copies the answer", glyph="\U000f00ec", value=answer.replace(",", ""),
                              score=1000))
        low = q.lower()
        if len(low) >= 3:
            for word, label, cmd, confirm in POWER:
                if word.startswith(low) or label.lower().startswith(low):
                    out.append(Result("power", label, "Press Enter twice to confirm" if confirm else "",
                                      glyph=POWER_ICONS[word], value=word, confirm=confirm, score=90,
                                      extra={"cmd": cmd}))
    return out


def search(query: str, apps: list[Result], usage: dict, engine: str = "duckduckgo", rank_by_use: bool = True) -> list[Result]:
    q = query.strip()
    special = extras(q, engine)
    if q.startswith((">", "?")):
        return special
    found = []
    for app in apps:
        m = match(q, app)
        if m:
            boost = math.log1p(popularity(app.app_id, usage)) * 6 if rank_by_use else 0
            app.score = m + boost
            found.append(app)
    found.sort(key=lambda a: (-a.score, a.title.lower()))
    return sorted(special + found, key=lambda r: -r.score)


# ---- what the window says and how its arrows move -----------------------------------------------------------------
def mode_label(query: str) -> str:
    """The chip beside the search box: what the launcher takes the text to be."""
    q = query.strip()
    if not q:
        return "APPS"
    if q.startswith(">"):
        return "RUN"
    if q.startswith("?"):
        return "WEB"
    return "SUM" if calculate(q) is not None else "SEARCH"


def action_text(result: Result) -> str:
    """The footer's description of what Enter does."""
    return {"app": f"Open {result.title}", "calc": f"Copy {result.title}"}.get(result.kind, result.title)


def initial(title: str) -> str:
    """The letter an app files under in the A to Z. Anything that is not A to Z goes under #."""
    ch = title.strip()[:1].upper()
    return ch if "A" <= ch <= "Z" else "#"


def first_with_initial(results: list[Result], letter: str) -> int | None:
    return next((i for i, r in enumerate(results) if initial(r.title) == letter), None)


def step(index: int, count: int, columns: int, direction: str) -> int:
    """Where an arrow lands among count results laid out columns wide. Left and right run on through the rows. Up and
    down keep to the column, but stop at the top and bottom instead of jumping sideways to the first or last result;
    the one exception is down into a shorter last row, which lands on its end."""
    if count < 1:
        return 0
    columns = max(columns, 1)
    if direction in ("left", "right"):
        return max(0, min(index + (1 if direction == "right" else -1), count - 1))
    target = index + (columns if direction == "down" else -columns)
    if 0 <= target < count:
        return target
    below = direction == "down" and (count - 1) // columns > index // columns
    return count - 1 if below else index


if __name__ == "__main__":
    query = " ".join(sys.argv[1:])
    apps = installed_apps()
    results = search(query, apps, load_usage()) if query else apps
    for r in results[:15]:
        print(f"{r.kind:8} {r.score:6.1f}  {r.title:32} {r.category if r.kind == 'app' else r.subtitle}")
