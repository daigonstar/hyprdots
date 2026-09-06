#!/bin/bash
# Game Mode. Turning off all animations

notif="$HOME/.config/swaync/images/ja.png"
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
	awww-daemon && awww img "$HOME/.config/rofi/.current_wallpaper" &
	sleep 0.1
	"${SCRIPTSDIR}/wallust.sh" "$HOME/.config/rofi/.current_wallpaper"
	sleep 0.5
	${SCRIPTSDIR}/refresh.sh	 
    notify-send -e -u normal -i "$notif" " Gamemode:" " disabled"
    exit
fi
hyprctl reload