#!/usr/bin/env bash
# Locks the screen (Super+L and the power menu's Lock).
# Asks the session to lock, so hypridle runs its lock_cmd as it does for the idle timer and before sleep. If nothing
# answers (hypridle not running), starts hyprlock directly, so locking never silently does nothing.
loginctl lock-session
for _ in 1 2 3 4 5 6 7 8 9 10; do
    pidof hyprlock >/dev/null && exit 0
    sleep 0.1
done
exec hyprlock
