-- ssh-registry schema, version 2 (the only schema).
-- The database is built from the source files; there are no migrations. A database
-- at any other version is rebuilt with `ssh-registry convert`.
-- The database is the source of truth. The ssh config is generated from it.
-- Applied once by db.connect(); PRAGMA user_version records the version.

CREATE TABLE meta (
  key   TEXT PRIMARY KEY,
  value TEXT NOT NULL
);

-- Every username, stored once.
--   personal: a person's own login (bthanujan.mahendran, ec2-user)
--   service:  a service account, the only kind allowed as a sudo target (svc_*)
--   system:   a shared login (git, bench)
CREATE TABLE login (
  id   INTEGER PRIMARY KEY,
  user TEXT NOT NULL UNIQUE CHECK (user <> ''),
  kind TEXT NOT NULL DEFAULT 'personal' CHECK (kind IN ('personal', 'service', 'system'))
);

-- One row per server, git host, or the Host * defaults.
CREATE TABLE host (
  id              INTEGER PRIMARY KEY,
  name            TEXT NOT NULL UNIQUE CHECK (name <> ''),
  kind            TEXT NOT NULL CHECK (kind IN ('on-prem','proxy','github','gitlab','default','EC2','bench','bench_env','devhub')),
  usage           TEXT NOT NULL DEFAULT 'cw' CHECK (usage IN ('cw','personal','shared')),
  hostname        TEXT CHECK (hostname IS NULL OR hostname <> ''),
  port            INTEGER CHECK (port IS NULL OR port BETWEEN 1 AND 65535),
  proxy_id        INTEGER REFERENCES host (id) ON DELETE RESTRICT,
  forward_agent   INTEGER NOT NULL DEFAULT 0 CHECK (forward_agent IN (0,1)),
  identities_only INTEGER NOT NULL DEFAULT 0 CHECK (identities_only IN (0,1)),
  sort_order      INTEGER NOT NULL,
  CHECK (proxy_id IS NULL OR proxy_id <> id)
);
CREATE INDEX idx_host_proxy ON host (proxy_id);

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

-- A person: someone whose personal login is used on the hosts they reach.
CREATE TABLE person (
  id       INTEGER PRIMARY KEY,
  name     TEXT NOT NULL UNIQUE CHECK (name <> ''),
  login_id INTEGER NOT NULL REFERENCES login (id) ON DELETE RESTRICT
);

-- Which logins a host is reached with, and how.
--   default: the login ssh uses. person_id NULL = shared, for everyone;
--            person_id set = that person's login, which wins over shared.
--   direct:  another login that works directly.
--   sudo:    an account reached with `sudo su -`, flag P or U. Service logins only.
CREATE TABLE host_login (
  id        INTEGER PRIMARY KEY,
  host_id   INTEGER NOT NULL REFERENCES host (id) ON DELETE CASCADE,
  login_id  INTEGER NOT NULL REFERENCES login (id) ON DELETE RESTRICT,
  role      TEXT NOT NULL CHECK (role IN ('default', 'direct', 'sudo')),
  flag      TEXT CHECK (flag IS NULL OR flag IN ('P', 'U')),
  person_id INTEGER REFERENCES person (id) ON DELETE CASCADE,
  CHECK ((role = 'sudo') = (flag IS NOT NULL)),
  CHECK (person_id IS NULL OR role = 'default')
);
CREATE UNIQUE INDEX one_shared_default ON host_login (host_id)
  WHERE role = 'default' AND person_id IS NULL;
CREATE UNIQUE INDEX one_person_default ON host_login (host_id, person_id)
  WHERE role = 'default' AND person_id IS NOT NULL;
CREATE UNIQUE INDEX one_sudo_flag ON host_login (host_id, flag) WHERE role = 'sudo';
CREATE INDEX idx_host_login_login ON host_login (login_id);

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
LEFT JOIN host_login hl ON hl.host_id = h.id AND hl.role = 'default' AND hl.person_id IS NULL
LEFT JOIN login l ON l.id = hl.login_id
LEFT JOIN host p ON p.id = h.proxy_id;

PRAGMA user_version = 2;
