#!/usr/bin/env python3
"""Leyline Control's HQ and safety additions: secrets scrubbed from every step line, the token checked in constant
time (header, cookie or link), "Ask before deploys", the last server check, and the Open HQ button.

    python3 -I tools/control/test_control_hq.py
"""
import http.client, importlib.util, json, os, sys, tempfile, threading, unittest
from http.server import ThreadingHTTPServer
from pathlib import Path

HERE = os.path.dirname(os.path.abspath(__file__))
PORT = 18098
os.environ.update(WU_CONTROL_PORT=str(PORT), LOCALAPPDATA=tempfile.mkdtemp())
spec = importlib.util.spec_from_file_location("control", os.path.join(HERE, "control.py"))
ctl = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ctl)
T = Path(tempfile.mkdtemp())
ctl.AUTO = T / "autopilot.json"
ctl.LAST_CHECK = T / "last-check.json"
srv = ThreadingHTTPServer(("127.0.0.1", PORT), ctl.H)
srv.daemon_threads = True
threading.Thread(target=srv.serve_forever, daemon=True).start()


def req(method, path, headers=None, body=None):
    c = http.client.HTTPConnection("127.0.0.1", PORT, timeout=20)
    h = {"Host": f"127.0.0.1:{PORT}"}
    h.update(headers or {})
    c.request(method, path, body=body, headers=h)
    r = c.getresponse()
    return r.status, {k.lower(): v for k, v in r.getheaders()}, r.read()


class Scrub(unittest.TestCase):
    def test_secrets_hidden(self):
        cases = {
            "SOAP_PASS=hunter2": "hunter2",
            "  MYSQL_ROOT_PASSWORD: 'abc def'": "abc def",
            "export GH_TOKEN=ghp_abcdefghijklmnopqrstuvwxyz0123": "ghp_abcdefghijklmnopqrstuvwxyz0123",
            "token github_pat_11ABCDEFG0123456789_abcdefghijklmnop": "github_pat_11ABCDEFG0123456789",
            "WU_ADMIN_SECRET=deadbeefcafe": "deadbeefcafe",
            "curl -H 'Authorization: Bearer abcdefghijklmnop123456'": "abcdefghijklmnop123456",
            "db mysql://root:s3cr3tpw@127.0.0.1:3306/acore": "s3cr3tpw",
            'LoginDatabaseInfo = "127.0.0.1;3306;acore;topsecretpw;acore_auth"': "topsecretpw",
            "AC_LOGIN_DATABASE_PASSWORD=pw123": "pw123",
            "-----BEGIN OPENSSH PRIVATE KEY----- b3BlbnNzaC1rZXk": "b3BlbnNzaC1rZXk",
        }
        for line, secret in cases.items():
            out = ctl.scrub(line)
            self.assertNotIn(secret, out, line)
            self.assertIn("[hidden", out, line)

    def test_plain_lines_untouched(self):
        for line in ("===== Play page and sign-in (1090a) =====", "FASTLOOP OK", "Uploading... 100%", "passed: 12/12"):
            self.assertEqual(ctl.scrub(line), line)


class Token(unittest.TestCase):
    def test_header_cookie_link(self):
        self.assertEqual(req("GET", "/api/state")[0], 403)
        self.assertEqual(req("GET", "/api/state", {"X-Token": "x" * 30})[0], 403)
        self.assertEqual(req("GET", "/api/state", {"X-Token": ctl.TOKEN})[0], 200)
        self.assertEqual(req("GET", "/api/state", {"Cookie": f"lc_token={ctl.TOKEN}"})[0], 200)
        self.assertEqual(req("GET", f"/api/state?t={ctl.TOKEN}")[0], 200)
        self.assertEqual(req("GET", f"/api/state?t={ctl.TOKEN}x")[0], 403)   # no prefix match any more
        st, hd, body = req("GET", f"/?t={ctl.TOKEN}")
        self.assertEqual(st, 200)
        self.assertIn("lc_token=", hd.get("set-cookie", ""))
        self.assertIn("HttpOnly", hd["set-cookie"])
        self.assertIn("SameSite=Strict", hd["set-cookie"])
        self.assertIn(b'id="hq"', body)
        self.assertIn(b"Open HQ", body)
        self.assertIn(b'id="ask"', body)
        self.assertEqual(req("GET", "/", {"Cookie": f"lc_token={ctl.TOKEN}"})[0], 200)
        self.assertEqual(req("GET", "/api/state", {"X-Token": ctl.TOKEN, "Host": "evil.example"})[0], 403)


class Confirm(unittest.TestCase):
    def test_default_off_and_toggle(self):
        self.assertFalse(ctl.confirm_on())
        ctl.set_autopilot(True)
        st, _, b = req("POST", "/api/confirm", {"X-Token": ctl.TOKEN, "Content-Type": "application/json"}, json.dumps({"on": True}))
        self.assertEqual(st, 200)
        self.assertTrue(ctl.confirm_on())
        self.assertTrue(ctl.autopilot_on())              # the switch keeps Autopilot as it was
        ctl.set_autopilot(False)
        self.assertTrue(ctl.confirm_on())                # and Autopilot keeps the ask setting
        state = json.loads(req("GET", "/api/state", {"X-Token": ctl.TOKEN})[2])
        self.assertIs(state["confirm"], True)
        ctl.set_autopilot(confirm=False)
        self.assertFalse(ctl.confirm_on())

    def test_read_only_steps_are_real_steps(self):
        self.assertTrue(ctl.READ_ONLY <= set(ctl.STEPS))
        for s in ("signin", "relay", "ship", "client", "gamedata-off"):
            self.assertNotIn(s, ctl.READ_ONLY)


class LastCheck(unittest.TestCase):
    def test_written(self):
        ctl.write_last_check("check-auto-1", False)
        d = json.loads(ctl.LAST_CHECK.read_text())
        self.assertEqual((d["id"], d["ok"]), ("check-auto-1", False))
        self.assertTrue(d["at"].endswith("Z"))


if __name__ == "__main__":
    unittest.main()
