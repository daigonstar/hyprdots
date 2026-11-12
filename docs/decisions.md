# Rust migration: decisions

Every dependency and design choice, with the reason. Newest at the bottom.

| Date | Decision | Why |
|---|---|---|
| (plan) | iced for the portable GUIs, exact version pinned in the workspace | User decision; checked by the Phase 2 spike |
| (plan) | Linux overlays: gtk4 + gtk4-layer-shell unless the spike shows iced layer-shell works | Notes already uses it; the community iced layer-shell crate may lag iced |
| (plan) | Settings stay in `user_settings.toml` + `user_settings.local.toml` | Existing configs keep working |
| 2026-11-12 | Settings behaviour is pinned by shared fixture folders (`assistant/tests/fixtures/usersettings/*`), read by Python now and by the Rust `settings` crate in Phase 1 | One set of cases, so Rust cannot drift from Python; JSON keeps int and float apart |
| 2026-11-12 | `apply_modes.py` is not ported | One-off source patch, already applied, used by nothing |
