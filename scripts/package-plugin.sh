#!/bin/sh
set -eu
cd "$(dirname "$0")/.."
manifest=plugin/.claude-plugin/plugin.json
version=$(sed -n 's/^[[:space:]]*"version"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p' "$manifest" | head -n 1)
case "$version" in
    ''|*[!0-9A-Za-z.-]*)
        echo "Could not read a valid version from $manifest." >&2
        exit 1
        ;;
esac
description_limit=500
description_length=$(python3 -I -c 'import json, sys; print(len(json.load(open(sys.argv[1], encoding="utf-8"))["description"]))' "$manifest") || {
    echo "Could not read the description from $manifest." >&2
    exit 1
}
if [ "$description_length" -gt "$description_limit" ]; then
    echo "The manifest description has $description_length characters; Cowork accepts at most $description_limit. No archive was written." >&2
    exit 1
fi
archive="dist/stock-radar-$version.zip"
file_list=$(mktemp)
trap 'rm -f "$file_list"' EXIT
(
    cd plugin
    git ls-files --cached --others --exclude-standard -- . | LC_ALL=C sort | while IFS= read -r path; do
        if [ -f "$path" ]; then
            printf '%s\n' "$path"
        fi
    done
) > "$file_list"
if ! grep -qx '.claude-plugin/plugin.json' "$file_list"; then
    echo "The manifest is missing from the distributable file list." >&2
    exit 1
fi
if grep -q '^bin/' "$file_list"; then
    echo "A top-level bin/ directory blocks installation in Cowork." >&2
    exit 1
fi
mkdir -p dist
rm -f "$archive"
(cd plugin && zip -X -q "../$archive" -@) < "$file_list"
unzip -l "$archive"
echo "Created $archive"
