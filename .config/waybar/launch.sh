#!/usr/bin/env bash
# Starts the bar.
# - style.css imports theme.css (your colours and font from the settings Theme page, git-ignored); GTK refuses the
#   whole style sheet when an import is missing, so put the default look in place first if there is none.
# - Run config.generated.json: the tracked config with your arrangement from the settings Bar layout page (layout.json)
#   and a theme override's own bar while one is on. If that cannot be built, run the tracked config.
dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
[[ -f "$dir/theme.css" ]] || cp "$dir/theme.default.css" "$dir/theme.css"
touch "$dir/tablet.css" "$dir/../rofi/touch.rasi"
"$HOME/.config/hypr/scripts/first-colours.sh" >/dev/null 2>&1  # the wallust colours it imports, likewise
if [[ -e "${XDG_STATE_HOME:-$HOME/.local/state}/hyprdots/touch-mode" ]]; then
    exec waybar -c "$dir/config-touch" "$@"  # no keyboard attached: hypr/tray/touch_mode.py
fi
if PYTHONPATH="$HOME/.config/hypr/settings" python3 -m hyprsettings.barlayout generate >/dev/null; then  # errors go to the journal
    # a theme override's dock (Mac style) runs beside the bar, so it can hide by itself (scripts/dock.py). The bar's
    # service only stops waybar on a restart (so apps opened from the bar live on), so an old dock is stopped here.
    pkill -f '[w]aybar/scripts/dock.py' 2>/dev/null
    [[ -f "$dir/config.dock.json" ]] && "$dir/scripts/dock.sh" &
    exec waybar -c "$dir/config.generated.json" "$@"
fi
exec waybar "$@"
