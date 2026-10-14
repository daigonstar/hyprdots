"""Full-screen settings editor built on prompt_toolkit (already needed by the assistant).

Keys: up/down move, Tab or left/right switch between the menu and the list, Enter edit, Space toggle,
- and + adjust numbers, r reset to default, Ctrl+S save, q quit, ? help.
All behaviour lives in App.handle_key / App.render, so it can be tested without a terminal."""

from __future__ import annotations

import os
import shutil
import signal
import subprocess
import sys
import textwrap
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from . import models
from .schema import BY_ID, PAGE_INTRO, PAGES, Setting, for_page
from .store import RESET, STARTUP_ID, Store

MENU_W = 20
STYLE = {
    "title": "bg:#1f6f8b #ffffff bold", "title.dirty": "bg:#c98a14 #000000 bold", "bar": "bg:#222222 #bbbbbb",
    "menu": "", "menu.sel": "bg:#1f6f8b #ffffff bold", "menu.focus": "bold", "group": "#6cc4dd bold", "dim": "#808080",
    "row.sel": "bg:#333a44 bold", "yours": "#7fd17f", "changed": "#e8b84a bold", "err": "#ff6b6b bold", "ok": "#7fd17f",
    "save": "bg:#c98a14 #000000 bold", "pending": "bg:#c98a14 #000000 bold",
    "help": "#cfcfcf", "popup": "bg:#1b1f24", "popup.sel": "bg:#1f6f8b #ffffff bold", "key": "#6cc4dd bold",
}


def state_dir() -> Path:
    return Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local/state")) / "hypr_agent"


def assistant_disabled() -> bool:
    return (state_dir() / "disabled").exists()


@dataclass
class Row:
    kind: str                     # header | setting | startup | source | action
    label: str = ""
    value: str = ""
    tag: str = ""                 # default | yours | changed
    setting: Setting | None = None
    ref: Any = None
    help: str = ""

    @property
    def selectable(self) -> bool:
        return self.kind not in ("header", "note")


@dataclass
class Popup:
    mode: str                     # choose | input | message | confirm | pull
    title: str = ""
    lines: list[str] = field(default_factory=list)
    items: list[tuple[Any, str, str]] = field(default_factory=list)    # value, label, detail
    index: int = 0
    text: str = ""
    cursor: int = 0
    error: str = ""
    on_select: Callable[[Any], None] | None = None
    on_submit: Callable[[str], None] | None = None
    on_confirm: Callable[[str], None] | None = None
    options: str = ""            # confirm: allowed keys, e.g. "ync"
    note: Callable[[Any], str] | None = None
    progress: float | None = None
    status: str = ""
    cancel: threading.Event | None = None


class App:
    def __init__(self, store: Store, size: tuple[int, int] = (110, 32)):
        self.store = store
        self.size = size
        self.page = 0
        self.menu_index = 0           # 0..len(PAGES)-1 are pages; len(PAGES) is the Save button
        self.focus = "menu"
        self.sel: dict[int, int] = {}
        self.popup: Popup | None = None
        self.notice = ""
        self.exit_action: str | None = None
        self.caps: dict[str, set[str]] = {}
        self.invalidate: Callable[[], None] = lambda: None
        self.exit_hook: Callable[[str], None] | None = None
        self.notice_error = False

    # ---- rows -----------------------------------------------------------------------------------------------
    def rows(self) -> list[Row]:
        page = PAGES[self.page]
        out: list[Row] = []
        for line in textwrap.wrap(PAGE_INTRO.get(page, ""), max(30, self.size[0] - MENU_W - 6)):
            out.append(Row("note", line))
        if out:
            out.append(Row("note", ""))
        if page == "Calendar":
            out.append(Row("header", "Calendars the assistant and the clock popup can read"))
            for i, src in enumerate(self.store.calendar_sources()):
                name, _, link = src.partition("|") if "|" in src else (f"calendar {i + 1}", "", src)
                out.append(Row("source", name.strip() or f"calendar {i + 1}", self._mask(link.strip()), "yours", ref=i,
                               help="Enter to rename, change the link, or remove this calendar. Links are private: they are only kept in "
                                    "user_settings.local.toml, which is never committed."))
            out.append(Row("action", "+ Add a calendar...", ref="add_calendar",
                           help="Paste the private iCal link (Google Calendar: Settings > your calendar > Integrate calendar > "
                                "Secret address in iCal format), or a path to a .ics file or folder."))
            return out
        last_group = None
        for s in for_page(page):
            if s.group and s.group != last_group:
                out.append(Row("header", s.group))
                last_group = s.group
            value, source = self.store.get(s)
            out.append(Row("setting", s.label, self._show(s, value), source, setting=s, help=s.help))
        if page == "Assistant":
            out.append(Row("header", "Turn on or off"))
            off = assistant_disabled()
            out.append(Row("action", "Assistant", "turned OFF" if off else "turned on", "changed" if off else "default", ref="toggle_assistant",
                           help="Enter to turn the assistant on or off. Off hides the bar button and Super+C shows a hint. "
                                "Models and packages are left alone. Applies immediately."))
        if page == "Hyprdots":
            apps = self.store.startup_apps()
            if apps:
                out.append(Row("header", "Start with the desktop (Space to switch)"))
                off = set(self.store.disabled_startup())
                for app in apps:
                    on = app["id"] not in off
                    out.append(Row("startup", app["label"], "on" if on else "off",
                                   "changed" if STARTUP_ID in self.store.staged else ("yours" if not on else "default"), ref=app["id"],
                                   help=f"Starts {app['cmd']} when Hyprland starts. Takes effect at your next login."))
            out.append(Row("header", "Files"))
            out.append(Row("action", "Open the raw settings files...", ref="edit_files",
                           help="Opens user_settings.toml (shared defaults) and user_settings.local.toml (yours) in your editor."))
        return out

    @staticmethod
    def _mask(link: str) -> str:
        if link.startswith(("http://", "https://", "webcal://")):
            host = link.split("//", 1)[1].split("/", 1)[0]
            return f"{host}  (link hidden)"
        return link

    @staticmethod
    def _show(s: Setting, value: Any) -> str:
        if s.kind == "bool":
            return "on" if value else "off"
        if s.kind in ("model",) and not value:
            return "(none)"
        if s.kind == "vision_model" and not value:
            return "None (image features off)"
        if s.kind == "vision_model" and value == "same":
            return "Same as chat model"
        if s.kind == "list":
            return ", ".join(value) if value else "(none)"
        if value == "":
            return "(empty)"
        for v, label in s.choices:
            if v == value and s.kind == "choice":
                return label.split("  (")[0].split(" (")[0]
        return f"{value}{(' ' + s.unit) if s.unit else ''}"

    def current_row(self) -> Row | None:
        rows = self.rows()
        i = self.sel.get(self.page, 0)
        selectable = [r for r in rows if r.selectable]
        if not selectable:
            return None
        return selectable[min(i, len(selectable) - 1)]

    # ---- keys -----------------------------------------------------------------------------------------------
    def handle_key(self, key: str, data: str = "") -> None:
        self._handle_key(key, data)

    def _handle_key(self, key: str, data: str = "") -> None:
        if self.popup:
            return self._popup_key(key, data)
        self.notice = ""
        if key in ("c-s", "s"):
            return self.save()
        if key in ("q", "escape", "c-c", "c-q"):
            return self.quit()
        if key == "?":
            return self.message("Keys", [
                "Up / Down      move", "Tab, Left, Right   switch between the menu and the list", "Enter          change the selected setting",
                "Space          switch an on/off setting", "- and +        adjust a number", "r              reset to the default",
                "Ctrl+S or s    save (or click [ Save changes ])", "q or Esc       quit", "Mouse: click a page, a setting, or Save", "",
                "Your changes are saved to user_settings.local.toml (private, never committed).",
                "The shared user_settings.toml holds the defaults and is left alone."])
        if key in ("tab",) or (key == "right" and self.focus == "menu") or (key == "left" and self.focus == "list"):
            self.focus = "list" if self.focus == "menu" else "menu"
            return
        if key == "up":
            self._move(-1)
        elif key == "down":
            self._move(1)
        elif key == "enter":
            if self.focus == "menu":
                if self.menu_index == len(PAGES):
                    self.save()
                else:
                    self.focus = "list"
            else:
                self.edit()
        elif self.focus == "list":
            row = self.current_row()
            if key == " ":
                if row and row.kind in ("setting", "startup"):
                    self.toggle(row)
            elif key in ("r", "R"):
                self.reset(row)
            elif key in ("-", "+", "="):
                self.nudge(row, -1 if key == "-" else 1)

    def _move(self, delta: int) -> None:
        if self.focus == "menu":
            self.menu_index = (self.menu_index + delta) % (len(PAGES) + 1)
            if self.menu_index < len(PAGES):
                self.page = self.menu_index
            return
        n = len([r for r in self.rows() if r.selectable])
        at = self.sel.get(self.page, 0)
        if delta > 0 and at >= n - 1:                 # Down past the last setting lands on the Save button
            self.focus, self.menu_index = "menu", len(PAGES)
            return
        self.sel[self.page] = max(0, min(n - 1, at + delta)) if n else 0

    # ---- editing ------------------------------------------------------------------------------------------
    def toggle(self, row: Row) -> None:
        if row.kind == "startup":
            self.store.set_startup(row.ref, row.value == "off")
        elif row.setting and row.setting.kind == "bool":
            self.store.stage(row.setting, not self.store.get(row.setting)[0])
        else:
            self.edit()

    def nudge(self, row: Row | None, direction: int) -> None:
        s = row.setting if row else None
        if not s or s.kind not in ("int", "float"):
            return
        value = self.store.get(s)[0]
        new = value + direction * s.step
        new = max(s.lo, min(s.hi, new)) if s.lo is not None and s.hi is not None else new
        self.store.stage(s, round(new, 3) if s.kind == "float" else int(new))

    def reset(self, row: Row | None) -> None:
        if not row:
            return
        if row.kind == "setting":
            self.store.reset(row.setting)
        elif row.kind == "startup":
            self.store.staged[STARTUP_ID] = RESET

    def edit(self) -> None:
        row = self.current_row()
        if not row:
            return
        if row.kind == "startup":
            return self.toggle(row)
        if row.kind == "action":
            return self.action(row.ref)
        if row.kind == "source":
            return self.source_menu(row.ref)
        s = row.setting
        if s.kind == "bool":
            return self.toggle(row)
        if s.kind in ("model", "vision_model"):
            return self.choose_model(s)
        if s.kind == "choice" or (s.kind == "text" and s.key in ("terminal", "file_manager", "browser", "store")):
            return self.choose_value(s)
        current = self.store.get(s)[0]
        text = ", ".join(current) if s.kind == "list" else str(current)
        hint = f"{s.lo:g} to {s.hi:g}" if s.lo is not None and s.hi is not None else ""
        self.ask(f"{s.label}" + (f"  ({hint}{' ' + s.unit if s.unit else ''})" if hint else ""), text,
                 lambda t, s=s: self._stage_text(s, t))

    def _stage_text(self, s: Setting, text: str) -> None:
        self.store.stage(s, text)   # raises ValueError for the input box to show

    def choose_value(self, s: Setting) -> None:
        current = self.store.get(s)[0]
        choices = list(self.store.app_choices(s)) if s.kind == "text" else [(v, label) for v, label in s.choices]
        if all(str(v) != str(current) for v, _ in choices):
            choices.insert(0, (current, f"{current}  (current)"))
        items = [(v, label, "") for v, label in choices]
        if s.allow_custom or s.kind == "text":
            items.append(("__custom__", "Something else...", ""))
        index = next((i for i, (v, _, _) in enumerate(items) if str(v) == str(current)), 0)

        def chosen(v):
            if v == "__custom__":
                self.ask(s.label, str(current), lambda t: self._stage_text(s, t))
            else:
                self.store.stage(s, v)
        self.popup = Popup("choose", s.label, [s.help], items, index, on_select=chosen)

    def choose_model(self, s: Setting) -> None:
        installed, err = models.installed()
        current = self.store.get(s)[0]
        vision = s.kind == "vision_model"
        names = [m["name"] for m in installed]
        sizes = {m["name"]: m["size_gb"] for m in installed}
        tier = models.recommend_tier(models.vram_mib())
        suggested = [models.TIERS[tier][1 if vision else 0]] + [t[1 if vision else 0] for t in models.TIERS.values()]
        items: list[tuple[Any, str, str]] = []
        chat_model = self.store.get(BY_ID["assistant.model"])[0]
        if vision:
            if chat_model and chat_model not in self.caps:
                self.caps[chat_model] = models.capabilities(chat_model)
            chat_sees = "vision" in self.caps.get(chat_model, set())
            same = ("same", "Same as chat model" + (f" ({chat_model})" if chat_model else ""), "no second model to load" if chat_sees else "")
            items.append(("none", "None - turn image features off", ""))
            items.insert(0 if chat_sees else 1, same)
        for n in names:
            items.append((n, n + ("  (current)" if n == current else ""), f"{sizes[n]} GB"))
        for n in dict.fromkeys(x for x in suggested if x and x not in names):
            items.append((f"pull:{n}", f"Download {n}", f"suggested for your GPU" if n == models.TIERS[tier][1 if vision else 0] else "popular choice"))
        items.append(("pull:?", "Download another model...", "any name from ollama.com/library"))
        index = next((i for i, (v, _, _) in enumerate(items) if v == (current or "none")), 0)
        lines = [s.help] + ([err] if err else [f"Your GPU suggests the '{tier}' size."])

        def chosen(v):
            if v == "pull:?":
                self.ask("Model to download (for example qwen3:8b)", "", lambda t: self.start_pull(s, t.strip()))
            elif isinstance(v, str) and v.startswith("pull:"):
                self.start_pull(s, v[5:])
            else:
                self.store.stage(s, v if v != "none" else "")

        def note(v):
            if not isinstance(v, str) or v.startswith("pull:") or v == "none":
                return ""
            if v == "same":
                seen = self.caps.get(chat_model)
                if seen is None:
                    return "checking whether your chat model can see images..."
                return (f"{chat_model} can read images, so one model does both." if "vision" in seen
                        else f"WARNING: {chat_model} does not report vision support, so images would fail.")
            caps = self.caps.get(v)
            if caps is None:
                return "checking what this model can do..."
            need = "vision" if vision else "tools"
            have = ", ".join(sorted(c for c in caps if c in ("tools", "vision", "thinking"))) or "unknown"
            return f"Abilities: {have}." + ("" if need in caps else f" WARNING: no {need} support reported, so this may not work here.")
        self.popup = Popup("choose", s.label, lines, items, index, on_select=chosen, note=note)
        self._fetch_caps(names)

    def _fetch_caps(self, names: list[str]) -> None:
        def work():
            for n in names:
                if n not in self.caps:
                    self.caps[n] = models.capabilities(n)
                    self.invalidate()
        threading.Thread(target=work, daemon=True).start()

    def start_pull(self, s: Setting, name: str) -> None:
        if not name:
            return
        cancel = threading.Event()
        popup = Popup("pull", f"Downloading {name}", ["Esc cancels the download."], status="starting...", cancel=cancel)
        self.popup = popup

        def progress(status, fraction):
            popup.status, popup.progress = status, fraction
            self.invalidate()

        def work():
            ok, msg = models.pull(name, progress, cancel)
            if ok:
                self.store.stage(s, name)
            if self.popup is popup:
                self.popup = None
            self.notice, self.notice_error = (f"{msg}. Press Ctrl+S to keep it." if ok else msg), not ok
            self.invalidate()
        threading.Thread(target=work, daemon=True).start()

    def ask(self, title: str, text: str, on_submit: Callable[[str], None], lines: list[str] | None = None) -> None:
        self.popup = Popup("input", title, lines or [], text=text, cursor=len(text), on_submit=on_submit)

    def message(self, title: str, lines: list[str]) -> None:
        self.popup = Popup("message", title, lines)

    def confirm(self, title: str, lines: list[str], options: str, on_confirm: Callable[[str], None]) -> None:
        self.popup = Popup("confirm", title, lines, options=options, on_confirm=on_confirm)

    # ---- calendars -----------------------------------------------------------------------------------------
    def action(self, name: str) -> None:
        if name == "toggle_assistant":
            return self.toggle_assistant()
        if name == "edit_files":
            self.exit_action = "edit"
            return
        if name == "add_calendar":
            def got_name(n):
                n = n.strip()
                self.ask("Calendar link or path", "", lambda link: self._add_calendar(n, link),
                         ["Paste the private iCal address (https://...) or a path to a .ics file or folder."])
            self.ask("Calendar name (for example Personal)", "", got_name)

    def _add_calendar(self, name: str, link: str) -> None:
        link = link.strip()
        if not link:
            raise ValueError("enter a link or a path")
        if "|" in name or "|" in link:
            raise ValueError("the | character cannot be used here")
        if "://" in link and not link.startswith(("http://", "https://", "webcal://")):
            raise ValueError("links must start with https:// or webcal://")
        self.store.set_calendar_sources([*self.store.calendar_sources(), f"{name or 'Calendar'}|{link}"])

    def source_menu(self, index: int) -> None:
        sources = self.store.calendar_sources()
        name, _, link = sources[index].partition("|")

        def chosen(v):
            if v == "rename":
                self.ask("New name", name, lambda t: self._edit_source(index, t.strip() or name, link))
            elif v == "link":
                self.ask("New link or path", "", lambda t: self._edit_source(index, name, t.strip()))
            elif v == "remove":
                self.confirm("Remove calendar?", [f"Remove '{name}' from the list? The calendar itself is not touched."], "yn",
                             lambda k: k == "y" and self.store.set_calendar_sources(sources[:index] + sources[index + 1:]))
        self.popup = Popup("choose", name, [], [("rename", "Rename", ""), ("link", "Change the link", ""), ("remove", "Remove", "")], 0, on_select=chosen)

    def _edit_source(self, index: int, name: str, link: str) -> None:
        if not link:
            raise ValueError("enter a link or a path")
        sources = self.store.calendar_sources()
        sources[index] = f"{name}|{link}"
        self.store.set_calendar_sources(sources)

    def toggle_assistant(self) -> None:
        marker = state_dir() / "disabled"
        if assistant_disabled():
            if not shutil.which("ollama"):
                return self.message("Assistant not installed", ["Ollama is not installed. Run:", "  ~/.config/hypr/assistant/setup.sh", "to set it up."])
            marker.unlink(missing_ok=True)
            self.notice = "Assistant turned on."
        else:
            marker.parent.mkdir(parents=True, exist_ok=True)
            marker.touch()
            self.notice = "Assistant turned off."
        subprocess.run(["pkill", "-SIGUSR2", "waybar"], capture_output=True)

    # ---- save / quit ---------------------------------------------------------------------------------------
    def save(self) -> None:
        if not self.store.dirty:
            self.notice = "Nothing to save."
            return
        try:
            effects = self.store.save()
        except Exception as e:  # a failed write must never look like success
            return self.message("Could not save", [str(e)])
        self.notice, self.notice_error = "Saved to user_settings.local.toml.", False
        if any("Hyprland" in e for e in effects) and shutil.which("hyprctl"):
            self.confirm("Reload Hyprland now?", ["Your Hyprland changes are saved.", "Reload now to see them? (windows stay open)"], "yn",
                         lambda k: k == "y" and self.reload_hyprland())
        elif effects:
            self.notice += " Takes effect " + ", ".join(effects) + "."

    def reload_hyprland(self) -> None:
        result = subprocess.run(["hyprctl", "reload"], capture_output=True, text=True)
        errors = subprocess.run(["hyprctl", "configerrors"], capture_output=True, text=True).stdout.strip()
        if errors and errors != "[]":
            self.message("Hyprland reported a problem", ["Hyprland reloaded but reported config errors:", errors[:600]])
        else:
            self.notice = "Hyprland reloaded." if result.returncode == 0 else "Could not reload Hyprland."

    def quit(self) -> None:
        if not self.store.dirty:
            self.exit_action = "quit"
            return

        def answer(k):
            if k == "y":
                self.save()
                if not self.store.dirty:
                    self.exit_action = "quit"
            elif k == "n":
                self.exit_action = "quit"
        self.confirm("Unsaved changes", ["You have changes that are not saved yet."], "ync", answer)

    # ---- popups ------------------------------------------------------------------------------------------------
    def _popup_key(self, key: str, data: str) -> None:
        p = self.popup
        assert p is not None
        if p.mode == "message":
            self.popup = None
        elif p.mode == "pull":
            if key in ("escape", "q", "c-c") and p.cancel:
                p.cancel.set()
        elif p.mode == "confirm":
            k = data.lower() if key not in ("escape", "enter") else ("c" if key == "escape" else "y")
            if k in p.options:
                self.popup = None
                if p.on_confirm:
                    p.on_confirm(k)
        elif p.mode == "choose":
            if key == "escape" or key == "q":
                self.popup = None
            elif key in ("up", "k"):
                p.index = (p.index - 1) % len(p.items)
            elif key in ("down", "j"):
                p.index = (p.index + 1) % len(p.items)
            elif key == "enter":
                value = p.items[p.index][0]
                self.popup = None
                if p.on_select:
                    p.on_select(value)
        elif p.mode == "input":
            self._input_key(p, key, data)

    def _input_key(self, p: Popup, key: str, data: str) -> None:
        if key == "escape" or key == "c-c":
            self.popup = None
        elif key == "enter":
            try:
                self.popup = None
                if p.on_submit:
                    p.on_submit(p.text)
            except ValueError as e:
                p.error = str(e)
                if self.popup is None:       # keep the box open so the mistake can be fixed
                    self.popup = p
        elif key == "backspace":
            if p.cursor:
                p.text, p.cursor = p.text[:p.cursor - 1] + p.text[p.cursor:], p.cursor - 1
        elif key == "delete":
            p.text = p.text[:p.cursor] + p.text[p.cursor + 1:]
        elif key == "left":
            p.cursor = max(0, p.cursor - 1)
        elif key == "right":
            p.cursor = min(len(p.text), p.cursor + 1)
        elif key in ("home", "c-a"):
            p.cursor = 0
        elif key in ("end", "c-e"):
            p.cursor = len(p.text)
        elif key == "c-u":
            p.text, p.cursor = "", 0
        elif data and data.isprintable() and key not in ("tab",):
            p.text, p.cursor, p.error = p.text[:p.cursor] + data + p.text[p.cursor:], p.cursor + len(data), ""

    # ---- rendering ----------------------------------------------------------------------------------------------
    # ---- mouse (every action also has a key) -----------------------------------------------------------------------
    def _mouse(self, action: Callable[[], None]):
        from prompt_toolkit.mouse_events import MouseEventType

        def handler(event):
            if event.event_type != MouseEventType.MOUSE_UP or self.popup:
                return None
            self.notice = ""
            action()
            self.invalidate()
            if self.exit_action and self.exit_hook:
                self.exit_hook(self.exit_action)
            return None
        return handler

    def click_page(self, index: int) -> None:
        self.page, self.menu_index, self.focus = index, index, "menu"

    def click_row(self, selectable_index: int) -> None:
        if self.focus == "list" and self.sel.get(self.page, 0) == selectable_index:
            self.edit()
        else:
            self.focus, self.sel[self.page] = "list", selectable_index

    def render(self):
        w, h = self.size
        frags: list[tuple] = []
        dirty = self.store.dirty
        pending = len(self.store.staged)
        title = " hypr-settings " + (f"   ● {pending} change{'s' if pending != 1 else ''} not saved yet" if dirty else "")
        frags.append(("class:title.dirty" if dirty else "class:title", title.ljust(w) + "\n"))
        body_h = h - 4
        rows = self.rows()
        sel_row = self.current_row()
        n_selectable = len([x for x in rows if x.selectable])
        marked_index = min(self.sel.get(self.page, 0), max(0, n_selectable - 1))
        selectable_idx = -1
        row_lines: list[tuple[Row, bool, int]] = []
        for r in rows:
            if r.selectable:
                selectable_idx += 1
            row_lines.append((r, r.selectable and selectable_idx == marked_index, selectable_idx))
        cursor_at = next((i for i, (_, sel, _) in enumerate(row_lines) if sel), 0)
        top = max(0, min(cursor_at - body_h // 2, max(0, len(row_lines) - body_h)))
        list_w = w - MENU_W - 3
        save_line = len(PAGES) + 1
        on_save = self.focus == "menu" and self.menu_index == len(PAGES)
        for line in range(body_h):
            menu, style, handler = "", "class:menu", None
            if line < len(PAGES):
                menu = f" {PAGES[line]}"
                handler = self._mouse(lambda i=line: self.click_page(i))
                if line == self.page:
                    style = "class:menu.sel" if (self.focus == "menu" and not on_save) else "class:menu.focus"
                    menu = f"›{PAGES[line]}"
            elif line == save_line:
                label = "[ Save changes ]" if dirty else "[ Nothing to save ]"
                menu = f"›{label}" if on_save else f" {label}"
                style = ("class:save" if dirty else "class:menu.sel") if on_save else ("class:save" if dirty else "class:dim")
                handler = self._mouse(self.save)
            elif line == save_line + 1 and dirty:
                menu = f"  {pending} pending (s)"
                style = "class:changed"
            frag = (style, menu.ljust(MENU_W)[:MENU_W]) + ((handler,) if handler else ())
            frags.append(frag)
            frags.append(("class:dim", " │ "))
            i = top + line
            if i < len(row_lines):
                r, marked, sidx = row_lines[i]
                row = self._row_frags(r, marked and self.focus == "list", marked, list_w)
                if r.selectable:
                    click = self._mouse(lambda k=sidx: self.click_row(k))
                    row = [(f[0], f[1], click) for f in row]
                frags += row
            frags.append(("", "\n"))
        frags.append(("class:dim", "─" * w + "\n"))
        if on_save:
            helptext = (f"Press Enter to save the {pending} pending change{'s' if pending != 1 else ''}." if dirty
                        else "Nothing to save yet. Change a setting first.")
        else:
            helptext = sel_row.help if sel_row and self.focus == "list" else "Choose a page on the left, then press Enter. Down from the last page reaches Save."
        wrapped = textwrap.wrap(helptext, w - 2) or [""]
        s = sel_row.setting if sel_row else None
        if s and self.focus == "list":
            wrapped = wrapped[:1] + [f"Takes effect {s.effect}."] if len(wrapped) > 1 else wrapped + [f"Takes effect {s.effect}."]
        frags.append(("class:help", " " + wrapped[0][:w - 2].ljust(w - 2) + "\n"))
        frags.append(("class:dim", " " + (wrapped[1] if len(wrapped) > 1 else "")[:w - 2].ljust(w - 2) + "\n"))
        if self.notice:
            frags.append(("class:err" if self.notice_error else "class:ok", (" " + self.notice).ljust(w)[:w], self._mouse(lambda: None)))
        elif dirty:
            many = f"{pending} change{'s' if pending != 1 else ''}"
            bar = (f" ● {many} not saved yet. Press Ctrl+S or s (or click [ Save changes ]) to keep them. q quits without saving."
                   if w >= 108 else f" ● {many} not saved. Press Ctrl+S or s to save · q quits without saving.")
            frags.append(("class:pending", bar.ljust(w)[:w], self._mouse(self.save)))
        else:
            frags.append(("class:bar", " Enter change · Space toggle · -/+ adjust · r reset · s save · ? help · q quit · mouse works too".ljust(w)[:w]))
        if self.popup:
            return self._with_popup(frags)
        return frags

    def _row_frags(self, r: Row, selected_row: bool, marked: bool, width: int):
        if r.kind == "note":
            return [("class:dim", ("  " + r.label).ljust(width)[:width])]
        if r.kind == "header":
            return [("class:group", ("  " + r.label).ljust(width)[:width])]
        label_w = min(32, max(14, width // 2))
        tag = {"yours": "yours", "changed": "● changed", "default": ""}.get(r.tag, r.tag)
        tag_w = 11 if width >= 60 else 0
        room = max(4, width - label_w - tag_w)
        value = r.value
        if len(value) > room - 1:
            value = value[:max(1, room - 2)] + "…"
        base = "class:row.sel" if selected_row else ""
        tag_style = {"yours": "class:yours", "changed": "class:changed"}.get(r.tag, "class:dim")
        pointer = "›" if marked else " "
        parts = [(base, f" {pointer} {r.label}".ljust(label_w)[:label_w]), (base, value.ljust(room)[:room])]
        if tag_w:
            parts.append((f"{base} {tag_style}".strip() if base else tag_style, f" {tag}".ljust(tag_w)[:tag_w]))
        return parts

    def _with_popup(self, frags):
        w, h = self.size
        p = self.popup
        assert p is not None
        pw = min(w - 6, 84)
        lines: list[tuple[str, str]] = []
        wrapped = [row for text in p.lines for row in (textwrap.wrap(text, pw - 4) or [""])]
        if p.mode == "choose":
            shown = min(len(p.items), h - 10 - len(wrapped))
            start = max(0, min(p.index - shown // 2, len(p.items) - shown))
            for i in range(start, start + shown):
                v, label, detail = p.items[i]
                text = f" {'›' if i == p.index else ' '} {label}"
                text = text.ljust(pw - 4 - len(detail)) + detail
                lines.append(("class:popup.sel" if i == p.index else "class:popup", text[:pw - 2].ljust(pw - 2)))
            if p.note:
                lines.append(("class:dim", (" " + p.note(p.items[p.index][0]))[:pw - 2].ljust(pw - 2)))
            hint = "Enter select · Esc cancel"
        elif p.mode == "input":
            text = p.text[:p.cursor] + "▏" + p.text[p.cursor:]
            lines.append(("class:key", (" > " + text)[:pw - 2].ljust(pw - 2)))
            if p.error:
                lines.append(("class:err", (" " + p.error)[:pw - 2].ljust(pw - 2)))
            hint = "Enter accept · Esc cancel · Ctrl+U clear"
        elif p.mode == "pull":
            bar = ""
            if p.progress is not None:
                filled = int(p.progress * (pw - 12))
                bar = "█" * filled + "░" * (pw - 12 - filled) + f" {int(p.progress * 100):3d}%"
            lines.append(("class:popup", (" " + p.status)[:pw - 2].ljust(pw - 2)))
            lines.append(("class:ok", (" " + bar)[:pw - 2].ljust(pw - 2)))
            hint = "Esc cancel"
        elif p.mode == "confirm":
            labels = {"y": "y yes", "n": "n no", "c": "c cancel"}
            hint = " · ".join(labels[o] for o in p.options)
        else:
            hint = "Press any key"
        box = [("class:key", f" {p.title} ".center(pw, "─"))]
        box += [("class:popup", " " + t.ljust(pw - 3)) for t in wrapped]
        box += lines
        box.append(("class:dim", f" {hint} ".center(pw, "─")))
        # draw the popup over the page: replace the middle lines of the existing output
        text_lines: list[list[tuple[str, str]]] = [[]]
        for frag in frags:
            style, text = frag[0], frag[1]
            parts = text.split("\n")
            for j, part in enumerate(parts):
                if j:
                    text_lines.append([])
                if part:
                    text_lines[-1].append((style, part))
        top = max(1, (h - len(box)) // 2)
        left = (w - pw) // 2
        for k, (style, text) in enumerate(box):
            idx = top + k
            if idx < len(text_lines):
                text_lines[idx] = [("", " " * left), (style, text.ljust(pw)[:pw])]
        out: list[tuple[str, str]] = []
        for k, line in enumerate(text_lines):
            out += line
            if k < len(text_lines) - 1:
                out.append(("", "\n"))
        return out

    def render_plain(self) -> str:
        return "".join(frag[1] for frag in self.render())


# ---- terminal glue -----------------------------------------------------------------------------------------------
def run(store: Store | None = None, input=None, output=None) -> str:
    """Runs the full-screen app. Returns the exit action ('quit' or 'edit')."""
    from prompt_toolkit import Application
    from prompt_toolkit.formatted_text import to_formatted_text
    from prompt_toolkit.key_binding import KeyBindings
    from prompt_toolkit.keys import Keys
    from prompt_toolkit.layout import Layout, Window
    from prompt_toolkit.layout.controls import FormattedTextControl
    from prompt_toolkit.styles import Style

    app = App(store or Store())
    kb = KeyBindings()

    @kb.add(Keys.Any)
    def _(event):
        press = event.key_sequence[0]
        key = press.key.value if hasattr(press.key, "value") else str(press.key)
        app.handle_key(key if key != "<any>" else press.data, press.data)
        app_obj.invalidate()
        if app.exit_action:
            event.app.exit(result=app.exit_action)

    for name in ("up", "down", "left", "right", "enter", "tab", "escape", "backspace", "delete", "home", "end",
                 "c-s", "c-c", "c-u", "c-a", "c-e", "c-q"):
        kb.add(name, eager=True)(lambda event, name=name: _dispatch(event, name))

    def _dispatch(event, name):
        data = {"enter": "\r", "tab": "\t"}.get(name, "")
        app.handle_key(name, data)
        app_obj.invalidate()
        if app.exit_action:
            event.app.exit(result=app.exit_action)

    def content():
        try:
            size = app_obj.output.get_size()
            app.size = (max(60, size.columns), max(16, size.rows))
        except Exception:
            pass
        return to_formatted_text(app.render())

    window = Window(FormattedTextControl(content, focusable=True, show_cursor=False))
    app_obj = Application(layout=Layout(window), key_bindings=kb, style=Style.from_dict(STYLE), full_screen=True, mouse_support=True,
                          input=input, output=output)
    app.invalidate = app_obj.invalidate
    app.exit_hook = lambda action: app_obj.exit(result=action)
    return app_obj.run() or "quit"


def main() -> int:
    if not sys.stdin.isatty():
        print("hypr-settings needs a terminal.", file=sys.stderr)
        return 1
    while True:
        store = Store()
        action = run(store)
        if action != "edit":
            return 0
        editor = os.environ.get("EDITOR") or shutil.which("nano") or "vi"
        subprocess.run([editor, str(store.shared_path), str(store.local_path)])
