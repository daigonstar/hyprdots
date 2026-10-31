#!/usr/bin/env bash
# The lock screen itself: hypridle's lock_cmd (written by hypr-settings, Power & lock page) and lock.sh run this.
#   lock-screen.sh [KEEP]       lock; with KEEP, the other screens are switched off until you unlock
#   lock-screen.sh wake [KEEP]  switch the screens back on after idle (while locked, only KEEP)
# KEEP is "all" (every screen stays on), "focused" (the screen you were using) or a screen name such as DP-1.

screens_except() {  # names of the screens that are not the one to keep
    hyprctl monitors -j | python3 -c '
import json, sys
keep = sys.argv[1]
mons = json.load(sys.stdin)
if keep == "focused":
    keep = next((m["name"] for m in mons if m["focused"]), "")
if keep and keep != "all" and any(m["name"] == keep for m in mons):
    print("\n".join(m["name"] for m in mons if m["name"] != keep))
' "$1"
}

dpms() {  # dpms on|off [screen]
    if [[ -n ${2:-} ]]; then
        hyprctl dispatch "hl.dsp.dpms({ action = \"$1\", monitor = \"$2\" })" >/dev/null
    else
        hyprctl dispatch "hl.dsp.dpms({ action = \"$1\" })" >/dev/null
    fi
}

if [[ ${1:-} == wake ]]; then
    keep=${2:-all}
    if pidof hyprlock >/dev/null && [[ $keep != all ]]; then
        # still locked: wake only the screen that shows the lock screen
        mapfile -t others < <(screens_except "$keep")
        dpms on
        for m in "${others[@]}"; do dpms off "$m"; done
    else
        dpms on
    fi
    exit 0
fi

pidof hyprlock >/dev/null && exit 0   # already locked
keep=${1:-all}

# Your look from the Power & lock page when you have saved one; the shipped hyprlock.conf otherwise
args=()
conf="$HOME/.config/hypr/hyprlock.local.conf"
if [[ -f $conf ]]; then
    args=(-c "$conf")
    grace=$(sed -n 's/^# grace=\([0-9]\+\)$/\1/p' "$conf" | head -n1)
    [[ ${grace:-0} -gt 0 ]] && args+=(--grace "$grace")
fi

mapfile -t others < <(screens_except "$keep")
for m in "${others[@]}"; do dpms off "$m"; done
hyprlock "${args[@]}"
for m in "${others[@]}"; do dpms on "$m"; done
