#!/usr/bin/env bash
# Starts the notification centre. style.css imports theme.css (colours and font from the settings Theme page,
# git-ignored); a missing import would drop the whole style sheet, so put the default in place first if there is none.
dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
[[ -f "$dir/theme.css" ]] || cp "$dir/theme.default.css" "$dir/theme.css"
"$HOME/.config/hypr/scripts/first-colours.sh" >/dev/null 2>&1  # the wallust colours it imports, likewise
exec swaync "$@"
