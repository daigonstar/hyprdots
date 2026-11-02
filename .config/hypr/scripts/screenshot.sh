#!/usr/bin/env bash
# Takes a screenshot (region, window or screen), which hyprshot saves and copies to the clipboard, then offers what to
# do with it. The buttons wait on the popup for a minute; after that the picture is still saved and on the clipboard.
dir="$HOME/Pictures/screenshots"
file="$dir/$(date +'%Y-%m-%d-%H%M%S').png"
mkdir -p "$dir"

case "${1:-region}" in
    screen) mode=(-m output -m active) ;;
    window) mode=(-m window) ;;
    *) mode=(-m region) ;;
esac
hyprshot "${mode[@]}" -s -o "$dir" -f "$(basename "$file")"
[[ -f "$file" ]] || exit 0  # you pressed Escape

actions=(-A open=Open -A folder="Show in folder")
command -v satty >/dev/null && actions=(-A edit=Edit "${actions[@]}")
choice="$(timeout 60 notify-send -a Screenshot -i "$file" "${actions[@]}" --wait "Screenshot saved" "Copied to the clipboard")"
case "$choice" in
    edit) exec satty --filename "$file" --output-filename "$file" --copy-command wl-copy ;;
    open) exec xdg-open "$file" ;;
    folder) exec xdg-open "$dir" ;;
esac
