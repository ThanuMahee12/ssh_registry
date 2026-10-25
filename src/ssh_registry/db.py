"""Open the registry database. Schema is applied on first open, and migrated forward.

Each version step is a file: schema.sql (v1), schema_v2.sql (v2). A database
at version N gets every later step in order. A database newer than this code
is refused, so an old program never writes a schema it does not understand.
"""

import sqlite3
from pathlib import Path

HERE = Path(__file__).parent
SCHEMA_V1 = HERE / "schema.sql"
SCHEMA_V2 = HERE / "schema_v2.sql"
SCHEMA_VERSION = 2


def connect(path: str | Path) -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    found = conn.execute("PRAGMA user_version").fetchone()[0]
    if found > SCHEMA_VERSION:
        conn.close()
        raise RuntimeError(f"{path} is schema v{found}; this code knows v{SCHEMA_VERSION}")
    if found == 0:
        conn.executescript(SCHEMA_V1.read_text(encoding="utf-8"))
        found = 1
    if found == 1:
        conn.executescript(SCHEMA_V2.read_text(encoding="utf-8"))
        found = 2
    return conn
