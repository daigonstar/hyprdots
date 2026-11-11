#!/usr/bin/env bash
# Video wallpapers. A video gets a still frame of itself, which becomes your wallpaper as far as the rest of the desktop
# knows: awww shows it, wallust takes the colours from it, the lock screen and theme overrides use it, and a login
# brings it back. mpvpaper plays the video over it, but only while that still is the current wallpaper.
#
#   video-wallpaper.sh start VIDEO   make (or reuse) the still, show it, take its colours, then play the video
#   video-wallpaper.sh sync          play or stop the video to match the current wallpaper (wallust.sh runs this
#                                    after every wallpaper change; login, game mode and theme overrides go through it)
#   video-wallpaper.sh stop          stop playing (game mode); sync starts it again
#   video-wallpaper.sh still VIDEO   print the still's path, making it if needed
set -u

STILLS="${XDG_CACHE_HOME:-$HOME/.cache}/hyprdots/video-wallpapers"
CURRENT="$HOME/.config/rofi/.current_wallpaper"  # the still while a video is on
VIDEO_LINK="$HOME/.config/rofi/.current_video"   # the video that still belongs to
SCRIPTS="$HOME/.config/hypr/scripts"
# no sound, loop forever, hardware decoding where the card has it; -p pauses while windows cover every screen
MPV_OPTS="no-audio loop hwdec=auto load-scripts=no"
PLAYER="${VIDEO_PLAYER:-mpvpaper}"  # the tests use a stand-in, so they never stop your real one

still_for() {
    local video="$1" key
    key=$(printf '%s%s' "$video" "$(stat -c %Y "$video" 2>/dev/null)" | cksum | cut -d' ' -f1)
    echo "$STILLS/$(basename "${video%.*}")-$key.png"
}

make_still() {
    local video="$1" out
    out=$(still_for "$video")
    if [[ ! -s "$out" ]]; then
        mkdir -p "$STILLS"
        # a frame a second in (the very first is often black), at the video's own size
        ffmpeg -loglevel error -y -ss 1 -i "$video" -frames:v 1 "$out" 2>/dev/null ||
            ffmpeg -loglevel error -y -i "$video" -frames:v 1 "$out" 2>/dev/null
    fi
    [[ -s "$out" ]] && echo "$out"
}

playing() {  # the video mpvpaper is playing now, if any (its last argument; read whole, so spaces in names are fine)
    local pid
    pid=$(pgrep -x "$PLAYER" | head -n1) || return 0
    tr '\0' '\n' < "/proc/$pid/cmdline" 2>/dev/null | grep -v '^$' | tail -n1
}

stop_video() {
    pkill -x "$PLAYER" 2>/dev/null
    return 0
}

play() {
    local video="$1"
    [[ "$(playing)" == "$video" ]] && return 0
    stop_video
    command -v "$PLAYER" >/dev/null || { notify-send "Video wallpaper" "mpvpaper is not installed: paru -S mpvpaper"; return 1; }
    local run=("$PLAYER" -p -o "$MPV_OPTS" '*' "$video")
    # its own scope: not part of whatever changed the wallpaper (the bar, the settings window)
    command -v systemd-run >/dev/null && run=(systemd-run --user --scope --collect --quiet -- "${run[@]}")
    setsid "${run[@]}" >/dev/null 2>&1 </dev/null &
}

# The video to play now: only while the current wallpaper is that video's still
wanted() {
    local now video
    now=$(readlink -f "$CURRENT" 2>/dev/null) || return 1
    [[ "$now" == "$STILLS"/* ]] || return 1
    video=$(readlink -f "$VIDEO_LINK" 2>/dev/null) || return 1
    [[ -f "$video" && "$(still_for "$video")" == "$now" ]] || return 1
    echo "$video"
}

case "${1:-}" in
    start)
        video=$(readlink -f "${2:-}")
        [[ -f "$video" ]] || { echo "No such video: ${2:-}" >&2; exit 1; }
        still=$(make_still "$video") || { notify-send "Video wallpaper" "Could not read a frame from $(basename "$video")"; exit 1; }
        ln -sfn "$video" "$VIDEO_LINK"
        pgrep -x awww-daemon >/dev/null || { (setsid awww-daemon --format xrgb >/dev/null 2>&1 &); sleep 0.5; }
        awww img "$still" --transition-type grow --transition-duration 1
        exec bash "$SCRIPTS/wallust.sh" "$still"  # colours from the still; it ends with sync, which starts the video
        ;;
    sync)
        if video=$(wanted); then play "$video"; else stop_video; fi
        ;;
    stop)
        stop_video
        ;;
    still)
        make_still "$(readlink -f "${2:-}")"
        ;;
    *)
        echo "usage: $0 start VIDEO | sync | stop | still VIDEO" >&2
        exit 2
        ;;
esac
