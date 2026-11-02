-- Built-in window rules, listed on the settings Window rules page. Your own rules, your changes to these and the ones you
-- switched off are kept in window_rules_local.lua (git-ignored), so updates can add to this list without touching them.
-- Plain data only: the settings app reads this file without running it.
return {
    { name = "chat-workspace", match = { class = "^(discord|WebCord|Vesktop)$" }, workspace = "2" },
    { name = "steam-workspace", match = { class = "^steam_app_.*$" }, workspace = "3" },
    { name = "steam-fullscreen", match = { class = "^steam_app_.*$" }, fullscreen = true },
    { name = "steam-immediate", match = { class = "^steam_app_.*$" }, immediate = true },
    { name = "steam-ui", match = { class = "^steam$" }, workspace = "1" },
    { name = "lutris", match = { title = "^Lutris$" }, workspace = "1" },
    { name = "heroic", match = { class = "^com.heroicgameslauncher.hgl$" }, workspace = "5" },
    { name = "remmina", match = { class = "^Remmina$" }, workspace = "4", fullscreen = true },
    { name = "vesktop-silent", match = { class = "^(vesktop)$" }, workspace = "2 silent" },
    { name = "bitwarden-silent", match = { class = "^(com.bitwarden.desktop)$" }, workspace = "3 silent" },
    { name = "solaar-silent", match = { class = "^(solaar)$" }, workspace = "5 silent" },
    { name = "spotify-magic", match = { class = "^(spotify)$" }, workspace = "special:magic silent" },
}
