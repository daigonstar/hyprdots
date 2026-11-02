#!/usr/bin/env bash
# A screen was plugged in or taken away: the wallpaper is redrawn for the new arrangement, and workspaces you gave a
# screen (settings Workspaces page) go back to it. Unplugging moves them away, and Hyprland does not move them back.
exec 9>"${XDG_RUNTIME_DIR:-/tmp}/monitor-changed.lock"
flock -n 9 || exit 0  # one screen can report several changes at once
sleep 1
awww restore 2>/dev/null
PYTHONPATH="$HOME/.config/hypr/settings" python3 -m hyprsettings.workspaces home
