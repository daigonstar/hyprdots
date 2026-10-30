#!/usr/bin/env bash
# Keybind cheatsheet (see cheatsheet.py). Running it again while it is open closes it.
dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"

# gtk4-layer-shell has to be loaded before GTK itself, hence the preload
shim=/usr/lib/libgtk4-layer-shell.so
if ! python3 -c "import gi; gi.require_version('Gtk4LayerShell', '1.0')" 2>/dev/null || [[ ! -e "$shim" ]]; then
    notify-send "Keybind cheatsheet" "Needs python-gobject, gtk4 and gtk4-layer-shell (sudo pacman -S python-gobject gtk4 gtk4-layer-shell)"
    exit 1
fi
LD_PRELOAD="$shim${LD_PRELOAD:+:$LD_PRELOAD}" exec python3 "$dir/cheatsheet.py" "$@"
