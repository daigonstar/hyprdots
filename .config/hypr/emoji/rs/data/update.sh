#!/usr/bin/env bash
# Remakes emoji.tsv from the latest Unicode emoji list and CLDR keywords. Only needed when a new emoji version comes
# out; the picker itself never downloads anything. Check the diff, then rebuild with ../../build.sh.
set -euo pipefail
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT
cldr="https://raw.githubusercontent.com/unicode-org/cldr-json/main/cldr-json"
curl -sSfo "$tmp/emoji-test.txt" https://unicode.org/Public/emoji/latest/emoji-test.txt
curl -sSfo "$tmp/annotations.json" "$cldr/cldr-annotations-full/annotations/en/annotations.json"
curl -sSfo "$tmp/derived.json" "$cldr/cldr-annotations-derived-full/annotationsDerived/en/annotations.json"
cargo run --quiet --release --manifest-path "$here/../Cargo.toml" --example generate -- \
    "$tmp/emoji-test.txt" "$tmp/annotations.json" "$tmp/derived.json" > "$tmp/emoji.tsv"
mv "$tmp/emoji.tsv" "$here/emoji.tsv"
echo "Wrote $here/emoji.tsv ($(grep -m1 '^# Version' "$tmp/emoji-test.txt"))"
