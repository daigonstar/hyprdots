#!/usr/bin/env bash
# Opens the Sound app (outputs, inputs, apps, sound cards, the equaliser and a headset), or brings it forward.
#   audio.sh [--page output|input|apps|devices|headset]
dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
setsid python3 "$dir/app.py" "$@" >/dev/null 2>&1 </dev/null &
