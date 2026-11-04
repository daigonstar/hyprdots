#!/usr/bin/env bash
set -euo pipefail

# snapshots.sh
# Keeps a snapshot of the system from before and after every pacman or paru run, so a bad update can be undone with
# hypr/scripts/undo-update.sh. Only for a btrfs root; anything else exits without changing anything. Run as root.
# Safe to run again. Uses snapper and snap-pac, keeps the newest 10 pairs, and cleans up by itself.

if [[ $EUID -ne 0 ]]; then
  echo "Run this as root: sudo $0" >&2
  exit 1
fi
if [[ "$(findmnt -no FSTYPE /)" != btrfs ]]; then
  echo "The system is not on btrfs, so there are no snapshots to take."
  exit 0
fi

pacman -S --needed --noconfirm snapper
if ! snapper --no-dbus list-configs | grep -q '^root '; then
  if [[ -e /.snapshots ]]; then
    echo "/.snapshots already exists and is not from snapper, so this leaves it alone." >&2
    exit 1
  fi
  snapper --no-dbus -c root create-config /
fi
snapper --no-dbus -c root set-config NUMBER_LIMIT=10 NUMBER_LIMIT_IMPORTANT=5 TIMELINE_CREATE=no
# After the config exists: snap-pac's hook fails on a pacman run without one
pacman -S --needed --noconfirm snap-pac
systemctl enable --now snapper-cleanup.timer
echo "Snapshots are on: each pacman or paru run now keeps a before and after."
