"""The host kit's "den" profile (realm/profiles/den.env, docs/DEN.md): private and invite-only by default, no bots, a
small database buffer, the profile file in the kit, and the in-game "Invite a friend" file (den-invite.dat) written
only for a Den and removed when the realm leaves the den profile."""
import io
import json
import os
import re
import tempfile
import unittest
from contextlib import redirect_stdout, redirect_stderr

import helpers  # noqa: F401

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
KIT = os.path.join(REPO, "hosting", "kit")


def env_values(path):
    vals = {}
    for ln in open(path, encoding="utf-8").read().splitlines():
        if ln and not ln.startswith("#") and "=" in ln:
            k, v = ln.split("=", 1)
            vals[k] = v
    return vals


class DenProfile(unittest.TestCase):
    def setUp(self):
        self.kit = tempfile.mkdtemp(prefix="wu-den-")
        os.makedirs(os.path.join(self.kit, "realm-files", "lua_scripts"))
        os.environ["WU_KIT"] = self.kit
        import importlib
        from wuhost import setup
        self.setup = importlib.reload(setup)

    def run_cmd(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            self.setup.main(list(argv))
        return out.getvalue(), err.getvalue()

    def dat(self):
        return os.path.join(self.kit, "realm-files", "lua_scripts", "den-invite.dat")

    def test_profile_tables(self):
        s = self.setup
        self.assertIn("den", s.PROFILES)
        self.assertIn("den", s.NO_BOTS)
        self.assertEqual(s.PROFILE_BOTS["den"], 0)
        self.assertEqual(s.PROFILE_ENV["den"]["WU_DB_BUFFER"], "256M")
        self.assertIsNone(s.check_options({"bots": 10}, "den"), "a Den never runs bots")
        self.assertEqual(s.check_options({"bots": 0}, "den"), {"bots": 0})
        self.assertTrue(all(t in s.TAGS for t in s.PROFILE_TAGS["den"]))
        self.assertTrue(s.DEFAULT_RULES["den"] and s.DEFAULT_TAGLINE["den"])

    def test_den_env(self):
        vals = env_values(os.path.join(REPO, "realm", "profiles", "den.env"))
        self.assertEqual(vals["OV_DEN"], "1")
        self.assertIn(vals["OV_DEN_THEME"], ("white", "stone", "wood"))
        self.assertEqual(vals["OV_BUILD_NEW_HOURS"], "0", "every builder on the full tier from the start")
        for k in ("OV_MAIN", "OV_BRAWL", "OV_BOOST_TO_70", "OV_QOL_HUB"):
            self.assertEqual(vals[k], "0", k + ": nothing teleports players out of the Den")
        self.assertEqual(vals["AC_PRELOAD_ALL_NON_INSTANCED_MAP_GRIDS"], "0")
        for k in vals:
            self.assertTrue(re.match(r"^(AC|OV)_[A-Z0-9_]+$", k), k)
        text = open(os.path.join(REPO, "realm", "profiles", "den.env"), encoding="utf-8").read()
        self.assertFalse(re.search(r"(?i)world\s*of\s*warcraft|\bwow\b|warcraft|lich\s*king|blizzard", text))

    def test_kit_copies_the_profile(self):
        for f in ("make-kit.sh", "Make host kit.bat"):
            self.assertRegex(open(os.path.join(KIT, f), encoding="utf-8").read(), r"vanillaplus,? ?den\b", f)

    def test_init_den_private_invite_only(self):
        out, _ = self.run_cmd("init", "--name", "My Den", "--profile", "den")
        st = os.path.join(self.kit, "state")
        cfg = json.load(open(os.path.join(st, "host.json")))
        self.assertEqual((cfg["profile"], cfg["visibility"], cfg["signup"], cfg["bots"]), ("den", "private", "invite", 0))
        env = open(os.path.join(self.kit, ".env")).read()
        self.assertIn("WU_DB_BUFFER=256M", env)
        self.assertIn("WU_PROFILE=den", env)
        # the in-game Invite a friend: the private link, data only, readable by the host alone
        text = open(self.dat(), encoding="ascii").read()
        self.assertEqual(text, 'return { invite = "%s" }\n' % json.loads(out)["invite"])
        self.assertTrue(text.split('"')[1].endswith("#" + cfg["invite_secret"]))
        if os.name == "posix":
            self.assertEqual(os.stat(self.dat()).st_mode & 0o077, 0)
        # a new invite rewrites it; the old secret is gone from it
        self.run_cmd("new-invite")
        new = json.load(open(os.path.join(st, "host.json")))["invite_secret"]
        self.assertIn("#" + new, open(self.dat(), encoding="ascii").read())
        self.assertNotIn(cfg["invite_secret"], open(self.dat(), encoding="ascii").read())
        # the host-realm.dat facts file still never carries the private secret
        hd = os.path.join(self.kit, "realm-files", "lua_scripts", "host-realm.dat")
        if os.path.exists(hd):
            self.assertNotIn(new, open(hd, encoding="ascii").read())

    def test_other_profiles_never_write_it(self):
        self.run_cmd("init", "--name", "Hang", "--profile", "dalaran", "--visibility", "private")
        self.assertFalse(os.path.exists(self.dat()))
        self.run_cmd("init", "--profile", "den")
        self.assertTrue(os.path.exists(self.dat()))
        self.run_cmd("init", "--profile", "main")
        self.assertFalse(os.path.exists(self.dat()), "leaving the den profile removes the link file")


if __name__ == "__main__":
    unittest.main()
