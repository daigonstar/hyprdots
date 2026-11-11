#!/usr/bin/env bash
# Builds the Rust version of Notes (notes/rs) into ~/.local/lib/hyprdots/hyprdots-notes, only when its source has changed
# since the last build. The installer and update.sh run this. The hyprdots-notes service runs that binary when it is there
# and notes.py when it is not (start.sh), so a failed or skipped build still leaves Notes working.
#   build.sh            build if the source changed, or the binary no longer runs (after a GTK update, say)
#   build.sh --force    build anyway
#   build.sh --remove   remove the binary, so Notes goes back to notes.py
# Restart Notes to use a new build: systemctl --user restart hyprdots-notes
set -uo pipefail
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
src="$here/rs"
dest="${HYPRDOTS_LIB:-$HOME/.local/lib/hyprdots}"
bin="$dest/hyprdots-notes"
stamp="$bin.source"
target="${XDG_CACHE_HOME:-$HOME/.cache}/hyprdots/notes-target"  # outside the repo, so updates never see it

if [[ "${1:-}" == --remove ]]; then
    rm -f "$bin" "$stamp"
    echo "Removed $bin: Notes uses notes.py from its next start"
    exit 0
fi

source_hash() {
    (cd "$src" && find Cargo.toml Cargo.lock src -type f -print0 | sort -z | xargs -0 sha256sum | sha256sum | cut -d' ' -f1)
}
hash="$(source_hash)"
if [[ "${1:-}" != --force && -x "$bin" && "$(cat "$stamp" 2>/dev/null)" == "$hash" ]] && "$bin" --version >/dev/null 2>&1; then
    echo "Notes (Rust) is up to date"
    exit 0
fi
if ! command -v cargo >/dev/null 2>&1; then
    echo "cargo is not installed, so Notes stays on notes.py (install rust, then run $0)" >&2
    exit 1
fi
echo "Building Notes (Rust); the first build takes a few minutes..."
start=$SECONDS
if ! CARGO_TARGET_DIR="$target" cargo build --release --locked --quiet --manifest-path "$src/Cargo.toml"; then
    echo "Could not build Notes (Rust). Notes keeps using $([[ -x "$bin" ]] && echo "the last build" || echo notes.py)" >&2
    exit 1
fi
mkdir -p "$dest"
# Next to the old one, then moved over it: a running copy keeps its file
install -m755 "$target/release/hyprdots-notes" "$bin.new" && mv -f "$bin.new" "$bin" || exit 1
echo "$hash" > "$stamp"
echo "Built Notes (Rust) in $((SECONDS - start)) s: $bin"
