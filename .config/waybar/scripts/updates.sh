#!/usr/bin/env bash
# Waybar update indicator: pending official (checkupdates), AUR (paru) and Flatpak updates.
# Prints JSON for waybar; always shows the icon. Class: "updated" (0), "pending" (1-49, orange), "critical" (50+, red).
#
# Waybar runs this once per bar, so with two monitors two copies start at the same moment.
# checkupdates uses one shared database, so a second simultaneous run came back empty and the
# bars showed different numbers. Now only one check runs at a time and every bar reads the same
# result for a few seconds. If a source fails, the last good number for it is kept.

TTL=20   # seconds a result is shared between bars; a refresh after an update is always newer than this
dir="${XDG_RUNTIME_DIR:-/tmp}/waybar-updates-$UID"
mkdir -p -m 700 "$dir"
state="$dir/state"                  # "epoch official aur flatpak"; a ? means that source has never been read
exec 9>"$dir/lock"
flock 9                             # the second bar waits here, then reuses the first bar's result

stamp=0 official="?" aur="?" flat="?"
[[ -r "$state" ]] && read -r stamp official aur flat < "$state"
now=$(date +%s)

if (( now - ${stamp:-0} >= TTL )); then
    out=$(checkupdates 2>/dev/null); rc=$?
    case $rc in                     # 0 = updates found, 2 = none, anything else = the check itself failed
        0) official=$(grep -c . <<<"$out") ;;
        2) official=0 ;;
    esac
    out=$(paru -Qua 2>/dev/null); rc=$?
    case $rc in 0) aur=$(grep -c . <<<"$out") ;; 1) aur=0 ;; esac   # paru -Qua exits 1 when nothing is pending
    out=$(flatpak remote-ls --updates 2>/dev/null); rc=$?
    (( rc == 0 )) && flat=$(grep -c . <<<"$out")
    printf '%s %s %s %s\n' "$now" "$official" "$aur" "$flat" > "$state.tmp" && mv "$state.tmp" "$state"
fi

total=0 unknown=""
for n in "$official" "$aur" "$flat"; do
    if [[ "$n" =~ ^[0-9]+$ ]]; then total=$((total + n)); else unknown=" ?"; fi
done

if [[ "$total" -eq 0 && -z "$unknown" ]]; then
    printf '{"text": "󰏔", "class": "updated", "tooltip": "System is up to date"}\n'
else
    class="pending"
    [[ "$total" -ge 50 ]] && class="critical"
    printf '{"text": "󰏔 %s%s", "class": "%s", "tooltip": "Official: %s\\nAUR: %s\\nFlatpak: %s\\n\\nClick to update"}\n' \
        "$total" "$unknown" "$class" "$official" "$aur" "$flat"
fi
