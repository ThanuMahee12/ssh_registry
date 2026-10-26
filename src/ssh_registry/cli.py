"""ssh-registry command line.

    ssh-registry convert  --db DB [SHARED_DIR]   one-time: source files -> database
    ssh-registry generate --db DB [--dir DIR]    write cw/personal/shared configs and shellrc.config
    ssh-registry list     --db DB                one line per host
    ssh-registry check    --db DB                integrity and foreign-key checks
"""

import argparse
import sys
from pathlib import Path

from . import __version__, convert, db, edit, render

# Order a machine reads the source files: the person layer first, the work hosts
# in their explicit order, and the Host * defaults last.
WORK_ORDER = ["proxy", "bench", "alchemy", "cwiq-pipe", "sli", "misc", "github", "global"]


def source_files(shared: Path) -> list[Path]:
    files = sorted((shared / "thanujan").glob("*.config"))
    files += [shared / "work" / f"{name}.config" for name in WORK_ORDER]
    missing = [str(f) for f in files if not f.is_file()]
    if missing:
        raise SystemExit("missing source files: " + ", ".join(missing))
    return files


def cmd_convert(args) -> int:
    conn = db.connect(args.db)
    try:
        convert.convert(conn, source_files(Path(args.shared)))
        hosts = conn.execute("SELECT COUNT(*) FROM host").fetchone()[0]
    finally:
        conn.close()
    print(f"converted into {args.db}: {hosts} hosts")
    return 0


def _ask(build):
    """Build and run a questionary prompt. A terminal that can't show prompts stops with a message."""
    try:
        return build().ask()
    except Exception as exc:  # e.g. Git Bash on Windows: no Windows console for the prompt
        raise SystemExit(f"prompt unavailable here ({type(exc).__name__}); run the command in PowerShell or cmd") from None


def ask_dir() -> str:
    """Ask for the output folder with questionary. Only possible at a terminal; there is no default."""
    if not sys.stdin.isatty():
        raise SystemExit("generate: give --dir; there is no terminal to ask for it")
    import questionary
    answer = _ask(lambda: questionary.path("Folder to write the generated config into:"))
    if not answer:
        raise SystemExit("generate: no folder given")
    return answer


def cmd_init(args) -> int:
    """Create the registry database: from the existing source files, or empty.

    Interactive: 1) existing source, 2) from scratch, or Back to change the path.
    """
    interactive = sys.stdin.isatty()
    db_path, start = args.db, args.start
    if (db_path is None or start is None) and not interactive:
        raise SystemExit("init: give --db and --start existing|new; there is no terminal to ask")
    step = "path" if db_path is None else ("start" if start is None else "done")
    while step != "done":
        if step == "path":
            import questionary
            db_path = _ask(lambda: questionary.path("Where should the database be created?"))
            if not db_path:
                raise SystemExit("init: no database path given")
            step = "start"
        elif step == "start":
            import questionary
            choice = _ask(lambda: questionary.select(
                "Start from:",
                choices=[
                    questionary.Choice("1) The existing source files (ssh/shared)", "existing"),
                    questionary.Choice("2) From scratch (an empty database)", "new"),
                    questionary.Choice("Back (change the database path)", "back"),
                ],
            ))
            if choice is None:
                raise SystemExit("init: cancelled")
            if choice == "back":
                db_path = None
                step = "path"
            else:
                start = choice
                step = "done"
    files = source_files(Path(args.shared)) if start == "existing" else []
    conn = db.connect(db_path)
    try:
        if conn.execute("SELECT COUNT(*) FROM host").fetchone()[0]:
            raise SystemExit(f"init: {db_path} already has hosts; it is not overwritten")
        with conn:
            if files:
                convert.convert(conn, files)
        hosts = conn.execute("SELECT COUNT(*) FROM host").fetchone()[0]
    finally:
        conn.close()
    print(f"created {db_path} ({start}): {hosts} hosts")
    return 0


def cmd_generate(args) -> int:
    folder = args.dir if args.dir is not None else ask_dir()
    conn = db.connect(args.db)
    try:
        written = render.write_all(conn, Path(folder).expanduser(), args.person)
    finally:
        conn.close()
    for path in written:
        print(f"wrote {path}")
    return 0


def cmd_list(args) -> int:
    conn = db.connect(args.db)
    try:
        for row in conn.execute("SELECT * FROM v_host ORDER BY id"):
            print("\t".join("" if row[k] is None else str(row[k]) for k in row.keys()))
    finally:
        conn.close()
    return 0


def cmd_check(args) -> int:
    conn = db.connect(args.db)
    try:
        ok = conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        broken = conn.execute("PRAGMA foreign_key_check").fetchall()
    finally:
        conn.close()
    if not ok:
        print("integrity_check failed", file=sys.stderr)
    for row in broken:
        print(f"foreign key broken: {row[0]} row {row[1]}", file=sys.stderr)
    return 0 if ok and not broken else 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="ssh-registry")
    parser.add_argument("--version", action="version", version=__version__)
    sub = parser.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("init", help="create the registry database, from existing source or empty")
    p.add_argument("--db", default=None, help="database path; asked for at the terminal if not given")
    p.add_argument("--start", choices=("existing", "new"), default=None,
                   help="existing: from the source files; new: empty. Asked for if not given")
    p.add_argument("shared", nargs="?", default="ssh/shared")
    p.set_defaults(func=cmd_init)

    p = sub.add_parser("convert", help="one-time conversion from the source files")
    p.add_argument("--db", required=True)
    p.add_argument("shared", nargs="?", default="ssh/shared")
    p.set_defaults(func=cmd_convert)

    p = sub.add_parser("generate", help="write cw/personal/shared configs and shellrc.config")
    p.add_argument("--db", required=True)
    p.add_argument("--dir", default=None,
                   help="output folder; asked for at the terminal if not given (no default)")
    p.add_argument("--person", default=None,
                   help="generate for one person (their logins win over shared); output in DIR/PERSON/")
    p.set_defaults(func=cmd_generate)

    p = sub.add_parser("list", help="one line per host")
    p.add_argument("--db", required=True)
    p.set_defaults(func=cmd_list)

    p = sub.add_parser("check", help="integrity and foreign-key checks")
    p.add_argument("--db", required=True)
    p.set_defaults(func=cmd_check)

    edit.register(sub)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
