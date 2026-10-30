"""Hero Key sign-in for Beacons (docs/HERO-KEY-SSO.md): the website's assertion (stream/herokey_sso.py) checked by
the realm side (wunet/herokey.py), then end to end: relay + agent + fake realm + the headless 3.3.5a client logging
in with the one-time password over SRP, through the relay's browser bridge. Plus: off by default, replay, wrong
audience, expiry, a relay that tampers, per-realm pseudonyms."""
import asyncio
import importlib.util
import json
import os
import time
import unittest

from helpers import ROOT, Rig, http, ws_opener
from wunet import herokey, keys, srp6, wire335

_spec = importlib.util.spec_from_file_location("hk_issuer", os.path.join(ROOT, "..", "stream", "herokey_sso.py"))
issuer = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(issuer)

SITE = bytes(range(32))           # a test key, made here; never a real one
PEPPER = bytes(range(32, 64))
PUB = issuer.public_key(SITE)
PINNED = {herokey.key_id(PUB): PUB}
RID = "abcdefghijk2345a"
OTHER = "qrstuvwxyz234567"
NOW = 1_800_000_000


def mint(acct="WR000123", rid=RID, now=NOW, ttl=120, secret=SITE):
    return issuer.issue(secret, PEPPER, acct, rid, "play.test", login_ttl=ttl, now=now)


class Assertion(unittest.TestCase):
    def test_sign_and_verify(self):
        t = mint()
        claims, why = herokey.check(t["assertion"], t["sig"], RID, PINNED, herokey.ReplayCache(), now=NOW + 5)
        self.assertIsNone(why)
        self.assertEqual(herokey.account_name(claims["sub"]), t["login"]["user"])
        self.assertRegex(t["login"]["user"], herokey.ACCOUNT_RE)
        self.assertEqual(len(t["login"]["pass"]), 16)
        # the verifier is the one-time password's, as AzerothCore computes it
        salt, ver = srp6.make_verifier(t["login"]["user"], t["login"]["pass"], bytes.fromhex(claims["salt"]))
        self.assertEqual(ver.hex(), claims["verifier"])
        # the password is nowhere in what the relay and the realm see
        self.assertNotIn(t["login"]["pass"], json.dumps(t["assertion"]) + t["sig"])

    def test_off_without_a_pinned_key(self):
        t = mint()
        self.assertEqual(herokey.check(t["assertion"], t["sig"], RID, {}, herokey.ReplayCache(), now=NOW)[1], "off")
        self.assertEqual(herokey.SITE_KEYS, ())   # the kit ships with none: off until the owner pins one
        self.assertEqual(herokey.pinned_keys({}), {})
        self.assertEqual(herokey.pinned_keys({herokey.ENV_KEYS: "zz," + PUB.hex()}), PINNED)

    def test_expiry_and_clock(self):
        t = mint()
        seen = herokey.ReplayCache()
        self.assertEqual(herokey.check(t["assertion"], t["sig"], RID, PINNED, seen, now=NOW + 120 + 61)[1], "expired")
        self.assertEqual(herokey.check(t["assertion"], t["sig"], RID, PINNED, seen, now=NOW - 61)[1], "early")
        self.assertIsNone(herokey.check(t["assertion"], t["sig"], RID, PINNED, seen, now=NOW + 150)[1])  # within skew

    def test_wrong_audience(self):
        t = mint(rid=OTHER)
        self.assertEqual(herokey.check(t["assertion"], t["sig"], RID, PINNED, herokey.ReplayCache(), now=NOW)[1], "aud")

    def test_replay(self):
        t = mint()
        seen = herokey.ReplayCache()
        self.assertIsNone(herokey.check(t["assertion"], t["sig"], RID, PINNED, seen, now=NOW)[1])
        self.assertEqual(herokey.check(t["assertion"], t["sig"], RID, PINNED, seen, now=NOW + 1)[1], "replay")
        # a bad signature never spends a nonce
        t2 = mint()
        bad = dict(t2["assertion"], sub="a" * 26)
        self.assertEqual(herokey.check(bad, t2["sig"], RID, PINNED, seen, now=NOW)[1], "sig")
        self.assertIsNone(herokey.check(t2["assertion"], t2["sig"], RID, PINNED, seen, now=NOW)[1])
        # expired nonces are swept, the cache never forgets a live one
        seen.sweep(NOW + 10_000)
        self.assertEqual(seen.seen, {})

    def test_tampering_relay_and_other_keys(self):
        t = mint()
        a = t["assertion"]
        for k, v in (("verifier", "11" * 32), ("sub", "b" * 26), ("login_ttl", 900), ("aud", OTHER), ("exp", NOW + 300)):
            self.assertEqual(herokey.check(dict(a, **{k: v}), t["sig"], a["aud"] if k != "aud" else OTHER, PINNED,
                                           herokey.ReplayCache(), now=NOW)[1], "sig", k)
        self.assertEqual(herokey.check(dict(a, extra=1), t["sig"], RID, PINNED, herokey.ReplayCache(), now=NOW)[1], "shape")
        # signed by a key that isn't pinned (a malicious realm or relay with its own key)
        rogue = mint(secret=bytes(32))
        self.assertEqual(herokey.check(rogue["assertion"], rogue["sig"], RID, PINNED, herokey.ReplayCache(), now=NOW)[1], "kid")
        forged = dict(rogue["assertion"], kid=herokey.key_id(PUB))
        self.assertEqual(herokey.check(forged, rogue["sig"], RID, PINNED, herokey.ReplayCache(), now=NOW)[1], "sig")
        # a heartbeat or relay-login signature is never an assertion (domain separation)
        sig = keys.sign_doc(SITE, a, keys.CTX_HEARTBEAT)
        self.assertEqual(herokey.check(a, sig, RID, PINNED, herokey.ReplayCache(), now=NOW)[1], "sig")
        # a lifetime longer than allowed, even when signed
        long = dict(a, exp=a["iat"] + 3600)
        self.assertEqual(herokey.check(long, issuer.sign_doc(SITE, long), RID, PINNED, herokey.ReplayCache(), now=NOW)[1],
                         "lifetime")

    def test_per_realm_ids_are_unlinkable(self):
        a1, a2 = mint(rid=RID), mint(rid=OTHER)
        b1 = mint(acct="WR000999", rid=RID)
        s = lambda t: t["assertion"]["sub"]   # noqa: E731
        self.assertEqual(s(a1), s(mint(rid=RID)))                    # stable on one realm
        self.assertNotEqual(s(a1), s(a2))                            # different on another
        self.assertNotEqual(a1["login"]["user"], a2["login"]["user"])
        self.assertNotEqual(s(a1), s(b1))
        for t in (a1, a2):
            self.assertNotIn("WR000123", json.dumps(t["assertion"]).upper())   # never the global account
        # without the pepper the two can't be tied together: another pepper gives unrelated ids
        other = issuer.pseudonym(bytes(32), RID, "WR000123")
        self.assertNotEqual(other, s(a1))
        # nothing else in the assertion repeats across realms (fresh salt, nonce, verifier)
        for k in ("salt", "verifier", "nonce"):
            self.assertNotEqual(a1["assertion"][k], a2["assertion"][k])
        # one-time passwords are fresh each time
        self.assertNotEqual(a1["login"]["pass"], mint(rid=RID)["login"]["pass"])

    def test_issuer_matches_kit(self):
        self.assertEqual(issuer.CTX, herokey.CTX)
        self.assertEqual(issuer.account_name("abcdefghijklmnopqrstuvwxyz"), herokey.account_name("abcdefghijklmnopqrstuvwxyz"))
        salt = issuer.new_salt()
        self.assertEqual(issuer.make_verifier("HKABC", "PW", salt), srp6.make_verifier("HKABC", "PW", salt)[1])
        with self.assertRaises(ValueError):
            mint(rid="../x")

    def test_site_key_files(self):
        import tempfile
        d = tempfile.mkdtemp()
        k = issuer.Keys(d)
        doc = k.public_doc()
        self.assertEqual(len(doc["keys"]), 1)
        self.assertEqual(oct(os.stat(os.path.join(d, "herokey-site.key")).st_mode & 0o777), "0o600")
        self.assertEqual(issuer.Keys(d).secret(), k.secret())   # the same key after a restart
        self.assertNotIn(k.secret().hex(), json.dumps(doc))      # only the public half is shown
        with open(os.path.join(d, "herokey-site.next.key"), "w") as f:
            f.write(bytes(range(1, 33)).hex())
        self.assertEqual([x["use"] for x in issuer.Keys(d).public_doc()["keys"]], ["current", "next"])


class EndToEnd(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.old = os.environ.get(herokey.ENV_KEYS)
        os.environ[herokey.ENV_KEYS] = PUB.hex()

    def tearDown(self):
        if self.old is None:
            os.environ.pop(herokey.ENV_KEYS, None)
        else:
            os.environ[herokey.ENV_KEYS] = self.old

    async def sign_in(self, r, t, origin="https://wrath.openvanilla.app"):
        return await http("POST", f"{r.http}/api/realms/{r.rid}/herokey", {"assertion": t["assertion"], "sig": t["sig"]},
                          {"Origin": origin})

    async def test_hop_signs_in_and_plays_through_the_bridge(self):
        async with Rig(host_extra={"herokey": True}) as r:
            s = r.relay.sessions[r.rid]
            self.assertTrue(s.herokey)
            st, info, _ = await http("GET", f"{r.http}/api/realms/{r.rid}")
            self.assertTrue(info.get("herokey"))
            t = issuer.issue(SITE, PEPPER, "WR000123", r.rid, "play.test")
            st, body, hd = await self.sign_in(r, t)
            self.assertEqual(st, 200, body)
            self.assertEqual(body["username"], t["login"]["user"])
            self.assertEqual(hd.get("access-control-allow-origin"), "https://wrath.openvanilla.app")
            # the account exists on the realm, made from the assertion; the agent remembers only the pseudonym
            self.assertIn(t["login"]["user"], r.realm.accounts)
            with open(os.path.join(r.host_dir, "herokey-accounts.json")) as f:
                m = json.load(f)
            self.assertEqual(m[t["assertion"]["sub"]]["account"], t["login"]["user"])
            self.assertNotIn("WR000123", json.dumps(m))
            # the stock protocol: SRP with the one-time password, through the browser bridge
            rep = await wire335.full_run("relay.test", 3724, t["login"]["user"], t["login"]["pass"],
                                         opener=ws_opener(r.base, r.rid))
            self.assertIn("enter_world", rep["steps"])
            # replay of the same assertion (a relay or anyone who saw it): refused
            st, body, _ = await self.sign_in(r, t)
            self.assertEqual((st, body["code"]), (409, "replay"))
            # the next hop: the same account, a new one-time password; the old one stops working
            t2 = issuer.issue(SITE, PEPPER, "WR000123", r.rid, "play.test")
            st, body, _ = await self.sign_in(r, t2)
            self.assertEqual((st, body["username"]), (200, t["login"]["user"]))
            with self.assertRaises((wire335.WowError, asyncio.IncompleteReadError, ConnectionError)):
                await wire335.logon("relay.test", 3724, t["login"]["user"], t["login"]["pass"], timeout=5,
                                    opener=ws_opener(r.base, r.rid))
            rep = await wire335.full_run("relay.test", 3724, t2["login"]["user"], t2["login"]["pass"],
                                         opener=ws_opener(r.base, r.rid))
            self.assertIn("enter_world", rep["steps"])
            # expiry: once login_ttl is over the one-time password is useless
            await r.agent.herokey_expire(t2["login"]["user"], r.agent.hk_gen[t2["login"]["user"]], 0)
            with self.assertRaises((wire335.WowError, asyncio.IncompleteReadError, ConnectionError)):
                await wire335.logon("relay.test", 3724, t2["login"]["user"], t2["login"]["pass"], timeout=5,
                                    opener=ws_opener(r.base, r.rid))

    async def test_refusals(self):
        async with Rig(host_extra={"herokey": True, "herokey_banned": []}) as r:
            # an assertion for another realm never reaches the agent
            t = issuer.issue(SITE, PEPPER, "WR000123", OTHER, "play.test")
            st, body, _ = await self.sign_in(r, t)
            self.assertEqual((st, body["code"]), (400, "shape"))
            # expired
            old = issuer.issue(SITE, PEPPER, "WR000123", r.rid, "play.test", now=int(time.time()) - 1000)
            st, body, _ = await self.sign_in(r, old)
            self.assertEqual((st, body["code"]), (410, "expired"))
            # a relay that swaps in its own verifier: the signature fails at the agent
            t = issuer.issue(SITE, PEPPER, "WR000123", r.rid, "play.test")
            evil = dict(t, assertion=dict(t["assertion"], verifier=srp6.make_verifier("X", "Y")[1].hex()))
            st, body, _ = await self.sign_in(r, evil)
            self.assertEqual((st, body["code"]), (400, "sig"))
            # an account of that name the agent did not make for a Hero Key is never taken over
            t = issuer.issue(SITE, PEPPER, "WR000777", r.rid, "play.test")
            r.realm.add_account(t["login"]["user"], "theirs")
            st, body, _ = await self.sign_in(r, t)
            self.assertEqual((st, body["code"]), (409, "taken"))
            # a pseudonym the host banned
            t = issuer.issue(SITE, PEPPER, "WR000888", r.rid, "play.test")
            r.agent.cfg["herokey_banned"] = [t["assertion"]["sub"]]
            st, body, _ = await self.sign_in(r, t)
            self.assertEqual((st, body["code"]), (403, "banned"))

    async def test_off_by_default(self):
        async with Rig() as r:   # no "herokey" in host.json: the old behaviour
            self.assertFalse(r.relay.sessions[r.rid].herokey)
            st, info, _ = await http("GET", f"{r.http}/api/realms/{r.rid}")
            self.assertNotIn("herokey", info)
            t = issuer.issue(SITE, PEPPER, "WR000123", r.rid, "play.test")
            st, body, _ = await self.sign_in(r, t)
            self.assertEqual((st, body["code"]), (403, "off"))
            self.assertEqual(await r.agent.herokey_login({"assertion": t["assertion"], "sig": t["sig"]}),
                             {"ok": False, "error": "off"})
            self.assertFalse([u for u in r.realm.accounts if u.startswith("HK")])

    async def test_on_in_host_json_but_no_pinned_key(self):
        os.environ.pop(herokey.ENV_KEYS, None)
        async with Rig(host_extra={"herokey": True}) as r:
            self.assertFalse(r.relay.sessions[r.rid].herokey)
            t = issuer.issue(SITE, PEPPER, "WR000123", r.rid, "play.test")
            st, body, _ = await self.sign_in(r, t)
            self.assertEqual((st, body["code"]), (403, "off"))

    async def test_rate_limit(self):
        async with Rig(host_extra={"herokey": True}, herokey_per_ip_min=2) as r:
            for _ in range(2):
                await self.sign_in(r, issuer.issue(SITE, PEPPER, "WR000123", r.rid, "play.test"))
            st, body, _ = await self.sign_in(r, issuer.issue(SITE, PEPPER, "WR000123", r.rid, "play.test"))
            self.assertEqual((st, body["code"]), (429, "rate"))


if __name__ == "__main__":
    unittest.main()
