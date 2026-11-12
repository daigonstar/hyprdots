# Inventory: Python and shell programs (Phase 0 of the Rust migration)

Taken 2026-11-12 from `main` at `4ead7de`. Line counts exclude tests unless stated. "Portable" means the logic could run on
Windows and macOS; "Linux" means it is tied to Hyprland, Wayland, systemd, PipeWire or `/proc`; "UI" means it is a
window and its toolkit matters.

## 0. What the plan got wrong or did not know

Read this first. These change scope or order, and need a decision before Phase 1.

1. **The repo is about four times larger than the plan assumed.** ~36,000 lines of Python outside tests (+9,700 lines
   of tests) and ~2,500 lines of shell. The plan covers the assistant (12.4k) and three overlays. Not in the plan at
   all: the **Settings app** (12.2k, a second full GTK4/libadwaita GUI *and* a 1.5k-line prompt_toolkit TUI), the
   **quick tray** with Alt+Tab, overview and tablet mode (3.1k, GTK **3**), the **Sound app** (1.9k), the **installer
   TUI** and the root **power daemon** (1.2k), the keybind **cheatsheet**, the Mac-style **dock**, the **popup
   calendar** (GTK 3), the **welcome** window and **game-autoworkspace**. See section 7 for which to include.
2. **Clipboard history already exists.** `SUPER + CTRL + C` runs `clipvault list | rofi -dmenu | clipvault get |
   wl-copy`, fed by `wl-paste --watch clipvault store` in `autostart.lua`. clipvault is a persistent store with
   dedupe already. Phase 4 (`clipboardd`) is therefore a replacement, not a new feature.
3. **Keybinds differ from the plan.** `SUPER + C` is Hearthling (the assistant), not the clipboard. Clipboard is
   `SUPER + CTRL + C`, wallpaper is `SUPER + W` (not `SUPER + SHIFT + W`), emoji is `SUPER + period`
   (rofimoji + wtype), notes is `SUPER + I`, launcher `SUPER + SPACE`. Binds are rebindable from Settings
   (`keybinds.lua` reads `custom_keys` from `user_overrides.lua`), so a new binary keeps the bind **id**, not the key.
4. **Launcher, power menu and wallpaper picker are already GTK4 + gtk4-layer-shell in Python**, not rofi. rofi remains
   only as fallback (`rofi/wallpaper/wallpaper.sh` hands off to `launcher/wallpicker.sh` when it can) and for the
   clipboard and emoji pickers.
5. **There are two settings loaders.** `assistant/usersettings.py` (52 lines: 4 sections, strict typed defaults) and
   `settings/hyprsettings/store.py` + `schema.py` (120 settings across many sections, comment-preserving writes via
   `tomledit.py`, plus GTK-derived values). The `settings` crate must match both. Reading is the easy half; the
   Settings app *writes* the TOML and keeps comments.
6. **Not every private value is in `user_settings.local.toml`.** Calendar links are, but the agent also reads
   `~/.local/state/hypr_agent/calendar_sources.txt`, and both names are in the agent's blocked list.
7. **Notes is only half moved.** The Rust build (`notes/rs`) is the window, but `notes.sh --append` still runs
   `notebook.py`, and `notes.py` remains as a fallback picked by `start.sh`. A parity test already makes Rust and
   Python agree on formatting.
8. **Theme roles come from wallust, not a fixed palette.** Each role (`design.py` `ROLES`) names a wallust slot
   (`color0`..`color15`, `foreground`, `background`) resolved from the current wallpaper's palette, plus opacities,
   fonts and bar style. There are also **theme overrides** (XP, Mac, Game UI, Sci-fi HUD) that rewrite GTK CSS, the bar
   and more (`theme_override.py`, `theme_parts.py`, `look_*.py`). The `theme` crate needs both.
9. **`apply_modes.py` is not an app.** It was a one-time patch to `hypr_agent.py`, already applied. Nothing to port.
10. **Live theme is file-based.** `livetheme.py` watches `~/.config/gtk-4.0/gtk.css` and reloads a CSS block. An iced
   app needs its own source of truth (the resolved roles), not GTK CSS.

## 1. Baseline test run

Run 2026-11-12 on this PC (Python 3.14.9, rustc 1.99.1). Everything passes; nothing is skipped.

| Suite | Command (from the folder) | Result |
|---|---|---|
| Assistant | `python3 -m unittest discover -s tests` in `.config/hypr/assistant` | 367 OK (now 368, see section 8) |
| Settings | same, in `.config/hypr/settings` | 235 OK |
| Quick tray | same, in `.config/hypr/tray` | 76 OK |
| Notes (Python) | same, in `.config/hypr/notes` | 18 OK |
| Sound | same, in `.config/hypr/audio` | 45 OK |
| Launcher | same, in `.config/hypr/launcher` | 62 OK |
| Installer | same, in `install` | 81 OK |
| Notes (Rust) | `cargo test --release --locked` in `.config/hypr/notes/rs` | 44 OK (23 unit + 21 parity) |

CI (`.github/workflows/ci.yml`) runs the same suites plus shellcheck, an installer dry run and a package-list check.

## 2. The assistant (`.config/hypr/assistant`, 12.4k lines, 368 tests)

| File | Lines | Purpose | Class | Tests |
|---|---|---|---|---|
| `hypr_agent.py` | 5,346 | The agent: Ollama chat loop, tools, approvals, blocked paths, web search/fetch, calendar parsing, memory, session transcript, slash commands, terminal UI (prompt_toolkit) | Portable core + Linux tools | `test_hypr_agent` (102), `test_calendar_and_guard` (54) |
| `agent_modes.py` | 277 | `/mode <name>`: per-mode prompt, tool set, model, caps | Portable | `test_mode_models` (5), via `test_dnd` |
| `apply_modes.py` | 155 | **A one-off source patcher** that added modes to `hypr_agent.py`. Already applied (the agent imports `agent_modes`) and referenced nowhere else: **do not port**; candidate for `legacy/` | n/a | none |
| `dnd_mode.py` | 2,071 | Hidden Dungeon Master mode: 2024 rules, campaign record, combat, dice, journal, `dnd_*` tools | Portable | `test_dnd` (138) |
| `dnd_library.py` | 166 | Player's own rulebooks, indexed for lookup | Portable | via `test_dnd` |
| `dnd_ui.py` | 768 | Dice tray and character builder widgets (GTK4, cairo) | UI | **none** |
| `hypr_assistant_app.py` | 3,031 | Hearthling window: GTK4 + libadwaita + optional VTE 3.91 | UI | `test_app` (40) |
| `localcal.py` | 226 | Local events in one `.ics` file shared with clock popup and Settings | Portable | `test_localcal` (5) |
| `agent_monitor.py` | 274 | Periodic health check (systemd timer `agent-monitor.timer`), notifies and writes a report | Linux | **none** |
| `usersettings.py` | 52 | Reads `user_settings.toml` + `.local` | Portable | `test_usersettings` (new) |
| `setup.sh` | 350 | Turns the assistant on/off, installs Ollama and models, writes `agent_context.md` | Linux, install | `test_setup` (13) |

**Python dependencies:** `ollama`, `prompt_toolkit`, PyGObject (Gtk 4.0, Adw 1, GdkPixbuf 2.0, Vte 3.91 optional),
pycairo; `icalendar` + `recurring_ical_events` (calendar, also in tests).

**External commands (agent):** `ollama`, `hyprctl`, `notify-send`, `grim` (screenshot), `wl-paste`, `systemctl`,
`journalctl`, `coredumpctl`, `pacman`, `paru`, `flatpak`, `df`, `free`, `nvidia-smi`, `bash` (run_command). The window
adds `xdg-open`. The monitor adds `gamemoded`.

**Files read/written** (state dir `~/.local/state/hypr_agent`, mode 0700, files 0600):
`memory.md`, `health.txt`, `notified.json`, `failures.log`, `session_summary.md`, `calendar_sources.txt`,
`dnd/` (campaign: `campaign.json` with a last-good copy, `transcript.jsonl`), `dnd_library/`, `dnd-archive-*`;
`$XDG_RUNTIME_DIR/hypr_agent_session_*.jsonl` (per-session transcript, deleted at exit),
`$XDG_RUNTIME_DIR/hypr_agent_screen.png`, `$XDG_RUNTIME_DIR/hypr_agent_paste`; `agent_context.md` next to the code
(git-ignored); the `disabled` marker read by `assistant-toggle.sh`.

**Agent tools (22):** `list_windows`, `focus_window`, `move_to_workspace`, `toggle_special_workspace`,
`screenshot_analysis`, `ask_about_image`, `system_info`, `performance_snapshot`, `pending_updates`, `health_report`,
`crash_report`, `remember`, `forget`, `web_search`, `news_search`, `web_fetch`, `calendar_events`, `date_info`,
`run_command`, `write_file`, `read_terminal`, `ask_user_to_run`. Plus the `dnd_*` set in `dnd_mode.TOOL_NAMES`.
The first eight and `pending_updates`/`crash_report` are Linux-only.

**Slash commands:** `/help`, `/mode`, `/calendar`, `/paste`, `/allow`, `/ask`, `/think`, `/effort` (plus mode-specific
ones; completions in `SLASH_ARGS`).

**Safety constants to port first (Phase 3):** `BLOCKED_PATHS` (ssh, gnupg, cloud and browser profiles, shell
histories, `/etc/shadow`, sudoers, `/root`, ...), `BLOCKED_NAMES`, `BLOCKED_SUFFIXES` (`.pem`, `.key`),
`PROTECTED_DIRS` (`~/hyprdots`), `_touches_blocked_path`, `AUTO_APPROVE` (never for sensitive), `MAX_OUTPUT_CHARS`
12,000, `MAX_OUTPUT_BYTES` 200,000, `MAX_WRITE_BYTES` 200,000, `MAX_TOOL_STEPS` and `MAX_HISTORY` (from settings),
`MAX_TOTAL_CALLS` 25, `OUTBOUND_LIMIT` 200, `parse_text_tool_call`.

**Launch glue:** `scripts/assistant-toggle.sh` (`SUPER + C`): checks `disabled`, Ollama and the `ollama` module;
toggles special workspace `agent`; runs the app if `--check` passes, else `ghostty --class=com.hyprdots.assistant -e
hypr_agent.py`. Also `scripts/ollama.sh`, `scripts/stop_ollama.sh`, Waybar `custom/assistant`.

## 3. Agent hooks the window installs (checked against the code)

From `install_hooks()` in `hypr_assistant_app.py:2049`. The plan's section 9 draft is correct in substance; additions
are marked **new**.

| Hook in Python | What it does | Rust event / reply |
|---|---|---|
| `agent.GUI[0] = True` | Agent knows a window is attached | **new**: frontend capability flags at session start |
| `agent.Spinner` | Status line while the model works | `Status(text)` |
| `agent.ReasoningView` | Streams reasoning | `ReasoningDelta`, `ReasoningDone` |
| `agent.AnswerView` | Streams the answer, reset per model call | `AnswerReset`, `AnswerDelta` |
| `agent._confirm(question, sensitive, auto_ok)` | Allow/Deny card; auto-approve only if not sensitive **and `auto_ok`** | `ApprovalRequest { id, question, sensitive, auto_ok }` **(add `auto_ok`)** / `Approval { id, allow }` |
| `agent.ui_tool(name, args)` | Tool row; suppressed for `ask_user_to_run` and `dnd_*` tools | `ToolStart { name, args }` (the UI filters) |
| `agent.ui_command(command)` | Command row | `Command(text)` |
| `agent.ui_write(action, target)` | File write row | `Write { action, target }` |
| `agent.TERMINAL_READER[0]` | Agent reads the embedded VTE | **new**: `TerminalReadRequest { id, lines }` / `TerminalText { id, text }` (`TERMINAL_LINES`, `TERMINAL_MAX_LINES`) |
| `agent.TERMINAL_RUNNER[0]` | "Run for user" card; returns output or None | `RunForUser` / `RunForUserOutcome` |
| `watch_web(name)` wrapping `agent.tools[...]` for `web_search`, `news_search`, `web_fetch` | Web panel rows, "Stopped." on cancel | `WebStart`, `WebFinish` |
| `dnd_mode.LISTENERS` (kinds `sheet`, `roll`, `note`) | Table updates | `SheetChanged`, `DiceRoll`, `DndNote` |
| `dnd_mode.ROLLER[0]` | Player throws the dice; None = stopped | `PlayerRollRequest` / `PlayerRoll` |
| `Assistant.stop()` | Sets `cancelled`, resolves pending approval/roll as False, raises `KeyboardInterrupt` in the worker via `PyThreadState_SetAsyncExc` | `Cancel` with a cancellation token |
| `Assistant.attention()` | `notify-send -u critical` when the window is unfocused | UI-side, on `ApprovalRequest`/`RunForUser`/`PlayerRollRequest` |

The window also calls straight into the agent (these become `core` API, not events): `process_prompt`,
`run_slash_command`, `start_session`, `end_session`, `log_turn`, `greeting`, `health_summary`, `analyze_image`,
`ensure_ollama_running`, `model_installed`, `chat_model`, `parse_text_tool_call`, `_touches_blocked_path` (attachments),
`_prepare_markdown`, `_parse_fetch_args`; and reads `THINK`, `THINK_EFFORTS`, `AUTO_APPROVE`, `VISION_*`, `MODEL`,
`SLASH_COMMANDS`, `SLASH_ARGS`, `EXAMPLE_PROMPTS`, `WEB_NOTICE`, `FAILURE_PREFIXES`, `TOOL_COUNT`, `HISTORY`,
`SESSION_FILE`, `SETTINGS`.

## 4. Settings (`.config/hypr/settings/hyprsettings`, 12.2k lines, 235 tests)

Two front ends over one model: `gui/` (GTK4 + libadwaita, 3.3k) and `tui.py` (prompt_toolkit, 1.5k, `settings.sh --tui`).

| Area | Files | Class | Tests | Shells out to |
|---|---|---|---|---|
| Model | `schema.py` (120 settings), `store.py`, `tomledit.py`, `overrides.py` (writes `user_overrides.lua`) | Portable | `test_core`, `test_tui` | none |
| Theme | `design.py` (roles), `theme.py`, `gtktheme.py`, `livetheme.py`, `theme_override.py`, `theme_parts.py`, `look_game/mac/scifi.py` | Linux (writes GTK, Qt, Waybar, swaync, hyprlock CSS) | `test_theme_override` (58), `test_qt_theme`, `test_displays_gtk` | `fc-list`, `gsettings`, `hyprctl`, `swaync-client`, `flatpak` |
| Hyprland | `displays.py` (`monitors.lua`), `workspaces.py`, `windowrules.py`, `keyspec.py`, `barlayout.py` | Linux | `test_displays_gtk`, `test_windowrules`, `test_bar_recording` | `hyprctl` |
| System | `network.py` + `net_helper.py` (root, via pkexec), `power.py` (talks to `powerd`), `idle.py`, `lockscreen.py`, `account.py`, `mimeapps.py`, `cloud.py` (rclone), `healthmonitor.py`, `models.py` (Ollama) | Linux | `test_network`, `test_power_page`, `test_mime`, `test_healthmonitor` | `nmcli`/`iwctl`/`networkctl`/`connmanctl`/`netctl`, `ip`, `resolvectl`, `rfkill`, `pkexec`, `systemctl`, `busctl`, `rclone`, `xdg-mime`, `hypridle`, `nvidia-smi` |

Writes: `user_settings.toml`/`.local.toml` (comment-preserving), `user_overrides.lua`, `monitors.lua`,
`workspaces.lua`, `hypridle.local.conf`, hyprlock config, `~/.config/mimeapps.list`, `gtk-3.0`/`gtk-4.0` CSS and
`settings.ini`, Qt and Waybar colours, `~/.local/state/hyprdots/theme-override.json`, rclone mounts, network files (as
root). This is the riskiest port in the repo: most of it changes system config.

## 5. Desktop programs outside the assistant and settings

| Program | Lines | Toolkit | Class | Tests | Notes |
|---|---|---|---|---|---|
| `launcher/launcher.py` + `search.py`, `stage.py`, `startmenu.py`, `logomenu.py` | 2.5k | GTK4 + layer-shell (Gsk, Graphene for animated styles) | Linux overlay | 51 | `SUPER + SPACE`. Apps (frecency in `~/.local/state/hyprdots/launcher-usage.json`), sums, `>` commands, `?` web, power actions. XP start menu and Mac logo menu for theme overrides. `gtk-launch`, `wl-copy`, `xdg-open`, `hyprctl`, `systemctl` |
| `launcher/wallpicker.py` | 626 | GTK4 + layer-shell | Linux overlay | 11 | `SUPER + W` via `rofi/wallpaper/wallpaper.sh`, which hands off to it. Thumbnails by `ffmpeg`; applies through `wallpaper.sh --apply` (awww + wallust, `video-wallpaper.sh` for video) |
| `rofi/powermenu/powermenu.py` | 341 | GTK4 + layer-shell, PangoCairo | Linux overlay | **none** | `hyprctl`, `systemctl`; closed by `click_away.lua` via `pkill` |
| `cheatsheet/cheatsheet.py` | 290 | GTK4 + layer-shell | Linux overlay | **none** | `SUPER + K`; reads binds |
| `notes/` | Rust 1.7k + Python 776 | gtk4-rs 0.11 + gtk4-layer-shell 0.8 | Portable logic, Linux window | Rust 44, Py 18 | Service `hyprdots-notes`, toggled by `SIGUSR1`, ready file `$XDG_RUNTIME_DIR/hyprdots-notes.ready`. Notes in `~/.local/state/hyprdots/notes` |
| `tray/quick_tray.py` + `notifications.py`, `overview.py`, `popups.py`, `sysinfo.py` | 2.1k | **GTK 3** + gtk-layer-shell 0.1 | Linux | 26 | Quick settings, system monitor, notification copy (swaync over D-Bus), Alt+Tab, `SUPER + TAB` overview (`grim` thumbnails), volume OSD. `pactl`, `powerprofilesctl`, `swaync-client`, `nvidia-smi` |
| `tray/tablet_mode.py` + `touch_gestures.py`, `touch_lift.py`, `touch_mode.py` | 1k | GTK 3 | Linux | 50 | Service; `monitor-sensor`, `squeekboard`, `wtype`, `grim`, `hyprctl` |
| `audio/` (Sound app) | 1.9k | GTK4 | Linux | 45 | `SUPER + SHIFT + A`. `pactl`, `pw-cli`, PipeWire filter chains (`eq.conf`, `clean-mic.conf`), headsetcontrol |
| `waybar/scripts/popup_calendar.py` | 614 | **GTK 3** + layer-shell | UI over portable data | **none** | Clock click. `icalendar`, `recurring_ical_events`, `localcal`, `[calendar]` settings |
| `waybar/scripts/dock.py` | 376 | GTK4 + layer-shell | Linux | `settings/tests/test_dock` (9) | Mac-style dock |
| `waybar/scripts/workspace_dot.py` | 53 | none | Linux | **none** | Waybar `exec` per workspace; Hyprland socket |
| `waybar/scripts/updates.sh` | 46 | shell | Linux | shellcheck | `custom/updates` |
| `welcome/welcome.py` | 76 | GTK4 + Adw | UI | **none** | First login only |
| `scripts/game-autoworkspace.py` | 262 | none | Linux | **none** | Hyprland socket, `hyprctl` |
| `theme-overrides/*/make_wallpaper.py` | 454 | Pillow | Build-time | **none** | Generates bundled wallpapers; not shipped logic |
| `install/tui.py`, `install/askpass/askpass.py` | 824 | curses | Linux install | 35 | Installer front end |
| `install/power/powerd.py` | 343 | none, runs as root | Linux system | 10 | `hyprdots-power.service`; CPU/GPU/RAM limits, heat guard |

**Shell (~2.5k lines):** `hyprinstall.sh` (758), `update.sh` (384), `install/*.sh`, `rofi/wallpaper/wallpaper.sh`
(apply backend), `rofi/launchers/categorized/*` (old launcher, unused by binds), `scripts/*.sh` (screenshot, record,
lock, gamemode, video wallpaper, wallust, desktop services, emoji, colour picker, ...). Under the plan's non-goals these
stay shell; only the lines that launch a ported program change.

## 6. Portable / Linux / UI summary

- **Portable logic (Rust crates, all OSes):** agent loop and Ollama client, approvals and blocked paths (paths are
  per-OS lists), web tools, memory, session transcript, slash commands, `agent_modes`, `dnd_mode`, `dnd_library`,
  `localcal` and calendar parsing, `usersettings`, settings `schema`/`store`/`tomledit`, notes `markdown`/`notebook`,
  launcher `search` ranking and frecency, `keyspec`.
- **Linux-only logic:** agent desktop tools (`hyprctl`, `grim`, pacman/paru/flatpak, journal), `agent_monitor`,
  everything under settings' Hyprland/System/Theme writers, tray, tablet mode, Sound, `powerd`, `workspace_dot`,
  `game-autoworkspace`, wallpaper apply.
- **UI:** `hypr_assistant_app`, `dnd_ui`, settings `gui/` and `tui.py`, launcher/wallpicker/powermenu/cheatsheet
  overlays, notes window, tray windows, Sound, popup calendar, dock, welcome.

## 7. Proposed port order (for review)

Unchanged from the plan where it still fits; changes in **bold**.

1. **Phase 1:** workspace, `settings` crate (read-only first: `usersettings` semantics, using the shared fixtures in
   `assistant/tests/fixtures/usersettings`; then `store.py` read semantics), `theme` crate (wallust slots to roles,
   fonts, override state), notes moved in unchanged.
2. **Phase 2:** iced spike, as planned. **Add a check: a GTK3 replacement for the tray's layer-shell popups**, since
   GTK3 and gtk-layer-shell 0.1 are the most dated pieces in the repo.
3. **Phase 3:** `core` + TUI, as planned, with the event contract in section 3 (including `auto_ok` and the terminal
   read request).
4. **Phase 4: decide clipboard first.** Either keep clipvault and only add a palette mode over it (recommended: it
   already stores and dedupes), or build `clipboardd` as planned to get pinning, sensitive-entry filtering and Windows/
   macOS backends.
5. **Phase 5:** monitor, calendar (**including `popup_calendar.py`**), Waybar modules.
6. **Phase 6:** palette: launcher (with the XP start menu and Mac logo menu styles), wallpaper picker, power menu,
   emoji (replacing rofimoji), clipboard mode, **and the cheatsheet**.
7. **Phase 7:** `dnd-core`, as planned.
8. **Phase 8:** assistant GUI, as planned.
9. **Phase 9:** settings UI and installers. **Re-size this: it is as large as the assistant, and the TUI needs a port
   too (ratatui).**
10. Phase 10: Windows and macOS.

**Needs a decision (out of the plan today):** quick tray + overview + Alt+Tab, tablet mode, Sound app, dock, welcome,
game-autoworkspace, installer TUI, `powerd`. Suggested default: they stay Python until Phase 9 is done, then get their
own phase; `powerd` (root, small, well tested) is a good early Rust candidate if wanted.

## 8. Characterisation tests added in Phase 0

- `assistant/tests/test_usersettings.py` with 17 cases in `assistant/tests/fixtures/usersettings/` (merge order,
  per-key local override, unknown keys, type checks including int-to-float widening and bool/int strictness, broken
  files ignored, whole-value replacement of tables). The Rust `settings` crate will run the same fixture folders.

Still untested and due before their phase: `agent_monitor.py` (Phase 5),
`popup_calendar.py` data side (Phase 5), `powermenu.py` actions (Phase 6), `dnd_ui.py` roll logic (Phase 8),
`store.py` read path against the same fixtures (Phase 1).
