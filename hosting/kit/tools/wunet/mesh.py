"""Leyline mesh records: the signed facts the realm list is made of, and the rules for merging them.

No node can forge a record or keep a dead realm alive: every record is signed by the key it is about, and every
record expires. See docs/LEYLINE-MESH.md. Standard library only (plus wunet.keys, which uses `cryptography` when it
is installed and the pure-Python Ed25519 otherwise).

Three kinds (each is one JSON object; "id" is derived, never trusted from the wire):

  realm   {"kind": "realm", "beat": {...}, "sig": "<hex>", "endpoints": [{"att": {...}, "sig": "<hex>"}, ...]}
          * beat/sig is the realm's own listing heartbeat, exactly as today's agents sign it (keys.CTX_HEARTBEAT):
            {"v": 1, "realm_id", "pubkey", "seq", "ts", "record": {...}, "status": {...}, "relay": "<host>",
             "relays": ["<host>", ...]?}. No agent change is needed: a relay that took the beat wraps it.
          * id = "r-" + realm_id; realm_id must be keys.realm_id(pubkey). Expires REALM_TTL after beat.ts.
          * endpoints: where the realm can be reached. Each one is signed by the relay node that holds the tunnel
            (CTX_ENDPOINT): {"v": 1, "realm_id", "relay": "<host>", "node": "<node pubkey hex>", "auth_port",
            "world_port", "ws": bool, "ts"}. The relay's host must be one the realm itself signed (beat.relay or
            beat.relays), so a relay can't claim a realm that never chose it. Expires ENDPOINT_TTL after att.ts.
  relay   {"kind": "relay", "node": {...}, "sig": "<hex>"}   (CTX_NODE)
          {"v": 1, "pubkey", "host", "http": "https://<host>", "seq", "ts", "region", "volunteer": bool,
           "seed": false, "ws": bool, "mesh": bool, "caps": {"realms", "streams", "kbps"},
           "load": {"realms", "streams"}}
          * id = "n-" + keys.realm_id(pubkey). Expires NODE_TTL after ts. "seed" is never believed from the record:
            a seed is a node whose key is pinned in SEED_KEYS (or the host is in the bootstrap list).
  block   {"kind": "block", "block": {...}, "sig": "<hex>"}   (CTX_BLOCK, signed by a pinned staff key)
          {"v": 1, "target": "r-<realm id>" | "n-<node id>", "reason", "ts", "expires", "staff": "<pubkey hex>"}
          * id = "b-" + target. Valid only when staff is one of the pinned staff keys. At most BLOCK_MAX_TTL.
            While it lasts the target's records are dropped everywhere and refused on arrival.

Merge rules (Store.offer): verify fully, or refuse; a blocked target is refused; for the same id the higher
version wins (realm: beat.seq; relay: node.seq; block: block.ts); an equal version with different bytes (a key
holder equivocating) keeps the record with the smaller sha256 of its signature, so every node picks the same one;
the same realm beat seen with more endpoints merges them (newest per relay node, at most MAX_ENDPOINTS). Expired
records are dropped on arrival and by sweep().
"""
from __future__ import annotations

import hashlib
import json
import re

from . import keys

CTX_ENDPOINT = "leyline-mesh-endpoint-v1"
CTX_NODE = "leyline-mesh-node-v1"
CTX_BLOCK = "leyline-mesh-block-v1"

REALM_TTL = 15 * 60          # a realm record lives 15 minutes after the beat it carries
ENDPOINT_TTL = 15 * 60
NODE_TTL = 30 * 60
BLOCK_MAX_TTL = 90 * 86400
SKEW = 300                   # a record "from the future" by more than this is refused
REFRESH = 5 * 60             # a relay re-publishes an unchanged realm this often (TTL / 3)
MAX_ENDPOINTS = 8
MAX_RECORD_BYTES = 6000
MAX_RECORDS = 50_000
BUCKETS = 256

HOST_RE = re.compile(r"^(?=.{1,253}$)([a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?)(\.[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?)+$")
HEX64 = re.compile(r"^[0-9a-f]{64}$")
REGIONS = ("na-east", "na-west", "sa", "eu", "africa", "me", "asia", "oce")
# TODO(owner): the staff key(s) whose signed blocks the mesh honours (hex Ed25519 public keys). Empty = no
# block record is valid anywhere (the seed relays' own RELAY_BLOCK_FILE keeps working as today).
STAFF_KEYS: tuple[str, ...] = ()
# TODO(owner): the seed relays' node public keys, once each seed has made its node key (RELAY_NODE_KEY).
SEED_KEYS: tuple[str, ...] = ()


def _int(v, lo=0, hi=2 ** 63):
    return isinstance(v, int) and not isinstance(v, bool) and lo <= v <= hi


def host_ok(h) -> bool:
    return isinstance(h, str) and bool(HOST_RE.match(h))


def node_id(pub_hex: str) -> str:
    return "n-" + keys.realm_id(bytes.fromhex(pub_hex))


def size(rec) -> int:
    return len(keys.canonical(rec))


def sig_rank(rec) -> str:
    """The tie-break for an equivocating key holder: the smaller sha256 of the signature wins, the same everywhere."""
    return hashlib.sha256(str(rec.get("sig", "")).encode()).hexdigest()


# ------------------------------------------------------------------------------------------------ making records
def realm_record(beat: dict, sig: str, endpoints: list | None = None) -> dict:
    return {"kind": "realm", "beat": beat, "sig": sig, "endpoints": list(endpoints or [])}


def endpoint(node_secret: bytes, realm_id: str, relay: str, auth_port: int, world_port: int, ws: bool, ts: int) -> dict:
    pub = keys.public_key(node_secret).hex()
    att = {"v": 1, "realm_id": realm_id, "relay": relay, "node": pub, "auth_port": int(auth_port),
           "world_port": int(world_port), "ws": bool(ws), "ts": int(ts)}
    return {"att": att, "sig": keys.sign_doc(node_secret, att, CTX_ENDPOINT)}


def relay_record(node_secret: bytes, host: str, seq: int, ts: int, *, http: str | None = None, region: str = "",
                 volunteer: bool = False, ws: bool = True, mesh: bool = True, caps: dict | None = None,
                 load: dict | None = None) -> dict:
    pub = keys.public_key(node_secret).hex()
    node = {"v": 1, "pubkey": pub, "host": host, "http": http or f"https://{host}", "seq": int(seq), "ts": int(ts),
            "region": region if region in REGIONS else "", "volunteer": bool(volunteer), "seed": False,
            "ws": bool(ws), "mesh": bool(mesh),
            "caps": {k: int((caps or {}).get(k) or 0) for k in ("realms", "streams", "kbps")},
            "load": {k: int((load or {}).get(k) or 0) for k in ("realms", "streams")}}
    return {"kind": "relay", "node": node, "sig": keys.sign_doc(node_secret, node, CTX_NODE)}


def block_record(staff_secret: bytes, target: str, reason: str, ts: int, expires: int) -> dict:
    b = {"v": 1, "target": target, "reason": str(reason)[:120], "ts": int(ts), "expires": int(expires),
         "staff": keys.public_key(staff_secret).hex()}
    return {"kind": "block", "block": b, "sig": keys.sign_doc(staff_secret, b, CTX_BLOCK)}


# ------------------------------------------------------------------------------------------------ checking records
class Bad(ValueError):
    pass


def _check_endpoint(e, rid: str, signed_relays: set, now: float):
    if not isinstance(e, dict) or not isinstance(e.get("att"), dict):
        raise Bad("endpoint is not {att, sig}")
    a = e["att"]
    if a.get("v") != 1 or a.get("realm_id") != rid:
        raise Bad("endpoint for another realm")
    if not host_ok(a.get("relay")) or a["relay"] not in signed_relays:
        raise Bad("endpoint relay was not chosen by the realm")
    if not (isinstance(a.get("node"), str) and HEX64.match(a["node"])):
        raise Bad("endpoint node key")
    if not (_int(a.get("auth_port"), 1, 65535) and _int(a.get("world_port"), 1, 65535)):
        raise Bad("endpoint ports")
    if not isinstance(a.get("ws"), bool) or not _int(a.get("ts")):
        raise Bad("endpoint fields")
    if a["ts"] > now + SKEW or now - a["ts"] > ENDPOINT_TTL:
        raise Bad("endpoint expired")
    if not keys.verify_doc(bytes.fromhex(a["node"]), a, CTX_ENDPOINT, e.get("sig", "")):
        raise Bad("endpoint signature")


def signed_relays(beat: dict) -> set:
    out = set()
    if host_ok(beat.get("relay")):
        out.add(beat["relay"])
    if isinstance(beat.get("relays"), list):
        out.update(h for h in beat["relays"][:MAX_ENDPOINTS] if host_ok(h))
    return out


def check(rec, now: float, staff_keys=None) -> tuple[str, int]:
    """(id, version) of a valid record, or raises Bad. Endpoints that fail are dropped from `rec` in place
    (a realm record stays valid with fewer endpoints)."""
    if not isinstance(rec, dict):
        raise Bad("not an object")
    if size(rec) > MAX_RECORD_BYTES:
        raise Bad("too big")
    kind = rec.get("kind")
    if kind == "realm":
        beat = rec.get("beat")
        if not isinstance(beat, dict) or beat.get("v") != 1:
            raise Bad("no beat")
        pk = beat.get("pubkey")
        if not (isinstance(pk, str) and HEX64.match(pk)):
            raise Bad("beat pubkey")
        rid = keys.realm_id(bytes.fromhex(pk))
        if beat.get("realm_id") != rid:
            raise Bad("realm id does not match the key")
        if not (_int(beat.get("seq")) and _int(beat.get("ts"))):
            raise Bad("beat seq/ts")
        if beat["ts"] > now + SKEW or now - beat["ts"] > REALM_TTL:
            raise Bad("expired")
        rec_doc = beat.get("record")
        if not isinstance(rec_doc, dict) or not isinstance(rec_doc.get("name"), str) or not rec_doc["name"].strip():
            raise Bad("record.name")
        if not keys.verify_doc(bytes.fromhex(pk), beat, keys.CTX_HEARTBEAT, rec.get("sig", "")):
            raise Bad("signature")
        relays = signed_relays(beat)
        good = []
        for e in rec.get("endpoints") or []:
            try:
                _check_endpoint(e, rid, relays, now)
                good.append(e)
            except Bad:
                continue
        rec["endpoints"] = _dedupe_endpoints(good)
        return "r-" + rid, beat["seq"]
    if kind == "relay":
        n = rec.get("node")
        if not isinstance(n, dict) or n.get("v") != 1:
            raise Bad("no node")
        pk = n.get("pubkey")
        if not (isinstance(pk, str) and HEX64.match(pk)):
            raise Bad("node pubkey")
        if not host_ok(n.get("host")):
            raise Bad("node host")
        http = n.get("http")
        if not (isinstance(http, str) and re.match(r"^https?://" + re.escape(n["host"]) + r"(:[0-9]{1,5})?$", http)):
            raise Bad("node http")
        if not (_int(n.get("seq")) and _int(n.get("ts"))):
            raise Bad("node seq/ts")
        if n["ts"] > now + SKEW or now - n["ts"] > NODE_TTL:
            raise Bad("expired")
        if not keys.verify_doc(bytes.fromhex(pk), n, CTX_NODE, rec.get("sig", "")):
            raise Bad("signature")
        return node_id(pk), n["seq"]
    if kind == "block":
        b = rec.get("block")
        if not isinstance(b, dict) or b.get("v") != 1:
            raise Bad("no block")
        staff = tuple(STAFF_KEYS if staff_keys is None else staff_keys)
        if b.get("staff") not in staff:
            raise Bad("not a staff key")
        t = b.get("target")
        if not (isinstance(t, str) and re.match(r"^[rn]-[a-z2-7]{16}$", t)):
            raise Bad("block target")
        if not (_int(b.get("ts")) and _int(b.get("expires"))):
            raise Bad("block times")
        if b["ts"] > now + SKEW or b["expires"] <= now or b["expires"] - b["ts"] > BLOCK_MAX_TTL:
            raise Bad("block expired or too long")
        if not keys.verify_doc(bytes.fromhex(b["staff"]), b, CTX_BLOCK, rec.get("sig", "")):
            raise Bad("signature")
        return "b-" + t, b["ts"]
    raise Bad("unknown kind")


def _dedupe_endpoints(eps: list) -> list:
    best = {}
    for e in eps:
        k = e["att"]["node"]
        if k not in best or e["att"]["ts"] > best[k]["att"]["ts"]:
            best[k] = e
    out = sorted(best.values(), key=lambda e: -e["att"]["ts"])[:MAX_ENDPOINTS]
    return sorted(out, key=lambda e: (e["att"]["relay"], e["att"]["node"]))


def expires_at(rec) -> float:
    k = rec.get("kind")
    if k == "realm":
        return rec["beat"]["ts"] + REALM_TTL
    if k == "relay":
        return rec["node"]["ts"] + NODE_TTL
    if k == "block":
        return rec["block"]["expires"]
    return 0


def target_of(rec_id: str) -> str:
    return rec_id[2:] if rec_id[:2] in ("r-", "n-") else rec_id


# ------------------------------------------------------------------------------------------------ the store
class Store:
    """Every valid record this node knows, with the merge rules above. `changed` counts accepted changes, and
    `log` keeps (counter, id) so a peer can ask for what changed since a cursor."""

    def __init__(self, staff_keys=None, max_records=MAX_RECORDS):
        self.staff_keys = tuple(STAFF_KEYS if staff_keys is None else staff_keys)
        self.max_records = max_records
        self.recs: dict[str, dict] = {}
        self.ver: dict[str, int] = {}
        self.counter = 0
        self.at: dict[str, int] = {}          # id -> counter of its last change
        self.stats = {"accepted": 0, "refused": 0, "stale": 0}
        self.last_id = None                   # the id of the record the last offer() looked at

    def blocked(self, rec_id: str) -> bool:
        b = self.recs.get("b-" + rec_id)
        return b is not None

    def offer(self, rec, now: float) -> tuple[bool, str]:
        """(changed, why). Never raises for bad input."""
        self.last_id = None
        try:
            rec = json.loads(json.dumps(rec))     # our own copy; check() may drop endpoints
            rid, ver = check(rec, now, self.staff_keys)
            self.last_id = rid
        except (Bad, ValueError, TypeError, KeyError, AttributeError) as e:
            self.stats["refused"] += 1
            return False, f"refused: {e}"
        if rec["kind"] != "block" and self.blocked(rid):
            self.stats["refused"] += 1
            return False, "refused: blocked"
        cur = self.recs.get(rid)
        if cur is not None:
            cv = self.ver[rid]
            if ver < cv:
                self.stats["stale"] += 1
                return False, "older"
            if ver == cv:
                if rec.get("sig") == cur.get("sig"):
                    if rec["kind"] != "realm":
                        self.stats["stale"] += 1
                        return False, "same"
                    merged = _dedupe_endpoints(cur["endpoints"] + rec["endpoints"])
                    if keys.canonical(merged) == keys.canonical(cur["endpoints"]):
                        self.stats["stale"] += 1
                        return False, "same"
                    rec = dict(cur, endpoints=merged)
                elif sig_rank(rec) >= sig_rank(cur):
                    self.stats["stale"] += 1
                    return False, "equivocation: kept the other"
            elif rec["kind"] == "realm":
                # a newer beat keeps endpoints that are still fresh (the relay re-attests every REFRESH anyway)
                rec["endpoints"] = _dedupe_endpoints(rec["endpoints"] + [
                    e for e in cur.get("endpoints", []) if e["att"]["relay"] in signed_relays(rec["beat"])
                    and now - e["att"]["ts"] <= ENDPOINT_TTL])
        elif len(self.recs) >= self.max_records:
            self.sweep(now)
            if len(self.recs) >= self.max_records:
                self.stats["refused"] += 1
                return False, "refused: full"
        self.recs[rid], self.ver[rid] = rec, ver
        self.counter += 1
        self.at[rid] = self.counter
        if rec["kind"] == "block":
            t = rec["block"]["target"]
            if t in self.recs:
                self._drop(t)
        self.stats["accepted"] += 1
        return True, "ok"

    def _drop(self, rid):
        self.recs.pop(rid, None)
        self.ver.pop(rid, None)
        self.at.pop(rid, None)

    def sweep(self, now: float) -> int:
        """Drop expired records and endpoints. Returns how many records went."""
        gone = [rid for rid, r in self.recs.items() if expires_at(r) <= now]
        for rid in gone:
            self._drop(rid)
        for r in self.recs.values():
            if r["kind"] == "realm":
                r["endpoints"] = [e for e in r["endpoints"] if now - e["att"]["ts"] <= ENDPOINT_TTL]
        return len(gone)

    def since(self, cursor: int, limit: int = 2000) -> tuple[list, int]:
        """Records changed after `cursor` (oldest change first), and the cursor to ask with next time."""
        if not _int(cursor) or cursor > self.counter:
            cursor = 0          # this node restarted (or a bogus cursor): start over
        ids = sorted((c, rid) for rid, c in self.at.items() if c > cursor)[:limit]
        return [self.recs[rid] for _, rid in ids], (ids[-1][0] if ids else self.counter)

    # ---------------------------------------------------------------- anti-entropy summary
    @staticmethod
    def bucket(rid: str) -> int:
        return hashlib.sha256(rid.encode()).digest()[0] % BUCKETS

    def summary(self) -> list[str]:
        """BUCKETS short hashes: two nodes holding the same (id, version, endpoint set) in a bucket agree on it."""
        acc = [hashlib.sha256() for _ in range(BUCKETS)]
        for rid in sorted(self.recs):
            r = self.recs[rid]
            tag = f"{rid}:{self.ver[rid]}:{len(r.get('endpoints') or [])};"
            acc[self.bucket(rid)].update(tag.encode())
        return [h.hexdigest()[:12] for h in acc]

    def in_buckets(self, wanted: set) -> list:
        return [r for rid, r in sorted(self.recs.items()) if self.bucket(rid) in wanted]

    def realms(self) -> list:
        return [r for r in self.recs.values() if r["kind"] == "realm"]

    def relays(self) -> list:
        return [r for r in self.recs.values() if r["kind"] == "relay"]


# ------------------------------------------------------------------------------------------------ relay choice
def choose_endpoint(rec: dict, relays: dict, rtt_ms: dict, *, volunteers: bool, seeds: set,
                    browser: bool = False) -> dict | None:
    """The endpoint to play `rec` through. `relays`: host -> relay record node dict (what the mesh says about
    each relay's caps and load); `rtt_ms`: host -> measured round trip (missing = not measured: 250 ms);
    `seeds`: the hosts of our own seed relays. With `volunteers` off only seed relays and the realm's own first
    relay (beat.relay, the one it chose itself) count. `browser`: only relays that serve the WebSocket bridge.
    Lower cost wins: rtt * (1 + 2 * load) where load = streams/caps.streams (0..1, unknown 0.5), +40 % for a
    relay that is full of realms; ties go to seeds, then to the host name."""
    own = rec["beat"].get("relay")
    best, best_key = None, None
    for e in rec.get("endpoints") or []:
        a = e["att"]
        h = a["relay"]
        if browser and not a["ws"]:
            continue
        if not volunteers and h not in seeds and h != own:
            continue
        n = relays.get(h) or {}
        caps, load = n.get("caps") or {}, n.get("load") or {}
        if caps.get("streams"):
            lf = min(1.0, (load.get("streams") or 0) / caps["streams"])
        else:
            lf = 0.0 if h in seeds else 0.5
        cost = float(rtt_ms.get(h, 250.0)) * (1 + 2 * lf)
        if caps.get("realms") and (load.get("realms") or 0) >= caps["realms"]:
            cost *= 1.4
        key = (round(cost, 3), 0 if h in seeds else 1, h)
        if best_key is None or key < best_key:
            best, best_key = e, key
    return best
