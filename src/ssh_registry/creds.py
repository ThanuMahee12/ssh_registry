"""The user's own login and key choices: ~/.shellrc/cred.toml.

    [global]            # every host
    user = "your.login"
    key = "id_ed25519"

    [cw_alchmy]         # one module; beats [global]
    user = "other.login"
    key = ["id_ed25519", "~/keys/alchemy.pem"]

Written by `shellrc config`, read by `generate`. It holds key NAMES or PATHS
only - never key material - but is still kept private: the directory is 0700
and the file 0600, because it says which login and key reach which servers.
"""

from __future__ import annotations

import os
import re
import tempfile
import tomllib
from pathlib import Path

SECTION = re.compile(r"^[A-Za-z0-9_-]+$")
GLOBAL = "global"


class CredError(Exception):
    pass


def load(path: Path) -> dict[str, dict]:
    if not path.is_file():
        return {}
    with path.open("rb") as f:
        data = tomllib.load(f)
    for section, values in data.items():
        if not isinstance(values, dict) or set(values) - {"user", "key"}:
            raise CredError(f"{path}: [{section}] may only hold user and key")
    return data


def _check_key(key: str) -> None:
    if not key or "\n" in key or "PRIVATE KEY" in key or "BEGIN " in key:
        raise CredError("key must be a file name under ~/.ssh or a path to one - never the key itself")


def _quote(s: str) -> str:
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'


def dump(data: dict[str, dict]) -> str:
    order = ([GLOBAL] if GLOBAL in data else []) + sorted(k for k in data if k != GLOBAL)
    out = ["# Written by `shellrc config`. Logins and key file names only - never key material.", ""]
    for section in order:
        values = data[section]
        if not values:
            continue
        out.append(f"[{section}]")
        if "user" in values:
            out.append(f"user = {_quote(values['user'])}")
        if "key" in values:
            k = values["key"]
            out.append("key = " + (_quote(k) if isinstance(k, str) else "[" + ", ".join(map(_quote, k)) + "]"))
        out.append("")
    return "\n".join(out)


def save(path: Path, data: dict[str, dict]) -> None:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(path.parent, 0o700)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(dump(data))
        os.chmod(tmp, 0o600)
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def set_values(path: Path, section: str, user: str | None, keys: list[str] | None,
               unset: list[str] | None = None) -> dict:
    if not SECTION.match(section):
        raise CredError(f"bad section name {section!r}")
    data = load(path)
    values = data.setdefault(section, {})
    if user is not None:
        if not user or any(c.isspace() for c in user):
            raise CredError("user must be a single login name")
        values["user"] = user
    if keys is not None:
        for k in keys:
            _check_key(k)
        values["key"] = keys[0] if len(keys) == 1 else keys
    for field in unset or []:
        values.pop(field, None)
    if not values:
        del data[section]
    save(path, data)
    return data


def key_path(key: str) -> str:
    """A bare name means ~/.ssh/<name>; anything with a slash or ~ is used as is."""
    return key if ("/" in key or key.startswith("~")) else f"~/.ssh/{key}"
