"""The user's own login and key choices: ~/.shellrc/cred.toml.

    [global]            # every host
    user = "your.login"
    key = "~/.ssh/id_ed25519"

    [cw_alchmy]         # one module; beats [global]
    user = "other.login"
    key = "~/keys/alchemy.pem"

Written by `shellrc config`, read by `generate`. `key` is the PATH to a private
key file - never the key itself - but the file is still kept private: the
directory is 0700 and the file 0600, because it says which login and key reach
which servers.
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
        if "key" in values and not isinstance(values["key"], str):
            raise CredError(f"{path}: [{section}] key must be one path, e.g. \"~/.ssh/id_ed25519\"")
    return data


def check_key(key: str) -> str | None:
    """Raise on anything but a key path; return a warning if the file is missing."""
    if not key or "\n" in key or "PRIVATE KEY" in key or "BEGIN " in key:
        raise CredError("key must be the path to a key file - never the key itself")
    if not (key.startswith(("/", "~")) or (len(key) > 2 and key[1] == ":")):
        raise CredError(f"key must be a path, e.g. ~/.ssh/{key}")
    if not Path(os.path.expanduser(key)).is_file():
        return f"{key} does not exist on this machine (saved anyway)"
    return None


def _quote(s: str) -> str:
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'


def dump(data: dict[str, dict]) -> str:
    order = ([GLOBAL] if GLOBAL in data else []) + sorted(k for k in data if k != GLOBAL)
    out = ["# Written by `shellrc config`. Logins and key file paths only - never key material.", ""]
    for section in order:
        values = data[section]
        if not values:
            continue
        out.append(f"[{section}]")
        if "user" in values:
            out.append(f"user = {_quote(values['user'])}")
        if "key" in values:
            out.append(f"key = {_quote(values['key'])}")
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


def set_values(path: Path, section: str, user: str | None, key: str | None,
               unset: list[str] | None = None) -> dict:
    if not SECTION.match(section):
        raise CredError(f"bad section name {section!r}")
    data = load(path)
    values = data.setdefault(section, {})
    if user is not None:
        if not user or any(c.isspace() for c in user):
            raise CredError("user must be a single login name")
        values["user"] = user
    if key is not None:
        check_key(key)
        values["key"] = key
    for field in unset or []:
        values.pop(field, None)
    if not values:
        del data[section]
    save(path, data)
    return data

