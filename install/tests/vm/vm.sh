#!/usr/bin/env bash
set -euo pipefail

# vm.sh
# A blank Arch virtual machine for testing a real install. Needs qemu and KVM, not sudo.
# Usage: vm.sh test [--local] | fresh | start | stop | ssh [command] | screenshot FILE | key KEYS...
#   test: the whole thing on a blank disk: the real installer, a reboot, a login, checks, then a second login. --local
#   puts your uncommitted changes on top of what it clones. About 15 minutes, and it downloads several GB.
# Everything lives in ~/.cache/hyprdots-vm. The base image is Arch's own and stays untouched: fresh copies it.

dir="${HYPRDOTS_VM_DIR:-$HOME/.cache/hyprdots-vm}"
mirror="https://geo.mirror.pkgbuild.com/images/latest"
image="${HYPRDOTS_VM_IMAGE:-Arch-Linux-x86_64-basic-20261101.620452.qcow2}"
port="${HYPRDOTS_VM_PORT:-2222}"
monitor="$dir/monitor.sock"
ssh_opts=(-o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o LogLevel=ERROR -o ConnectTimeout=5 -p "$port" -i "$dir/key")

monitor_cmd() { printf '%s\n' "$1" | socat - "UNIX-CONNECT:$monitor" >/dev/null; }

fetch() {
  mkdir -p "$dir"
  if [[ ! -f "$dir/$image" ]]; then
    curl -fL --retry 3 -o "$dir/$image.part" "$mirror/$image"
    curl -fsSL -o "$dir/$image.SHA256" "$mirror/$image.SHA256"
    (cd "$dir" && sed "s/  .*/  $image.part/" "$image.SHA256" | sha256sum -c -)
    mv "$dir/$image.part" "$dir/$image"
  fi
  [[ -f "$dir/key" ]] || ssh-keygen -q -t ed25519 -N '' -f "$dir/key"
}

start() {
  [[ -f "$dir/disk.qcow2" ]] || { echo "No disk: run $0 fresh" >&2; exit 1; }
  # A real GPU for Hyprland needs the packages qemu-hw-display-virtio-vga-gl and qemu-ui-egl-headless; the plain card does for an install
  local graphics=(-vga std -display none)
  if [[ -e /usr/lib/qemu/hw-display-virtio-vga-gl.so && -e /usr/lib/qemu/ui-egl-headless.so ]]; then
    graphics=(-device virtio-vga-gl -display egl-headless,gl=on)
  fi
  qemu-system-x86_64 -machine q35 -enable-kvm -cpu host -smp 8 -m 8G -daemonize -pidfile "$dir/pid" \
    -drive "file=$dir/disk.qcow2,if=virtio" \
    "${graphics[@]}" \
    -nic "user,model=virtio-net-pci,hostfwd=tcp:127.0.0.1:$port-:22" \
    -monitor "unix:$monitor,server,nowait" -serial "file:$dir/serial.log"
}

stop() {
  [[ -f "$dir/pid" ]] && kill "$(cat "$dir/pid")" 2>/dev/null || true
  rm -f "$dir/pid"
}

# The image's user is arch, password arch: published by Arch, and only reachable from this PC
install_key() {
  local ask="$dir/askpass"
  printf '#!/bin/sh\necho arch\n' > "$ask"
  chmod 700 "$ask"
  for _ in $(seq 60); do
    if SSH_ASKPASS="$ask" SSH_ASKPASS_REQUIRE=force setsid -w ssh "${ssh_opts[@]}" -o PreferredAuthentications=password arch@127.0.0.1 \
        "mkdir -p ~/.ssh && chmod 700 ~/.ssh && cat >> ~/.ssh/authorized_keys" < "$dir/key.pub" 2>/dev/null; then
      return 0
    fi
    sleep 3
  done
  echo "The VM did not answer on ssh." >&2
  exit 1
}

vm() { ssh "${ssh_opts[@]}" arch@127.0.0.1 "$@"; }
vm_env='export HYPRLAND_INSTANCE_SIGNATURE=$(ls -t /run/user/1000/hypr | head -1) XDG_RUNTIME_DIR=/run/user/1000 WAYLAND_DISPLAY=wayland-1;'
failures=0
check() {  # check "what" "command in the VM that must succeed"
  if vm "$vm_env $2" >/dev/null 2>&1; then echo "  ok    $1"; else echo "  FAIL  $1"; failures=$((failures + 1)); fi
}

wait_for_ssh() {
  sleep 20
  for _ in $(seq 40); do vm true 2>/dev/null && return 0; sleep 5; done
  echo "The VM did not come back." >&2
  exit 1
}

# Like a new PC: a user in wheel whose sudo asks for a password. Then the full-screen installer with its default answers.
run_installer() {
  vm 'sudo pacman -Syu --noconfirm --needed git tmux >/dev/null && sudo usermod -aG wheel arch &&
      echo "%wheel ALL=(ALL:ALL) ALL" | sudo tee /etc/sudoers.d/10-wheel >/dev/null && sudo chmod 440 /etc/sudoers.d/10-wheel &&
      git clone -q https://github.com/daigonstar/hyprdots ~/hyprdots && sudo rm /etc/sudoers.d/arch'
  if [[ "${1:-}" == "--local" ]]; then
    local repo
    repo="$(git -C "$(dirname "$0")" rev-parse --show-toplevel)"
    git -C "$repo" diff HEAD | vm 'cd ~/hyprdots && git apply'
    git -C "$repo" ls-files -oz --exclude-standard | tar -C "$repo" --null -T - -cf - | vm 'tar -C ~/hyprdots -xf -'
  fi
  vm 'tmux new -d -s i -x 120 -y 40 "cd ~/hyprdots && ./hyprinstall.sh; exec bash"'
  local screen prompts=0 started=false waited=0
  while :; do
    screen="$(vm 'tmux capture-pane -p -t i' 2>/dev/null || true)"
    if [[ "$started" == false ]] && grep -q 'password for arch:' <<<"$screen" && ! grep -q 'Sorry' <<<"$screen"; then
      vm 'tmux send-keys -t i arch Enter'
      echo "  note  it asked for the password in the terminal before the interface started"
      sleep 15
    elif [[ "$started" == false ]] && grep -q 'Step 1 of 8' <<<"$screen"; then
      vm 'for i in 1 2 3 4 5 6 7 8; do tmux send-keys -t i Enter; sleep 0.8; done'
      started=true
    elif grep -q 'needs your password' <<<"$screen"; then
      prompts=$((prompts + 1))
      vm 'tmux send-keys -t i arch Enter'
    elif grep -qE 'The install stopped|Failed to obtain' <<<"$screen" || (( waited > 240 )); then
      echo "$screen" >&2
      echo "  FAIL  the installer did not finish" >&2
      exit 1
    elif grep -q 'setup completed' <<<"$screen"; then
      break
    fi
    sleep 5
    waited=$((waited + 1))
  done
  echo "  ok    the installer finished, asking for the password $prompts time(s)"
  vm 'tmux send-keys -t i Enter; sleep 1; echo arch | sudo -S -p "" systemctl reboot' || true
  wait_for_ssh
}

log_in() {
  sleep 5
  "$0" key a r c h ret
  sleep 25
}

desktop_checks() {
  check "no config errors" '[ -z "$(hyprctl configerrors | tr -d "[:space:]")" ]'
  check "keybinds loaded" '[ "$(hyprctl binds -j | grep -c modmask)" -gt 50 ]'
  check "background parts running" 'systemctl --user is-active waybar swaync hypridle hyprdots-tray hyprdots-usb'
  check "nothing failed" '[ -z "$(systemctl --user --failed --no-legend)" ]'
  check "a wallpaper is showing" 'awww query | grep -q image:'
  check "bar showing" 'hyprctl layers | grep -q waybar'
  check "safe mode has copies" '[ "$(ls ~/.local/state/hyprdots/last_good | wc -l)" -gt 5 ]'
  check "sound running" 'wpctl status'
}

case "${1:-}" in
  test)
    "$0" fresh
    run_installer "${2:-}"
    log_in
    echo "First login:"
    desktop_checks
    check "the welcome opens" 'hyprctl clients | grep -q com.hyprdots.welcome'
    "$0" screenshot "$dir/first-login.png"
    vm "$vm_env hyprctl dispatch 'hl.dsp.exit()'" || true
    sleep 8
    log_in
    echo "Second login:"
    desktop_checks
    check "the welcome stays away" '! hyprctl clients | grep -q com.hyprdots.welcome'
    "$0" screenshot "$dir/second-login.png"
    echo "Failures: $failures. Screenshots are in $dir"
    exit $(( failures > 0 ))
    ;;
  fresh)
    stop
    fetch
    cp "$dir/$image" "$dir/disk.qcow2"
    start
    install_key
    echo "Fresh VM is up: $0 ssh"
    ;;
  start) start ;;
  stop) stop ;;
  ssh) shift; exec ssh "${ssh_opts[@]}" arch@127.0.0.1 "$@" ;;
  screenshot) monitor_cmd "screendump $2.ppm"; sleep 1; magick "$2.ppm" "$2" 2>/dev/null || python3 -c "from PIL import Image; import sys; Image.open(sys.argv[1]).save(sys.argv[2])" "$2.ppm" "$2"; rm -f "$2.ppm" ;;
  key) shift; for k in "$@"; do monitor_cmd "sendkey $k"; sleep 0.15; done ;;
  *) sed -n 6,8p "$0"; exit 2 ;;
esac
