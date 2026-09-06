hl.on("hyprland.start", function()
    local commands = {
        "dbus-update-activation-environment --systemd WAYLAND_DISPLAY XDG_CURRENT_DESKTOP",
        "systemctl --user import-environment WAYLAND_DISPLAY XDG_CURRENT_DESKTOP",
        "systemctl --user start graphical-session.target",
        "discord",
        "com.nextcloud.desktopclient.nextcloud --background",
        "openrgb --startminimized -p Ice.orp",
        "coolercontrol",
        "solaar --w hide",
        "com.bitwarden.desktop --hidden",
        "org.localsend.localsend_app --hidden",
        "hyprctl setcursor Future-cursors 24",
        "awww-daemon --format xrgb",
        "systemctl --user start hyprpolkitagent",
        "systemctl --user enable --now hyprpolkitagent.service",
        "waybar",
        "nm-applet",
        "swaync",
        "hypridle",
        "wl-paste --watch clipvault store",
        "arch-update --tray",
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
end)
