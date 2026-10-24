"""The generated single config must resolve every host exactly like the source files.

`ssh -G` resolves a host without connecting. For each host name, the settings
from the original multi-file config (Include, in machine order) must equal the
settings from the one generated file.
"""

import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from ssh_registry import cli, db, render, convert  # noqa: E402

SHARED = ROOT / "ssh" / "shared"


def concrete_names(files: list[Path]) -> list[str]:
    names: set[str] = set()
    for f in files:
        for line in f.read_text(encoding="utf-8").splitlines():
            parts = line.split()
            if parts and parts[0].lower() == "host":
                names.update(p for p in parts[1:] if "*" not in p)
    for n in range(1, 11):
        for suffix in ("", "_svcP", "_svcU"):
            names.add(f"alchmy_ny5p{n:02d}{suffix}")
    return sorted(names)


def resolve(config: Path, host: str) -> list[str]:
    result = subprocess.run(["ssh", "-F", str(config), "-G", host],
                            capture_output=True, text=True, check=True)
    return sorted(result.stdout.splitlines())


@unittest.skipUnless(shutil.which("ssh"), "ssh is not installed")
class GeneratedMatchesSource(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="ssh-registry-"))
        self.files = cli.source_files(SHARED)
        self.db = self.tmp / "hosts.sqlite"
        conn = db.connect(self.db)
        try:
            convert.convert(conn, self.files)
            self.generated = self.tmp / "ssh_registry.config"
            self.generated.write_text(render.render(conn), encoding="utf-8")
        finally:
            conn.close()
        self.original = self.tmp / "original.config"
        # Concatenate in machine order. ssh -G resolves the same as the Include chain,
        # and Windows OpenSSH does not resolve absolute Include paths.
        self.original.write_text("".join(f.read_text(encoding="utf-8") + "\n" for f in self.files),
                                 encoding="utf-8")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_every_host_resolves_identically(self):
        names = concrete_names(self.files)
        self.assertTrue(names)
        differing = [h for h in names if resolve(self.original, h) != resolve(self.generated, h)]
        self.assertEqual(differing, [], f"hosts that resolve differently: {differing}")

    def test_generated_file_has_no_include(self):
        self.assertNotIn("Include", self.generated.read_text(encoding="utf-8"))


class SchemaRules(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="ssh-registry-schema-"))
        self.conn = db.connect(self.tmp / "s.sqlite")

    def tearDown(self):
        self.conn.close()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_kind_is_checked(self):
        import sqlite3
        with self.assertRaises(sqlite3.IntegrityError):
            with self.conn:
                self.conn.execute("INSERT INTO host (name, kind, sort_order) VALUES ('x', 'bogus', 1)")

    def test_schema_version(self):
        self.assertEqual(self.conn.execute("PRAGMA user_version").fetchone()[0], 1)


if __name__ == "__main__":
    unittest.main()
