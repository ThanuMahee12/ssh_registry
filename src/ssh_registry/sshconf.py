"""Parse the ssh config subset the source files use: Host blocks and keyword lines.

Include and Match are refused. The source files are flat, so an Include would
make the conversion order ambiguous.
"""

from dataclasses import dataclass, field
from pathlib import Path

# Keywords with a column of their own; everything else goes to host_option/host_key.
CANONICAL = {
    "hostname": "HostName",
    "user": "User",
    "proxyjump": "ProxyJump",
    "forwardagent": "ForwardAgent",
    "identitiesonly": "IdentitiesOnly",
    "identityfile": "IdentityFile",
    "port": "Port",
}

# Keywords whose case is normalised. Unknown keywords keep the case they were written in.
KNOWN = {
    k.lower(): k for k in (
        "RemoteCommand", "RequestTTY", "ServerAliveInterval", "ServerAliveCountMax",
        "TCPKeepAlive", "Compression", "AddKeysToAgent", "StrictHostKeyChecking",
        "UserKnownHostsFile",
    )
}


def canonical_key(key: str) -> str:
    lower = key.lower()
    return CANONICAL.get(lower) or KNOWN.get(lower, key)


@dataclass
class Block:
    patterns: list[str]
    pairs: list[tuple[str, str]] = field(default_factory=list)


def parse(path: Path) -> list[Block]:
    blocks: list[Block] = []
    current: Block | None = None
    with open(path, encoding="utf-8") as fh:
        for number, raw in enumerate(fh, 1):
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            key, _, value = line.replace("=", " ", 1).partition(" ")
            key, value = key.strip(), value.strip()
            if key.lower() == "host":
                if not value:
                    raise ValueError(f"{path}:{number}: Host with no pattern")
                current = Block(patterns=value.split())
                blocks.append(current)
            elif key.lower() in ("include", "match"):
                raise ValueError(f"{path}:{number}: {key} is not supported in source host files")
            elif current is None:
                raise ValueError(f"{path}:{number}: keyword before any Host: {key}")
            elif not value:
                raise ValueError(f"{path}:{number}: {key} has no value")
            else:
                current.pairs.append((key, value))
    return blocks
