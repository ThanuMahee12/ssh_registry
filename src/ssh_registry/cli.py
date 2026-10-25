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


def cmd_generate(args) -> int:
    conn = db.connect(args.db)
    try:
        written = render.write_all(conn, Path(args.dir).expanduser(), args.person)
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

    p = sub.add_parser("convert", help="one-time conversion from the source files")
    p.add_argument("--db", required=True)
    p.add_argument("shared", nargs="?", default="ssh/shared")
    p.set_defaults(func=cmd_convert)

    p = sub.add_parser("generate", help="write cw/personal/shared configs and shellrc.config")
    p.add_argument("--db", required=True)
    p.add_argument("--dir", default="~/.shellrc", help="output directory (default: ~/.shellrc)")
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
