-- ssh-registry schema, version 1.
-- The database is the source of truth. The ssh config is generated from it.
-- Applied once by db.connect(); PRAGMA user_version records the version.

CREATE TABLE meta (
  key   TEXT PRIMARY KEY,
  value TEXT NOT NULL
);

-- Every username, stored once: people, git, ec2-user, service accounts.
CREATE TABLE login (
  id   INTEGER PRIMARY KEY,
  user TEXT NOT NULL UNIQUE CHECK (user <> '')
);

-- One row per server, git host, or the Host * defaults.
CREATE TABLE host (
  id              INTEGER PRIMARY KEY,
  name            TEXT NOT NULL UNIQUE CHECK (name <> ''),
  kind            TEXT NOT NULL CHECK (kind IN ('on-prem','proxy','github','gitlab','default','EC2')),
  usage           TEXT NOT NULL DEFAULT 'work' CHECK (usage IN ('work','personal','shared')),
  hostname        TEXT CHECK (hostname IS NULL OR hostname <> ''),
  port            INTEGER CHECK (port IS NULL OR port BETWEEN 1 AND 65535),
  login_id        INTEGER REFERENCES login (id) ON DELETE RESTRICT,
  proxy_id        INTEGER REFERENCES host (id) ON DELETE RESTRICT,
  forward_agent   INTEGER NOT NULL DEFAULT 0 CHECK (forward_agent IN (0,1)),
  identities_only INTEGER NOT NULL DEFAULT 0 CHECK (identities_only IN (0,1)),
  sort_order      INTEGER NOT NULL,
  CHECK (proxy_id IS NULL OR proxy_id <> id)
);
CREATE INDEX idx_host_proxy ON host (proxy_id);
CREATE INDEX idx_host_login ON host (login_id);

-- Extra names that select a host, e.g. alchmy_ny5p01* for alchmy_ny5p01.
CREATE TABLE host_name (
  pattern TEXT PRIMARY KEY CHECK (pattern <> ''),
  host_id INTEGER NOT NULL REFERENCES host (id) ON DELETE CASCADE
);
CREATE INDEX idx_host_name_host ON host_name (host_id);

-- Keys a host offers, in order. Paths only, never key material.
CREATE TABLE host_key (
  host_id INTEGER NOT NULL REFERENCES host (id) ON DELETE CASCADE,
  seq     INTEGER NOT NULL CHECK (seq >= 0),
  path    TEXT NOT NULL CHECK (path <> ''),
  PRIMARY KEY (host_id, seq)
);

-- Accounts a group host switches to with `sudo su -` (interactive only).
CREATE TABLE account (
  id       INTEGER PRIMARY KEY,
  host_id  INTEGER NOT NULL REFERENCES host (id) ON DELETE CASCADE,
  flag     TEXT NOT NULL CHECK (flag <> ''),
  login_id INTEGER NOT NULL REFERENCES login (id) ON DELETE RESTRICT,
  UNIQUE (host_id, flag)
);

-- Other ssh keywords that have no column.
CREATE TABLE host_option (
  host_id INTEGER NOT NULL REFERENCES host (id) ON DELETE CASCADE,
  key     TEXT NOT NULL CHECK (key <> ''),
  seq     INTEGER NOT NULL CHECK (seq >= 0),
  value   TEXT NOT NULL,
  PRIMARY KEY (host_id, key, seq)
);

-- Who changed what. Written by the CLI on every change.
CREATE TABLE change_log (
  id         INTEGER PRIMARY KEY,
  at         TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
  who        TEXT NOT NULL CHECK (who <> ''),
  action     TEXT NOT NULL CHECK (action IN ('insert','update','delete')),
  table_name TEXT NOT NULL,
  row_id     INTEGER,
  detail     TEXT
);

-- Flat view for listing hosts.
CREATE VIEW v_host AS
SELECT h.id, h.name, h.kind, h.usage, h.hostname, h.port,
       l.user AS login, p.name AS proxy, h.forward_agent, h.identities_only
FROM host h
LEFT JOIN login l ON l.id = h.login_id
LEFT JOIN host p ON p.id = h.proxy_id;

PRAGMA user_version = 1;
