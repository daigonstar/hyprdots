#!/usr/bin/env bash
#
# Sets up the PC assistant: choose a model size that suits your hardware, or turn the
# assistant off. Safe to re-run any time to switch models or enable/disable it.
#
# Usage: setup.sh                      interactive menu (recommends a tier for your GPU)
#        setup.sh --none               turn the assistant off (nothing is deleted)
#        setup.sh --tier full|balanced|light|auto
#        setup.sh --model NAME [--vision-model NAME|same|none]
# Options: --no-pull  --no-packages  --no-services  --no-search  --yes  --dry-run
# Unattended: HYPR_ASSISTANT=none|auto|full|balanced|light
#
# The choice is saved in user_settings.local.toml ([assistant] model, vision_model). That
# file is git-ignored, so it stays per machine.
#
# Web search: when Docker or Podman is available, a private SearXNG search service is started on
# 127.0.0.1:8888 (only this PC can reach it; about 150 MB RAM, idle CPU). Public search engines block
# the assistant, so this makes its research far better. Skip it with --no-search.
set -euo pipefail

ASSIST_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
HYPR_DIR="$(dirname "$ASSIST_DIR")"
LOCAL_SETTINGS="${ASSISTANT_LOCAL_SETTINGS:-$HYPR_DIR/user_settings.local.toml}"
STATE_DIR="${XDG_STATE_HOME:-$HOME/.local/state}/hypr_agent"
DISABLED_MARKER="$STATE_DIR/disabled"

DRY_RUN=false PULL=true PACKAGES=true SERVICES=true SEARCH=true ASSUME_YES=false
SEARXNG_PORT="${SEARXNG_PORT:-8888}"
SEARXNG_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/searxng"
TIER="${HYPR_ASSISTANT:-}" MODEL="" VISION="" VISION_SET=false
while [[ $# -gt 0 ]]; do
  case "$1" in
    --none) TIER=none ;;
    --tier) TIER="${2:?--tier needs a value}"; shift ;;
    --model) MODEL="${2:?--model needs a name}"; TIER=custom; shift ;;
    --vision-model) VISION="${2:?--vision-model needs a name, 'same' or 'none'}"; VISION_SET=true; shift ;;
    --no-pull) PULL=false ;;
    --no-packages) PACKAGES=false ;;
    --no-services) SERVICES=false ;;
    --no-search) SEARCH=false ;;
    --yes|-y) ASSUME_YES=true ;;
    --dry-run) DRY_RUN=true ;;
    -h|--help) sed -n 2,18p "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "Unknown option: $1" >&2; exit 2 ;;
  esac
  shift
done

step() { printf '\n==> %s\n' "$*"; }
warn() { printf 'WARN: %s\n' "$*" >&2; }
run() { if $DRY_RUN; then printf '[dry-run] %s\n' "$*"; else "$@"; fi; }
interactive() { [[ -t 0 && -t 1 ]] && ! $ASSUME_YES; }

# --- Hardware ----------------------------------------------------------------
gpu_vendor() {
  local info
  info="$(lspci -nn 2>/dev/null | grep -Ei 'vga|3d controller|display controller' || true)"
  if grep -qi nvidia <<<"$info"; then echo nvidia
  elif grep -qiE 'amd|ati|advanced micro' <<<"$info"; then echo amd
  elif grep -qi intel <<<"$info"; then echo intel
  else echo none; fi
}

vram_mib() {  # largest GPU memory in MiB, 0 when unknown
  local best=0 value f
  if command -v nvidia-smi >/dev/null 2>&1; then
    value="$(nvidia-smi --query-gpu=memory.total --format=csv,noheader,nounits 2>/dev/null | sort -n | tail -1 || true)"
    [[ "$value" =~ ^[0-9]+$ ]] && best=$value
  fi
  for f in /sys/class/drm/card*/device/mem_info_vram_total; do
    [[ -r "$f" ]] || continue
    value=$(( $(cat "$f") / 1048576 ))
    (( value > best )) && best=$value
  done
  echo "$best"
}

ram_mib() { awk '/MemTotal/ {printf "%d", $2/1024}' /proc/meminfo; }

recommend_tier() {
  local vram="$1"
  if (( vram >= 14000 )); then echo full
  elif (( vram >= 7000 )); then echo balanced
  else echo light; fi
}

# --- Tiers -------------------------------------------------------------------
# name | chat model | vision model ("" = none) | download | memory needed
tier_info() {
  case "$1" in
    full)     echo "gpt-oss:20b|qwen2.5vl:7b|~19 GB|16 GB GPU memory" ;;
    balanced) echo "qwen3:8b|qwen2.5vl:3b|~8 GB|8 GB GPU memory" ;;
    light)    echo "qwen3:4b||~3 GB|4 GB GPU memory (or CPU only, slowly)" ;;
    *) return 1 ;;
  esac
}

choose_interactively() {
  local vram ram vendor rec pick
  vram="$(vram_mib)"; ram="$(ram_mib)"; vendor="$(gpu_vendor)"
  rec="$(recommend_tier "$vram")"
  echo "The PC assistant is an optional AI helper that runs locally through Ollama."
  echo "It needs a decent GPU; skip it if your machine is modest. Nothing is sent to the cloud."
  echo
  echo "Detected: GPU $vendor, $(( (vram + 512) / 1024 )) GB GPU memory, $(( (ram + 512) / 1024 )) GB RAM"
  (( vram == 0 )) && echo "No GPU memory found: models would run on the CPU, which is slow."
  echo
  local tier line chat vision size need mark
  for tier in full balanced light; do
    line="$(tier_info "$tier")"; IFS='|' read -r chat vision size need <<<"$line"
    mark=""; [[ "$tier" == "$rec" ]] && mark="  <- recommended"
    printf '  %-9s chat %-12s vision %-14s %s, needs %s%s\n' "$tier" "$chat" "${vision:-none}" "$size" "$need" "$mark"
  done
  echo "  custom    pick your own Ollama models"
  echo "  none      no assistant (you can enable it later with this script)"
  echo "The assistant is tuned for gpt-oss (full); smaller models are less reliable with tools."
  echo
  read -rp "Choice [$rec]: " pick
  TIER="${pick:-$rec}"
}

resolve_choice() {
  [[ "$TIER" == auto ]] && TIER="$(recommend_tier "$(vram_mib)")"
  case "$TIER" in
    none) return 0 ;;
    full|balanced|light)
      IFS='|' read -r CHAT_MODEL VISION_MODEL _ _ <<<"$(tier_info "$TIER")"
      ;;
    custom)
      CHAT_MODEL="$MODEL"; VISION_MODEL=""
      if [[ -z "$CHAT_MODEL" ]]; then
        read -rp "Chat model (an Ollama name, e.g. qwen3:8b): " CHAT_MODEL
      fi
      if ! $VISION_SET && interactive; then
        read -rp "Vision model for screenshots: a model name, 'same' if the chat model can see images (e.g. qwen3.5), or Enter for none: " VISION
        VISION_SET=true
      fi
      ;;
    *) echo "Unknown tier '$TIER' (use full, balanced, light, auto, custom or none)." >&2; exit 2 ;;
  esac
  if $VISION_SET; then
    [[ "$VISION" == none ]] && VISION=""
    VISION_MODEL="$VISION"
  fi
  [[ "$TIER" == none || -n "${CHAT_MODEL:-}" ]] || { echo "A chat model is required." >&2; exit 2; }
}

# --- Settings ----------------------------------------------------------------
set_local() {  # set_local key value [key value...]: writes [assistant] entries, keeping everything else
  if $DRY_RUN; then
    echo "[dry-run] would set in $LOCAL_SETTINGS: [assistant] $*"
    return
  fi
  LOCAL="$LOCAL_SETTINGS" python3 - "$@" <<'PY'
import json, os, sys
from pathlib import Path

path = Path(os.environ["LOCAL"])
pairs = sys.argv[1:]
values = dict(zip(pairs[::2], pairs[1::2]))
lines = path.read_text().splitlines() if path.exists() else []

start = next((i for i, l in enumerate(lines) if l.strip() == "[assistant]"), None)
if start is None:
    if lines and lines[-1].strip():
        lines.append("")
    lines.append("[assistant]")
    start = len(lines) - 1
end = next((i for i in range(start + 1, len(lines)) if lines[i].lstrip().startswith("[")), len(lines))
for key, value in values.items():
    entry = f"{key} = {json.dumps(value)}"
    for i in range(start + 1, end):
        if lines[i].split("=", 1)[0].strip() == key:
            lines[i] = entry
            break
    else:
        lines.insert(start + 1, entry)
        end += 1
path.parent.mkdir(parents=True, exist_ok=True)
path.write_text("\n".join(lines) + "\n")
path.chmod(0o600)
PY
}

write_settings() {
  set_local model "$CHAT_MODEL" vision_model "$VISION_MODEL"
  $DRY_RUN || echo "Saved your model choice in $LOCAL_SETTINGS"
}

# --- Packages and services ---------------------------------------------------
install_packages() {
  command -v pacman >/dev/null 2>&1 || { warn "Not an Arch system: install ollama and the python ollama module yourself."; return; }
  local pkgs=() ollama_pkg
  if ! command -v ollama >/dev/null 2>&1; then
    case "$(gpu_vendor)" in
      nvidia) ollama_pkg=ollama-cuda ;;
      amd) ollama_pkg=ollama-rocm ;;
      intel) ollama_pkg=ollama-vulkan ;;
      *) ollama_pkg=ollama ;;
    esac
    pkgs+=("$ollama_pkg")
  fi
  local p
  for p in python-ollama python-prompt_toolkit; do
    pacman -Qq "$p" >/dev/null 2>&1 || pkgs+=("$p")
  done
  if ((${#pkgs[@]})); then
    echo "Installing: ${pkgs[*]}"
    run paru -S --needed --noconfirm "${pkgs[@]}" || warn "Could not install ${pkgs[*]}"
  else
    echo "ollama and its Python modules are already installed."
  fi
}

start_ollama() {
  command -v ollama >/dev/null 2>&1 || $DRY_RUN || { warn "ollama is not installed; skipping the service and the model download."; return 1; }
  if command -v systemctl >/dev/null 2>&1; then
    run sudo systemctl enable --now ollama.service || warn "Could not enable ollama.service"
  fi
  $DRY_RUN && return 0
  local i
  for i in $(seq 1 20); do
    curl -fsS --max-time 2 "${OLLAMA_HOST:-http://127.0.0.1:11434}/api/tags" >/dev/null 2>&1 && return 0
    sleep 1
  done
  warn "Ollama did not respond; run 'ollama pull <model>' later."
  return 1
}

pull_model() {
  local name="$1"
  [[ -n "$name" ]] || return 0
  if ! $DRY_RUN && ollama list 2>/dev/null | awk 'NR>1 {print $1}' | grep -qxF "$name"; then
    echo "$name is already downloaded."
  else
    run ollama pull "$name" || warn "Could not download $name; run 'ollama pull $name' later."
  fi
}

# --- Web search (SearXNG) ---------------------------------------------------
container_tool() {  # docker or podman that this user can actually run, else nothing
  if command -v docker >/dev/null 2>&1 && docker info >/dev/null 2>&1; then echo docker
  elif command -v podman >/dev/null 2>&1; then echo podman
  fi
}

searxng_config() {
  cat <<EOF
# SearXNG for the Hyprland assistant: private, only reachable from this PC.
use_default_settings: true
general:
  instance_name: "hyprdots search"
server:
  secret_key: "$(python3 -c 'import secrets; print(secrets.token_hex(32))')"
  limiter: false        # only this PC uses it, so no rate limiting
  image_proxy: false
search:
  safe_search: 0
  formats:
    - html
    - json              # the assistant reads results as JSON
EOF
}

setup_search() {
  local tool url="http://127.0.0.1:$SEARXNG_PORT"
  tool="$(container_tool)"
  if [[ -z "$tool" ]]; then
    if command -v docker >/dev/null 2>&1; then
      warn "Docker is installed but you cannot use it (add yourself to the docker group, log out and in, then re-run this script)."
    else
      echo "Skipping private web search: install docker or podman and re-run this script to add it."
    fi
    return 0
  fi
  step "Private web search: SearXNG with $tool on $url"
  if [[ ! -e "$SEARXNG_DIR/settings.yml" ]]; then  # never overwrite your own SearXNG config
    run mkdir -p "$SEARXNG_DIR"
    $DRY_RUN || (umask 077; searxng_config > "$SEARXNG_DIR/settings.yml")
  fi
  if $DRY_RUN; then
    echo "[dry-run] would start the searxng container on 127.0.0.1:$SEARXNG_PORT"
  elif "$tool" container inspect searxng >/dev/null 2>&1; then
    "$tool" start searxng >/dev/null || { warn "Could not start the existing searxng container."; return 0; }
  else
    "$tool" pull -q docker.io/searxng/searxng:latest >/dev/null || { warn "Could not download SearXNG; web search stays on the public engines."; return 0; }
    "$tool" run -d --name searxng --restart unless-stopped -p "127.0.0.1:$SEARXNG_PORT:8080" \
      -v "$SEARXNG_DIR:/etc/searxng:rw" docker.io/searxng/searxng:latest >/dev/null \
      || { warn "Could not start SearXNG (is port $SEARXNG_PORT in use?)."; return 0; }
    # Podman only honours --restart after a reboot when its restart service is enabled
    if [[ "$tool" == podman ]]; then systemctl --user enable --now podman-restart.service >/dev/null 2>&1 || true; fi
  fi
  if ! $DRY_RUN; then
    local i ready=false
    for i in $(seq 1 30); do
      if curl -fsS --max-time 3 "$url/search?q=test&format=json" >/dev/null 2>&1; then ready=true; break; fi
      sleep 1
    done
    $ready || { warn "SearXNG did not answer on $url; check '$tool logs searxng'."; return 0; }
  fi
  set_local searxng_url "$url"
  echo "Web search runs through your own SearXNG. Remove it any time with: $tool rm -f searxng"
}

install_context() {  # your machine context: copied from the template once, never overwritten
  local example="$ASSIST_DIR/agent_context.example.md" mine="$ASSIST_DIR/agent_context.md"
  [[ -f "$example" && ! -e "$mine" ]] || return 0
  run cp "$example" "$mine"
  echo "Created $mine from the template. Edit it to describe your hardware and setup (git-ignored)."
}

reload_waybar() {
  $DRY_RUN && return
  pgrep -x waybar >/dev/null 2>&1 && pkill -SIGUSR2 waybar 2>/dev/null || true
}

# --- Main --------------------------------------------------------------------
if [[ -z "$TIER" ]]; then
  if interactive; then choose_interactively; else TIER=auto; fi
fi
CHAT_MODEL="${MODEL:-}" VISION_MODEL=""
resolve_choice

if [[ "$TIER" == none ]]; then
  step "Turning the PC assistant off"
  run mkdir -p "$STATE_DIR"
  run touch "$DISABLED_MARKER"
  reload_waybar
  echo "The assistant button and Super+C do nothing now. Models and packages were left alone."
  echo "Turn it back on with: $ASSIST_DIR/setup.sh"
  exit 0
fi

step "Assistant models: chat ${CHAT_MODEL}, vision ${VISION_MODEL:-none}"
$PACKAGES && install_packages
write_settings
install_context
run rm -f "$DISABLED_MARKER"
if $SERVICES && $PULL; then
  if start_ollama; then
    pull_model "$CHAT_MODEL"
    pull_model "$VISION_MODEL"
  fi
elif $SERVICES; then
  start_ollama || true
fi
$SERVICES && $SEARCH && setup_search
reload_waybar
step "Done. Press Super+C or click the assistant button in the bar."
