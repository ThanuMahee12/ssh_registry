# shellcheck shell=bash
# Read ssh_registry settings: settings.toml next to this repo, overridden by
# ~/.config/ssh_registry/settings.toml. Handles the subset of TOML the file
# uses: [section] headers, key = "string" | number | true/false, # comments.
#
#   . lib/settings.sh
#   bucket=$(registry_setting source bucket)

REGISTRY_DIR="${REGISTRY_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"

_registry_toml_get() { # file section key
    [[ -f "$1" ]] || return 1
    awk -v want_s="$2" -v want_k="$3" '
        { sub(/\r$/, "") }
        /^[[:space:]]*(#|$)/ { next }
        /^[[:space:]]*\[/ {
            s = $0; gsub(/^[[:space:]]*\[[[:space:]]*|[[:space:]]*\][[:space:]]*(#.*)?$/, "", s)
            next
        }
        s == want_s {
            line = $0
            k = line; sub(/[[:space:]]*=.*/, "", k); gsub(/^[[:space:]]+/, "", k)
            if (k != want_k) next
            v = line; sub(/^[^=]*=[[:space:]]*/, "", v)
            if (v ~ /^"/) { sub(/^"/, "", v); sub(/"[[:space:]]*(#.*)?$/, "", v) }
            else          { sub(/[[:space:]]*(#.*)?$/, "", v) }
            print v; found = 1; exit
        }
        END { exit !found }
    ' "$1"
}

# registry_setting <section> <key> -> value, user file first, then the repo's.
# Exits 1 when the key is in neither. A leading ~ expands to $HOME.
registry_setting() {
    local v
    v=$(_registry_toml_get "${XDG_CONFIG_HOME:-$HOME/.config}/ssh_registry/settings.toml" "$1" "$2") ||
    v=$(_registry_toml_get "$REGISTRY_DIR/settings.toml" "$1" "$2") || return 1
    [[ "$v" == "~" || "$v" == "~/"* ]] && v="$HOME${v:1}"
    printf '%s\n' "$v"
}
