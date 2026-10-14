"""Reads and writes settings. Effective value = your local file, else the shared user_settings.toml, else
the schema default. Edits are staged in memory and written together on save."""

from __future__ import annotations

import os
import shutil
from pathlib import Path
from typing import Any

from . import overrides, tomledit
from .schema import APP_CANDIDATES, BY_ID, SETTINGS, Setting

RESET = object()  # staged marker: remove the key from the local file
STARTUP_ID = "hyprdots.startup_disabled"


def default_hypr_dir() -> Path:
    env = os.environ.get("HYPR_SETTINGS_DIR")
    return Path(env) if env else Path(__file__).resolve().parents[2]


class Store:
    def __init__(self, hypr_dir: Path | str | None = None):
        self.dir = Path(hypr_dir) if hypr_dir else default_hypr_dir()
        self.shared_path = self.dir / "user_settings.toml"
        self.local_path = self.dir / "user_settings.local.toml"
        self.overrides_path = self.dir / "user_overrides.lua"
        self.autostart_path = self.dir / "autostart.lua"
        self.staged: dict[str, Any] = {}
        self.warnings: list[str] = []
        self.reload()

    # ---- loading -------------------------------------------------------------------------------------
    def reload(self) -> None:
        self.warnings = []
        self.shared = self._safe_read(self.shared_path)
        self.local = self._safe_read(self.local_path)
        self.staged = {}

    def _safe_read(self, path: Path) -> dict:
        try:
            return tomledit.read(path)
        except tomledit.TomlError as e:
            self.warnings.append(f"Could not read {path.name} ({e}); it is being ignored until fixed.")
            return {}

    # ---- values ------------------------------------------------------------------------------------------
    def _from(self, tree: dict, s: Setting):
        value = tree.get(s.section, {}).get(s.key)
        if value is None:
            return None
        try:
            return self.coerce(s, value)
        except ValueError:
            self.warnings.append(f"{s.id} has an invalid value ({value!r}) in your settings; showing the default instead.")
            return None

    def default(self, s: Setting):
        shared = self._from(self.shared, s)
        return s.default if shared is None else shared

    def get(self, s: Setting) -> tuple[Any, str]:
        """(value, source) where source is 'changed' (unsaved), 'yours' or 'default'."""
        if s.id in self.staged:
            staged = self.staged[s.id]
            return (self.default(s), "default") if staged is RESET else (staged, "changed")
        mine = self._from(self.local, s)
        return (mine, "yours") if mine is not None else (self.default(s), "default")

    def stage(self, s: Setting, value: Any) -> None:
        value = self.coerce(s, value)
        self.staged[s.id] = RESET if value == self.default(s) else value

    def reset(self, s: Setting) -> None:
        self.staged[s.id] = RESET

    @property
    def dirty(self) -> bool:
        return bool(self.staged)

    # ---- validation ----------------------------------------------------------------------------------------
    def coerce(self, s: Setting, raw: Any):
        k = s.kind
        if k == "bool":
            if isinstance(raw, bool):
                return raw
            if str(raw).strip().lower() in ("true", "yes", "on", "1"):
                return True
            if str(raw).strip().lower() in ("false", "no", "off", "0"):
                return False
            raise ValueError("choose on or off")
        if k in ("int", "float") or (k == "choice" and isinstance(s.default, (int, float)) and not isinstance(s.default, bool)):
            cast = float if (k == "float") else int
            try:
                if isinstance(raw, bool):
                    raise ValueError
                value = cast(str(raw).strip()) if isinstance(raw, str) else cast(raw)
            except ValueError:
                raise ValueError(f"enter a number{' (whole)' if cast is int else ''}") from None
            if k != "choice":
                if s.lo is not None and value < s.lo or s.hi is not None and value > s.hi:
                    raise ValueError(f"must be between {s.lo:g} and {s.hi:g}{s.unit and ' ' + s.unit}")
            elif value <= 0 and s.key == "num_ctx":
                raise ValueError("must be a positive number")
            return round(value, 3) if cast is float else value
        if k == "list":
            items = raw if isinstance(raw, list) else [x.strip() for x in str(raw).split(",")]
            return [x for x in items if x]
        text = str(raw).strip()
        if k in ("model", "vision_model"):
            if not text and k == "model":
                raise ValueError("a chat model is required")
            return "" if text.lower() == "none" else ("same" if text.lower() == "same" else text)
        if k == "choice" and not s.allow_custom and s.choices and text not in {str(v) for v, _ in s.choices}:
            raise ValueError("pick one of the listed options")
        if k == "text" and s.key in {"terminal", "file_manager", "browser", "store"} and not text:
            raise ValueError("enter a command")
        return text

    # ---- startup apps (a list in the file, a checkbox per app in the UI) ---------------------------------
    def startup_apps(self) -> list[dict]:
        return overrides.startup_apps(self.autostart_path)

    def disabled_startup(self) -> list[str]:
        if STARTUP_ID in self.staged:
            value = self.staged[STARTUP_ID]
            return [] if value is RESET else list(value)
        return list(self.local.get("hyprdots", {}).get("startup_disabled", []))

    def set_startup(self, app_id: str, enabled: bool) -> None:
        current = set(self.disabled_startup())
        (current.discard if enabled else current.add)(app_id)
        self.staged[STARTUP_ID] = sorted(current) if current else RESET

    # ---- calendar sources (private, only ever in the local file) --------------------------------------------
    def calendar_sources(self) -> list[str]:
        key = "calendar.sources"
        if key in self.staged:
            return [] if self.staged[key] is RESET else list(self.staged[key])
        return [str(x) for x in self.local.get("calendar", {}).get("sources", [])]

    def set_calendar_sources(self, sources: list[str]) -> None:
        self.staged["calendar.sources"] = list(sources) if sources else RESET

    # ---- app suggestions -------------------------------------------------------------------------------------
    def app_choices(self, s: Setting) -> list[tuple[str, str]]:
        seen, out = set(), []
        for cmd in [self.default(s), *APP_CANDIDATES.get(s.key, [])]:
            first = cmd.split()[0]
            if cmd not in seen and (cmd == self.default(s) or shutil.which(first)):
                seen.add(cmd)
                out.append((cmd, cmd + ("  (default)" if cmd == self.default(s) else "")))
        return out

    # ---- saving -----------------------------------------------------------------------------------------------
    def save(self) -> list[str]:
        """Writes staged changes. Returns what the user should do for them to take effect."""
        touched_lua = False
        for sid, value in list(self.staged.items()):
            if sid in ("calendar.sources", STARTUP_ID):
                section, key = sid.split(".", 1)
                touched_lua |= sid == STARTUP_ID
            else:
                s = BY_ID[sid]
                section, key = s.section, s.key
                touched_lua |= s.section in ("hyprland", "hyprdots")
            if value is RESET:
                tomledit.unset(self.local_path, section, key)
            else:
                tomledit.set_value(self.local_path, section, key, value)
        self.local = self._safe_read(self.local_path)
        if touched_lua or not self.overrides_path.exists():
            self.write_overrides()
        effects = sorted({BY_ID[sid].effect for sid in self.staged if sid in BY_ID})
        self.staged = {}
        return effects

    def write_overrides(self) -> None:
        config, apps = [], {}
        for s in SETTINGS:
            if s.section == "hyprland":
                value = self._from(self.local, s)
                if value is not None and value != self.default(s):
                    config.append((s.lua, value))
            elif s.section == "hyprdots":
                value = self._from(self.local, s)
                if value is not None and value != self.default(s):
                    apps[s.key] = value
        overrides.write(self.overrides_path, overrides.render(config, apps, self.disabled_startup()))
