#!/usr/bin/env bash
# Graphics cards in this PC whose drivers are not installed, using the same matching and lists as the installer.
# Prints one vendor per line. --notify tells you on the desktop instead, unless you said not to remind you.
lists="$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")/../../../install"
off="${XDG_STATE_HOME:-$HOME/.local/state}/hyprdots/gpu-check-off"

cards="$(lspci -nn 2>/dev/null | grep -Ei 'vga|3d controller|display controller')"
missing=()
# One package each driver always has, so another driver from the same vendor (nvidia-dkms, say) does not count as missing
check() {  # vendor pattern package
    grep -qiE "$2" <<<"$cards" && ! pacman -T "$3" >/dev/null && [[ -f "$lists/gpu-$1.txt" ]] && missing+=("$1")
}
check nvidia '\[10de:|\bnvidia\b' nvidia-utils
check amd '\[1002:|\b(amd|ati)\b|advanced micro' vulkan-radeon
check intel '\[8086:|\bintel\b' vulkan-intel

if [[ "${1:-}" != "--notify" ]]; then
    printf '%s\n' "${missing[@]}" | grep .
    exit 0
fi
[[ ${#missing[@]} -gt 0 && ! -e "$off" ]] || exit 0
answer="$(notify-send -u critical --action=off="Don't remind me" "Graphics drivers are missing" \
    "This PC has ${missing[*]} graphics without its drivers. Run hyprupdate in a terminal to install them.")"
[[ "$answer" != off ]] || { mkdir -p "$(dirname "$off")" && touch "$off"; }
