"""Leyline end to end, stock-client path, no game data: a friend group goes from nothing to a listed
Dalaran-hangout Beacon with its own GM and house rules.

Everything is the real code except AzerothCore (tests/fake_realm.py speaks the 3.3.5a login and
world handshake) and its MySQL (helpers.FakeDB):

  leyline host --config-only   (the real bash command, setup.py on this machine's python3)
  -> the real host agent        (wuhost.agent: tunnel, realm list address, GM rights, heartbeats)
  -> the real relay             (wurelay: tunnel, ports, join API, listing, claims)
  -> the real headless client   (wunet.wire335: SRP6 logon, realm list, world auth, enter world)

Checks: listing JSON, join page + join API, the GM account (made by the operator, never by the
script; its name can't be squatted), house rules updates, claim + ownership, private vs public,
and that nothing a player sees names the game's publisher or titles.
"""
import asyncio
import hashlib
import json
import os
import re
import shutil
import tempfile
import time
import unittest

from helpers import ROOT, FakeDB, free_port, free_range, http, srp_account
from fake_realm import FakeRealm
from wunet import keys, ws, wire335
from wuhost import agent as agentmod
from wurelay import listing as listingmod, relay as relaymod

# Words players must never see (domains like openvanilla.app are config, not text).
BANNED = re.compile(r"World of Warcraft|Warcraft|Lich King|Blizzard|\bWoW\b|Open Vanilla|OpenVanilla|OpenWoW")
RULES = ["Be kind; duels by consent only.", "No spam in trade.", "GM word is final."]


def banned_in(text):
    t = text if isinstance(text, str) else json.dumps(text)
    return BANNED.findall(t)


class LeylineEndToEnd(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.mkdtemp(prefix="leyline-e2e-")
        self.kit = os.path.join(self.tmp, "kit")
        os.makedirs(self.kit)
        src = os.path.join(ROOT, "kit")
        for f in ("leyline", "host-wrath-realm.sh"):
            shutil.copy(os.path.join(src, f), self.kit)
        shutil.copytree(os.path.join(src, "tools"), os.path.join(self.kit, "tools"),
                        ignore=shutil.ignore_patterns("__pycache__"))
        self._min_interval = listingmod.MIN_INTERVAL
        listingmod.MIN_INTERVAL = 0          # beats every 0.2 s here instead of 60 s
        lo, hi = free_range(20)
        self.relay = await relaymod.Relay(relaymod.Config(
            name="relay.test", http_bind="127.0.0.1:0", game_bind="127.0.0.1", shared_auth_port=free_port(),
            port_min=lo, port_max=hi, state_file=os.path.join(self.tmp, "relay", "state.json"),
            site_url="https://leyline.test", site_origins=["https://leyline.test"],
            listing_site_secret="site-secret",
            accounts_per_ip_hour=20)).start()   # every "player" here shares 127.0.0.1
        self.http = f"http://127.0.0.1:{self.relay.http_port()}"
        self.wsbase = f"ws://127.0.0.1:{self.relay.http_port()}"
        self.realm = await FakeRealm(realm_name="(not set yet)").start()
        self.db = FakeDB(self.realm)
        self.agents = []

    async def asyncTearDown(self):
        listingmod.MIN_INTERVAL = self._min_interval
        for a in self.agents:
            a.stop_ev.set()
            a.close_all()
            a.task.cancel()
        await self.relay.stop()
        await self.realm.stop()
        shutil.rmtree(self.tmp, ignore_errors=True)

    # ------------------------------------------------------------------ plumbing
    async def leyline(self, *args, ok=True, **env):
        e = dict(os.environ, LEYLINE_LOCAL_TOOLS="1", LEYLINE_NONINTERACTIVE="1", WU_RELAY="relay.test",
                 WU_RELAY_URL=self.wsbase + "/agent", WU_LISTING_URL=self.http + "/api/listing/heartbeat")
        e.update(env)
        p = await asyncio.create_subprocess_exec("bash", os.path.join(self.kit, "leyline"), *args, env=e,
                                                 stdin=asyncio.subprocess.DEVNULL,
                                                 stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT)
        out, _ = await asyncio.wait_for(p.communicate(), 60)
        out = out.decode()
        if ok:
            self.assertEqual(p.returncode, 0, out)
        return p.returncode, out

    def state(self, name):
        return os.path.join(self.kit, "state", name)

    def cfg(self):
        return json.load(open(self.state("host.json")))

    def start_agent(self):
        a = agentmod.Agent(os.path.join(self.kit, "state"), db=self.db,
                           services={3724: ("127.0.0.1", self.realm.auth_port), 8085: ("127.0.0.1", self.realm.world_port)})
        a.tick, a.heartbeat_every = 0.05, 0.2
        a.task = asyncio.ensure_future(a.run())
        self.agents.append(a)
        return a

    async def until(self, fn, what, timeout=10):
        t0 = time.monotonic()
        while time.monotonic() - t0 < timeout:
            v = fn()
            if asyncio.iscoroutine(v):
                v = await v
            if v:
                return v
            await asyncio.sleep(0.05)
        self.fail(f"timed out waiting for: {what}")

    async def listed(self):
        st, doc, hdr = await http("GET", f"{self.http}/api/listing/realms.json")
        self.assertEqual(st, 200)
        self.assertEqual(hdr.get("access-control-allow-origin"), "*")
        return {r["community"]["realmId"]: r for r in doc["realms"]}

    # ------------------------------------------------------------------ the flow
    async def test_friend_group_dalaran_beacon(self):
        # 1. the operator: one command, a few answers (here from the environment)
        rules_file = os.path.join(self.tmp, "rules.txt")
        with open(rules_file, "w") as f:
            f.write("# our rules\n" + "\n".join(RULES) + "\n")
        _, out = await self.leyline("host", "--config-only", LEYLINE_NAME="Violet Hangout", LEYLINE_GM="bossman",
                                    LEYLINE_RULES_FILE=rules_file, LEYLINE_TAGLINE="Fountain duels nightly")
        self.assertEqual(banned_in(out), [], out)
        cfg = self.cfg()
        rid = cfg["realm_id"]
        self.assertEqual((cfg["profile"], cfg["visibility"], cfg["signup"], cfg["bots"]), ("dalaran", "public", "open", 0))
        self.assertEqual(cfg["gm_name"], "BOSSMAN")
        # the command made no account and set no password
        self.assertNotIn("gm", cfg)
        self.assertFalse(os.path.exists(self.state("host-login.txt")))
        self.assertEqual(cfg["record"]["rules"], RULES)
        self.assertEqual(cfg["record"]["tagline"], "Fountain duels nightly")
        self.assertEqual(open(self.state("invite.txt")).read().strip(), f"https://relay.test/join/{rid}")
        host_link = open(self.state("host-link.txt")).read().strip()
        self.assertEqual(os.stat(self.state("host-link.txt")).st_mode & 0o777, 0o600)
        self.assertIn("BOSSMAN", out)
        self.assertIn(host_link, out)
        host_key = host_link.split("#", 1)[1].split("~")[1]

        # 2. the realm starts; its agent registers with the relay (realm key, no account anywhere)
        agent = self.start_agent()
        s = await self.until(lambda: self.relay.sessions.get(rid), "agent registered")
        await self.until(lambda: agent.address_done, "realm list address set")
        auth_port, world_port = self.relay.state["realms"][rid]["auth"], self.relay.state["realms"][rid]["world"]
        self.assertEqual(self.realm.world_address, f"relay.test:{world_port}")
        self.assertEqual(self.realm.realm_name, "Violet Hangout")
        self.assertEqual(s.visibility, "public")
        self.assertEqual(self.db.gm, {})                       # nobody is GM yet: the account doesn't exist

        # 3. heartbeats -> the Leyline realm list
        recs = await self.until(self.listed, "listed")
        rec = recs[rid]
        self.assertEqual((rec["name"], rec["state"], rec["official"]), ("Violet Hangout", "live", False))
        self.assertEqual(rec["profile"]["ruleset"], "dalaran")
        self.assertEqual((rec["profile"]["address"], rec["profile"]["port"]), ("relay.test", auth_port))
        self.assertEqual(rec["rules"], RULES)
        self.assertEqual(rec["tagline"], "Fountain duels nightly")
        self.assertEqual(rec["connect"]["url"], f"https://relay.test/join/{rid}")
        self.assertEqual(rec["community"]["lastHeartbeat"], {"online": True, "players": 2, "bots": 40, "uptime_s": 1234})
        self.assertFalse(rec["community"]["claimed"])
        self.assertEqual(banned_in(rec), [], rec)

        # 4. a player follows the Join link: page, realm info, knock
        st, page, hdr = await http("GET", f"{self.http}/join/{rid}")
        self.assertEqual(st, 200)
        self.assertEqual(banned_in(page), [])
        st, info, _ = await http("GET", f"{self.http}/api/realms/{rid}")
        self.assertEqual((st, info["online"], info["visibility"], info["signup"]), (200, True, "public", "open"))
        st, k, _ = await http("POST", f"{self.http}/api/realms/{rid}/knock", {})
        self.assertEqual(st, 200, k)
        # this relay has no shared 3724, so the line is the realm's own port (what the join page shows)
        self.assertEqual(k["realmlist"], f"relay.test:{auth_port}")
        self.assertEqual(banned_in(k), [])

        # 5. the GM account: a stranger can't take the name; the host makes it from their own link
        st, body, _ = await http("POST", f"{self.http}/api/realms/{rid}/accounts", srp_account("bossman", "stolen12"))
        self.assertEqual(st, 403, body)
        self.assertNotIn("BOSSMAN", self.realm.accounts)
        st, body, _ = await http("POST", f"{self.http}/api/realms/{rid}/accounts",
                                 dict(srp_account("bossman", "fake1234"), host="WRONGHOSTKEY"))
        self.assertEqual(st, 403, body)
        st, body, _ = await http("POST", f"{self.http}/api/realms/{rid}/accounts",
                                 dict(srp_account("bossman", "MyOwnPass1"), invite=cfg["invite_secret"], host=host_key))
        self.assertEqual(st, 201, body)
        await self.until(lambda: self.db.gm.get("BOSSMAN") == 3, "GM rights for the host's account")
        st_txt = json.load(open(self.state("relay-state.json")))
        self.assertTrue(st_txt["gm_ok"])
        _, out = await self.leyline("status")
        self.assertIn("BOSSMAN  (has GM rights on this realm)", out)
        self.assertIn(f"set realmlist relay.test:{auth_port}", out)
        self.assertEqual(banned_in(out), [], out)
        # a friend signs up on the public join page and is not a GM
        st, body, _ = await http("POST", f"{self.http}/api/realms/{rid}/accounts", srp_account("friend1", "hunter22"))
        self.assertEqual(st, 201, body)
        self.assertNotIn("FRIEND1", self.db.gm)

        # 6. the stock-client path through the relay: logon on the realm's port, realm list -> relay, world
        for user, pw in (("bossman", "MyOwnPass1"), ("friend1", "hunter22")):
            rep = await wire335.full_run("127.0.0.1", auth_port, user, pw, world_override=f"127.0.0.1:{world_port}")
            self.assertEqual(rep["realm"]["address"], f"relay.test:{world_port}")
            self.assertEqual(rep["realm"]["name"], "Violet Hangout")
            self.assertIn("enter_world", rep["steps"])
        with self.assertRaises((wire335.WowError, asyncio.IncompleteReadError, ConnectionError)):
            await wire335.logon("127.0.0.1", auth_port, "bossman", "stolen12", timeout=3)

        # 7. house rules change: edit the file, `leyline rules`, the list shows it with the next beat
        new_rules = ["Dalaran fountain is a no-gank zone.", "RP welcome."]
        with open(self.state("rules.txt"), "w") as f:
            f.write("# edited\n" + "\n".join(new_rules) + "\n")
        await self.leyline("rules")
        await self.until(lambda: self._rules_are(new_rules, rid), "new rules on the list")

        # 8. claim and ownership
        auth = {"Authorization": "Bearer site-secret"}
        token = "CLAIM" + "x" * 20
        st, _, _ = await http("POST", f"{self.http}/api/listing/claims", {"realm_id": rid, "token": token}, auth)
        self.assertEqual(st, 409)                                # the realm's signed beat doesn't carry it yet
        await self.leyline("claim", token)
        await self.until(lambda: self.relay.listing.entries[rid].get("claim") == token, "claim token in a signed beat")
        st, _, _ = await http("POST", f"{self.http}/api/listing/claims", {"realm_id": rid, "token": token},
                              {"Authorization": "Bearer nope"})
        self.assertEqual(st, 401)
        st, body, _ = await http("POST", f"{self.http}/api/listing/claims",
                                 {"realm_id": rid, "token": token, "claimed_by": "Orion"}, auth)
        self.assertEqual(st, 200, body)
        self.assertEqual((await self.listed())[rid]["community"]["claimedBy"], "Orion")
        # someone else's key can't speak for this realm: not in a heartbeat ...
        other = keys.load_or_create(os.path.join(self.tmp, "other.key"))
        forged = {"v": 1, "realm_id": rid, "pubkey": keys.public_key(other).hex(), "seq": int(time.time() * 1000) + 10**9,
                  "ts": int(time.time()), "record": {"name": "Hijacked"}, "status": {"online": True}, "claim": "EVIL" + "x" * 20}
        st, _, _ = await http("POST", f"{self.http}/api/listing/heartbeat",
                              {"beat": forged, "sig": keys.sign_doc(other, forged, keys.CTX_HEARTBEAT)})
        self.assertEqual(st, 400)
        # ... nor at the relay's front door (the realm id is the key's hash)
        sock = await ws.connect(self.wsbase + "/agent")
        _, msg = await sock.recv()
        ch = json.loads(msg)
        hello = {"realm_id": rid, "pubkey": keys.public_key(other).hex(), "challenge": ch["challenge"],
                 "relay": ch["relay"], "name": "Hijacked", "visibility": "public", "invite_sha256": None,
                 "signup": "open", "version": "x", "ts": int(time.time())}
        await sock.send(json.dumps({"hello": hello, "sig": keys.sign_doc(other, hello, keys.CTX_RELAY_LOGIN)}))
        _, msg = await sock.recv()
        self.assertIn("does not match the key", json.loads(msg)["error"])
        sock.abort()
        self.assertIs(self.relay.sessions[rid], s)               # the real host is still connected
        # and a realm that isn't connected to this relay can't get onto its list
        lone = keys.load_or_create(os.path.join(self.tmp, "lone.key"))
        beat = {"v": 1, "realm_id": keys.realm_id(keys.public_key(lone)), "pubkey": keys.public_key(lone).hex(),
                "seq": 1, "ts": int(time.time()), "record": {"name": "Ghost"}, "status": {"online": True}}
        st, _, _ = await http("POST", f"{self.http}/api/listing/heartbeat",
                              {"beat": beat, "sig": keys.sign_doc(lone, beat, keys.CTX_HEARTBEAT)})
        self.assertEqual(st, 409)

        # 9. private: off the list at once, invite-only from then on
        await self.leyline("private")
        await self.until(lambda: s.visibility == "private", "relay knows it is private")
        self.assertNotIn(rid, await self.listed())
        self.assertNotIn(rid, self.relay.listing.entries)
        await asyncio.sleep(0.5)                                  # no beat brings it back
        self.assertNotIn(rid, await self.listed())
        b = agent.beat(await agent.status())
        st, _, _ = await http("POST", f"{self.http}/api/listing/heartbeat", b)
        self.assertEqual(st, 403)
        st, _, _ = await http("POST", f"{self.http}/api/realms/{rid}/knock", {})
        self.assertEqual(st, 403)
        st, _, _ = await http("POST", f"{self.http}/api/realms/{rid}/knock", {"invite": cfg["invite_secret"]})
        self.assertEqual(st, 200)
        st, _, _ = await http("POST", f"{self.http}/api/realms/{rid}/accounts", srp_account("stranger", "abcdefgh"))
        self.assertEqual(st, 403)
        st, _, _ = await http("POST", f"{self.http}/api/realms/{rid}/accounts",
                              dict(srp_account("friend2", "abcdefgh"), invite=cfg["invite_secret"]))
        self.assertEqual(st, 201)
        # 10. and back to public: listed again with the next beat
        await self.leyline("public")
        await self.until(lambda: s.visibility == "public", "relay knows it is public")
        recs = await self.until(self._listed_rid(rid), "listed again")
        self.assertEqual(recs[rid]["rules"], new_rules)

    def _listed_rid(self, rid):
        async def f():
            recs = await self.listed()
            return recs if rid in recs else None
        return f

    async def _rules_are(self, rules, rid):
        recs = await self.listed()
        return rid in recs and recs[rid]["rules"] == rules

    async def test_private_beacon_is_never_listed(self):
        _, out = await self.leyline("host", "--config-only", LEYLINE_NAME="Friends Only", LEYLINE_GM="hostguy",
                                    LEYLINE_VISIBILITY="private")
        cfg = self.cfg()
        self.assertEqual((cfg["visibility"], cfg["signup"], cfg["profile"]), ("private", "invite", "dalaran"))
        self.assertIn("#" + cfg["invite_secret"], open(self.state("invite.txt")).read())
        agent = self.start_agent()
        await self.until(lambda: self.relay.sessions.get(cfg["realm_id"]), "agent registered")
        await asyncio.sleep(0.6)
        self.assertNotIn(cfg["realm_id"], await self.listed())
        self.assertNotIn("listing_status", json.load(open(self.state("relay-state.json"))))   # it never beat
        # even a hand-made beat is refused
        st, _, _ = await http("POST", f"{self.http}/api/listing/heartbeat", agent.beat(await agent.status()))
        self.assertEqual(st, 403)
        # the host's own link still makes the GM account (it carries the invite too)
        host_key = open(self.state("host-link.txt")).read().strip().split("~")[1]
        st, body, _ = await http("POST", f"{self.http}/api/realms/{cfg['realm_id']}/accounts",
                                 dict(srp_account("hostguy", "secret99"), invite=cfg["invite_secret"]))
        self.assertEqual(st, 403, body)                          # a friend with the invite can't take the GM name
        st, body, _ = await http("POST", f"{self.http}/api/realms/{cfg['realm_id']}/accounts",
                                 dict(srp_account("hostguy", "secret99"), invite=cfg["invite_secret"], host=host_key))
        self.assertEqual(st, 201, body)
        await self.until(lambda: self.db.gm.get("HOSTGUY") == 3, "GM rights")

    async def test_leyline_never_makes_accounts(self):
        rc, out = await self.leyline("friend", "bob", ok=False)
        self.assertNotEqual(rc, 0)
        self.assertIn("doesn't make accounts", out)
        rc, out = await self.leyline("host", "--config-only", ok=False, LEYLINE_NAME="X Realm")   # no GM name
        self.assertNotEqual(rc, 0)
        self.assertIn("LEYLINE_GM", out)
        self.assertFalse(os.path.exists(self.state("host-login.txt")))
        src = open(os.path.join(ROOT, "kit", "leyline")).read()
        for bad in ("account create", "set password", "INSERT INTO account", "make_verifier"):
            self.assertNotIn(bad, src)
        # `leyline gm NAME` names the GM account and nothing else
        await self.leyline("host", "--config-only", LEYLINE_NAME="X Realm", LEYLINE_GM="first")
        await self.leyline("gm", "second")
        self.assertEqual(self.cfg()["gm_name"], "SECOND")
        self.assertNotIn("gm", self.cfg())


class OneDomainLine(unittest.TestCase):
    def test_domains_come_from_leyline_env(self):
        from wunet import domains
        d = domains.load({})
        self.assertEqual(d, {"domain": "openvanilla.app", "relay": "relay.openvanilla.app",
                             "site": "https://openvanilla.app", "join": "https://relay.openvanilla.app"})
        d = domains.load({"LEYLINE_DOMAIN": "leyline.example"})
        self.assertEqual((d["relay"], d["site"], d["join"]),
                         ("relay.leyline.example", "https://leyline.example", "https://relay.leyline.example"))
        env = open(domains.FILE).read()
        self.assertEqual([ln for ln in env.splitlines() if ln and not ln.startswith("#")], ["LEYLINE_DOMAIN=openvanilla.app"])
        # no hard-coded domain left in the host kit's and relay's code paths
        for p in ("kit/tools/wuhost/setup.py", "kit/tools/wuhost/agent.py", "relay/wurelay/relay.py",
                  "relay/wurelay/listing.py", "kit/leyline", "kit/host-wrath-realm.sh"):
            src = open(os.path.join(ROOT, p)).read()
            self.assertNotIn('"relay.openvanilla.app"', src, p)
            self.assertNotIn('"https://openvanilla.app"', src, p)
            self.assertNotIn(":-relay.openvanilla.app}", src, p)


if __name__ == "__main__":
    unittest.main()
