"""Edit commands: each rule is enforced with a clear error, and every change is logged."""

import io
import shutil
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from ssh_registry import cli, db, render  # noqa: E402


class EditCommands(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="ssh-registry-edit-"))
        self.db = str(self.tmp / "e.sqlite")
        conn = db.connect(self.db)
        conn.close()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def run_cli(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            try:
                code = cli.main([*argv[:2], "--db", self.db, *argv[2:], "--who", "tester"])
            except SystemExit as exc:  # argparse reports usage errors this way
                code = exc.code
        return code, out.getvalue(), err.getvalue()

    def ok(self, *argv):
        code, out, err = self.run_cli(*argv)
        self.assertEqual(code, 0, f"expected success for {argv}: {err}")
        return out

    def fails(self, expected, *argv):
        code, out, err = self.run_cli(*argv)
        self.assertEqual(code, 1, f"expected failure for {argv}")
        self.assertIn(expected, err)

    def query(self, sql, *args):
        conn = db.connect(self.db)
        try:
            return [tuple(r) for r in conn.execute(sql, args).fetchall()]
        finally:
            conn.close()

    # --- hosts ---------------------------------------------------------------

    def test_host_add_update_and_remove(self):
        self.ok("host", "add", "web1", "--kind", "on-prem", "--hostname", "10.0.0.5", "--key", "~/.ssh/id_ed25519")
        self.assertEqual(self.query("SELECT hostname, kind, usage FROM host WHERE name = 'web1'"),
                         [("10.0.0.5", "on-prem", "cw")])
        self.ok("host", "update", "web1", "--port", "2222", "--identities-only", "yes")
        self.assertEqual(self.query("SELECT port, identities_only FROM host WHERE name = 'web1'"), [(2222, 1)])
        self.ok("host", "remove", "web1")
        self.assertEqual(self.query("SELECT COUNT(*) FROM host"), [(0,)])

    def test_duplicate_and_bad_kind_are_refused(self):
        self.ok("host", "add", "web1", "--kind", "on-prem")
        self.fails("already exists", "host", "add", "web1", "--kind", "on-prem")
        code, _, err = self.run_cli("host", "add", "web2", "--kind", "bogus")
        self.assertEqual(code, 2)
        self.assertIn("invalid choice", err)

    def test_proxy_rules(self):
        self.ok("host", "add", "jump", "--kind", "proxy")
        self.ok("host", "add", "app", "--kind", "on-prem", "--proxy", "jump")
        self.assertEqual(self.query("SELECT p.name FROM host h JOIN host p ON p.id = h.proxy_id WHERE h.name = 'app'"),
                         [("jump",)])
        self.fails("cannot be its own proxy", "host", "update", "jump", "--proxy", "jump")
        self.fails("is the proxy of: app", "host", "remove", "jump")
        self.ok("host", "update", "app", "--proxy", "none")
        self.ok("host", "remove", "jump")

    def test_key_add_remove_keeps_order(self):
        self.ok("host", "add", "h", "--kind", "on-prem", "--key", "a", "--key", "b", "--key", "c")
        self.ok("host", "key-remove", "h", "b")
        self.assertEqual(self.query("SELECT seq, path FROM host_key ORDER BY seq"),
                         [(0, "a"), (1, "c")])
        self.fails("already offers", "host", "key-add", "h", "a")

    def test_nothing_to_change_is_refused(self):
        self.ok("host", "add", "h", "--kind", "on-prem")
        self.fails("nothing to change", "host", "update", "h")

    # --- logins and persons --------------------------------------------------

    def test_login_add_classifies_and_refuses_in_use(self):
        self.ok("login", "add", "svc_x")
        self.assertEqual(self.query("SELECT kind FROM login WHERE user = 'svc_x'"), [("service",)])
        self.ok("host", "add", "h", "--kind", "on-prem")
        self.ok("link", "set", "h", "svc_x", "--role", "direct")
        self.fails("still used", "login", "remove", "svc_x")

    def test_sudo_link_needs_flag_and_service_login(self):
        self.ok("host", "add", "grp*", "--kind", "on-prem")
        self.ok("login", "add", "me.user", "--kind", "personal")
        self.ok("login", "add", "svc_a")
        self.fails("needs --flag", "link", "set", "grp*", "svc_a", "--role", "sudo")
        self.fails("only service logins", "link", "set", "grp*", "me.user", "--role", "sudo", "--flag", "P")
        self.ok("link", "set", "grp*", "svc_a", "--role", "sudo", "--flag", "P")
        self.assertEqual(self.query("SELECT role, flag FROM host_login"), [("sudo", "P")])

    def test_person_default_wins_and_remove_person(self):
        self.ok("host", "add", "h", "--kind", "on-prem")
        self.ok("login", "add", "shared.user", "--kind", "system")
        self.ok("login", "add", "me.user", "--kind", "personal")
        self.ok("person", "add", "me", "--login", "me.user")
        self.ok("link", "set", "h", "shared.user", "--role", "default")
        self.ok("link", "set", "h", "me.user", "--role", "default", "--person", "me")
        self.assertIn("User me.user", render.render(db.connect(self.db), person="me"))
        self.assertIn("User shared.user", render.render(db.connect(self.db)))
        self.ok("person", "remove", "me")
        with self.assertRaises(ValueError):
            render.render(db.connect(self.db), person="me")

    def test_link_remove(self):
        self.ok("host", "add", "h", "--kind", "on-prem")
        self.ok("login", "add", "shared.user", "--kind", "system")
        self.ok("link", "set", "h", "shared.user", "--role", "default")
        self.ok("link", "remove", "h", "--role", "default")
        self.fails("no default link", "link", "remove", "h", "--role", "default")

    def test_flag_only_for_sudo(self):
        self.ok("host", "add", "h", "--kind", "on-prem")
        self.ok("login", "add", "shared.user", "--kind", "system")
        self.fails("--flag is only for sudo", "link", "set", "h", "shared.user", "--role", "default", "--flag", "P")

    # --- change log ----------------------------------------------------------

    def test_every_change_is_logged_with_who(self):
        self.ok("host", "add", "h", "--kind", "on-prem")
        self.ok("host", "update", "h", "--port", "22")
        self.ok("host", "remove", "h")
        rows = self.query("SELECT who, action, table_name FROM change_log ORDER BY id")
        self.assertEqual(rows, [("tester", "insert", "host"), ("tester", "update", "host"),
                                ("tester", "delete", "host")])


if __name__ == "__main__":
    unittest.main()
