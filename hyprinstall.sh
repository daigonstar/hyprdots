#!/usr/bin/env bash

#

# hyprinstall-final.sh

# Production-ready Hyprland setup installer

# Options: --dry-run, --verbose

# Logging: ~/.local/share/hyprinstall/hyprinstall.log

set -euo pipefail

# Configuration defaults

DEFAULT_LOG="$HOME/.local/share/hyprinstall/hyprinstall.log"
FALLBACK_LOG="$HOME/hyprinstall.log"
BASE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$BASE_DIR"
DOTFILES_DIR="$REPO_DIR/.config"
REQUIRED_FILE="$BASE_DIR/required.txt"
FLATPAK_FILE="$BASE_DIR/flatpak.txt"
LOGFILE="$DEFAULT_LOG"
EXTRA_DEPENDENCIES=(git base-devel flatpak python rust imagemagick rsync pciutils)

# Parse flags

DRY_RUN=false
VERBOSE=false
for arg in "$@"; do
case "$arg" in
--dry-run) DRY_RUN=true ;;
--verbose) VERBOSE=true ;;
esac
done
# Logging helpers

init_logging() {
if [[ "$DRY_RUN" == "true" ]]; then
echo "[DRY RUN] Would initialize logging to $LOGFILE"
return
fi
if touch "$DEFAULT_LOG" >/dev/null 2>&1; then
LOGFILE="$DEFAULT_LOG"
else
LOGFILE="$FALLBACK_LOG"
mkdir -p "$(dirname "$LOGFILE")"
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

# Script start

init_logging
preflight_checks
log "INFO" "Starting hyprinstall-final. Log: $LOGFILE"

# Branch selection for repo operations (supports UPDATE_BRANCH env var or .update-branch file)
BRANCH="${UPDATE_BRANCH:-}"
if [[ -f "$BASE_DIR/.update-branch" ]]; then
  BRANCH="$(<$BASE_DIR/.update-branch)"
fi
if [[ -z "$BRANCH" && "$DRY_RUN" == "false" && -t 0 ]]; then
  echo "Select branch to use for repo operations:"
  echo "  1) main (end users)"
  echo "  2) dev (development)"
  echo "  3) Enter branch name"
  read -rp "Choice [1-3] (default 2): " _choice
  case "$_choice" in
    1) BRANCH="main" ;;
    3) read -rp "Enter branch name: " BRANCH ;;
    *) BRANCH="dev" ;;
  esac
fi
BRANCH="${BRANCH:-dev}"
log "INFO" "Using branch: $BRANCH"

# If repo exists and is a git repo, attempt to check it out and update to the selected branch
if git -C "$REPO_DIR" rev-parse --git-dir >/dev/null 2>&1; then
  run_cmd "git -C \"$REPO_DIR\" fetch --prune origin"
  # Best-effort checkout and pull; do not abort installer if these fail
  run_cmd "git -C \"$REPO_DIR\" checkout \"$BRANCH\"" || true
  run_cmd "git -C \"$REPO_DIR\" pull --ff-only origin \"$BRANCH\"" || true
fi

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
read_packages_to_array "$FLATPAK_FILE" FLATPAK_PKGS

# Install paru (AUR helper)

install_paru() {
if command -v paru >/dev/null 2>&1; then
log "OK" "paru already installed"
return
fi
run_cmd "sudo pacman -S --needed --noconfirm git base-devel"
local tmpdir
tmpdir="$(mktemp -d)"
run_cmd "git clone https://aur.archlinux.org/paru.git \"$tmpdir/paru\""
pushd "$tmpdir/paru" >/dev/null
run_cmd "makepkg -si --noconfirm"
popd >/dev/null
rm -rf "$tmpdir"
log "OK" "paru installed"
}
install_paru

# Install required packages

install_package_list() {
local pkgs=("$@")
for pkg in "${pkgs[@]:-}"; do
if pacman -Qq "$pkg" &>/dev/null; then
log "OK" "Package $pkg already installed"
elif pacman -Si "$pkg" &>/dev/null; then
log "INFO" "Installing official package: $pkg"
run_cmd "sudo pacman -S --needed --noconfirm \"$pkg\"" ||
  die "Failed to install official package: $pkg. See $LOGFILE for details."
else
if command -v paru >/dev/null 2>&1; then
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
    read -ra GPU_VENDORS <<<"$HYPR_GPU"
    return
  fi

  local gpu_info detected=()
  gpu_info="$(lspci -nn 2>/dev/null | grep -Ei 'vga|3d controller|display controller' || true)"
  grep -qi 'nvidia' <<<"$gpu_info" && detected+=(nvidia)
  grep -qiE 'amd|ati|advanced micro' <<<"$gpu_info" && detected+=(amd)
  grep -qi 'intel' <<<"$gpu_info" && detected+=(intel)

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

select_gpu_vendors
if [[ ${#GPU_VENDORS[@]} -eq 0 ]]; then
  log "WARN" "No GPU drivers selected; skipping GPU packages (Steam and the assistant will run without GPU acceleration)"
fi
for vendor in "${GPU_VENDORS[@]}"; do
  gpu_file="$BASE_DIR/gpu-$vendor.txt"
  if [[ ! -f "$gpu_file" ]]; then
    log "WARN" "No driver list for '$vendor' ($gpu_file); skipping"
    continue
  fi
  log "INFO" "Installing $vendor GPU drivers"
  read_packages_to_array "$gpu_file" GPU_PKGS
  install_package_list "${GPU_PKGS[@]}"
done

install_package_list "${REQUIRED_PKGS[@]}"

# Flatpak installs

run_cmd "flatpak remote-add --if-not-exists flathub https://dl.flathub.org/repo/flathub.flatpakrepo" ||
  die "Failed to configure the Flathub remote. See $LOGFILE for details."

for f in "${FLATPAK_PKGS[@]:-}"; do
if flatpak list --app | grep -qw "$f"; then
log "OK" "Flatpak $f already installed"
else
run_cmd "flatpak install -y --noninteractive --or-update flathub \"$f\"" ||
  die "Failed to install Flatpak: $f. See $LOGFILE for details."
fi
done

# Services needed by the installed apps. ollama is restarted so it picks up
# the GPU backend (ROCm/CUDA/Vulkan) that was installed above.

for svc in NetworkManager bluetooth coolercontrold docker ollama; do
  run_cmd "sudo systemctl enable --now $svc.service" || log "WARN" "Could not enable $svc.service"
done
run_cmd "sudo systemctl restart ollama.service" || log "WARN" "Could not restart ollama.service"

# WinBoat runs Windows in a docker container; the user must be in the docker group
if ! id -nG "$USER" | tr ' ' '\n' | grep -qx docker; then
  run_cmd "sudo usermod -aG docker \"$USER\"" && log "INFO" "Added $USER to the docker group (log out and back in for it to apply)"
fi

# PC assistant models (names come from user_settings.toml)

mapfile -t ASSISTANT_MODELS < <(python3 -c "
import sys
sys.path.insert(0, '$DOTFILES_DIR/hypr/assistant')
import usersettings
s = usersettings.section('assistant', {'model': 'gpt-oss:20b', 'vision_model': 'qwen2.5vl:7b'})
print(s['model']); print(s['vision_model'])" 2>/dev/null)
if [[ ${#ASSISTANT_MODELS[@]} -gt 0 ]] && yesno_prompt "Download the PC assistant's AI models (${ASSISTANT_MODELS[*]}, ~19 GB)?" "Y"; then
  run_cmd "sleep 3"
  for model in "${ASSISTANT_MODELS[@]}"; do
    run_cmd "ollama pull \"$model\"" || log "WARN" "Could not download model $model (run 'ollama pull $model' later)"
  done
fi

# Home directories

run_cmd "mkdir -p \"$HOME/Pictures\" \"$HOME/Videos\" \"$HOME/Documents\" \"$HOME/.config\" \"$HOME/Downloads\""

# Backup existing config (optional)

BACKUP_YES=false
if yesno_prompt "Back up existing config directories?"; then
    BACKUP_DIR="$HOME/.config-backup"
    run_cmd "mkdir -p \"$BACKUP_DIR\""
    BACKUP_YES=true
fi

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
[[ -e "$target" ]] && [[ "$BACKUP_YES" == "true" ]] && run_cmd cp -r "$target" "$BACKUP_DIR/"
run_cmd rm -rf "$target"
run_cmd ln -sfn "$source" "$target"
done

# Add temp monitor and workspace configs (machine-local, gitignored; Lua since the 0.55+ config migration)

run_cmd touch "$HOME/.config/hypr/monitors.lua"
run_cmd touch "$HOME/.config/hypr/workspaces.lua"

# Starship config

starship_file="$HOME/.config/starship.toml"
[[ -e "$starship_file" ]] && run_cmd rm "$starship_file"
run_cmd ln -sfn "$DOTFILES_DIR/starship.toml" "$starship_file"

# Wallpapers

wallpaper_src="$REPO_DIR/wallpapers"
wallpaper_dest="$HOME/Pictures/wallpapers"
[[ -e "$wallpaper_dest" ]] && run_cmd rm -rf "$wallpaper_dest"
[[ -d "$wallpaper_src" ]] && run_cmd cp -r "$wallpaper_src" "$wallpaper_dest"

# Make scripts executable

SCRIPT_FILES=(hypr/scripts/ai.sh hypr/scripts/browser.sh hypr/scripts/gamemode.sh hypr/scripts/game-autoworkspace.py hypr/scripts/ollama.sh hypr/scripts/stop_ollama.sh hypr/scripts/restart.sh hypr/scripts/pywall.sh hypr/scripts/rainbowb.sh hypr/scripts/refresh.sh hypr/scripts/wallust.sh hypr/assistant/hypr_agent.py hypr/assistant/agent_monitor.py waybar/scripts/updates.sh waybar/scripts/popup_calendar.py rofi/powermenu/powermenu.sh rofi/launchers/launcher.sh rofi/launchers/categorized/launcher.sh rofi/launchers/categorized/category-mode.sh rofi/launchers/categorized/applist.sh rofi/cheatsheet/cheatsheet.sh rofi/cheatsheet/generate.sh rofi/wallpaper/wallpaper.sh)
for s in "${SCRIPT_FILES[@]}"; do
sp="$DOTFILES_DIR/$s"
[[ -f "$sp" ]] && run_cmd "chmod +x \"$sp\""
done

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
if [[ -f "$AGENT_MONITOR_SCRIPT" ]]; then
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
run_cmd "sudo cp -r \"$REPO_DIR/icons/Future-cursors\" /usr/share/icons/Future-cursors"
run_cmd "flatpak --user override --filesystem=/home/\"$USER\"/.icons/:ro"
run_cmd "flatpak --user override --filesystem=/usr/share/icons/:ro"
fi

# Bashrc update

BASHRC_MARKER="# --- hyprinstall additions BEGIN ---"
if ! grep -Fq "$BASHRC_MARKER" "$HOME/.bashrc" 2>/dev/null; then
cat >> "$HOME/.bashrc" <<EOF

# --- hyprinstall additions BEGIN ---

alias update='paru -Syu && flatpak update'
alias hyprupdate="$REPO_DIR/update.sh"
eval "$(starship init bash)"
command fastfetch

# --- hyprinstall additions END ---

EOF
log "OK" "Appended hyprinstall additions to ~/.bashrc"
else
log "INFO" "~/.bashrc already contains hyprinstall additions; skipping"
fi

# SDDM: restrict the login greeter to a single monitor
#
# Detect connected outputs via xrandr, ask the user which one is the main
# display, then generate an Xsetup script that sets that output as primary
# and turns every other connected output off for the greeter session only.
# (This has no effect on Hyprland's own monitor layout at session start.)
#
# Output names detected here (Wayland/Xwayland, e.g. "DP-1") are used as-is:
# the SDDM greeter's Xorg modesetting driver uses the same DRM connector names.

echo "🖥️  Configuring SDDM to only show the login screen on your main monitor..."

XSETUP_FILE="/usr/share/sddm/scripts/Xsetup"
XSETUP_TEMPLATE="$REPO_DIR/SDDM/Xsetup"

mapfile -t CONNECTED_MONITORS < <(xrandr --query 2>/dev/null | awk '/ connected/ {print $1}')

if [[ "${#CONNECTED_MONITORS[@]}" -eq 0 ]]; then
    log "WARN" "No connected monitors detected via xrandr; skipping SDDM monitor restriction."
elif [[ "${#CONNECTED_MONITORS[@]}" -eq 1 ]]; then
    log "INFO" "Only one connected monitor (${CONNECTED_MONITORS[0]}); skipping SDDM monitor restriction."
else
    echo "Detected connected monitors:"
    for i in "${!CONNECTED_MONITORS[@]}"; do
        printf "  %d) %s\n" "$((i + 1))" "${CONNECTED_MONITORS[$i]}"
    done

    MAIN_MONITOR=""
    if [[ "$DRY_RUN" == "true" ]]; then
        MAIN_MONITOR="${CONNECTED_MONITORS[0]}"
        echo "[DRY RUN] Would prompt for main monitor; assuming ${MAIN_MONITOR}"
    else
        while [[ -z "$MAIN_MONITOR" ]]; do
            read -rp "Which monitor should show the SDDM login screen (number)? " choice
            if [[ "$choice" =~ ^[0-9]+$ ]] && (( choice >= 1 && choice <= ${#CONNECTED_MONITORS[@]} )); then
                MAIN_MONITOR="${CONNECTED_MONITORS[$((choice - 1))]}"
            else
                echo "Invalid choice, please enter a number between 1 and ${#CONNECTED_MONITORS[@]}."
            fi
        done
    fi

    log "INFO" "Selected '$MAIN_MONITOR' as the main monitor for SDDM."

    XRANDR_BLOCK="xrandr --output $MAIN_MONITOR --primary --auto"
    for mon in "${CONNECTED_MONITORS[@]}"; do
        if [[ "$mon" != "$MAIN_MONITOR" ]]; then
            XRANDR_BLOCK+=$'\n'"xrandr --output $mon --off"
        fi
    done

    GENERATED_XSETUP="$(mktemp)"
    awk -v block="$XRANDR_BLOCK" '{
        if ($0 ~ /__HYPRINSTALL_XRANDR_BLOCK__/) print block
        else print
    }' "$XSETUP_TEMPLATE" > "$GENERATED_XSETUP"

    run_cmd "sudo cp \"$XSETUP_FILE\" \"$XSETUP_FILE.bak\" 2>/dev/null || true"
    run_cmd "sudo cp \"$GENERATED_XSETUP\" \"$XSETUP_FILE\""
    run_cmd "sudo chmod +x \"$XSETUP_FILE\""
    rm -f "$GENERATED_XSETUP"
    log "OK" "SDDM Xsetup configured: '$MAIN_MONITOR' primary, others disabled at greeter (backup at $XSETUP_FILE.bak)."
fi

# Hide unwanted apps from launcher

echo "🔧 Hiding unwanted apps from launcher..."
APPS_FILE="$REPO_DIR/hide.txt"

if [[ ! -f "$APPS_FILE" ]]; then
    echo "❌ App list file not found: $APPS_FILE. Skipping app hiding."
else
  while IFS= read -r app; do
      [[ -z "$app" || "$app" =~ ^# ]] && continue
      desktop_file="/usr/share/applications/$app.desktop"
      user_desktop_file="$HOME/.local/share/applications/$app.desktop"

      echo "Processing app '$app' for hiding..."
      if [[ -f "$desktop_file" ]]; then
          run_cmd "mkdir -p \"$HOME/.local/share/applications\""
          run_cmd "cp \"$desktop_file\" \"$user_desktop_file\""
          if grep -q '^NoDisplay=true' "$user_desktop_file"; then
              echo "✅ App '$app' is already hidden."
          else
              echo "Hiding '$app.desktop'"
              run_cmd "echo \"NoDisplay=true\" >> \"$user_desktop_file\""
          fi
      else
          echo "Could not find desktop file: '$desktop_file', skipping hiding for '$app'."
      fi
  done < "$APPS_FILE"
fi

#Git Setup



# SDDM Configuration

echo "enabling SDDM"
run_cmd "sudo systemctl enable sddm.service"

echo "🎨 Installing SDDM theme..."
run_cmd "sudo cp -R $REPO_DIR/SDDM/sugar-dark /usr/share/sddm/themes"
run_cmd "sudo mkdir -p /etc/sddm.conf.d" # Ensure directory exists
run_cmd "sudo cp $REPO_DIR/SDDM/sddm.conf /etc/sddm.conf.d/sddm.conf"

# Plymouth Configuration

run_cmd "sudo git clone https://github.com/krishnan793/PlymouthTheme-Cat.git /usr/share/plymouth/themes/PlymouthTheme-Cat"
run_cmd "sudo plymouth-set-default-theme PlymouthTheme-Cat -R"

log "INFO" "DaigonStar Hyprdots setup completed."
echo "DaigonStar Hyprdots setup completed."
sleep 3
echo "Restarting SDDM to apply changes..."
sleep 2
run_cmd "sudo systemctl restart sddm"

exit 0
