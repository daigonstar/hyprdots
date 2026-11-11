#!/bin/bash
# /* ---- 💫 https://github.com/JaKooLit 💫 ---- */
# Optimized for Multi-Monitor Sync and Wallust 3.0

# WALLPAPERS PATH
wallDIR="$HOME/Pictures/wallpapers"
SCRIPTSDIR="$HOME/.config/hypr/scripts"

# awww transition config
FPS=60
TYPE="any"
DURATION=2
BEZIER=".43,1.19,1,.4"
AWWW_PARAMS="--transition-fps $FPS --transition-type $TYPE --transition-duration $DURATION --transition-bezier $BEZIER"

# Variables
rofi_theme="$HOME/.config/rofi/wallpaper/wallpaper.rasi"
thumbDIR="${XDG_CACHE_HOME:-$HOME/.cache}/wallpaper-thumbs-fit"
mkdir -p "$thumbDIR"

# Kill existing wallpaper daemons (a picture stops a playing video; wallust.sh's sync would too)
kill_wallpaper_for_image() {
  pkill mpvpaper 2>/dev/null
  pkill swaybg 2>/dev/null
  pkill hyprpaper 2>/dev/null
}

# Retrieve wallpapers (sorted, so the menu index maps straight back to a file)
mapfile -d '' -t PICS < <(find -L "${wallDIR}" -type f \( \
  -iname "*.jpg" -o -iname "*.jpeg" -o -iname "*.png" -o -iname "*.gif" -o \
  -iname "*.bmp" -o -iname "*.tiff" -o -iname "*.webp" -o \
  -iname "*.mp4" -o -iname "*.mkv" -o -iname "*.mov" -o -iname "*.webm" \) -print0 | sort -z)

if [[ ${#PICS[@]} -eq 0 ]]; then
  notify-send "No wallpapers" "Add images or videos to $wallDIR"
  exit 1
fi

# Thumbnails keep each picture's shape (fitted inside a transparent 480px square), cached by path + modification time, so the picker opens instantly
thumb_for() {
  local f="$1" key
  key=$(printf '%s%s' "$f" "$(stat -c %Y "$f")" | cksum | cut -d' ' -f1)
  echo "$thumbDIR/$key.png"
}

make_thumb() {
  local f="$1" out="$2"
  [[ -s "$out" ]] && return
  if [[ "$f" =~ \.(mp4|mkv|mov|webm|MP4|MKV|MOV|WEBM)$ ]]; then
    ffmpeg -loglevel quiet -y -ss 1 -i "$f" -frames:v 1 \
      -vf "scale=480:480:force_original_aspect_ratio=decrease,pad=480:480:-1:-1:color=black@0,format=rgba" "$out" 2>/dev/null
  else
    magick "${f}[0]" -thumbnail 480x480 -background none -gravity center -extent 480x480 "$out" 2>/dev/null
  fi
}
export -f make_thumb
export thumbDIR

build_thumbs() {
  local f
  for f in "${PICS[@]}"; do
    printf '%s\0%s\0' "$f" "$(thumb_for "$f")"
  done | xargs -0 -n 2 -P 4 bash -c 'make_thumb "$0" "$1"'
}

# Rofi command (-format i prints the row number, so names never need to be matched back to files)
rofi_command="rofi -i -dmenu -format i -config $rofi_theme"

# Thumbnail size that fits a 5 x 3 grid on the focused screen (the theme is full screen)
screen_icon_size() {
  hyprctl monitors -j | jq -r '(map(select(.focused))[0] // .[0]) | "\(.width) \(.height) \(.scale)"' |
    awk '{ w = $1 / $3; h = $2 / $3
           row = (h - 160 - 60 - 64) / 3 - 80; col = (w - 300) / 5 - 40
           s = (row < col ? row : col); if (s < 120) s = 120; if (s > 480) s = 480; printf "%d", s }'
}

# Row 0 is a random pick, then every wallpaper with its thumbnail
menu() {
  printf "Random\x00icon\x1f%s\n" "$(thumb_for "${PICS[$((RANDOM % ${#PICS[@]}))]}")"
  local f name
  for f in "${PICS[@]}"; do
    name=$(basename "$f"); name="${name%.*}"
    printf "%s\x00icon\x1f%s\n" "$name" "$(thumb_for "$f")"
  done
}

# Start on the wallpaper that is showing now
current_row() {
  local cur i
  cur=$(awww query 2>/dev/null | grep -o 'image: .*' | head -n1 | sed 's/^image: //')
  # a video shows as its still: start on the video itself
  if pgrep -x mpvpaper >/dev/null && [[ -e "$HOME/.config/rofi/.current_video" ]]; then
    cur=$(readlink -f "$HOME/.config/rofi/.current_video")
  fi
  for i in "${!PICS[@]}"; do
    [[ "${PICS[$i]}" == "$cur" ]] && { echo $((i + 1)); return; }
  done
  echo 0
}

# Apply Image Wallpaper (Syncs All Monitors)
apply_image_wallpaper() {
  local image_path="$1"
  kill_wallpaper_for_image

  if ! pgrep -x "awww-daemon" >/dev/null; then
    awww-daemon --format xrgb &
    sleep 0.5
  fi

  awww img "$image_path" $AWWW_PARAMS

  # Run wallust and pass the path directly
  if [ -f "$SCRIPTSDIR/wallust.sh" ]; then
    bash "$SCRIPTSDIR/wallust.sh" "$image_path"
  fi

  # Refresh other components (Waybar/SwayNC)
  if [ -f "$SCRIPTSDIR/refresh.sh" ]; then
    bash "$SCRIPTSDIR/refresh.sh"
  fi
}

# A video: video-wallpaper.sh shows a still frame of it (colours, lock screen and login go by that), then plays it over
apply_video_wallpaper() {
  local video_path="$1"
  if ! command -v mpvpaper &>/dev/null; then
    notify-send "Video wallpaper" "mpvpaper is not installed: paru -S mpvpaper"
    return 1
  fi
  pkill swaybg 2>/dev/null
  pkill hyprpaper 2>/dev/null
  bash "$SCRIPTSDIR/video-wallpaper.sh" start "$video_path"
}

# Main function
main() {
  build_thumbs
  choice=$(menu | $rofi_command -theme-str "element-icon { size: $(screen_icon_size)px; }" -selected-row "$(current_row)")
  [[ -z "$choice" ]] && exit 0

  if [[ "$choice" == 0 ]]; then
    selected_file="${PICS[$((RANDOM % ${#PICS[@]}))]}"
  else
    selected_file="${PICS[$((choice - 1))]}"
  fi

  if [[ "$selected_file" =~ \.(mp4|mkv|mov|webm|MP4|MKV|MOV|WEBM)$ ]]; then
    apply_video_wallpaper "$selected_file"
  else
    apply_image_wallpaper "$selected_file"
  fi
}

# --apply FILE: set it, as a pick from the menu would (the GTK picker, hypr/launcher/wallpicker.py, uses this)
if [[ "${1:-}" == "--apply" ]]; then
  [[ -f "${2:-}" ]] || { echo "No such wallpaper: ${2:-}" >&2; exit 1; }
  if [[ "$2" =~ \.(mp4|mkv|mov|webm|MP4|MKV|MOV|WEBM)$ ]]; then
    apply_video_wallpaper "$2"
  else
    apply_image_wallpaper "$2"
  fi
  exit
fi

# The picker is hyprdots' own GTK window (categories, previews, a monitor round the one you are on). This rofi menu
# stays as the fallback, and for --rofi.
picker="$HOME/.config/hypr/launcher/wallpicker.sh"
if [[ "${1:-}" != "--rofi" && -x "$picker" && -e /usr/lib/libgtk4-layer-shell.so ]] &&
   python3 -c "import gi; gi.require_version('Gtk4LayerShell', '1.0')" 2>/dev/null; then
  exec "$picker"
fi

if pidof rofi >/dev/null; then
  pkill rofi
fi

main
