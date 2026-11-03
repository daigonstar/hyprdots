#!/usr/bin/env bash

#

# hyprinstall-final.sh

# Production-ready Hyprland setup installer

# Options: --dry-run, --verbose, --plain (plain questions instead of the full-screen interface, install/tui.py)

# Logging: ~/.local/share/hyprinstall/hyprinstall.log

set -euo pipefail
USER="${USER:-$(id -un)}"  # unset in some containers and minimal shells

# Configuration defaults

DEFAULT_LOG="$HOME/.local/share/hyprinstall/hyprinstall.log"
FALLBACK_LOG="$HOME/hyprinstall.log"
BASE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$BASE_DIR"
DOTFILES_DIR="$REPO_DIR/.config"
REQUIRED_FILE="$BASE_DIR/install/required.txt"
LOGFILE="$DEFAULT_LOG"
EXTRA_DEPENDENCIES=(git base-devel flatpak python rust imagemagick rsync pciutils)

# Parse flags

DRY_RUN=false
VERBOSE=false
PLAIN=false
for arg in "$@"; do
case "$arg" in
--dry-run) DRY_RUN=true ;;
--verbose) VERBOSE=true ;;
--plain) PLAIN=true ;;
esac
done
# With a terminal, install/tui.py asks the questions and runs this script again to do the work (HYPRINSTALL_TUI set)
use_tui() { [[ -z "${HYPRINSTALL_TUI:-}" && "$PLAIN" == "false" && -t 0 && -t 1 && "${TERM:-dumb}" != "dumb" ]]; }
# Progress marks that the interface reads; nothing in plain mode
mark() { [[ -z "${HYPRINSTALL_TUI:-}" ]] || printf '::%s\n' "$*"; }

# Logging helpers

init_logging() {
  mkdir -p "$(dirname "$DEFAULT_LOG")" 2>/dev/null || true
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

# Command runner

run_cmd() {
local cmd="$*"
mark run "$cmd"
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
    [[ -t 1 ]] && printf "\r%s" "${dots[i]}"
    i=$(( (i + 1) % ${#dots[@]} ))
    sleep 0.5
done
wait "$pid"
local st=$?
[[ -t 1 ]] && printf "\r   \r"
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

# Utility functions

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

# Preflight: refuse to run as root, ensure sudo exists, and cache credentials
# up front so none of the dozens of later `sudo` calls (some running inside
# backgrounded AUR builds) ever stall or fail on a lapsed/missing prompt.
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
# The interface has the screen, and the first run through here already asked for the password
if [[ -n "${HYPRINSTALL_TUI:-}" ]]; then
  sudo -n -v || { echo "Your sudo password has expired. Run ./hyprinstall.sh again." >&2; exit 1; }
else
echo "Caching sudo credentials (you may be prompted for your password)..."
fi
if [[ -z "${HYPRINSTALL_TUI:-}" ]] && ! sudo -v; then
echo "Failed to obtain sudo privileges. Ensure your user is in the 'wheel' group and sudoers is configured." >&2
exit 1
fi
# Keep the sudo timestamp alive for the duration of the script so long AUR
# builds don't hit an expired/backgrounded password prompt.
( while true; do sudo -n true 2>/dev/null; sleep 60; kill -0 "$$" 2>/dev/null || exit; done ) >/dev/null 2>&1 </dev/null &
SUDO_KEEPALIVE_PID=$!
trap '[[ -n "${SUDO_KEEPALIVE_PID:-}" ]] && kill "$SUDO_KEEPALIVE_PID" 2>/dev/null' EXIT
}

# Script start

init_logging

# Branch selection for repo operations (supports UPDATE_BRANCH env var or .update-branch file)
BRANCH="${UPDATE_BRANCH:-}"
if [[ -f "$BASE_DIR/.update-branch" ]]; then
  BRANCH="$(<"$BASE_DIR/.update-branch")"
fi
if [[ -z "$BRANCH" && "$DRY_RUN" == "false" && -t 0 ]] && ! use_tui; then
  echo "Select branch to use for repo operations:"
  echo "  1) main (recommended)"
  echo "  2) dev (development)"
  echo "  3) Enter branch name"
  read -rp "Choice [1-3] (default 1): " _choice
  case "$_choice" in
    1) BRANCH="main" ;;
    3) read -rp "Enter branch name: " BRANCH ;;
    *) BRANCH="main" ;;
  esac
fi
BRANCH="${BRANCH:-main}"

# Update the repo first. A pull can change this very script, so when it does, start again from the new copy rather
# than carry on with the old one against new files.
if [[ -z "${HYPRINSTALL_RESTARTED:-}" ]] && git -C "$REPO_DIR" rev-parse --git-dir >/dev/null 2>&1; then
  before="$(git -C "$REPO_DIR" rev-parse HEAD 2>/dev/null || true)"
  # Best-effort fetch, checkout and pull; do not abort the installer if these fail
  run_cmd "git -C \"$REPO_DIR\" fetch --prune origin" || true
  run_cmd "git -C \"$REPO_DIR\" checkout \"$BRANCH\"" || true
  run_cmd "git -C \"$REPO_DIR\" pull --ff-only origin \"$BRANCH\"" || true
  if [[ "$DRY_RUN" == "false" && "$(git -C "$REPO_DIR" rev-parse HEAD 2>/dev/null || true)" != "$before" ]]; then
    log "INFO" "The repo was updated; restarting the installer from the new copy"
    UPDATE_BRANCH="$BRANCH" HYPRINSTALL_RESTARTED=1 exec bash "$BASE_DIR/hyprinstall.sh" "$@"
  fi
fi

preflight_checks

# The full-screen interface needs Python, which a bare system may not have yet. If it cannot start, the plain questions take over.
if use_tui; then
  command -v python3 >/dev/null 2>&1 || run_cmd "sudo pacman -S --needed --noconfirm python" || true
  if python3 -c 'import curses; curses.setupterm()' 2>/dev/null; then
    export UPDATE_BRANCH="$BRANCH"
    exec python3 "$BASE_DIR/install/tui.py" "$@"
  fi
  log "WARN" "Could not start the full-screen interface; using plain questions"
fi

log "INFO" "Starting hyprinstall. Log: $LOGFILE"
log "INFO" "Using branch: $BRANCH"

# Steam and the 32-bit GPU libraries live in the [multilib] repo, which is
# disabled on a fresh Arch install. Enable it before the first database sync.
if grep -qE '^\[multilib\]' /etc/pacman.conf; then
  log "OK" "multilib repository already enabled"
else
  run_cmd "sudo sed -i '/^#\[multilib\]/,/^#Include/ s/^#//' /etc/pacman.conf" ||
    die "Failed to enable the multilib repository. See $LOGFILE for details."
  log "OK" "Enabled the multilib repository (needed for Steam)"
fi

# Full system sync/upgrade first. On a freshly imaged vanilla Arch install,
# the package DB/keyring can be stale relative to current repos; installing
# packages against a stale DB is the classic cause of partial-upgrade and
# signature verification failures.
mark step system
log "INFO" "Refreshing package database and keyring before installing anything"
run_cmd "sudo pacman -Sy --needed --noconfirm archlinux-keyring" ||
  die "Failed to refresh archlinux-keyring. See $LOGFILE for details."
run_cmd "sudo pacman -Syu --noconfirm" ||
  die "Failed to sync/upgrade the system. See $LOGFILE for details."

# Install core dependencies

log "INFO" "Ensuring extra dependencies: ${EXTRA_DEPENDENCIES[*]}"
for d in "${EXTRA_DEPENDENCIES[@]}"; do
if pacman -Qi "$d" &>/dev/null; then
log "OK" "Dependency present: $d"
else
run_cmd "sudo pacman -S --needed --noconfirm \"$d\"" ||
  die "Failed to install required dependency: $d. See $LOGFILE for details."
fi
done

# Read package lists

read_packages_to_array "$REQUIRED_FILE" REQUIRED_PKGS

# Which optional apps (install/apps/) and browser. Asked here, early, so the rest can run without you.
APP_PKGS=() FLATPAK_PKGS=() APP_GROUPS=() BROWSER_CMD="" BROWSER_DESKTOP=""
apps_args=(--print)
[[ "$DRY_RUN" == "true" ]] && apps_args+=(--dry-run)
while read -r kind value extra; do
  case "$kind" in
    group) APP_GROUPS+=("$value") ;;
    pacman) APP_PKGS+=("$value") ;;
    flatpak) FLATPAK_PKGS+=("$value") ;;
    browser) BROWSER_CMD="$value" BROWSER_DESKTOP="$extra" ;;
  esac
done < <("$BASE_DIR/install/apps.sh" "${apps_args[@]}")
log "INFO" "Optional apps: ${APP_GROUPS[*]:-none}; browser: ${BROWSER_CMD:-your own}"
chose_group() { [[ " ${APP_GROUPS[*]:-} " == *" $1 "* ]]; }

# Install paru (AUR helper)

install_paru() {
if command -v paru >/dev/null 2>&1; then
log "OK" "paru already installed"
return
fi
run_cmd "sudo pacman -S --needed --noconfirm git base-devel"
local tmpdir
tmpdir="$(mktemp -d)"
run_cmd "git clone https://aur.archlinux.org/paru.git \"$tmpdir/paru\"" || die "Could not download paru. See $LOGFILE for details."
run_cmd "cd \"$tmpdir/paru\" && makepkg -si --noconfirm" || die "Could not build paru. See $LOGFILE for details."
rm -rf "$tmpdir"
[[ "$DRY_RUN" == "true" ]] && return
log "OK" "paru installed"
}
install_paru

# Install required packages

install_package_list() {
local pkgs=("$@")
mark items "${#pkgs[@]}"
for pkg in "${pkgs[@]:-}"; do
mark item "$pkg"
# -T also counts a package that provides it (vesktop-git for vesktop): installing the listed one would conflict
if pacman -T "$pkg" &>/dev/null; then
log "OK" "Package $pkg already installed"
elif pacman -Si "$pkg" &>/dev/null; then
log "INFO" "Installing official package: $pkg"
run_cmd "sudo pacman -S --needed --noconfirm \"$pkg\"" ||
  die "Failed to install official package: $pkg. See $LOGFILE for details."
else
if [[ "$DRY_RUN" == "true" ]] || command -v paru >/dev/null 2>&1; then
# (a dry run has not really installed paru or enabled multilib, so it reports these instead of stopping)
log "INFO" "Installing AUR package: $pkg"
run_cmd "paru -S --needed --noconfirm \"$pkg\"" ||
  die "Failed to install AUR package: $pkg. See $LOGFILE for details."
else
die "Package $pkg is not in the official repositories and paru is unavailable."
fi
fi
done
}

# GPU drivers: detect the vendor(s) via lspci and let the user confirm or change.
# Override for unattended installs: HYPR_GPU="amd" (or "nvidia", "intel", "amd nvidia").
select_gpu_vendors() {
  GPU_VENDORS=()
  if [[ -n "${HYPR_GPU:-}" ]]; then
    [[ "$HYPR_GPU" == none ]] || read -ra GPU_VENDORS <<<"$HYPR_GPU"
    return
  fi

  local gpu_info detected=()
  gpu_info="$(lspci -nn 2>/dev/null | grep -Ei 'vga|3d controller|display controller' || true)"
  # Match the PCI vendor ID ([10de:...] etc.), or the name as a whole word: a bare 'ati' would match "Intel Corporation"
  grep -qiE '\[10de:|\bnvidia\b' <<<"$gpu_info" && detected+=(nvidia)
  grep -qiE '\[1002:|\b(amd|ati)\b|advanced micro' <<<"$gpu_info" && detected+=(amd)
  grep -qiE '\[8086:|\bintel\b' <<<"$gpu_info" && detected+=(intel)

  if [[ "$DRY_RUN" == "true" || ! -t 0 ]]; then
    GPU_VENDORS=("${detected[@]}")
    return
  fi

  if [[ ${#detected[@]} -gt 0 ]]; then
    echo "Detected GPU(s): ${detected[*]}"
    read -rp "Install drivers for these? [Y/n]: " ans
    if [[ ! "$ans" =~ ^[Nn] ]]; then
      GPU_VENDORS=("${detected[@]}")
      return
    fi
  else
    echo "Could not detect a GPU."
  fi

  echo "Choose the GPU driver set(s) to install:"
  echo "  1) AMD   2) NVIDIA   3) Intel   4) None (skip)"
  read -rp "Number(s), e.g. '1' or '1 2' for a hybrid setup: " picks
  local pick
  for pick in $picks; do
    case "$pick" in
      1) GPU_VENDORS+=(amd) ;;
      2) GPU_VENDORS+=(nvidia) ;;
      3) GPU_VENDORS+=(intel) ;;
    esac
  done
}

mark step drivers
select_gpu_vendors
if [[ ${#GPU_VENDORS[@]} -eq 0 ]]; then
  log "WARN" "No GPU drivers selected; skipping GPU packages (Steam and the assistant will run without GPU acceleration)"
fi
for vendor in "${GPU_VENDORS[@]}"; do
  gpu_file="$BASE_DIR/install/gpu-$vendor.txt"
  if [[ ! -f "$gpu_file" ]]; then
    log "WARN" "No driver list for '$vendor' ($gpu_file); skipping"
    continue
  fi
  log "INFO" "Installing $vendor GPU drivers"
  read_packages_to_array "$gpu_file" GPU_PKGS
  install_package_list "${GPU_PKGS[@]}"
done

mark step desktop
install_package_list "${REQUIRED_PKGS[@]}"
mark step apps
[[ ${#APP_PKGS[@]} -eq 0 ]] || install_package_list "${APP_PKGS[@]}"

# Flatpak installs

mark step flatpak
mark items "${#FLATPAK_PKGS[@]}"
run_cmd "flatpak remote-add --if-not-exists flathub https://dl.flathub.org/repo/flathub.flatpakrepo" ||
  die "Failed to configure the Flathub remote. See $LOGFILE for details."

for f in "${FLATPAK_PKGS[@]:-}"; do
[[ -n "$f" ]] || continue
mark item "$f"
if flatpak list --app 2>/dev/null | grep -qw "$f"; then
log "OK" "Flatpak $f already installed"
else
run_cmd "flatpak install -y --noninteractive --or-update flathub \"$f\"" ||
  die "Failed to install Flatpak: $f. See $LOGFILE for details."
fi
done

mark step services
# Services needed by the installed apps. (ollama is enabled by the assistant setup below,
# only if you choose the assistant.)

# NetworkManager is skipped when another network manager is already in charge: two of them fight over the
# connection and the network can drop mid-install.
other_net=""
for svc in systemd-networkd connman dhcpcd netctl wicd; do
  if systemctl is-enabled --quiet "$svc.service" 2>/dev/null; then other_net="$svc"; break; fi
done
SERVICES=(bluetooth)
chose_group hardware && SERVICES+=(coolercontrold)
chose_group windows && SERVICES+=(docker)
if [[ -n "$other_net" ]] && ! systemctl is-enabled --quiet NetworkManager.service 2>/dev/null; then
  log "WARN" "$other_net manages your network, so NetworkManager was not enabled (the bar's network menu needs it)"
else
  SERVICES=(NetworkManager "${SERVICES[@]}")
fi
for svc in "${SERVICES[@]}"; do
  run_cmd "sudo systemctl enable --now $svc.service" || log "WARN" "Could not enable $svc.service"
done

# WinBoat runs Windows in a docker container; the user must be in the docker group
if chose_group windows && ! id -nG "$USER" | tr ' ' '\n' | grep -qx docker; then
  run_cmd "sudo usermod -aG docker \"$USER\"" && log "INFO" "Added $USER to the docker group (log out and back in for it to apply)"
fi

mark step assistant
# PC assistant (optional): choose a model size for your hardware, or skip it.
# Unattended: HYPR_ASSISTANT=none|auto|full|balanced|light. It can be changed later with
# ~/.config/hypr/assistant/setup.sh
ASSISTANT_SETUP="$DOTFILES_DIR/hypr/assistant/setup.sh"
if [[ -x "$ASSISTANT_SETUP" ]]; then
  ASSISTANT_ARGS=()
  [[ "$DRY_RUN" == "true" ]] && ASSISTANT_ARGS+=(--dry-run --yes)
  # Run directly (not through run_cmd) so its menu and download progress stay visible.
  "$ASSISTANT_SETUP" "${ASSISTANT_ARGS[@]}" || log "WARN" "Assistant setup failed (run $ASSISTANT_SETUP later)"
else
  log "WARN" "Assistant setup script not found: $ASSISTANT_SETUP. Skipping."
fi

# Home directories

mark step config
run_cmd "mkdir -p \"$HOME/Pictures\" \"$HOME/Videos\" \"$HOME/Documents\" \"$HOME/.config\" \"$HOME/Downloads\""

# Existing configs are always moved here rather than deleted, so nothing of the user's is lost

BACKUP_DIR="$HOME/.config-backup/$(date +%Y%m%d-%H%M%S)"
backup_path() {
local path="$1"
[[ -e "$path" || -L "$path" ]] || return 0
run_cmd "mkdir -p \"$BACKUP_DIR\""
run_cmd "mv \"$path\" \"$BACKUP_DIR/\""
log "INFO" "Moved existing $path to $BACKUP_DIR"
}

# Symlink config directories

CONFIG_TARGETS=(hypr fastfetch rofi waybar swaync wallust ghostty)
for dir in "${CONFIG_TARGETS[@]}"; do
target="$HOME/.config/$dir"
source="$DOTFILES_DIR/$dir"
if [[ ! -d "$source" ]]; then
log "WARN" "Source missing: $source"
continue
fi
if [[ -L "$target" && "$(readlink "$target")" == "$source" ]]; then
log "OK" "Already symlinked: $target"
continue
fi
backup_path "$target"
run_cmd ln -sfn "$source" "$target"
done

# Add temp monitor and workspace configs (machine-local, gitignored; Lua since the 0.55+ config migration)

run_cmd touch "$HOME/.config/hypr/monitors.lua"
run_cmd touch "$HOME/.config/hypr/workspaces.lua"

# Starship config

starship_file="$HOME/.config/starship.toml"
if [[ ! -L "$starship_file" || "$(readlink "$starship_file")" != "$DOTFILES_DIR/starship.toml" ]]; then
backup_path "$starship_file"
fi
run_cmd ln -sfn "$DOTFILES_DIR/starship.toml" "$starship_file"

# Wallpapers

wallpaper_src="$REPO_DIR/wallpapers"
wallpaper_dest="$HOME/Pictures/wallpapers"
# Add the repo's wallpapers alongside the user's own; never delete or overwrite existing files
if [[ -d "$wallpaper_src" ]]; then
run_cmd "mkdir -p \"$wallpaper_dest\""
run_cmd "cp -r --update=none \"$wallpaper_src/.\" \"$wallpaper_dest/\""
fi
# Starting colours and a current wallpaper until you pick one (Super+W); these files are git-ignored
run_cmd "bash \"$DOTFILES_DIR/hypr/scripts/first-colours.sh\""

# Make scripts executable

mapfile -t SCRIPT_FILES < <(git -C "$REPO_DIR" ls-files .config bash install 2>/dev/null |
  while read -r f; do [[ -f "$REPO_DIR/$f" ]] && head -c2 "$REPO_DIR/$f" | grep -q '#!' && echo "$REPO_DIR/$f"; done)
if [[ ${#SCRIPT_FILES[@]} -gt 0 ]]; then
  run_cmd "chmod +x $(printf '"%s" ' "${SCRIPT_FILES[@]}")"
fi

# Thunar's "Open Terminal Here" needs a stand-in for xfce4-mime-helper (installed into ~/.local/bin)
# and to know which terminal to open; hypr-settings re-runs this when the terminal is changed
run_cmd "$DOTFILES_DIR/hypr/scripts/exo-terminal.sh"

# Steam shortcut cleanup: periodically remove Steam-generated game launcher
# entries via a systemd --user timer

STEAM_CLEANUP_SCRIPT="$REPO_DIR/bash/remove-steam-shortcuts.sh"
if [[ -f "$STEAM_CLEANUP_SCRIPT" ]]; then
    echo "🧹 Setting up periodic Steam shortcut cleanup..."
    run_cmd "chmod +x \"$STEAM_CLEANUP_SCRIPT\""
    run_cmd "mkdir -p \"$HOME/.config/systemd/user\""
    # The timer unit has no path references, so it can be symlinked as-is.
    run_cmd "ln -sfn \"$DOTFILES_DIR/systemd/user/remove-steam-shortcuts.timer\" \"$HOME/.config/systemd/user/remove-steam-shortcuts.timer\""
    # The service unit's ExecStart hardcodes %h/hyprdots/..., which only
    # works if the repo was cloned to exactly $HOME/hyprdots. Generate a copy
    # with ExecStart pointing at the repo's actual location instead.
    if [[ "$DRY_RUN" == "true" ]]; then
        echo "[DRY RUN] Would generate $HOME/.config/systemd/user/remove-steam-shortcuts.service pointing at $STEAM_CLEANUP_SCRIPT"
    else
        sed "s|^ExecStart=.*|ExecStart=$STEAM_CLEANUP_SCRIPT|" \
            "$DOTFILES_DIR/systemd/user/remove-steam-shortcuts.service" \
            > "$HOME/.config/systemd/user/remove-steam-shortcuts.service"
        log "OK" "Generated remove-steam-shortcuts.service with ExecStart=$STEAM_CLEANUP_SCRIPT"
    fi
    run_cmd "systemctl --user daemon-reload"
    run_cmd "systemctl --user enable --now remove-steam-shortcuts.timer"
    log "OK" "Steam shortcut cleanup timer enabled"
else
    log "WARN" "Steam cleanup script not found: $STEAM_CLEANUP_SCRIPT. Skipping."
fi

# PC health monitor for the Hyprland agent (flags problems via notifications)

AGENT_MONITOR_SCRIPT="$DOTFILES_DIR/hypr/assistant/agent_monitor.py"
if [[ -f "$AGENT_MONITOR_SCRIPT" ]] && [[ "${HYPR_HEALTH:-ask}" != no ]] && { [[ "${HYPR_HEALTH:-ask}" == yes ]] || yesno_prompt "Enable the background health monitor (desktop notifications about failed services, full disks, heat)? It needs no AI model." "Y"; }; then
    echo "🩺 Setting up periodic PC health monitor..."
    run_cmd "chmod +x \"$AGENT_MONITOR_SCRIPT\""
    run_cmd "mkdir -p \"$HOME/.config/systemd/user\""
    # The service runs the script via %h/.config/hypr, so both units can be symlinked as-is.
    run_cmd "ln -sfn \"$DOTFILES_DIR/systemd/user/agent-monitor.service\" \"$HOME/.config/systemd/user/agent-monitor.service\""
    run_cmd "ln -sfn \"$DOTFILES_DIR/systemd/user/agent-monitor.timer\" \"$HOME/.config/systemd/user/agent-monitor.timer\""
    run_cmd "systemctl --user daemon-reload"
    run_cmd "systemctl --user enable --now agent-monitor.timer"
    log "OK" "PC health monitor timer enabled"
fi

# Private user settings (calendar links); never overwrite an existing file
USER_LOCAL_SETTINGS="$DOTFILES_DIR/hypr/user_settings.local.toml"
if [[ ! -f "$USER_LOCAL_SETTINGS" && -f "$USER_LOCAL_SETTINGS.example" ]]; then
    run_cmd "cp \"$USER_LOCAL_SETTINGS.example\" \"$USER_LOCAL_SETTINGS\""
    run_cmd "chmod 600 \"$USER_LOCAL_SETTINGS\""
    log "OK" "Created user_settings.local.toml - add your calendar link there (see the file for steps)"
fi

# Cursor icons + Flatpak overrides

if [[ -d "$REPO_DIR/icons/Future-cursors" ]]; then
run_cmd "sudo mkdir -p /usr/share/icons/Future-cursors && sudo cp -rT \"$REPO_DIR/icons/Future-cursors\" /usr/share/icons/Future-cursors"
run_cmd "flatpak --user override --filesystem=/home/\"$USER\"/.icons/:ro"
run_cmd "flatpak --user override --filesystem=/usr/share/icons/:ro"
fi
# The keyboard layout you picked, on the desktop (the login screen reads it further down)
if [[ -n "${HYPR_KB_LAYOUT:-}" ]]; then
  run_cmd "\"$BASE_DIR/install/apps.sh\" --set-keyboard \"$HYPR_KB_LAYOUT\"" || log "WARN" "Could not set the keyboard layout; pick it in Settings"
fi

# The browser you picked is the one Super+B opens
if [[ -n "$BROWSER_CMD" ]]; then
  run_cmd "\"$BASE_DIR/install/apps.sh\" --set-browser \"$BROWSER_CMD\" \"$BROWSER_DESKTOP\"" || log "WARN" "Could not set the browser; pick it in Settings"
fi

# Flatpak apps follow the settings Theme page: they may read its colours (~/.config/gtk-*), and GTK 3 ones get the
# adw-gtk3 style as a Flatpak (GTK 4 apps need no theme)
run_cmd "flatpak --user override --filesystem=xdg-config/gtk-3.0:ro --filesystem=xdg-config/gtk-4.0:ro"
run_cmd "flatpak install -y --noninteractive --or-update flathub org.gtk.Gtk3theme.adw-gtk3 org.gtk.Gtk3theme.adw-gtk3-dark" ||
  log "WARN" "Could not install the adw-gtk3 theme for Flatpak apps; GTK 3 Flatpak apps keep their own look"

# Bashrc update

BASHRC_MARKER="# --- hyprinstall additions BEGIN ---"
if grep -Fq "$BASHRC_MARKER" "$HOME/.bashrc" 2>/dev/null; then
log "INFO" "$HOME/.bashrc already contains hyprinstall additions; skipping"
elif [[ "$DRY_RUN" == "true" ]]; then
echo "[DRY RUN] Would add the update/hyprupdate aliases, starship and fastfetch to $HOME/.bashrc"
else
cat >> "$HOME/.bashrc" <<'BASHRC'

# --- hyprinstall additions BEGIN ---

alias update='paru -Syu && flatpak update'
# The repo is wherever ~/.config/hypr links to, so this keeps working if it moves
alias hyprupdate='"$(readlink -f ~/.config/hypr)/../../update.sh"'
eval "$(starship init bash)"
command fastfetch

# --- hyprinstall additions END ---

BASHRC
log "OK" "Appended hyprinstall additions to ~/.bashrc"
fi

# SDDM: the login screen runs on Wayland inside Weston, on your main screen only
#
# No X server, so nothing like the old xrandr step can hold it up, and Plymouth's last frame stays on screen until the
# login screen appears (plymouth quit --retain-splash). Connected screens are read from the kernel, which works from a
# text console too, unlike xrandr; Weston uses the same names (DP-1, HDMI-A-1). Every screen except the one you pick
# is switched off for the login screen only: Hyprland's own layout is not affected.

mark step login
echo "🖥️  Setting up the login screen..."

mapfile -t CONNECTED_MONITORS < <(
    for status in /sys/class/drm/card*-*/status; do
        [[ -r "$status" && "$(<"$status")" == "connected" ]] || continue
        name="$(basename "$(dirname "$status")")"
        [[ "$name" == *-Writeback-* ]] && continue   # a virtual output inside the GPU, not a screen
        echo "${name#card*-}"
    done | sort -u
)

MAIN_MONITOR=""
if [[ "${#CONNECTED_MONITORS[@]}" -gt 1 ]]; then
    echo "Detected connected monitors:"
    for i in "${!CONNECTED_MONITORS[@]}"; do
        printf "  %d) %s\n" "$((i + 1))" "${CONNECTED_MONITORS[$i]}"
    done
    if [[ -n "${HYPR_LOGIN_MONITOR:-}" ]]; then
        MAIN_MONITOR="$HYPR_LOGIN_MONITOR"
    elif [[ "$DRY_RUN" == "true" || ! -t 0 ]]; then
        MAIN_MONITOR="${CONNECTED_MONITORS[0]}"
        log "INFO" "Not asking for the main monitor; using ${MAIN_MONITOR}"
    else
        while [[ -z "$MAIN_MONITOR" ]]; do
            read -rp "Which monitor should show the login screen (number)? " choice
            if [[ "$choice" =~ ^[0-9]+$ ]] && (( choice >= 1 && choice <= ${#CONNECTED_MONITORS[@]} )); then
                MAIN_MONITOR="${CONNECTED_MONITORS[$((choice - 1))]}"
            else
                echo "Please enter a number between 1 and ${#CONNECTED_MONITORS[@]}."
            fi
        done
    fi
    log "INFO" "Selected '$MAIN_MONITOR' as the main monitor for the login screen."
fi

KB_LAYOUT="${HYPR_KB_LAYOUT:-$(grep -oP 'kb_layout\s*=\s*"\K[^"]+' "$DOTFILES_DIR/hypr/input.lua" 2>/dev/null | head -n1)}"
GENERATED_WESTON_INI="$(mktemp)"
{
    sed "s/__KB_LAYOUT__/${KB_LAYOUT:-us}/" "$REPO_DIR/SDDM/weston.ini"
    for mon in "${CONNECTED_MONITORS[@]}"; do
        [[ -n "$MAIN_MONITOR" && "$mon" != "$MAIN_MONITOR" ]] && printf '\n# Not your main screen: off at the login screen\n[output]\nname=%s\nmode=off\n' "$mon"
    done
} > "$GENERATED_WESTON_INI"
run_cmd "sudo install -Dm644 \"$GENERATED_WESTON_INI\" /etc/sddm/weston.ini"
run_cmd "sudo install -Dm644 \"$REPO_DIR/SDDM/zz-hyprdots-wayland.conf\" /etc/sddm.conf.d/zz-hyprdots-wayland.conf"
run_cmd "sudo install -Dm644 \"$REPO_DIR/SDDM/plymouth-quit-retain-splash.conf\" /etc/systemd/system/plymouth-quit.service.d/10-retain-splash.conf"
run_cmd "sudo systemctl daemon-reload"
rm -f "$GENERATED_WESTON_INI"
log "OK" "Login screen set up on Wayland${MAIN_MONITOR:+ ($MAIN_MONITOR only)}, keyboard ${KB_LAYOUT:-us}."

# Hide unwanted apps from launcher

mark step finish
echo "🔧 Hiding unwanted apps from launcher..."
HIDE_ARGS=(--file "$BASE_DIR/install/hide.txt")
[[ "$DRY_RUN" == "true" ]] && HIDE_ARGS+=(--dry-run)
bash "$BASE_DIR/install/hide.sh" "${HIDE_ARGS[@]}" | tee -a "$LOGFILE" || log "WARN" "Hiding apps failed (run install/hide.sh later)"

# SDDM Configuration

echo "enabling SDDM"
run_cmd "sudo systemctl enable sddm.service"

echo "🎨 Installing SDDM theme..."
run_cmd "sudo mkdir -p /usr/share/sddm/themes/sugar-dark && sudo cp -rT \"$REPO_DIR/SDDM/sugar-dark\" /usr/share/sddm/themes/sugar-dark"
run_cmd "sudo mkdir -p /etc/sddm.conf.d" # Ensure directory exists
run_cmd "sudo cp \"$REPO_DIR/SDDM/sddm.conf\" /etc/sddm.conf.d/sddm.conf"

# Plymouth Configuration

# The theme, the plymouth hook and "quiet splash" on the kernel command line (see install/plymouth.sh)
run_cmd "sudo bash \"$BASE_DIR/install/plymouth.sh\"" || log "WARN" "Boot splash setup failed; run sudo $BASE_DIR/install/plymouth.sh later"

log "INFO" "DaigonStar Hyprdots setup completed."
echo "DaigonStar Hyprdots setup completed."
# The interface offers this on its last screen, so it can be your choice when to leave this session
[[ -z "${HYPRINSTALL_TUI:-}" ]] || exit 0
sleep 3
echo "Restarting SDDM to apply changes..."
sleep 2
run_cmd "sudo systemctl restart sddm"

exit 0
