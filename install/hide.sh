#!/usr/bin/env bash
set -euo pipefail

# hide_apps.sh
# Hides desktop entries listed in a file by copying the system .desktop file
# into ~/.local/share/applications/ and appending NoDisplay=true.
#
# Usage:
#   hide_apps.sh [--file PATH] [--dry-run] [--undo]
#
# Defaults:
#   --file defaults to $HOME/hyprdots/install/hide.txt

APPS_FILE="$HOME/hyprdots/install/hide.txt"
DRY_RUN=false
UNDO=false

usage() {
  cat <<EOF
Usage: $0 [--file PATH] [--dry-run] [--undo] [-h|--help]

  --file PATH    Path to file with app names (one per line, without .desktop)
  --dry-run      Print what would be done without changing files
  --undo         Remove NoDisplay=true lines from copied user desktop files
  -h, --help     Show this help
EOF
  exit 0
}

# Parse args
while [[ $# -gt 0 ]]; do
  case "$1" in
    --file) APPS_FILE="$2"; shift 2 ;;
    --dry-run) DRY_RUN=true; shift ;;
    --undo) UNDO=true; shift ;;
    -h|--help) usage ;;
    *) echo "Unknown arg: $1"; usage ;;
  esac
done

log() {
  printf "%s\n" "$*"
}

if [[ ! -f "$APPS_FILE" ]]; then
  log "App list file not found: $APPS_FILE. Exiting."
  exit 0
fi

mkdir -p "$HOME/.local/share/applications"

process_app() {
  local app="$1"
  # Trim whitespace
  app="${app#"${app%%[![:space:]]*}"}"
  app="${app%"${app##*[![:space:]]}"}"
  [[ -z "$app" ]] && return
  [[ "$app" =~ ^# ]] && return

  local desktop_file="/usr/share/applications/${app}.desktop"
  local user_desktop="$HOME/.local/share/applications/${app}.desktop"

  if [[ ! -f "$desktop_file" ]]; then
    log "Could not find desktop file: $desktop_file (skipping $app)"
    return
  fi

  if [[ "$DRY_RUN" == "true" ]]; then
    if [[ "$UNDO" == "true" ]]; then
      log "[DRY RUN] Would remove 'NoDisplay=true' from $user_desktop (if present)"
    else
      log "[DRY RUN] Would copy $desktop_file -> $user_desktop and add NoDisplay=true if not present"
    fi
    return
  fi

  # Copy the system .desktop file to user's local applications (overwrite so updates propagate)
  cp -f "$desktop_file" "$user_desktop"
  if [[ "$UNDO" == "true" ]]; then
    # Remove any NoDisplay=true lines
    if grep -q '^NoDisplay=true' "$user_desktop"; then
      sed -i '/^NoDisplay=true/d' "$user_desktop"
      log "Removed NoDisplay=true from $user_desktop"
    else
      log "NoDisplay=true not present in $user_desktop"
    fi
  else
    if grep -q '^NoDisplay=true' "$user_desktop"; then
      log "Already hidden: $app"
    else
      echo "NoDisplay=true" >> "$user_desktop"
      log "Hid: $app"
    fi
  fi
}

# Read file and process lines
while IFS= read -r line || [[ -n "$line" ]]; do
  process_app "$line"
done < "$APPS_FILE"

log "Done."
