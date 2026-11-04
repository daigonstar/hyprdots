-- Optional apps that start with the desktop. hypr-settings lists the entries between the markers
-- (one per line, in this exact shape) and can switch each one off; the rest of this file is always run.
local ok, overrides = pcall(require, "user_overrides")
local disabled = (ok and type(overrides) == "table" and overrides.startup_disabled) or {}
local terminal = (ok and type(overrides) == "table" and type(overrides.apps) == "table" and overrides.apps.terminal) or "ghostty"

-- STARTUP-APPS-BEGIN
local optional_apps = {
    { id = "vesktop", label = "Vesktop", cmd = "vesktop" },
    { id = "nextcloud", label = "Nextcloud sync", cmd = "com.nextcloud.desktopclient.nextcloud --background" },
    { id = "openrgb", label = "OpenRGB (lighting profile)", cmd = "openrgb --startminimized -p ICE.orp" },
    { id = "coolercontrol", label = "CoolerControl (fans and cooling)", cmd = "coolercontrol" },
    { id = "solaar", label = "Solaar (Logitech devices)", cmd = "solaar --w hide" },
    { id = "bitwarden", label = "Bitwarden", cmd = "com.bitwarden.desktop --hidden" },
    { id = "localsend", label = "LocalSend (file sharing)", cmd = "org.localsend.localsend_app --hidden" },
}
-- STARTUP-APPS-END

-- Puts the wallpaper and workspaces right when a screen comes or goes
for _, event in ipairs({ "monitor.added", "monitor.removed" }) do
    hl.on(event, function()
        hl.exec_cmd("~/.config/hypr/scripts/monitor-changed.sh")
    end)
end

hl.on("hyprland.start", function()
    local commands = {
        -- The bar, notifications, tray, USB mounting and idle: services that come back by themselves if they crash
        "~/.config/hypr/scripts/desktop-services.sh login",
        -- (optional apps are started separately below, so hypr-settings can switch them off)
        "hyprctl setcursor Future-cursors 24",
        "awww-daemon --format xrgb",
        "~/.config/hypr/scripts/login-wallpaper.sh",
        "sleep 8 && ~/.config/hypr/scripts/gpu-check.sh --notify",
        "python3 ~/.config/hypr/welcome/welcome.py",  -- only at the first login
        -- lets Thunar ("Open terminal here") and other exo-open callers find your terminal
        "~/.config/hypr/scripts/exo-terminal.sh '" .. terminal:gsub("'", "'\\''") .. "'",
        "wl-paste --watch clipvault store",
        -- Detects games launched from Steam, Lutris, Heroic, or bare
        -- Wine/Proton/gamescope wrappers (no shared window class exists
        -- across launchers) and routes them to workspace 3, fullscreen.
        "python3 " .. os.getenv("HOME") .. "/.config/hypr/scripts/game-autoworkspace.py",
        -- Start on workspace 1, on whichever screen it lives (Workspaces page)
        "sleep 2 && hyprctl dispatch 'hl.dsp.focus({ workspace = 1 })'",
        "thunar --daemon",
    }

    for _, command in ipairs(commands) do
        hl.exec_cmd(command)
    end

    -- After the bar's tray is up, or tray apps like Vesktop start without a tray icon
    for _, app in ipairs(optional_apps) do
        if not disabled[app.id] then
            hl.exec_cmd("~/.config/hypr/scripts/after-tray.sh " .. app.cmd)
        end
    end
end)
