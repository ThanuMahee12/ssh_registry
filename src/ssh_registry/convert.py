"""One-time conversion: the source host files -> the SQLite database.

Rules:
- A pattern that is exactly `<literal>*` in a block with `<literal>` becomes a
  host_name alias of that host (alchmy_ny5p01* of alchmy_ny5p01).
- Any other pattern is a host, merged by name across files.
- A block whose RemoteCommand runs `sudo su - <user>` on `<group>_svcP|U` becomes
  an account of the group host, not a host.
- identity.config supplies the person's login; their hosts link to it.
"""

import re
import sqlite3
from pathlib import Path

from . import sshconf

PERSON_FILE = "identity.config"
SVC = re.compile(r"^(?P<group>.+)_svc(?P<flag>[PU])$")
SUDO = re.compile(r"^sudo\s+su\s+-\s+(?P<user>\S+)$")
KIND_BY_NAME = {"sf_jump": "proxy", "*": "default"}
SYSTEM_LOGINS = {"git", "bench", "ec2-user"}


def classify_login(user: str) -> str:
    """personal: a person's login. service: svc_* (the only valid sudo target). system: shared logins."""
    if user.startswith("svc_"):
        return "service"
    if user in SYSTEM_LOGINS:
        return "system"
    return "personal"


class Converter:
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn
        self.order = 0
        self.proxies: dict[str, str] = {}
        self.accounts: list[tuple[str, str, str]] = []

    # --- small helpers -----------------------------------------------------

    def login_id(self, user: str) -> int:
        self.conn.execute("INSERT OR IGNORE INTO login (user, kind) VALUES (?, ?)",
                          (user, classify_login(user)))
        return self.conn.execute("SELECT id FROM login WHERE user = ?", (user,)).fetchone()[0]

    def host(self, name: str, kind: str, usage: str) -> int:
        row = self.conn.execute("SELECT id FROM host WHERE name = ?", (name,)).fetchone()
        if row:
            return row[0]
        self.order += 1
        cur = self.conn.execute(
            "INSERT INTO host (name, kind, usage, sort_order) VALUES (?, ?, ?, ?)",
            (name, kind, usage, self.order),
        )
        return cur.lastrowid

    def set_once(self, host_id: int, column: str, value) -> None:
        # first value wins, as with ssh itself
        self.conn.execute(
            f"UPDATE host SET {column} = COALESCE({column}, ?) WHERE id = ?", (value, host_id)
        )

    def add_option(self, host_id: int, key: str, value: str) -> None:
        if self.conn.execute(
            "SELECT 1 FROM host_option WHERE host_id = ? AND key = ? AND value = ?",
            (host_id, key, value),
        ).fetchone():
            return
        seq = self.conn.execute(
            "SELECT COALESCE(MAX(seq) + 1, 0) FROM host_option WHERE host_id = ? AND key = ?",
            (host_id, key),
        ).fetchone()[0]
        self.conn.execute(
            "INSERT INTO host_option (host_id, key, seq, value) VALUES (?, ?, ?, ?)",
            (host_id, key, seq, value),
        )

    def add_key(self, host_id: int, path: str) -> None:
        if self.conn.execute(
            "SELECT 1 FROM host_key WHERE host_id = ? AND path = ?", (host_id, path)
        ).fetchone():
            return
        seq = self.conn.execute(
            "SELECT COALESCE(MAX(seq) + 1, 0) FROM host_key WHERE host_id = ?", (host_id,)
        ).fetchone()[0]
        self.conn.execute("INSERT INTO host_key (host_id, seq, path) VALUES (?, ?, ?)", (host_id, seq, path))

    # --- conversion --------------------------------------------------------

    def convert_file(self, path: Path) -> None:
        blocks = sshconf.parse(path)
        person_login = None
        if path.name == PERSON_FILE:
            person_login = next(
                (v for b in blocks for k, v in b.pairs if sshconf.canonical_key(k) == "User"), None
            )
            if not person_login:
                raise ValueError(f"{path}: person file has no User line")
        for block in blocks:
            self.convert_block(path, block, person_login)

    def convert_block(self, path: Path, block: sshconf.Block, person_login: str | None) -> None:
        literals = {p for p in block.patterns if "*" not in p}
        for pattern in block.patterns:
            if pattern.endswith("*") and pattern[:-1] in literals and len(literals) == 1:
                continue  # an alias: handled after its host exists
            svc = SVC.match(pattern)
            if svc and self.is_sudo_account(block):
                user = self.sudo_user(block)
                self.accounts.append((svc["group"], svc["flag"], user))
                continue
            self.convert_host(path, pattern, block, person_login)
        for pattern in block.patterns:
            if pattern.endswith("*") and pattern[:-1] in literals and len(literals) == 1:
                host_id = self.conn.execute("SELECT id FROM host WHERE name = ?", (pattern[:-1],)).fetchone()[0]
                self.conn.execute("INSERT OR IGNORE INTO host_name (pattern, host_id) VALUES (?, ?)",
                                  (pattern, host_id))

    def is_sudo_account(self, block: sshconf.Block) -> bool:
        return any(sshconf.canonical_key(k) == "RemoteCommand" and SUDO.match(v) for k, v in block.pairs)

    def sudo_user(self, block: sshconf.Block) -> str:
        for k, v in block.pairs:
            m = SUDO.match(v) if sshconf.canonical_key(k) == "RemoteCommand" else None
            if m:
                return m["user"]
        raise ValueError("sudo account without a user")

    def convert_host(self, path: Path, name: str, block: sshconf.Block, person_login: str | None) -> None:
        stem = path.stem.lower()
        if name == "*":
            kind, usage = "default", "shared"
        else:
            kind = KIND_BY_NAME.get(name) or ("github" if "github" in stem else "gitlab" if "gitlab" in stem else "on-prem")
            personal = path.parent.name == "thanujan" and path.name != PERSON_FILE
            usage = "personal" if personal else "cw"
        host_id = self.host(name, kind, usage)
        for key, value in block.pairs:
            canon = sshconf.canonical_key(key)
            if canon == "HostName":
                self.set_once(host_id, "hostname", value)
            elif canon == "User":
                if person_login is not None:
                    self.set_once(host_id, "login_id", self.login_id(person_login))
                else:
                    self.set_once(host_id, "login_id", self.login_id(value))
            elif canon == "ProxyJump":
                self.proxies.setdefault(name, value)
            elif canon == "ForwardAgent":
                self.conn.execute("UPDATE host SET forward_agent = ? WHERE id = ?",
                                  (1 if value.lower() == "yes" else 0, host_id))
            elif canon == "IdentitiesOnly":
                self.conn.execute("UPDATE host SET identities_only = ? WHERE id = ?",
                                  (1 if value.lower() == "yes" else 0, host_id))
            elif canon == "IdentityFile":
                self.add_key(host_id, value)
            elif canon == "Port":
                self.set_once(host_id, "port", int(value))
            else:
                self.add_option(host_id, canon, value)

    def finish(self) -> None:
        for name, proxy in self.proxies.items():
            row = self.conn.execute("SELECT id FROM host WHERE name = ?", (proxy,)).fetchone()
            if row is None:
                raise ValueError(f"{name}: ProxyJump {proxy} is not defined")
            self.conn.execute("UPDATE host SET proxy_id = ? WHERE name = ?", (row[0], name))
        for group, flag, user in self.accounts:
            row = self.conn.execute("SELECT id FROM host WHERE name = ?", (group,)).fetchone()
            if row is None:
                raise ValueError(f"account {group}_svc{flag}: group host {group} is not defined")
            if classify_login(user) != "service":
                raise ValueError(f"account {group}_svc{flag}: {user} is not a service login")
            self.conn.execute(
                "INSERT OR REPLACE INTO account (host_id, flag, login_id) VALUES (?, ?, ?)",
                (row[0], flag, self.login_id(user)),
            )


def convert(conn: sqlite3.Connection, files: list[Path]) -> None:
    """Load every source file into the database, in order, in one transaction."""
    with conn:
        converter = Converter(conn)
        for path in files:
            converter.convert_file(Path(path))
        converter.finish()
