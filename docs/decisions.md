# Rust migration: decisions

Every dependency and design choice, with the reason. Newest at the bottom.

| Date | Decision | Why |
|---|---|---|
| (plan) | iced for the portable GUIs, exact version pinned in the workspace | User decision; checked by the Phase 2 spike |
| (plan) | Linux overlays: gtk4 + gtk4-layer-shell unless the spike shows iced layer-shell works | Notes already uses it; the community iced layer-shell crate may lag iced |
| (plan) | Settings stay in `user_settings.toml` + `user_settings.local.toml` | Existing configs keep working |
| 2026-11-12 | Settings behaviour is pinned by shared fixture folders (`assistant/tests/fixtures/usersettings/*`), read by Python now and by the Rust `settings` crate in Phase 1 | One set of cases, so Rust cannot drift from Python; JSON keeps int and float apart |
| 2026-11-12 | `apply_modes.py` is not ported | One-off source patch, already applied, used by nothing |
| 2026-11-12 | **Full migration shelved. New features are written in Rust, and existing Python stays Python** | Large cost (36k lines, two big GUIs) for little gain: Python is already portable, and the real gaps are laptop and tablet. See `progress.md` |
| 2026-11-12 | New Rust programs use gtk4-rs + gtk4-layer-shell, not iced | Matches Notes and every existing overlay. No spike is needed, and the theme works the same way |
| 2026-11-12 | Clipboard history keeps clipvault as the store | It already persists and dedupes. The new work is the window over it |
| 2026-11-12 | Emoji data is generated from Unicode's `emoji-test.txt` and the CLDR English annotations into `emoji/rs/data/emoji.tsv`, built into the binary | Gives keywords ("happy" finds 😀) and exact skin tone versions. The `emojis` crate has no keywords. Nothing is downloaded at run time; `data/update.sh` refreshes it |
| 2026-11-12 | The emoji picker types with `wtype` after it closes, and falls back to `wl-copy` plus a notification | Same as rofimoji did. `wl-copy` keeps the clipboard alive after the picker exits |
| 2026-11-12 | Rust in this repo is formatted at 120 columns (`rustfmt.toml`) | Matches the Python and Notes; lets CI run `cargo fmt --check` |
| 2026-11-12 | Every emoji pick is also copied to the clipboard, not only when typing fails | Electron apps (the Claude app) ignore what `wtype` types without it failing, so Ctrl+V has to work too. User's choice |
