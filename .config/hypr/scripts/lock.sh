#!/usr/bin/env bash
# Locks the screen (Super+L and the power menu's Lock).
# Asks the session to lock, so hypridle runs its lock_cmd as it does for the idle timer and before sleep. If nothing
# answers (hypridle not running), runs that same lock command directly, so locking never silently does nothing.
loginctl lock-session
for _ in 1 2 3 4 5 6 7 8 9 10; do
    pidof hyprlock >/dev/null && exit 0
    sleep 0.1
done
cmd=$(sed -n 's/^[[:space:]]*lock_cmd[[:space:]]*=[[:space:]]*//p' "$HOME/.config/hypr/hypridle.local.conf" 2>/dev/null | head -n1)
exec bash -c "${cmd:-$HOME/.config/hypr/scripts/lock-screen.sh all}"
