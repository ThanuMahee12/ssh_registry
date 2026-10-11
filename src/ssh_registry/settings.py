"""settings.toml from the repo, overridden key by key by the user's own copy."""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

REPO_DIR = Path(__file__).resolve().parents[2]
REPO_SETTINGS = REPO_DIR / "settings.toml"


def user_settings_path() -> Path:
    base = os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config"
    return Path(base) / "ssh_registry" / "settings.toml"


from . import creds as creds_mod


@dataclass(frozen=True)
class Login:
    user: str | None = None
    key: str | None = None


@dataclass(frozen=True)
class Settings:
    bucket: str
    region: str
    prefix: str
    cache_dir: Path
    output: Path
    cred_file: Path
    creds: dict[str, dict] = field(default_factory=dict)
    modules: dict[str, Login] = field(default_factory=dict)
    hosts: dict[str, Login] = field(default_factory=dict)
    ssh_defaults: dict[str, str] = field(default_factory=dict)

    @property
    def s3_uri(self) -> str:
        return f"s3://{self.bucket}/{self.prefix.strip('/')}/"

    def login_for(self, host: str, module: str) -> Login:
        """User: [hosts.x] > cred [module] > [modules.m] > cred [global].
        Key: cred [module] > cred [global]."""
        g = self.creds.get(creds_mod.GLOBAL, {})
        m = self.creds.get(module, {})
        user = g.get("user")
        repo_module, repo_host = self.modules.get(module), self.hosts.get(host)
        if repo_module and repo_module.user is not None:
            user = repo_module.user
        user = m.get("user", user)
        if repo_host and repo_host.user is not None:
            user = repo_host.user
        return Login(user or None, m.get("key", g.get("key")))


def _read(path: Path) -> dict:
    if not path.is_file():
        return {}
    with path.open("rb") as f:
        return tomllib.load(f)


def _merge(base: dict, override: dict) -> dict:
    out = dict(base)
    for k, v in override.items():
        out[k] = _merge(out[k], v) if isinstance(v, dict) and isinstance(out.get(k), dict) else v
    return out


def _login(raw: dict, where: str) -> Login:
    unknown = set(raw) - {"user"}
    if unknown:
        raise SystemExit(f"settings.toml [{where}]: unknown key(s) {sorted(unknown)}; only user is allowed")
    return Login(raw.get("user"))


def load(repo_file: Path = REPO_SETTINGS, user_file: Path | None = None) -> Settings:
    data = _merge(_read(repo_file), _read(user_file or user_settings_path()))
    try:
        return Settings(
            bucket=data["source"]["bucket"],
            region=data["source"]["region"],
            prefix=data["source"]["prefix"],
            cache_dir=Path(os.path.expanduser(data["cache"]["dir"])),
            output=Path(os.path.expanduser(data["output"]["config"])),
            cred_file=(cf := Path(os.path.expanduser(data.get("credentials", {}).get("file", "~/.shellrc/cred.toml")))),
            creds=creds_mod.load(cf),
            modules={k: _login(v, f"modules.{k}") for k, v in data.get("modules", {}).items()},
            hosts={k: _login(v, f'hosts."{k}"') for k, v in data.get("hosts", {}).items()},
            ssh_defaults={k: str(v) for k, v in data.get("ssh_defaults", {}).items()},
        )
    except KeyError as e:
        raise SystemExit(f"settings.toml: missing key {e} (checked {repo_file} and the user override)")
