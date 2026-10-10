#!/usr/bin/env bash
#
# remove-steam-shortcuts.sh
# Removes .desktop launcher entries that Steam auto-generates for installed
# games (identified by Exec=steam steam://rungameid/... or Icon=steam_icon_*).
#
# Run manually or via a systemd user timer (see remove-steam-shortcuts.timer).

set -euo pipefail

APP_DIRS=(
    "$HOME/.local/share/applications"
    "$HOME/.var/app/com.valvesoftware.Steam/data/applications"
)

LOG_TAG="remove-steam-shortcuts"
removed=0

for dir in "${APP_DIRS[@]}"; do
    [[ -d "$dir" ]] || continue

    while IFS= read -r -d '' file; do
        if grep -q 'Exec=steam steam://rungameid/\|Icon=steam_icon_' "$file" 2>/dev/null; then
            rm -f -- "$file"
            removed=$((removed + 1))
            logger -t "$LOG_TAG" "removed $file" 2>/dev/null || true
            echo "Removed: $file"
        fi
    done < <(find "$dir" -maxdepth 1 -iname "*.desktop" -print0)
done

# Refresh the desktop database if available so launchers pick up the change
if command -v update-desktop-database >/dev/null 2>&1; then
    update-desktop-database "$HOME/.local/share/applications" 2>/dev/null || true
fi

echo "Done. Removed $removed Steam shortcut(s)."
