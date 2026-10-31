"""Time to listed (launch smoke S6, 2026-10-30): a new public realm, from its agent's first connect to the relay to
"live" on the relay's realm list, with the agent's REAL cadence (housekeeping every 5 s, first heartbeat as soon as
the tunnel is up, then every 60 s) and the relay's real heartbeat rate limit. Also: the Join line follows who may
make accounts (no "make a game account there" when sign-up is off), and a new public AzerothCore realm is listed with
Warden off (browser players on).

    cd hosting/tests && python3 -m pytest -q test_time_to_listed.py -s     (prints the measured seconds)
"""
import asyncio
import json
import os
import shutil
import tempfile
import time
import unittest

from helpers import ROOT, FakeDB, free_port, free_range, http
from fake_realm import FakeRealm
from wuhost import agent as agentmod
from wurelay import listing as listingmod, relay as relaymod

BUDGET_S = 10.0   # "a stranger ... sees it listed in minutes": the relay side must be seconds


class TimeToListed(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.mkdtemp(prefix="leyline-ttl-")
        self.kit = os.path.join(self.tmp, "kit")
        os.makedirs(self.kit)
        src = os.path.join(ROOT, "kit")
        for f in ("leyline", "host-wrath-realm.sh"):
            shutil.copy(os.path.join(src, f), self.kit)
        shutil.copytree(os.path.join(src, "tools"), os.path.join(self.kit, "tools"),
                        ignore=shutil.ignore_patterns("__pycache__"))
        lo, hi = free_range(20)
        self.relay = await relaymod.Relay(relaymod.Config(
            name="relay.test", http_bind="127.0.0.1:0", game_bind="127.0.0.1", shared_auth_port=free_port(),
            port_min=lo, port_max=hi, state_file=os.path.join(self.tmp, "relay", "state.json"),
            site_url="https://leyline.test", site_origins=["https://leyline.test"], listing_site_secret="site-secret",
            accounts_per_ip_hour=20)).start()
        self.http = f"http://127.0.0.1:{self.relay.http_port()}"
        self.realm = await FakeRealm(realm_name="(not set yet)").start()
        self.db = FakeDB(self.realm)
        self.agent = None

    async def asyncTearDown(self):
        if self.agent:
            self.agent.stop_ev.set()
            self.agent.close_all()
            self.agent.task.cancel()
        await self.relay.stop()
        await self.realm.stop()
        shutil.rmtree(self.tmp, ignore_errors=True)

    async def leyline(self, *args, **env):
        e = dict(os.environ, LEYLINE_LOCAL_TOOLS="1", LEYLINE_NONINTERACTIVE="1", WU_RELAY="relay.test",
                 WU_RELAY_URL=f"ws://127.0.0.1:{self.relay.http_port()}/agent",
                 WU_LISTING_URL=self.http + "/api/listing/heartbeat")
        e.update(env)
        p = await asyncio.create_subprocess_exec("bash", os.path.join(self.kit, "leyline"), *args, env=e,
                                                 stdin=asyncio.subprocess.DEVNULL, stdout=asyncio.subprocess.PIPE,
                                                 stderr=asyncio.subprocess.STDOUT)
        out, _ = await asyncio.wait_for(p.communicate(), 60)
        self.assertEqual(p.returncode, 0, out.decode())
        return out.decode()

    async def listed(self, rid):
        st, doc, _ = await http("GET", f"{self.http}/api/listing/realms.json")
        r = next((x for x in doc.get("realms", []) if x["community"]["realmId"] == rid), None) if st == 200 else None
        return r if r and r["state"] == "live" else None

    async def test_listed_seconds_after_connect(self):
        await self.leyline("host", "--config-only", LEYLINE_NAME="Quick Start", LEYLINE_GM="hostgm",
                           LEYLINE_RULESET="main", LEYLINE_VISIBILITY="public")
        cfg = json.load(open(os.path.join(self.kit, "state", "host.json")))
        rid = cfg["realm_id"]
        self.assertEqual((cfg["browser"], cfg["warden"]), (True, False))
        self.agent = agentmod.Agent(os.path.join(self.kit, "state"), db=self.db,
                                    services={3724: ("127.0.0.1", self.realm.auth_port),
                                              8085: ("127.0.0.1", self.realm.world_port)})
        self.assertEqual(self.agent.heartbeat_every, 60)   # the real cadence, not a test's
        t0 = time.monotonic()
        self.agent.task = asyncio.ensure_future(self.agent.run())
        t_conn = rec = None
        while time.monotonic() - t0 < 30:
            if t_conn is None and rid in self.relay.sessions:
                t_conn = time.monotonic()
            rec = await self.listed(rid)
            if rec:
                break
            await asyncio.sleep(0.05)
        t_list = time.monotonic()
        self.assertIsNotNone(rec, "not listed within 30 s")
        connect_s, listed_s = (t_conn or t_list) - t0, t_list - (t_conn or t0)
        print(f"\nS6 time to listed: agent start -> relay tunnel {connect_s:.2f} s, tunnel -> live on the list "
              f"{listed_s:.2f} s, total {t_list - t0:.2f} s")
        self.assertLess(t_list - t0, BUDGET_S)
        self.assertFalse(rec["profile"]["warden"])
        st, info, _ = await http("GET", f"{self.http}/api/realms/{rid}")   # what the host's page shows
        self.assertTrue(st == 200 and info["listed"] is True and 0 <= info["listed_in_s"] < BUDGET_S, info)
        print(f"relay says: listed in {info['listed_in_s']} s")
        self.assertIn("make a game account there", rec["connect"]["note"])   # a public realm: sign-up open

        # the Join line follows sign-up, live from the agent's session (no new record needed)
        self.relay.sessions[rid].signup = "off"
        rec = await self.listed(rid)
        self.assertNotIn("make a game account", rec["connect"]["note"])
        self.assertIn("account you already have", rec["connect"]["note"])
        self.relay.sessions[rid].signup = "open"
        rec = await self.listed(rid)
        self.assertIn("make a game account there", rec["connect"]["note"])


class JoinNote(unittest.TestCase):
    def test_notes(self):
        self.assertNotIn("make a game account", listingmod.join_note("off"))
        self.assertIn("invite link", listingmod.join_note("invite"))
        self.assertIn("make a game account there", listingmod.join_note("open"))
        self.assertNotIn("make a game account", listingmod.join_note(None))
        self.assertEqual(listingmod.clean_record({"name": "x", "signup": "off"})["signup"], "off")
        self.assertIsNone(listingmod.clean_record({"name": "x", "signup": "<b>"})["signup"])


if __name__ == "__main__":
    unittest.main()
