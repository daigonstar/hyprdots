#!/usr/bin/env bash
# Opens hypr-settings: one place to change the PC assistant, health monitor, calendars, displays, GTK look,
# Hyprland look and default apps. Run it from a terminal, the bar's cog, or: settings.sh
dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
if ! python3 -c "import prompt_toolkit" 2>/dev/null; then
    echo "hypr-settings needs python-prompt_toolkit (sudo pacman -S python-prompt_toolkit)."
    read -rp "Press Enter to close..." _
    exit 1
fi
PYTHONPATH="$dir/settings${PYTHONPATH:+:$PYTHONPATH}" exec python3 -m hyprsettings "$@"
