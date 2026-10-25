"""Community Beacons listing: public home-hosted realms announce themselves with signed heartbeats.

  POST /api/listing/heartbeat   {"beat": {...}, "sig": "<hex>"}   from a host's agent, every 60 s
  GET  /api/listing/realms.json  the community records (Beacons record schema 1 + "community")
  POST /api/listing/claims       {"realm_id", "token", "claimed_by"}   from the website only
                                 (Authorization: Bearer RELAY_LISTING_SITE_SECRET)

A heartbeat ("beat") is signed with the realm's own key (keys.CTX_HEARTBEAT):
  {"v": 1, "realm_id", "pubkey", "seq", "ts", "record": {...}, "status": {...}, "claim": "<token>"?}
  - realm_id must be derived from pubkey; ts within 5 minutes of the listing's clock; seq must grow
    (a replayed or reordered beat is refused); one beat per 20 s per realm.
  - "record" is the host's Beacon text (name, tagline, summary, type, ruleset, rules, discord),
    checked and trimmed here; the listing adds everything else itself (address, connect button,
    status URL, the "community" block). Hosts cannot set official, order or badges.
  - "status" carries players and bots separately (bots are never added to players).
  - "claim" (optional) is the token the website gave the host's Hero Key account.

Claim flow: the host signs in on the site with a Hero Key (v2: Ed25519 challenge-response, so the
host never types a password into anything the realm sees), picks "Claim a realm", enters the realm
id; the site makes a one-time token and shows it. The host runs `Claim my realm.bat <token>`: the
agent puts it in the signed heartbeat and on the realm's status page. The site then calls
POST /api/listing/claims with that token: the listing checks the latest SIGNED heartbeat carries
it (only the realm key's holder could put it there) and marks the record claimed by that account.
Unclaimed records are listed as "unclaimed". Ordering never depends on money or votes.

Records leave the list 24 h after the last heartbeat; after 3 missed beats they show as offline.
State lives in memory and in RELAY_STATE's sibling listing.json (no player data in it).
"""
import collections
import hmac
import json
import os
import re
import time

from wunet import keys

from . import httpd

TYPES = ("PvE", "PvP", "RP", "RP-PvP", "Fun")
RULESETS = ("main", "brawl", "progression", "casual", "custom")
HTTPS_DISCORD = re.compile(r"^https://(discord\.gg|discord\.com/invite)/[A-Za-z0-9-]{2,32}$")
CLAIM_RE = re.compile(r"^[A-Za-z0-9_-]{16,64}$")
SKEW = 300
MIN_INTERVAL = 20
OFFLINE_AFTER = 180
FORGET_AFTER = 86400
MAX_RECORDS = 2000


def _text(v, n):
    if not isinstance(v, str):
        return ""
    v = " ".join(v.replace("\x00", "").split())
    return v[:n]


def clean_record(rec: dict) -> dict:
    rec = rec if isinstance(rec, dict) else {}
    out = {
        "name": _text(rec.get("name"), 32),
        "tagline": _text(rec.get("tagline"), 80),
        "summary": _text(rec.get("summary"), 400),
        "type": rec.get("type") if rec.get("type") in TYPES else "PvE",
        "ruleset": rec.get("ruleset") if rec.get("ruleset") in RULESETS else "custom",
        "rules": [t for t in (_text(x, 120) for x in (rec.get("rules") or [])[:10]) if t],
        "discord": rec.get("discord") if isinstance(rec.get("discord"), str) and HTTPS_DISCORD.match(rec["discord"]) else None,
        "warden": rec.get("warden") if isinstance(rec.get("warden"), bool) else None,
        "language": _text(rec.get("language"), 8) or None,
    }
    return out


class Listing:
    def __init__(self, cfg, relay=None):
        self.cfg, self.relay = cfg, relay
        self.path = os.path.join(os.path.dirname(os.path.abspath(cfg.state_file)), "listing.json")
        self.entries = {}
        self.new_by_ip = collections.defaultdict(collections.deque)
        self.dirty = False
        try:
            with open(self.path, encoding="utf-8") as f:
                self.entries = json.load(f).get("entries", {})
        except (OSError, ValueError):
            pass

    def save(self):
        if not self.dirty:
            return
        try:
            tmp = self.path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump({"entries": self.entries}, f, sort_keys=True)
            os.replace(tmp, self.path)
            self.dirty = False
        except OSError:
            pass

    # ------------------------------------------------------------------ heartbeat
    def heartbeat(self, doc, ip, now=None):
        """(status, reply)."""
        now = time.time() if now is None else now
        beat, sig = doc.get("beat"), doc.get("sig", "")
        if not isinstance(beat, dict) or beat.get("v") != 1:
            return 400, {"error": "expected {beat, sig}"}
        try:
            pub = bytes.fromhex(beat.get("pubkey", ""))
        except ValueError:
            return 400, {"error": "bad public key"}
        rid = beat.get("realm_id")
        if len(pub) != 32 or keys.realm_id(pub) != rid:
            return 400, {"error": "realm id does not match the key"}
        if not keys.verify_doc(pub, beat, keys.CTX_HEARTBEAT, sig):
            return 403, {"error": "bad signature"}
        ts, seq = beat.get("ts"), beat.get("seq")
        if not isinstance(ts, (int, float)) or abs(now - ts) > SKEW:
            return 400, {"error": "clock is off by more than 5 minutes"}
        if not isinstance(seq, int) or seq < 0:
            return 400, {"error": "bad seq"}
        rec = clean_record(beat.get("record"))
        if not rec["name"]:
            return 400, {"error": "record.name is required"}
        e = self.entries.get(rid)
        if e:
            if seq <= e["seq"]:
                return 409, {"error": "replayed or old heartbeat"}
            if now - e["last_seen"] < MIN_INTERVAL:
                return 429, {"error": "one heartbeat per 20 s"}
        else:
            q = self.new_by_ip[ip]
            while q and now - q[0] > 3600:
                q.popleft()
            if len(q) >= 5:
                return 429, {"error": "too many new realms from this address"}
            if len(self.entries) >= MAX_RECORDS:
                self.forget(now)
                if len(self.entries) >= MAX_RECORDS:
                    return 503, {"error": "listing is full"}
            q.append(now)
            e = {"first_seen": now, "claimed_by": None, "claim_ok": None}
        st = beat.get("status") if isinstance(beat.get("status"), dict) else {}

        def num(k):
            v = st.get(k)
            return v if isinstance(v, int) and 0 <= v < 1_000_000 else None
        claim = beat.get("claim") if isinstance(beat.get("claim"), str) and CLAIM_RE.match(beat["claim"]) else None
        e.update(realm_id=rid, pubkey=pub.hex(), seq=seq, last_seen=now, record=rec,
                 status={"online": bool(st.get("online")), "players": num("players"), "bots": num("bots"),
                         "uptime_s": num("uptime_s")},
                 claim=claim, relay=_text(beat.get("relay"), 253) or (self.cfg.name if self.cfg else None))
        self.entries[rid] = e
        self.dirty = True
        return 200, {"ok": True, "listed": True, "next_in": 60, "claimed": bool(e.get("claimed_by"))}

    def forget(self, now=None):
        now = time.time() if now is None else now
        for rid in [r for r, e in self.entries.items() if now - e["last_seen"] > FORGET_AFTER]:
            del self.entries[rid]
            self.dirty = True

    # ------------------------------------------------------------------ claims (site -> listing)
    def claim(self, doc, now=None):
        rid, token, who = doc.get("realm_id"), doc.get("token"), doc.get("claimed_by")
        e = self.entries.get(rid)
        if not e:
            return 404, {"error": "realm not listed"}
        if not (isinstance(token, str) and e.get("claim") and hmac.compare_digest(token, e["claim"])):
            return 409, {"error": "the realm's signed heartbeat does not carry this token (yet)"}
        e["claimed_by"] = _text(who, 40) or "a Hero Key account"
        e["claimed_at"] = time.time() if now is None else now
        self.dirty = True
        return 200, {"ok": True, "realm_id": rid, "claimed_by": e["claimed_by"]}

    # ------------------------------------------------------------------ records
    def record(self, e, now):
        rid, rec = e["realm_id"], e["record"]
        relay = e.get("relay") or "relay.openvanilla.app"
        site = getattr(self.cfg, "site_url", "https://openvanilla.app")
        online = now - e["last_seen"] <= OFFLINE_AFTER and e["status"]["online"]
        auth_port = None
        if self.relay:
            alloc = self.relay.state["realms"].get(rid)
            auth_port = alloc["auth"] if alloc else None
        return {
            "schema": 1,
            "slug": "c-" + rid,
            "name": rec["name"],
            "official": False,
            "state": "live" if online else "offline",
            "stateNote": None if online else "The host's realm is not running right now.",
            "order": 1000,
            "tagline": rec["tagline"],
            "summary": rec["summary"],
            "type": rec["type"],
            "profile": {"game": "Wrath of the Lich King", "version": "3.3.5a", "build": 12340,
                        "address": relay, "port": auth_port, "warden": rec["warden"],
                        "ruleset": rec["ruleset"], "patches": None, "clientFiles": "own"},
            "connect": {"kind": "web-signin", "url": f"{site}/join/{rid}", "label": "Join this realm",
                        "note": "Opens the realm's join page: make a game account there, then set your realmlist."},
            "rules": rec["rules"],
            "features": [],
            "media": {"icon": None, "screenshots": [], "trailer": None},
            "discord": rec["discord"],
            "status": {"url": f"https://{relay}/r/{rid}/status.json", "format": "openvanilla-status-1"},
            "leaderboards": {"duels": None, "bossfights": None},
            "updated": time.strftime("%Y-%m-%d", time.gmtime(e["last_seen"])),
            "community": {
                "realmId": rid, "relay": relay, "signed": True,
                "claimed": bool(e.get("claimed_by")), "claimedBy": e.get("claimed_by"),
                "firstSeen": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(e["first_seen"])),
                "lastSeen": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(e["last_seen"])),
                "lastHeartbeat": e["status"],
            },
        }

    def realms_json(self, now=None):
        now = time.time() if now is None else now
        self.forget(now)
        blocked = self.relay.blocked if self.relay else set()
        recs = [self.record(e, now) for rid, e in self.entries.items() if rid not in blocked]
        recs.sort(key=lambda r: (r["state"] != "live", r["name"].lower(), r["community"]["realmId"]))
        return {"schema": 1, "kind": "community", "updated": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now)),
                "realms": recs}

    # ------------------------------------------------------------------ HTTP
    async def route(self, req, rest):
        pub = {"Access-Control-Allow-Origin": "*"}
        if rest == ["heartbeat"] and req.method == "POST":
            st, body = self.heartbeat(req.json(), req.ip)
            return httpd.response(st, body)
        if rest == ["realms.json"] and req.method == "GET":
            return httpd.response(200, self.realms_json(), headers=dict(pub, **{"Cache-Control": "public, max-age=30"}))
        if rest == ["claims"] and req.method == "POST":
            secret = getattr(self.cfg, "listing_site_secret", "")
            auth = req.headers.get("authorization", "")
            if not secret or not hmac.compare_digest(auth, "Bearer " + secret):
                return httpd.response(401, {"error": "site only"})
            st, body = self.claim(req.json())
            return httpd.response(st, body)
        return httpd.response(404, {"error": "not found"})
