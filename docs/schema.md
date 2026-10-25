# Schema

The schema is `src/ssh_registry/schema.sql`, version 2 (`PRAGMA user_version = 2`).
It is the only schema. A database at any other version is refused, and rebuilt
with `convert`.

Foreign keys are on for every connection. Journal mode is WAL while open.

## Tables

### `login`

Every username, stored once.

| Column | Type | Notes |
|---|---|---|
| `id` | INTEGER PK | |
| `user` | TEXT, unique | Non-empty. Examples: `bthanujan.mahendran`, `git`, `svc_dat_alchemy`. |
| `kind` | TEXT | `personal`, `service` or `system`. Default `personal`. |

Kinds:
- `personal`: a person's own login.
- `service`: a service account (`svc_*`). The only kind allowed as a sudo target.
- `system`: a shared login (`git`, `bench`).

The converter sets the kind from the name: `svc_*` is `service`, `git` and `bench`
are `system`, and everything else is `personal`.

### `host`

One row per server, git host, or the `Host *` defaults.

| Column | Type | Notes |
|---|---|---|
| `id` | INTEGER PK | |
| `name` | TEXT, unique | The name you type. Non-empty. |
| `kind` | TEXT | `on-prem`, `proxy`, `github`, `gitlab`, `default` or `EC2`. |
| `usage` | TEXT | `cw`, `personal` or `shared`. Default `cw`. Decides which generated file it goes in. |
| `hostname` | TEXT, nullable | `HostName` (IP or DNS). Null for group hosts such as `alchmy_ny5p*`. |
| `port` | INTEGER, nullable | 1–65535. |
| `proxy_id` | INTEGER, nullable | `ProxyJump`: another host. Cannot be itself. |
| `forward_agent` | 0/1 | `ForwardAgent yes` when 1. |
| `identities_only` | 0/1 | `IdentitiesOnly yes` when 1. |
| `sort_order` | INTEGER | Generation order. Set from the source file order. |

Usage values:
- `cw`: company hosts.
- `personal`: your own git hosts (GitHub, GitLab).
- `shared`: the `Host *` defaults. Included last in the generated config.

### `host_name`

Extra names that select a host. For example, the `alchmy_ny5p01*` pattern selects
the host `alchmy_ny5p01`.

| Column | Type | Notes |
|---|---|---|
| `pattern` | TEXT PK | Non-empty. |
| `host_id` | INTEGER | Cascades when the host is deleted. |

### `host_key`

The keys a host offers, in order. Paths only, never key material.

| Column | Type | Notes |
|---|---|---|
| `host_id` | INTEGER | Part of the primary key. |
| `seq` | INTEGER | Order. Part of the primary key. |
| `path` | TEXT | Non-empty. Example: `~/.ssh/id_ed25519`. |

### `person`

Someone whose personal login is used on the hosts they reach.

| Column | Type | Notes |
|---|---|---|
| `id` | INTEGER PK | |
| `name` | TEXT, unique | Also the output directory name for `generate --person`. |
| `login_id` | INTEGER | The person's login. |

### `host_login`

How a host is reached. One row per link.

| Column | Type | Notes |
|---|---|---|
| `id` | INTEGER PK | |
| `host_id` | INTEGER | |
| `login_id` | INTEGER | The login to use. |
| `role` | TEXT | `default`, `direct` or `sudo`. |
| `flag` | TEXT, nullable | `P` or `U`. Required for `sudo`, null otherwise. |
| `person_id` | INTEGER, nullable | Only for `default` rows. Null means shared, for everyone. |

Roles:
- `default`: the login `ssh` uses. At most one shared default per host, and at most one default per person per host.
- `direct`: another login that works directly. The converter doesn't create these yet.
- `sudo`: an account reached with `sudo su -`. Generated as a `Host <name>_svc<flag>` block with `RemoteCommand sudo su - <login>`. Only service logins are allowed here.

Resolution for a default login, with `--person NAME`: the person's own row wins; otherwise the shared row (`person_id` null) is used. Without a person, only shared rows apply.

Indexes that enforce this:
- `one_shared_default`: one shared default per host.
- `one_person_default`: one default per person per host.
- `one_sudo_flag`: one `P` and one `U` per host.

### `host_option`

Other ssh keywords that have no column. For example, `ServerAliveInterval` on the
`Host *` row, or `RequestTTY`.

| Column | Type | Notes |
|---|---|---|
| `host_id` | INTEGER | Part of the primary key. |
| `key` | TEXT | Part of the primary key. |
| `seq` | INTEGER | Part of the primary key. Keeps repeats in order. |
| `value` | TEXT | |

### `meta`

A key/value table. It exists in the schema, but nothing writes to it yet.

### `change_log`

Records who changed what: `who`, `action` (`insert`, `update` or `delete`),
`table_name`, `row_id`, and a `detail` field. The schema has it, but nothing
writes to it yet.

### `v_host` (view)

One row per host, for listing. It shows the shared default login, not a person's.

## Rules the converter enforces

- A sudo target must be a `service` login. Any other kind is refused.
- A sudo account must target a group host that is defined.
- A `ProxyJump` must name a host that is defined.
- The first `User` for a host (per person, or shared) wins; a later one is ignored.

## Rules the database enforces

- `host.kind`, `host.usage`, `login.kind`, `host_login.role`, `host_login.flag` and `host.port` only accept their listed values.
- A host cannot proxy through itself.
- Names are unique: host name, login user, person name, and host-name pattern.
- A `flag` is required for `sudo` rows, and forbidden for the others.
- `person_id` is only allowed on `default` rows.
- At most one shared default per host, and one default per person per host.
- Deleting a host cascades to its names, keys, options and login links.
