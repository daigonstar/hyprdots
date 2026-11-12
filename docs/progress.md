# Rust: progress

## Policy (decided 2026-11-12)

**New features are written in Rust. Existing Python stays Python.** The full migration in
`docs/rust-migration-plan.md` is shelved: it would cost months and fix none of the gaps in `AUDIT.md`. An existing
Python program is ported only for a measured reason, such as slow start-up, running as root or crashes.

How a new Rust program fits in, following Notes (`.config/hypr/notes/rs`):

- gtk4-rs + gtk4-layer-shell, the same as the notes window and the Python overlays, so it looks and behaves like them.
- Colours and font from the Theme page, read the way `notes/rs/src/theme.rs` reads them.
- A `build.sh` builds it into `~/.local/lib/hyprdots/` when its source changes. The installer and `update.sh` run it.
- The launch script falls back to the tool it replaces when the binary is missing, so a failed build never leaves a
  keybind dead.
- The keybind keeps its id in `keybinds.lua`, so a custom combo from Settings still works.
- Tests run in CI like `notes-rust`. Any Python logic it shares (settings, theme) gets a parity test.

## Features

| Feature | Replaces | Bind (id) | Status |
|---|---|---|---|
| Emoji picker | rofimoji + wtype (`scripts/emoji.sh`) | `SUPER + period` (`emoji`) | **Built** (`.config/hypr/emoji`). 15 tests, CI job `emoji-rust`. Checked on the desktop: opens, themed, search, arrow keys, Escape, toggle. Not yet checked by hand: Enter typing into an app, Shift+Enter copy, touch mode |
| Clipboard history window | `clipvault list \| rofi -dmenu` | `SUPER + CTRL + C` (`clipboard`) | Not started. clipvault stays the store, and this is a window over it |

## Log

- 2026-11-12: Phase 0 inventory (`docs/INVENTORY.md`), baseline (884 Python + 44 Rust tests pass), settings
  characterisation tests. Then the full migration was shelved for the policy above.
- 2026-11-12: emoji picker in Rust (gtk4-rs + layer-shell). `scripts/emoji.sh` prefers it and falls back to rofimoji;
  installer and `update.sh` run `emoji/build.sh`.
