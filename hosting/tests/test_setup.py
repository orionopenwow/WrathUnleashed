"""Host setup: files, secrets, re-run safety, beacon record, invite link, friend SQL."""
import io
import json
import os
import stat
import tempfile
import unittest
from contextlib import redirect_stdout, redirect_stderr

import helpers  # noqa: F401
from wunet import keys, srp6


class Setup(unittest.TestCase):
    def setUp(self):
        self.kit = tempfile.mkdtemp(prefix="wu-kit-")
        os.environ["WU_KIT"] = self.kit
        import importlib
        from wuhost import setup
        self.setup = importlib.reload(setup)

    def run_cmd(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            self.setup.main(list(argv))
        return out.getvalue(), err.getvalue()

    def test_init_and_rerun(self):
        out, _ = self.run_cmd("init", "--name", "Frost Haven", "--profile", "main", "--visibility", "private")
        res = json.loads(out)
        st = os.path.join(self.kit, "state")
        cfg = json.load(open(os.path.join(st, "host.json")))
        self.assertEqual(res["realm_id"], cfg["realm_id"])
        sec = keys.load_or_create(os.path.join(st, "realm.key"))
        self.assertEqual(keys.realm_id(keys.public_key(sec)), cfg["realm_id"])
        self.assertEqual(stat.S_IMODE(os.stat(os.path.join(st, "realm.key")).st_mode), 0o600)
        self.assertEqual(stat.S_IMODE(os.stat(os.path.join(self.kit, ".env")).st_mode), 0o600)
        self.assertEqual(res["invite"], f"https://openvanilla.app/join/{cfg['realm_id']}#{cfg['invite_secret']}")
        self.assertFalse(cfg["warden"])                      # private: browser client friendly
        env = open(os.path.join(self.kit, ".env")).read()
        self.assertIn(f"DB_ROOT_PASSWORD={cfg['db_password']}", env)
        self.assertIn("WU_IMAGE=ghcr.io/orionopenwow/wu-ac-wotlk", env)
        self.assertIn("WU_PROFILE=main", env)
        # the host's GM login works against its verifier
        login = open(os.path.join(st, "host-login.txt")).read()
        user = login.split("account:")[1].split()[0]
        pw = login.split("password:")[1].split()[0]
        salt = bytes.fromhex(cfg["gm"]["salt"])
        self.assertEqual(srp6.make_verifier(user, pw, salt)[1].hex(), cfg["gm"]["verifier"])
        self.assertNotIn(pw, json.dumps(cfg))                # the password itself is not in host.json
        # re-run: same key, passwords, invite; new profile/visibility applied
        out2, _ = self.run_cmd("init", "--profile", "brawl", "--visibility", "public",
                               "--image", "ov/ac-wotlk", "--tag", "custom")
        cfg2 = json.load(open(os.path.join(st, "host.json")))
        for k in ("realm_id", "db_password", "invite_secret", "gm"):
            self.assertEqual(cfg[k], cfg2[k])
        self.assertEqual((cfg2["profile"], cfg2["visibility"], cfg2["warden"], cfg2["name"]),
                         ("brawl", "public", True, "Frost Haven"))
        self.assertEqual(json.loads(out2)["invite"], f"https://openvanilla.app/join/{cfg['realm_id']}")
        rec = json.load(open(os.path.join(st, "beacon.json")))
        self.assertEqual((rec["name"], rec["ruleset"], rec["warden"]), ("Frost Haven", "brawl", True))
        self.assertIn("WU_IMAGE=ov/ac-wotlk", open(os.path.join(self.kit, ".env")).read())

    def test_admin_commands(self):
        self.run_cmd("init", "--name", "R", "--profile", "progression", "--visibility", "private")
        st = os.path.join(self.kit, "state")
        old = json.load(open(os.path.join(st, "host.json")))["invite_secret"]
        out, _ = self.run_cmd("new-invite")
        new = json.load(open(os.path.join(st, "host.json")))["invite_secret"]
        self.assertNotEqual(old, new)
        self.assertTrue(out.strip().endswith("#" + new))
        self.run_cmd("claim", "CLAIMTOKEN0123456789")
        self.assertEqual(json.load(open(os.path.join(st, "host.json")))["claim"], "CLAIMTOKEN0123456789")
        with self.assertRaises(SystemExit):
            self.run_cmd("claim", "bad token!")
        out, err = self.run_cmd("friend", "buddy", "secret1")
        self.assertIn("INSERT INTO account", out)
        self.assertIn("BUDDY", err)
        out, _ = self.run_cmd("get")
        self.assertIn("WU_OLD_PROFILE=progression", out)
        with self.assertRaises(SystemExit):
            self.run_cmd("init", "--name", "Bad;Name")


if __name__ == "__main__":
    unittest.main()
