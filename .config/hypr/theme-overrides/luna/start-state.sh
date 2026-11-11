#!/usr/bin/env bash
# XP style's start button on the bar: drawn pressed in while the start menu is open. The start menu
# (launcher/startmenu.py) marks itself open or closed and sends the bar SIGRTMIN+12, which runs this again.
#   start-state.sh [LOGO]    prints the button for waybar: {"text": "LOGO  start", "class": "open"|"closed"}
mark="${XDG_RUNTIME_DIR:-/tmp}/hyprdots-startmenu-open"
if [[ -e "$mark" ]] && pgrep -f '[l]auncher/launcher.py' >/dev/null; then state=open; else state=closed; fi
text="start"
[[ -n "${1:-}" ]] && text="$1  start"
printf '{"text": "%s", "class": "%s", "tooltip": "Open the app launcher"}\n' "$text" "$state"
