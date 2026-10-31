#!/usr/bin/env bash
#
## Categorized Rofi App Launcher (entry point)
##
## Shows category tabs along the top (under the search bar) and a tiled
## app grid below, matching the visual style of the original drun launcher.
## The rofi fallback for the app launcher (~/.config/hypr/launcher).

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/applist.sh"

MODE_SCRIPT="$SCRIPT_DIR/category-mode.sh"
THEME="$SCRIPT_DIR/style.rasi"

# Build the -modi list, one entry per non-empty category, e.g.:
#   "All Apps:/path/category-mode.sh All Apps,Internet:/path/category-mode.sh Internet,..."
# "All Apps" is placed first so it's both the leftmost tab and the default
# view when the launcher opens.
mapfile -t buckets < <(print_nonempty_buckets)
ordered_buckets=()
for b in "${buckets[@]}"; do
    [[ "$b" == "All Apps" ]] && ordered_buckets=("All Apps" "${ordered_buckets[@]}") && continue
    ordered_buckets+=("$b")
done

modi_list=""
first_bucket=""
for bucket in "${ordered_buckets[@]}"; do
    [[ -z "$bucket" ]] && continue
    [[ -z "$first_bucket" ]] && first_bucket="$bucket"
    entry="${bucket}:${MODE_SCRIPT} \"${bucket}\""
    if [[ -z "$modi_list" ]]; then
        modi_list="$entry"
    else
        modi_list="${modi_list},${entry}"
    fi
done

if [[ -z "$modi_list" ]]; then
    notify-send "App Launcher" "No applications found." 2>/dev/null
    exit 1
fi

rofi -show "$first_bucket" -modes "$modi_list" -theme "$THEME"
