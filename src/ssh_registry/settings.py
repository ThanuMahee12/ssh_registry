"""settings.toml from the repo, overridden key by key by the user's own copy."""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass
from pathlib import Path

REPO_DIR = Path(__file__).resolve().parents[2]
REPO_SETTINGS = REPO_DIR / "settings.toml"


def user_settings_path() -> Path:
    base = os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config"
    return Path(base) / "ssh_registry" / "settings.toml"


@dataclass(frozen=True)
class Settings:
    bucket: str
    region: str
    prefix: str
    cache_dir: Path
    output: Path
    me: str

    @property
    def s3_uri(self) -> str:
        return f"s3://{self.bucket}/{self.prefix.strip('/')}/"


def _read(path: Path) -> dict:
    if not path.is_file():
        return {}
    with path.open("rb") as f:
        return tomllib.load(f)


def _merge(base: dict, override: dict) -> dict:
    out = {k: dict(v) if isinstance(v, dict) else v for k, v in base.items()}
    for section, values in override.items():
        if isinstance(values, dict):
            out.setdefault(section, {}).update(values)
        else:
            out[section] = values
    return out


def _path(value: str) -> Path:
    return Path(os.path.expanduser(value))


def load(repo_file: Path = REPO_SETTINGS, user_file: Path | None = None) -> Settings:
    data = _merge(_read(repo_file), _read(user_file or user_settings_path()))
    try:
        return Settings(
            bucket=data["source"]["bucket"],
            region=data["source"]["region"],
            prefix=data["source"]["prefix"],
            cache_dir=_path(data["cache"]["dir"]),
            output=_path(data["output"]["config"]),
            me=data.get("identity", {}).get("me", ""),
        )
    except KeyError as e:
        raise SystemExit(f"settings.toml: missing key {e} (checked {repo_file} and the user override)")
