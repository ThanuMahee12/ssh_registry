"""Edit commands: change hosts, logins, links and persons in the database.

Each command runs in one transaction and writes a change_log row, so every change
records who made it. The rules the schema enforces are checked first, so an error
says what is wrong instead of printing a constraint name.
"""

import getpass
import json
import sqlite3
import sys

from . import db
from .convert import classify_login

KINDS = ("on-prem", "proxy", "github", "gitlab", "default", "EC2")
USAGES = ("cw", "personal", "shared")
LOGIN_KINDS = ("personal", "service", "system")
ROLES = ("default", "direct", "sudo")
FLAGS = ("P", "U")


class EditError(Exception):
    """A rule was broken. The message says which one."""


def _who(args) -> str:
    return args.who or getpass.getuser() or "unknown"


def _log(conn, who, action, table, row_id, detail) -> None:
    conn.execute(
        "INSERT INTO change_log (who, action, table_name, row_id, detail) VALUES (?, ?, ?, ?, ?)",
        (who, action, table, row_id, json.dumps(detail, sort_keys=True, default=str)),
    )


def _check_choice(name: str, value, allowed) -> None:
    if value is not None and value not in allowed:
        raise EditError(f"{name} must be one of {', '.join(allowed)}; got {value!r}")


def _host_id(conn, name: str) -> int:
    row = conn.execute("SELECT id FROM host WHERE name = ?", (name,)).fetchone()
    if row is None:
        raise EditError(f"no host named {name!r}")
    return row["id"]


def _login_id(conn, user: str) -> int:
    row = conn.execute("SELECT id FROM login WHERE user = ?", (user,)).fetchone()
    if row is None:
        raise EditError(f"no login named {user!r}; add it with: login add {user}")
    return row["id"]


def _person_id(conn, name: str) -> int:
    row = conn.execute("SELECT id FROM person WHERE name = ?", (name,)).fetchone()
    if row is None:
        raise EditError(f"no person named {name!r}")
    return row["id"]


def _proxy_id(conn, proxy: str | None, host_name: str | None):
    if proxy is None or proxy == "none":
        return None
    if host_name is not None and proxy == host_name:
        raise EditError(f"{host_name} cannot be its own proxy")
    row = conn.execute("SELECT id FROM host WHERE name = ?", (proxy,)).fetchone()
    if row is None:
        raise EditError(f"proxy {proxy!r} is not a host")
    return row["id"]


# --- hosts -------------------------------------------------------------------

def host_add(conn, who, name, kind, usage, hostname, port, proxy, forward_agent,
             identities_only, keys) -> None:
    _check_choice("kind", kind, KINDS)
    _check_choice("usage", usage, USAGES)
    if conn.execute("SELECT 1 FROM host WHERE name = ?", (name,)).fetchone():
        raise EditError(f"a host named {name!r} already exists")
    if conn.execute("SELECT 1 FROM host_name WHERE pattern = ?", (name,)).fetchone():
        raise EditError(f"{name!r} is already a name of another host")
    proxy_id = _proxy_id(conn, proxy, name)
    order = conn.execute(
        "SELECT COALESCE(MAX(sort_order), 0) + 1 FROM host WHERE kind <> 'default'").fetchone()[0]
    cur = conn.execute(
        """INSERT INTO host (name, kind, usage, hostname, port, proxy_id,
                             forward_agent, identities_only, sort_order)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (name, kind, usage, hostname, port, proxy_id,
         1 if forward_agent else 0, 1 if identities_only else 0, order),
    )
    host_id = cur.lastrowid
    for seq, path in enumerate(keys or []):
        conn.execute("INSERT INTO host_key (host_id, seq, path) VALUES (?, ?, ?)", (host_id, seq, path))
    _log(conn, who, "insert", "host", host_id, {
        "name": name, "kind": kind, "usage": usage, "hostname": hostname, "port": port,
        "proxy": proxy, "forward_agent": bool(forward_agent),
        "identities_only": bool(identities_only), "keys": keys or [],
    })


def host_update(conn, who, name, changes: dict) -> None:
    host_id = _host_id(conn, name)
    if not changes:
        raise EditError("nothing to change; give at least one option")
    _check_choice("kind", changes.get("kind"), KINDS)
    _check_choice("usage", changes.get("usage"), USAGES)
    values = {}
    for column, value in changes.items():
        if column == "proxy":
            values["proxy_id"] = _proxy_id(conn, value, name)
        elif column in ("forward_agent", "identities_only"):
            values[column] = 1 if value else 0
        else:
            values[column] = value
    assignments = ", ".join(f"{column} = ?" for column in values)
    conn.execute(f"UPDATE host SET {assignments} WHERE id = ?", (*values.values(), host_id))
    _log(conn, who, "update", "host", host_id, {"name": name, **changes})


def host_remove(conn, who, name) -> None:
    host_id = _host_id(conn, name)
    users = [r[0] for r in conn.execute("SELECT name FROM host WHERE proxy_id = ?", (host_id,))]
    if users:
        raise EditError(f"{name} is the proxy of: {', '.join(users)}; change those first")
    conn.execute("DELETE FROM host WHERE id = ?", (host_id,))
    _log(conn, who, "delete", "host", host_id, {"name": name})


def key_add(conn, who, name, path) -> None:
    host_id = _host_id(conn, name)
    if conn.execute("SELECT 1 FROM host_key WHERE host_id = ? AND path = ?", (host_id, path)).fetchone():
        raise EditError(f"{name} already offers {path}")
    seq = conn.execute("SELECT COALESCE(MAX(seq) + 1, 0) FROM host_key WHERE host_id = ?",
                       (host_id,)).fetchone()[0]
    conn.execute("INSERT INTO host_key (host_id, seq, path) VALUES (?, ?, ?)", (host_id, seq, path))
    _log(conn, who, "insert", "host_key", host_id, {"host": name, "path": path})


def key_remove(conn, who, name, path) -> None:
    host_id = _host_id(conn, name)
    cur = conn.execute("DELETE FROM host_key WHERE host_id = ? AND path = ?", (host_id, path))
    if cur.rowcount == 0:
        raise EditError(f"{name} does not offer {path}")
    rows = conn.execute("SELECT path FROM host_key WHERE host_id = ? ORDER BY seq", (host_id,)).fetchall()
    conn.execute("DELETE FROM host_key WHERE host_id = ?", (host_id,))
    for seq, (remaining,) in enumerate(rows):
        conn.execute("INSERT INTO host_key (host_id, seq, path) VALUES (?, ?, ?)", (host_id, seq, remaining))
    _log(conn, who, "delete", "host_key", host_id, {"host": name, "path": path})


# --- logins ------------------------------------------------------------------

def login_add(conn, who, user, kind) -> None:
    _check_choice("kind", kind, LOGIN_KINDS)
    if conn.execute("SELECT 1 FROM login WHERE user = ?", (user,)).fetchone():
        raise EditError(f"login {user!r} already exists")
    kind = kind or classify_login(user)
    cur = conn.execute("INSERT INTO login (user, kind) VALUES (?, ?)", (user, kind))
    _log(conn, who, "insert", "login", cur.lastrowid, {"user": user, "kind": kind})


def login_remove(conn, who, user) -> None:
    login_id = _login_id(conn, user)
    try:
        conn.execute("DELETE FROM login WHERE id = ?", (login_id,))
    except sqlite3.IntegrityError:
        raise EditError(f"login {user!r} is still used by a host, a link or a person") from None
    _log(conn, who, "delete", "login", login_id, {"user": user})


# --- links (host_login) ------------------------------------------------------

def link_set(conn, who, host, user, role, flag, person) -> None:
    _check_choice("role", role, ROLES)
    host_id = _host_id(conn, host)
    login_id = _login_id(conn, user)
    person_id = _person_id(conn, person) if person else None
    if person_id is not None and role != "default":
        raise EditError("--person is only for default links")
    if role == "sudo":
        if flag not in FLAGS:
            raise EditError("a sudo link needs --flag P or U")
        kind = conn.execute("SELECT kind FROM login WHERE id = ?", (login_id,)).fetchone()["kind"]
        if kind != "service":
            raise EditError(f"{user} is a {kind} login; only service logins can be sudo targets")
        conn.execute("DELETE FROM host_login WHERE host_id = ? AND role = 'sudo' AND flag = ?",
                     (host_id, flag))
    elif flag is not None:
        raise EditError("--flag is only for sudo links")
    elif role == "default":
        conn.execute("DELETE FROM host_login WHERE host_id = ? AND role = 'default' AND person_id IS ?",
                     (host_id, person_id))
    else:
        conn.execute("DELETE FROM host_login WHERE host_id = ? AND login_id = ? AND role = 'direct'",
                     (host_id, login_id))
    cur = conn.execute(
        "INSERT INTO host_login (host_id, login_id, role, flag, person_id) VALUES (?, ?, ?, ?, ?)",
        (host_id, login_id, role, flag, person_id),
    )
    _log(conn, who, "insert", "host_login", cur.lastrowid, {
        "host": host, "login": user, "role": role, "flag": flag, "person": person})


def link_remove(conn, who, host, role, flag, person) -> None:
    _check_choice("role", role, ROLES)
    host_id = _host_id(conn, host)
    person_id = _person_id(conn, person) if person else None
    cur = conn.execute(
        """DELETE FROM host_login
           WHERE host_id = ? AND role = ? AND flag IS ? AND person_id IS ?""",
        (host_id, role, flag, person_id),
    )
    if cur.rowcount == 0:
        raise EditError(f"{host} has no {role} link matching those options")
    _log(conn, who, "delete", "host_login", None, {
        "host": host, "role": role, "flag": flag, "person": person})


# --- persons -----------------------------------------------------------------

def person_add(conn, who, name, user) -> None:
    if conn.execute("SELECT 1 FROM person WHERE name = ?", (name,)).fetchone():
        raise EditError(f"person {name!r} already exists")
    if not conn.execute("SELECT 1 FROM login WHERE user = ?", (user,)).fetchone():
        conn.execute("INSERT INTO login (user, kind) VALUES (?, ?)", (user, classify_login(user)))
    login_id = _login_id(conn, user)
    cur = conn.execute("INSERT INTO person (name, login_id) VALUES (?, ?)", (name, login_id))
    _log(conn, who, "insert", "person", cur.lastrowid, {"name": name, "login": user})


def person_remove(conn, who, name) -> None:
    person_id = _person_id(conn, name)
    conn.execute("DELETE FROM person WHERE id = ?", (person_id,))
    _log(conn, who, "delete", "person", person_id, {"name": name})


# --- command line ------------------------------------------------------------

def _run(args, action) -> int:
    conn = db.connect(args.db)
    try:
        with conn:
            action(conn, _who(args), args)
    except EditError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    except sqlite3.IntegrityError as exc:
        print(f"error: the database refused this change: {exc}", file=sys.stderr)
        return 1
    finally:
        conn.close()
    return 0


def _yes_no(value: str | None) -> bool | None:
    if value is None:
        return None
    if value not in ("yes", "no"):
        raise EditError("use yes or no")
    return value == "yes"


def _host_cmd(args, conn, who, a) -> None:
    if args.host_action == "add":
        host_add(conn, who, a.name, a.kind, a.usage, a.hostname, a.port, a.proxy,
                 _yes_no(a.forward_agent), _yes_no(a.identities_only), a.key)
    elif args.host_action == "update":
        changes = {k: v for k, v in {
            "kind": a.kind, "usage": a.usage, "hostname": a.hostname, "port": a.port,
            "proxy": a.proxy,
            "forward_agent": _yes_no(a.forward_agent),
            "identities_only": _yes_no(a.identities_only),
        }.items() if v is not None}
        host_update(conn, who, a.name, changes)
    elif args.host_action == "remove":
        host_remove(conn, who, a.name)
    elif args.host_action == "key-add":
        key_add(conn, who, a.name, a.path)
    elif args.host_action == "key-remove":
        key_remove(conn, who, a.name, a.path)


def _login_cmd(args, conn, who, a) -> None:
    if args.login_action == "add":
        login_add(conn, who, a.user, a.kind)
    else:
        login_remove(conn, who, a.user)


def _link_cmd(args, conn, who, a) -> None:
    if args.link_action == "set":
        link_set(conn, who, a.host, a.user, a.role, a.flag, a.person)
    else:
        link_remove(conn, who, a.host, a.role, a.flag, a.person)


def _person_cmd(args, conn, who, a) -> None:
    if args.person_action == "add":
        person_add(conn, who, a.name, a.login)
    else:
        person_remove(conn, who, a.name)


def _host_options(p, required: bool) -> None:
    p.add_argument("--kind", choices=KINDS, default=None)
    p.add_argument("--usage", choices=USAGES, default=None)
    p.add_argument("--hostname", default=None)
    p.add_argument("--port", type=int, default=None)
    p.add_argument("--proxy", default=None, help="a host name, or 'none' to clear (update only)")
    p.add_argument("--forward-agent", choices=("yes", "no"), default=None)
    p.add_argument("--identities-only", choices=("yes", "no"), default=None)


def register(sub) -> None:
    """Add the edit commands to the CLI's subparsers."""

    def common(p):
        p.add_argument("--db", required=True)
        p.add_argument("--who", default=None, help="who makes the change (default: the login user)")

    host = sub.add_parser("host", help="add, update, remove hosts and their keys")
    host_sub = host.add_subparsers(dest="host_action", required=True)
    p = host_sub.add_parser("add", help="add a host")
    common(p)
    p.add_argument("name")
    p.add_argument("--kind", choices=KINDS, required=True)
    p.add_argument("--usage", choices=USAGES, default="cw")
    p.add_argument("--hostname", default=None)
    p.add_argument("--port", type=int, default=None)
    p.add_argument("--proxy", default=None)
    p.add_argument("--forward-agent", choices=("yes", "no"), default="no")
    p.add_argument("--identities-only", choices=("yes", "no"), default="no")
    p.add_argument("--key", action="append", default=[], help="an IdentityFile path; repeat for more")
    p = host_sub.add_parser("update", help="change a host's kind, usage, hostname, port, proxy or flags")
    common(p)
    p.add_argument("name")
    _host_options(p, required=False)
    p = host_sub.add_parser("remove", help="remove a host (refused while it is a proxy)")
    common(p)
    p.add_argument("name")
    p = host_sub.add_parser("key-add", help="add an IdentityFile path to a host")
    common(p)
    p.add_argument("name")
    p.add_argument("path")
    p = host_sub.add_parser("key-remove", help="remove an IdentityFile path from a host")
    common(p)
    p.add_argument("name")
    p.add_argument("path")
    host.set_defaults(func=lambda a: _run(a, lambda c, w, x: _host_cmd(a, c, w, x)))

    login = sub.add_parser("login", help="add or remove a login (username)")
    login_sub = login.add_subparsers(dest="login_action", required=True)
    p = login_sub.add_parser("add", help="add a login; the kind is classified from the name unless given")
    common(p)
    p.add_argument("user")
    p.add_argument("--kind", choices=LOGIN_KINDS, default=None)
    p = login_sub.add_parser("remove", help="remove a login (refused while in use)")
    common(p)
    p.add_argument("user")
    login.set_defaults(func=lambda a: _run(a, lambda c, w, x: _login_cmd(a, c, w, x)))

    link = sub.add_parser("link", help="set or remove how a host is reached (default, direct, sudo)")
    link_sub = link.add_subparsers(dest="link_action", required=True)
    p = link_sub.add_parser("set", help="set a host's login for a role")
    common(p)
    p.add_argument("host")
    p.add_argument("user")
    p.add_argument("--role", choices=ROLES, required=True)
    p.add_argument("--flag", choices=FLAGS, default=None, help="sudo links only: P or U")
    p.add_argument("--person", default=None, help="default links only: this person's login")
    p = link_sub.add_parser("remove", help="remove a host's link for a role")
    common(p)
    p.add_argument("host")
    p.add_argument("--role", choices=ROLES, required=True)
    p.add_argument("--flag", choices=FLAGS, default=None)
    p.add_argument("--person", default=None)
    link.set_defaults(func=lambda a: _run(a, lambda c, w, x: _link_cmd(a, c, w, x)))

    person = sub.add_parser("person", help="add or remove a person and their login")
    person_sub = person.add_subparsers(dest="person_action", required=True)
    p = person_sub.add_parser("add", help="add a person with their login")
    common(p)
    p.add_argument("name")
    p.add_argument("--login", required=True)
    p = person_sub.add_parser("remove", help="remove a person and their personal links")
    common(p)
    p.add_argument("name")
    person.set_defaults(func=lambda a: _run(a, lambda c, w, x: _person_cmd(a, c, w, x)))
