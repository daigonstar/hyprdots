#!/usr/bin/env bash
case "$1" in
    swaync)
        pkill swaync || true
        sleep 0.1
        ~/.config/swaync/launch.sh &
        python3 ~/.config/hypr/tray/quick_tray.py &  # does nothing if it is still running
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
        python3 ~/.config/hypr/tray/quick_tray.py &  # does nothing if it is still running
        ;;
esac
