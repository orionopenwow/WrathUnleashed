"""The game-port check from outside the box (relay/deploy/portcheck.py): live realms' ports from the relay's own API,
refused = the packets arrive (open firewall), all timeouts = blocked (the Hetzner console clicks), and the relay and
check steps run it read-only.

    python3 tests/test_portcheck.py          (from hosting/)
"""
import io
import os
import socket
import sys
import unittest
from contextlib import redirect_stdout

HOSTING = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(HOSTING, "relay", "deploy"))
import portcheck  # noqa: E402

LISTING = {"realms": [
    {"state": "live", "community": {"realmId": "aaaaaaaaaaaaaaaa"}},
    {"state": "offline", "community": {"realmId": "bbbbbbbbbbbbbbbb"}},
]}
INFO = {"aaaaaaaaaaaaaaaa": {"online": True, "name": "Wrath Unleashed", "auth_port": 40010, "world_port": 40011}}


def fetch(url):
    if url.endswith("/api/listing/realms.json"):
        return LISTING
    return INFO.get(url.rsplit("/", 1)[1])


class PortCheck(unittest.TestCase):
    def run_main(self, probe):
        seen = []

        def p(host, port, timeout):
            seen.append(port)
            return probe(port)
        out = io.StringIO()
        with redirect_stdout(out):
            rc = portcheck.main(["--host", "localhost", "--relay", "relay.test"], probe_fn=p, fetch=fetch)
        return rc, out.getvalue(), seen

    def test_reachable(self):
        rc, out, seen = self.run_main(lambda port: "open" if port in (40010, 40011) else "refused")
        self.assertEqual(rc, 0)
        self.assertEqual(seen, [40010, 40011, 40000, 40999])          # the live realm's pair, then the range ends
        self.assertIn("game ports 40000-40999: reachable", out)
        self.assertIn("Wrath Unleashed auth", out)

    def test_refused_alone_means_open(self):
        rc, out, _ = self.run_main(lambda port: "refused")
        self.assertEqual(rc, 0)
        self.assertIn("reachable", out)

    def test_blocked(self):
        rc, out, _ = self.run_main(lambda port: "timeout")
        self.assertEqual(rc, 4)
        self.assertIn("BLOCKED", out)
        self.assertIn("ACTION NEEDED", out)
        self.assertIn("console.hetzner.cloud", out)
        self.assertIn("Port 40000-40999", out)

    def test_unknown(self):
        rc, out, _ = self.run_main(lambda port: "error: network is unreachable")
        self.assertEqual(rc, 0)
        self.assertIn("could not tell", out)

    def test_real_probe(self):
        s = socket.socket()
        s.bind(("127.0.0.1", 0))
        s.listen(1)
        port = s.getsockname()[1]
        try:
            self.assertEqual(portcheck.probe("127.0.0.1", port, 2), "open")
        finally:
            s.close()
        self.assertEqual(portcheck.probe("127.0.0.1", port, 2), "refused")

    def test_steps_run_it(self):
        bat = open(os.path.join(HOSTING, "relay", "Deploy relay.bat")).read()
        self.assertIn(r"relay\deploy\portcheck.py", bat)
        check = os.path.join(os.path.dirname(HOSTING), "realm", "Server check.bat")
        if os.path.exists(check):
            self.assertIn(r"hosting\relay\deploy\portcheck.py", open(check).read())
        doc = open(os.path.join(HOSTING, "INSTALL-OPERATE.md")).read()
        self.assertIn("console.hetzner.cloud", doc)


if __name__ == "__main__":
    unittest.main()
