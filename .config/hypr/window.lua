local colors = require("wallust.colors")

hl.config({
    general = {
        gaps_in = 5,
        gaps_out = 10,
        border_size = 2,
        col = {
            active_border = colors.color12,
            inactive_border = colors.color10,
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
            color = colors.color13,
            color_inactive = colors.color10,
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
}

for name, points in pairs(curves) do
    hl.curve(name, { type = "bezier", points = points })
end

local animations = {
    { leaf = "windowsIn", enabled = true, speed = 3, bezier = "easeInOutSine", style = "popin" },
    { leaf = "windowsOut", enabled = true, speed = 3, bezier = "easeInOutSine", style = "popin" },
    { leaf = "border", enabled = true, speed = 3, bezier = "easeInOutSine" },
    { leaf = "borderangle", enabled = true, speed = 30, bezier = "easeInOutSine", style = "loop" },
    { leaf = "workspacesIn", enabled = true, speed = 3, bezier = "easeInOutSine", style = "slidefade" },
    { leaf = "workspacesOut", enabled = true, speed = 3, bezier = "easeInOutSine", style = "slidefade" },
    { leaf = "specialWorkspaceIn", enabled = true, speed = 3, bezier = "easeInOutSine", style = "slidevert" },
    { leaf = "specialWorkspaceOut", enabled = true, speed = 3, bezier = "easeInOutSine", style = "slidevert" },
    { leaf = "layersIn", enabled = true, speed = 3, bezier = "easeInOutSine", style = "fade" },
    { leaf = "layersOut", enabled = true, speed = 3, bezier = "easeInOutSine", style = "fade" },
}

for _, animation in ipairs(animations) do
    hl.animation(animation)
end

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
    name = "discord-silent",
    match = { class = "^(discord)$" },
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
    size = { "(monitor_w*0.7)", "(monitor_h*0.8)" },
    center = true,
    animation = "popin 85%",
})
hl.window_rule({
    name = "spotify-magic",
    match = { class = "^(spotify)$" },
    workspace = "special:magic silent",
})
