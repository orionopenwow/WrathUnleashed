"""launcher_updates.py with a fake gh and npx: the private key and password reach GitHub only on stdin, never in a
command line or the output; only the public key lands in tauri.conf.json; running again does not make a new key.

    python3 -I tools/launcher-updates/test_launcher_updates.py
"""
import contextlib
import io
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import launcher_updates as lu  # noqa: E402

PUB = "dW50cnVzdGVkIGNvbW1lbnQ6IG1pbmlzaWduIHB1YmxpYyBrZXk6IEFCQ0QKUldUVEVTVA" * 2
PRIV = b"dW50cnVzdGVkIGNvbW1lbnQ6IHJzaWduIGVuY3J5cHRlZCBzZWNyZXQga2V5ClJXUlRZMEl5"


class FakeGitHub:
    def __init__(self, secret=False, var=None, who="orionopenwow"):
        self.calls, self.secrets, self.vars, self.who = [], {}, {}, who
        if secret:
            self.secrets[lu.SECRET_KEY] = b"old"
        if var:
            self.vars[lu.VAR_PUB] = var

    def run(self, args, stdin=None, cwd=None):
        self.calls.append(list(args))
        if args[1:2] == ["--version"]:
            return 0, "1.0"
        if args[0] == "npx":
            key = Path(args[args.index("--write-keys") + 1])
            key.write_bytes(PRIV + b"\n")
            Path(str(key) + ".pub").write_text(PUB + "\n")
            self.keydir = key.parent
            return 0, ""
        if args[:3] == ["gh", "api", "user"]:
            return 0, self.who + "\n"
        if args[:3] == ["gh", "repo", "view"]:
            return 0, "{}"
        if args[:3] == ["gh", "secret", "list"]:
            return 0, json.dumps([{"name": n} for n in self.secrets])
        if args[:3] == ["gh", "secret", "set"]:
            self.secrets[args[3]] = stdin
            return 0, ""
        if args[:3] == ["gh", "variable", "get"]:
            return (0, self.vars[args[3]] + "\n") if args[3] in self.vars else (1, "")
        if args[:3] == ["gh", "variable", "set"]:
            self.vars[args[3]] = stdin.decode()
            return 0, ""
        return 1, "unexpected"


class LauncherUpdates(unittest.TestCase):
    def setUp(self):
        self.d = Path(tempfile.mkdtemp())
        self.conf = self.d / "tauri.conf.json"
        shutil.copy(lu.CONF, self.conf)

    def tearDown(self):
        shutil.rmtree(self.d, ignore_errors=True)

    def go(self, gh, *argv):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            rc = lu.main(list(argv), r=gh, conf=self.conf)
        return rc, out.getvalue()

    def test_first_run_stores_secrets_on_stdin_and_only_the_public_key_in_the_file(self):
        gh = FakeGitHub()
        rc, out = self.go(gh)
        self.assertEqual(rc, 0, out)
        self.assertEqual(gh.secrets[lu.SECRET_KEY], PRIV)
        password = gh.secrets[lu.SECRET_PASS].decode()
        self.assertGreaterEqual(len(password), 32)
        self.assertEqual(gh.vars[lu.VAR_PUB], PUB)
        conf = json.loads(self.conf.read_text())
        self.assertEqual(conf["plugins"]["updater"]["pubkey"], PUB)
        text = self.conf.read_text()
        self.assertNotIn(PRIV.decode(), text)
        # never printed, never in a gh command line
        self.assertNotIn(PRIV.decode(), out)
        self.assertNotIn(password, out)
        for c in gh.calls:
            if c[0] == "gh":
                self.assertNotIn(PRIV.decode(), " ".join(c))
                self.assertNotIn(password, " ".join(c))
        # the throwaway key folder is gone
        self.assertFalse(gh.keydir.exists())
        self.assertIn("LAUNCHER UPDATES OK", out)

    def test_running_again_keeps_the_key(self):
        gh = FakeGitHub(secret=True, var=PUB)
        rc, out = self.go(gh)
        self.assertEqual(rc, 0, out)
        self.assertFalse(any(c[0] == "npx" and "signer" in c for c in gh.calls), "no new key")
        self.assertEqual(gh.secrets[lu.SECRET_KEY], b"old")
        self.assertEqual(json.loads(self.conf.read_text())["plugins"]["updater"]["pubkey"], PUB)

    def test_a_secret_without_its_public_key_stops_unless_asked_for_a_new_key(self):
        rc, out = self.go(FakeGitHub(secret=True))
        self.assertEqual(rc, 1)
        self.assertIn("--new-key", out)
        self.assertTrue(json.loads(self.conf.read_text())["plugins"]["updater"]["pubkey"].startswith("TODO"))
        gh = FakeGitHub(secret=True)
        rc, out = self.go(gh, "--new-key")
        self.assertEqual(rc, 0, out)
        self.assertEqual(gh.secrets[lu.SECRET_KEY], PRIV)

    def test_never_as_the_helper_account(self):
        rc, out = self.go(FakeGitHub(who="Chumpton"))
        self.assertEqual(rc, 1)
        self.assertIn("gh auth switch", out)


if __name__ == "__main__":
    unittest.main()
