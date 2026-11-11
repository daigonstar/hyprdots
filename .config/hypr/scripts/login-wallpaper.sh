#!/usr/bin/env bash
# At login: colours follow the wallpaper awww remembers. On a new install it remembers none, so start the one first-colours.sh picked.
for _ in {1..30}; do
    awww query >/dev/null 2>&1 && break
    sleep 0.1
done
wallpaper="$(awww query | grep -oP 'image: \K.*' | head -n1)"
if [[ -z "$wallpaper" ]]; then
    wallpaper="$(readlink -f "$HOME/.config/rofi/.current_wallpaper")"
    [[ -f "$wallpaper" ]] || exit 0
    awww img "$wallpaper"
fi
wallust run "$wallpaper" && PYTHONPATH="$HOME/.config/hypr/settings" python3 -m hyprsettings.design refresh
# a video wallpaper: awww shows its still, and this plays the video over it again
bash "$HOME/.config/hypr/scripts/video-wallpaper.sh" sync
