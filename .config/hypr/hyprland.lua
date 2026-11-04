-- Hyprland 0.55+ loads this file in preference to hyprland.conf.
-- The legacy .conf files remain available as a rollback path.

local safe = require("safe_config")

safe.load("monitors")
safe.load("workspaces")
safe.load("keybinds")
safe.load("input")
safe.load("autostart")
safe.load("environment")
safe.load("window")
safe.load("click_away")

-- Overrides written by hypr-settings (settings/ folder). Optional: without the file nothing changes.
local ok, overrides = pcall(require, "user_overrides")
if ok and type(overrides) == "table" and overrides.apply then
    pcall(overrides.apply)
end

safe.finish()
