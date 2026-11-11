#!/usr/bin/env bash
# What the hyprdots-notes service runs: the Rust build when it is installed (build.sh puts it there), notes.py otherwise.
# HYPRDOTS_NOTES=python picks notes.py anyway: systemctl --user set-environment HYPRDOTS_NOTES=python, then restart it.
bin="${HYPRDOTS_LIB:-$HOME/.local/lib/hyprdots}/hyprdots-notes"
if [[ "${HYPRDOTS_NOTES:-}" != python && -x "$bin" ]]; then
    exec "$bin"
fi
exec /usr/bin/python3 "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)/notes.py"
