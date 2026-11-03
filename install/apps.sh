#!/usr/bin/env bash
# The optional apps: install/apps/*.txt, one group per file, plus a choice of web browser. Everything the desktop
# itself needs is in required.txt. Run it any time to add more; switching a group off does not uninstall anything.
#
#   apps.sh                               ask, then install what you picked
#   apps.sh --print [--dry-run]           ask, then print the picks for hyprinstall.sh to install ("pacman X", "flatpak X",
#                                         "group X", "browser COMMAND DESKTOPFILE"); the questions go to stderr
#   apps.sh --set-browser COMMAND DESKTOPFILE   make it the browser Super+B opens, and the system default
#   apps.sh --set-keyboard LAYOUT         the keyboard layout on the desktop
#   apps.sh --list                        the choices, for install/tui.py ("browser|id|name", "group|id|yes/no|title|about")
#
# Unattended: HYPR_APPS="gaming chat" (or all, or none) and HYPR_BROWSER=firefox|zen|chromium|brave|none. With no terminal
# to ask in, and neither set, you get the groups marked "default: yes" and Firefox.
set -uo pipefail
dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
state="${XDG_STATE_HOME:-$HOME/.local/state}/hyprdots/apps"

# id, name, package, command, desktop file
BROWSERS=(
  "firefox|Firefox|firefox|firefox|firefox.desktop"
  "zen|Zen|zen-browser-bin|zen-browser|zen.desktop"
  "chromium|Chromium|chromium|chromium|chromium.desktop"
  "brave|Brave|brave-bin|brave|brave-browser.desktop"
  "none|None, I will sort out my own|||"
)

set_setting() {
  PYTHONPATH="$dir/../.config/hypr/settings" python3 - "$1" "$2" "$3" <<'PY' || echo "Could not save $2; you can pick it in Settings." >&2
import sys
from hyprsettings import tomledit
from hyprsettings.store import Store

store = Store()
tomledit.set_value(store.local_path, sys.argv[1], sys.argv[2], sys.argv[3])
Store().write_overrides()
PY
}

set_browser() {
  set_setting hyprdots browser "$1"
  command -v xdg-settings >/dev/null 2>&1 && xdg-settings set default-web-browser "$2" 2>/dev/null
  return 0
}
if [[ "${1:-}" == "--set-browser" ]]; then
  set_browser "$2" "$3"
  exit 0
fi
if [[ "${1:-}" == "--set-keyboard" ]]; then
  set_setting hyprland kb_layout "$2"
  exit 0
fi

print=false dry=false list=false
for arg in "$@"; do
  case "$arg" in
    --print) print=true ;;
    --list) list=true ;;
    --dry-run) dry=true ;;
    *) echo "Unknown option: $arg" >&2; exit 2 ;;
  esac
done

field() { sed -n "s/^# $1: //p" "$2" | head -n1; }

ids=() titles=() abouts=() picked=()
for file in "$dir"/apps/*.txt; do
  id="$(basename "$file" .txt)"
  ids+=("$id")
  titles+=("$(field title "$file")")
  abouts+=("$(field about "$file")")
  if [[ -f "$state" ]]; then
    grep -qxF "group=$id" "$state" && picked+=(yes) || picked+=(no)
  else
    [[ "$(field default "$file")" == "yes" ]] && picked+=(yes) || picked+=(no)
  fi
done

if [[ "$list" == true ]]; then
  for entry in "${BROWSERS[@]}"; do
    IFS='|' read -r id name _ <<<"$entry"
    printf 'browser|%s|%s\n' "$id" "$name"
  done
  for i in "${!ids[@]}"; do
    printf 'group|%s|%s|%s|%s\n' "${ids[i]}" "${picked[i]}" "${titles[i]}" "${abouts[i]}"
  done
  exit 0
fi

# A menu only with someone to answer it. HYPR_APPS_MENU=1 lets the tests answer through a pipe.
ask=false
if [[ -z "${HYPR_APPS:-}" && "$dry" == false ]] && { [[ -t 0 ]] || [[ "${HYPR_APPS_MENU:-}" == "1" ]]; }; then
  ask=true
fi

browser="${HYPR_BROWSER:-firefox}"
if [[ "$ask" == true ]]; then
  {
    echo
    echo "Which web browser would you like?"
    i=1
    for entry in "${BROWSERS[@]}"; do
      IFS='|' read -r _ name _ <<<"$entry"
      echo "  $i) $name"
      i=$((i + 1))
    done
  } >&2
  read -rp "Number (Enter for 1): " answer
  if [[ "$answer" =~ ^[0-9]+$ ]] && (( answer >= 1 && answer <= ${#BROWSERS[@]} )); then
    IFS='|' read -r browser _ <<<"${BROWSERS[answer - 1]}"
  fi

  while true; do
    {
      echo
      echo "Which extra apps would you like? The desktop works without any of them."
      for i in "${!ids[@]}"; do
        mark=" "
        [[ "${picked[i]}" == yes ]] && mark="x"
        printf '  %2d) [%s] %s\n         %s\n' "$((i + 1))" "$mark" "${titles[i]}" "${abouts[i]}"
      done
      echo "Type numbers to switch them on or off (like: 1 3), a for all, n for none, or press Enter when done."
    } >&2
    read -rp "> " answer || break
    [[ -z "$answer" ]] && break
    for word in $answer; do
      case "$word" in
        a) for i in "${!ids[@]}"; do picked[i]=yes; done ;;
        n) for i in "${!ids[@]}"; do picked[i]=no; done ;;
        *)
          if [[ "$word" =~ ^[0-9]+$ ]] && (( word >= 1 && word <= ${#ids[@]} )); then
            [[ "${picked[word - 1]}" == yes ]] && picked[word - 1]=no || picked[word - 1]=yes
          else
            echo "Skipping $word: not one of the choices." >&2
          fi ;;
      esac
    done
  done
elif [[ -n "${HYPR_APPS:-}" ]]; then
  for i in "${!ids[@]}"; do picked[i]=no; done
  for word in $HYPR_APPS; do
    found=false
    for i in "${!ids[@]}"; do
      if [[ "$word" == all || "$word" == "${ids[i]}" ]]; then
        picked[i]=yes
        found=true
      fi
    done
    [[ "$found" == true || "$word" == none ]] || echo "Skipping $word: no such group of apps." >&2
  done
fi

# What was chosen
pacman_pkgs=() flatpaks=() browser_cmd="" browser_file=""
for entry in "${BROWSERS[@]}"; do
  IFS='|' read -r id _ pkg cmd file <<<"$entry"
  if [[ "$id" == "$browser" ]]; then
    [[ -n "$pkg" ]] && pacman_pkgs+=("$pkg")
    browser_cmd="$cmd" browser_file="$file"
  fi
done
groups=()
for i in "${!ids[@]}"; do
  [[ "${picked[i]}" == yes ]] || continue
  groups+=("${ids[i]}")
  while read -r line; do
    case "$line" in
      flatpak:*) flatpaks+=("${line#flatpak:}") ;;
      *) pacman_pkgs+=("$line") ;;
    esac
  done < <(sed 's/#.*//; s/[[:space:]]*$//; /^[[:space:]]*$/d' "$dir/apps/${ids[i]}.txt")
done

if [[ "$dry" == false ]]; then
  mkdir -p "$(dirname "$state")"
  { printf 'browser=%s\n' "$browser"; printf 'group=%s\n' "${groups[@]+"${groups[@]}"}"; } > "$state"
fi

if [[ "$print" == true ]]; then
  for x in "${groups[@]+"${groups[@]}"}"; do printf 'group %s\n' "$x"; done
  for x in "${pacman_pkgs[@]+"${pacman_pkgs[@]}"}"; do printf 'pacman %s\n' "$x"; done
  for x in "${flatpaks[@]+"${flatpaks[@]}"}"; do printf 'flatpak %s\n' "$x"; done
  [[ -n "$browser_cmd" ]] && printf 'browser %s %s\n' "$browser_cmd" "$browser_file"
  exit 0
fi

# On its own: install them now
if [[ "$dry" == true ]]; then
  echo "[dry run] packages: ${pacman_pkgs[*]+"${pacman_pkgs[*]}"}"
  echo "[dry run] flatpaks: ${flatpaks[*]+"${flatpaks[*]}"}"
  exit 0
fi
if (( ${#pacman_pkgs[@]} > 0 )); then
  if command -v paru >/dev/null 2>&1; then
    paru -S --needed "${pacman_pkgs[@]}" || echo "Some packages did not install." >&2
  else
    sudo pacman -S --needed "${pacman_pkgs[@]}" || echo "Some packages did not install (AUR packages need paru)." >&2
  fi
fi
for app in "${flatpaks[@]+"${flatpaks[@]}"}"; do
  flatpak install -y --noninteractive --or-update flathub "$app" || echo "Could not install $app." >&2
done
[[ -n "$browser_cmd" ]] && set_browser "$browser_cmd" "$browser_file"
echo "Done. Docker and CoolerControl need their services on: sudo systemctl enable --now docker coolercontrold"
