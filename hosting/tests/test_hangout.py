"""The official realm, Wrath Unleashed (the operator's own realm as a Leyline Beacon) and website pairing, against the REAL relay and
agent with a fake AzerothCore realm:

  * `setup.py official` writes a public, signup-off, "official" host.json with a key made where it runs;
  * its agent connects, is listed (players and bots from the play page's status document, never the database),
    and never touches the realm list, accounts or GM rights, even when it could reach the database;
  * the relay refuses join-page signups for it; a hop through the browser bridge logs in with the player's EXISTING
    account (the Wrath login): no account is made;
  * pairing: a realm shows sha256("leyline-pair-v1\\n" + token); GET /api/pair/<hash> finds it, the first realm keeps
    it, it survives a relay restart, a claim change later re-pairs, junk is a 404, lookups are rate limited.
"""
import asyncio
import io
import json
import os
import shutil
import stat
import tempfile
import threading
import unittest
from contextlib import redirect_stdout, redirect_stderr
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from helpers import FakeDB, FakeRealm, Rig, WSStream, agentmod, free_port, free_range, http, keys, relaymod
from wunet import ws, wire335

PLAY = "https://wrath.openvanilla.test"


class Status(BaseHTTPRequestHandler):
    doc = {"online": True, "players": 7, "bots": 31, "uptime_s": 999, "realm": "WrathUnleashed"}

    def log_message(self, *a):
        pass

    def do_GET(self):
        b = json.dumps(self.doc).encode()
        self.send_response(200); self.send_header("Content-Length", str(len(b))); self.end_headers(); self.wfile.write(b)


def hop_opener(base, rid, headers=None):
    async def opener(host, port):
        sock = await ws.connect(f"{base}/ws/{rid}/{'auth' if port == 3724 else 'world'}?host={host}", headers=headers)
        s = WSStream(sock)
        return s.reader, s
    return opener


def run_setup(kit, *argv):
    os.environ["WU_KIT"] = kit
    import importlib
    from wuhost import setup
    setup = importlib.reload(setup)
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        setup.main(list(argv))
    return out.getvalue(), err.getvalue()


class Hangout(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.mkdtemp(prefix="wu-hangout-")
        lo, hi = free_range(20)
        self.relay = await relaymod.Relay(relaymod.Config(
            name="relay.test", http_bind="127.0.0.1:0", game_bind="127.0.0.1", shared_auth_port=free_port(),
            port_min=lo, port_max=hi, state_file=os.path.join(self.tmp, "relay", "state.json"),
            play_origins=[PLAY], listing_site_secret="s")).start()
        self.base = f"ws://127.0.0.1:{self.relay.http_port()}"
        self.http = f"http://127.0.0.1:{self.relay.http_port()}"
        self.realm = await FakeRealm(realm_name="WrathUnleashed", world_address="play.example:8085").start()
        self.status = ThreadingHTTPServer(("127.0.0.1", 0), Status)
        threading.Thread(target=self.status.serve_forever, daemon=True).start()
        self.kit = os.path.join(self.tmp, "hangout")
        os.makedirs(self.kit)
        with open(os.path.join(self.kit, "rules.txt"), "w") as f:
            f.write("# comment\nBe kind.\nDuels by consent.\n")
        out, _ = run_setup(self.kit, "official", "--name", "Wrath Unleashed", "--relay", "relay.test",
                           "--relay-url", self.base + "/agent", "--listing-url", self.http + "/api/listing/heartbeat",
                           "--auth-service", "ov-ac-authserver:3724", "--world-service", "ov-ac-worldserver:8085",
                           "--status-url", f"http://127.0.0.1:{self.status.server_address[1]}/wrath/status.json",
                           "--tagline", "The realm's own Dalaran", "--rules-file", os.path.join(self.kit, "rules.txt"))
        self.rid = json.loads(out)["realm_id"]
        self.db = FakeDB(self.realm)
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
        self.status.shutdown()
        shutil.rmtree(self.tmp, ignore_errors=True)

    async def test_official_config(self):
        cfg = json.load(open(os.path.join(self.kit, "state", "host.json")))
        self.assertTrue(cfg["official"])
        self.assertEqual((cfg["visibility"], cfg["signup"], cfg["realmlist"], cfg["profile"]), ("public", "off", "keep", "dalaran"))
        self.assertEqual((cfg["auth_service"], cfg["world_service"]), ("ov-ac-authserver:3724", "ov-ac-worldserver:8085"))
        for k in ("invite_secret", "host_secret", "gm", "gm_name", "db_password", "claim"):
            self.assertNotIn(k, cfg)
        self.assertEqual(cfg["record"]["rules"], ["Be kind.", "Duels by consent."])
        kp = os.path.join(self.kit, "state", "realm.key")
        self.assertEqual(stat.S_IMODE(os.stat(kp).st_mode), 0o600)
        self.assertEqual(keys.realm_id(keys.public_key(keys.load_or_create(kp))), self.rid)
        # again: the same key and id; brand words refused; a host kit folder refused
        out, _ = run_setup(self.kit, "official", "--name", "Wrath Unleashed", "--auth-service", "a:1", "--world-service", "b:2")
        self.assertEqual(json.loads(out)["realm_id"], self.rid)
        with self.assertRaises(SystemExit):
            run_setup(self.kit, "official", "--name", "WoW Hangout", "--auth-service", "a:1", "--world-service", "b:2")
        other = os.path.join(self.tmp, "kit")
        os.makedirs(other)
        run_setup(other, "init", "--name", "Frost Haven", "--profile", "main", "--visibility", "private", "--gm-name", "frostgm")
        with self.assertRaises(SystemExit):
            run_setup(other, "official", "--name", "Wrath Unleashed", "--auth-service", "a:1", "--world-service", "b:2")
        with self.assertRaises(SystemExit):   # and the other way round
            run_setup(self.kit, "init", "--name", "X", "--profile", "main", "--visibility", "public")

    async def test_listed_with_status_numbers_and_hands_off(self):
        self.assertIn(self.rid, self.relay.sessions)
        st, doc, _ = await http("GET", f"{self.http}/api/listing/realms.json")
        rec = next(r for r in doc["realms"] if r["community"]["realmId"] == self.rid)
        self.assertEqual((rec["name"], rec["state"], rec["profile"]["ruleset"]), ("Wrath Unleashed", "live", "dalaran"))
        self.assertEqual((rec["community"]["lastHeartbeat"]["players"], rec["community"]["lastHeartbeat"]["bots"]), (7, 31))
        st, doc, _ = await http("GET", f"{self.http}/r/{self.rid}/status.json")
        self.assertEqual((doc["online"], doc["players"], doc["bots"]), (True, 7, 31))
        await asyncio.sleep(0.3)   # several housekeeping ticks
        self.assertEqual(self.db.address_calls, [], "the realm list row is never touched")
        self.assertEqual(self.realm.world_address, "play.example:8085")
        self.assertEqual(self.db.gm, {}, "no GM rights granted")
        self.assertFalse(self.agent.address_done)

    async def test_no_signups_and_a_hop_uses_the_existing_account(self):
        self.realm.add_account("wr000123", "WrathPass1234567")   # the player's Wrath account, made by the website
        before = set(self.realm.accounts)
        st, doc, _ = await http("POST", f"{self.http}/api/realms/{self.rid}/accounts",
                                {"username": "newbie1", "salt": "00" * 32, "verifier": "11" * 32})
        self.assertEqual(st, 403)
        rep = await wire335.full_run("relay.test", 3724, "wr000123", "WrathPass1234567",
                                     opener=hop_opener(self.base, self.rid, {"Origin": PLAY}))
        self.assertEqual(rep["steps"][-1], "logout")
        self.assertEqual(rep["realm"]["address"], "play.example:8085", "its own realm list, not a relay address")
        self.assertEqual(set(self.realm.accounts), before, "no account made by the hop")
        with self.assertRaises(Exception):   # a wrong password is still a wrong password
            await wire335.full_run("relay.test", 3724, "wr000123", "nope", opener=hop_opener(self.base, self.rid, {"Origin": PLAY}))


class Pairing(unittest.IsolatedAsyncioTestCase):
    async def test_pair_lookup(self):
        async with Rig(pair_lookups_per_ip_min=1000) as r:
            st, doc, _ = await http("GET", f"{r.http}/api/pair/{'0' * 64}")
            self.assertEqual(st, 404)
            st, _, _ = await http("GET", f"{r.http}/api/pair/notahash")
            self.assertEqual(st, 404)
            # the host gets a claim token from the website: host.json changes, the agent tells the relay
            cfg = json.load(open(os.path.join(r.host_dir, "host.json")))
            cfg["claim"] = "websitetokenwebsitetoken"
            json.dump(cfg, open(os.path.join(r.host_dir, "host.json"), "w"))
            os.utime(os.path.join(r.host_dir, "host.json"), (1, 1))
            h = keys.pair_hash("websitetokenwebsitetoken")
            for _ in range(100):
                st, doc, _ = await http("GET", f"{r.http}/api/pair/{h}")
                if st == 200:
                    break
                await asyncio.sleep(0.05)
            self.assertEqual((st, doc), (200, {"realm_id": r.rid, "online": True}))
            self.assertNotIn("websitetokenwebsitetoken", json.dumps(r.relay.state), "the relay keeps the hash, never the token")
            # a second realm showing the same hash (a copied download) doesn't take it over
            other_dir = os.path.join(r.tmp, "copy")
            os.makedirs(other_dir)
            import helpers
            c2, _ = helpers.make_host_state(other_dir, relay_url=r.base + "/agent")
            c2["claim"] = "websitetokenwebsitetoken"
            json.dump(c2, open(os.path.join(other_dir, "host.json"), "w"))
            a2 = agentmod.Agent(other_dir, db=None, services={3724: ("127.0.0.1", 9), 8085: ("127.0.0.1", 9)})
            a2.task = asyncio.ensure_future(a2.run())
            r.agents.append(a2)
            for _ in range(100):
                if c2["realm_id"] in r.relay.sessions:
                    break
                await asyncio.sleep(0.05)
            self.assertIn(c2["realm_id"], r.relay.sessions)
            st, doc, _ = await http("GET", f"{r.http}/api/pair/{h}")
            self.assertEqual(doc["realm_id"], r.rid)
            # it survives a relay restart (the state file), and says offline while the realm is away
            r.relay.dirty = True
            r.relay.save()
            again = relaymod.Relay(r.relay.cfg)
            self.assertEqual(again.state["pairs"][h], r.rid)

    async def test_pair_rate_limit(self):
        async with Rig(pair_lookups_per_ip_min=2) as r:
            codes = [(await http("GET", f"{r.http}/api/pair/{'1' * 64}", headers={"X-Forwarded-For": "198.51.100.9"}))[0]
                     for _ in range(3)]
            self.assertEqual(codes, [404, 404, 429])

    async def test_bad_pair_hash_in_hello_is_refused(self):
        async with Rig() as r:
            err, _ = r.relay.check_hello({"hello": {"pair_sha256": "zz"}}, "x")
            self.assertTrue(err)


if __name__ == "__main__":
    unittest.main()
