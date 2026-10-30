"""The Leyline mesh (docs/LEYLINE-MESH.md): signed records, expiry, staff blocks, the merge rules, bucket summaries,
relay choice, the relay as a mesh node (in-process gossip, then real HTTP between two relays and an agent), the
community relay profile, and that all of it is off by default."""
import asyncio
import json
import os
import tempfile
import time
import types
import unittest

from helpers import Rig, free_range  # noqa: F401 (sets sys.path)
from wunet import keys, mesh
from wuhost import meshpick
from wurelay import httpd, meshnode
from wurelay import relay as relaymod

NOW = 1_800_000_000


class Realm:
    def __init__(self):
        self.sec = keys.new_secret()
        self.pub = keys.public_key(self.sec)
        self.rid = keys.realm_id(self.pub)
        self.seq = 0

    def beat(self, ts=NOW, name="Frost Haven", relay="relay.test", relays=None, online=True, players=3, seq=None):
        self.seq = seq if seq is not None else self.seq + 1
        b = {"v": 1, "realm_id": self.rid, "pubkey": self.pub.hex(), "seq": self.seq, "ts": ts, "relay": relay,
             "record": {"name": name, "tagline": "Duels all day", "tags": ["pvp"]},
             "status": {"online": online, "players": players, "bots": 0, "uptime_s": 10}}
        if relays:
            b["relays"] = relays
        return b, keys.sign_doc(self.sec, b, keys.CTX_HEARTBEAT)


class Node:
    def __init__(self, host="relay.test"):
        self.sec = keys.new_secret()
        self.pub = keys.public_key(self.sec).hex()
        self.host = host

    def ep(self, rid, ts=NOW, relay=None, auth=40000, ws=True):
        return mesh.endpoint(self.sec, rid, relay or self.host, auth, auth + 1, ws, ts)

    def rec(self, ts=NOW, seq=1, **kw):
        return mesh.relay_record(self.sec, self.host, seq, ts, **kw)


def realm_rec(r, n, ts=NOW, **kw):
    b, s = r.beat(ts=ts, relay=n.host, **kw)
    return mesh.realm_record(b, s, [n.ep(r.rid, ts)])


class Records(unittest.TestCase):
    def test_a_realm_record_is_checked_end_to_end(self):
        r, n = Realm(), Node()
        rec = realm_rec(r, n)
        rid, ver = mesh.check(json.loads(json.dumps(rec)), NOW)
        self.assertEqual((rid, ver), ("r-" + r.rid, 1))
        bad = json.loads(json.dumps(rec))
        bad["beat"]["record"]["name"] = "Forged"
        with self.assertRaises(mesh.Bad):
            mesh.check(bad, NOW)
        other = Realm()
        bad = json.loads(json.dumps(rec))
        bad["beat"]["realm_id"] = other.rid
        with self.assertRaisesRegex(mesh.Bad, "realm id"):
            mesh.check(bad, NOW)
        with self.assertRaisesRegex(mesh.Bad, "expired"):
            mesh.check(json.loads(json.dumps(rec)), NOW + mesh.REALM_TTL + 1)
        with self.assertRaisesRegex(mesh.Bad, "expired"):
            mesh.check(json.loads(json.dumps(rec)), NOW - mesh.SKEW - 1)
        with self.assertRaisesRegex(mesh.Bad, "too big"):
            b, s = r.beat(name="x" * 7000)
            mesh.check(mesh.realm_record(b, s), NOW)

    def test_endpoints_must_be_chosen_by_the_realm_and_signed_by_the_relay(self):
        r, n, rogue = Realm(), Node(), Node("evil.example.org")
        b, s = r.beat(relay=n.host)
        eps = [n.ep(r.rid), rogue.ep(r.rid), n.ep(Realm().rid), n.ep(r.rid, ts=NOW - mesh.ENDPOINT_TTL - 1)]
        forged = n.ep(r.rid)
        forged["att"]["auth_port"] = 1
        eps.append(forged)
        rec = mesh.realm_record(b, s, eps)
        mesh.check(rec, NOW)
        self.assertEqual(len(rec["endpoints"]), 1, "only the relay the realm signed, for this realm, fresh, untampered")
        # a realm may sign several relays (the beat's optional "relays")
        b, s = r.beat(relay=n.host, relays=["evil.example.org"])
        rec = mesh.realm_record(b, s, [n.ep(r.rid), rogue.ep(r.rid)])
        mesh.check(rec, NOW)
        self.assertEqual({e["att"]["relay"] for e in rec["endpoints"]}, {"relay.test", "evil.example.org"})

    def test_relay_and_block_records(self):
        n = Node()
        rec = n.rec(caps={"realms": 25, "streams": 512}, load={"realms": 3, "streams": 10}, volunteer=True)
        self.assertTrue(mesh.check(json.loads(json.dumps(rec)), NOW)[0].startswith("n-"))
        bad = json.loads(json.dumps(rec))
        bad["node"]["http"] = "https://another.example.org"
        with self.assertRaises(mesh.Bad):
            mesh.check(bad, NOW)
        with self.assertRaisesRegex(mesh.Bad, "expired"):
            mesh.check(json.loads(json.dumps(rec)), NOW + mesh.NODE_TTL + 1)
        staff = keys.new_secret()
        sp = keys.public_key(staff).hex()
        r = Realm()
        blk = mesh.block_record(staff, "r-" + r.rid, "spam", NOW, NOW + 86400)
        with self.assertRaisesRegex(mesh.Bad, "staff"):
            mesh.check(blk, NOW)       # no staff key pinned: no block is valid
        self.assertEqual(mesh.check(blk, NOW, staff_keys=(sp,))[0], "b-r-" + r.rid)
        with self.assertRaises(mesh.Bad):
            mesh.check(mesh.block_record(staff, "r-" + r.rid, "x", NOW, NOW + mesh.BLOCK_MAX_TTL + 10), NOW, (sp,))
        with self.assertRaises(mesh.Bad):
            mesh.check(blk, NOW + 86401, (sp,))


class Merge(unittest.TestCase):
    def test_newer_wins_older_is_refused_and_endpoints_merge(self):
        st, r, a, b = mesh.Store(), Realm(), Node("a.relay.test"), Node("b.relay.test")
        b1, s1 = r.beat(relay=a.host, relays=[b.host])
        self.assertTrue(st.offer(mesh.realm_record(b1, s1, [a.ep(r.rid)]), NOW)[0])
        self.assertEqual(st.offer(mesh.realm_record(b1, s1, [a.ep(r.rid)]), NOW), (False, "same"))
        self.assertTrue(st.offer(mesh.realm_record(b1, s1, [b.ep(r.rid)]), NOW)[0], "same beat, a new endpoint")
        self.assertEqual(len(st.recs["r-" + r.rid]["endpoints"]), 2)
        b2, s2 = r.beat(relay=a.host, name="Frost Haven II")
        self.assertTrue(st.offer(mesh.realm_record(b2, s2, []), NOW + 60)[0])
        cur = st.recs["r-" + r.rid]
        self.assertEqual(cur["beat"]["record"]["name"], "Frost Haven II")
        self.assertEqual([e["att"]["relay"] for e in cur["endpoints"]], [a.host], "b is no longer signed by the realm")
        self.assertEqual(st.offer(mesh.realm_record(b1, s1, [a.ep(r.rid)]), NOW + 60), (False, "older"))

    def test_equivocation_is_settled_the_same_way_everywhere(self):
        r, n = Realm(), Node()
        x = realm_rec(r, n, seq=7, name="One")
        y = realm_rec(r, n, seq=7, name="Two")
        s1, s2 = mesh.Store(), mesh.Store()
        for rec in (x, y):
            s1.offer(rec, NOW)
        for rec in (y, x):
            s2.offer(rec, NOW)
        self.assertEqual(s1.recs["r-" + r.rid]["sig"], s2.recs["r-" + r.rid]["sig"])

    def test_forgeries_never_enter_and_dead_realms_expire(self):
        st, r, n = mesh.Store(), Realm(), Node()
        rec = realm_rec(r, n)
        forged = json.loads(json.dumps(rec))
        forged["beat"]["status"]["players"] = 999
        self.assertFalse(st.offer(forged, NOW)[0])
        self.assertTrue(st.offer(rec, NOW)[0])
        # nobody can keep it alive: re-offering the same signed record after its expiry is refused
        self.assertEqual(st.sweep(NOW + mesh.REALM_TTL + 1), 1)
        self.assertFalse(st.offer(rec, NOW + mesh.REALM_TTL + 1)[0])
        self.assertEqual(st.recs, {})

    def test_staff_blocks_drop_and_refuse(self):
        staff = keys.new_secret()
        st = mesh.Store(staff_keys=(keys.public_key(staff).hex(),))
        r, n = Realm(), Node()
        st.offer(realm_rec(r, n), NOW)
        self.assertTrue(st.offer(mesh.block_record(staff, "r-" + r.rid, "spam", NOW, NOW + 3600), NOW)[0])
        self.assertNotIn("r-" + r.rid, st.recs)
        self.assertEqual(st.offer(realm_rec(r, n), NOW), (False, "refused: blocked"))
        rogue = keys.new_secret()
        self.assertFalse(st.offer(mesh.block_record(rogue, "r-" + Realm().rid, "x", NOW, NOW + 60), NOW)[0])

    def test_summary_and_cursor(self):
        a, b = mesh.Store(), mesh.Store()
        recs = [realm_rec(Realm(), Node()) for _ in range(20)]
        for x in recs:
            a.offer(x, NOW)
        for x in reversed(recs):
            b.offer(x, NOW)
        self.assertEqual(a.summary(), b.summary(), "the order records arrived in does not matter")
        b.offer(realm_rec(Realm(), Node()), NOW)
        diff = [i for i, (x, y) in enumerate(zip(a.summary(), b.summary())) if x != y]
        self.assertEqual(len(diff), 1)
        got, cur = a.since(0)
        self.assertEqual((len(got), cur), (20, 20))
        self.assertEqual(a.since(cur), ([], 20))
        self.assertEqual(len(a.since(999)[0]), 20, "a cursor from before a restart starts over")
        self.assertLessEqual(len(a.in_buckets(set(diff))), 1)


class Choice(unittest.TestCase):
    def test_choose_endpoint(self):
        r = Realm()
        seed, v1, v2 = Node("relay.test"), Node("v1.example.org"), Node("v2.example.org")
        b, s = r.beat(relay=seed.host, relays=[v1.host, v2.host])
        rec = mesh.realm_record(b, s, [seed.ep(r.rid), v1.ep(r.rid, auth=41000), v2.ep(r.rid, auth=41010, ws=False)])
        mesh.check(rec, NOW)
        nodes = {v1.host: {"caps": {"streams": 100, "realms": 10}, "load": {"streams": 10, "realms": 1}},
                 v2.host: {"caps": {"streams": 100, "realms": 10}, "load": {"streams": 0, "realms": 1}}}
        rtt = {seed.host: 120, v1.host: 30, v2.host: 25}
        pick = lambda **k: mesh.choose_endpoint(rec, nodes, rtt, seeds={seed.host}, **k)["att"]["relay"]  # noqa: E731
        self.assertEqual(pick(volunteers=False), seed.host, "volunteers off: the seed (and the realm's own relay)")
        self.assertEqual(pick(volunteers=True), v2.host, "nearest, least loaded")
        self.assertEqual(pick(volunteers=True, browser=True), v1.host, "the browser needs the WebSocket bridge")
        nodes[v1.host]["load"] = {"streams": 100, "realms": 10}
        self.assertEqual(pick(volunteers=True, browser=True), seed.host, "a full volunteer costs more than the seed")
        self.assertIsNone(mesh.choose_endpoint(mesh.realm_record(b, s, []), nodes, rtt, seeds=set(), volunteers=True))

    def test_host_side_pick_and_the_volunteer_env(self):
        nodes = [{"host": "relay.test", "caps": {"realms": 100}, "load": {"realms": 90}},
                 {"host": "v1.example.org", "caps": {"realms": 25}, "load": {"realms": 25}},
                 {"host": "v2.example.org", "caps": {"realms": 25}, "load": {"realms": 5}}]
        self.assertEqual(meshpick.pick_relay(nodes, volunteers=False, seeds={"relay.test"}), "relay.test")
        self.assertEqual(meshpick.pick_relay(nodes, volunteers=True, seeds={"relay.test"}), "v2.example.org")
        env = meshpick.volunteer_env("Relay.Example.org", region="eu", max_realms=10, bootstrap="https://relay.test,javascript:x")
        self.assertIn("RELAY_NAME=relay.example.org\n", env)
        self.assertIn("RELAY_MESH_BOOTSTRAP=https://relay.test\n", env)
        self.assertIn("RELAY_PORT_MAX=41021\n", env)
        with self.assertRaises(SystemExit):
            meshpick.volunteer_env("not a host")
        n = Node("v9.example.org")
        doc = {"relays": [n.rec(ts=int(time.time())), {"kind": "relay", "node": {"host": "x"}}]}
        got = meshpick.fetch_relays("https://a.test", get=lambda u: doc)
        self.assertEqual([g["host"] for g in got], ["v9.example.org"])


def cfg(tmp, **kw):
    base = dict(name="relay.test", http_bind="127.0.0.1:0", game_bind="127.0.0.1", shared_auth_port=0,
                state_file=os.path.join(tmp, "state.json"))
    base.update(kw)
    return relaymod.Config(**base)


class Req:
    def __init__(self, method, url, body=None, ip="10.0.0.1"):
        self.method, self.ip = method, ip
        path, _, q = url.partition("?")
        self.path = path
        self.query = dict(p.split("=", 1) for p in q.split("&") if "=" in p)
        self.body = json.dumps(body).encode() if body is not None else b""
        self.headers = {}

    def json(self):
        return json.loads(self.body)


def wire(nodes):
    """In-process transport: node.call(method, url, body) reaches the node whose http base starts the url."""
    by = {n.http_base: n for n in nodes}

    def make(me):
        async def call(method, url, body=None):
            base = next((b for b in by if url.startswith(b + "/")), None)
            if base is None or getattr(by[base], "down", False):
                return 0, None
            rest = [x for x in url[len(base):].split("?")[0].split("/") if x][2:]
            raw = await by[base].route(Req(method, url[len(base):], body), rest)
            head, _, body_b = raw.partition(b"\r\n\r\n")
            return int(head.split(b" ")[1]), json.loads(body_b or b"null")
        return call
    for n in nodes:
        n.call = make(n)


class MeshNodes(unittest.TestCase):
    def nodes(self, k):
        out = []
        for i in range(k):
            tmp = tempfile.mkdtemp()
            c = cfg(tmp, name=f"n{i}.relay.test", mesh=True, mesh_public_http=f"https://n{i}.relay.test",
                    mesh_bootstrap="https://n0.relay.test")
            out.append(meshnode.MeshNode(c, clock=lambda: NOW))
        wire(out)
        return out

    def test_gossip_spreads_signed_records_and_drops_forgeries(self):
        ns = self.nodes(6)

        async def go():
            for n in ns[1:]:
                await n.bootstrap_once(NOW)
            r, relay = Realm(), Node("n3.relay.test")
            ns[3].accept([realm_rec(r, relay)], NOW)
            forged = realm_rec(Realm(), relay)
            forged["beat"]["record"]["name"] = "Fake"
            ns[4].accept([forged], NOW)
            for _ in range(6):
                for n in ns:
                    await n.gossip_round(NOW)
            return r
        r = asyncio.run(go())
        for n in ns:
            self.assertIn("r-" + r.rid, n.store.recs, n.http_base)
            self.assertEqual(len(n.store.realms()), 1, "the forged record went nowhere")
            self.assertEqual(len(n.store.relays()), 6, "every node's signed relay record reached every node")
        doc = ns[0].realms_json(NOW)
        self.assertEqual(doc["source"], "mesh")
        self.assertEqual(doc["realms"][0]["profile"]["address"], "n3.relay.test")
        self.assertEqual(doc["realms"][0]["state"], "live")
        self.assertEqual(doc["realms"][0]["connect"]["url"], f"https://n3.relay.test/join/{r.rid}")

    def test_push_rate_limit_and_routes(self):
        n = self.nodes(1)[0]

        async def go():
            recs = [realm_rec(Realm(), Node()) for _ in range(5)]
            ok = await n.route(Req("POST", "/api/mesh/push", {"records": recs}), ["push"])
            many = await n.route(Req("POST", "/api/mesh/push", {"records": recs * 30}), ["push"])
            node = await n.route(Req("GET", "/api/mesh/node"), ["node"])
            return ok, many, node
        ok, many, node = asyncio.run(go())
        self.assertIn(b" 200 ", ok.split(b"\r\n")[0] + b" ")
        self.assertIn(b"429", many.split(b"\r\n")[0])
        self.assertIn(b'"kind":"relay"', node)


class Relays(unittest.TestCase):
    def test_off_by_default_and_the_volunteer_profile(self):
        tmp = tempfile.mkdtemp()
        old = {k: os.environ.pop(k, None) for k in ("RELAY_MESH", "RELAY_VOLUNTEER", "RELAY_MAX_REALMS")}
        try:
            c = relaymod.Config(state_file=os.path.join(tmp, "s.json"))
            self.assertFalse(c.mesh or c.volunteer)
            rl = relaymod.Relay(c)
            self.assertIsNone(rl.mesh, "no mesh node unless RELAY_MESH=1")
            out = asyncio.run(rl.route(Req("GET", "/api/mesh/node"), None, None))
            self.assertIn(b"404", out.split(b"\r\n")[0])
            v = relaymod.Config(state_file=os.path.join(tmp, "v.json"), volunteer=True)
            self.assertEqual((v.mesh, v.max_realms, v.kbps, v.shared_auth_port), (True, 25, 256, 0))
            v2 = relaymod.Config(state_file=os.path.join(tmp, "v2.json"), volunteer=True, max_realms=5)
            self.assertEqual(v2.max_realms, 5, "an explicit setting wins over the profile")
        finally:
            for k, x in old.items():
                if x is not None:
                    os.environ[k] = x


class CrossLanguage(unittest.TestCase):
    def test_the_launcher_test_vector_verifies_here(self):
        # launcher/src-tauri/src/p2p/mesh.rs python_signed_records_verify_here reads the same file
        p = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
                         "launcher", "src-tauri", "src", "p2p", "mesh-vector.json")
        with open(p, encoding="utf-8") as f:
            recs = json.load(f)["records"]
        rid, seq = mesh.check(json.loads(json.dumps(recs[0])), 1761700010)
        self.assertEqual((rid, seq), ("r-kzdvvj2umnduyauf", 1761700000123))
        self.assertTrue(mesh.check(recs[1], 1761700010)[0].startswith("n-"))


class Simulation(unittest.TestCase):
    def test_the_harness_runs_small(self):
        try:
            import numpy as np
        except ImportError:
            self.skipTest("numpy")
        import importlib.util
        here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        spec = importlib.util.spec_from_file_location("meshsim", os.path.join(here, "mesh-sim", "meshsim.py"))
        sim = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(sim)
        rng = np.random.default_rng(1)
        g = sim.gossip(500, rng, offline=0.3, malicious=0.1)
        self.assertEqual(g["reached"], 1.0)
        r = sim.real_merge(rng, n=30, realms=3, rounds=15)
        self.assertEqual(r["forged_or_tampered_records_accepted"], 0)
        self.assertEqual(r["records_left_after_expiry"], 0)
        d = sim.dht(500, rng, lookups=10, offline=0.3)
        self.assertGreater(d["found_closest_live_node"], 0.8)
        c = sim.relay_choice(rng, players=2000, realms=100, volunteers=30)
        self.assertEqual(c["unserved"], 0)


class EndToEnd(unittest.TestCase):
    def test_agent_heartbeat_to_relay_a_reaches_relay_b_over_http(self):
        async def go():
            async with Rig(mesh=True, mesh_public_http="http://relay.test") as rig:
                a = rig.relay
                for _ in range(200):
                    if a.mesh.store.realms():
                        break
                    await asyncio.sleep(0.05)
                self.assertTrue(a.mesh.store.realms(), "the realm's beat became a mesh record")
                lo, hi = free_range(10)
                tmp = tempfile.mkdtemp()
                b = await relaymod.Relay(cfg(tmp, name="b.relay.test", port_min=lo, port_max=hi, mesh=True,
                                             mesh_bootstrap=rig.http, mesh_public_http="http://b.relay.test")).start()
                try:
                    for _ in range(200):
                        if b.mesh.store.realms():
                            break
                        await asyncio.sleep(0.05)
                    bport = b.http_port()
                    doc = await asyncio.to_thread(meshnode._http, "GET", f"http://127.0.0.1:{bport}/api/mesh/realms.json")
                    mine = await asyncio.to_thread(meshnode._http, "GET", f"{rig.http}/api/listing/realms.json")
                finally:
                    await b.stop()
                return rig.rid, a.state["realms"][rig.rid]["auth"], doc, mine
        rid, auth, (st, doc), (st2, mine) = asyncio.run(go())
        self.assertEqual(st, 200)
        rec = [x for x in doc["realms"] if x["community"]["realmId"] == rid]
        self.assertEqual(len(rec), 1, "relay B lists a realm that only ever talked to relay A")
        self.assertEqual((rec[0]["profile"]["address"], rec[0]["profile"]["port"]), ("relay.test", auth))
        self.assertEqual(st2, 200)
        self.assertEqual(mine["realms"][0]["community"]["realmId"], rid, "today's listing API is unchanged")


if __name__ == "__main__":
    unittest.main()
