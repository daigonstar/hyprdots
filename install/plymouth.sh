#!/usr/bin/env bash
# Boot splash: installs the Cat theme and switches Plymouth on. Run as root (hyprinstall.sh does this with sudo).
# Safe to run again: every step checks first.
#
#   1. the theme, cloned once (a second clone into the same folder would fail)
#   2. the plymouth hook in /etc/mkinitcpio.conf, after udev or systemd
#   3. "quiet splash" on the kernel command line, wherever this machine keeps it:
#      /etc/kernel/cmdline (unified kernel images), systemd-boot entries, GRUB or Limine
#   4. the theme set as default, which also rebuilds the initramfs
#
#   --dry-run   say what would change, change nothing
set -euo pipefail

THEME=PlymouthTheme-Cat
THEME_URL=https://github.com/krishnan793/PlymouthTheme-Cat.git
THEMES=/usr/share/plymouth/themes
DRY_RUN=false
[[ "${1:-}" == "--dry-run" ]] && DRY_RUN=true

say() { printf '%s\n' "$*"; }
do_or_say() {  # runs the command, or in a dry run prints it
    if $DRY_RUN; then say "[DRY RUN] $*"; else "$@"; fi
}

if ! $DRY_RUN && [[ $EUID -ne 0 ]]; then
    say "Run this as root: sudo $0" >&2
    exit 1
fi
command -v plymouth-set-default-theme >/dev/null || { say "plymouth is not installed (pacman -S plymouth); skipping the boot splash."; exit 0; }

# 1. theme
if [[ -f "$THEMES/$THEME/$THEME.plymouth" ]]; then
    say "Boot splash theme already installed"
else
    do_or_say rm -rf "${THEMES:?}/$THEME"  # a half-finished earlier clone
    do_or_say git clone --depth 1 "$THEME_URL" "$THEMES/$THEME"
fi

# 2. initramfs hook
conf=/etc/mkinitcpio.conf
if grep -Eq '^HOOKS=.*\bplymouth\b' "$conf"; then
    say "plymouth hook already in $conf"
elif grep -Eq '^HOOKS=.*\b(udev|systemd)\b' "$conf"; then
    do_or_say sed -i -E '/^HOOKS=/ s/\b(udev|systemd)\b/& plymouth/' "$conf"
    say "Added the plymouth hook to $conf"
else
    say "WARNING: no udev or systemd hook in $conf; add 'plymouth' to HOOKS yourself."
fi

# 3. kernel command line
add_params() {  # file, sed address of the lines that hold the parameters
    local file="$1" where="$2" p
    for p in quiet splash; do
        if ! grep -E "$where" "$file" | grep -Eq "(^|[ \"'=])$p([ \"']|$)"; then
            do_or_say sed -i -E "/$where/ s/[[:space:]]*([\"']?)[[:space:]]*\$/ $p\\1/" "$file"
            say "Added '$p' to the kernel command line in $file"
        fi
    done
}
found=false
if [[ -f /etc/kernel/cmdline ]]; then
    add_params /etc/kernel/cmdline '.'
    found=true
fi
shopt -s nullglob
entries=(/boot/loader/entries/*.conf /efi/loader/entries/*.conf)
for entry in "${entries[@]}"; do
    add_params "$entry" '^options[[:space:]]'
    found=true
done
if [[ -f /etc/default/grub ]]; then
    add_params /etc/default/grub '^GRUB_CMDLINE_LINUX_DEFAULT='
    if ! $DRY_RUN && command -v grub-mkconfig >/dev/null; then
        grub-mkconfig -o /boot/grub/grub.cfg
    fi
    found=true
fi
for limine in /boot/limine.conf /boot/limine/limine.conf /efi/limine.conf; do
    [[ -f "$limine" ]] || continue
    add_params "$limine" '^[[:space:]]*(kernel_)?cmdline:'
    found=true
done
$found || say "WARNING: could not find the kernel command line (no /etc/kernel/cmdline, systemd-boot, GRUB or Limine); add 'quiet splash' to it yourself."

# 4. default theme, rebuilding the initramfs (and unified kernel images) with the hook
do_or_say plymouth-set-default-theme -R "$THEME"
say "Boot splash set up."
