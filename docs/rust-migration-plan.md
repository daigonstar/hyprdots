# Hyprdots: Python to Rust Migration Plan

Handoff document for a local coding session. Read all of it before touching anything. Corrections found in Phase 0 are
in `docs/INVENTORY.md` section 0 and take precedence where they conflict with this text (keybinds, clipboard, scope).

## 1. Goal

Port every custom Python app in the repo to Rust, one piece at a time, so that:

- the suite ships as single binaries with no Python environment to maintain,
- shared logic lives in reusable crates, with UIs as thin layers,
- the portable apps (assistant, D&D mode, notes, monitor, calendar, clipboard history) also run on Windows and macOS,
- the Linux-only shell overlays (launcher, power menu, wallpaper selector, emoji picker) stay Hyprland-native.

### Non-goals

- Do NOT rewrite standard config: `hyprland.conf` / `.lua` rules, Waybar, rofi, SDDM, themes, wallpapers. These stay as
  they are. Only edit them to point at new Rust binaries, and only per milestone.
- No big-bang rewrite. Python versions stay in place and working until the Rust replacement passes the same tests.
- No new features in Python. New features (clipboard history, emoji picker) are built in Rust from the start.

## 2. What is known and not known

Superseded by `docs/INVENTORY.md`.

## 3. Decisions already made

- GUI toolkit for portable apps: iced (user decision). Pin the exact version in the workspace. Upgrade deliberately.
- Linux-only overlays: decide after the spike (section 8). Fallback is gtk4 + gtk4-layer-shell, which notes already uses.
- Settings format stays `user_settings.toml`, so existing configs keep working.

## 4. Ground rules for the session

1. Work in small milestones. One commit (or PR) per milestone, with a passing test run.
2. Python tests under `tests/` are the behaviour spec. Port the cases, do not reinterpret them. Where there are no
   tests, write characterisation tests against the Python first.
3. Port safety logic first and with tests: blocked-path protection for file/credential access, approval rules
   (anything that changes the system needs Allow/Deny), sensitive-action handling, cancellation semantics. Never
   weaken these.
4. Keep file formats compatible (settings, campaign record, session history) so Python and Rust can read each other
   during the migration.
5. No secrets in the repo. Private values (e.g. the iCal secret address) stay in the local, git-ignored file or the OS
   keychain.
6. Do not delete or rename Python files until the Rust replacement is merged and the user agrees. Move retired code to
   `legacy/`, do not remove it.
7. Ask before touching compositor or system config, or anything under `/etc`, systemd, SDDM or the install scripts.
8. Prefer boring dependencies. Record every dependency choice and why in `docs/decisions.md`.
9. Record the status of each phase in `docs/progress.md` so the next session can resume quickly.

## 5. Target architecture

```
hyprdots-rs/                 (Cargo workspace, edition 2024)
  Cargo.toml                 (workspace; pinned versions)
  crates/
    settings/                user_settings.toml, local override, schema/defaults
    theme/                   Theme page roles to colours + fonts, live reload
    core/                    agent loop, tools, Ollama client, event stream, slash commands
    notes-core/              notes storage, parsing, search (no UI types)
    dnd-core/                rules engine, campaign record, books library
    platform/                traits: metrics, notifications, clipboard, mode switching
    platform-linux/          Hyprland / Wayland backends
    platform-windows/        later
    platform-macos/          later
    fuzzy/                   shared fuzzy matcher (nucleo) + frecency
  apps/
    cli/                     scripting entry point and Waybar modules
    tui/                     terminal frontend for the agent
    clipboardd/              clipboard history daemon
    monitord/                health monitor daemon
    notes/                   existing notes app, moved in
    palette/                 launcher + emoji + power + wallpaper + clipboard modes
    assistant/               the main iced GUI
    settings-ui/             settings app
```

Pattern: long-running daemons own state, and CLIs and GUIs are clients over a local Unix socket (named pipe on
Windows). Waybar modules call the CLI.

Crate rules: `core`, `*-core`, `settings` and `theme` must not depend on any GUI crate.

## 6. Phase 0: Inventory and spec (no Rust yet)

Deliverables:

- `docs/INVENTORY.md`: every Python and shell program, its purpose, entry points, files it reads/writes, external
  commands it shells out to, Python dependencies, and test coverage.
- Mark each module: portable (all OSes), Linux-only, or UI.
- A list of all hooks the GUI installs on the agent (section 9 is the starting draft), checked against the real code.
- Run the existing tests and record the baseline.
- Write characterisation tests for untested logic that will be ported.

Done when the user has reviewed the inventory and agreed the port order.

## 7. Phase 1: Workspace, settings, theme

- Create the workspace and CI-style local script (`cargo fmt`, `clippy -D warnings`, `cargo test`).
- `settings` crate: read `user_settings.toml` and the local override with identical keys and defaults to
  `usersettings.py`. Port its tests.
- `theme` crate: resolve the Theme page roles (base, base_text, surface, surface_alt, text, accent, secondary, muted,
  icons, attention) and font list, plus a watcher for live theme changes.
- Move the existing notes app into the workspace unchanged (still GTK). Do not refactor yet.

Done when: Rust and Python read the same settings file and agree on every value in a comparison test.

## 8. Phase 2: iced spike (decides the GUI)

Build throwaway prototypes in `spikes/` and record pass/fail with screenshots in `docs/spike-results.md`. Checklist:

1. Streaming markdown: headings, lists, inline code, links, fenced code blocks with Copy buttons, and text selection
   across a rendered answer.
2. Notes-style editor on the real notes file format.
3. Embedded terminal that the agent can read back (iced_term or similar). Alternative: external terminal fallback.
4. Animated hearth logo on a canvas (flicker, embers, busy state).
5. Layer-shell overlay (community `iced_layershell` or similar), plus the scratchpad window class.
6. Theme loading and live switching.
7. Wallpaper thumbnail grid performance (hundreds of images).
8. Clipboard (including image paste) and IME behaviour.

Decision rules:

- 1, 2, 3 pass: assistant and notes move to iced.
- 3 fails: terminal becomes an external/auxiliary window, which is acceptable.
- 1 fails: stop and report to the user before continuing. Alternatives are a webview-based UI (Tauri/Dioxus) or
  staying on GTK for the assistant.
- 5 fails: Linux-only overlays stay on gtk4 + gtk4-layer-shell; iced is used for the portable apps only.

## 9. Phase 3: `core` crate, event contract, terminal frontend

The Python GUI customises the agent by monkeypatching. In Rust the agent emits events and receives replies. The checked
hook list and event mapping is in `docs/INVENTORY.md` section 3.

Agent to UI events:

- `Status(text)`
- `ReasoningDelta(text)`, `ReasoningDone`
- `AnswerReset` (a new model call starts; drop the previous draft), `AnswerDelta(text)`
- `ToolStart { name, args }`, `Command(text)`, `Write { action, target }`
- `ApprovalRequest { id, question, sensitive }`
- `RunForUser { id, command, reason }`
- `WebStart { id, tool, arg }`, `WebFinish { id, result }`
- D&D: `PlayerRollRequest { id, request }`, `DiceRoll(record)`, `DndNote(text)`, `SheetChanged`
- `TurnDone { reply, took, steps, failed }`

UI to agent:

- `Submit { text, attachments }`
- `Approval { id, allow }`
- `RunForUserOutcome { id, outcome: None | Finished(output) | Said(output) }`
- `PlayerRoll { id, value | cancelled }`
- `Cancel` (must stop the current turn cleanly, resolve any pending approvals as denied, and never leave work
  half-saved)
- `SlashCommand(line)`

Requirements:

- A single turn runs as an async task with a cancellation token (replaces the async-exception trick).
- Approvals and prompts use one-shot channels, never polling.
- Agent behaviours to preserve and test: recognising a tool call that the model wrote out as text and not showing it
  as an answer; auto-approve mode only for non-sensitive actions; blocked paths for attachments; image downscale to
  1600 px and text attachment limits (200 KB read, 12,000 characters in the prompt); slash commands and their
  completions.

Work items:

- Ollama client with streaming, reasoning/answer separation, vision model call.
- Tool system, `agent_modes` (including the hidden Dungeon Master mode).
- Session history file compatible with Python.
- `apps/tui` (ratatui or plain CLI): the first frontend, replacing the terminal use of `hypr_agent.py`.

Done when: the same scripted conversations (recorded against a mock Ollama) produce the same events and replies as
Python, and the TUI can replace `hypr_agent.py` day to day.

## 10. Phase 4: `clipboardd`

- Wayland data-control watcher (equivalent to `wl-paste --watch`), text and images.
- Store in SQLite or redb: dedupe by hash, pin, retention limit, search.
- Ignore sensitive entries (password managers set hint MIME types). Consider encrypting the database at rest.
- Client commands: `list`, `search`, `copy`, `pin`, `clear`. Keep the existing clipboard bind working via the CLI until
  the palette replaces it.
- `ClipboardWatcher` trait in `platform` so Windows/macOS backends can follow.

## 11. Phase 5: monitor, calendar, Waybar modules

- `monitord`: port `agent_monitor.py`. CPU/RAM/disk via `sysinfo`; GPU and temperatures behind the metrics trait
  (Linux first).
- Calendar: port `localcal.py` (iCal fetch, parse, recurring events, timezone handling) and the clock-popup data
  source. Store the secret iCal address in the local file or the keychain.
- `cli` exposes JSON for Waybar `custom` modules. Swap modules in the Waybar config one at a time, with user approval.

## 12. Phase 6: `palette` (launcher + emoji + power + wallpapers + clipboard)

One overlay app with modes, sharing the `fuzzy` crate and the theme.

- Launcher: parse `.desktop` entries, nucleo matching, frecency ranking.
- Power menu: `systemctl` / `hyprctl dispatch exit` actions with confirmation.
- Wallpaper selector: cached thumbnails (`image` crate), apply through the existing wallpaper backend (CLI/IPC),
  per-monitor choice.
- Emoji picker: bundled emoji data with keywords, skin tones, recents, favourites. Insert via copy plus synthesised
  paste (wtype / virtual keyboard); document compositor differences.
- Clipboard mode: search and pin from `clipboardd`.
- Existing keybinds open the palette in the matching mode (bind ids: `launcher`, `clipboard`, `wallpaper`, `emoji`).

Toolkit follows the spike result. Each former tool is retired only once its mode matches it.

## 13. Phase 7: `dnd-core`

- Port `dnd_mode.py` and `dnd_library.py`: character record, abilities, skills, conditions, spell slots, XP/level
  tables, combat order and economy, dice, campaign journal, books library.
- Rules text and tooltips move into data files (TOML/JSON), not code.
- Save files stay readable by both versions during the transition.
- The tool interface the agent calls (`dnd_update`, rolls, etc.) keeps the same names and error messages, including
  `Rejected:` prefixes.
- Exhaustive tests for rules (proficiency, DCs, death saves, rests, level-ups).

## 14. Phase 8: assistant GUI (iced)

Port `hypr_assistant_app.py` against the event stream:

- Window class `com.hyprdots.assistant` so the existing scratchpad rule keeps working; `--check` fallback to the
  terminal when `interface = "terminal"`.
- Chat bubbles, reasoning panel (dim, folds when the answer starts), tool/command/write rows, Allow/Deny cards
  (sensitive variant), "run for user" cards, typing indicator, footer with time and tool count.
- Markdown rendering: headings, lists, inline code, links, fenced code blocks with Copy / Paste / Run, `$ command` lines
  as copyable blocks.
- Attachments: paperclip, paste, drag-and-drop, thumbnails, file chips.
- Slash command chips and completion, history recall (Up), Tab completion, Esc to stop.
- Web activity panel and terminal pane (per spike result).
- Logo with the hidden Dungeon Master trigger (five quick clicks).
- D&D table mode: tavern theme, character sheet panel (Hero, Gear, Story, Books), dice tray, character builder,
  subclass picker.
- Notifications on completion and when approval is needed while the window is unfocused.

Done when the Rust app can replace the Python window for a full day of normal use, and every item above is checked off
in `docs/progress.md`.

## 15. Phase 9: settings UI and installers

- Port the `hyprsettings` app (Theme page, store, schema). It is a second full GUI plus a TUI (see INVENTORY).
- Arch `PKGBUILD` for the Rust binaries. Keep `hyprinstall.sh`, updated to install the binaries and optional Ollama
  models.
- Systemd user units for the daemons (`clipboardd`, `monitord`).

## 16. Phase 10: Windows and macOS

- `platform-windows` / `platform-macos`: metrics, notifications (`notify-rust`), clipboard watcher, autostart, tray
  icon, global hotkey.
- Only portable apps ship: assistant, D&D mode, notes, monitor, calendar, clipboard history, emoji picker.
- Mode switching (Do Not Disturb / Focus) has no public API on these OSes, so it is Linux-only or reduced.
- Installers: MSI/MSIX on Windows, signed DMG on macOS (plan for signing and notarisation).
- CI matrix on all three OSes.

## 17. Notes app

- Phase 1: moved into the workspace unchanged.
- Later: extract storage/parsing/search into `notes-core` with no GTK types, keeping behaviour identical and the
  existing app working.
- Only then consider an iced front-end, after the editor spike passes.

## 18. Risks

- Behavioural drift in the agent (tool-call recovery, approvals, cancellation). Mitigation: recorded-conversation tests.
- Two large GUIs (assistant and settings) dominate the effort.
- iced limitations: text selection, rich text, terminal embedding, pre-1.0 churn. Mitigation: the spike and a pinned
  version.
- Community layer-shell crate may lag iced releases. Mitigation: GTK fallback for Linux overlays.
- OS-specific code (GPU stats, notifications, clipboard) multiplies per platform. Mitigation: traits and Linux-first
  delivery.
- Scope creep. New features wait for the Rust base; the order in this plan is the contract.

## 19. Working method per session

1. Read `docs/progress.md` and the current phase section of this plan.
2. State the milestone being worked on and which tests define it.
3. Make the smallest change that moves a test from red to green; keep Python untouched.
4. Run fmt, clippy and tests. Update `docs/progress.md` and `docs/decisions.md`.
5. Commit. Stop at the milestone boundary and summarise what changed and what is next.
