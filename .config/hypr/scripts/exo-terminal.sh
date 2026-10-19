#!/usr/bin/env bash
# Makes Thunar's "Open Terminal Here" (and anything else that calls exo-open) use your terminal.
# exo-open needs a helper program, xfce4-mime-helper, that only comes with the Xfce desktop; without it
# those menu items fail with: Failed to launch preferred application for category "TerminalEmulator".
# This installs a small stand-in (xfce4-mime-helper next to this script) and records the terminal to use.
# Usage: exo-terminal.sh [terminal command]   (defaults to the last one used, else ghostty). Safe to run any time.
cfg="${XDG_CONFIG_HOME:-$HOME/.config}/hypr-settings"
# No argument: keep the terminal chosen before (so updating never resets it), else ghostty
term="${1:-$(cat "$cfg/terminal" 2>/dev/null)}"
term="${term:-ghostty}"
# Ghostty normally hands a new window to the copy that is already running, which forgets the folder
# "Open Terminal Here" asked for. A separate instance keeps it.
case "$term" in
    ghostty|ghostty\ *) [[ "$term" == *gtk-single-instance* ]] || term="$term --gtk-single-instance=false" ;;
esac

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
bin="$HOME/.local/bin"
mkdir -p "$cfg" "$bin"
printf '%s\n' "$term" > "$cfg/terminal"

# Never replace a real Xfce helper; only manage our own link
if [[ ! -e "$bin/xfce4-mime-helper" || -L "$bin/xfce4-mime-helper" ]]; then
    ln -sfn "$here/xfce4-mime-helper" "$bin/xfce4-mime-helper"
fi

# Clean up files an earlier version of this script wrote
rm -f "${XDG_DATA_HOME:-$HOME/.local/share}/applications/hyprdots-terminal.desktop"
rc="${XDG_CONFIG_HOME:-$HOME/.config}/xfce4/helpers.rc"
if [[ -f "$rc" ]] && grep -qx 'TerminalEmulator=hyprdots-terminal\(.desktop\)\?' "$rc"; then
    grep -vx 'TerminalEmulator=hyprdots-terminal\(.desktop\)\?' "$rc" | grep -vx '\[Default\]' > "$rc.tmp"
    if [[ -s "$rc.tmp" ]]; then mv "$rc.tmp" "$rc"; else rm -f "$rc" "$rc.tmp"; fi
fi
