#!/usr/bin/env bash
# Screen recording. record.sh [screen|region] starts one (on the screen you are on, or an area you draw), and the same
# again stops it, as does record.sh stop or clicking the red dot on the bar. Records system sound and not your microphone.
run="${XDG_RUNTIME_DIR:-/tmp}"
pidfile="$run/recording.pid"
dir="$HOME/Videos/recordings"

recording() { [[ -f "$pidfile" ]] && kill -0 "$(cat "$pidfile")" 2>/dev/null; }
bar() { pkill -RTMIN+11 -x waybar; }  # custom/recording in the bar's config

case "${1:-screen}" in
    status)
        recording && printf '{"text": "\xf3\xb0\x91\x8a REC", "class": "recording", "tooltip": "Recording. Click to stop"}\n'
        exit 0 ;;
    stop)
        recording && kill -INT "$(cat "$pidfile")"
        exit 0 ;;
esac
if recording; then
    kill -INT "$(cat "$pidfile")"
    exit 0
fi
if ! command -v gpu-screen-recorder >/dev/null; then
    notify-send "Screen recording" "Needs gpu-screen-recorder (sudo pacman -S gpu-screen-recorder)"
    exit 1
fi

if [[ "$1" == "region" ]]; then
    area="$(slurp -f '%wx%h+%x+%y')" || exit 0  # you pressed Escape
    source=(-w region -region "$area")
else
    source=(-w "$(hyprctl monitors -j | jq -r '.[] | select(.focused) | .name')")
fi
mkdir -p "$dir"
file="$dir/$(date +'%Y-%m-%d-%H%M%S').mp4"
log="$run/recording.log"

gpu-screen-recorder "${source[@]}" -f 60 -a default_output -o "$file" >"$log" 2>&1 &
echo $! >"$pidfile"
bar
wait "$!"
rm -f "$pidfile"
bar

if [[ ! -s "$file" ]]; then
    notify-send -u critical -a "Screen recording" "Recording failed" "$(tail -n 2 "$log")"
    exit 1
fi
choice="$(timeout 60 notify-send -a "Screen recording" -i video-x-generic -A open=Open -A folder="Show in folder" --wait \
    "Recording saved" "$(basename "$file")")"
case "$choice" in
    open) exec xdg-open "$file" ;;
    folder) exec xdg-open "$dir" ;;
esac
