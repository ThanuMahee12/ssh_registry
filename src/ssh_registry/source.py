"""Import hosts from a CSV or JSON Lines file into the registry database.

Columns (CSV header, or the same keys in each JSON object):
  host, kind, usage, proxy, hostname, user, service_account, alias

- kind: one of KINDS. usage: cw (default), personal or shared.
- proxy: another host in the same file.
- hostname: an address or DNS name. Empty, or the placeholder xx.xx.xx.xx, means
  the host is written without a HostName line (its address is dynamic).
- user: one or more logins, comma-separated. The first is the host's default login;
  the others are direct logins.
- service_account: up to two service logins, comma-separated: the first is the
  P account, the second the U account. Each must be a svc_* login.
- alias: extra names for the host, comma-separated.

Every row is checked before anything is written. If any row is wrong, nothing is
written and every problem is reported with its row number.
"""

import csv
import json
import sqlite3
from pathlib import Path

from .convert import classify_login

KINDS = ("on-prem", "proxy", "github", "gitlab", "default", "EC2", "bench", "bench_env", "devhub")
USAGES = ("cw", "personal", "shared")
PLACEHOLDER = "xx.xx.xx.xx"


class SourceError(Exception):
    """One or more rows are wrong. The message lists every problem."""


def _clean(value) -> str:
    return "" if value is None else str(value).strip()


def _split(value: str) -> list[str]:
    return [part.strip() for part in value.split(",") if part.strip()]


def read_rows(path: Path) -> list[tuple[int, dict]]:
    """Return (row number, normalised row) pairs. Row numbers are the file's line numbers."""
    text = path.read_text(encoding="utf-8-sig")
    rows: list[tuple[int, dict]] = []
    if path.suffix.lower() in (".jsonl", ".json"):
        for number, line in enumerate(text.splitlines(), 1):
            if not line.strip():
                continue
            try:
                raw = json.loads(line)
            except json.JSONDecodeError as exc:
                raise SourceError(f"line {number}: not valid JSON ({exc.msg})") from None
            rows.append((number, {str(k).strip().lower(): _clean(v) for k, v in raw.items()}))
    else:
        reader = csv.DictReader(text.splitlines())
        for number, raw in enumerate(reader, 2):
            rows.append((number, {str(k).strip().lower(): _clean(v) for k, v in raw.items() if k}))
    return rows


def validate(rows: list[tuple[int, dict]]) -> list[dict]:
    """Check every row. Return the hosts to write, or raise SourceError listing all problems."""
    problems: list[str] = []
    hosts: list[dict] = []
    names: dict[str, int] = {}
    for number, row in rows:
        host = row.get("host", "")
        here = f"row {number} ({host or 'no name'})"
        if not host:
            problems.append(f"row {number}: host is empty")
            continue
        if host in names:
            problems.append(f"{here}: host {host!r} is also on row {names[host]}")
            continue
        names[host] = number
        kind = row.get("kind", "")
        if kind not in KINDS:
            problems.append(f"{here}: kind {kind!r} is not one of {', '.join(KINDS)}")
        usage = row.get("usage", "") or "cw"
        if usage not in USAGES:
            problems.append(f"{here}: usage {usage!r} is not one of {', '.join(USAGES)}")
        hostname = row.get("hostname", "")
        hostname = None if hostname in ("", PLACEHOLDER) else hostname
        users = _split(row.get("user", ""))
        services = _split(row.get("service_account", ""))
        if len(services) > 2:
            problems.append(f"{here}: at most two service accounts (P and U); got {len(services)}")
        for account in services:
            if classify_login(account) != "service":
                problems.append(f"{here}: {account!r} is not a service login (svc_*)")
        hosts.append({
            "number": number, "name": host, "kind": kind, "usage": usage, "hostname": hostname,
            "proxy": row.get("proxy", "") or None, "users": users, "services": services,
            "aliases": _split(row.get("alias", "")),
        })
    known = set(names)
    for item in hosts:
        if item["proxy"] and item["proxy"] not in known:
            problems.append(f"row {item['number']} ({item['name']}): proxy {item['proxy']!r} is not a host in this file")
        if item["proxy"] == item["name"]:
            problems.append(f"row {item['number']} ({item['name']}): a host cannot be its own proxy")
        for alias in item["aliases"]:
            if alias in known:
                problems.append(f"row {item['number']} ({item['name']}): alias {alias!r} is also a host name")
    if problems:
        raise SourceError("; ".join(problems))
    return hosts


def write(conn: sqlite3.Connection, hosts: list[dict]) -> int:
    """Write the checked hosts into an empty database, in one transaction."""
    ids: dict[str, int] = {}
    with conn:
        for order, item in enumerate(hosts, 1):
            cur = conn.execute(
                "INSERT INTO host (name, kind, usage, hostname, sort_order) VALUES (?, ?, ?, ?, ?)",
                (item["name"], item["kind"], item["usage"], item["hostname"], order),
            )
            ids[item["name"]] = cur.lastrowid
        for item in hosts:
            if item["proxy"]:
                conn.execute("UPDATE host SET proxy_id = ? WHERE id = ?",
                             (ids[item["proxy"]], ids[item["name"]]))
            for alias in item["aliases"]:
                conn.execute("INSERT INTO host_name (pattern, host_id) VALUES (?, ?)",
                             (alias, ids[item["name"]]))
            for index, user in enumerate(item["users"]):
                conn.execute("INSERT OR IGNORE INTO login (user, kind) VALUES (?, ?)",
                             (user, classify_login(user)))
                login_id = conn.execute("SELECT id FROM login WHERE user = ?", (user,)).fetchone()[0]
                role = "default" if index == 0 else "direct"
                conn.execute(
                    "INSERT OR IGNORE INTO host_login (host_id, login_id, role) VALUES (?, ?, ?)",
                    (ids[item["name"]], login_id, role),
                )
            for flag, account in zip(("P", "U"), item["services"]):
                conn.execute("INSERT OR IGNORE INTO login (user, kind) VALUES (?, ?)",
                             (account, classify_login(account)))
                login_id = conn.execute("SELECT id FROM login WHERE user = ?", (account,)).fetchone()[0]
                conn.execute(
                    "INSERT INTO host_login (host_id, login_id, role, flag) VALUES (?, ?, 'sudo', ?)",
                    (ids[item["name"]], login_id, flag),
                )
    return len(hosts)


def import_file(conn: sqlite3.Connection, path: Path) -> int:
    """Read, check and write one CSV or JSON Lines file. Returns the number of hosts."""
    if not path.is_file():
        raise SourceError(f"no file at {path}")
    return write(conn, validate(read_rows(path)))
