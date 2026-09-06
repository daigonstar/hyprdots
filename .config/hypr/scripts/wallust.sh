#!/bin/bash
# /* ---- 💫 https://github.com/JaKooLit 💫 ---- */ ##

# 1. Determine which image to use
if [ -n "$1" ]; then
    # Use the image passed from the selector script
    wallpaper_path="$1"
else
    # Fall back to the wallpaper symlink maintained by the selector.
    wallpaper_path="$HOME/.config/rofi/.current_wallpaper"
fi

# 2. Safety check: Ensure it's a real file
if [ -f "$wallpaper_path" ]; then
    # Resolve symlinks (e.g. when called with .current_wallpaper itself, as
    # gamemode.sh does) so we never `ln -sf` a path onto itself, which would
    # leave .current_wallpaper as a broken self-referencing symlink.
    wallpaper_path="$(readlink -f "$wallpaper_path")"
    echo "Wallust processing: $wallpaper_path"

    # Symlinks for Rofi and Styles
    ln -sf "$wallpaper_path" "$HOME/.config/rofi/.current_wallpaper"
    cp "$wallpaper_path" "$HOME/.config/rofi/.wallpaper_current"

    # 3. Execute Wallust 3.0+ (Flags BEFORE the path)
    # -s: skip terminal sequences for speed
    wallust run -s "$wallpaper_path"
    hyprctl reload

    # 4. Refresh Waybar live
    # SIGUSR2 tells Waybar to re-read CSS without restarting
    killall -SIGUSR2 waybar
    
    # Optional: If you use SwayNC, refresh it too
    # swaync-client -rs
    
    echo "Success! Waybar colors updated."
else
    echo "Error: Invalid wallpaper path: $wallpaper_path"
    exit 1
fi