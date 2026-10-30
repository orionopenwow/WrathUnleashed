"""Real throwaway git repos (a bare 'GitHub', the owner's folder); gh is faked."""
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import fresh_history as F  # noqa: E402

ENV = dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@x", GIT_COMMITTER_NAME="t",
           GIT_COMMITTER_EMAIL="t@x", GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_NOSYSTEM="1")


@unittest.skipUnless(shutil.which("git"), "git not installed")
class FreshTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.origin = os.path.join(self.tmp, "origin.git")
        self.pc = os.path.join(self.tmp, "pc")
        self.g("init", "-q", "--bare", "-b", "main", self.origin)
        self.g("clone", "-q", self.origin, self.pc)
        for i in range(3):
            self.commit(f"f{i}.txt", f"secret old line {i}")
        self.g("-C", self.pc, "tag", "v1")
        self.g("-C", self.pc, "push", "-q", "origin", "main", "v1")
        self.g("-C", self.pc, "push", "-q", "origin", "main:hub-index/daily")
        self.old = self.g("-C", self.pc, "rev-parse", "HEAD")
        self.confirm = os.path.join(self.tmp, "CONFIRM")
        self.backups = os.path.join(self.tmp, "Desktop")
        self.lines = []

    def g(self, *a):
        r = subprocess.run(["git"] + list(a), env=ENV, capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        return r.stdout.strip()

    def commit(self, name, text):
        with open(os.path.join(self.pc, name), "w") as f:
            f.write(text)
        self.g("-C", self.pc, "add", name)
        self.g("-C", self.pc, "commit", "-q", "-m", "old: " + name)

    def runner(self, args, env=None):
        if args[0] == "gh":
            if args[1:3] == ["api", "user"]:
                return 0, self.who
            if args[1:3] == ["pr", "list"]:
                return 0, "#7 Hub index: review"
            raise AssertionError(args)
        e = dict(ENV, **{k: v for k, v in (env or {}).items() if k.startswith("GIT_")})
        r = subprocess.run(args, env=e, capture_output=True, text=True)
        return r.returncode, (r.stdout + r.stderr).strip()

    who = "orionopenwow"

    def go(self, go=True, confirm=None):
        if confirm is not None:
            with open(self.confirm, "w") as f:
                f.write(confirm)
        return F.fresh(self.pc, go=go, confirm_file=self.confirm, backup_dir=self.backups,
                       runner=self.runner, out=self.lines.append, now=lambda fmt: "20261030-010000")

    def test_dry_run_changes_nothing(self):
        self.assertEqual(self.go(go=False), 0)
        self.assertEqual(self.g("-C", self.origin, "rev-parse", "main"), self.old)
        self.assertFalse(os.path.exists(self.backups))
        self.assertIn("DRY RUN OK", "\n".join(self.lines))

    def test_fresh_start(self):
        tree = self.g("-C", self.pc, "rev-parse", "HEAD^{tree}")
        self.assertEqual(self.go(confirm=self.old), 0, self.lines)
        new = self.g("-C", self.origin, "rev-parse", "main")
        self.assertNotEqual(new, self.old)
        self.assertEqual(self.g("-C", self.origin, "rev-list", "--count", "main"), "1")      # one commit
        self.assertEqual(self.g("-C", self.origin, "rev-parse", "main^{tree}"), tree)        # same files
        self.assertEqual(self.g("-C", self.origin, "log", "-1", "--format=%s %an", "main"), "Leyline Orion")
        self.assertEqual(self.g("-C", self.origin, "for-each-ref", "--format=%(refname)"), "refs/heads/main")
        self.assertEqual(self.g("-C", self.pc, "rev-parse", "HEAD"), new)                    # folder follows
        self.assertEqual(self.g("-C", self.pc, "status", "--porcelain"), "")
        self.assertEqual(self.g("-C", self.pc, "tag", "-l"), "")
        bundle = os.path.join(self.backups, "Leyline-history-backup-20261030-010000.bundle")
        heads = self.g("-C", self.pc, "bundle", "list-heads", bundle)
        self.assertIn(self.old, heads)                                                        # backup has all
        self.assertIn("refs/tags/v1", heads)
        self.assertIn("#7", "\n".join(self.lines))                                           # open PRs named

    def test_stops_if_someone_pushed(self):
        with self.assertRaises(F.Stop):
            self.go(confirm="0000000")
        self.assertEqual(self.g("-C", self.origin, "rev-parse", "main"), self.old)
        self.assertFalse(os.path.exists(self.backups))

    def test_needs_confirm(self):
        with self.assertRaises(F.Stop):
            self.go()
        self.assertEqual(self.g("-C", self.origin, "rev-parse", "main"), self.old)

    def test_stops_on_unshipped_work(self):
        self.commit("new.txt", "not on GitHub")
        with self.assertRaises(F.Stop):
            self.go(confirm=self.old)
        self.assertEqual(self.g("-C", self.origin, "rev-parse", "main"), self.old)

    def test_never_the_helper_account(self):
        self.who = "Chumpton"
        with self.assertRaises(F.Stop):
            self.go(confirm=self.old)
        self.assertEqual(self.g("-C", self.origin, "rev-parse", "main"), self.old)


if __name__ == "__main__":
    unittest.main()
