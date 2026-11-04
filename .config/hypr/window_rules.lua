-- Built-in window rules, listed on the settings Window rules page. Your own rules, your changes to these and the ones you
-- switched off are kept in window_rules_local.lua (git-ignored), so updates can add to this list without touching them.
-- Plain data only: the settings app reads this file without running it.
-- Only rules any desktop wants: where you keep your own apps is yours to set, on that page.
return {
    { name = "steam-workspace", match = { class = "^steam_app_.*$" }, workspace = "3" },
    { name = "steam-fullscreen", match = { class = "^steam_app_.*$" }, fullscreen = true },
    { name = "steam-immediate", match = { class = "^steam_app_.*$" }, immediate = true },
}
