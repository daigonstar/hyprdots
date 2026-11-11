#!/usr/bin/env bash
set -euo pipefail

# power.sh
# Installs the service that keeps the CPU, graphics card and RAM inside safe limits (install/power/powerd.py). Run as
# root. The code is copied to /usr/local/lib/hyprdots, so only root can change what runs as root. Safe to run again:
# it only restarts the service when something changed, and it keeps your settings in /etc/hyprdots/power.json.

if [[ $EUID -ne 0 ]]; then
  echo "Run this as root: sudo $0" >&2
  exit 1
fi
src="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/power"
changed=
for pair in "powerd.py:/usr/local/lib/hyprdots/powerd.py:755" "hyprdots-power.service:/etc/systemd/system/hyprdots-power.service:644"; do
  IFS=: read -r name dest mode <<<"$pair"
  if ! cmp -s "$src/$name" "$dest"; then
    install -D -o root -g root -m "$mode" "$src/$name" "$dest"
    changed=1
  fi
done
if [[ -n "$changed" ]]; then
  systemctl daemon-reload
  systemctl enable hyprdots-power.service >/dev/null 2>&1
  systemctl restart hyprdots-power.service
fi
systemctl is-active --quiet hyprdots-power.service || systemctl enable --now hyprdots-power.service
echo "The power service is running. Change it on the Performance page of Settings."
