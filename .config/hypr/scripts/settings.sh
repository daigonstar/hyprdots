#!/usr/bin/env bash
# Opens hypr-settings: one place to change the PC assistant, health monitor, calendars, displays, GTK look,
# Hyprland look, keybinds and default apps. A GTK window from the bar's cog or: settings.sh
# settings.sh --tui opens the terminal version instead (also used automatically over SSH).
dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
if [[ " $* " == *" --tui "* || -z "${WAYLAND_DISPLAY:-}${DISPLAY:-}" ]]; then
    if ! python3 -c "import prompt_toolkit" 2>/dev/null; then
        echo "hypr-settings needs python-prompt_toolkit (sudo pacman -S python-prompt_toolkit)."
        read -rp "Press Enter to close..." _
        exit 1
    fi
elif ! python3 -c "import gi; gi.require_version('Adw', '1')" 2>/dev/null; then
    notify-send "Settings" "Needs libadwaita and python-gobject (sudo pacman -S libadwaita python-gobject). Opening the terminal version."
    exec ghostty -e "$0" --tui
fi
PYTHONPATH="$dir/settings${PYTHONPATH:+:$PYTHONPATH}" exec python3 -m hyprsettings "$@"
