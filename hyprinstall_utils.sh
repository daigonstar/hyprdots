#!/usr/bin/env bash
# hyprinstall_utils.sh
# Utility functions for hyprinstall.sh

init_logging() {
  if [[ "$DRY_RUN" == "true" ]]; then
    echo "[DRY RUN] Would initialize logging to $LOGFILE"
    return
  fi
  mkdir -p "$(dirname "$DEFAULT_LOG")"
  if touch "$DEFAULT_LOG" >/dev/null 2>&1; then
    LOGFILE="$DEFAULT_LOG"
  else
    LOGFILE="$FALLBACK_LOG"
    touch "$LOGFILE"
    echo "Note: couldn't write to $DEFAULT_LOG; using $LOGFILE"
  fi
}

log() {
  local level="$1"; shift
  local ts
  ts="$(date +'%Y-%m-%d %H:%M:%S')"
  printf "%s [%s] %s\n" "$ts" "$level" "$*" | tee -a "$LOGFILE"
}

die() {
  log "ERROR" "$*"
  exit 1
}

run_cmd() {
  local cmd="$*"
  if [[ "$DRY_RUN" == "true" ]]; then
    printf "[DRY RUN] %s\n" "$cmd" | tee -a "$LOGFILE"
    return
  fi

  if [[ "$VERBOSE" == "true" ]]; then
    log "CMD" "$cmd"
    bash -c "$cmd" 2>&1 | tee -a "$LOGFILE"
    return ${PIPESTATUS[0]}
  fi

  local out
  out=$(mktemp)
  bash -c "$cmd" >"$out" 2>&1 &
  local pid=$!
  local dots=( "   " "*  " "** " "***" )
  local i=0
  while kill -0 "$pid" 2>/dev/null; do
    printf "\r%s" "${dots[i]}"
    i=$(( (i + 1) % ${#dots[@]} ))
    sleep 0.5
  done
  wait "$pid"
  local st=$?
  printf "\r   \r"
  if [[ $st -eq 0 ]]; then
    log "OK" "$cmd"
    rm -f "$out"
  else
    log "FAIL" "$cmd (exit $st)"
    log "FAIL" "Command output (first 200 lines):"
    sed -n '1,200p' "$out" | sed "s/^/    /" >> "$LOGFILE"
    rm -f "$out"
    return $st
  fi
}

read_packages_to_array() {
  local file="$1"
  local -n arr=$2
  arr=()
  [[ -f "$file" ]] || die "Package list not found: $file"
  while IFS= read -r line || [[ -n "$line" ]]; do
    line="${line%%#*}"
    line="$(echo "$line" | xargs)"
    [[ -z "$line" ]] && continue
    arr+=("$line")
  done < "$file"
}

yesno_prompt() {
  local prompt="$1"
  local default="${2:-N}"
  if [[ "$DRY_RUN" == "true" ]]; then
    printf "[DRY RUN] %s (default %s) -> No\n" "$prompt" "$default"
    return 1
  fi
  read -rp "$prompt [$default]: " ans
  [[ -z "$ans" ]] && ans="$default"
  [[ "$ans" =~ ^[Yy] ]]
}

preflight_checks() {
  if [[ "$DRY_RUN" == "true" ]]; then
    echo "[DRY RUN] Would run preflight checks (root/sudo/credential cache)"
    return
  fi
  if [[ "$EUID" -eq 0 ]]; then
    echo "This script must be run as a normal (non-root) user with sudo access, not as root." >&2
    echo "Create a user first, e.g.:" >&2
    echo "  useradd -m -G wheel -s /bin/bash <username> && passwd <username>" >&2
    echo "  pacman -S --needed sudo" >&2
    echo "  EDITOR=nano visudo   # uncomment '%wheel ALL=(ALL:ALL) ALL'" >&2
    echo "Then log in as that user and re-run this script." >&2
    exit 1
  fi
  if ! command -v sudo >/dev/null 2>&1; then
    echo "'sudo' is not installed. On a vanilla Arch install, run the following as root first:" >&2
    echo "  pacman -S --needed sudo" >&2
    echo "  usermod -aG wheel $USER" >&2
    echo "  EDITOR=nano visudo   # uncomment '%wheel ALL=(ALL:ALL) ALL'" >&2
    echo "Log out/in (or reboot) so the group membership takes effect, then re-run this script." >&2
    exit 1
  fi
  echo "Caching sudo credentials (you may be prompted for your password)..."
  if ! sudo -v; then
    echo "Failed to obtain sudo privileges. Ensure your user is in the 'wheel' group and sudoers is configured." >&2
    exit 1
  fi
  # Keep the sudo timestamp alive for the duration of the script so long AUR
  # builds don't hit an expired/backgrounded password prompt.
  ( while true; do sudo -n true 2>/dev/null; sleep 60; kill -0 "$$" 2>/dev/null || exit; done ) &
  SUDO_KEEPALIVE_PID=$!
  trap '[[ -n "${SUDO_KEEPALIVE_PID:-}" ]] && kill "$SUDO_KEEPALIVE_PID" 2>/dev/null' EXIT
}
