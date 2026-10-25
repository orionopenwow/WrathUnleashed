"""Runs the docker e2e's player script (tests/e2e/e2e_client.py) against an in-process rig, so the
script itself is tested here even without Docker: private phase, switch to public, public phase."""
import asyncio
import json
import os
import sys
import unittest

from helpers import Rig, HERE


class E2EClientScript(unittest.IsolatedAsyncioTestCase):
    async def client(self, r, *args):
        p = await asyncio.create_subprocess_exec(
            sys.executable, os.path.join(HERE, "e2e", "e2e_client.py"), *args, "--state", r.host_dir,
            "--relay-host", "127.0.0.1", "--relay-http", r.http, "--shared-port", str(r.shared),
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT)
        out, _ = await asyncio.wait_for(p.communicate(), 120)
        return p.returncode, out.decode()

    async def test_private_then_public(self):
        async with Rig(name="127.0.0.1", visibility="private", max_streams_per_ip=64, max_streams_per_ip_total=64,
                       conn_rate_per_ip=1000) as r:
            acc = os.path.join(r.tmp, "account.txt")
            code, out = await self.client(r, "private", "--save-account", acc)
            self.assertEqual(code, 0, out)
            self.assertIn('"ok": true', out)
            cfg = json.load(open(os.path.join(r.host_dir, "host.json")))
            cfg["visibility"] = "public"
            json.dump(cfg, open(os.path.join(r.host_dir, "host.json"), "w"))
            r.agent.cfg_mtime = 0
            r.agent.heartbeat_every = 1
            hb = asyncio.ensure_future(r.agent.heartbeat_loop(1))
            code, out = await self.client(r, "public", "--account", open(acc).read())
            hb.cancel()
            self.assertEqual(code, 0, out)


if __name__ == "__main__":
    unittest.main()
