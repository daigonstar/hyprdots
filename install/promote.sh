#!/usr/bin/env bash
set -euo pipefail

# promote.sh
# Moves the 'stable' branch, which new installs follow, up to the newest main. Only for a version CI has passed, and
# only forwards. Run it once you have used that version for a while yourself: CI cannot see the desktop.

cd "$(git rev-parse --show-toplevel)"
git fetch -q origin
commit="$(git rev-parse origin/main)"

result="$(gh run list --commit "$commit" --workflow ci.yml --limit 1 --json status,conclusion -q '.[0] | .status + " " + .conclusion')"
if [[ "$result" != "completed success" ]]; then
  echo "Not promoted: CI on ${commit:0:7} says '${result:-no run found}'." >&2
  exit 1
fi

if git rev-parse --verify -q origin/stable >/dev/null; then
  if ! git merge-base --is-ancestor origin/stable "$commit"; then
    echo "Not promoted: stable has commits main does not. Sort that out by hand." >&2
    exit 1
  fi
  range="origin/stable..$commit"
else
  echo "This creates the stable branch."
  range="$commit"
fi

echo "Moving stable to ${commit:0:7}. Everyone on stable gets:"
git log --no-merges -n 40 --format='- %s' "$range"
count="$(git rev-list --no-merges --count "$range")"
(( count > 40 )) && echo "...and $(( count - 40 )) more"
read -rp "Go ahead? [y/N] " answer || answer=""
[[ "$answer" == [yY] ]] || { echo "Not promoted."; exit 1; }
git push origin "$commit:refs/heads/stable"
