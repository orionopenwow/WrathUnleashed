"""SRP6, the 3.3.5a header cipher, keys: pinned to published vectors and to the owner's own
account maker (realm/make_account.py), then a full client/server handshake."""
import asyncio
import hashlib
import hmac
import os
import unittest

import helpers  # noqa: F401  (sys.path)
from wunet import keys, srp6, wire335


def rev(b):
    return bytes(reversed(b))


class SRP(unittest.TestCase):
    def test_x_known_answer(self):
        # wow_srp corpus (MIT), the vectors benilla-srp pins: salt and x big-endian there.
        salt = rev(bytes.fromhex("CAC94AF32D817BA64B13F18FDEDEF92AD4ED7EF7AB0E19E9F2AE13C828AEAF57"))
        for user, pw, x in (("00XD0QOSA9L8KMXC", "43R4Z35TKBKFW8JI", "E2F9A0F1E824006C98DA753448E743F7DAA1EAA1"),
                            ("01GJDP3DSFHR56JQ", "9ZK1PFJ9LA0JSHPR", "553A6123ABCFD539F2E0B77F64860C64675BC0FD")):
            self.assertEqual(srp6.calc_x(user, pw, salt), int(x, 16))

    def test_interleave_known_answer(self):
        for s, k in (("8F4CEBD60DFC34E5C007E51BD4F3A4FF2BC1D930E2D3EA770D8D3EEDFF2DCCFC",
                      "EE144E1AE08DAC891AB63ABC42BF89738003343422E6B58131BEE4C3087A7027E55A7216D18D556C"),
                     ("CCC1BDE07FC4FA3182DDEAAB036A88F78AD605AB0D8BFBF6F5EE8ED65CDE4F09",
                      "2AA23706C3FC3517A4293E2D4944F567E220CC1A227359D70154E5FD3CEE973673130C4AFBAD9E6D")):
            self.assertEqual(srp6.interleave(bytes.fromhex(s)), bytes.fromhex(k))

    def test_verifier_golden(self):
        # benilla-srp password_verifier_golden: salt[i] = i*11+2
        salt = bytes((i * 11 + 2) & 0xFF for i in range(32))
        _, v = srp6.make_verifier("alice", "password1", salt)
        self.assertEqual(v.hex(), "28b837075a12b82553921d9095fa3fdcb0151c4bfc860ab97a69d0fa86a3d213")

    def test_matches_owner_account_maker(self):
        # realm/make_account.py, verbatim math (what the owner's working realm accepts)
        N = int("894B645E89E1535BBDAD5B8B290650530801B18EBFBF5E8FAB3C82872A3E9BB7", 16)
        user, pw, salt = "FRIEND1", "HUNTER2", os.urandom(32)
        h1 = hashlib.sha1(f"{user}:{pw}".encode()).digest()
        x = int.from_bytes(hashlib.sha1(salt + h1).digest(), "little")
        v = pow(7, x, N).to_bytes(32, "little")
        self.assertEqual(srp6.make_verifier("friend1", "hunter2", salt)[1], v)

    def test_handshake_and_wrong_password(self):
        salt, ver = srp6.make_verifier("bob", "secret")
        for _ in range(30):
            srv = srp6.Server("bob", salt, ver)
            c = srp6.Client("bob", "secret")
            A, M1 = c.process(srv.B, salt)
            K, M2 = srv.verify(A, M1)
            self.assertEqual(K, c.K)
            self.assertTrue(c.check_server(M2))
        srv = srp6.Server("bob", salt, ver)
        A, M1 = srp6.Client("bob", "wrong").process(srv.B, salt)
        self.assertIsNone(srv.verify(A, M1))


class Cipher(unittest.TestCase):
    def test_rc4_rfc6229(self):
        self.assertEqual(wire335.Arc4(bytes([1, 2, 3, 4, 5]), drop=0).apply(bytes(16)).hex(),
                         "b2396305f03dc027ccc3524a0a1118a8")
        self.assertEqual(wire335.Arc4(bytes([1, 2, 3, 4, 5]), drop=1024).apply(bytes(16)).hex(),
                         "30abbcc7c20b01609f23ee2d5f6bb7df")

    def test_hmac_rfc2202(self):
        self.assertEqual(hmac.new(b"Jefe", b"what do ya want for nothing?", hashlib.sha1).hexdigest(),
                         "effcdf6ae5eb2fa2d27416d5f184df9c259a7c79")

    def test_ends_agree(self):
        K = bytes([0x5A]) * 40
        s_enc, s_dec = wire335.header_crypt(K, server=True)
        c_enc, c_dec = wire335.header_crypt(K, server=False)
        for h in (bytes([0, 5, 0xEE, 1]), bytes([0x12, 0x34, 0x56, 0x78])):
            wire = s_enc.apply(h)
            self.assertNotEqual(wire, h)
            self.assertEqual(c_dec.apply(wire), h)
        self.assertEqual(s_dec.apply(c_enc.apply(b"\x00\x08\xdc\x01\x00\x00")), b"\x00\x08\xdc\x01\x00\x00")


class Keys(unittest.TestCase):
    def test_sign_verify_both_backends(self):
        sec = keys.new_secret()
        pub = keys.public_key(sec)
        doc = {"b": 2, "a": [1, "x"]}
        sig = keys.sign_doc(sec, doc, keys.CTX_HEARTBEAT)
        self.assertTrue(keys.verify_doc(pub, doc, keys.CTX_HEARTBEAT, sig))
        self.assertFalse(keys.verify_doc(pub, doc, keys.CTX_RELAY_LOGIN, sig))   # context binding
        self.assertFalse(keys.verify_doc(pub, dict(doc, b=3), keys.CTX_HEARTBEAT, sig))
        # the pure-Python fallback interoperates with cryptography
        from wunet import ed25519_pure
        self.assertEqual(ed25519_pure.public_key(sec), pub)
        msg = keys.CTX_HEARTBEAT.encode() + b"\n" + keys.canonical(doc)
        self.assertTrue(ed25519_pure.verify(pub, msg, bytes.fromhex(sig)))
        self.assertTrue(keys.verify(pub, msg, ed25519_pure.sign(sec, msg)))

    def test_realm_id(self):
        rid = keys.realm_id(keys.public_key(keys.new_secret()))
        self.assertRegex(rid, keys.REALM_ID_RE)


class FakeRealmLogin(unittest.IsolatedAsyncioTestCase):
    async def test_direct_full_run(self):
        from fake_realm import FakeRealm
        r = await FakeRealm().start()
        r.world_address = f"127.0.0.1:{r.world_port}"
        r.add_account("tester", "pw1")
        rep = await wire335.full_run("127.0.0.1", r.auth_port, "tester", "pw1")
        self.assertEqual(rep["steps"], ["logon", "realm_list", "world_auth", "char_enum", "char_create",
                                        "enter_world", "ping", "logout"])
        self.assertIn(("time_sync", "TESTER"), r.events)
        with self.assertRaises(wire335.WowError):
            await wire335.logon("127.0.0.1", r.auth_port, "tester", "bad")
        self.assertEqual(await wire335.logon_probe("127.0.0.1", r.auth_port), 0x04)
        await r.stop()


if __name__ == "__main__":
    unittest.main()
