-- A click outside a popup closes it, wherever the click lands: another screen, the bar, the desktop or a window.
-- The click still reaches whatever is under it. Popups that fill a screen close themselves when clicked on that screen.
local BAR_WAIT = "sleep 0.25; "  -- bar buttons are toggles: the button goes first, so it closes its own popup rather than reopening it

local close = {
    rofi = "pkill -x rofi",
    launcher = "pkill -f '[h]ypr/launcher/launcher.py'",
    cheatsheet = "pkill -f '[h]ypr/cheatsheet/cheatsheet.py'",
    powermenu = "pkill -f '[p]owermenu/powermenu.py'",
    calendar = 'kill "$(cat "$XDG_RUNTIME_DIR/waybar-calendar.pid")"',
    ["hyprdots-notes"] = "pkill -USR2 -f '[h]ypr/notes/notes.py'",  -- hides it unless it is pinned
    ["quick-tray-overview"] = "pkill -HUP -f '[h]ypr/tray/quick_tray'",
    ["quick-tray"] = "swaync-client -cp -sw",  -- opens and closes with swaync's panel, which swaync 0.12 draws no window for
}
-- swaync's toast window is as tall as the screen, so its size says nothing about where the toasts are. All of them are
-- hidden on every click, after the wait so a click on a toast still counts. They stay listed in the quick tray.
local HIDE_TOASTS = BAR_WAIT .. "swaync-client --hide-all -sw"

local function contains(layer, at)
    return at.x >= layer.x and at.x < layer.x + layer.w and at.y >= layer.y and at.y < layer.y + layer.h
end

local function clicked()
    local at = hl.get_cursor_pos()
    if not at then return end
    local on_bar, open = false, {}
    for _, layer in ipairs(hl.get_layers()) do
        if layer.mapped then
            local inside = contains(layer, at)
            on_bar = on_bar or (inside and layer.namespace == "waybar")
            if layer.namespace == "swaync-notification-window" then
                open[HIDE_TOASTS] = true
            elseif close[layer.namespace] and not inside then
                open[layer.namespace] = true
            end
        end
    end
    for what in pairs(open) do
        local command = close[what]
        hl.exec_cmd(command and ((on_bar and BAR_WAIT or "") .. command) or what)
    end
end

hl.bind("mouse:272", clicked, { non_consuming = true })
hl.bind("mouse:273", clicked, { non_consuming = true })
