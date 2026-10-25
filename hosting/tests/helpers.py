"""Shared test plumbing: a relay + a fake realm + an agent in one event loop."""
import asyncio
import hashlib
import json
import os
import random
import socket
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
for p in (os.path.join(ROOT, "kit", "tools"), os.path.join(ROOT, "relay"), HERE):
    if p not in sys.path:
        sys.path.insert(0, p)

from wunet import keys, srp6, ws, wire335  # noqa: E402
from wuhost import agent as agentmod  # noqa: E402
from wurelay import relay as relaymod  # noqa: E402
from fake_realm import FakeRealm  # noqa: E402


def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


def free_range(n=20):
    for _ in range(50):
        base = random.randrange(20000, 60000) & ~1
        ok = True
        socks = []
        for p in range(base, base + n):
            s = socket.socket()
            try:
                s.bind(("127.0.0.1", p))
            except OSError:
                ok = False
            socks.append(s)
        for s in socks:
            s.close()
        if ok:
            return base, base + n - 1
    raise RuntimeError("no free port range")


class FakeDB:
    """Stands in for the realm's MySQL: the realm list row lives in the fake realm."""

    def __init__(self, realm: FakeRealm):
        self.realm = realm
        self.address_calls = []
        self.fail_address = 0

    def set_realm_address(self, name, address, port):
        if self.fail_address:
            self.fail_address -= 1
            raise ConnectionError("database starting")
        self.address_calls.append((name, address, port))
        self.realm.realm_name = name
        new = f"{address}:{port}"
        if self.realm.world_address == new:
            return "unchanged"
        self.realm.world_address = new
        return "updated"

    def create_account(self, username, salt, verifier, gmlevel=0):
        if username.upper() in self.realm.accounts:
            return "taken"
        self.realm.add_account_raw(username, bytes.fromhex(salt), bytes.fromhex(verifier))
        return "ok"

    def status(self):
        return {"players": 2, "bots": 40, "uptime_s": 1234, "bots_method": "rndbot_account_prefix"}


def make_host_state(tmp, name="Test Realm", visibility="public", relay_url="", listing_url=None, signup="invite"):
    secret = keys.load_or_create(os.path.join(tmp, "realm.key"))
    rid = keys.realm_id(keys.public_key(secret))
    cfg = {"realm_id": rid, "name": name, "visibility": visibility, "signup": signup,
           "invite_secret": "INV" + "".join(random.choice("ABCDEFGHJKMNPQRSTVWXYZ23456789") for _ in range(20)),
           "relay_url": relay_url, "listing_url": listing_url, "profile": "main",
           "record": {"name": name, "tagline": "A test realm", "type": "PvE", "ruleset": "main"}}
    with open(os.path.join(tmp, "host.json"), "w") as f:
        json.dump(cfg, f)
    return cfg, secret


class WSStream:
    """(reader, writer) over a WebSocket, so wire335 can run through the relay's /r/<id>/ws/<port>."""

    def __init__(self, sock):
        self.sock = sock
        self.reader = asyncio.StreamReader()
        self.task = asyncio.ensure_future(self._pump())

    async def _pump(self):
        try:
            while True:
                op, data = await self.sock.recv()
                if op == ws.OP_BIN:
                    self.reader.feed_data(data)
        except ws.WSClosed:
            self.reader.feed_eof()

    # writer side
    def write(self, data):
        self.sock.send_nowait(bytes(data), ws.OP_BIN)

    async def drain(self):
        await self.sock.writer.drain()

    def close(self):
        self.sock.abort()
        self.task.cancel()


def ws_opener(base, realm_id, invite=None, headers=None):
    """opener(host, port) for wire335 that dials the relay's WebSocket path instead of TCP."""
    async def opener(host, port):
        q = f"?invite={invite}" if invite else ""
        sock = await ws.connect(f"{base}/r/{realm_id}/ws/{port}{q}", headers=headers)
        s = WSStream(sock)
        return s.reader, s
    return opener


class Rig:
    """relay + fake realm + agent. `async with Rig(...) as r:`"""

    def __init__(self, visibility="public", signup="invite", listing=True, **cfg_over):
        self.visibility, self.signup, self.listing = visibility, signup, listing
        self.cfg_over = cfg_over
        self.tmp = tempfile.mkdtemp(prefix="wu-test-")
        self.agents = []

    async def __aenter__(self):
        lo, hi = free_range(20)
        self.shared = free_port()
        cfg = dict(name="relay.test", http_bind="127.0.0.1:0", game_bind="127.0.0.1", shared_auth_port=self.shared,
                   port_min=lo, port_max=hi, state_file=os.path.join(self.tmp, "relay", "state.json"),
                   site_url="https://openvanilla.test", site_origins=["https://openvanilla.test"],
                   listing_site_secret="site-secret")
        cfg.update(self.cfg_over)
        self.relay = await relaymod.Relay(relaymod.Config(**cfg)).start()
        self.base = f"ws://127.0.0.1:{self.relay.http_port()}"
        self.http = f"http://127.0.0.1:{self.relay.http_port()}"
        self.realm = await FakeRealm().start()
        self.db = FakeDB(self.realm)
        self.host_dir = os.path.join(self.tmp, "host")
        os.makedirs(self.host_dir)
        self.cfg, self.secret = make_host_state(
            self.host_dir, visibility=self.visibility, signup=self.signup, relay_url=self.base + "/agent",
            listing_url=(self.http + "/api/listing/heartbeat") if self.listing else None)
        self.rid = self.cfg["realm_id"]
        self.agent = self.new_agent()
        await self.wait_online()
        return self

    def new_agent(self):
        a = agentmod.Agent(self.host_dir, db=self.db,
                           services={3724: ("127.0.0.1", self.realm.auth_port), 8085: ("127.0.0.1", self.realm.world_port)})
        a.tick = 0.05
        a.task = asyncio.ensure_future(a.run())
        self.agents.append(a)
        return a

    async def wait_online(self, timeout=10):
        t0 = time.monotonic()
        while time.monotonic() - t0 < timeout:
            s = self.relay.sessions.get(self.rid)
            if s and self.agent.address_done:
                return s
            await asyncio.sleep(0.05)
        raise AssertionError("agent never came online")

    @property
    def ports(self):
        a = self.relay.state["realms"][self.rid]
        return a["auth"], a["world"]

    async def __aexit__(self, *exc):
        for a in self.agents:
            a.stop_ev.set()
            a.close_all()
            a.task.cancel()
        await self.relay.stop()
        await self.realm.stop()
        await asyncio.sleep(0)


async def http(method, url, body=None, headers=None):
    """Tiny HTTP client: (status, json or text)."""
    import urllib.parse
    u = urllib.parse.urlsplit(url)
    r, w = await asyncio.open_connection(u.hostname, u.port)
    data = json.dumps(body).encode() if body is not None else b""
    lines = [f"{method} {u.path}{'?' + u.query if u.query else ''} HTTP/1.1", f"Host: {u.hostname}",
             f"Content-Length: {len(data)}", "Content-Type: application/json"]
    for k, v in (headers or {}).items():
        lines.append(f"{k}: {v}")
    w.write(("\r\n".join(lines) + "\r\n\r\n").encode() + data)
    await w.drain()
    raw = await r.read()
    w.close()
    head, _, payload = raw.partition(b"\r\n\r\n")
    status = int(head.split(b" ")[1])
    hdrs = {}
    for ln in head.decode("latin-1").split("\r\n")[1:]:
        k, _, v = ln.partition(":")
        hdrs[k.strip().lower()] = v.strip()
    try:
        return status, json.loads(payload), hdrs
    except ValueError:
        return status, payload.decode("utf-8", "replace"), hdrs


def srp_account(user, password):
    salt, ver = srp6.make_verifier(user, password)
    return {"username": user, "salt": salt.hex(), "verifier": ver.hex()}


def sha(s):
    return hashlib.sha256(s.encode()).hexdigest()
