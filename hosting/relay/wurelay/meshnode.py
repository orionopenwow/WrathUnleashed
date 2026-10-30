"""The relay as one node of the Leyline mesh (docs/LEYLINE-MESH.md). Off unless RELAY_MESH=1.

What it does:
  * keeps a wunet.mesh.Store of signed records (realms, relays, staff blocks), merged by the rules in wunet/mesh.py;
  * publishes its own relay record (signed with its node key, RELAY_NODE_KEY) and, for every public realm whose
    heartbeat its listing accepted, a realm record: the realm's own signed beat plus this relay's signed endpoint
    (relay host, the realm's auth/world ports, whether the browser bridge is served);
  * gossips: every RELAY_MESH_EVERY seconds it pushes what is new to RELAY_MESH_FANOUT random peers, and every 6th
    round it compares bucket summaries with one random peer and pulls the buckets that differ (anti-entropy);
  * finds peers from the bootstrap list (RELAY_MESH_BOOTSTRAP), its peers cache (mesh-peers.json next to the state
    file) and the relay records it learns (any node with "mesh": true);
  * serves, under /api/mesh/: node, peers, summary, records (?since=<cursor>&epoch= or ?buckets=0a,ff), snapshot,
    realms.json (the same shape as /api/listing/realms.json, built only from verified records), and push (POST).

Today's listing API is untouched: /api/listing/realms.json still lists only the realms with a tunnel to this relay.
"""
from __future__ import annotations

import asyncio
import collections
import json
import logging
import os
import random
import secrets
import time
import urllib.error
import urllib.request

from wunet import keys, mesh

from . import httpd, listing

log = logging.getLogger("wu-relay.mesh")
PUSH_BYTES = 14_000          # under httpd.MAX_BODY
PEERS_MAX = 64
PUSH_PER_IP_MIN = 120        # records a single address may push per minute
UA = "wu-relay-mesh/1"


def _http(method, url, body=None, timeout=5.0):
    """(status, JSON or None). Blocking: called in a thread."""
    data = None if body is None else json.dumps(body, separators=(",", ":")).encode()
    req = urllib.request.Request(url, data=data, method=method,
                                 headers={"User-Agent": UA, "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read(8 << 20)
            return r.status, json.loads(raw.decode("utf-8") or "null")
    except urllib.error.HTTPError as e:
        return e.code, None
    except (OSError, ValueError):
        return 0, None


def batches(recs, limit=PUSH_BYTES):
    out, cur, n = [], [], 2
    for r in recs:
        s = mesh.size(r) + 1
        if s > limit:
            continue
        if cur and n + s > limit:
            out.append(cur)
            cur, n = [], 2
        cur.append(r)
        n += s
    if cur:
        out.append(cur)
    return out


class MeshNode:
    def __init__(self, cfg, relay=None, fetch=None, clock=time.time):
        self.cfg, self.relay, self.clock = cfg, relay, clock
        self.fetch = fetch or _http
        self.store = mesh.Store()
        state_dir = os.path.dirname(os.path.abspath(cfg.state_file))
        self.secret = keys.load_or_create(getattr(cfg, "mesh_node_key", "") or os.path.join(state_dir, "node.key"))
        self.pub = keys.public_key(self.secret).hex()
        self.id = mesh.node_id(self.pub)
        self.http_base = (getattr(cfg, "mesh_public_http", "") or f"https://{cfg.name}").rstrip("/")
        self.peers_file = os.path.join(state_dir, "mesh-peers.json")
        self.bootstrap = [u.strip().rstrip("/") for u in (getattr(cfg, "mesh_bootstrap", "") or "").split(",")
                          if u.strip() and u.strip().rstrip("/") != self.http_base]
        self.peers: dict[str, dict] = {}
        for u in self.bootstrap + self._load_peers():
            self.peers.setdefault(u, {"fails": 0, "cursor": 0, "epoch": None})
        self.seq = int(self.clock() * 1000)
        self.epoch = secrets.token_hex(4)
        self.fresh: list[dict] = []
        self.published: dict[str, tuple] = {}
        self.rounds = 0
        self.push_rate = collections.defaultdict(collections.deque)
        self.metrics = collections.Counter()
        self.publish_self()

    # ---------------------------------------------------------------- peers
    def _load_peers(self):
        try:
            with open(self.peers_file, encoding="utf-8") as f:
                v = json.load(f)
            return [u for u in v.get("peers", []) if isinstance(u, str) and u.startswith(("https://", "http://"))][:PEERS_MAX]
        except (OSError, ValueError, AttributeError):
            return []

    def save_peers(self):
        good = sorted(u for u, p in self.peers.items() if p["fails"] < 3)[:PEERS_MAX]
        try:
            tmp = self.peers_file + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump({"peers": good}, f)
            os.replace(tmp, self.peers_file)
        except OSError:
            pass

    def learn_peers(self):
        for r in self.store.relays():
            n = r["node"]
            if n.get("mesh") and n["http"] != self.http_base and n["pubkey"] != self.pub:
                self.peers.setdefault(n["http"], {"fails": 0, "cursor": 0, "epoch": None})
        if len(self.peers) > PEERS_MAX:
            # keep the bootstrap list, then the healthiest
            extra = sorted((p["fails"], u) for u, p in self.peers.items() if u not in self.bootstrap)
            for _, u in extra[PEERS_MAX - len(self.bootstrap):]:
                del self.peers[u]

    def pick(self, k):
        live = [u for u, p in self.peers.items() if p["fails"] < 5]
        random.shuffle(live)
        return live[:k]

    # ---------------------------------------------------------------- publishing
    def load(self):
        if self.relay is None:
            return {"realms": 0, "streams": 0}
        return {"realms": len(self.relay.sessions), "streams": self.relay.streams_total()}

    def caps(self):
        c = self.cfg
        return {"realms": int(getattr(c, "max_realms", 0) or 0), "streams": int(getattr(c, "max_streams_total", 0) or 0),
                "kbps": int(getattr(c, "kbps", 0) or 0)}

    def publish_self(self, now=None):
        now = int(self.clock() if now is None else now)
        self.seq = max(self.seq + 1, now * 1000)
        rec = mesh.relay_record(self.secret, self.cfg.name, self.seq, now, http=self.http_base,
                                region=getattr(self.cfg, "region", "") or "",
                                volunteer=bool(getattr(self.cfg, "volunteer", False)), ws=True, mesh=True,
                                caps=self.caps(), load=self.load())
        self.accept([rec], now, local=True)
        return rec

    def local_beat(self, beat: dict, sig: str, now=None):
        """The listing took this signed beat from a realm with a tunnel here: publish it with our endpoint, when it
        changed in a way the list shows, or every mesh.REFRESH seconds."""
        now = int(self.clock() if now is None else now)
        rid = beat.get("realm_id")
        alloc = self.relay.state["realms"].get(rid) if self.relay is not None else None
        if not alloc:
            return None
        st = beat.get("status") if isinstance(beat.get("status"), dict) else {}
        players = st.get("players") if isinstance(st.get("players"), int) else 0
        key = (keys.canonical(beat.get("record")), bool(st.get("online")), min(players, 1000) // 5,
               keys.canonical(sorted(mesh.signed_relays(beat))))
        last = self.published.get(rid)
        if last and last[1] == key and now - last[0] < mesh.REFRESH:
            return None
        ep = mesh.endpoint(self.secret, rid, self.cfg.name, alloc["auth"], alloc["world"], True, now)
        rec = mesh.realm_record(beat, sig, [ep])
        ok, why = self.accept([rec], now, local=True)
        if ok:
            self.published[rid] = (now, key)
        else:
            log.info("mesh did not take the beat of %s: %s", rid, why)
        return rec

    def forget_realm(self, rid):
        self.published.pop(rid, None)

    # ---------------------------------------------------------------- merging
    def accept(self, recs, now=None, local=False):
        """Offer records to the store. Returns (any accepted, the last reason)."""
        now = self.clock() if now is None else now
        any_ok, why = False, "empty"
        for r in recs if isinstance(recs, list) else []:
            ok, why = self.store.offer(r, now)
            if ok:
                any_ok = True
                self.fresh.append(self.store.recs[self.store.last_id])
                self.metrics["accepted_local" if local else "accepted"] += 1
            elif why.startswith("refused"):
                self.metrics["refused"] += 1
        return any_ok, why

    # ---------------------------------------------------------------- gossip
    async def call(self, method, url, body=None):
        return await asyncio.to_thread(self.fetch, method, url, body)

    async def gossip_round(self, now=None):
        now = self.clock() if now is None else now
        self.rounds += 1
        if self.rounds % 30 == 1:
            self.publish_self(now)
        self.store.sweep(now)
        self.learn_peers()
        fresh, self.fresh = self.fresh, []
        fanout = int(getattr(self.cfg, "mesh_fanout", 3) or 3)
        targets = self.pick(fanout)
        if fresh and targets:
            for b in batches(fresh):
                await asyncio.gather(*(self.push(u, b) for u in targets))
        if self.rounds % 6 == 1 or not fresh:
            for u in self.pick(1):
                await self.pull(u, now)
        if self.rounds % 30 == 1:
            self.save_peers()

    async def push(self, base, recs):
        st, _ = await self.call("POST", base + "/api/mesh/push", {"records": recs, "from": self.http_base})
        self.metrics["push_sent"] += 1
        self._mark(base, st == 200)

    def _mark(self, base, ok):
        p = self.peers.get(base)
        if p is not None:
            p["fails"] = 0 if ok else p["fails"] + 1

    async def pull(self, base, now=None):
        """Anti-entropy with one peer: its changes since our cursor, or the buckets whose summary differs."""
        now = self.clock() if now is None else now
        p = self.peers.setdefault(base, {"fails": 0, "cursor": 0, "epoch": None})
        st, doc = await self.call("GET", f"{base}/api/mesh/records?since={p['cursor']}&epoch={p['epoch'] or ''}")
        self.metrics["pull_sent"] += 1
        if st != 200 or not isinstance(doc, dict):
            self._mark(base, False)
            return 0
        self._mark(base, True)
        if doc.get("epoch") != p["epoch"]:
            p["cursor"] = 0           # the peer restarted: its cursors mean nothing now
            p["epoch"] = doc.get("epoch")
        before = self.store.stats["accepted"]
        self.accept(doc.get("records") or [], now)
        if isinstance(doc.get("cursor"), int):
            p["cursor"] = doc["cursor"]
        if doc.get("more"):
            p["cursor"] = doc["cursor"]
        return self.store.stats["accepted"] - before

    async def sync_buckets(self, base, now=None):
        """The full comparison (used when a cursor can't be trusted): summary, then the differing buckets."""
        now = self.clock() if now is None else now
        st, doc = await self.call("GET", f"{base}/api/mesh/summary")
        if st != 200 or not isinstance(doc, dict) or not isinstance(doc.get("buckets"), list):
            return 0
        mine = self.store.summary()
        diff = [i for i, (a, b) in enumerate(zip(mine, doc["buckets"])) if a != b]
        if not diff:
            return 0
        got = 0
        for i in range(0, len(diff), 32):
            q = ",".join(f"{x:02x}" for x in diff[i:i + 32])
            st, d = await self.call("GET", f"{base}/api/mesh/records?buckets={q}")
            if st == 200 and isinstance(d, dict):
                before = self.store.stats["accepted"]
                self.accept(d.get("records") or [], now)
                got += self.store.stats["accepted"] - before
        return got

    async def bootstrap_once(self, now=None):
        """First contact: pull everything from up to 3 peers (bootstrap list first)."""
        for u in (self.bootstrap + self.pick(3))[:3]:
            await self.pull(u, now)
        self.learn_peers()

    # ---------------------------------------------------------------- serving
    def endpoint_relays(self):
        return {r["node"]["host"]: r["node"] for r in self.store.relays()}

    def realms_json(self, now=None):
        """Today's realms.json shape, from verified records only: every realm the mesh knows, each through its
        own relay's endpoint when there is one (else the least loaded seed/volunteer endpoint)."""
        now = self.clock() if now is None else now
        relays = self.endpoint_relays()
        seeds = {h for h, n in relays.items() if not n.get("volunteer")}
        out = []
        for r in self.store.realms():
            ep = mesh.choose_endpoint(r, relays, {}, volunteers=False, seeds=seeds) or \
                mesh.choose_endpoint(r, relays, {}, volunteers=True, seeds=seeds)
            out.append(record_view(r, ep, now))
        out.sort(key=lambda x: (x["state"] != "live", -x["community"]["score"], x["name"].lower(), x["community"]["realmId"]))
        live = [x for x in out if x["state"] == "live"]
        return {"schema": 1, "kind": "community", "source": "mesh",
                "updated": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now)),
                "network": {"realms": len(live), "players": sum(x["community"]["lastHeartbeat"].get("players") or 0 for x in live),
                            "bots": sum(x["community"]["lastHeartbeat"].get("bots") or 0 for x in live)},
                "realms": out}

    def push_ok(self, ip, n, now):
        q = self.push_rate[ip]
        while q and now - q[0] > 60:
            q.popleft()
        if len(q) + n > PUSH_PER_IP_MIN:
            return False
        q.extend([now] * n)
        return True

    async def route(self, req, rest):
        pub = {"Access-Control-Allow-Origin": "*"}
        now = self.clock()
        if rest == ["node"] and req.method == "GET":
            mine = self.store.recs.get(self.id) or self.publish_self(now)
            return httpd.response(200, {"node": mine, "epoch": self.epoch}, headers=pub)
        if rest == ["peers"] and req.method == "GET":
            rel = self.store.relays()
            random.shuffle(rel)
            return httpd.response(200, {"relays": rel[:32]}, headers=pub)
        if rest == ["summary"] and req.method == "GET":
            return httpd.response(200, {"buckets": self.store.summary(), "epoch": self.epoch,
                                        "records": len(self.store.recs)}, headers=pub)
        if rest == ["records"] and req.method == "GET":
            if "buckets" in req.query:
                try:
                    want = {int(x, 16) for x in req.query["buckets"].split(",")[:64] if x}
                except ValueError:
                    return httpd.response(400, {"error": "buckets are hex numbers"})
                return httpd.response(200, {"records": self.store.in_buckets(want), "epoch": self.epoch}, headers=pub)
            try:
                since = int(req.query.get("since") or 0)
            except ValueError:
                since = 0
            if req.query.get("epoch") != self.epoch:
                since = 0
            recs, cur = self.store.since(since, 2000)
            return httpd.response(200, {"records": recs, "cursor": cur, "epoch": self.epoch,
                                        "more": cur < self.store.counter}, headers=pub)
        if rest == ["snapshot"] and req.method == "GET":
            self.store.sweep(now)
            return httpd.response(200, {"v": 1, "node": self.store.recs.get(self.id), "epoch": self.epoch,
                                        "records": list(self.store.recs.values())},
                                  headers=dict(pub, **{"Cache-Control": "public, max-age=30"}))
        if rest == ["realms.json"] and req.method == "GET":
            return httpd.response(200, self.realms_json(now), headers=dict(pub, **{"Cache-Control": "public, max-age=30"}))
        if rest == ["push"] and req.method == "POST":
            doc = req.json()
            recs = doc.get("records")
            if not isinstance(recs, list) or len(recs) > 200:
                return httpd.response(400, {"error": "expected {records: [...]}"})
            if not self.push_ok(req.ip, len(recs), now):
                return httpd.response(429, {"error": "too many records from this address"})
            self.accept(recs, now)
            frm = doc.get("from")
            if isinstance(frm, str) and frm.startswith("https://") and len(self.peers) < PEERS_MAX:
                # only remember a pusher that the mesh vouches for (a signed relay record with that http base)
                if any(r["node"]["http"] == frm for r in self.store.relays()):
                    self.peers.setdefault(frm, {"fails": 0, "cursor": 0, "epoch": None})
            return httpd.response(200, {"ok": True})
        return httpd.response(404, {"error": "not found"})


def record_view(r: dict, ep: dict | None, now: float) -> dict:
    """A verified realm record in the realms.json record shape (schema 1 + "community"), the way listing.py writes
    one: the host's text cleaned by listing.clean_record, the address from the chosen signed endpoint."""
    beat = r["beat"]
    rid = beat["realm_id"]
    rec = listing.clean_record(beat.get("record"))
    st = beat.get("status") if isinstance(beat.get("status"), dict) else {}

    def num(k):
        v = st.get(k)
        return v if isinstance(v, int) and not isinstance(v, bool) and 0 <= v < 1_000_000 else None
    a = (ep or {}).get("att") or {}
    relay = a.get("relay") or (beat.get("relay") if mesh.host_ok(beat.get("relay")) else None)
    online = bool(st.get("online")) and bool(a) and now - beat["ts"] <= listing.OFFLINE_AFTER + mesh.REFRESH
    version, game = listing.BUILDS.get(rec["build"], listing.BUILDS[12340])
    players, bots = num("players"), num("bots")
    return {
        "schema": 1, "slug": "c-" + rid, "name": rec["name"] or rid, "official": False,
        "state": "live" if online else "offline",
        "stateNote": None if online else "The host's realm is not running right now.",
        "order": 1000, "tagline": rec["tagline"], "summary": rec["summary"], "type": rec["type"],
        "profile": {"game": game, "version": version, "build": rec["build"], "core": rec["core"],
                    "address": relay, "port": a.get("auth_port"), "warden": rec["warden"], "ruleset": rec["ruleset"],
                    "patches": None, "clientFiles": "own"},
        "tags": rec["tags"], "region": rec["region"], "language": rec["language"], "maxPlayers": rec["max_players"],
        "connect": {"kind": "web-signin", "url": f"https://{relay}/join/{rid}" if relay else None,
                    "label": "Join this realm",
                    "note": "Opens the realm's join page: make a game account there, then set your realmlist."},
        "rules": rec["rules"], "features": [], "media": {"icon": None, "screenshots": [], "trailer": None},
        "discord": rec["discord"],
        "status": {"url": f"https://{relay}/r/{rid}/status.json" if relay else None, "format": "openvanilla-status-1"},
        "leaderboards": {"duels": None, "bossfights": None},
        "updated": time.strftime("%Y-%m-%d", time.gmtime(beat["ts"])),
        "community": {
            "realmId": rid, "relay": relay, "signed": True, "claimed": False, "claimedBy": None,
            "lastSeen": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(beat["ts"])),
            "lastHeartbeat": {"online": bool(st.get("online")), "players": players, "bots": bots, "uptime_s": num("uptime_s")},
            "uptime": {"h24": None, "d7": None}, "new": False,
            "score": listing.score(online, players, bots, None, None, False),
            "regionEstimate": None, "latency": None,
            "directConnect": False,
            "endpoints": len(r.get("endpoints") or []),
            "browser": bool(a.get("ws")),
        },
    }
