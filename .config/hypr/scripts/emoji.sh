#!/usr/bin/env bash
# Pick an emoji in rofi (so it has your theme): it is typed into the window you were in, and copied if that fails.
if ! command -v rofimoji >/dev/null || ! command -v wtype >/dev/null; then
    notify-send "Emoji picker" "Needs rofimoji and wtype (sudo pacman -S rofimoji wtype noto-fonts-emoji)"
    exit 1
fi
exec rofimoji --selector rofi --action type --typer wtype --clipboarder wl-copy --prompt "Emoji" --skin-tone neutral
