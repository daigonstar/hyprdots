# Rust migration: progress

The plan is `docs/rust-migration-plan.md`. Each session: read this file, then the current phase of the plan.

| Phase | Status | Notes |
|---|---|---|
| 0. Inventory and spec | **Waiting for review** | `docs/INVENTORY.md`. Baseline: all 884 Python tests and 44 Rust notes tests pass. One characterisation suite added (settings). |
| 1. Workspace, settings, theme | Not started | Blocked on Phase 0 review |
| 2. iced spike | Not started | |
| 3. `core`, events, TUI | Not started | |
| 4. `clipboardd` | Not started | Scope question: clipvault already does this (INVENTORY 0.2) |
| 5. Monitor, calendar, Waybar | Not started | |
| 6. Palette | Not started | |
| 7. `dnd-core` | Not started | |
| 8. Assistant GUI | Not started | |
| 9. Settings UI, installers | Not started | Larger than the plan assumed (INVENTORY 0.1) |
| 10. Windows, macOS | Not started | |

## Open questions for the user (Phase 0 exit)

1. Agree the port order in INVENTORY section 7?
2. Which out-of-plan programs are in scope (tray, tablet mode, Sound, dock, welcome, game-autoworkspace, installer TUI,
   `powerd`)? Default suggestion: they stay Python for now.
3. Clipboard: keep clipvault and add a palette mode, or build `clipboardd`?

## Log

- 2026-11-12, Phase 0: inventory written, hooks checked against `hypr_assistant_app.py:install_hooks`, baseline
  recorded, `assistant/tests/test_usersettings.py` + fixtures added. Branch
  `claude/hyprdots-python-rust-migration-2b9e2d`.
