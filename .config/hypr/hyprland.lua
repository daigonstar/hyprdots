-- Hyprland 0.55+ loads this file in preference to hyprland.conf.
-- The legacy .conf files remain available as a rollback path.

require("monitors")
require("workspaces")
require("keybinds")
require("input")
require("autostart")
require("environment")
require("window")

-- Overrides written by hypr-settings (settings/ folder). Optional: without the file nothing changes.
local ok, overrides = pcall(require, "user_overrides")
if ok and type(overrides) == "table" and overrides.apply then
    pcall(overrides.apply)
end
