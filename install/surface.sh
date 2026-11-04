#!/usr/bin/env bash
# What a Microsoft Surface needs beyond the normal desktop. Does nothing on any other PC, and asks for no password when
# everything is already in place, so the installer and update.sh can both call it every time.
#   install/surface.sh [sys root]     the root is for the tests
set -uo pipefail

BASE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SYS="${1:-/sys}"
SLEEP_HOOK=/usr/lib/systemd/system-sleep/hyprdots-mwifiex

is_surface() {
    [[ "$(cat "$SYS/class/dmi/id/sys_vendor" 2>/dev/null)" == "Microsoft Corporation" ]] &&
        [[ "$(cat "$SYS/class/dmi/id/product_name" 2>/dev/null)" == Surface* ]]
}

# The Marvell 88W8897 Wi-Fi: see install/mwifiex-sleep
has_marvell_wifi() {
    local dev
    for dev in "$SYS"/bus/pci/devices/*; do
        [[ "$(cat "$dev/vendor" 2>/dev/null)" == 0x11ab && "$(cat "$dev/device" 2>/dev/null)" == 0x2b38 ]] && return 0
    done
    return 1
}

is_surface || exit 0

if command -v pacman >/dev/null 2>&1; then
    mapfile -t packages < <(sed -E 's/#.*//; s/[[:space:]]+//g; /^$/d' "$BASE_DIR/surface.txt")
    # pacman -T prints the packages that are not installed (and exits non-zero if there are any)
    mapfile -t missing < <(pacman -T "${packages[@]}" || true)
    if [[ ${#missing[@]} -gt 0 ]]; then
        echo "Installing for this Surface: ${missing[*]}"
        sudo pacman -S --needed --noconfirm "${missing[@]}" || echo "Warning: could not install ${missing[*]}." >&2
    fi
fi

# The lock screen's on-screen keyboard: see install/gtklock-keyboard.c. Built for the gtklock that is installed, and again
# when that changes. Needs no root: gtklock runs as you.
keyboard_module="$HOME/.local/lib/hyprdots/gtklock-keyboard.so"
if command -v gtklock >/dev/null 2>&1 && { [[ ! -f $keyboard_module ]] ||
    [[ $BASE_DIR/gtklock-keyboard.c -nt $keyboard_module || /usr/bin/gtklock -nt $keyboard_module ]]; }; then
    version="$(gtklock --version | grep -oE '[0-9]+\.[0-9]+' | head -n1)"
    mkdir -p "$(dirname "$keyboard_module")"
    # shellcheck disable=SC2046
    gcc -shared -fPIC -O2 -Wall -Wextra -DMAJOR_VERSION="${version%.*}" -DMINOR_VERSION="${version#*.}" "$BASE_DIR/gtklock-keyboard.c" \
        -o "$keyboard_module" $(pkg-config --cflags --libs gtk+-3.0 gmodule-2.0) ||
        echo "Warning: could not build the lock screen's keyboard." >&2
fi

# Touch gestures: your session may read the touchscreen, and only that. See the rules file.
TOUCH_RULES=/etc/udev/rules.d/70-hyprdots-touchscreen.rules
if ! cmp -s "$BASE_DIR/70-hyprdots-touchscreen.rules" "$TOUCH_RULES"; then
    echo "Letting your session read the touchscreen, for gestures"
    sudo install -Dm644 "$BASE_DIR/70-hyprdots-touchscreen.rules" "$TOUCH_RULES" && sudo udevadm control --reload &&
        sudo udevadm trigger --subsystem-match=input --action=change || echo "Warning: could not install $TOUCH_RULES." >&2
fi

# The login screen's on-screen keyboard, in the theme itself: see SDDM/sugar-dark/Components/TouchKeys.qml
THEME=/usr/share/sddm/themes/sugar-dark
if [[ -d $THEME ]] && { ! diff -rq --exclude=theme.conf.user "$BASE_DIR/../SDDM/sugar-dark" "$THEME" >/dev/null 2>&1 ||
    ! grep -qs 'TouchKeyboard=true' "$THEME/theme.conf.user"; }; then
    echo "Adding the on-screen keyboard to the login screen"
    sudo cp -rT "$BASE_DIR/../SDDM/sugar-dark" "$THEME" && echo 'TouchKeyboard=true' | sudo tee "$THEME/theme.conf.user" >/dev/null ||
        echo "Warning: could not update the login screen." >&2
fi

# The on-screen keyboard's layouts, with Super and Ctrl for desktop shortcuts
mkdir -p "$HOME/.local/share/squeekboard/keyboards"
cp "$BASE_DIR"/squeekboard/*.yaml "$HOME/.local/share/squeekboard/keyboards/"

# The power button sleeps rather than shuts down
LOGIND_CONF=/etc/systemd/logind.conf.d/hyprdots-surface.conf
if ! cmp -s "$BASE_DIR/logind-surface.conf" "$LOGIND_CONF"; then
    echo "Making the power button sleep"
    sudo install -Dm644 "$BASE_DIR/logind-surface.conf" "$LOGIND_CONF" && sudo systemctl kill -s HUP systemd-logind ||
        echo "Warning: could not install $LOGIND_CONF." >&2
fi

if has_marvell_wifi && ! cmp -s "$BASE_DIR/mwifiex-sleep" "$SLEEP_HOOK"; then
    echo "Keeping the Wi-Fi working after sleep (Marvell driver reload)"
    sudo install -Dm755 "$BASE_DIR/mwifiex-sleep" "$SLEEP_HOOK" || echo "Warning: could not install $SLEEP_HOOK." >&2
fi
exit 0
