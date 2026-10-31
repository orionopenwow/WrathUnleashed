"""The Leyline network listing (hosting/relay/wurelay/listing.py): the 2026-10-29 listing quality fields, checked and
capped; uptime from heartbeats; the fair score; auto-hide; the network totals; the region estimate; direct connect
(ready but off); and an rtt probe and the setup.py fields end to end with a real relay and agent."""
import asyncio
import json
import os
import tempfile
import time
import types
import unittest

from helpers import Rig, http  # noqa: F401 (sets sys.path)
from wunet import keys
from wurelay import listing


def cfg(**kw):
    d = tempfile.mkdtemp()
    base = {"state_file": os.path.join(d, "state.json"), "name": "relay.test", "join_base": None, "region": "",
            "advertise_direct": False}
    base.update(kw)
    return types.SimpleNamespace(**base)


class Host:
    def __init__(self):
        self.sec = keys.new_secret()
        self.pub = keys.public_key(self.sec)
        self.rid = keys.realm_id(self.pub)
        self.seq = 0

    def beat(self, now, record=None, online=True, players=3, bots=0):
        self.seq += 1
        b = {"v": 1, "realm_id": self.rid, "pubkey": self.pub.hex(), "seq": self.seq, "ts": int(now),
             "record": record or {"name": "Frost Haven"},
             "status": {"online": online, "players": players, "bots": bots, "uptime_s": 10}}
        return {"beat": b, "sig": keys.sign_doc(self.sec, b, keys.CTX_HEARTBEAT)}


def rd(p):
    with open(p, encoding="utf-8") as f:
        return json.load(f)


def wr(p, doc):
    with open(p, "w", encoding="utf-8") as f:
        json.dump(doc, f)


def run_for(L, h, start, seconds, every=60, **kw):
    t = start
    while t <= start + seconds:
        st, body = L.heartbeat(h.beat(t, **kw), "198.51.100.1", now=t)
        assert st == 200, body
        t += every
    return t - every


class Fields(unittest.TestCase):
    def test_new_fields_checked_and_capped(self):
        rec = listing.clean_record({"name": "A", "core": "trinitycore", "build": 5875,
                                    "tags": ["PvP", "rp", "evil", "pvp", 7] + ["x"] * 50, "region": "eu",
                                    "language": "pt-BR", "max_players": 120, "direct": True})
        self.assertEqual((rec["core"], rec["build"], rec["tags"], rec["region"], rec["language"], rec["max_players"],
                          rec["direct"]), ("trinitycore", 5875, ["pvp", "rp"], "eu", "pt-BR", 120, True))
        bad = listing.clean_record({"name": "A", "core": "<script>", "build": 99999, "tags": "pvp", "region": "mars",
                                    "language": "english please", "max_players": 10**9, "direct": "yes"})
        self.assertEqual((bad["core"], bad["build"], bad["tags"], bad["region"], bad["language"], bad["max_players"],
                          bad["direct"]), ("azerothcore", 12340, [], None, None, None, False))
        self.assertIsNone(listing.clean_record({"name": "A", "build": True})["max_players"])
        self.assertEqual(listing.clean_record({"name": "A", "build": True})["build"], 12340, "a bool is not a build")

    def test_old_agents_still_list(self):
        L, h, now = listing.Listing(cfg()), Host(), time.time()
        self.assertEqual(L.heartbeat(h.beat(now), "1.2.3.4", now=now)[0], 200)
        r = L.realms_json(now)["realms"][0]
        self.assertEqual((r["profile"]["build"], r["profile"]["version"], r["profile"]["game"], r["profile"]["core"]),
                         (12340, "3.3.5a", "wrath-3.3.5a", "azerothcore"))
        self.assertEqual((r["tags"], r["region"], r["language"], r["maxPlayers"]), ([], None, None, None))
        self.assertEqual(r["community"]["uptime"], {"h24": None, "d7": None}, "under an hour: not known yet")
        self.assertTrue(r["community"]["new"])
        self.assertFalse(r["community"]["directConnect"])

    def test_record_carries_the_fields(self):
        L, h, now = listing.Listing(cfg()), Host(), time.time()
        L.heartbeat(h.beat(now, record={"name": "Old Days", "build": 5875, "core": "vmangos", "tags": ["blizzlike"],
                                        "region": "na-east", "language": "en", "max_players": 50}), "1.2.3.4", now=now)
        r = L.realms_json(now)["realms"][0]
        self.assertEqual((r["profile"]["version"], r["profile"]["game"], r["profile"]["core"]),
                         ("1.12.1", "classic-1.12.1", "vmangos"))
        self.assertEqual((r["tags"], r["region"], r["language"], r["maxPlayers"]), (["blizzlike"], "na-east", "en", 50))


class Uptime(unittest.TestCase):
    def test_uptime_24h_and_7d_from_heartbeats(self):
        L, h = listing.Listing(cfg()), Host()
        t0 = 1_800_000_000
        t = run_for(L, h, t0, 12 * 3600)                  # 12 h online
        t = run_for(L, h, t + 12 * 3600, 12 * 3600)       # 12 h silent, then 12 h online again
        e = L.entries[h.rid]
        self.assertAlmostEqual(L.uptime(e, t, 86400), 50, delta=2)
        self.assertAlmostEqual(L.uptime(e, t, 7 * 86400), 67, delta=2, msg="36 h watched, 24 h of it online")
        self.assertEqual(len(e["up"]) <= 7 * 24 + 1, True)

    def test_offline_beats_do_not_count(self):
        L, h = listing.Listing(cfg()), Host()
        t = run_for(L, h, 1_800_000_000, 2 * 3600, online=False)
        self.assertEqual(L.uptime(L.entries[h.rid], t, 86400), 0)
        r = L.realms_json(t)["realms"][0]
        self.assertEqual((r["state"], r["community"]["score"]), ("offline", 0.0))

    def test_history_is_pruned_to_a_week(self):
        L, h = listing.Listing(cfg()), Host()
        e = {"up": {}}
        L.credit(e, 0, 10 * 86400)
        self.assertLessEqual(len(e["up"]), 7 * 24 + 1)
        self.assertTrue(all(v <= 3600 for v in e["up"].values()))


class Score(unittest.TestCase):
    def test_fair_order(self):
        s = listing.score
        self.assertEqual(s(False, 50, 50, 100, 100, True), 0.0, "offline is last")
        self.assertGreater(s(True, 10, 0, 90, 90, False), s(True, 0, 200, 90, 90, False), "people beat bots")
        self.assertLessEqual(s(True, 0, 10**5, None, None, False) - s(True, 0, 0, None, None, False), 5, "bots: at most 5")
        self.assertLess(s(True, 10**5, 0, 0, 0, False), 41, "players: diminishing, capped")
        self.assertGreater(s(True, 3, 0, 99, 99, False), s(True, 3, 0, 20, 20, False), "uptime counts")
        self.assertGreater(s(True, 0, 0, None, None, True), s(True, 0, 0, None, None, False), "new realms get seen")

    def test_listing_sorted_by_score_and_network_totals(self):
        L, now = listing.Listing(cfg()), time.time()
        a, b, c = Host(), Host(), Host()
        L.heartbeat(a.beat(now, record={"name": "Busy"}, players=20, bots=5), "1.1.1.1", now=now)
        L.heartbeat(b.beat(now, record={"name": "Botty"}, players=0, bots=300), "1.1.1.2", now=now)
        L.heartbeat(c.beat(now, record={"name": "Asleep"}, online=False, players=0), "1.1.1.3", now=now)
        doc = L.realms_json(now)
        self.assertEqual([r["name"] for r in doc["realms"]], ["Busy", "Botty", "Asleep"])
        self.assertEqual(doc["network"], {"realms": 2, "players": 20, "bots": 305})


class AutoHide(unittest.TestCase):
    def test_offline_then_hidden_then_forgotten(self):
        L, h = listing.Listing(cfg()), Host()
        t = run_for(L, h, 1_800_000_000, 3600)
        self.assertEqual(L.realms_json(t + 100)["realms"][0]["state"], "live")
        self.assertEqual(L.realms_json(t + listing.OFFLINE_AFTER + 1)["realms"][0]["state"], "offline")
        self.assertEqual(len(L.realms_json(t + listing.HIDE_AFTER - 10)["realms"]), 1)
        self.assertEqual(L.realms_json(t + listing.HIDE_AFTER + 10)["realms"], [], "6 h silent: off the list")
        self.assertIn(h.rid, L.entries, "the entry (uptime, first seen) is kept a while")
        L.realms_json(t + listing.FORGET_AFTER + 10)
        self.assertNotIn(h.rid, L.entries)

    def test_back_after_a_day_is_not_new_again(self):
        L, h = listing.Listing(cfg()), Host()
        t = run_for(L, h, 1_800_000_000, 600)
        later = t + listing.NEW_FOR - 60   # a week on: still remembered (first seen kept), so not "new" again
        L.heartbeat(h.beat(later), "1.1.1.1", now=later)
        self.assertFalse(L.realms_json(later)["realms"][0]["community"]["new"])

    def test_tunnel_gone_means_offline_at_once(self):
        relay = types.SimpleNamespace(sessions={}, blocked=set(), state={"realms": {}})
        L, h, now = listing.Listing(cfg(), relay), Host(), time.time()
        relay.sessions[h.rid] = types.SimpleNamespace(visibility="public", rtt_ms=None)
        self.assertEqual(L.heartbeat(h.beat(now), "1.1.1.1", now=now)[0], 200)
        self.assertEqual(L.realms_json(now)["realms"][0]["state"], "live")
        del relay.sessions[h.rid]
        self.assertEqual(L.realms_json(now + 5)["realms"][0]["state"], "offline")


class RegionAndDirect(unittest.TestCase):
    def _one(self, rtt, **kw):
        relay = types.SimpleNamespace(sessions={}, blocked=set(), state={"realms": {}})
        L, h, now = listing.Listing(cfg(**kw), relay), Host(), time.time()
        relay.sessions[h.rid] = types.SimpleNamespace(visibility="public", rtt_ms=rtt)
        L.heartbeat(h.beat(now, record={"name": "X", "direct": True}), "1.1.1.1", now=now)
        return L.realms_json(now)["realms"][0]["community"]

    def test_region_estimate_only_when_near(self):
        self.assertEqual(self._one(12.0, region="eu")["regionEstimate"], "eu")
        self.assertEqual(self._one(12.0, region="eu")["latency"], "near")
        far = self._one(180.0, region="eu")
        self.assertEqual((far["regionEstimate"], far["latency"]), (None, "far"))
        self.assertIsNone(self._one(12.0, region="")["regionEstimate"], "the relay does not know where it is")
        self.assertIsNone(self._one(None, region="eu")["latency"])

    def test_direct_connect_is_ready_but_off(self):
        self.assertFalse(self._one(None)["directConnect"], "off unless the relay operator turns it on")
        self.assertTrue(self._one(None, advertise_direct=True)["directConnect"])


class EndToEnd(unittest.IsolatedAsyncioTestCase):
    async def test_rtt_probe_with_a_real_agent(self):
        async with Rig() as r:
            s = r.relay.sessions[r.rid]
            ms = await s.probe_rtt()
            self.assertIsNotNone(ms, "every agent answers the unknown 'rtt' op at once")
            self.assertLess(ms, 2000)
            r.agent.cfg["record"] = {"name": "Test Realm", "tags": ["pvp", "bots"], "region": "eu", "language": "en"}
            st, body, _ = await http("POST", f"{r.http}/api/listing/heartbeat", r.agent.beat(await r.agent.status()))
            self.assertEqual(st, 200, body)
            st, doc, _ = await http("GET", f"{r.http}/api/listing/realms.json")
            rec = doc["realms"][0]
            self.assertEqual((rec["tags"], rec["region"], rec["language"]), (["pvp", "bots"], "eu", "en"))
            self.assertEqual(rec["community"]["latency"], "near")
            self.assertIn("network", doc)


class Setup(unittest.TestCase):
    """setup.py: the host sets the fields (init flags, `listing`, beacon.json); bots and the kit's core follow."""

    def setUp(self):
        self.kit = tempfile.mkdtemp()
        os.environ["WU_KIT"] = self.kit
        import importlib
        from wuhost import setup as setupmod
        self.s = importlib.reload(setupmod)

    def tearDown(self):
        os.environ.pop("WU_KIT", None)

    def cfg(self):
        return rd(os.path.join(self.kit, "state", "host.json"))

    def test_init_and_listing_command(self):
        self.s.main(["init", "--name", "Frost Haven", "--profile", "dalaran", "--visibility", "public", "--gm-name", "HOSTER",
                     "--region", "eu", "--language", "de", "--tags", "pvp,hangout"])
        rec = self.cfg()["record"]
        self.assertEqual((rec["tags"], rec["region"], rec["language"], rec["max_players"], rec["direct"],
                          rec["core"], rec["build"]), (["pvp", "hangout"], "eu", "de", 40, False, "azerothcore", 12340))
        self.s.main(["listing", "--tags", "rp", "--max-players", "0", "--direct", "on", "--region", "none"])
        rec = self.cfg()["record"]
        self.assertEqual((rec["tags"], rec["max_players"], rec["direct"], rec["region"]), (["rp"], None, True, None))
        beacon = rd(os.path.join(self.kit, "state", "beacon.json"))
        self.assertEqual((beacon["tags"], beacon["direct"]), (["rp"], True), "beacon.json stays in step")
        with self.assertRaises(SystemExit):
            self.s.main(["listing", "--tags", "pay2win"])
        with self.assertRaises(SystemExit):
            self.s.main(["listing", "--language", "klingon!"])

    def test_profile_tags_and_bots(self):
        self.s.main(["init", "--name", "Main Town", "--profile", "main", "--visibility", "public", "--gm-name", "HOSTER"])
        self.assertEqual(self.cfg()["record"]["tags"], ["boosted", "bots"], "main runs bots by default")
        self.s.main(["init", "--bots", "0"])
        self.assertEqual(self.cfg()["record"]["tags"], ["boosted"])
        # the host edits beacon.json by hand: checked on the next run
        p = os.path.join(self.kit, "state", "beacon.json")
        b = rd(p)
        b.update(tags=["custom", "nonsense"], language="xx-YY-ZZ", region="eu")
        wr(p, b)
        self.s.main(["rules"])
        rec = self.cfg()["record"]
        self.assertEqual((rec["tags"], rec["language"], rec["region"]), (["custom"], None, "eu"))



class ScoreCap(unittest.TestCase):
    def test_score_never_counts_players_the_relay_does_not_see(self):
        now = time.time()
        h = Host()
        st = lambda ip: types.SimpleNamespace(ip=ip)   # noqa: E731
        sess = types.SimpleNamespace(visibility="public", streams={1: st("a"), 2: st("a"), 3: st("b")}, listed_at=1,
                                     rtt_ms=None, signup=None)
        relay = types.SimpleNamespace(blocked=set(), sessions={h.rid: sess}, state={"realms": {}}, mesh=None)
        L = listing.Listing(cfg(), relay)
        self.assertEqual(L.heartbeat(h.beat(now, players=500), "198.51.100.20", now=now)[0], 200)
        r = L.realms_json(now)["realms"][0]
        self.assertEqual(r["community"]["playersConfirmed"], 2)
        self.assertEqual(r["community"]["lastHeartbeat"]["players"], 500, "the count shown is the realm's own")
        self.assertEqual(r["community"]["score"], listing.score(True, 2, 0, None, None, True))


class WordFilter(unittest.TestCase):
    """The listing's word filter: brand words out of the host's text, slurs refused; the same lists as the website's
    host form (stream/hostflow.py), which ships apart from the relay."""

    def test_same_lists_as_the_website(self):
        import ast
        import re
        src = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "stream", "hostflow.py")
        tree = ast.parse(open(src, encoding="utf-8").read())
        got = {}
        for node in tree.body:
            if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
                n = node.targets[0].id
                if n == "SLURS":
                    got[n] = ast.literal_eval(node.value)
                elif n == "BANNED":
                    got[n] = ast.literal_eval(node.value.args[0])
                elif n == "_LEET":
                    got[n] = tuple(ast.literal_eval(a) for a in node.value.args)
        self.assertEqual(got.get("SLURS"), listing.SLURS)
        self.assertEqual(got.get("BANNED"), listing.BANNED.pattern)
        self.assertEqual(str.maketrans(*got["_LEET"]), listing._LEET)
        self.assertTrue(re.compile(got["BANNED"]).search("World of Warcraft"))

    def test_brand_words_taken_out(self):
        rec = listing.clean_record({"name": "WoW Frost Haven", "tagline": "Best Warcraft fun",
                                    "summary": "Wrath of the Lich King, blizzlike", "rules": ["No Blizzard talk", "Be kind"]})
        self.assertEqual(rec["name"], "Frost Haven")
        self.assertFalse(rec["name_ok"])
        self.assertEqual(rec["tagline"], "Best fun")
        self.assertEqual(rec["summary"], "Wrath, blizzlike")
        self.assertEqual(rec["rules"], ["No talk", "Be kind"])
        ok = listing.clean_record({"name": "Frost Haven"})
        self.assertTrue(ok["name_ok"])
        for fine in ("Raccoon Den", "Spicy Duels", "Scunthorpe", "Wowza", "Flowow"):
            self.assertTrue(listing.clean_record({"name": fine})["name_ok"], fine)

    def test_slurs_refused(self):
        L = listing.Listing(cfg())
        now = time.time()
        for bad in ("Fag Den", "n1gger town", "R E T A R D S", "f.a.g.g.o.t"):
            st, body = L.heartbeat(Host().beat(now, record={"name": bad}), "198.51.100.9", now=now)
            self.assertEqual(st, 400, bad)
            self.assertIn("not allowed", body["error"])
        h = Host()
        st, _ = L.heartbeat(h.beat(now, record={"name": "Fine Realm", "tagline": "kike", "rules": ["no tranny jokes", "ok"]}),
                            "198.51.100.10", now=now)
        self.assertEqual(st, 200)
        r = L.realms_json(now)["realms"][0]
        self.assertEqual((r["tagline"], r["rules"], r["community"]["nameOk"]), ("", ["ok"], True))
        h2 = Host()
        L.heartbeat(h2.beat(now, record={"name": "Blizzard Haven"}), "198.51.100.11", now=now)
        r2 = next(r for r in L.realms_json(now)["realms"] if r["community"]["realmId"] == h2.rid)
        self.assertEqual((r2["name"], r2["community"]["nameOk"]), ("Haven", False))


if __name__ == "__main__":
    unittest.main()
