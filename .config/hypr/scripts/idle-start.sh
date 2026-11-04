#!/usr/bin/env bash
# Starts hypridle. hypr-settings (Power & lock page) writes hypridle.local.conf; without it the shipped hypridle.conf is used.
c="$HOME/.config/hypr/hypridle.local.conf"
[[ -f "$c" ]] && exec hypridle -c "$c"
exec hypridle
