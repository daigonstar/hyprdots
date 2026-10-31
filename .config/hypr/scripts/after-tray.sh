#!/usr/bin/env bash
# Runs a command once the bar's tray is ready (autostart.lua starts the optional apps through this).
# Electron apps such as Vesktop look for the tray only once, when they start: started before the bar,
# they never show a tray icon. Gives up waiting after 20 seconds and runs the command anyway.
#   after-tray.sh <command line>
for _ in $(seq 40); do
    busctl --user status org.kde.StatusNotifierWatcher >/dev/null 2>&1 && break
    sleep 0.5
done
exec bash -c "$*"
