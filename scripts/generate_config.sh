#!/usr/bin/env bash
# =============================================================================
#  Generate the single ssh config from the SQLite host database.
#
#  Usage:  scripts/generate_config.sh [--db PATH] [--out PATH]
#    --db   the host database   (default: ~/.shellrc/hosts.sqlite)
#    --out  the config to write (default: ~/.ssh/ssh_registry.config)
#
#  The new config is written to a temp file first. Every concrete host in it is
#  checked with `ssh -G` (no connection is opened). Only when every host
#  resolves is it moved into place, so a bad database never replaces a good
#  config. On failure the existing output is left untouched.
#
#  Environment: PYTHON (default: python3, falls back to python).
# =============================================================================
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DB="$HOME/.shellrc/hosts.sqlite"
OUT="$HOME/.ssh/ssh_registry.config"

while [[ $# -gt 0 ]]; do
    case "$1" in
        --db)  DB="$2"; shift ;;
        --out) OUT="$2"; shift ;;
        -h|--help) sed -n '2,15p' "$0"; exit 0 ;;
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

mkdir -p "$(dirname "$OUT")"
TMP="$(mktemp "${OUT}.XXXXXX")"
trap 'rm -f "$TMP"' EXIT

SRC="$REPO/src"
if command -v cygpath >/dev/null 2>&1; then SRC="$(cygpath -m "$SRC")"; fi
PYTHONPATH="$SRC" "$PY" -m ssh_registry.cli generate --db "$DB" --out "$TMP" >/dev/null

# Every literal host name in the generated file must resolve. Patterns with a
# '*' are skipped: they only match when a concrete name is used.
failed=""
count=0
while read -r host; do
    count=$((count + 1))
    if ! ssh -F "$TMP" -G "$host" >/dev/null 2>&1; then
        failed="$failed $host"
    fi
done < <(awk '/^Host /{for (i = 2; i <= NF; i++) if ($i !~ /[*?]/) print $i}' "$TMP" | sort -u)

if [[ -n "$failed" ]]; then
    echo "generate_config: these hosts do not resolve, $OUT left unchanged:$failed" >&2
    exit 1
fi

mv -f "$TMP" "$OUT"
trap - EXIT
echo "generate_config: wrote $OUT ($count hosts checked)"
