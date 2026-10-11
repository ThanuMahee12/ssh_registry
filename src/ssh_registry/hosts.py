"""Load and validate the module files (*.jsonl).

Each line is a GROUP: settings shared by its servers, plus the servers.

    {"proxy": "sf_jump", "forward_agent": true,
     "service_users": [{"flag": "P", "user": "svc_dat_alchemy"}],
     "servers": [{"host_name": "ny5-predpalch01", "aliases": ["alchmy_ny5p01"],
                  "host": "10.0.0.1"}]}

A field set on a server overrides the same field on its group. There are no
users or keys here: those come from settings.toml, so one set of files serves
every person.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from .settings import Settings

# field -> type, for both levels; "servers" only on a group, the rest anywhere
SHARED = {
    "proxy": str,
    "port": int,
    "forward_agent": bool,
    "identities_only": bool,
    "service_users": list,
    "options": dict,
    "note": str,
}
GROUP = {**SHARED, "servers": list}
SERVER = {**SHARED, "host_name": str, "host": str, "aliases": list}

NAME = re.compile(r"^[A-Za-z0-9._@-]+$")
FLAG = re.compile(r"^[A-Za-z0-9]+$")
KEYWORD = re.compile(r"^[A-Za-z]+$")


class RegistryError(Exception):
    pass


@dataclass
class Host:
    name: str
    hostname: str
    module: str
    source: str  # "file.jsonl:line", for error messages
    aliases: list[str] = field(default_factory=list)
    port: int | None = None
    proxy: str | None = None
    forward_agent: bool = False
    identities_only: bool = False
    service_users: dict[str, str] = field(default_factory=dict)  # flag -> account
    options: dict[str, str] = field(default_factory=dict)
    note: str | None = None
    user: str | None = None
    keys: tuple[str, ...] = ()

    @property
    def names(self) -> list[str]:
        return [self.name, *self.aliases]

    def svc_hosts(self) -> list[str]:
        return [f"{n}_svc{f}" for n in self.names for f in self.service_users]


def _typecheck(raw: dict, spec: dict, where: str, what: str) -> None:
    if not isinstance(raw, dict):
        raise RegistryError(f"{where}: a {what} must be a JSON object")
    unknown = sorted(set(raw) - set(spec))
    if unknown:
        raise RegistryError(f"{where}: unknown {what} field(s) {unknown}; allowed: {sorted(spec)}")
    for key, typ in spec.items():
        v = raw.get(key)
        if key in raw and (not isinstance(v, typ) or (typ is int and isinstance(v, bool))):
            raise RegistryError(f"{where}: {what} '{key}' must be {typ.__name__}")


def _service_users(raw: list, where: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for su in raw:
        if not (isinstance(su, dict) and set(su) == {"flag", "user"}
                and isinstance(su["flag"], str) and FLAG.match(su["flag"])
                and isinstance(su["user"], str) and su["user"]):
            raise RegistryError(f'{where}: service_users entries look like {{"flag": "P", "user": "svc_x"}}')
        if su["flag"] in out:
            raise RegistryError(f"{where}: service_users flag '{su['flag']}' appears twice")
        out[su["flag"]] = su["user"]
    return out


def _server(group: dict, raw: dict, module: str, where: str) -> Host:
    _typecheck(raw, SERVER, where, "server")
    merged = {k: v for k, v in group.items() if k != "servers"} | raw
    for req in ("host_name", "host"):
        if not merged.get(req):
            raise RegistryError(f"{where}: server needs '{req}'")
    aliases = merged.get("aliases", [])
    for n in [merged["host_name"], *aliases]:
        if not isinstance(n, str) or not NAME.match(n):
            raise RegistryError(f"{where}: bad host name {n!r} (no spaces or wildcards)")
    for k, v in merged.get("options", {}).items():
        if not KEYWORD.match(k) or not isinstance(v, str):
            raise RegistryError(f'{where}: options look like {{"SshKeyword": "value"}}')
    return Host(
        name=merged["host_name"],
        hostname=merged["host"],
        module=module,
        source=where,
        aliases=list(aliases),
        port=merged.get("port"),
        proxy=merged.get("proxy"),
        forward_agent=merged.get("forward_agent", False),
        identities_only=merged.get("identities_only", False),
        service_users=_service_users(merged.get("service_users", []), where),
        options=dict(merged.get("options", {})),
        note=merged.get("note"),
    )


def load_dir(directory: Path) -> list[Host]:
    files = sorted(directory.glob("*.jsonl"))
    if not files:
        raise RegistryError(f"no *.jsonl files in {directory}")
    hosts: list[Host] = []
    for path in files:
        module = path.stem
        for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if not line.strip():
                continue
            where = f"{path.name}:{n}"
            try:
                group = json.loads(line)
            except json.JSONDecodeError as e:
                raise RegistryError(f"{where}: invalid JSON ({e.msg})") from None
            _typecheck(group, GROUP, where, "group")
            if not group.get("servers"):
                raise RegistryError(f"{where}: group has no 'servers'")
            for i, raw in enumerate(group["servers"], 1):
                hosts.append(_server(group, raw, module, f"{where} server {i}"))
    _check_set(hosts)
    return hosts


def _check_set(hosts: list[Host]) -> None:
    seen: dict[str, str] = {}
    for h in hosts:
        for name in [*h.names, *h.svc_hosts()]:
            if name in seen:
                raise RegistryError(f"{h.source}: '{name}' is already defined at {seen[name]}")
            seen[name] = h.source
    for h in hosts:
        if h.proxy and h.proxy not in seen:
            raise RegistryError(f"{h.source}: proxy '{h.proxy}' is not a host in the registry")


def apply_logins(hosts: list[Host], s: Settings) -> list[Host]:
    """Fill user and keys from settings.toml; every host must end up with a user."""
    missing = []
    for h in hosts:
        login = s.login_for(h.name, h.module)
        h.user, h.keys = login.user, login.keys
        if not h.user:
            missing.append(h.name)
    if missing:
        raise RegistryError(
            f"no login for {len(missing)} host(s) (first: {missing[0]}): [identity] user is empty.\n"
            "Set it in ~/.config/ssh_registry/settings.toml:\n\n  [identity]\n  user = \"your.login\""
        )
    return hosts
