local colors = require("wallust.colors")
-- Border colours from the settings Theme page (hypr/theme.lua, rewritten when the wallpaper changes); without it,
-- the wallust colours below
local has_theme, theme = pcall(require, "theme")
if not has_theme or type(theme) ~= "table" then
    theme = {}
end

hl.config({
    general = {
        gaps_in = 5,
        gaps_out = 10,
        border_size = 2,
        col = {
            active_border = theme.active_border or colors.color12,
            inactive_border = theme.inactive_border or colors.color10,
        },
        resize_on_border = false,
        allow_tearing = true,
        layout = "dwindle",
    },
    decoration = {
        rounding = 18,
        rounding_power = 2,
        active_opacity = 1.0,
        inactive_opacity = 1.0,
        shadow = {
            enabled = false,
            range = 4,
            render_power = 3,
            color = theme.group_active or colors.color13,
            color_inactive = theme.group_inactive or colors.color10,
        },
        blur = {
            enabled = true,
            size = 3,
            passes = 1,
            vibrancy = 0.1696,
        },
    },
    animations = {
        enabled = true,
    },
    dwindle = {
        preserve_split = true,
    },
    master = {
        new_status = "master",
    },
    misc = {
        force_default_wallpaper = -1,
        disable_hyprland_logo = false,
    },
})

local curves = {
    wind = {{0.05, 0.9}, {0.1, 1.05}},
    winIn = {{0.1, 1.1}, {0.1, 1.1}},
    winOut = {{0.3, -0.3}, {0, 1}},
    linear = {{1, 1}, {1, 1}},
    Cubic = {{0.1, 0.1}, {0.1, 1}},
    overshot = {{0.05, 0.9}, {0.1, 1.1}},
    ["ease-in-out"] = {{0.17, 0.67}, {0.83, 0.67}},
    ["ease-in"] = {{0.17, 0.67}, {0.83, 0.67}},
    ["ease-out"] = {{0.42, 0}, {1, 1}},
    easeInOutSine = {{0.37, 0}, {0.63, 1}},
    easeInSine = {{0.12, 0}, {0.39, 0}},
    easeOutSine = {{0.61, 1}, {0.88, 1}},
    decel = {{0.05, 0.7}, {0.1, 1}},
    accel = {{0.3, 0}, {0.8, 0.15}},
}

for name, points in pairs(curves) do
    hl.curve(name, { type = "bezier", points = points })
end

-- Things arrive with a quick start and settle gently (decel, wind), and leave faster than they came (accel), so opening
-- feels responsive and closing is out of your way. Speed is in tenths of a second.
local animations = {
    { leaf = "windowsIn", enabled = true, speed = 2.5, bezier = "wind", style = "popin 90%" },
    { leaf = "windowsOut", enabled = true, speed = 1.5, bezier = "accel", style = "popin 95%" },
    { leaf = "windowsMove", enabled = true, speed = 3, bezier = "wind", style = "slide" },
    { leaf = "fadeIn", enabled = true, speed = 2, bezier = "decel" },
    { leaf = "fadeOut", enabled = true, speed = 1.5, bezier = "accel" },
    { leaf = "border", enabled = true, speed = 2, bezier = "decel" },
    -- Rotates gradient borders, and keeps redrawing the screen to do it. Yours are one colour, so there is nothing to see.
    { leaf = "borderangle", enabled = false },
    { leaf = "workspacesIn", enabled = true, speed = 3, bezier = "decel", style = "slidefade 20%" },
    { leaf = "workspacesOut", enabled = true, speed = 3, bezier = "decel", style = "slidefade 20%" },
    { leaf = "specialWorkspaceIn", enabled = true, speed = 2.5, bezier = "decel", style = "slidevert" },
    { leaf = "specialWorkspaceOut", enabled = true, speed = 2, bezier = "accel", style = "slidevert" },
    { leaf = "layersIn", enabled = true, speed = 2, bezier = "decel", style = "fade" },
    { leaf = "layersOut", enabled = true, speed = 1.5, bezier = "accel", style = "fade" },
}

for _, animation in ipairs(animations) do
    hl.animation(animation)
end

-- Panels come from where they live
hl.layer_rule({ name = "quick-tray-slide", match = { namespace = "^quick-tray$" }, animation = "slide right" })
hl.layer_rule({ name = "quick-tray-level", match = { namespace = "^quick-tray-osd$" }, animation = "slide bottom" })
hl.layer_rule({ name = "quick-tray-overview", match = { namespace = "^quick-tray-overview$" }, animation = "fade" })
hl.layer_rule({ name = "quick-tray-switcher", match = { namespace = "^quick-tray-switcher$" }, animation = "popin 95%" })

hl.window_rule({
    name = "chat-workspace",
    match = { class = "^(discord|WebCord|Vesktop)$" },
    workspace = "2",
})
hl.window_rule({
    name = "steam-workspace",
    match = { class = "^steam_app_.*$" },
    workspace = "3",
})
hl.window_rule({
    name = "steam-fullscreen",
    match = { class = "^steam_app_.*$" },
    fullscreen = true,
})
hl.window_rule({
    name = "steam-immediate",
    match = { class = "^steam_app_.*$" },
    immediate = true,
})
hl.window_rule({
    name = "steam-ui",
    match = { class = "^steam$" },
    workspace = "1",
})
hl.window_rule({
    name = "lutris",
    match = { title = "^Lutris$" },
    workspace = "1",
})
hl.window_rule({
    name = "heroic",
    match = { class = "^com.heroicgameslauncher.hgl$" },
    workspace = "5",
})
hl.window_rule({
    name = "remmina",
    match = { class = "^Remmina$" },
    workspace = "4",
    fullscreen = true,
})
hl.window_rule({
    name = "vesktop-silent",
    match = { class = "^(vesktop)$" },
    workspace = "2 silent",
})
hl.window_rule({
    name = "bitwarden-silent",
    match = { class = "^(com.bitwarden.desktop)$" },
    workspace = "3 silent",
})
hl.window_rule({
    name = "solaar-silent",
    match = { class = "^(solaar)$" },
    workspace = "5 silent",
})
hl.window_rule({
    name = "assistant-scratchpad",
    match = { class = "^com\\.hyprdots\\.assistant$" },
    workspace = "special:agent",
    float = true,
    size = { "(monitor_w*0.8)", "(monitor_h*0.8)" },
    center = true,
    animation = "popin 85%",
})
hl.window_rule({
    name = "spotify-magic",
    match = { class = "^(spotify)$" },
    workspace = "special:magic silent",
})
