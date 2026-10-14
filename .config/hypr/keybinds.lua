local terminal = "ghostty"
local file_manager = "thunar"
local menu = "~/.config/rofi/launchers/categorized/launcher.sh"
local wallpaper_menu = "~/.config/rofi/wallpaper/wallpaper.sh"
local browser = "zen-browser"
local store = "flatpak run io.github.kolunmi.Bazaar"
local main_mod = "SUPER"

hl.bind(main_mod .. " + T", hl.dsp.exec_cmd(terminal))
hl.bind(main_mod .. " + A", hl.dsp.exec_cmd(store))
hl.bind(main_mod .. " + C", hl.dsp.exec_cmd("~/.config/hypr/scripts/assistant-toggle.sh"))
hl.bind(main_mod .. " + Q", hl.dsp.window.close())
hl.bind(main_mod .. " + B", hl.dsp.exec_cmd(browser))
hl.bind(main_mod .. " + SHIFT + R", hl.dsp.exec_cmd("hyprctl reload"))
hl.bind(main_mod .. " + W", hl.dsp.exec_cmd(wallpaper_menu))
hl.bind(main_mod .. " + O", hl.dsp.exec_cmd("flatpak run md.obsidian.Obsidian"))
hl.bind(main_mod .. " + E", hl.dsp.exec_cmd(file_manager))
hl.bind(main_mod .. " + V", hl.dsp.window.float({ action = "toggle" }))
hl.bind(main_mod .. " + SPACE", hl.dsp.exec_cmd(menu))
hl.bind(main_mod .. " + P", hl.dsp.window.pseudo())
hl.bind(main_mod .. " + J", hl.dsp.layout("togglesplit"))
hl.bind(main_mod .. " + Z", hl.dsp.exec_cmd("zeditor"))

hl.bind(main_mod .. " + L", hl.dsp.exec_cmd("loginctl lock-session"))
hl.bind(main_mod .. " + N", hl.dsp.exec_cmd("~/.config/hypr/scripts/restart.sh all"))
hl.bind(main_mod .. " + SHIFT + N", hl.dsp.exec_cmd("~/.config/hypr/scripts/restart.sh waybar"))
hl.bind(main_mod .. " + END", hl.dsp.exit())
hl.bind(main_mod .. " + SHIFT + G", hl.dsp.exec_cmd("~/.config/hypr/scripts/gamemode.sh"))
hl.bind(main_mod .. " + CTRL + O", hl.dsp.exec_cmd("~/.config/hypr/scripts/ollama.sh"))
hl.bind(main_mod .. " + SHIFT + O", hl.dsp.exec_cmd("~/.config/hypr/scripts/stop_ollama.sh"))
hl.bind(main_mod .. " + CTRL + C", hl.dsp.exec_cmd("clipvault list | rofi -dmenu -display-columns 2 | clipvault get | wl-copy"))
hl.bind(main_mod .. " + F12", hl.dsp.focus({ monitor = "DP-1" }))

hl.bind("CONTROL + ALT + S", hl.dsp.exec_cmd("hyprshot -m window -o ~/Pictures/screenshots"))
hl.bind("CONTROL + SHIFT + S", hl.dsp.exec_cmd("hyprshot -m region -o ~/Pictures/screenshots"))

hl.bind(main_mod .. " + left", hl.dsp.focus({ direction = "left" }))
hl.bind(main_mod .. " + right", hl.dsp.focus({ direction = "right" }))
hl.bind(main_mod .. " + up", hl.dsp.focus({ direction = "up" }))
hl.bind(main_mod .. " + down", hl.dsp.focus({ direction = "down" }))

-- `hyprctl dispatch resizeactive 'x y'` is legacy syntax and no longer works
-- under the Lua config parser; use the native window.resize dispatcher.
hl.bind(main_mod .. " + SHIFT + left", hl.dsp.window.resize({ x = -50, y = 0, relative = true }), { repeating = true })
hl.bind(main_mod .. " + SHIFT + right", hl.dsp.window.resize({ x = 50, y = 0, relative = true }), { repeating = true })
hl.bind(main_mod .. " + SHIFT + up", hl.dsp.window.resize({ x = 0, y = -50, relative = true }), { repeating = true })
hl.bind(main_mod .. " + SHIFT + down", hl.dsp.window.resize({ x = 0, y = 50, relative = true }), { repeating = true })

for workspace = 1, 10 do
    local key = workspace % 10
    hl.bind(main_mod .. " + " .. key, hl.dsp.focus({ workspace = workspace }))
    hl.bind(main_mod .. " + SHIFT + " .. key, hl.dsp.window.move({ workspace = workspace }))
end

hl.bind(main_mod .. " + CTRL + S", hl.dsp.workspace.toggle_special("magic"))
hl.bind(main_mod .. " + SHIFT + S", hl.dsp.window.move({ workspace = "special:magic" }))
hl.bind(main_mod .. " + mouse_down", hl.dsp.focus({ workspace = "e+1" }))
hl.bind(main_mod .. " + mouse_up", hl.dsp.focus({ workspace = "e-1" }))
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

-- `hyprctl dispatch fullscreen[ 1]` stopped working after the Lua migration:
-- hyprctl's `dispatch` now expects a Lua dispatcher expression, not the old
-- legacy dispatcher names. Use the native dispatcher directly instead.
hl.bind(main_mod .. " + SHIFT + F", hl.dsp.window.fullscreen())
hl.bind(main_mod .. " + CTRL + F", hl.dsp.window.fullscreen({ mode = "maximized" }))
hl.bind(main_mod .. " + K", hl.dsp.exec_cmd("~/.config/rofi/cheatsheet/cheatsheet.sh"))
