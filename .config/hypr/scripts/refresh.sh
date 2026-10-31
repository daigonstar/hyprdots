#!/usr/bin/env bash
# After a wallpaper change (the wallpaper picker and game mode run this): closes rofi and restarts the bar and
# notifications through their launch scripts, so your bar layout (settings Bar layout page) and theme are kept.
# The colours themselves are already updated by wallust.sh.
pkill -x rofi || true
exec "$HOME/.config/hypr/scripts/restart.sh" all
