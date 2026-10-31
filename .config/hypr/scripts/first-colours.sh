#!/usr/bin/env bash
# Fills in the files that follow your wallpaper when they are missing (a new install, or a clean checkout).
# They are git-ignored because wallust and the wallpaper picker rewrite them on every wallpaper change:
#   - the colour files wallust writes: start from the .default copy next to each one
#   - ~/.config/rofi/.current_wallpaper (the lock screen and game mode use it): points at a shipped wallpaper
# Never touches files that already exist. Run by hyprinstall.sh and update.sh.
set -u
cfg="$HOME/.config"

for f in waybar/colors/colors.css rofi/colors.rasi swaync/wallust/colors-wallust.css hypr/wallust/colors.lua; do
    if [[ ! -e "$cfg/$f" && -f "$cfg/$f.default" ]]; then
        cp "$cfg/$f.default" "$cfg/$f"
        echo "Added starting colours: ~/.config/$f"
    fi
done

link="$cfg/rofi/.current_wallpaper"
if [[ ! -e "$link" ]]; then  # missing, or a link to a file that is gone
    walls="$HOME/Pictures/wallpapers"
    pick="$walls/Hyprland_in_Space.png"
    [[ -f "$pick" ]] || pick="$(find "$walls" -maxdepth 1 -type f \( -iname '*.png' -o -iname '*.jpg' -o -iname '*.jpeg' -o -iname '*.webp' \) 2>/dev/null | sort | head -n1)"
    if [[ -n "$pick" && -f "$pick" ]]; then
        ln -sfn "$pick" "$link"
        echo "Current wallpaper set to $pick"
    fi
fi
exit 0
