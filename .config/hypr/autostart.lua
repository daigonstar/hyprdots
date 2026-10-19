-- Optional apps that start with the desktop. hypr-settings lists the entries between the markers
-- (one per line, in this exact shape) and can switch each one off; the rest of this file is always run.
local ok, overrides = pcall(require, "user_overrides")
local disabled = (ok and type(overrides) == "table" and overrides.startup_disabled) or {}
local terminal = (ok and type(overrides) == "table" and type(overrides.apps) == "table" and overrides.apps.terminal) or "ghostty"

-- STARTUP-APPS-BEGIN
local optional_apps = {
    { id = "discord", label = "Discord", cmd = "discord" },
    { id = "nextcloud", label = "Nextcloud sync", cmd = "com.nextcloud.desktopclient.nextcloud --background" },
    { id = "openrgb", label = "OpenRGB (lighting profile)", cmd = "openrgb --startminimized -p Ice.orp" },
    { id = "coolercontrol", label = "CoolerControl (fans and cooling)", cmd = "coolercontrol" },
    { id = "solaar", label = "Solaar (Logitech devices)", cmd = "solaar --w hide" },
    { id = "bitwarden", label = "Bitwarden", cmd = "com.bitwarden.desktop --hidden" },
    { id = "localsend", label = "LocalSend (file sharing)", cmd = "org.localsend.localsend_app --hidden" },
}
-- STARTUP-APPS-END

hl.on("hyprland.start", function()
    local commands = {
        "dbus-update-activation-environment --systemd WAYLAND_DISPLAY XDG_CURRENT_DESKTOP",
        "systemctl --user import-environment WAYLAND_DISPLAY XDG_CURRENT_DESKTOP",
        "systemctl --user start graphical-session.target",
        -- (optional apps are started separately below, so hypr-settings can switch them off)
        "hyprctl setcursor Future-cursors 24",
        "awww-daemon --format xrgb",
        "systemctl --user start hyprpolkitagent",
        "systemctl --user enable --now hyprpolkitagent.service",
        "waybar",
        "swaync",
        -- lets Thunar ("Open terminal here") and other exo-open callers find your terminal
        "~/.config/hypr/scripts/exo-terminal.sh '" .. terminal:gsub("'", "'\\''") .. "'",
        "hypridle",
        "wl-paste --watch clipvault store",
        -- Detects games launched from Steam, Lutris, Heroic, or bare
        -- Wine/Proton/gamescope wrappers (no shared window class exists
        -- across launchers) and routes them to workspace 3, fullscreen.
        "python3 " .. os.getenv("HOME") .. "/.config/hypr/scripts/game-autoworkspace.py",
        -- `hyprctl dispatch workspace 1`/`focusmonitor DP-1` are legacy
        -- dispatcher names and no longer work under the Lua config parser.
        "sleep 2 && hyprctl dispatch 'hl.dsp.focus({ workspace = 1 })' && hyprctl dispatch 'hl.dsp.focus({ monitor = \"DP-1\" })'",
    }

    for _, command in ipairs(commands) do
        hl.exec_cmd(command)
    end

    for _, app in ipairs(optional_apps) do
        if not disabled[app.id] then
            hl.exec_cmd(app.cmd)
        end
    end
end)
