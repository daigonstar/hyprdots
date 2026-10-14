#!/usr/bin/env bash
#
# Checks that every package the installer asks for still exists: official repos first, then the
# AUR, and every Flatpak on Flathub. Exits 1 and lists what is missing. Needs pacman (with synced
# databases), curl and network access. CI runs it weekly so a deleted AUR package is noticed early.
set -uo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")" || exit 1

read_list() { grep -hvE '^\s*(#|$)' "$@" | sed 's/[[:space:]].*//' | sort -u; }

missing=()
aur_candidates=()
while read -r pkg; do
  pacman -Si "$pkg" >/dev/null 2>&1 || aur_candidates+=("$pkg")
done < <(read_list required.txt gpu-*.txt)

if ((${#aur_candidates[@]})); then
  query=""
  for pkg in "${aur_candidates[@]}"; do query+="&arg[]=$pkg"; done
  found="$(curl -fsS --max-time 30 "https://aur.archlinux.org/rpc/v5/info?${query#&}" | python3 -c '
import json, sys
print("\n".join(r["Name"] for r in json.load(sys.stdin).get("results", [])))')" || { echo "Could not query the AUR" >&2; exit 2; }
  for pkg in "${aur_candidates[@]}"; do
    grep -qxF "$pkg" <<<"$found" || missing+=("package: $pkg")
  done
fi

while read -r app; do
  code="$(curl -s -o /dev/null -w '%{http_code}' --max-time 20 "https://flathub.org/api/v2/appstream/$app")"
  [[ "$code" == 200 ]] || missing+=("flatpak: $app (HTTP $code)")
done < <(read_list flatpak.txt)

if ((${#missing[@]})); then
  printf 'Missing:\n'; printf '  %s\n' "${missing[@]}"
  exit 1
fi
echo "All packages found: ${#aur_candidates[@]} from the AUR, the rest in the official repos, and every Flatpak on Flathub."
