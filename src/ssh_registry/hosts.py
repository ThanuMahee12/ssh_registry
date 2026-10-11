"""Load and validate host rows from the *.jsonl files.

One row per line:

    {"host": "alchmy_ny5p01", "hostname": "10.0.0.1", "user": "@me",
     "proxy": "sf_jump", "forward_agent": true, "keys": ["id_ed25519"],
     "svc": {"P": "svc_dat_alchemy"}}

"user": "@me" is replaced by settings [identity] me, so the files themselves
hold no person's login and serve every user.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

ME = "@me"

FIELDS = {
    "host": str,
    "aliases": list,
    "hostname": str,
    "port": int,
    "user": str,
    "proxy": str,
    "keys": list,
    "forward_agent": bool,
    "identities_only": bool,
    "svc": dict,
    "options": dict,
    "note": str,
}

# Host names become ssh patterns: no whitespace, and wildcards only where meant.
NAME = re.compile(r"^[A-Za-z0-9._@*?-]+$")
SVC_KEY = re.compile(r"^[A-Za-z0-9]+$")


class RegistryError(Exception):
    pass


@dataclass
class Host:
    host: str
    source: str  # "file.jsonl:line", for error messages
    hostname: str | None = None
    aliases: list[str] = field(default_factory=list)
    port: int | None = None
    user: str | None = None
    proxy: str | None = None
    keys: list[str] = field(default_factory=list)
    forward_agent: bool = False
    identities_only: bool = False
    svc: dict[str, str] = field(default_factory=dict)
    options: dict[str, str] = field(default_factory=dict)
    note: str | None = None

    @property
    def is_pattern(self) -> bool:
        return "*" in self.host or "?" in self.host

    def svc_hosts(self) -> list[str]:
        return [f"{self.host}_svc{k}" for k in self.svc]


def _row(raw: dict, where: str) -> Host:
    if not isinstance(raw, dict):
        raise RegistryError(f"{where}: a row must be a JSON object")
    unknown = sorted(set(raw) - set(FIELDS))
    if unknown:
        raise RegistryError(f"{where}: unknown field(s) {unknown}; allowed: {sorted(FIELDS)}")
    for key, typ in FIELDS.items():
        if key in raw and not isinstance(raw[key], typ) or (typ is int and isinstance(raw.get(key), bool)):
            raise RegistryError(f"{where}: '{key}' must be {typ.__name__}")
    if "host" not in raw:
        raise RegistryError(f"{where}: 'host' is required")

    h = Host(source=where, **raw)
    for name in [h.host, *h.aliases]:
        if not isinstance(name, str) or not NAME.match(name):
            raise RegistryError(f"{where}: bad host name {name!r}")
    if not h.is_pattern and not h.hostname:
        raise RegistryError(f"{where}: '{h.host}' needs a 'hostname' (IP or DNS name)")
    if h.is_pattern and (h.hostname or h.svc):
        raise RegistryError(f"{where}: pattern '{h.host}' may only carry defaults, not hostname/svc")
    if not all(isinstance(k, str) and k and "/" not in k for k in h.keys):
        raise RegistryError(f"{where}: 'keys' are file names under ~/.ssh, e.g. [\"id_ed25519\"]")
    for k, account in h.svc.items():
        if not SVC_KEY.match(k) or not isinstance(account, str) or not account:
            raise RegistryError(f"{where}: svc must map a letter to an account, e.g. {{\"P\": \"svc_x\"}}")
    for k, v in h.options.items():
        if not isinstance(v, str) or not re.match(r"^[A-Za-z]+$", k):
            raise RegistryError(f"{where}: options must be {{\"SshKeyword\": \"value\"}}")
    return h


def load_dir(directory: Path) -> list[Host]:
    files = sorted(directory.glob("*.jsonl"))
    if not files:
        raise RegistryError(f"no *.jsonl files in {directory}")
    hosts: list[Host] = []
    for path in files:
        for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if not line.strip():
                continue
            where = f"{path.name}:{n}"
            try:
                raw = json.loads(line)
            except json.JSONDecodeError as e:
                raise RegistryError(f"{where}: invalid JSON ({e.msg})") from None
            hosts.append(_row(raw, where))
    _check_set(hosts)
    return hosts


def _check_set(hosts: list[Host]) -> None:
    seen: dict[str, str] = {}
    for h in hosts:
        for name in [h.host, *h.aliases, *h.svc_hosts()]:
            if name in seen:
                raise RegistryError(f"{h.source}: '{name}' is already defined at {seen[name]}")
            seen[name] = h.source
    for h in hosts:
        if h.proxy and h.proxy not in seen:
            raise RegistryError(f"{h.source}: proxy '{h.proxy}' is not a host in the registry")


def resolve_me(hosts: list[Host], me: str) -> list[Host]:
    needs = [h.source for h in hosts if h.user == ME]
    if needs and not me:
        raise RegistryError(
            f'{len(needs)} host(s) use "user": "{ME}" (first: {needs[0]}) but [identity] me is empty.\n'
            "Set it in ~/.config/ssh_registry/settings.toml:\n\n  [identity]\n  me = \"your.login\""
        )
    for h in hosts:
        if h.user == ME:
            h.user = me
    return hosts
