"""Beacons beta: the "dalaran" hosting preset (setup, rules text, kit files), the relay behind a Docker-bridge
Caddy (trusted proxy range), and the image workflow."""
import io
import json
import os
import shutil
import subprocess
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout

import helpers  # noqa: F401
from wurelay import listing, relay as relaymod

HOSTING = helpers.ROOT
REPO = os.path.dirname(HOSTING)


def read_env(p):
    return dict(l.rstrip("\n").split("=", 1) for l in open(p) if "=" in l and not l.startswith("#"))


class DalaranPreset(unittest.TestCase):
    def setUp(self):
        self.kit = tempfile.mkdtemp(prefix="wu-kit-")
        os.environ["WU_KIT"] = self.kit
        import importlib
        from wuhost import setup
        self.setup = importlib.reload(setup)
        self.st = os.path.join(self.kit, "state")

    def tearDown(self):
        shutil.rmtree(self.kit, ignore_errors=True)

    def run_cmd(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            self.setup.main(list(argv))
        return out.getvalue(), err.getvalue()

    def cfg(self):
        return json.load(open(os.path.join(self.st, "host.json")))

    def test_dalaran_defaults_rules_and_switching(self):
        self.run_cmd("init", "--name", "Violet Hangout", "--profile", "dalaran", "--visibility", "public")
        cfg = self.cfg()
        self.assertEqual((cfg["profile"], cfg["bots"]), ("dalaran", 0))
        env = read_env(os.path.join(self.kit, ".env"))
        self.assertEqual((env["WU_PROFILE"], env["WU_BOTS"], env["WU_DB_BUFFER"], env["WU_PLAYER_LIMIT"]),
                         ("dalaran", "0", "256M", "40"))
        # the host's own GM login, as for every profile
        self.assertIn("account:", open(os.path.join(self.st, "host-login.txt")).read())
        self.assertIn("verifier", cfg["gm"])
        # rules text: state/rules.txt, filled with hangout defaults
        rules_txt = open(os.path.join(self.st, "rules.txt")).read()
        self.assertTrue(rules_txt.startswith("# Your realm's rules"))
        rec = cfg["record"]
        self.assertEqual(rec["ruleset"], "dalaran")
        self.assertTrue(rec["rules"] and all(len(r) <= 120 for r in rec["rules"]))
        self.assertIn("Dalaran", rec["tagline"])
        # the listing keeps the ruleset (not "custom") and the rules
        clean = listing.clean_record(rec)
        self.assertEqual(clean["ruleset"], "dalaran")
        self.assertEqual(clean["rules"], rec["rules"])
        # the host edits the text, then "Realm tools > rules"
        with open(os.path.join(self.st, "rules.txt"), "w") as f:
            f.write("# mine\nNo ganking at the Violet Citadel.\n\nRP welcome.\n")
        b = json.load(open(os.path.join(self.st, "beacon.json")))
        b.update(tagline="Fountain duels nightly", discord="https://discord.gg/abcd1234", name="Hijack", official=True)
        json.dump(b, open(os.path.join(self.st, "beacon.json"), "w"))
        self.run_cmd("rules")
        rec = self.cfg()["record"]
        self.assertEqual(rec["rules"], ["No ganking at the Violet Citadel.", "RP welcome."])
        self.assertEqual(rec["tagline"], "Fountain duels nightly")
        self.assertEqual(rec["discord"], "https://discord.gg/abcd1234")
        self.assertEqual(rec["name"], "Violet Hangout")              # the name comes from setup only
        self.assertNotIn("official", rec)
        # re-run keeps the edits; an explicit bot count is kept for this profile
        self.run_cmd("init", "--bots", "5")
        self.run_cmd("init")
        cfg = self.cfg()
        self.assertEqual(cfg["bots"], 5)
        self.assertEqual(cfg["record"]["rules"], ["No ganking at the Violet Citadel.", "RP welcome."])
        # switching to main: main's defaults come back, the hangout's memory settings go
        self.run_cmd("init", "--profile", "main")
        env = read_env(os.path.join(self.kit, ".env"))
        self.assertEqual((env["WU_PROFILE"], env["WU_BOTS"]), ("main", "40"))
        self.assertNotIn("WU_DB_BUFFER", env)
        self.assertNotIn("WU_PLAYER_LIMIT", env)

    def test_other_profiles_unchanged(self):
        self.run_cmd("init", "--name", "Frost", "--profile", "main", "--visibility", "private")
        cfg = self.cfg()
        self.assertEqual(cfg["bots"], 40)
        self.assertEqual(cfg["record"]["rules"], [])
        self.assertEqual(cfg["record"]["tagline"], "")
        self.assertNotIn("WU_DB_BUFFER", read_env(os.path.join(self.kit, ".env")))

    def test_kit_files_know_dalaran(self):
        p = os.path.join(REPO, "realm", "profiles", "dalaran.env")
        if not os.path.exists(p):
            self.skipTest("realm profiles live in the WrathUnleashed repo")
        prof = read_env(p)
        self.assertEqual(prof["OV_MAIN"], "1")                       # level 1 or the boost to 80 (Dalaran)
        self.assertEqual(prof["OV_QOL_HUB"], "1")
        self.assertEqual(prof["AC_GRID_UNLOAD"], "1")
        self.assertNotIn("AC_PLAYERBOTS_MIN_RANDOM_BOTS", prof)      # bots come from WU_BOTS (0)
        kit = os.path.join(HOSTING, "kit")
        bat = open(os.path.join(kit, "Host a Wrath realm.bat")).read()
        self.assertIn('if /i not "%WU_PROFILE%"=="dalaran"', bat)
        self.assertIn('if /i "%WU_PROFILE%"=="dalaran" set "FILES=main_unbrawl.sql main_world.sql modern_combos.sql"', bat)
        sh = open(os.path.join(kit, "host-wrath-realm.sh")).read()
        self.assertIn("main brawl progression dalaran", sh)
        self.assertIn("main|dalaran)", sh)
        self.assertIn("dalaran", open(os.path.join(kit, "Make host kit.bat")).read())
        self.assertIn(":rules", open(os.path.join(kit, "Realm tools.bat")).read())
        # make-kit.sh copies the profile (run on a copy of the kit, against the real realm folder)
        t = tempfile.mkdtemp()
        try:
            shutil.copy(os.path.join(kit, "make-kit.sh"), t)
            subprocess.run(["bash", os.path.join(t, "make-kit.sh"), os.path.join(REPO, "realm")], check=True,
                           capture_output=True)
            self.assertTrue(os.path.exists(os.path.join(t, "realm-files", "profiles", "dalaran.env")))
        finally:
            shutil.rmtree(t, ignore_errors=True)


class TrustedProxies(unittest.TestCase):
    def ip(self, cfg, peer, xff="198.51.100.7"):
        r = relaymod.Relay.__new__(relaymod.Relay)
        r.cfg = cfg
        req = type("Req", (), {"peer": peer, "headers": {"x-forwarded-for": xff}})()
        return r.client_ip(req)

    def test_default_loopback_only(self):
        cfg = relaymod.Config()
        self.assertEqual(self.ip(cfg, "127.0.0.1"), "198.51.100.7")
        self.assertEqual(self.ip(cfg, "::1"), "198.51.100.7")
        self.assertEqual(self.ip(cfg, "172.18.0.5"), "172.18.0.5")   # a container can't claim another IP
        self.assertEqual(self.ip(cfg, "203.0.113.9"), "203.0.113.9")

    def test_bridge_caddy(self):
        cfg = relaymod.Config(trusted_proxies="127.0.0.1/32,172.18.0.0/16")
        self.assertEqual(self.ip(cfg, "172.18.0.5"), "198.51.100.7")  # the site's Caddy on wenilla-realm_default
        self.assertEqual(self.ip(cfg, "::ffff:172.18.0.5"), "198.51.100.7")
        self.assertEqual(self.ip(cfg, "172.19.0.5"), "172.19.0.5")
        self.assertEqual(self.ip(cfg, "not-an-ip"), "not-an-ip")
        cfg = relaymod.Config(trusted_proxies="172.18.0.0/16", trust_proxy=False)
        self.assertEqual(self.ip(cfg, "172.18.0.5"), "172.18.0.5")


class ImagesWorkflow(unittest.TestCase):
    def test_publishes_what_the_kit_pulls(self):
        # the source copy (tools/github-workflows/); .github/workflows/ gets it from "setup\Turn on GitHub builds.bat"
        p = os.path.join(REPO, "tools", "github-workflows", "wu-images.yml")
        if not os.path.exists(p):
            p = os.path.join(REPO, ".github", "workflows", "wu-images.yml")
        if not os.path.exists(p):
            self.skipTest("the image workflow lives in the WrathUnleashed repo")
        text = open(p).read()
        try:
            import yaml
        except ImportError:
            yaml = None
        if yaml:
            doc = yaml.safe_load(text)
            on = doc.get("on", doc.get(True))
            self.assertEqual(on["push"]["branches"], ["main"])
            self.assertEqual(doc["permissions"]["packages"], "write")
        kit_bat = open(os.path.join(HOSTING, "kit", "Host a Wrath realm.bat")).read()
        self.assertIn("WU_IMAGE=ghcr.io/orionopenwow/wu-ac-wotlk", kit_bat)
        for part in ("db-import", "authserver", "worldserver"):
            self.assertIn(f"ghcr.io/orionopenwow/wu-ac-wotlk-{part}:stable", text)
        self.assertIn("ghcr.io/orionopenwow/wu-host-tools:1", text)
        # only the orionopenwow org, only the built-in token, no game data
        import re
        owners = set(re.findall(r"ghcr\.io/([a-z0-9-]+)/", text)) | set(re.findall(r"github\.com/([A-Za-z0-9-]+)/", text))
        self.assertEqual(owners, {"orionopenwow"})
        self.assertEqual(set(re.findall(r"secrets\.([A-Z_]+)", text)), {"GITHUB_TOKEN"})
        self.assertIn("rm -rf realm/custom/acore/modules/mod-arac/patch-contents", text)


if __name__ == "__main__":
    unittest.main()
