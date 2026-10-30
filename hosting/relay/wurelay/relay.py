"""wu-relay: home-hosted WrathUnleashed (3.3.5a) realms reachable with no open ports, the host's
IP hidden.

    host PC: realm (docker) <- agent --outbound wss--> relay <-- players (raw TCP or WebSocket)

* The host's agent keeps ONE outbound WebSocket to wss://<relay>/agent (port 443 only) and proves
  its realm key (Ed25519 challenge). Player connections are multiplexed on it (wunet/mux.py).
* Each realm gets a fixed pair of relay ports: <auth_port> (logon, 3724 behind it) and
  <world_port> (= auth_port + 1, the world server 8085 behind it). The realm advertises
  "<relay name>:<world_port>" in its realm list, so stock clients go back to the relay.
* Players set `realmlist <relay name>` (shared port 3724: routed by the player's IP to the realm
  whose join page they last opened, "a knock") or `realmlist <relay name>:<auth_port>`.
* Browser client: wss://<relay>/r/<realm id>/ws/<port> (port 3724/8085, or the realm's own pair), or the
  realm hop bridge wss://<relay>/ws/<realm id>/auth and /ws/<realm id>/world (the in-game Leyline window's
  Join: the page rewrites the client's /ws/<port> to these). Same framing as wu-play's /ws/<port>: binary
  messages, one TCP read per message, the bytes reassembled as a stream on both sides; either side's close
  closes the other. The bridge only ever reaches a realm whose agent is connected and signed in (its
  multiplexed tunnel): the relay never dials a host, and nothing in the request names one (?host= is ignored).
  Limits on top of the per-realm and per-IP ones: WebSocket upgrades per IP per minute, browser streams in
  total, all streams in total, and an Origin allow-list (a page on another site can't use a player's browser).
* Realms made on the website ("+ Your server", stream/hostflow.py): the key is made on the host's PC, and its
  hello carries pair_sha256 = sha256("leyline-pair-v1\n" + the website's token). GET /api/pair/<that hash>
  tells the website which realm id is its own (first realm to show a hash keeps it).
* Private realms: only IPs that opened the invite link (knock with the secret) get in, or a
  WebSocket that carries the secret. The relay keeps only sha256(secret); the host sets it.
* Abuse limits: per realm (streams, KB/s token bucket, GB/day), per IP (streams, connection
  rate, wrong passwords: the relay reads only the authserver's logon answers, as a realm can't tell its
  relay players apart), idle timeouts, registration rate, port pool size. See Config.

Privacy: the host never sees player IPs (every connection reaches the realm from the agent),
players never see the host's IP. Logs carry IPs only as a salted daily hash; the knock table
(IP -> realm, needed for routing) lives in memory only and is never written to disk.
"""
import asyncio
import collections
import hashlib
import hmac
import ipaddress
import json
import logging
import os
import re
import secrets
import signal
import sys
import time

from wunet import domains, keys, mux, ws
from wunet.mux import CLOSE, DATA, OPEN

from . import httpd, listing, meshnode

log = logging.getLogger("wu-relay")
SID_RE = re.compile(r"^[a-z2-7]{16}$")
USER_RE = re.compile(r"^[A-Za-z0-9]{3,16}$")
HEX64_RE = re.compile(r"^[0-9a-fA-F]{64}$")
NAME_RE = re.compile(r"^[A-Za-z0-9 _'-]{1,32}$")
VISIBILITIES = ("public", "private")
SIGNUPS = ("invite", "open", "off")
HERE = os.path.dirname(os.path.abspath(__file__))


def _env_int(name, default):
    v = os.environ.get(name)
    return int(v) if v not in (None, "") else default


# (attribute, env var, value) for RELAY_VOLUNTEER=1: about 25 realms, 512 streams, 5 GB a day per realm.
VOLUNTEER_DEFAULTS = (("max_realms", "RELAY_MAX_REALMS", 25), ("max_streams_total", "RELAY_MAX_STREAMS_TOTAL", 512),
                      ("max_ws_total", "RELAY_MAX_WS_TOTAL", 128), ("kbps", "RELAY_KBPS", 256),
                      ("daily_gb", "RELAY_DAILY_GB", 5), ("max_streams", "RELAY_MAX_STREAMS", 64),
                      ("shared_auth_port", "RELAY_SHARED_AUTH_PORT", 0), ("mesh", "RELAY_MESH", True))


class Config:
    def __init__(self, **over):
        e = os.environ.get
        self.name = e("RELAY_NAME", domains.RELAY)   # public DNS name (A record only!)
        self.http_bind = e("RELAY_HTTP_BIND", "127.0.0.1:8080")  # Caddy proxies https here
        self.game_bind = e("RELAY_GAME_BIND", "0.0.0.0")         # raw TCP game ports
        self.shared_auth_port = _env_int("RELAY_SHARED_AUTH_PORT", 3724)  # 0 = off
        self.port_min = _env_int("RELAY_PORT_MIN", 40000)
        self.port_max = _env_int("RELAY_PORT_MAX", 40999)
        self.state_file = e("RELAY_STATE", "/var/lib/wu-relay/state.json")
        self.trust_proxy = e("RELAY_TRUST_PROXY", "1") == "1"   # X-Forwarded-For from a trusted proxy only
        # Who may set X-Forwarded-For: loopback (Caddy on the host network) and, when Caddy runs in a
        # Docker bridge network (a box that already has a web stack), that network, e.g. 172.18.0.0/16.
        self.trusted_proxies = e("RELAY_TRUSTED_PROXIES", "127.0.0.1/32,::1/128")
        self.allow_file = e("RELAY_ALLOW_FILE", "")             # realm ids; empty = open registration
        self.block_file = e("RELAY_BLOCK_FILE", "")             # realm ids refused and delisted (re-read every minute)
        self.site_origins = [o for o in e("RELAY_SITE_ORIGINS", domains.SITE).split(",") if o]
        self.site_url = e("RELAY_SITE_URL", domains.SITE)
        # Join pages: the relay serves /join/<id> itself, so links work without the website.
        self.join_base = e("RELAY_JOIN_BASE", "")   # empty = https://<name>
        # The browser game's own sites: they may frame /join/<id>?hop=1 and open the hop bridge. A WebSocket
        # whose Origin is neither one of these nor a site origin is refused (no Origin: a native tool, allowed
        # as raw TCP is).
        self.play_origins = [o for o in e("RELAY_PLAY_ORIGINS", f"https://wrath.{domains.DOMAIN},https://play.{domains.DOMAIN}").split(",") if o]

        self.listing = e("RELAY_LISTING", "1") == "1"
        self.listing_site_secret = e("RELAY_LISTING_SITE_SECRET", "")
        # Where this relay runs (na-east na-west sa eu africa me asia oce, or empty): the listing's coarse region
        # estimate for realms whose tunnel answers fast (wurelay/listing.py).
        self.region = e("RELAY_REGION", "")
        # Ready but off: list "direct connect available" for hosts who allow it (the launcher's p2p_hosting flag).
        self.advertise_direct = e("RELAY_ADVERTISE_DIRECT", "0") == "1"
        # The Leyline mesh (docs/LEYLINE-MESH.md), off by default: this relay becomes one node of the realm list
        # gossip (wurelay/meshnode.py). RELAY_VOLUNTEER=1 is the community relay profile: smaller default caps.
        self.mesh = e("RELAY_MESH", "0") == "1"
        self.mesh_bootstrap = e("RELAY_MESH_BOOTSTRAP", f"https://{domains.RELAY}")
        self.mesh_node_key = e("RELAY_NODE_KEY", "")            # empty: node.key next to RELAY_STATE
        self.mesh_public_http = e("RELAY_MESH_HTTP", "")        # empty: https://<name>
        self.mesh_every = _env_int("RELAY_MESH_EVERY", 10)
        self.mesh_fanout = _env_int("RELAY_MESH_FANOUT", 3)
        self.volunteer = e("RELAY_VOLUNTEER", "0") == "1"
        # --- limits per realm
        self.max_streams = _env_int("RELAY_MAX_STREAMS", 128)          # a player uses 2 (auth, world)
        self.kbps = _env_int("RELAY_KBPS", 512)                          # both directions together
        self.daily_gb = _env_int("RELAY_DAILY_GB", 20)
        # --- limits per player IP
        self.max_streams_per_ip = _env_int("RELAY_MAX_STREAMS_PER_IP", 8)       # in one realm
        self.max_streams_per_ip_total = _env_int("RELAY_MAX_STREAMS_PER_IP_TOTAL", 24)
        self.conn_rate_per_ip = _env_int("RELAY_CONN_PER_MIN_PER_IP", 40)
        self.ws_rate_per_ip = _env_int("RELAY_WS_PER_MIN_PER_IP", 30)          # browser upgrades (each hop: 2)
        # wrong passwords (failed logons the realm's authserver answered), per player IP and realm: every player reaches
        # a realm from its agent's address, so the realm can't tell players apart (an IP ban there would lock out
        # everyone); the relay can. After this many in RELAY_AUTH_FAIL_WINDOW_SECS, that IP's logins to that realm wait.
        self.auth_fails_per_ip = _env_int("RELAY_AUTH_FAILS_PER_IP", 10)
        self.auth_fail_window = _env_int("RELAY_AUTH_FAIL_WINDOW_SECS", 600)
        # --- limits for the whole relay
        self.max_streams_total = _env_int("RELAY_MAX_STREAMS_TOTAL", 4096)   # every realm, TCP and browser
        self.max_ws_total = _env_int("RELAY_MAX_WS_TOTAL", 1024)             # browser streams (the bridge)
        # --- timeouts
        self.stream_idle = _env_int("RELAY_STREAM_IDLE_SECS", 900)
        self.ctrl_idle = _env_int("RELAY_CTRL_IDLE_SECS", 90)
        self.hello_timeout = _env_int("RELAY_HELLO_TIMEOUT_SECS", 10)
        self.request_timeout = _env_int("RELAY_REQUEST_TIMEOUT_SECS", 8)
        self.knock_ttl = _env_int("RELAY_KNOCK_TTL_SECS", 86400)
        # --- registration and signup
        self.new_realms_per_ip_hour = _env_int("RELAY_NEW_REALMS_PER_IP_HOUR", 3)
        self.max_realms = _env_int("RELAY_MAX_REALMS", 0) or (self.port_max - self.port_min + 1) // 2
        self.reclaim_days = _env_int("RELAY_RECLAIM_DAYS", 30)
        self.accounts_per_ip_hour = _env_int("RELAY_ACCOUNTS_PER_IP_HOUR", 3)
        self.accounts_per_realm_day = _env_int("RELAY_ACCOUNTS_PER_REALM_DAY", 50)
        self.knocks_per_ip_min = _env_int("RELAY_KNOCKS_PER_IP_MIN", 10)
        self.pair_lookups_per_ip_min = _env_int("RELAY_PAIR_PER_MIN_PER_IP", 60)   # the website asks for its realms
        self.max_pairs = _env_int("RELAY_MAX_PAIRS", 20000)
        self.status_ttl = _env_int("RELAY_STATUS_TTL_SECS", 30)
        if self.volunteer or over.get("volunteer"):
            # a community relay on someone's own connection: modest caps unless the operator set them
            for k, env, v in VOLUNTEER_DEFAULTS:
                if os.environ.get(env) in (None, "") and k not in over:
                    setattr(self, k, v)
        for k, v in over.items():
            if not hasattr(self, k):
                raise AttributeError(k)
            setattr(self, k, v)
        self.join_base = (self.join_base or f"https://{self.name}").rstrip("/")
        nets = self.trusted_proxies if isinstance(self.trusted_proxies, (list, tuple)) else self.trusted_proxies.split(",")
        self.trusted_proxies = [ipaddress.ip_network(str(n).strip(), strict=False) for n in nets if str(n).strip()]

    def is_trusted_proxy(self, peer):
        try:
            a = ipaddress.ip_address(peer)
        except ValueError:
            return False
        if getattr(a, "ipv4_mapped", None):
            a = a.ipv4_mapped
        return any(a.version == n.version and a in n for n in self.trusted_proxies)


def utc_day(now=None):
    return time.strftime("%Y-%m-%d", time.gmtime(now))


class Window:
    """Events per key within a sliding window."""

    def __init__(self, seconds):
        self.seconds = seconds
        self.ev = collections.defaultdict(collections.deque)

    def hit(self, key, limit, now=None) -> bool:
        now = time.monotonic() if now is None else now
        q = self.ev[key]
        while q and now - q[0] > self.seconds:
            q.popleft()
        if len(q) >= limit:
            return False
        q.append(now)
        return True

    def sweep(self):
        now = time.monotonic()
        for k in [k for k, q in self.ev.items() if not q or now - q[-1] > self.seconds]:
            del self.ev[k]


# ------------------------------------------------------------------------------ player sides
class TcpConn:
    kind = "tcp"

    def __init__(self, reader, writer):
        self.reader, self.writer = reader, writer

    async def read(self):
        try:
            return await self.reader.read(mux.MAX_CHUNK)
        except (ConnectionError, OSError):
            return b""

    def write(self, data) -> bool:
        if self.writer.is_closing():
            return False
        self.writer.write(data)
        t = self.writer.transport
        return t.get_write_buffer_size() <= mux.MAX_BUFFER

    def close(self):
        try:
            self.writer.close()
        except (OSError, RuntimeError):
            pass


class WsConn:
    kind = "ws"

    def __init__(self, sock: ws.WebSocket):
        self.sock = sock

    async def read(self):
        try:
            while True:
                op, data = await self.sock.recv()
                if op == ws.OP_BIN:
                    return data
        except ws.WSClosed:
            return b""

    def write(self, data) -> bool:
        if self.sock.closed:
            return False
        for i in range(0, len(data), mux.MAX_CHUNK):
            self.sock.send_nowait(data[i:i + mux.MAX_CHUNK], ws.OP_BIN)
        return self.sock.buffered() <= mux.MAX_BUFFER

    def close(self):
        self.sock.abort()


class Stream:
    def __init__(self, sid, session, port, conn, ip):
        self.sid, self.session, self.port, self.conn, self.ip = sid, session, port, conn, ip
        self.last = time.monotonic()
        self.closed = False
        self.bytes = 0
        self.auth_seen = 0     # logon answers looked at (service 3724 only: the challenge, then the proof)


# ------------------------------------------------------------------------------ realm session
class Session:
    """One connected host agent (one realm)."""

    def __init__(self, relay, sock, realm_id, hello, alloc, agent_ip):
        self.relay, self.ws, self.realm_id, self.agent_ip = relay, sock, realm_id, agent_ip
        self.name = hello["name"]
        self.visibility = hello["visibility"]
        self.invite_sha = (hello.get("invite_sha256") or "").lower() or None
        self.signup = hello.get("signup", "invite")
        self.host_sha = (hello.get("host_sha256") or "").lower() or None
        self.pair_sha = (hello.get("pair_sha256") or "").lower() or None
        self.version = str(hello.get("version", ""))[:40]
        self.alloc = alloc
        self.streams: dict[int, Stream] = {}
        self.next_sid = 1
        self.bucket = mux.TokenBucket(relay.cfg.kbps * 1024)
        self.last_frame = time.monotonic()
        self.connected_at = time.time()
        self.pending: dict[int, asyncio.Future] = {}
        self.next_req = 1
        self.closed = False
        self.status_cache = (0.0, None)
        self.rtt_ms = None          # the tunnel's round trip (the fastest of the recent probes), for the listing
        self.rtt_samples = collections.deque(maxlen=5)
        self.rtt_at = 0.0

    # control requests to the agent ("status", "create_account")
    async def request(self, op, **fields):
        rid = self.next_req
        self.next_req += 1
        fut = asyncio.get_running_loop().create_future()
        self.pending[rid] = fut
        try:
            self.ws.send_nowait(json.dumps(dict(fields, req=rid, op=op)))
            return await asyncio.wait_for(fut, self.relay.cfg.request_timeout)
        finally:
            self.pending.pop(rid, None)

    async def probe_rtt(self):
        """Time one control round trip. "rtt" is an op no agent knows, so every agent version answers it at once
        ({"ok": false}) without touching its realm."""
        self.rtt_at = time.monotonic()
        t0 = time.monotonic()
        try:
            await self.request("rtt")
        except (asyncio.TimeoutError, ConnectionError, ws.WSClosed):
            return None
        self.rtt_samples.append((time.monotonic() - t0) * 1000)
        self.rtt_ms = round(min(self.rtt_samples), 1)
        return self.rtt_ms

    def open_stream(self, port, conn, ip) -> Stream:
        sid = self.next_sid
        self.next_sid += 1
        st = Stream(sid, self, port, conn, ip)
        self.streams[sid] = st
        self.ws.send_nowait(mux.pack(OPEN, sid, mux.open_payload(port)))
        return st

    def close_stream(self, st: Stream, tell_agent=True, why=""):
        if st.closed:
            return
        st.closed = True
        self.streams.pop(st.sid, None)
        self.relay.ip_streams_dec(st.ip, self.realm_id)
        if st.conn.kind == "ws":
            self.relay.ws_open -= 1
        st.conn.close()
        if tell_agent and not self.closed:
            try:
                self.ws.send_nowait(mux.pack(CLOSE, st.sid))
            except ws.WSClosed:
                pass
        self.relay.metrics["streams_closed"] += 1
        if why:
            log.info("stream closed realm=%s sid=%d why=%s", self.realm_id, st.sid, why)

    def shutdown(self, why=""):
        if self.closed:
            return
        self.closed = True
        for st in list(self.streams.values()):
            self.close_stream(st, tell_agent=False)
        for fut in self.pending.values():
            if not fut.done():
                fut.set_exception(ConnectionError("realm went offline"))
        self.ws.abort()
        log.info("realm offline realm=%s why=%s", self.realm_id, why)


# ------------------------------------------------------------------------------ the relay
class Relay:
    def __init__(self, cfg: Config | None = None):
        self.cfg = cfg or Config()
        self.sessions: dict[str, Session] = {}
        # realms: realm_id -> {auth, world, first, last, name}; pairs: pair hash -> realm id (a realm made on the
        # website shows sha256("leyline-pair-v1\n" + its token) so the website can find it: first realm wins)
        self.state = {"realms": {}, "usage": {}, "pairs": {}}
        self.port_owner: dict[int, tuple[str, int]] = {}   # relay port -> (realm_id, service port)
        self.listeners: dict[int, asyncio.base_events.Server] = {}
        self.knocks: dict[str, collections.OrderedDict] = {}  # ip -> realm_id -> expiry (memory only)
        self.ip_total = collections.Counter()
        self.ip_realm = collections.Counter()
        self.conn_rate = Window(60)
        self.ws_rate = Window(60)
        self.auth_fails: dict[tuple, collections.deque] = {}   # (ip, realm id) -> failure times (memory only)
        self.ws_open = 0          # browser streams open now (WsConn), for max_ws_total
        self.reg_rate = Window(3600)
        self.acct_ip = Window(3600)
        self.acct_realm = Window(86400)
        self.knock_rate = Window(60)
        self.pair_rate = Window(60)
        self.salt = secrets.token_bytes(16)
        self.metrics = collections.Counter()
        self.dirty = False
        self.http_server = None
        self.tasks = set()
        self.allow = None
        self.blocked = set()
        self.block_mtime = None
        self.listing = listing.Listing(self.cfg, self) if self.cfg.listing else None
        self.mesh = meshnode.MeshNode(self.cfg, self) if self.cfg.mesh else None
        self._load()

    # ---------------------------------------------------------------- state
    def _load(self):
        try:
            with open(self.cfg.state_file, encoding="utf-8") as f:
                st = json.load(f)
            self.state["realms"] = st.get("realms", {})
            self.state["usage"] = st.get("usage", {})
            self.state["pairs"] = st.get("pairs", {}) if isinstance(st.get("pairs"), dict) else {}
        except FileNotFoundError:
            pass
        except (OSError, ValueError) as e:
            log.error("state file unreadable (%s): starting empty, not overwriting until next save", e)
        for rid, r in self.state["realms"].items():
            self.port_owner[r["auth"]] = (rid, 3724)
            self.port_owner[r["world"]] = (rid, 8085)
        if self.cfg.allow_file:
            try:
                with open(self.cfg.allow_file, encoding="utf-8") as f:
                    self.allow = {ln.split()[0] for ln in f if ln.strip() and not ln.startswith("#")}
            except OSError as e:
                log.error("allow file unreadable (%s): no realm may register", e)
                self.allow = set()

    def load_blocklist(self):
        """RELAY_BLOCK_FILE: one realm id per line (# comments). Blocked realms are cut off at once,
        refused at login and left out of the listing."""
        if not self.cfg.block_file:
            return
        try:
            m = os.stat(self.cfg.block_file).st_mtime
        except OSError:
            m = None
        if m == self.block_mtime:
            return
        self.block_mtime = m
        ids = set()
        if m is not None:
            with open(self.cfg.block_file, encoding="utf-8") as f:
                ids = {ln.split()[0] for ln in f if ln.strip() and not ln.lstrip().startswith("#")}
        self.blocked = ids
        for rid in ids & set(self.sessions):
            self.sessions[rid].shutdown("blocked by the relay operator")
        log.info("blocklist: %d realms", len(ids))

    def save(self):
        if not self.dirty:
            return
        tmp = self.cfg.state_file + ".tmp"
        try:
            os.makedirs(os.path.dirname(os.path.abspath(self.cfg.state_file)), exist_ok=True)
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(self.state, f, indent=1, sort_keys=True)
            os.replace(tmp, self.cfg.state_file)
            self.dirty = False
        except OSError as e:
            log.error("cannot save state: %s", e)

    def iphash(self, ip):
        return hashlib.sha256(self.salt + utc_day().encode() + str(ip).encode()).hexdigest()[:12]

    # ---------------------------------------------------------------- ports
    def allocate(self, realm_id, name):
        r = self.state["realms"].get(realm_id)
        now = int(time.time())
        if r:
            r["last"], r["name"] = now, name
            self.dirty = True
            return r
        used = {p for rr in self.state["realms"].values() for p in (rr["auth"], rr["world"])}
        if self.cfg.shared_auth_port:
            used.add(self.cfg.shared_auth_port)
        start = self.cfg.port_min + (self.cfg.port_min & 1)
        free = next((p for p in range(start, self.cfg.port_max, 2) if p not in used and p + 1 not in used), None)
        if free is None:  # reclaim the longest-unseen realm older than reclaim_days
            cutoff = now - self.cfg.reclaim_days * 86400
            stale = sorted((rr["last"], rid) for rid, rr in self.state["realms"].items()
                           if rr["last"] < cutoff and rid not in self.sessions)
            if not stale:
                return None
            _, old = stale[0]
            free = self.state["realms"].pop(old)["auth"]
            self.state["usage"].pop(old, None)
            log.info("reclaimed ports %d/%d from realm %s", free, free + 1, old)
        r = {"auth": free, "world": free + 1, "first": now, "last": now, "name": name}
        self.state["realms"][realm_id] = r
        self.port_owner[free] = (realm_id, 3724)
        self.port_owner[free + 1] = (realm_id, 8085)
        self.dirty = True
        return r

    async def ensure_listener(self, port):
        if port in self.listeners:
            return True
        try:
            srv = await asyncio.start_server(lambda r, w, p=port: self._spawn(self.on_game_tcp(r, w, p)),
                                             self.cfg.game_bind, port, reuse_address=True, limit=1 << 16)
        except OSError as e:
            log.error("cannot listen on %s:%d: %s", self.cfg.game_bind, port, e)
            return False
        self.listeners[port] = srv
        return True

    def bound_port(self, port):
        """The real port of a listener (tests bind port 0)."""
        srv = self.listeners.get(port)
        return srv.sockets[0].getsockname()[1] if srv else None

    # ---------------------------------------------------------------- usage / caps
    def usage(self, realm_id):
        u = self.state["usage"].get(realm_id)
        day = utc_day()
        if not u or u.get("day") != day:
            u = {"day": day, "bytes": 0}
            self.state["usage"][realm_id] = u
        return u

    def over_quota(self, realm_id):
        return self.usage(realm_id)["bytes"] >= self.cfg.daily_gb * (1 << 30)

    def count_bytes(self, session, n):
        self.usage(session.realm_id)["bytes"] += n
        self.metrics["bytes"] += n
        self.dirty = True

    def ip_streams_inc(self, ip, realm_id):
        self.ip_total[ip] += 1
        self.ip_realm[(ip, realm_id)] += 1

    def ip_streams_dec(self, ip, realm_id):
        self.ip_total[ip] -= 1
        if self.ip_total[ip] <= 0:
            del self.ip_total[ip]
        self.ip_realm[(ip, realm_id)] -= 1
        if self.ip_realm[(ip, realm_id)] <= 0:
            del self.ip_realm[(ip, realm_id)]

    # ---------------------------------------------------------------- access
    def knock(self, ip, realm_id):
        t = self.knocks.setdefault(ip, collections.OrderedDict())
        t.pop(realm_id, None)
        t[realm_id] = time.monotonic() + self.cfg.knock_ttl
        while len(t) > 16:
            t.popitem(last=False)

    def knocked(self, ip, realm_id):
        t = self.knocks.get(ip)
        exp = t.get(realm_id) if t else None
        return exp is not None and exp > time.monotonic()

    def last_knock(self, ip):
        t = self.knocks.get(ip)
        if not t:
            return None
        now = time.monotonic()
        for rid in reversed(t):
            if t[rid] > now:
                return rid
        return None

    # ---------------------------------------------------------------- wrong passwords
    def watch_logon(self, st, data):
        """The realm's authserver answers in plain bytes: the logon challenge answer [0x00, 0x00, result, ...] and the
        proof answer [0x01, error, ...]. A non-zero result is a failed logon (wrong password, unknown or banned account)
        and counts against the player's IP for this realm. Nothing else of the stream is read."""
        st.auth_seen += 1
        if len(data) < 2:
            return
        failed = (data[0] == 0x01 and data[1] != 0) or (data[0] == 0x00 and len(data) >= 3 and data[2] != 0)
        if data[0] == 0x01:
            st.auth_seen = 2   # the proof answer: the logon is decided either way
        if failed:
            q = self.auth_fails.setdefault((st.ip, st.session.realm_id), collections.deque())
            q.append(time.monotonic())
            self.metrics["auth_failed"] += 1

    def auth_locked(self, ip, realm_id):
        q = self.auth_fails.get((ip, realm_id))
        if not q:
            return False
        now = time.monotonic()
        while q and now - q[0] > self.cfg.auth_fail_window:
            q.popleft()
        if not q:
            del self.auth_fails[(ip, realm_id)]
            return False
        return len(q) >= self.cfg.auth_fails_per_ip

    def remember_pair(self, s):
        """Book the realm's pair hash (first realm to show it keeps it: a copied download can't take over a
        realm the website already found)."""
        if not s.pair_sha:
            return
        pairs = self.state["pairs"]
        have = pairs.get(s.pair_sha)
        if have == s.realm_id:
            return
        if have is not None:
            log.info("pair hash already belongs to realm=%s; realm=%s ignored", have, s.realm_id)
            return
        while len(pairs) >= max(1, self.cfg.max_pairs):
            pairs.pop(next(iter(pairs)))
        pairs[s.pair_sha] = s.realm_id
        self.dirty = True

    def api_pair(self, req, pair):
        """GET /api/pair/<sha256 hex>: the realm a website-made realm's PC registered (its id is known only to whoever
        knows the token behind the hash: the website and the host's PC), and whether it is online now."""
        h = self.cors(req, True)
        if not self.pair_rate.hit(req.ip, self.cfg.pair_lookups_per_ip_min):
            return httpd.response(429, {"error": "slow down"}, headers=h)
        rid = self.state["pairs"].get(pair.lower())
        if not rid:
            return httpd.response(404, {"error": "no realm has shown this pairing yet"}, headers=h)
        return httpd.response(200, {"realm_id": rid, "online": rid in self.sessions}, headers=h)

    def invite_ok(self, session, invite):
        if not invite or not session.invite_sha:
            return False
        return hmac.compare_digest(hashlib.sha256(invite.encode()).hexdigest(), session.invite_sha)

    def admit(self, realm_id, ip, invite=None):
        """(session, None) when this player may open a stream to the realm, else (None, (status, why))."""
        s = self.sessions.get(realm_id)
        if not s:
            return None, (404, "realm offline")
        if s.visibility == "private" and not (self.knocked(ip, realm_id) or self.invite_ok(s, invite)):
            return None, (403, "private realm: open your invite link on this computer first")
        if self.over_quota(realm_id):
            return None, (429, "realm used its traffic for today")
        if len(s.streams) >= self.cfg.max_streams:
            return None, (503, "realm is full")
        if self.streams_total() >= self.cfg.max_streams_total:
            return None, (503, "the relay is full right now")
        if self.ip_realm[(ip, realm_id)] >= self.cfg.max_streams_per_ip:
            return None, (429, "too many connections from your address")
        if self.ip_total[ip] >= self.cfg.max_streams_per_ip_total:
            return None, (429, "too many connections from your address")
        if not self.conn_rate.hit(ip, self.cfg.conn_rate_per_ip):
            return None, (429, "connecting too fast")
        return s, None

    def streams_total(self):
        return sum(len(s.streams) for s in self.sessions.values())

    def ws_origin_ok(self, req):
        origin = req.headers.get("origin")
        return origin is None or origin in self.cfg.play_origins or origin in self.cfg.site_origins

    # ---------------------------------------------------------------- player pump
    async def pump(self, session: Session, st: Stream):
        """Player -> agent until either side ends."""
        try:
            while not st.closed and not session.closed:
                data = await st.conn.read()
                if not data:
                    break
                st.last = time.monotonic()
                st.bytes += len(data)
                self.count_bytes(session, len(data))
                await session.bucket.take(len(data))
                if st.closed or session.closed:
                    break
                session.ws.send_nowait(mux.pack(DATA, st.sid, data))
                if session.ws.buffered() > mux.MAX_BUFFER:
                    await session.ws.writer.drain()
        except (ws.WSClosed, ConnectionError, OSError):
            pass
        finally:
            session.close_stream(st, tell_agent=True)

    async def on_game_tcp(self, reader, writer, port):
        peer = writer.get_extra_info("peername") or ("?", 0)
        ip = peer[0]
        conn = TcpConn(reader, writer)
        if port == self.cfg.shared_auth_port:
            realm_id, service = self.last_knock(ip), 3724
            if not realm_id:
                self.metrics["refused_no_knock"] += 1
                conn.close()
                return
        else:
            owner = self.port_owner.get(port)
            if not owner:
                conn.close()
                return
            realm_id, service = owner
        s, err = self.admit(realm_id, ip)
        if not err and service == 3724 and self.auth_locked(ip, realm_id):
            s, err = None, (429, "too many wrong passwords")
        if err:
            self.metrics[f"refused_{err[0]}"] += 1
            log.info("tcp refused realm=%s port=%d ip=%s why=%s", realm_id, port, self.iphash(ip), err[1])
            conn.close()
            return
        self.ip_streams_inc(ip, realm_id)
        st = s.open_stream(service, conn, ip)
        self.metrics["streams_opened"] += 1
        await self.pump(s, st)

    # ---------------------------------------------------------------- agent side
    async def agent_session(self, sock: ws.WebSocket, agent_ip):
        challenge = secrets.token_hex(16)
        sock.send_nowait(json.dumps({"challenge": challenge, "relay": self.cfg.name, "v": 1}))
        try:
            op, msg = await asyncio.wait_for(sock.recv(), self.cfg.hello_timeout)
            doc = json.loads(msg) if op == ws.OP_TEXT else None
        except (asyncio.TimeoutError, ws.WSClosed, ValueError):
            sock.abort()
            return
        err, hello = self.check_hello(doc, challenge)
        if not err:
            rid = hello["realm_id"]
            if (rid not in self.state["realms"] and not self.reg_rate.hit(agent_ip, self.cfg.new_realms_per_ip_hour)):
                err = ("too many new realms from this address; try again in an hour", 3600)
            elif rid not in self.state["realms"] and len(self.state["realms"]) >= self.cfg.max_realms:
                err = ("this relay is full", 3600)
        alloc = None
        if not err:
            alloc = self.allocate(hello["realm_id"], hello["name"])
            if not alloc:
                err = ("this relay has no free ports", 3600)
            elif not (await self.ensure_listener(alloc["auth"]) and await self.ensure_listener(alloc["world"])):
                err = ("relay could not open the realm's ports", 300)
        if err:
            log.info("agent refused ip=%s why=%s", self.iphash(agent_ip), err[0])
            try:
                await sock.send(json.dumps({"error": err[0], "retry": err[1]}))
            except (ws.WSClosed, OSError):
                pass
            await sock.close(4003)
            return
        rid = hello["realm_id"]
        old = self.sessions.get(rid)
        if old:
            old.shutdown("replaced by a new connection")
        s = Session(self, sock, rid, hello, alloc, agent_ip)
        self.sessions[rid] = s
        self.remember_pair(s)
        self.metrics["agent_logins"] += 1
        welcome = {"realm_id": rid, "address": self.cfg.name,
                   "auth_port": self.bound_port(alloc["auth"]) or alloc["auth"],
                   "world_port": self.bound_port(alloc["world"]) or alloc["world"],
                   "shared_auth_port": self.cfg.shared_auth_port or None,
                   "limits": {"max_streams": self.cfg.max_streams, "kbps": self.cfg.kbps,
                              "daily_gb": self.cfg.daily_gb, "stream_idle_secs": self.cfg.stream_idle,
                              "ping_secs": 20, "ctrl_idle_secs": self.cfg.ctrl_idle},
                   "visibility": s.visibility,
                   "join_url": f"{self.cfg.join_base}/join/{rid}",
                   "status_url": f"https://{self.cfg.name}/r/{rid}/status.json"}
        sock.send_nowait(json.dumps({"welcome": welcome}))
        log.info("realm online realm=%s name=%r vis=%s ports=%d/%d", rid, s.name, s.visibility,
                 welcome["auth_port"], welcome["world_port"])
        try:
            await self.agent_loop(s)
        finally:
            s.shutdown("tunnel closed")
            if self.sessions.get(rid) is s:
                del self.sessions[rid]
                self.state["realms"][rid]["last"] = int(time.time())
                self.dirty = True

    def check_hello(self, doc, challenge):
        """(error or None, hello). error = (text, retry seconds)."""
        if not isinstance(doc, dict) or not isinstance(doc.get("hello"), dict):
            return ("expected a hello", 60), None
        h = doc["hello"]
        try:
            pub = bytes.fromhex(h.get("pubkey", ""))
        except ValueError:
            return ("bad public key", 3600), None
        if h.get("challenge") != challenge or h.get("relay") != self.cfg.name:
            return ("hello does not answer this challenge", 60), None
        if len(pub) != 32 or keys.realm_id(pub) != h.get("realm_id"):
            return ("realm id does not match the key", 3600), None
        if not keys.verify_doc(pub, h, keys.CTX_RELAY_LOGIN, doc.get("sig", "")):
            return ("bad signature", 3600), None
        if not isinstance(h.get("name"), str) or not NAME_RE.match(h["name"]):
            return ("realm name: 1-32 letters, digits, spaces, _ ' -", 3600), None
        if h.get("visibility") not in VISIBILITIES:
            return ("visibility must be public or private", 3600), None
        inv = h.get("invite_sha256")
        if inv is not None and not (isinstance(inv, str) and HEX64_RE.match(inv)):
            return ("bad invite hash", 3600), None
        hs = h.get("host_sha256")
        if hs is not None and not (isinstance(hs, str) and HEX64_RE.match(hs)):
            return ("bad host hash", 3600), None
        ps = h.get("pair_sha256")
        if ps is not None and not (isinstance(ps, str) and HEX64_RE.match(ps)):
            return ("bad pair hash", 3600), None
        if h["visibility"] == "private" and not inv:
            return ("a private realm needs an invite secret", 3600), None
        if h.get("signup", "invite") not in SIGNUPS:
            return ("signup must be invite, open or off", 3600), None
        if h["realm_id"] in self.blocked:
            return ("this realm is blocked on this relay", 86400), None
        if self.allow is not None and h["realm_id"] not in self.allow:
            return ("this relay only takes listed realms", 3600), None
        return None, h

    async def agent_loop(self, s: Session):
        while not s.closed:
            try:
                op, msg = await s.ws.recv()
            except ws.WSClosed:
                return
            s.last_frame = time.monotonic()
            if op == ws.OP_BIN:
                try:
                    kind, sid, payload = mux.unpack(msg)
                except ValueError:
                    continue
                st = s.streams.get(sid)
                if kind == DATA and st and st.port == 3724 and st.auth_seen < 2:
                    self.watch_logon(st, payload)
                if kind == DATA and st:
                    st.last = time.monotonic()
                    st.bytes += len(payload)
                    self.count_bytes(s, len(payload))
                    if not st.conn.write(payload):
                        s.close_stream(st, why="player too slow (buffer full)")
                    d = s.bucket.delay_for(len(payload))
                    if d > 0:
                        await asyncio.sleep(d)
                    if self.over_quota(s.realm_id):
                        for x in list(s.streams.values()):
                            s.close_stream(x, why="daily traffic cap")
                elif kind == CLOSE and st:
                    s.close_stream(st, tell_agent=False)
                continue
            try:
                doc = json.loads(msg)
            except ValueError:
                continue
            if not isinstance(doc, dict):
                continue
            if "ping" in doc:
                s.ws.send_nowait(json.dumps({"pong": doc["ping"]}))
            elif "res" in doc:
                fut = s.pending.get(doc["res"])
                if fut and not fut.done():
                    fut.set_result(doc)
            elif isinstance(doc.get("update"), dict):
                self.apply_update(s, doc["update"])

    def apply_update(self, s, u):
        if u.get("visibility") in VISIBILITIES:
            inv = u.get("invite_sha256", s.invite_sha)
            if u["visibility"] == "private" and not inv:
                return
            s.visibility = u["visibility"]
        if "invite_sha256" in u and (u["invite_sha256"] is None or HEX64_RE.match(str(u["invite_sha256"]))):
            s.invite_sha = (u["invite_sha256"] or "").lower() or None
        if u.get("signup") in SIGNUPS:
            s.signup = u["signup"]
        if isinstance(u.get("host_sha256"), str) and HEX64_RE.match(u["host_sha256"]):
            s.host_sha = u["host_sha256"].lower()
        if isinstance(u.get("pair_sha256"), str) and HEX64_RE.match(u["pair_sha256"]):
            s.pair_sha = u["pair_sha256"].lower()
            self.remember_pair(s)
        if isinstance(u.get("name"), str) and NAME_RE.match(u["name"]):
            s.name = u["name"]
        if s.visibility == "private" and self.listing:
            self.listing.delist(s.realm_id)   # gone from the public list at once, not after 24 h
        log.info("realm updated realm=%s vis=%s", s.realm_id, s.visibility)

    # ---------------------------------------------------------------- HTTP
    def client_ip(self, req):
        if self.cfg.trust_proxy and self.cfg.is_trusted_proxy(req.peer) and req.headers.get("x-forwarded-for"):
            return req.headers["x-forwarded-for"].split(",")[-1].strip()
        return req.peer

    def cors(self, req, public=False):
        origin = req.headers.get("origin", "")
        if public:
            return {"Access-Control-Allow-Origin": "*"}
        if origin in self.cfg.site_origins:
            return {"Access-Control-Allow-Origin": origin, "Vary": "Origin",
                    "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
                    "Access-Control-Allow-Headers": "Content-Type"}
        return {}

    async def on_http(self, reader, writer):
        peer = (writer.get_extra_info("peername") or ("?",))[0]
        try:
            req = await httpd.read_request(reader, peer)
        except (httpd.BadRequest, asyncio.TimeoutError, asyncio.IncompleteReadError, ConnectionError) as e:
            if isinstance(e, httpd.BadRequest):
                writer.write(httpd.response(e.status, {"error": str(e)}))
            writer.close()
            return
        req.ip = self.client_ip(req)
        try:
            out = await self.route(req, reader, writer)
        except httpd.BadRequest as e:
            out = httpd.response(e.status, {"error": str(e)}, headers=self.cors(req))
        except Exception:  # never let one request take the relay down
            log.exception("request failed: %s %s", req.method, req.path)
            out = httpd.response(500, {"error": "internal error"})
        if out is None:  # upgraded to a websocket; that handler owns the socket now
            return
        try:
            writer.write(out)
            await writer.drain()
        except (ConnectionError, OSError):
            pass
        writer.close()

    async def route(self, req, reader, writer):
        p, m = req.path, req.method
        if m == "OPTIONS":
            return httpd.response(204, b"", ctype="", headers=dict(self.cors(req) or self.cors(req, True),
                                  **{"Access-Control-Allow-Methods": "GET, POST, OPTIONS",
                                     "Access-Control-Allow-Headers": "Content-Type"}))
        if p == "/healthz":
            return httpd.response(200, "ok\n", "text/plain")
        if p == "/metrics":
            return httpd.response(200, self.metrics_text(), "text/plain; version=0.0.4")
        if p == "/agent" and m == "GET":
            try:
                sock = await ws.server_upgrade(req, reader, writer, max_message=mux.MAX_CHUNK + 64)
            except ws.HandshakeError as e:
                return httpd.response(e.status, {"error": str(e)})
            await self.agent_session(sock, req.ip)
            return None
        parts = [x for x in p.split("/") if x]
        if len(parts) >= 4 and parts[0] == "r" and SID_RE.match(parts[1]) and parts[-2] == "ws" and m == "GET":
            invite = req.query.get("invite")
            if len(parts) == 6 and parts[2] == "i":
                invite = parts[3]
            elif len(parts) != 4:
                return httpd.response(404, {"error": "not found"})
            return await self.player_ws(req, reader, writer, parts[1], parts[-1], invite)
        if len(parts) == 3 and parts[0] == "ws" and SID_RE.match(parts[1]) and m == "GET":
            service = {"auth": 3724, "world": 8085}.get(parts[2])
            if not service:
                return httpd.response(404, {"error": "only /ws/<realm>/auth and /ws/<realm>/world"})
            return await self.player_ws(req, reader, writer, parts[1], str(service), req.query.get("invite"))
        if len(parts) == 3 and parts[0] == "r" and SID_RE.match(parts[1]) and parts[2] == "status.json":
            return await self.status(req, parts[1])
        if len(parts) == 2 and parts[0] == "join" and SID_RE.match(parts[1]):
            return self.join_page()
        if len(parts) >= 3 and parts[:2] == ["api", "realms"] and SID_RE.match(parts[2]):
            rid = parts[2]
            if len(parts) == 3 and m == "GET":
                return self.realm_info(req, rid)
            if len(parts) == 4 and parts[3] == "knock" and m == "POST":
                return self.api_knock(req, rid)
            if len(parts) == 4 and parts[3] == "accounts" and m == "POST":
                return await self.api_account(req, rid)
        if len(parts) == 3 and parts[:2] == ["api", "pair"] and HEX64_RE.match(parts[2]) and m == "GET":
            return self.api_pair(req, parts[2])
        if parts[:2] == ["api", "listing"] and self.listing:
            return await self.listing.route(req, parts[2:])
        if parts[:2] == ["api", "mesh"] and self.mesh:
            return await self.mesh.route(req, parts[2:])
        return httpd.response(404, {"error": "not found"})

    async def player_ws(self, req, reader, writer, rid, port_s, invite):
        if not port_s.isdigit():
            return httpd.response(404, {"error": "not found"})
        port = int(port_s)
        alloc = self.state["realms"].get(rid)
        if port in mux.PORTS:
            service = port
        elif alloc and port == alloc["auth"]:
            service = 3724
        elif alloc and port == alloc["world"]:
            service = 8085
        else:
            return httpd.response(404, {"error": "only the realm's auth and world ports"})
        if not self.ws_origin_ok(req):
            self.metrics["refused_ws_origin"] += 1
            return httpd.response(403, {"error": "this page may not connect to Leyline realms"})
        if not self.ws_rate.hit(req.ip, self.cfg.ws_rate_per_ip):
            self.metrics["refused_429"] += 1
            return httpd.response(429, {"error": "connecting too fast"})
        if self.ws_open >= self.cfg.max_ws_total:
            self.metrics["refused_503"] += 1
            return httpd.response(503, {"error": "the relay is full right now"})
        s, err = self.admit(rid, req.ip, invite)
        if not err and service == 3724 and self.auth_locked(req.ip, rid):
            s, err = None, (429, f"too many wrong passwords from your address: try again in {self.cfg.auth_fail_window // 60} minutes")
        if err:
            self.metrics[f"refused_{err[0]}"] += 1
            return httpd.response(err[0], {"error": err[1]})
        try:
            sock = await ws.server_upgrade(req, reader, writer, max_message=mux.MAX_CHUNK * 2)
        except ws.HandshakeError as e:
            return httpd.response(e.status, {"error": str(e)})
        if s.closed or self.sessions.get(rid) is not s:   # the realm went away during the handshake
            sock.abort()
            return None
        if invite and self.invite_ok(s, invite):
            self.knock(req.ip, rid)
        self.ip_streams_inc(req.ip, rid)
        self.ws_open += 1
        st = s.open_stream(service, WsConn(sock), req.ip)
        self.metrics["streams_opened"] += 1
        await self.pump(s, st)
        return None

    def join_page(self):
        """/join/<id>: the join page. The browser game may frame it (?hop=1, the first hop to a realm), so it is
        served cross-origin-isolation friendly (COEP + CORP) and only the play origins may frame it; the page
        hands a login back only to an origin in data-hop-origins."""
        with open(os.path.join(HERE, "www", "join.html"), "rb") as f:
            page = f.read()
        origins = [o for o in self.cfg.play_origins if re.match(r"^https?://[A-Za-z0-9.:-]+$", o)]
        page = page.replace(b'data-hop-origins=""', b'data-hop-origins="' + " ".join(origins).encode() + b'"', 1)
        return httpd.response(200, page, "text/html; charset=utf-8",
                              {"Cache-Control": "no-cache", "Referrer-Policy": "no-referrer",
                               "Content-Security-Policy": "frame-ancestors " + (" ".join(origins) or "'none'"),
                               "Cross-Origin-Embedder-Policy": "require-corp",
                               "Cross-Origin-Resource-Policy": "cross-origin"})

    def realm_info(self, req, rid):
        s = self.sessions.get(rid)
        alloc = self.state["realms"].get(rid)
        if not alloc:
            return httpd.response(404, {"error": "unknown realm"}, headers=self.cors(req, True))
        doc = {"realm_id": rid, "online": bool(s), "name": s.name if s else alloc.get("name"),
               "visibility": s.visibility if s else None, "signup": s.signup if s else None,
               "address": self.cfg.name, "auth_port": alloc["auth"], "world_port": alloc["world"],
               "shared_auth_port": self.cfg.shared_auth_port or None,
               "status_url": f"https://{self.cfg.name}/r/{rid}/status.json"}
        return httpd.response(200, doc, headers=self.cors(req, True))

    def api_knock(self, req, rid):
        h = self.cors(req)
        if not self.knock_rate.hit(req.ip, self.cfg.knocks_per_ip_min):
            return httpd.response(429, {"error": "slow down"}, headers=h)
        doc = req.json()
        s = self.sessions.get(rid)
        if not s:
            return httpd.response(404, {"error": "realm offline"}, headers=h)
        if s.visibility == "private" and not self.invite_ok(s, doc.get("invite")):
            return httpd.response(403, {"error": "this invite link is not valid (the host may have made a new one)"},
                                  headers=h)
        self.knock(req.ip, rid)
        self.metrics["knocks"] += 1
        alloc = s.alloc
        return httpd.response(200, {"ok": True, "name": s.name, "visibility": s.visibility,
                                    "realmlist": self.cfg.name if self.cfg.shared_auth_port == 3724
                                    else f"{self.cfg.name}:{alloc['auth']}",
                                    "realmlist_port": f"{self.cfg.name}:{alloc['auth']}",
                                    "signup": s.signup, "valid_hours": self.cfg.knock_ttl // 3600}, headers=h)

    async def api_account(self, req, rid):
        h = self.cors(req)
        doc = req.json()
        s = self.sessions.get(rid)
        if not s:
            return httpd.response(404, {"error": "realm offline"}, headers=h)
        invited = self.invite_ok(s, doc.get("invite"))
        hk = doc.get("host")
        is_host = bool(isinstance(hk, str) and hk and s.host_sha
                       and hmac.compare_digest(hashlib.sha256(hk.encode()).hexdigest(), s.host_sha))
        if s.signup == "off" or (s.signup == "invite" and not invited) or (s.visibility == "private" and not invited):
            return httpd.response(403, {"error": "this realm makes accounts only from its invite link"
                                        if s.signup != "off" else "the host makes accounts on this realm"}, headers=h)
        user, salt, ver = doc.get("username", ""), doc.get("salt", ""), doc.get("verifier", "")
        if not (isinstance(user, str) and USER_RE.match(user) and isinstance(salt, str) and HEX64_RE.match(salt)
                and isinstance(ver, str) and HEX64_RE.match(ver)):
            return httpd.response(400, {"error": "account name: 3-16 letters or digits"}, headers=h)
        if not self.acct_ip.hit(req.ip, self.cfg.accounts_per_ip_hour):
            return httpd.response(429, {"error": "too many new accounts from your address; try later"}, headers=h)
        if not self.acct_realm.hit(rid, self.cfg.accounts_per_realm_day):
            return httpd.response(429, {"error": "this realm made enough accounts today"}, headers=h)
        try:
            res = await s.request("create_account", username=user.upper(), salt=salt.lower(), verifier=ver.lower(),
                                  host=is_host)
        except (asyncio.TimeoutError, ConnectionError, ws.WSClosed):
            return httpd.response(504, {"error": "the realm did not answer"}, headers=h)
        if res.get("error") == "reserved":
            return httpd.response(403, {"error": "that account name is kept for the realm's host"}, headers=h)
        if not res.get("ok"):
            return httpd.response(409 if res.get("error") == "taken" else 502,
                                  {"error": "that account name is taken" if res.get("error") == "taken"
                                   else "the realm could not make the account"}, headers=h)
        self.knock(req.ip, rid)
        self.metrics["accounts_created"] += 1
        return httpd.response(201, {"ok": True, "username": user.upper()}, headers=h)

    async def status(self, req, rid):
        h = dict(self.cors(req, True), **{"Cache-Control": f"public, max-age={self.cfg.status_ttl}"})
        s = self.sessions.get(rid)
        base = {"online": False, "players": None, "bots": None, "uptime_s": None, "build": "3.3.5a",
                "realm_id": rid, "relay": True,
                "updated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
        if not s:
            if rid not in self.state["realms"]:
                return httpd.response(404, {"error": "unknown realm"}, headers=h)
            return httpd.response(200, base, headers=h)
        at, cached = s.status_cache
        if cached and time.monotonic() - at < self.cfg.status_ttl:
            return httpd.response(200, cached, headers=h)
        try:
            res = await s.request("status")
            doc = dict(base, **{k: v for k, v in (res.get("status") or {}).items()
                                if k in ("online", "players", "bots", "uptime_s", "realm", "queue",
                                         "bots_method", "claim", "profile")})
        except (asyncio.TimeoutError, ConnectionError, ws.WSClosed):
            doc = dict(base, online=True)  # the tunnel is up but the realm did not answer in time
        doc["realm"] = s.name
        s.status_cache = (time.monotonic(), doc)
        return httpd.response(200, doc, headers=h)

    def metrics_text(self):
        lines = [f"wu_relay_realms_online {len(self.sessions)}",
                 f"wu_relay_realms_known {len(self.state['realms'])}",
                 f"wu_relay_streams_open {self.streams_total()}",
                 f"wu_relay_ws_streams_open {self.ws_open}"]
        for k, v in sorted(self.metrics.items()):
            lines.append(f"wu_relay_{k}_total {v}")
        return "\n".join(lines) + "\n"

    # ---------------------------------------------------------------- housekeeping
    def _spawn(self, coro):
        t = asyncio.ensure_future(coro)
        self.tasks.add(t)
        t.add_done_callback(self.tasks.discard)
        return t

    async def sweeper(self, every=5):
        n = 0
        while True:
            await asyncio.sleep(every)
            now = time.monotonic()
            for s in list(self.sessions.values()):
                if now - s.last_frame > self.cfg.ctrl_idle:
                    s.shutdown("agent silent")
                    continue
                for st in list(s.streams.values()):
                    if now - st.last > self.cfg.stream_idle:
                        s.close_stream(st, why="idle")
                if self.listing and now - s.rtt_at > (60 if not s.rtt_samples else 1800):
                    self._spawn(s.probe_rtt())
            for ip in [ip for ip, t in self.knocks.items() if all(e <= now for e in t.values())]:
                del self.knocks[ip]
            for k in [k for k, q in self.auth_fails.items() if not q or now - q[-1] > self.cfg.auth_fail_window]:
                del self.auth_fails[k]
            n += 1
            if self.mesh and n % max(1, self.cfg.mesh_every // max(1, every)) == 0:
                self._spawn(self.mesh.gossip_round())
            if n % 12 == 0:
                self.load_blocklist()
                for w in (self.conn_rate, self.ws_rate, self.reg_rate, self.acct_ip, self.acct_realm, self.knock_rate,
                          self.pair_rate):
                    w.sweep()
                self.save()
                if self.listing:
                    self.listing.save()

    async def start(self):
        host, port = self.cfg.http_bind.rsplit(":", 1)
        self.http_server = await asyncio.start_server(lambda r, w: self._spawn(self.on_http(r, w)),
                                                      host, int(port), limit=1 << 16)
        if self.cfg.shared_auth_port:
            await self.ensure_listener(self.cfg.shared_auth_port)
        self.load_blocklist()
        self._spawn(self.sweeper())
        if self.mesh:
            self._spawn(self.mesh.bootstrap_once())
        return self

    def http_port(self):
        return self.http_server.sockets[0].getsockname()[1]

    async def stop(self):
        if self.http_server:
            self.http_server.close()
        for srv in self.listeners.values():
            srv.close()
        for s in list(self.sessions.values()):
            try:
                s.ws.send_nowait(json.dumps({"bye": "relay restarting", "retry": 5}))
            except ws.WSClosed:
                pass
            s.shutdown("relay stopping")
        for t in list(self.tasks):
            t.cancel()
        self.save()
        if self.listing:
            self.listing.save()


async def amain():
    logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"),
                        format='{"t":"%(asctime)s","lvl":"%(levelname)s","msg":"%(message)s"}')
    relay = await Relay().start()
    log.info("wu-relay listening http=%s game=%s shared_auth=%s ports=%d-%d", relay.cfg.http_bind,
             relay.cfg.game_bind, relay.cfg.shared_auth_port, relay.cfg.port_min, relay.cfg.port_max)
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            loop.add_signal_handler(sig, stop.set)
        except NotImplementedError:
            pass
    await stop.wait()
    log.info("shutting down")
    await relay.stop()


def main():
    try:
        asyncio.run(amain())
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
