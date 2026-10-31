#!/usr/bin/env bash
# Starts the bar.
# - style.css imports theme.css (your colours and font from the settings Theme page, git-ignored); GTK refuses the
#   whole style sheet when an import is missing, so put the default look in place first if there is none.
# - With a layout.json (the settings Bar layout page), run config.generated.json: the tracked config with your
#   arrangement. If that cannot be built, run the tracked config.
dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
[[ -f "$dir/theme.css" ]] || cp "$dir/theme.default.css" "$dir/theme.css"
"$HOME/.config/hypr/scripts/first-colours.sh" >/dev/null 2>&1  # the wallust colours it imports, likewise
if [[ -f "$dir/layout.json" ]] && PYTHONPATH="$HOME/.config/hypr/settings" python3 -m hyprsettings.barlayout generate >/dev/null 2>&1; then
    exec waybar -c "$dir/config.generated.json" "$@"
fi
exec waybar "$@"
