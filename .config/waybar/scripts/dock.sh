#!/usr/bin/env bash
# A theme override's dock (Mac style): see dock.py. Started by launch.sh when config.dock.json is there.
# gtk4-layer-shell has to be loaded before GTK itself (for the strips along the bottom edges), hence the preload.
dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
pkill -f '[w]aybar/scripts/dock.py' 2>/dev/null  # one dock at a time, even if the bar was started by hand
shim=/usr/lib/libgtk4-layer-shell.so
[[ -e "$shim" ]] || exit 0  # needs gtk4-layer-shell (sudo pacman -S gtk4-layer-shell)
LD_PRELOAD="$shim${LD_PRELOAD:+:$LD_PRELOAD}" exec python3 "$dir/dock.py"
