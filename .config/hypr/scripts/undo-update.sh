#!/usr/bin/env bash
# Puts the system back as it was before the last pacman or paru run, from the snapshots install/snapshots.sh turns on.
# Only system files: your home folder is not touched. A run that changed the kernel cannot be undone from here.
set -uo pipefail

if ! command -v snapper >/dev/null; then
    echo "Snapshots are not turned on. They need a btrfs system: sudo ~/hyprdots/install/snapshots.sh" >&2
    exit 1
fi
# The package list has to go back with the files, or pacman would no longer know what is installed
if [[ "$(stat -c %d /)" != "$(stat -c %d /var/lib/pacman)" ]]; then
    echo "pacman's records are on their own btrfs subvolume, so undoing from here would leave them wrong." >&2
    exit 1
fi

sudo -v || exit 1
# number|type|pre-number|description: the newest "post" belongs to the last run
last="$(sudo snapper -c root --csvout --no-headers --separator '|' list --columns number,type,pre-number,description | awk -F'|' '$2 == "post"' | tail -n1)"
if [[ -z "$last" ]]; then
    echo "There are no snapshots of an update yet."
    exit 1
fi
IFS='|' read -r post _type pre description <<<"$last"

changes="$(sudo snapper -c root status "$pre..$post")"
# /boot is not in the snapshot, so the kernel there would stay new with its modules gone: the PC would not start properly
if grep -q ' /usr/lib/modules/' <<<"$changes"; then
    echo "That update changed the kernel, which cannot be undone from here. Install the older one from pacman's cache." >&2
    exit 1
fi

echo "Last run: $description"
echo "Undoing it changes $(wc -l <<<"$changes") files back to how they were."
read -rp "Undo it? [y/N] " answer || answer=""
[[ "$answer" == [yY] ]] || { echo "Nothing was changed."; exit 0; }
sudo snapper -c root undochange "$pre..$post" || exit 1
echo "Done. Restart the PC to be sure everything is using the old files."
