"""Interactive `shellrc config`: pick global or a module, then user and key.

Plain numbered prompts on stdin/stdout - no curses - so it behaves the same in
a Linux terminal, Git Bash and PowerShell.
"""

from __future__ import annotations

import os
from pathlib import Path

from . import creds as creds_mod
from .settings import Settings

NOT_KEYS = {"config", "known_hosts", "known_hosts.old", "authorized_keys", "environment"}


def find_keys(ssh_dir: Path | None = None) -> list[str]:
    """Private key files in ~/.ssh, shown as ~/.ssh/<name>. Only the first line
    of each file is read, to recognise a PEM/OpenSSH private key header."""
    ssh_dir = ssh_dir or Path.home() / ".ssh"
    found = []
    if not ssh_dir.is_dir():
        return found
    for p in sorted(ssh_dir.iterdir()):
        if (not p.is_file() or p.name in NOT_KEYS or p.suffix in {".pub", ".bak", ".config"}
                or p.name.startswith(".")):
            continue
        try:
            with p.open("r", encoding="ascii", errors="replace") as f:
                head = f.readline(80)
        except OSError:
            continue
        if "PRIVATE KEY" in head:
            found.append(f"~/.ssh/{p.name}")
    return found


def _ask(prompt: str) -> str | None:
    try:
        return input(prompt).strip()
    except EOFError:
        return None


def _effective(s: Settings, section: str) -> tuple[str, str]:
    """What the generated config will use for this section, and where it comes from."""
    g = s.creds.get(creds_mod.GLOBAL, {})
    own = s.creds.get(section, {})
    if section == creds_mod.GLOBAL:
        return (g.get("user") or "-", g.get("key") or "-")
    if "user" in own:
        user = own["user"]
    elif s.modules.get(section) and s.modules[section].user:
        user = f"{s.modules[section].user} (default)"
    elif g.get("user"):
        user = f"{g['user']} (global)"
    else:
        user = "-"
    key = own.get("key") or (f"{g['key']} (global)" if g.get("key") else "-")
    return user, key


def _dashboard(s: Settings, sections: list[str]) -> None:
    rows = [(str(i), sec, *_effective(s, sec)) for i, sec in enumerate(sections, 1)]
    w = [max(len(r[c]) for r in rows + [("#", "Section", "User", "Key")]) for c in range(4)]
    print(f"\n  ssh_registry - {s.cred_file}\n")
    print("  " + "  ".join(h.ljust(w[c]) for c, h in enumerate(("#", "Section", "User", "Key"))))
    print("  " + "  ".join("-" * w[c] for c in range(4)))
    for r in rows:
        print("  " + "  ".join(r[c].ljust(w[c]) for c in range(4)))
    print("\n  q  quit")


def _pick_key(current: str | None) -> tuple[bool, str | None]:
    """(changed, value). value None means clear."""
    keys = find_keys()
    print(f"\n  Key (now: {current or '-'})")
    for i, k in enumerate(keys, 1):
        print(f"    {i}  {k}")
    print("    n  new path")
    if current:
        print("    -  clear")
    print("    Enter  keep")
    while True:
        a = _ask("  key> ")
        if a is None or a == "":
            return False, current
        if a == "-" and current:
            return True, None
        if a.lower() == "n":
            path = _ask("  path to private key file: ")
            if not path:
                return False, current
            try:
                note = creds_mod.check_key(path)
            except creds_mod.CredError as e:
                print(f"  ! {e}")
                continue
            if note:
                print(f"  ! {note}")
            return True, path
        if a.isdigit() and 1 <= int(a) <= len(keys):
            return True, keys[int(a) - 1]
        print("  ! choose a number, n, - or Enter")


def _edit(s: Settings, section: str) -> None:
    own = s.creds.get(section, {})
    print(f"\n  [{section}]")
    user = _ask(f"  User (optional; now: {own.get('user', '-')}; Enter keep, - clear): ")
    if user is None:
        return
    key_changed, key = _pick_key(own.get("key"))

    set_user, set_key, unset = None, None, []
    if user == "-":
        unset += ["user"] if "user" in own else []
    elif user:
        set_user = user
    if key_changed:
        if key is None:
            unset.append("key")
        else:
            set_key = key
    if set_user is None and set_key is None and not unset:
        print("  nothing changed")
        return
    try:
        creds_mod.set_values(s.cred_file, section, set_user, set_key, unset)
    except creds_mod.CredError as e:
        print(f"  ! {e}")
        return
    print(f"  saved [{section}]")


def run(s: Settings, modules: list[str], reload) -> int:
    """`reload` returns fresh Settings after a save."""
    while True:
        extra = sorted(k for k in s.creds if k != creds_mod.GLOBAL and k not in modules)
        sections = [creds_mod.GLOBAL, *modules, *extra]
        _dashboard(s, sections)
        a = _ask("\n  choose> ")
        if a is None or a.lower() in {"q", "quit", "exit"}:
            print("\n  Run `shellrc generate` to apply changes.")
            return 0
        if a.isdigit() and 1 <= int(a) <= len(sections):
            _edit(s, sections[int(a) - 1])
            s = reload()
        elif a:
            print("  ! choose a number or q")


def interactive() -> bool:
    return os.isatty(0) and os.isatty(1)
