# ssh_registry

The host registry for shellrc. Every server, git host and login is stored once,
in a SQLite database. The ssh config files are generated from that database.

> PRIVATE: keep this repository private. The data includes production IPs,
> jump hosts and service-account names.

## What is where

| Path | What |
|---|---|
| `src/ssh_registry/schema.sql` | The schema. The only schema; see [docs/schema.md](docs/schema.md). |
| `src/ssh_registry/convert.py` | One-time import from the source files into the database. |
| `src/ssh_registry/render.py` | Generates the ssh config text from the database. |
| `src/ssh_registry/cli.py` | Command line: `convert`, `generate`, `list`, `check`. |
| `src/ssh_registry/db.py` | Opens the database and applies the schema. |
| `src/ssh_registry/sshconf.py` | Parses the source ssh config files. |
| `ssh/shared/` | The source files the database was converted from. Kept until the database is the only source. |
| `data/hosts.sqlite` | The database, when it is committed. See [Database](#database). |
| `scripts/generate_config.sh` | Generates the configs and checks every host with `ssh -G` before replacing anything. |
| `scripts/verify-hosts.sh` | Checks the host definitions in `ssh/shared/`. |
| `tests/test_equivalence.py` | Tests, including that the generated config resolves every host like the source files. |

## Concepts

- **Host:** one server, git host or the `Host *` defaults. Has a name, a kind, a usage, and a hostname.
- **Usage:** `cw` (company hosts), `personal` (your own git hosts), or `shared` (the defaults). Each usage gets its own generated file.
- **Login:** a username, stored once. Each login has a kind: `personal`, `service` or `system`.
- **Person:** someone whose personal login is used on the hosts they reach.
- **Host login:** how a host is reached. A `default` login is what `ssh` uses; a `sudo` login is an account reached with `sudo su -` (flag `P` or `U`, service logins only).

## Commands

Run from the repository root, with `src` on the Python path:

```
export PYTHONPATH="$PWD/src"        # Windows PowerShell: $env:PYTHONPATH = "$PWD\src"

python -m ssh_registry.cli convert --db data/hosts.sqlite           # one-time: source files -> database
python -m ssh_registry.cli check --db data/hosts.sqlite             # integrity and foreign keys
python -m ssh_registry.cli list --db data/hosts.sqlite              # one line per host
python -m ssh_registry.cli generate --db data/hosts.sqlite --dir ~/.shellrc
python -m ssh_registry.cli generate --db data/hosts.sqlite --dir ~/.shellrc --person thanujan
```

`generate` writes four files into `--dir`:

| File | Contents |
|---|---|
| `cw.config` | Hosts with usage `cw`, and the `_svcP`/`_svcU` account blocks. |
| `personal.config` | Hosts with usage `personal`. |
| `shared.config` | The `Host *` defaults. |
| `shellrc.config` | Includes the three files above, in that order, so the defaults stay last. |

With `--person NAME`, the files go into `DIR/NAME/`. Each host's login is then
that person's own default if they have one, otherwise the shared default. Without
`--person`, only the shared logins are used.

`scripts/generate_config.sh` runs the same generation into a temp directory, checks
every literal host in the combined result with `ssh -G`, and only then moves the
files into place. A bad database leaves the existing files untouched.

## Editing

The database can be edited directly with these commands. Each change is one
transaction, is checked against the schema's rules, and writes a row to
`change_log` with who made it (`--who`, default: the login user).

```
python -m ssh_registry.cli host add NAME --kind on-prem --usage cw --hostname 10.0.0.5 --proxy sf_jump --key ~/.ssh/id_ed25519
python -m ssh_registry.cli host update NAME --port 2222 --proxy none --forward-agent yes
python -m ssh_registry.cli host remove NAME                 # refused while it is a proxy
python -m ssh_registry.cli host key-add NAME PATH
python -m ssh_registry.cli host key-remove NAME PATH
python -m ssh_registry.cli login add USER [--kind personal|service|system]
python -m ssh_registry.cli login remove USER                # refused while in use
python -m ssh_registry.cli link set HOST USER --role default [--person NAME]
python -m ssh_registry.cli link set HOST SVC --role sudo --flag P    # service logins only
python -m ssh_registry.cli link set HOST USER --role direct
python -m ssh_registry.cli link remove HOST --role default [--person NAME]
python -m ssh_registry.cli person add NAME --login USER
python -m ssh_registry.cli person remove NAME
```

`host update` changes the kind, usage, hostname, port, proxy (or `none`) and the
`forward_agent` and `identities_only` flags. A host's kind and usage are checked
against the allowed values, and a proxy cannot be the host itself.

Edits are made to the database. The source files in `ssh/shared/` are not updated
by these commands, so a fresh `convert` would bring the old values back.

## Database

The database is the source of truth; the ssh config is always generated from it,
and nothing edits the generated files by hand.

The database is rebuilt from `ssh/shared/` with `convert`. An older database is
refused, with the rebuild command in the error message. There are no migrations:
the schema is one file, and a database at a different version is rebuilt.

Whether `data/hosts.sqlite` is committed is a decision still open. The file is
currently tracked on some branches and ignored on none, so check `git status`
before committing it.

## Tests

```
python tests/test_equivalence.py
```

The equivalence test converts the source files, generates the config for `thanujan`,
and compares `ssh -G` for every host name (including the `_svcP`/`_svcU` accounts)
against the source files concatenated in the same order. It also checks the
schema rules: the host kind, one default login per host and per person, and a
refused old schema.

Windows OpenSSH does not resolve absolute `Include` paths, so the test concatenates
the sources instead of using `Include`. The result is the same.

## Not done yet

- **Change log for the source files:** the edit commands log their changes; `convert` does not, and the source files have no history of their own.
- **Direct logins:** the `direct` role exists in the schema, but `convert` doesn't create any.
- **Second person:** only `thanujan` is in the source data. Other people's hosts and logins need adding.
- **Wiring on machines:** `~/.ssh/config` must include `~/.shellrc/shellrc.config` on each machine. That's a manual step; see shellrc's setup guide.
- **Long-term source:** the source files in `ssh/shared/` are still the input for `convert`. Moving the source of truth to the database alone is a later step.
