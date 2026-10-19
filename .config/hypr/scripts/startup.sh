#!/usr/bin/env bash

# 1. Launch Bitwarden natively on Wayland silently in the background
ELECTRON_OZONE_PLATFORM_HINT=wayland flatpak run com.bitwarden.desktop > /dev/null 2>&1 &

# 2. Wait up to 5 seconds for Hyprland to detect the window
for i in {1..50}; do
    if hyprctl clients | grep -q "class: com.bitwarden.desktop"; then
        # 3. Use the unified address/class identifier syntax
        hyprctl dispatch closewindow "class:com.bitwarden.desktop"
        break
    fi
    sleep 0.1
done
