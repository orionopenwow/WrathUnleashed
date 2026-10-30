"""The join page's in-browser SRP6 verifier must match AzerothCore's (via wunet.srp6), and the relay
serves the page. Needs node for the JS part (skipped without it)."""
import json
import os
import shutil
import subprocess
import unittest

from helpers import Rig, http, ROOT
from wunet import srp6

PAGE = os.path.join(ROOT, "relay", "wurelay", "www", "join.html")


@unittest.skipUnless(shutil.which("node"), "node not installed")
class JoinPageSRP(unittest.TestCase):
    def test_js_verifier_matches(self):
        src = open(PAGE, encoding="utf-8").read()
        a = src.index("  const N = BigInt(")
        b = src.index("  window.__wuVerifier")
        js = src[a:b] + """
const cases = JSON.parse(process.argv[1]);
(async () => { const out = [];
  for (const [u, p, s] of cases) out.push(hex(await verifier(u, p, Uint8Array.from(Buffer.from(s, 'hex')))));
  console.log(JSON.stringify(out)); })();"""
        cases = [("friend1", "hunter2", os.urandom(32).hex()), ("ALICE", "password1", bytes((i * 11 + 2) & 0xFF for i in range(32)).hex()),
                 ("x1y2z3", "Pässwörd", os.urandom(32).hex())]
        out = subprocess.run(["node", "-e", js, json.dumps(cases)], capture_output=True, text=True, timeout=30)
        self.assertEqual(out.returncode, 0, out.stderr)
        got = json.loads(out.stdout)
        for (u, p, s), v in zip(cases[:2], got[:2]):
            self.assertEqual(v, srp6.make_verifier(u, p, bytes.fromhex(s))[1].hex())
        self.assertEqual(got[1], "28b837075a12b82553921d9095fa3fdcb0151c4bfc860ab97a69d0fa86a3d213")


class JoinPageServed(unittest.IsolatedAsyncioTestCase):
    async def test_relay_serves_join_page(self):
        async with Rig() as r:
            st, body, hdr = await http("GET", f"{r.http}/join/{r.rid}")
            self.assertEqual(st, 200)
            self.assertIn("text/html", hdr["content-type"])
            self.assertIn("no-referrer", hdr["referrer-policy"])
            st, _, _ = await http("GET", f"{r.http}/join/NOTANID")
            self.assertEqual(st, 404)


if __name__ == "__main__":
    unittest.main()
