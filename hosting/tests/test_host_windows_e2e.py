"""The website's "+ Your server" flow end to end, the Windows way, against the REAL relay (no Docker, no network):

  /wrath/host (form) -> the .bat download -> what cmd.exe would run from it (each line checked; the docker run lines
  are run as this machine's python3 with the kit at /kit) -> "Host a Wrath realm.bat"'s own setup line -> the real agent
  (fake AzerothCore realm) -> the relay (pairing by the token's hash, the tunnel, the signed heartbeat, the listing)
  -> the start page: "Waiting for your PC", then Online with the PC's realm id and links, then listed and claimed.

Also: the realm key is made on the PC (the website never holds one), the .bat stays within cmd.exe's limits, and a
copied download can't take over a realm the website already found.

    python3 tests/test_host_windows_e2e.py          (from hosting/)
"""
import asyncio
import base64
import http.client
import importlib.util
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import threading
import unittest
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from helpers import FakeDB, FakeRealm, agentmod, free_port, free_range, keys, relaymod
from helpers import http as ahttp

HERE = os.path.dirname(os.path.abspath(__file__))
HOSTING = os.path.dirname(HERE)
ROOT = os.path.dirname(HOSTING)
PORTAL = os.path.join(ROOT, "stream", "wrath_portal.py")
HOST_BAT = os.path.join(HOSTING, "kit", "Host a Wrath realm.bat")
SITE_SECRET = "site-secret-for-the-test"
ACCOUNTS = {"alice": ("Alice", "WR000001", "AlicePass1234567")}


class Website(BaseHTTPRequestHandler):
    """The Open Vanilla realm service's /api/me and /api/play for a signed-in cookie."""

    def log_message(self, *a):
        pass

    def do_GET(self):
        m = re.search(r"wr_session=(\w+)", self.headers.get("Cookie", ""))
        acct = ACCOUNTS.get(m.group(1)) if m else None
        if not acct:
            self.send_response(401); self.send_header("Content-Length", "0"); self.end_headers(); return
        doc = {"/api/me": {"display_name": acct[0]}, "/api/play": {"user": acct[1], "pass": acct[2]}}[self.path]
        b = json.dumps(doc).encode()
        self.send_response(200); self.send_header("Content-Length", str(len(b))); self.end_headers(); self.wfile.write(b)


def serve(handler):
    srv = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


class Cmd:
    """Just enough of cmd.exe for the website's .bat and the kit's setup line: every line must be one we know."""

    def __init__(self, kit, env):
        self.kit, self.env, self.ran = kit, dict(env), []

    def expand(self, s):
        s = s.replace("%~dp0.", self.kit).replace("%~dp0", self.kit + os.sep)
        return re.sub(r"%([A-Z_]+)%", lambda m: self.env.get(m.group(1), ""), s)

    def setup(self, line):
        """`docker run ... <tools image> python -m wuhost.setup ARGS >nul || (...)` -> python3 -m wuhost.setup ARGS."""
        cmd = self.expand(line.split(" >nul")[0].split(" || ")[0])
        m = re.search(r"-v \"([^\"]+):/kit\" -e WU_KIT=/kit \S+ python -m wuhost\.setup (.*)$", cmd)
        assert m and m.group(1) == self.kit, cmd
        args = shlex.split(m.group(2))
        env = dict(os.environ, PYTHONPATH=os.path.join(self.kit, "tools"), WU_KIT=self.kit)
        p = subprocess.run([sys.executable, "-m", "wuhost.setup"] + args,
                           env=env, cwd=self.kit, capture_output=True, text=True, timeout=60)
        self.ran.append((args, p.returncode, p.stdout, p.stderr))
        return p

    def run_bat(self, text):
        for raw in text.split("\r\n"):
            line = raw.strip()
            if not line or line.startswith(("rem ", "title ")) or line in ("@echo off", "setlocal", 'cd /d "%~dp0"'):
                continue
            m = re.fullmatch(r'(?:if not defined (\w+) )?set "(\w+)=([^"%]*)"', line)
            if m:
                if not (m.group(1) and m.group(1) in self.env):
                    self.env[m.group(2)] = m.group(3)
                continue
            if line.startswith(('if not exist "Host a Wrath realm.bat"', "docker version ", "docker pull ", "docker image inspect ")):
                continue
            if line == 'if not exist "state" mkdir "state"':
                os.makedirs(os.path.join(self.kit, "state"), exist_ok=True)
                continue
            m = re.fullmatch(r'> "state\\seed\.b64" echo ([A-Za-z0-9+/=]+)', line)
            if m:
                with open(os.path.join(self.kit, "state", "seed.b64"), "w") as f:
                    f.write(m.group(1) + " \r\n")   # cmd's echo: CRLF (and a stray space is harmless too)
                continue
            if line.startswith("docker run --rm -v ") and " python -m wuhost.setup " in line:
                p = self.setup(line)
                assert p.returncode == 0, p.stdout + p.stderr
                continue
            if line == 'call "Host a Wrath realm.bat"':
                self.host_bat()
                continue
            raise AssertionError(f"a .bat line this test does not know: {line!r}")

    def host_bat(self):
        """"Host a Wrath realm.bat": no questions (WU_NAME etc. are set), then its setup line (the image choice is a
        Docker matter: the prebuilt name)."""
        bat = open(HOST_BAT, encoding="utf-8").read()
        lines = [ln.strip() for ln in bat.splitlines()]
        get = next(ln for ln in lines if "python -m wuhost.setup get" in ln)
        p = self.setup(re.search(r"`(docker run .*)`", get).group(1))
        assert p.returncode == 0, p.stderr
        init = next(ln for ln in lines if ln.startswith("docker run") and "python -m wuhost.setup init" in ln)
        self.env.update(IMG=self.env.get("WU_IMAGE", "ghcr.io/orionopenwow/wu-ac-wotlk"), TAG=self.env.get("WU_TAG", "stable"))
        p = self.setup(init)
        assert p.returncode == 0, p.stdout + p.stderr


class HostOnWindows(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.mkdtemp(prefix="wu-win-e2e-")
        lo, hi = free_range(20)
        self.relay = await relaymod.Relay(relaymod.Config(
            name="relay.test", http_bind="127.0.0.1:0", game_bind="127.0.0.1", shared_auth_port=free_port(),
            port_min=lo, port_max=hi, state_file=os.path.join(self.tmp, "relay", "state.json"),
            site_url="https://openvanilla.test", site_origins=["https://openvanilla.test"],
            listing_site_secret=SITE_SECRET)).start()
        self.rhttp = f"http://127.0.0.1:{self.relay.http_port()}"
        self.website = serve(Website)
        os.environ.update(SOAP_USER="WUSOAP", AC_SOAP_URL="http://127.0.0.1:9/",
                          PORTAL_URL=f"http://127.0.0.1:{self.website.server_address[1]}", WU_STREAM="0",
                          STREAM_HOST="wrath.example", WU_HOST_DIR=os.path.join(self.tmp, "hosted"),
                          WU_RELAY_LISTING=f"{self.rhttp}/api/listing/realms.json", WU_JOIN_BASE="https://relay.test",
                          WU_LISTING_SITE_SECRET=SITE_SECRET, WU_HANGOUT_FILE=os.path.join(self.tmp, "none.id"))
        spec = importlib.util.spec_from_file_location("wp_win_e2e", PORTAL)
        self.wp = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.wp)
        self.wp.realm_status = lambda: {"online": True, "players": 1, "bots": 0}
        self.hf = self.wp.hostflow
        self.page = serve(self.wp.PageHandler)
        self.realm = await FakeRealm().start()
        self.agents = []

    async def asyncTearDown(self):
        for a in self.agents:
            a.stop_ev.set(); a.close_all(); a.task.cancel()
        await self.relay.stop()
        await self.realm.stop()
        self.page.shutdown(); self.website.shutdown()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def req(self, method, path, body=None, ip="10.3.0.1"):
        c = http.client.HTTPConnection("127.0.0.1", self.page.server_address[1], timeout=30)
        h = {"X-Forwarded-For": ip, "Cookie": "wr_session=alice"}
        if body is not None:
            body = urllib.parse.urlencode(body).encode()
            h["Content-Type"] = "application/x-www-form-urlencoded"
        c.request(method, path, body=body, headers=h)
        r = c.getresponse()
        return r.status, {k.lower(): v for k, v in r.getheaders()}, r.read()

    async def areq(self, *a, **k):
        return await asyncio.to_thread(self.req, *a, **k)

    def kit(self, name):
        kit = os.path.join(self.tmp, name)
        os.makedirs(kit)
        for f in ("Host a Wrath realm.bat", "host-wrath-realm.sh"):
            shutil.copy(os.path.join(HOSTING, "kit", f), kit)
        shutil.copytree(os.path.join(HOSTING, "kit", "tools"), os.path.join(kit, "tools"),
                        ignore=shutil.ignore_patterns("__pycache__"))
        return kit

    def start_agent(self, kit):
        """The kit's agent container: host.json as setup wrote it, the relay's address standing in for DNS."""
        p = os.path.join(kit, "state", "host.json")
        cfg = json.load(open(p))
        self.assertEqual((cfg["relay"], cfg["relay_url"]), ("relay.test", "wss://relay.test/agent"))
        cfg.update(relay_url=f"ws://127.0.0.1:{self.relay.http_port()}/agent", listing_url=f"{self.rhttp}/api/listing/heartbeat")
        json.dump(cfg, open(p, "w"))
        a = agentmod.Agent(os.path.join(kit, "state"), db=FakeDB(self.realm),
                           services={3724: ("127.0.0.1", self.realm.auth_port), 8085: ("127.0.0.1", self.realm.world_port)})
        a.tick, a.heartbeat_every = 0.05, 1
        a.task = asyncio.ensure_future(a.run())
        self.agents.append(a)
        return a, cfg

    async def wait(self, pred, what, timeout=15):
        for _ in range(int(timeout / 0.1)):
            v = await asyncio.to_thread(pred) if not asyncio.iscoroutinefunction(pred) else await pred()
            if v:
                return v
            await asyncio.sleep(0.1)
        self.fail(f"timed out: {what}")

    async def status_text(self, pid):
        self.hf._status.clear()
        with self.wp._listing_lock:
            self.wp._listing["at"] = -1e9
        self.wp.community_realms()
        await asyncio.to_thread(self.wp._listing_done.wait, 3)
        st, _, b = await self.areq("GET", f"/wrath/host/{pid}")
        self.assertEqual(st, 200)
        return b.decode()

    async def test_form_to_bat_to_listed_and_claimed(self):
        st, _, b = await self.areq("GET", "/wrath/host")
        csrf = re.search(rb'name="csrf" value="([0-9a-f]+)"', b).group(1).decode()
        form = {"csrf": csrf, "name": "Frost Haven", "preset": "dalaran", "visibility": "public", "gm": "frostgm",
                "tagline": "Duels at the fountain", "rules": "Be kind.\nDuels by consent."}
        st, h, _ = await self.areq("POST", "/wrath/host", form)
        self.assertEqual(st, 303)
        pid = re.fullmatch(r"/wrath/host/([a-z2-7]{16})", h["location"]).group(1)
        rec = self.hf.load(pid)
        self.assertNotIn("realm_key", rec, "the website never holds a realm key")
        self.assertIn("Waiting for your PC", await self.status_text(pid))

        st, h, bat = await self.areq("GET", f"/wrath/host/{pid}/leyline-{pid}.bat")
        self.assertEqual(st, 200)
        text = bat.decode("utf-8")
        self.assertTrue(text.endswith("\r\n") and "\n" not in text.replace("\r\n", ""), "CRLF only")
        self.assertLess(max(len(ln) for ln in text.split("\r\n")), 8000, "cmd.exe line limit is 8191")
        self.assertNotRegex(text, r"(?i)passw(or)?d\s*=|account create")
        kit = self.kit("kit")
        cmd = Cmd(kit, {})
        cmd.run_bat(text)
        self.assertFalse(os.path.exists(os.path.join(kit, "state", "seed.b64")), "the seed is used once and deleted")
        cfg = json.load(open(os.path.join(kit, "state", "host.json")))
        key = bytes.fromhex(open(os.path.join(kit, "state", "realm.key")).read().strip())
        rid = keys.realm_id(keys.public_key(key))
        self.assertEqual(cfg["realm_id"], rid)
        self.assertNotEqual(rid, pid)
        self.assertEqual((cfg["name"], cfg["profile"], cfg["visibility"], cfg["gm_name"], cfg["claim"], cfg["signup"]),
                         ("Frost Haven", "dalaran", "public", "FROSTGM", rec["claim"], "open"))
        self.assertEqual(cfg["record"]["rules"], ["Be kind.", "Duels by consent."])
        self.assertFalse(os.path.exists(os.path.join(kit, "state", "host-login.txt")), "no generated login, no password")
        self.assertEqual(len([r for r in cmd.ran if r[0][:1] == ["init"]]), 2, "the .bat's init, then the kit's own")

        a, _ = self.start_agent(kit)
        await self.wait(lambda: rid in self.relay.sessions, "the PC connects")
        st, doc, _ = await ahttp("GET", f"{self.rhttp}/api/pair/{keys.pair_hash(rec['claim'])}")
        self.assertEqual((st, doc), (200, {"realm_id": rid, "online": True}))
        page = await self.status_text(pid)
        self.assertRegex(page, r"Online(, listed|: joining the realm list)")
        self.assertIn(f"https://play.openvanilla.app/wrath/r/{rid}", page)
        self.assertIn(f"https://relay.test/join/{rid}#{rec['invite_secret']}~{rec['host_secret']}", page)
        self.assertEqual(self.hf.load(pid)["realm_id"], rid)

        async def listed():
            return "Online, listed" in await self.status_text(pid)
        await self.wait(listed, "listed on Leyline")
        e = self.relay.listing.entries[rid]
        self.assertEqual(e["claimed_by"], "Alice", "claimed for the account through the signed heartbeat")
        self.assertTrue(self.hf.load(pid)["claimed"])
        st, _, _ = await self.areq("GET", f"/wrath/host/{pid}/leyline-{pid}.bat")
        self.assertEqual(st, 410, "nothing more to download once the PC holds the key")

        # a copied download on another PC: its own realm, but the website keeps the first one
        kit2 = self.kit("kit2")
        Cmd(kit2, {}).run_bat(text)
        a2, cfg2 = self.start_agent(kit2)
        await self.wait(lambda: cfg2["realm_id"] in self.relay.sessions, "the copy connects")
        st, doc, _ = await ahttp("GET", f"{self.rhttp}/api/pair/{keys.pair_hash(rec['claim'])}")
        self.assertEqual(doc["realm_id"], rid)
        self.assertNotEqual(cfg2["realm_id"], rid)

    async def test_the_same_kit_never_takes_a_second_realm(self):
        st, _, b = await self.areq("GET", "/wrath/host")
        csrf = re.search(rb'name="csrf" value="([0-9a-f]+)"', b).group(1).decode()
        pids = []
        for name in ("First Realm", "Second Realm"):
            st, h, _ = await self.areq("POST", "/wrath/host", {"csrf": csrf, "name": name, "preset": "main",
                                                               "visibility": "private", "gm": "hostgm", "rules": ""},
                                       ip=f"10.4.0.{len(pids) + 1}")
            pids.append(h["location"].rsplit("/", 1)[1])
        kit = self.kit("kit")
        bats = [(await self.areq("GET", f"/wrath/host/{p}/leyline-{p}.bat"))[2].decode() for p in pids]
        Cmd(kit, {}).run_bat(bats[0])
        first = json.load(open(os.path.join(kit, "state", "host.json")))
        with self.assertRaises(AssertionError) as cm:
            Cmd(kit, {}).run_bat(bats[1])
        self.assertIn("already hosts another realm", str(cm.exception))
        self.assertEqual(json.load(open(os.path.join(kit, "state", "host.json")))["realm_id"], first["realm_id"])


if __name__ == "__main__":
    unittest.main()
