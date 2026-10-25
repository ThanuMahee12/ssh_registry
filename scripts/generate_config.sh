#!/usr/bin/env bash
# =============================================================================
#  Generate the ssh configs from the SQLite host database.
#
#  Usage:  scripts/generate_config.sh [--db PATH] [--dir PATH]
#    --db   the host database   (default: ~/.shellrc/hosts.sqlite)
#    --dir  the output directory (default: ~/.shellrc)
#
#  Writes cw.config, personal.config, shared.config and shellrc.config.
#  shellrc.config is what ~/.ssh/config should Include.
#
#  The new files are written to a temp directory first. Every literal host in
#  the combined result is checked with `ssh -G` (no connection is opened). Only
#  when every host resolves are the files moved into place, so a bad database
#  never replaces a good config.
#
#  Environment: PYTHON (default: python3, falls back to python).
# =============================================================================
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DB="$HOME/.shellrc/hosts.sqlite"
DIR="$HOME/.shellrc"

while [[ $# -gt 0 ]]; do
    case "$1" in
        --db)  DB="$2"; shift ;;
        --dir) DIR="$2"; shift ;;
        -h|--help) sed -n '2,17p' "$0"; exit 0 ;;
        *) echo "unknown argument: $1" >&2; exit 2 ;;
    esac
    shift
done

if [[ ! -f "$DB" ]]; then
    echo "generate_config: no database at $DB" >&2
    echo "  create it once with: python -m ssh_registry.cli convert --db \"$DB\"" >&2
    exit 1
fi

if [[ -n "${PYTHON:-}" ]]; then
    PY="$PYTHON"
elif command -v python3 >/dev/null 2>&1; then
    PY=python3
else
    PY=python
fi

SRC="$REPO/src"
if command -v cygpath >/dev/null 2>&1; then SRC="$(cygpath -m "$SRC")"; fi

STAGE="$(mktemp -d)"
trap 'rm -rf "$STAGE"' EXIT

PYTHONPATH="$SRC" "$PY" -m ssh_registry.cli generate --db "$DB" --dir "$STAGE" >/dev/null

# Check the combined content, in the order ~/.ssh/config will read it. Include
# paths point at the real directory, so the check uses the staged files directly.
COMBINED="$STAGE/combined.check"
cat "$STAGE/cw.config" "$STAGE/personal.config" "$STAGE/shared.config" > "$COMBINED"

failed=""
count=0
while read -r host; do
    count=$((count + 1))
    if ! ssh -F "$COMBINED" -G "$host" >/dev/null 2>&1; then
        failed="$failed $host"
    fi
done < <(awk '/^Host /{for (i = 2; i <= NF; i++) if ($i !~ /[*?]/) print $i}' "$COMBINED" | sort -u)

if [[ -n "$failed" ]]; then
    echo "generate_config: these hosts do not resolve, $DIR left unchanged:$failed" >&2
    exit 1
fi

mkdir -p "$DIR"
for f in cw.config personal.config shared.config shellrc.config; do
    mv -f "$STAGE/$f" "$DIR/$f"
done
echo "generate_config: wrote $DIR (cw, personal, shared, shellrc.config; $count hosts checked)"
echo "  to use it, ~/.ssh/config must include: Include ~/.shellrc/shellrc.config"
