-- Default apps and key combos can be changed in hypr-settings (it writes user_overrides.lua); these are the fallbacks.
local ok, overrides = pcall(require, "user_overrides")
local has_overrides = ok and type(overrides) == "table"
local apps = (has_overrides and overrides.apps) or {}
local custom_keys = (has_overrides and type(overrides.keybinds) == "table" and overrides.keybinds) or {}
local terminal = apps.terminal or "ghostty"
local file_manager = apps.file_manager or "thunar"
local menu = "~/.config/rofi/launchers/categorized/launcher.sh"
local wallpaper_menu = "~/.config/rofi/wallpaper/wallpaper.sh"
local browser = apps.browser or "zen-browser"
local store = apps.store or "flatpak run io.github.kolunmi.Bazaar"
local main_mod = "SUPER"

-- Rebindable keybinds. hypr-settings reads this list (Keybinds page), so keep each row in the form
--   { id = "unique_name", label = "What it does", keys = "SUPER + T", action = ..., opts = { ... } },
-- and put a "-- group: Name" comment above each section. A new row shows up in the settings app by itself.
-- KEYBINDS-BEGIN
local binds = {
    -- group: Apps
    { id = "terminal", label = "Open terminal", keys = "SUPER + T", action = hl.dsp.exec_cmd(terminal) },
    { id = "store", label = "Open app store", keys = "SUPER + A", action = hl.dsp.exec_cmd(store) },
    { id = "assistant", label = "Open the assistant", keys = "SUPER + C", action = hl.dsp.exec_cmd("~/.config/hypr/scripts/assistant-toggle.sh") },
    { id = "browser", label = "Open web browser", keys = "SUPER + B", action = hl.dsp.exec_cmd(browser) },
    { id = "obsidian", label = "Open Obsidian", keys = "SUPER + O", action = hl.dsp.exec_cmd("flatpak run md.obsidian.Obsidian") },
    { id = "file_manager", label = "Open file manager", keys = "SUPER + E", action = hl.dsp.exec_cmd(file_manager) },
    { id = "editor", label = "Open Zed editor", keys = "SUPER + Z", action = hl.dsp.exec_cmd("zeditor") },
    { id = "launcher", label = "App launcher", keys = "SUPER + SPACE", action = hl.dsp.exec_cmd(menu) },
    { id = "wallpaper", label = "Wallpaper picker", keys = "SUPER + W", action = hl.dsp.exec_cmd(wallpaper_menu) },
    { id = "clipboard", label = "Clipboard history", keys = "SUPER + CTRL + C", action = hl.dsp.exec_cmd("clipvault list | rofi -dmenu -display-columns 2 | clipvault get | wl-copy") },
    { id = "cheatsheet", label = "Keybind cheatsheet", keys = "SUPER + K", action = hl.dsp.exec_cmd("~/.config/rofi/cheatsheet/cheatsheet.sh") },
    { id = "screenshot_window", label = "Screenshot a window", keys = "CONTROL + ALT + S", action = hl.dsp.exec_cmd("hyprshot -m window -o ~/Pictures/screenshots") },
    { id = "screenshot_region", label = "Screenshot a region", keys = "CONTROL + SHIFT + S", action = hl.dsp.exec_cmd("hyprshot -m region -o ~/Pictures/screenshots") },

    -- group: Windows
    { id = "close", label = "Close window", keys = "SUPER + Q", action = hl.dsp.window.close() },
    { id = "float", label = "Float / tile window", keys = "SUPER + V", action = hl.dsp.window.float({ action = "toggle" }) },
    { id = "pseudo", label = "Pseudo-tile window", keys = "SUPER + P", action = hl.dsp.window.pseudo() },
    { id = "split", label = "Toggle split direction", keys = "SUPER + J", action = hl.dsp.layout("togglesplit") },
    -- `hyprctl dispatch fullscreen[ 1]` stopped working after the Lua migration:
    -- hyprctl's `dispatch` now expects a Lua dispatcher expression, not the old
    -- legacy dispatcher names. Use the native dispatcher directly instead.
    { id = "fullscreen", label = "Fullscreen", keys = "SUPER + SHIFT + F", action = hl.dsp.window.fullscreen() },
    { id = "maximize", label = "Maximize", keys = "SUPER + CTRL + F", action = hl.dsp.window.fullscreen({ mode = "maximized" }) },
    { id = "focus_left", label = "Focus window on the left", keys = "SUPER + left", action = hl.dsp.focus({ direction = "left" }) },
    { id = "focus_right", label = "Focus window on the right", keys = "SUPER + right", action = hl.dsp.focus({ direction = "right" }) },
    { id = "focus_up", label = "Focus window above", keys = "SUPER + up", action = hl.dsp.focus({ direction = "up" }) },
    { id = "focus_down", label = "Focus window below", keys = "SUPER + down", action = hl.dsp.focus({ direction = "down" }) },
    -- `hyprctl dispatch resizeactive 'x y'` is legacy syntax and no longer works
    -- under the Lua config parser; use the native window.resize dispatcher.
    { id = "resize_left", label = "Shrink window width", keys = "SUPER + SHIFT + left", action = hl.dsp.window.resize({ x = -50, y = 0, relative = true }), opts = { repeating = true } },
    { id = "resize_right", label = "Grow window width", keys = "SUPER + SHIFT + right", action = hl.dsp.window.resize({ x = 50, y = 0, relative = true }), opts = { repeating = true } },
    { id = "resize_up", label = "Shrink window height", keys = "SUPER + SHIFT + up", action = hl.dsp.window.resize({ x = 0, y = -50, relative = true }), opts = { repeating = true } },
    { id = "resize_down", label = "Grow window height", keys = "SUPER + SHIFT + down", action = hl.dsp.window.resize({ x = 0, y = 50, relative = true }), opts = { repeating = true } },

    -- group: Workspaces and monitors
    { id = "special_toggle", label = "Show / hide scratch workspace", keys = "SUPER + CTRL + S", action = hl.dsp.workspace.toggle_special("magic") },
    { id = "special_move", label = "Send window to scratch workspace", keys = "SUPER + SHIFT + S", action = hl.dsp.window.move({ workspace = "special:magic" }) },
    { id = "workspace_next", label = "Next workspace (scroll down)", keys = "SUPER + mouse_down", action = hl.dsp.focus({ workspace = "e+1" }) },
    { id = "workspace_prev", label = "Previous workspace (scroll up)", keys = "SUPER + mouse_up", action = hl.dsp.focus({ workspace = "e-1" }) },
    { id = "monitor_dp1", label = "Focus monitor DP-1", keys = "SUPER + F12", action = hl.dsp.focus({ monitor = "DP-1" }) },

    -- group: Session and system
    { id = "reload", label = "Reload Hyprland", keys = "SUPER + SHIFT + R", action = hl.dsp.exec_cmd("hyprctl reload") },
    { id = "lock", label = "Lock the screen", keys = "SUPER + L", action = hl.dsp.exec_cmd("loginctl lock-session") },
    { id = "restart_all", label = "Restart bar and helpers", keys = "SUPER + N", action = hl.dsp.exec_cmd("~/.config/hypr/scripts/restart.sh all") },
    { id = "restart_waybar", label = "Restart the bar only", keys = "SUPER + SHIFT + N", action = hl.dsp.exec_cmd("~/.config/hypr/scripts/restart.sh waybar") },
    { id = "exit", label = "Exit Hyprland", keys = "SUPER + END", action = hl.dsp.exit() },
    { id = "gamemode", label = "Toggle game mode", keys = "SUPER + SHIFT + G", action = hl.dsp.exec_cmd("~/.config/hypr/scripts/gamemode.sh") },
    { id = "ollama_start", label = "Start Ollama", keys = "SUPER + CTRL + O", action = hl.dsp.exec_cmd("~/.config/hypr/scripts/ollama.sh") },
    { id = "ollama_stop", label = "Stop Ollama", keys = "SUPER + SHIFT + O", action = hl.dsp.exec_cmd("~/.config/hypr/scripts/stop_ollama.sh") },
}
-- KEYBINDS-END

for _, b in ipairs(binds) do
    local keys = custom_keys[b.id]
    if type(keys) ~= "string" or keys == "" then
        keys = b.keys
    end
    if keys ~= "none" then -- "none" means the user left it unbound
        if b.opts then
            hl.bind(keys, b.action, b.opts)
        else
            hl.bind(keys, b.action)
        end
    end
end

-- Not rebindable in hypr-settings: workspace numbers, mouse drag and the media keys.
for workspace = 1, 10 do
    local key = workspace % 10
    hl.bind(main_mod .. " + " .. key, hl.dsp.focus({ workspace = workspace }))
    hl.bind(main_mod .. " + SHIFT + " .. key, hl.dsp.window.move({ workspace = workspace }))
end

hl.bind(main_mod .. " + mouse:272", hl.dsp.window.drag(), { mouse = true })
hl.bind(main_mod .. " + mouse:273", hl.dsp.window.resize(), { mouse = true })

local repeating_locked = { locked = true, repeating = true }
hl.bind("XF86AudioRaiseVolume", hl.dsp.exec_cmd("wpctl set-volume -l 1 @DEFAULT_AUDIO_SINK@ 5%+"), repeating_locked)
hl.bind("XF86AudioLowerVolume", hl.dsp.exec_cmd("wpctl set-volume @DEFAULT_AUDIO_SINK@ 5%-"), repeating_locked)
hl.bind("XF86AudioMute", hl.dsp.exec_cmd("wpctl set-mute @DEFAULT_AUDIO_SINK@ toggle"), repeating_locked)
hl.bind("XF86AudioMicMute", hl.dsp.exec_cmd("wpctl set-mute @DEFAULT_AUDIO_SOURCE@ toggle"), repeating_locked)
hl.bind("XF86MonBrightnessUp", hl.dsp.exec_cmd("brightnessctl -e4 -n2 set 5%+"), repeating_locked)
hl.bind("XF86MonBrightnessDown", hl.dsp.exec_cmd("brightnessctl -e4 -n2 set 5%-"), repeating_locked)

local locked = { locked = true }
hl.bind("XF86AudioNext", hl.dsp.exec_cmd("playerctl next"), locked)
hl.bind("XF86AudioPause", hl.dsp.exec_cmd("playerctl play-pause"), locked)
hl.bind("XF86AudioPlay", hl.dsp.exec_cmd("playerctl play-pause"), locked)
hl.bind("XF86AudioPrev", hl.dsp.exec_cmd("playerctl previous"), locked)
