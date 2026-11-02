#!/bin/bash
# Game Mode. Turning off all animations

notif="$HOME/.config/rofi/images/ja.png"
SCRIPTSDIR="$HOME/.config/hypr/scripts"


# Since the hyprland.lua migration, hyprctl no longer supports the legacy
# `keyword` command ("keyword can't work with non-legacy parsers. Use eval.")
# and `getoption` now reports booleans as "true"/"false" instead of "1"/"0".
HYPRGAMEMODE=$(hyprctl getoption animations:enabled | awk 'NR==1{print $2}')
if [ "$HYPRGAMEMODE" = "true" ] ; then
    hyprctl eval '
        hl.config({
            animations = { enabled = false },
            decoration = {
                shadow = { enabled = false },
                blur = { enabled = false },
                rounding = 0,
            },
            general = {
                gaps_in = 0,
                gaps_out = 0,
                border_size = 1,
            },
        })
        hl.window_rule({
            name = "gamemode-opacity",
            match = { class = ".*" },
            opacity = "1 override 1 override 1 override",
        })
    '

    awww kill
    notify-send -e -u low -i "$notif" " Gamemode:" " enabled"
    exit
else
    # Puts back the wallpaper, and Hyprland's own settings by reloading. The bar and notifications are left alone: they
    # were never changed, and restarting them would flash the bar and lose your notifications.
    (setsid awww-daemon --format xrgb >/dev/null 2>&1 &)
    for _ in {1..30}; do
        awww query >/dev/null 2>&1 && break
        sleep 0.1
    done
    awww img "$(readlink -f "$HOME/.config/rofi/.current_wallpaper")"
    hyprctl reload
    notify-send -e -u normal -i "$notif" " Gamemode:" " disabled"
    exit
fi
