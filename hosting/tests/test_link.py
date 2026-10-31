"""Linking a server the host already runs to the realm list (`setup.py link`, `leyline link`, "Link my server.bat"),
against the REAL relay and agent with a fake realm standing in for the host's own server:

  * `setup.py link` writes a public, signup-off, "linked" host.json with a key made where it runs, the host's own
    core and client build, and nothing to invite to, no GM account and no database login;
  * the agent connects, the realm is listed with that core and build, and it never touches the realm list, accounts or
    GM rights, even when handed a database; the relay refuses join-page signups for it; players log in through the
    relay with the accounts the server already has, and get the server's own realm address;
  * refusals: a folder that hosts a kit realm, brand words, bad addresses, a client Leyline doesn't offer; init is
    refused in a linked folder; `rules` keeps the host's core and build;
  * `leyline link` (the real bash command, a fake docker): four answers, only the agent container, restart
    unless-stopped, read-only, no capabilities, host network on Linux; status / stop / remove;
  * "Link my server.bat" is there and does the same job on Windows;
  * the Vanilla+ ruleset: offered by setup, its profile file holds the first era (ProgressionLimit 7) and level 60.
"""
import asyncio
import json
import os
import re
import shutil
import stat
import subprocess
import tempfile
import unittest

from helpers import ROOT, FakeDB, FakeRealm, free_port, free_range, http, keys, relaymod, agentmod
from test_hangout import run_setup
from wunet import wire335

KIT = os.path.join(ROOT, "kit")
REPO = os.path.dirname(ROOT)


class Linked(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.mkdtemp(prefix="wu-link-")
        lo, hi = free_range(20)
        self.relay = await relaymod.Relay(relaymod.Config(
            name="relay.test", http_bind="127.0.0.1:0", game_bind="127.0.0.1", shared_auth_port=free_port(),
            port_min=lo, port_max=hi, state_file=os.path.join(self.tmp, "relay", "state.json"),
            listing_site_secret="s")).start()
        self.base = f"ws://127.0.0.1:{self.relay.http_port()}"
        self.http = f"http://127.0.0.1:{self.relay.http_port()}"
        # the host's own server: its realm list already hands out its public address
        self.realm = await FakeRealm(realm_name="Frost Haven", world_address="frost.example:8085").start()
        self.kit = os.path.join(self.tmp, "kit")
        os.makedirs(self.kit)
        out, _ = run_setup(self.kit, "link", "--name", "Frost Haven", "--relay", "relay.test",
                           "--relay-url", self.base + "/agent", "--listing-url", self.http + "/api/listing/heartbeat",
                           "--auth-service", "127.0.0.1:3724", "--world-service", "127.0.0.1:8085",
                           "--build", "12340", "--core", "trinitycore", "--type", "pvp", "--tags", "blizzlike,pvp",
                           "--region", "eu", "--tagline", "An old friend, now on Leyline")
        self.rid = json.loads(out)["realm_id"]
        self.db = FakeDB(self.realm)   # even with a database in reach, a linked server is never touched
        self.agent = agentmod.Agent(os.path.join(self.kit, "state"), db=self.db,
                                    services={3724: ("127.0.0.1", self.realm.auth_port), 8085: ("127.0.0.1", self.realm.world_port)})
        self.agent.tick, self.agent.heartbeat_every = 0.05, 1
        self.agent.task = asyncio.ensure_future(self.agent.run())
        for _ in range(200):
            if self.rid in self.relay.sessions and self.rid in self.relay.listing.entries:
                break
            await asyncio.sleep(0.05)

    async def asyncTearDown(self):
        self.agent.stop_ev.set(); self.agent.close_all(); self.agent.task.cancel()
        await self.relay.stop()
        await self.realm.stop()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def cfg(self):
        with open(os.path.join(self.kit, "state", "host.json")) as f:
            return json.load(f)

    async def test_link_config(self):
        cfg = self.cfg()
        self.assertTrue(cfg["linked"])
        self.assertNotIn("official", cfg)
        self.assertEqual((cfg["visibility"], cfg["signup"], cfg["realmlist"], cfg["profile"]), ("public", "off", "keep", "linked"))
        self.assertEqual((cfg["auth_service"], cfg["world_service"]), ("127.0.0.1:3724", "127.0.0.1:8085"))
        for k in ("invite_secret", "host_secret", "gm", "gm_name", "db_password"):
            self.assertNotIn(k, cfg)
        rec = cfg["record"]
        self.assertEqual((rec["core"], rec["build"], rec["ruleset"], rec["type"], rec["tags"], rec["region"]),
                         ("trinitycore", 12340, "custom", "PvP", ["blizzlike", "pvp"], "eu"))
        kp = os.path.join(self.kit, "state", "realm.key")
        self.assertEqual(stat.S_IMODE(os.stat(kp).st_mode), 0o600)
        self.assertEqual(keys.realm_id(keys.public_key(keys.load_or_create(kp))), self.rid)
        self.assertTrue(self.agent.official(), "hands off, like the operator's own realm")
        # again, with only a new client: same key and id, the rest kept
        out, _ = run_setup(self.kit, "link", "--build", "5875")
        self.assertEqual(json.loads(out)["realm_id"], self.rid)
        cfg = self.cfg()
        self.assertEqual((cfg["name"], cfg["auth_service"], cfg["record"]["build"], cfg["record"]["core"],
                          cfg["record"]["tagline"]), ("Frost Haven", "127.0.0.1:3724", 5875, "trinitycore",
                                                      "An old friend, now on Leyline"))
        # rules re-reads the text but keeps the host's core and build (not the kit's own)
        with open(os.path.join(self.kit, "state", "rules.txt"), "w") as f:
            f.write("# c\nBe kind.\n")
        run_setup(self.kit, "rules")
        rec = self.cfg()["record"]
        self.assertEqual((rec["core"], rec["build"], rec["ruleset"], rec["rules"]), ("trinitycore", 5875, "custom", ["Be kind."]))
        # claim works the usual way
        run_setup(self.kit, "claim", "TOKEN-0123456789abcdef")
        self.assertEqual(self.cfg()["claim"], "TOKEN-0123456789abcdef")

    async def test_refusals(self):
        for argv in (("--name", "WoW Classic Fun"),                       # brand words
                     ("--tagline", "The best Warcraft server"),
                     ("--auth-service", "nope"),                            # not host:port
                     ("--world-service", "127.0.0.1:99999"),
                     ("--build", "15595"),                                  # a client not offered now
                     ("--core", "made-up"),
                     ("--status-url", "javascript:alert(1)"),
                     ("--discord", "https://evil.example/x")):
            with self.assertRaises(SystemExit, msg=argv):
                run_setup(self.kit, "link", *argv)
        self.assertEqual(self.cfg()["name"], "Frost Haven", "a refused run changes nothing")
        with self.assertRaises(SystemExit):   # a linked folder is not a host kit realm
            run_setup(self.kit, "init", "--name", "X", "--profile", "main", "--visibility", "public")
        other = os.path.join(self.tmp, "kit2")
        os.makedirs(other)
        run_setup(other, "init", "--name", "Kit Realm", "--profile", "main", "--visibility", "private", "--gm-name", "kitgm")
        with self.assertRaises(SystemExit):   # a host kit realm's folder can't be turned into a link
            run_setup(other, "link", "--name", "Frost Haven", "--auth-service", "a:1", "--world-service", "b:2")
        fresh = os.path.join(self.tmp, "kit3")
        os.makedirs(fresh)
        with self.assertRaises(SystemExit):   # addresses are needed the first time
            run_setup(fresh, "link", "--name", "Frost Haven")

    async def test_listed_with_its_core_and_build_and_hands_off(self):
        st, doc, _ = await http("GET", f"{self.http}/api/listing/realms.json")
        rec = next(r for r in doc["realms"] if r["community"]["realmId"] == self.rid)
        self.assertEqual((rec["name"], rec["state"], rec["type"]), ("Frost Haven", "live", "PvP"))
        self.assertEqual((rec["profile"]["core"], rec["profile"]["build"], rec["profile"]["ruleset"]),
                         ("trinitycore", 12340, "custom"))
        self.assertEqual(rec["tags"], ["blizzlike", "pvp"])
        await asyncio.sleep(0.3)   # several housekeeping ticks
        self.assertEqual(self.db.address_calls, [], "the realm list row is never touched")
        self.assertEqual(self.realm.world_address, "frost.example:8085")
        self.assertEqual(self.db.gm, {}, "no GM rights granted")
        self.assertFalse(self.agent.address_done)

    async def test_no_signups_and_existing_accounts_log_in_through_the_relay(self):
        self.realm.add_account("oldtimer", "OldPass12345")   # made on the server the way it always has
        before = set(self.realm.accounts)
        st, doc, _ = await http("POST", f"{self.http}/api/realms/{self.rid}/accounts",
                                {"username": "newbie1", "salt": "00" * 32, "verifier": "11" * 32})
        self.assertEqual(st, 403)
        port = self.relay.state["realms"][self.rid]["auth"]
        _, realms = await wire335.logon("127.0.0.1", port, "oldtimer", "OldPass12345")
        self.assertEqual(realms[0]["address"], "frost.example:8085", "its own realm address, not a relay address")
        self.assertEqual(set(self.realm.accounts), before)


def fake_docker(tmp):
    """A docker on PATH that records its calls and answers like a running daemon."""
    b = os.path.join(tmp, "bin")
    os.makedirs(b, exist_ok=True)
    with open(os.path.join(b, "docker"), "w") as f:
        f.write('#!/bin/sh\necho "docker $*" >> "%s/calls"\n'
                'case "$1" in ps) echo "Up 2 minutes" ;; inspect) echo unless-stopped ;; esac\nexit 0\n' % tmp)
    os.chmod(os.path.join(b, "docker"), 0o755)
    return b


class LeylineLink(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="wu-link-sh-")
        self.kit = os.path.join(self.tmp, "kit")
        os.makedirs(self.kit)
        for f in ("leyline", "host-wrath-realm.sh"):
            shutil.copy(os.path.join(KIT, f), self.kit)
        shutil.copytree(os.path.join(KIT, "tools"), os.path.join(self.kit, "tools"),
                        ignore=shutil.ignore_patterns("__pycache__"))
        self.bin = fake_docker(self.tmp)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def leyline(self, *args, ok=True, **env):
        e = dict(os.environ, PATH=self.bin + os.pathsep + os.environ["PATH"], LEYLINE_LOCAL_TOOLS="1",
                 LEYLINE_NONINTERACTIVE="1", LEYLINE_LINK_WAIT="1", **env)
        e.pop("WU_KIT", None)
        r = subprocess.run(["bash", os.path.join(self.kit, "leyline"), *args], env=e, capture_output=True, text=True,
                           timeout=60)
        if ok:
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        return r

    def calls(self):
        try:
            with open(os.path.join(self.tmp, "calls")) as f:
                return f.read().splitlines()
        except OSError:
            return []

    def test_link_runs_only_the_agent(self):
        r = self.leyline("link", LEYLINE_LINK_NAME="Old Realm", LEYLINE_LINK_CLIENT="vanilla",
                         LEYLINE_LINK_TAGLINE="Twenty years young")
        cfg = json.load(open(os.path.join(self.kit, "state", "host.json")))
        self.assertTrue(cfg["linked"])
        self.assertEqual((cfg["name"], cfg["record"]["build"], cfg["record"]["tagline"]), ("Old Realm", 5875, "Twenty years young"))
        runs = [c for c in self.calls() if c.startswith("docker run")]
        self.assertEqual(len(runs), 1, self.calls())
        run = runs[0]
        for flag in ("--name wu-link-agent", "--restart unless-stopped", "--read-only", "--cap-drop ALL",
                     "--security-opt no-new-privileges", "--memory 96m", "python -m wuhost.agent --state /state"):
            self.assertIn(flag, run)
        self.assertIn("--network host" if os.uname().sysname == "Linux" else "host.docker.internal:host-gateway", run)
        self.assertNotIn("compose", " ".join(self.calls()), "no realm of ours is started")
        out = r.stdout
        self.assertIn("realm list within a minute", out)
        self.assertIn("WrongPass.MaxCount = 0", out)
        self.assertIn("Nothing on your server was changed", out)
        self.assertFalse(re.search(r"(?i)world\s*of\s*warcraft|\bwow\b|warcraft|lich\s*king|blizzard", out + r.stderr))
        # again: same realm id, the earlier answers kept
        rid = cfg["realm_id"]
        self.leyline("link", LEYLINE_LINK_CLIENT="wrath")
        cfg = json.load(open(os.path.join(self.kit, "state", "host.json")))
        self.assertEqual((cfg["realm_id"], cfg["name"], cfg["record"]["build"]), (rid, "Old Realm", 12340))
        # status, stop, remove
        self.assertIn("Old Realm", self.leyline("link", "status").stdout)
        self.leyline("link", "stop")
        self.assertIn("docker stop wu-link-agent", self.calls())
        out = self.leyline("link", "remove").stdout
        self.assertIn("docker rm -f wu-link-agent", self.calls())
        self.assertIn("same realm", out)
        self.assertTrue(os.path.exists(os.path.join(self.kit, "state", "realm.key")), "the key is kept")
        r = self.leyline("link", "nonsense", ok=False)
        self.assertNotEqual(r.returncode, 0)

    def test_link_refuses_a_kit_realm_and_a_bad_client(self):
        r = self.leyline("link", ok=False, LEYLINE_LINK_CLIENT="cataclysm")
        self.assertNotEqual(r.returncode, 0)
        os.makedirs(os.path.join(self.kit, "state"))
        with open(os.path.join(self.kit, "state", "host.json"), "w") as f:
            json.dump({"realm_id": "x", "name": "Kit Realm", "profile": "main"}, f)
        r = self.leyline("link", ok=False)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("already hosts a realm", r.stderr)
        self.assertEqual([c for c in self.calls() if c.startswith("docker run")], [])

    def test_host_takes_its_answers_on_the_command_line(self):
        r = self.leyline("host", "--config-only", "--ruleset", "vanillaplus", "--public", "--name", "Old World",
                         "--gm", "oldgm", WU_DRY="1")
        cfg = json.load(open(os.path.join(self.kit, "state", "host.json")))
        self.assertEqual((cfg["profile"], cfg["visibility"], cfg["name"], cfg["gm_name"], cfg["bots"]),
                         ("vanillaplus", "public", "Old World", "OLDGM", 0))
        self.assertIn("Vanilla+", cfg["record"]["tagline"])
        self.assertNotEqual(self.leyline("host", "--bogus", ok=False).returncode, 0)

    def test_help_and_syntax(self):
        self.assertEqual(subprocess.run(["bash", "-n", os.path.join(KIT, "leyline")]).returncode, 0)
        out = self.leyline("help").stdout
        self.assertIn("leyline link", out)
        self.assertIn("--always-on", out)


class Files(unittest.TestCase):
    def test_link_bat(self):
        bat = open(os.path.join(KIT, "Link my server.bat"), encoding="ascii").read()
        for s in ("wuhost.setup link", 'set "LC=wu-link-agent"', "--name %LC%", "--restart unless-stopped", "--read-only",
                  "--cap-drop ALL", "host.docker.internal", "WrongPass.MaxCount = 0", "status", "remove"):
            self.assertIn(s, bat)
        self.assertNotIn("compose", bat.split(":status")[0].replace("Docker Desktop", ""))
        self.assertFalse(re.search(r"(?i)world\s*of\s*warcraft|\bwow\b|warcraft|lich\s*king|blizzard", bat))

    def test_vanillaplus_profile(self):
        env = open(os.path.join(REPO, "realm", "profiles", "vanillaplus.env")).read()
        vals = dict(ln.split("=", 1) for ln in env.splitlines() if ln and not ln.startswith("#"))
        self.assertEqual(vals["AC_INDIVIDUAL_PROGRESSION_ENABLE"], "1")
        self.assertEqual(vals["AC_INDIVIDUAL_PROGRESSION_PROGRESSION_LIMIT"], "7")   # the module's "Vanilla content"
        self.assertEqual(vals["AC_MAX_PLAYER_LEVEL"], "60")
        self.assertEqual(vals["AC_RATE_XP_KILL"], "1.5")
        from wuhost import setup
        self.assertIn("vanillaplus", setup.PROFILES)
        self.assertEqual(setup.check_options({"bots": 10}, "vanillaplus"), {"bots": 10}, "bots allowed, none by default")
        self.assertIsNone(setup.check_options({"bots": 10}, "dalaran"))
        for f in ("make-kit.sh", "Make host kit.bat"):
            self.assertIn("vanillaplus", open(os.path.join(KIT, f)).read())


if __name__ == "__main__":
    unittest.main()
