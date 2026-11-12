#!/usr/bin/env bash
# Emoji picker (Super+.): the emoji you pick is typed into the window you were in. Running it again while it is open
# closes it. The Rust picker (hypr/emoji, built by emoji/build.sh) when it is installed, rofimoji otherwise.
# HYPRDOTS_EMOJI=rofi picks rofimoji anyway.
picker="${HYPRDOTS_LIB:-$HOME/.local/lib/hyprdots}/hyprdots-emoji"
shim=/usr/lib/libgtk4-layer-shell.so

if [[ "${HYPRDOTS_EMOJI:-}" != rofi && -x "$picker" && -e "$shim" ]]; then
    pkill -x hyprdots-emoji && exit 0
    # gtk4-layer-shell has to be loaded before GTK itself, hence the preload
    LD_PRELOAD="$shim${LD_PRELOAD:+:$LD_PRELOAD}" exec "$picker"
fi

if ! command -v rofimoji >/dev/null || ! command -v wtype >/dev/null; then
    notify-send "Emoji picker" "Needs rofimoji and wtype (sudo pacman -S rofimoji wtype noto-fonts-emoji), or run ~/.config/hypr/emoji/build.sh"
    exit 1
fi
exec rofimoji --selector rofi --action type --typer wtype --clipboarder wl-copy --prompt "Emoji" --skin-tone neutral
