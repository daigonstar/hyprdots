#!/usr/bin/env bash
case "$1" in
    swaync)
        pkill swaync || true
        sleep 0.1
        ~/.config/swaync/launch.sh &
        ;;
    waybar)
        pkill waybar || true
        sleep 0.1
        ~/.config/waybar/launch.sh &
        ;;
    all|"")
        pkill swaync || true
        pkill waybar || true
        sleep 0.2
        ~/.config/waybar/launch.sh &
        ~/.config/swaync/launch.sh &
        ;;
esac
