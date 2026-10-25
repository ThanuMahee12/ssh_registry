"""Open the registry database.

There is one schema, schema.sql. A new database gets it on first open. A database
at any other version is refused: the database is built from the source files, so
it is rebuilt with `ssh-registry convert` rather than migrated.
"""

import sqlite3
from pathlib import Path

SCHEMA = Path(__file__).with_name("schema.sql")
SCHEMA_VERSION = 2


def connect(path: str | Path) -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    found = conn.execute("PRAGMA user_version").fetchone()[0]
    if found == 0:
        conn.executescript(SCHEMA.read_text(encoding="utf-8"))
    elif found != SCHEMA_VERSION:
        conn.close()
        raise RuntimeError(
            f"{path} is schema v{found}; this code expects v{SCHEMA_VERSION}. "
            f"Rebuild it with: ssh-registry convert --db {path}"
        )
    return conn
