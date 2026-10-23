#!/usr/bin/env bash
# =============================================================================
#  Verify the shared host definitions in ssh/shared/. Read-only: uses `ssh -G`,
#  which resolves a host's settings WITHOUT opening a connection.
#
#  Usage:  scripts/verify-hosts.sh [-q]
#          -q   only print failures and the final verdict
#
#  Exit 0 = every check passed. Non-zero = the number of failed checks.
#
#  This repo owns the host definitions, so it checks them on their own: it
#  builds a throwaway ssh config that includes every shared file, in the same
#  order a machine uses, and does not depend on any other repo. Checks on the
#  machine configs themselves live with the machines (shellrc).
# =============================================================================
set -uo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO"

QUIET=0
[[ "${1:-}" == "-q" ]] && QUIET=1

RED=$'\033[0;31m'; GRN=$'\033[0;32m'; YEL=$'\033[1;33m'; GRY=$'\033[0;90m'; NC=$'\033[0m'
FAILED=0
say()  { [[ $QUIET -eq 1 ]] || printf '%s\n' "$*"; }
ok()   { [[ $QUIET -eq 1 ]] || printf '  %s✓%s %s\n' "$GRN" "$NC" "$*"; }
bad()  { printf '  %sx%s %s\n' "$RED" "$NC" "$*"; FAILED=$((FAILED+1)); }
note() { [[ $QUIET -eq 1 ]] || printf '  %s·%s %s\n' "$GRY" "$NC" "$*"; }

# Include order, same as a machine's final config: person layer first, work
# hosts explicit and ordered, global.config last so Host * defaults come last.
SHARED="$REPO/ssh/shared"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
CFG="$TMP/hosts.config"
{
    for f in "$SHARED"/thanujan/*.config; do
        [[ -f "$f" ]] && printf 'Include %s\n' "$f"
    done
    for n in proxy bench alchemy cwiq-pipe sli misc github global; do
        printf 'Include %s\n' "$SHARED/work/$n.config"
    done
} > "$CFG"

# --- the host list -----------------------------------------------------------
# Wildcard-only hosts do not appear in a `^Host ` grep. alchemy.config names
# each server literally AND as a wildcard, but the service accounts are
# wildcard-only, so enumerate all 30 alchemy names below regardless.
all_hosts() {
    grep -hE '^Host ' "$SHARED"/*/*.config 2>/dev/null \
        | awk '{for (i=2; i<=NF; i++) print $i}' | grep -v '[*]'
    local n
    for n in 01 02 03 04 05 06 07 08 09 10; do
        printf 'alchmy_ny5p%s\nalchmy_ny5p%s_svcP\nalchmy_ny5p%s_svcU\n' "$n" "$n" "$n"
    done
}

HOSTS="$(all_hosts | sort -u)"
NHOSTS=$(printf '%s\n' "$HOSTS" | grep -c .)

say "${YEL}registry host verification${NC}  ($NHOSTS hosts)"
say ""

# --- 1. every host resolves --------------------------------------------------
say "1. resolution (ssh -G, no connection opened)"
miss=""
for h in $HOSTS; do
    ssh -F "$CFG" -G "$h" >/dev/null 2>&1 || miss="$miss $h"
done
if [[ -n "$miss" ]]; then bad "fail to parse:$miss"; else ok "all $NHOSTS resolve"; fi

# --- 2. hosts with no HostName resolve to their own name (usually a typo) ----
say ""
say "2. hosts with no HostName (would try to DNS-resolve their alias)"
nohn=""
for h in $HOSTS; do
    hn=$(ssh -F "$CFG" -G "$h" 2>/dev/null | awk '/^hostname /{print $2}')
    # a real DNS name equal to the alias is fine (github.com, gitlab.com)
    if [[ "$hn" == "$h" && "$h" != *.* ]]; then nohn="$nohn $h"; fi
done
if [[ -n "$nohn" ]]; then bad "no HostName:$nohn"; else ok "every non-DNS alias has a HostName"; fi

# --- 3. the person layer -----------------------------------------------------
say ""
say "3. person layer"
pu=$(grep -rhE '^[[:space:]]*User ' "$SHARED"/*/identity.config 2>/dev/null | awk '{print $2}' | sort -u)
if [[ -z "$pu" ]]; then
    bad "no ssh/shared/*/identity.config defines a User"
else
    for u in $pu; do
        n=$(grep -rl "User $u" "$SHARED" 2>/dev/null | wc -l)
        if [[ "$n" -ne 1 ]]; then bad "'$u' appears in $n files under ssh/shared/ — must be only <person>/identity.config"
        else ok "'$u' declared exactly once ($(grep -rl "User $u" "$SHARED" | sed "s#$REPO/##"))"; fi
    done
fi
# a blanket User on Host * would break the git / ec2-user / service-account hosts
leak=$(awk '/^Host \*/{f=1;next} /^Host /{f=0} f && /^[[:space:]]*User /{print FILENAME": "$0}' "$SHARED"/*/*.config 2>/dev/null || true)
if [[ -n "$leak" ]]; then bad "User set on 'Host *' — breaks every host that logs in as someone else: $leak"
else ok "no 'User' on a 'Host *' block"; fi

# --- 4. no duplicated IPs ----------------------------------------------------
say ""
say "4. no duplicated IPs"
dupip=$(grep -hE '^[[:space:]]*HostName ' "$SHARED/work/alchemy.config" 2>/dev/null | awk '{print $2}' | sort | uniq -d)
if [[ -n "$dupip" ]]; then bad "alchemy IP declared more than once: ${dupip//$'\n'/ }"
else ok "alchemy: $(grep -cE '^[[:space:]]*HostName ' "$SHARED/work/alchemy.config") HostName lines, all distinct"; fi

# A host in SEVERAL files is by design: identity.config sets User, work/*.config
# gives the HostName. Disjoint keywords, so nothing is shadowed. What IS a bug:
#   a) the same Host pattern twice in ONE file  -> the second block is dead
#   b) two included files both setting HostName for one host -> the later is dead
for f in "$SHARED"/*/*.config; do
    d=$(grep -hE '^Host ' "$f" | awk '{for(i=2;i<=NF;i++)print $i}' | sort | uniq -d)
    [[ -n "$d" ]] && bad "${f#"$SHARED"/} defines the same pattern twice: ${d//$'\n'/ }"
done
dup2=$(awk '$1=="Host"{c=NF; for(i=2;i<=NF;i++) h[i]=$i; next}
            tolower($1)=="hostname"{for(i=2;i<=c;i++) print h[i]; c=0}' \
       $(awk 'tolower($1)=="include"{print $2}' "$CFG") | sort | uniq -d)
if [[ -n "$dup2" ]]; then bad "HostName declared in two included files (later is dead): ${dup2//$'\n'/ }"
else ok "no shadowed HostName (each host has one HostName)"; fi

# --- 5. informational --------------------------------------------------------
say ""
say "5. notes"
rc=$(grep -lE '^[[:space:]]*RemoteCommand' "$SHARED"/*/*.config 2>/dev/null | sed "s#$REPO/##" | tr '\n' ' ')
[[ -n "$rc" ]] && note "RemoteCommand hosts (NOT valid scp/rsync targets) in: $rc"

# --- verdict -----------------------------------------------------------------
say ""
if [[ $FAILED -eq 0 ]]; then
    printf '%sPASS%s  %s hosts, all host checks clean\n' "$GRN" "$NC" "$NHOSTS"
else
    printf '%sFAIL%s  %s check(s) failed\n' "$RED" "$NC" "$FAILED"
fi
exit $FAILED
