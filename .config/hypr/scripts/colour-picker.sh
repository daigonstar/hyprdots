#!/usr/bin/env bash
# Pick a colour anywhere on screen: it goes on the clipboard as #rrggbb, and a notification shows a swatch of it.
if ! command -v hyprpicker >/dev/null; then
    notify-send "Colour picker" "Needs hyprpicker (sudo pacman -S hyprpicker)"
    exit 1
fi
colour="$(hyprpicker -a -f hex)"
[[ "$colour" =~ ^#[0-9a-fA-F]{6}$ ]] || exit 0  # you pressed Escape
swatch="${XDG_RUNTIME_DIR:-/tmp}/colour-swatch.png"
ffmpeg -y -loglevel error -f lavfi -i "color=c=$colour:s=64x64" -frames:v 1 "$swatch"
notify-send -a "Colour picker" -i "$swatch" "$colour" "Copied to the clipboard"
