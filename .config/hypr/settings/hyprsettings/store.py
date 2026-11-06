"""Reads and writes settings. Effective value = your local file, else the shared user_settings.toml, else
the schema default. Edits are staged in memory and written together on save."""

from __future__ import annotations

import math
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any

from . import account, keyspec, overrides, tomledit
from .schema import APP_CANDIDATES, BY_ID, GTK_NOW, INSTALLED_CHOICES, SETTINGS, Setting

RESET = object()  # staged marker: remove the key from the local file
STARTUP_ID = "hyprdots.startup_disabled"
CUSTOM_STARTUP_ID = "hyprdots.startup_custom"  # your own startup apps: "Label|command" strings
KB_PREFIX = "keybinds."  # staged id for one keybind: keybinds.<id>


def default_hypr_dir() -> Path:
    env = os.environ.get("HYPR_SETTINGS_DIR")
    return Path(env) if env else Path(__file__).resolve().parents[2]


def _can_start(app: dict) -> bool:
    program = app["cmd"].split()[0]
    if program.startswith("~/") and "openrgb" in program:
        program = "openrgb"
    return program.startswith("~/") or shutil.which(program) is not None


class Store:
    def __init__(self, hypr_dir: Path | str | None = None):
        self.dir = Path(hypr_dir) if hypr_dir else default_hypr_dir()
        self.shared_path = self.dir / "user_settings.toml"
        self.local_path = self.dir / "user_settings.local.toml"
        self.overrides_path = self.dir / "user_overrides.lua"
        self.autostart_path = self.dir / "autostart.lua"
        self.keybinds_path = self.dir / "keybinds.lua"
        self.staged: dict[str, Any] = {}
        self.warnings: list[str] = []
        self.reload()

    # ---- loading -------------------------------------------------------------------------------------
    def reload(self) -> None:
        self.warnings = []
        self.shared = self._safe_read(self.shared_path)
        self.local = self._safe_read(self.local_path)
        self.staged = {}
        self._gtk: dict | None = None

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
        if shared is None and s.id in GTK_NOW:
            return self._gtk_now().get(GTK_NOW[s.id], s.default)
        return s.default if shared is None else shared

    def _gtk_now(self) -> dict:
        """What GTK uses now, as the Theme page's Apps values (read once). The adw-gtk3 style the Theme page sets
        itself is not offered as your own style."""
        if self._gtk is None:
            from . import gtktheme
            now = gtktheme.current()
            family, size = gtktheme.font_parts(now["font"])
            self._gtk = {**now, "font": family}
            try:
                self._gtk["font_size"] = int(float(size))
                self._gtk["cursor_size"] = int(float(now["cursor_size"]))
            except ValueError:
                self._gtk.pop("font_size", None)
                self._gtk.pop("cursor_size", None)
            if str(now["theme"]).startswith("adw-gtk3"):
                self._gtk.pop("theme")
        return self._gtk

    def choices(self, s: Setting) -> list[tuple]:
        """(value, label) pairs to pick from: the schema's, or what is installed."""
        if s.kind == "text":
            return self.app_choices(s)
        if s.id in INSTALLED_CHOICES:
            from . import gtktheme
            return [(n, n) for n in getattr(gtktheme, INSTALLED_CHOICES[s.id])()]
        return list(s.choices)

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
        if k == "palette":
            from .design import PALETTE
            if str(raw).strip() not in PALETTE:
                raise ValueError("pick one of the palette colours")
            return str(raw).strip()
        if k == "font":
            if not str(raw).strip() or '"' in str(raw):
                raise ValueError("pick a font")
            return str(raw).strip()
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
            if not math.isfinite(value):  # float() takes "nan" and "inf", which would break the generated Lua
                raise ValueError("enter a number")
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
        if k == "mode_model":
            return "" if text.lower() in ("", "same", "none") else text
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
        """The ones you can start: an app you did not install has nothing to switch on."""
        return [a for a in overrides.startup_apps(self.autostart_path) if _can_start(a)]

    def disabled_startup(self) -> list[str]:
        if STARTUP_ID in self.staged:
            value = self.staged[STARTUP_ID]
            return [] if value is RESET else list(value)
        return list(self.local.get("hyprdots", {}).get("startup_disabled", []))

    def set_startup(self, app_id: str, enabled: bool) -> None:
        current = set(self.disabled_startup())
        (current.discard if enabled else current.add)(app_id)
        self.staged[STARTUP_ID] = sorted(current) if current else RESET

    # Your own startup apps, added here rather than in autostart.lua: removing one takes it off the list
    def custom_startup(self) -> list[dict]:
        """[{label, cmd}] in the order you added them."""
        if CUSTOM_STARTUP_ID in self.staged:
            value = self.staged[CUSTOM_STARTUP_ID]
            raw = [] if value is RESET else list(value)
        else:
            raw = self.local.get("hyprdots", {}).get("startup_custom", [])
        out = []
        for item in raw if isinstance(raw, list) else []:
            label, sep, cmd = str(item).partition("|")
            if sep and label.strip() and cmd.strip():
                out.append({"label": label.strip(), "cmd": cmd.strip()})
        return out

    def _set_custom_startup(self, apps: list[dict]) -> None:
        self.staged[CUSTOM_STARTUP_ID] = [f"{a['label']}|{a['cmd']}" for a in apps] if apps else RESET

    def add_startup(self, label: str, cmd: str) -> None:
        """Raises ValueError, in words, for the add dialog to show."""
        label, cmd = label.strip(), cmd.strip()
        if not label:
            raise ValueError("enter a name for it")
        if not cmd:
            raise ValueError("enter the command that starts it")
        if "|" in label or any(c in label + cmd for c in "\n\r"):
            raise ValueError("the name cannot contain |, and neither can be more than one line")
        program = os.path.expanduser(cmd.split()[0])
        if not (shutil.which(program) or (os.sep in program and os.access(program, os.X_OK))):
            raise ValueError(f"cannot find the program '{cmd.split()[0]}'. Check it is installed, or give its full path")
        apps = self.custom_startup()
        if any(a["label"].lower() == label.lower() for a in apps) or \
                any(a["label"].lower() == label.lower() for a in overrides.startup_apps(self.autostart_path)):
            raise ValueError(f"there is already a startup app called '{label}'")
        self._set_custom_startup([*apps, {"label": label, "cmd": cmd}])

    def remove_startup(self, index: int) -> None:
        apps = self.custom_startup()
        if 0 <= index < len(apps):
            self._set_custom_startup(apps[:index] + apps[index + 1:])

    # ---- calendar sources (private, only ever in the local file) --------------------------------------------
    def calendar_sources(self) -> list[str]:
        key = "calendar.sources"
        if key in self.staged:
            return [] if self.staged[key] is RESET else list(self.staged[key])
        return [str(x) for x in self.local.get("calendar", {}).get("sources", [])]

    def set_calendar_sources(self, sources: list[str]) -> None:
        self.staged["calendar.sources"] = list(sources) if sources else RESET

    # ---- keybinds (listed in keybinds.lua, your choices saved under [keybinds] in the local file) ---------
    def keybind_rows(self) -> list[dict]:
        return overrides.keybind_rows(self.keybinds_path)

    def get_keybind(self, row: dict) -> tuple[str, str]:
        """(keys, source) where source is 'changed' (unsaved), 'yours' or 'default'."""
        sid = KB_PREFIX + row["id"]
        if sid in self.staged:
            staged = self.staged[sid]
            return (row["keys"], "default") if staged is RESET else (staged, "changed")
        mine = self.local.get("keybinds", {}).get(row["id"])
        if isinstance(mine, str) and mine.strip():
            return mine, "yours"
        return row["keys"], "default"

    def stage_keybind(self, row: dict, text: str) -> None:
        keys = keyspec.normalize(text)  # raises ValueError for the input box to show
        if keys != "none":
            if keyspec.is_reserved(keys):
                raise ValueError(f"{keys} is used for workspaces, the mouse or the media keys and cannot be reused. Pick another.")
            for other in self.keybind_rows():
                if other["id"] != row["id"] and keyspec.canon(self.get_keybind(other)[0]) == keyspec.canon(keys):
                    raise ValueError(f"{keys} is already used for '{other['label']}'. Change or unbind that one first.")
        same = keyspec.canon(keys) == keyspec.canon(row["keys"])
        self.staged[KB_PREFIX + row["id"]] = RESET if same else keys

    def reset_keybind(self, row: dict) -> None:
        self.staged[KB_PREFIX + row["id"]] = RESET

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
            if sid in ("calendar.sources", STARTUP_ID, CUSTOM_STARTUP_ID):
                section, key = sid.split(".", 1)
                touched_lua |= sid in (STARTUP_ID, CUSTOM_STARTUP_ID)
            elif sid.startswith(KB_PREFIX):
                section, key = "keybinds", sid[len(KB_PREFIX):]
                touched_lua = True
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
        if any(sid.startswith("power.") for sid in self.staged):
            from . import idle  # hypridle.local.conf is built from these settings
            try:
                path = idle.write(self.dir, idle.render(*(self.get(BY_ID[f"power.{k}"])[0] for k in
                                                          ("lock_after", "screen_off_after", "suspend_after", "lock_before_sleep", "lock_screens"))))
                idle.restart(path)
            except OSError as e:
                self.warnings.append(f"Saved, but the idle settings could not be applied: {e}")
        if any(sid.startswith("theme.") for sid in self.staged):
            from . import design  # the bar, notifications, rofi, window borders and the lock screen use these
            for problem in design.refresh_all(self):
                self.warnings.append(f"Saved, but the {problem}")
        if any(sid.startswith("lockscreen.") for sid in self.staged):
            from . import lockscreen  # hyprlock.local.conf is built from these settings
            try:
                from . import design
                accent = design.resolved(design.theme_options(self))["accent"]  # the password line follows the Theme page
                lockscreen.write(lockscreen.local_path(self.dir), lockscreen.render(self.lock_options(), accent=accent))
            except OSError as e:
                self.warnings.append(f"Saved, but the lock screen could not be updated: {e}")
        if any(sid.startswith("cloud.") for sid in self.staged):
            from . import cloud  # mount flags come from these settings; drives use them from their next restart
            try:
                cloud.refresh_unit()
            except OSError as e:
                self.warnings.append(f"Saved, but the cloud drive service could not be updated: {e}")
        effects = {BY_ID[sid].effect for sid in self.staged if sid in BY_ID}
        if any(sid.startswith(KB_PREFIX) for sid in self.staged):
            effects.add("when Hyprland reloads")
        effects = sorted(effects)
        self.staged = {}
        return effects

    def lock_options(self) -> dict:
        """The lock screen settings as they stand, including unsaved changes (the Preview button uses this)."""
        options = {s.key: self.get(s)[0] for s in SETTINGS if s.section == "lockscreen"}
        if account.picture_path().exists():
            options["picture"] = str(account.picture_path())
        return options

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
        keybinds = {}
        for row in self.keybind_rows():
            value = self.local.get("keybinds", {}).get(row["id"])
            if isinstance(value, str) and value.strip():
                try:
                    value = keyspec.normalize(value)
                except ValueError:
                    self.warnings.append(f"Keybind '{row['id']}' has an invalid value ({value!r}); using the default.")
                    continue
                if keyspec.canon(value) != keyspec.canon(row["keys"]):
                    keybinds[row["id"]] = value
        overrides.write(self.overrides_path, overrides.render(config, apps, self.disabled_startup(), keybinds, self.custom_startup()))
        self.sync_terminal(apps.get("terminal") or self.default(BY_ID["hyprdots.terminal"]))

    def sync_terminal(self, terminal: str) -> None:
        """Thunar and other Xfce-style apps need to be told the terminal (see scripts/exo-terminal.sh)."""
        script = self.dir / "scripts" / "exo-terminal.sh"
        if script.exists():
            try:
                subprocess.run([str(script), terminal], capture_output=True, timeout=10)
            except (OSError, subprocess.SubprocessError):
                pass
