#!/usr/bin/env bash
# Wallpaper picker (see wallpicker.py). Running it again while it is open closes it.
dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
# gtk4-layer-shell has to be loaded before GTK itself, hence the preload
LD_PRELOAD="/usr/lib/libgtk4-layer-shell.so${LD_PRELOAD:+:$LD_PRELOAD}" exec python3 "$dir/wallpicker.py" "$@"
