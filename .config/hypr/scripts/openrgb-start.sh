#!/usr/bin/env bash
# Starts OpenRGB with the lighting profile you saved most recently, or with none if you have not saved one.
command -v openrgb >/dev/null 2>&1 || exit 0
profile="$(ls -t "$HOME/.config/OpenRGB/profiles" 2>/dev/null | head -n1)"
exec openrgb --startminimized ${profile:+-p "$profile"}
