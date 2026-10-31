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

Listing quality (2026-10-29, all optional in the beat, so older agents keep working): the record may also carry
  core ("azerothcore", ...), build (12340, ...), tags (blizzlike boosted custom pvp rp hangout bots), region
  (host-chosen: na-east na-west sa eu africa me asia oce), language ("en", "pt-BR"), max_players, and
  direct (the host allows direct connections). Each is checked here and dropped when it is not one of those.
The listing works out the rest itself from the heartbeats: uptime over 24 h and 7 d (hourly buckets of the seconds
a realm was seen online), "new" (first seen in the last 7 days), a coarse region estimate (the relay's own
RELAY_REGION when the realm's tunnel answers in under 45 ms) and a fair score (players, bots counted apart and
worth little, uptime, new; never money or votes). "Direct connect available" is only advertised when the relay
operator turns RELAY_ADVERTISE_DIRECT on (off by default) and the host allows it.

Auto-hide: a realm whose tunnel to this relay is gone, or that missed 3 beats, shows as offline at once; 6 h after
its last heartbeat it leaves the list; its entry (uptime history, first seen) is forgotten after 7 days.
State lives in memory and in RELAY_STATE's sibling listing.json (no player data in it).
"""
import collections
import hmac
import json
import math
import os
import re
import time

from wunet import domains, keys

from . import httpd

TYPES = ("PvE", "PvP", "RP", "RP-PvP", "Fun")
RULESETS = ("main", "brawl", "progression", "casual", "dalaran", "vanillaplus", "custom")
HTTPS_DISCORD = re.compile(r"^https://(discord\.gg|discord\.com/invite)/[A-Za-z0-9-]{2,32}$")
CLAIM_RE = re.compile(r"^[A-Za-z0-9_-]{16,64}$")
SKEW = 300
MIN_INTERVAL = 20
OFFLINE_AFTER = 180
HIDE_AFTER = 6 * 3600          # offline this long: not listed any more
FORGET_AFTER = 7 * 86400       # silent this long: the entry (and its uptime history) is dropped
NEW_FOR = 7 * 86400
MAX_RECORDS = 2000
TAGS = ("blizzlike", "boosted", "custom", "pvp", "rp", "hangout", "bots")
REGIONS = ("na-east", "na-west", "sa", "eu", "africa", "me", "asia", "oce")
CORES = ("azerothcore", "trinitycore", "cmangos", "vmangos", "mangos", "other")
# client build number -> (version, the profile's "game")
BUILDS = {5875: ("1.12.1", "classic-1.12.1"), 8606: ("2.4.3", "tbc-2.4.3"), 12340: ("3.3.5a", "wrath-3.3.5a"),
          15595: ("4.3.4", "cata-4.3.4"), 18414: ("5.4.8", "mop-5.4.8")}
LANG_RE = re.compile(r"^[a-z]{2,3}(-[A-Z]{2})?$")
NEAR_MS = 45


def _tags(v):
    if not isinstance(v, list):
        return []
    want = {x.strip().lower() for x in v[:20] if isinstance(x, str)}
    return [t for t in TAGS if t in want]


def _int_in(v, lo, hi):
    return v if isinstance(v, int) and not isinstance(v, bool) and lo <= v <= hi else None


def score(live, players, bots, up24, up7, new) -> float:
    """The fair order of the list, highest first: people playing now (diminishing, so one big realm can't bury the
    rest), bots counted apart and worth at most 5, uptime (7 d weighs more than 24 h; unknown counts as 50 %), and a
    small boost while a realm is new so it can be found. Offline is 0. Nothing here can be bought or voted on."""
    if not live:
        return 0.0
    p = min(40.0, 8 * math.sqrt(players or 0))
    b = min(5.0, math.sqrt(bots or 0) / 2)
    if up7 is None:
        u = 20.0
    else:
        u = 0.25 * up7 + 0.15 * (up24 if up24 is not None else up7)
    return round(p + b + u + (10.0 if new else 0.0), 1)


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
        "language": rec.get("language") if isinstance(rec.get("language"), str) and LANG_RE.match(rec["language"]) else None,
        "core": rec.get("core") if rec.get("core") in CORES else "azerothcore",
        "build": rec.get("build") if rec.get("build") in BUILDS and not isinstance(rec.get("build"), bool) else 12340,
        "tags": _tags(rec.get("tags")),
        "region": rec.get("region") if rec.get("region") in REGIONS else None,
        "max_players": _int_in(rec.get("max_players"), 1, 10000),
        "direct": rec.get("direct") is True,
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
        if self.relay is not None:
            # Only Beacons that hold a tunnel to this relay get listed (no join link to nowhere),
            # and never a private one (a host who switched to private must not linger on the list).
            if rid in self.relay.blocked:
                return 403, {"error": "this realm is blocked on this relay"}
            s = self.relay.sessions.get(rid)
            if s is None:
                return 409, {"error": "connect this realm to the relay first"}
            if s.visibility != "public":
                self.delist(rid)
                return 403, {"error": "private realms are not listed"}
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
        online_now = bool(st.get("online"))
        e.setdefault("up_since", now)
        if "last_seen" in e and e.get("status", {}).get("online") and online_now and now - e["last_seen"] <= OFFLINE_AFTER:
            self.credit(e, e["last_seen"], now)
        e.update(realm_id=rid, pubkey=pub.hex(), seq=seq, last_seen=now, record=rec,
                 status={"online": online_now, "players": num("players"), "bots": num("bots"),
                         "uptime_s": num("uptime_s")},
                 claim=claim, relay=_text(beat.get("relay"), 253) or (self.cfg.name if self.cfg else None))
        self.entries[rid] = e
        self.dirty = True
        if self.relay is not None and getattr(self.relay, "mesh", None):
            self.relay.mesh.local_beat(beat, sig, now)   # the Leyline mesh (off unless RELAY_MESH=1)
        return 200, {"ok": True, "listed": True, "next_in": 60, "claimed": bool(e.get("claimed_by"))}

    # ------------------------------------------------------------------ uptime
    @staticmethod
    def credit(e, t0, t1):
        """Count t0..t1 as online, in hourly buckets ({"<hour number>": seconds}); a week of them is kept."""
        up = e.setdefault("up", {})
        while t0 < t1:
            h = int(t0 // 3600)
            end = min(t1, (h + 1) * 3600)
            up[str(h)] = round(min(3600.0, up.get(str(h), 0) + (end - t0)), 1)
            t0 = end
        oldest = int(t1 // 3600) - 7 * 24
        for k in [k for k in up if not k.isdigit() or int(k) < oldest]:
            del up[k]

    @staticmethod
    def uptime(e, now, window):
        """Percent of the last `window` seconds the realm was seen online (whole numbers), or None while the
        listing has watched it for less than an hour. Only the time since the listing started watching counts."""
        covered = min(window, now - e.get("up_since", now))
        if covered < 3600:
            return None
        lo = int((now - covered) // 3600)
        total = sum(v for k, v in (e.get("up") or {}).items() if k.isdigit() and int(k) >= lo
                    and isinstance(v, (int, float)))
        return max(0, min(100, round(100 * total / covered)))

    def rtt_ms(self, rid):
        s = self.relay.sessions.get(rid) if self.relay is not None else None
        v = getattr(s, "rtt_ms", None)
        return v if isinstance(v, (int, float)) else None

    def delist(self, rid):
        if self.entries.pop(rid, None) is not None:
            self.dirty = True
        if self.relay is not None and getattr(self.relay, "mesh", None):
            self.relay.mesh.forget_realm(rid)

    def hidden(self, e, now):
        return now - e["last_seen"] > HIDE_AFTER

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
        relay = e.get("relay") or domains.RELAY
        join = getattr(self.cfg, "join_base", None) or f"https://{relay}"
        online = now - e["last_seen"] <= OFFLINE_AFTER and e["status"]["online"]
        if self.relay is not None and rid not in self.relay.sessions:
            online = False   # the tunnel is gone: nobody can get in, whatever the last beat said
        auth_port = None
        if self.relay:
            alloc = self.relay.state["realms"].get(rid)
            auth_port = alloc["auth"] if alloc else None
        build = rec.get("build") if rec.get("build") in BUILDS else 12340
        version, game = BUILDS[build]
        up24, up7 = self.uptime(e, now, 86400), self.uptime(e, now, 7 * 86400)
        new = now - e["first_seen"] < NEW_FOR
        rtt = self.rtt_ms(rid)
        region_cfg = getattr(self.cfg, "region", "") or ""
        st = e["status"]
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
            "profile": {"game": game, "version": version, "build": build, "core": rec.get("core") or "azerothcore",
                        "address": relay, "port": auth_port, "warden": rec["warden"],
                        "ruleset": rec["ruleset"], "patches": None, "clientFiles": "own"},
            "tags": list(rec.get("tags") or []),
            "region": rec.get("region"),
            "language": rec.get("language"),
            "maxPlayers": rec.get("max_players"),
            "connect": {"kind": "web-signin", "url": f"{join}/join/{rid}", "label": "Join this realm",
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
                "uptime": {"h24": up24, "d7": up7},
                "new": new,
                "score": score(online, st.get("players"), st.get("bots"), up24, up7, new),
                "regionEstimate": region_cfg if (region_cfg in REGIONS and rtt is not None and rtt < NEAR_MS) else None,
                "latency": None if rtt is None else ("near" if rtt < NEAR_MS else "mid" if rtt < 120 else "far"),
                # ready but off: only when the relay operator turns it on AND the host allows it
                "directConnect": bool(getattr(self.cfg, "advertise_direct", False) and rec.get("direct")),
            },
        }

    def realms_json(self, now=None):
        now = time.time() if now is None else now
        self.forget(now)
        blocked = self.relay.blocked if self.relay else set()
        private = {rid for rid, s in self.relay.sessions.items() if s.visibility != "public"} if self.relay else set()
        recs = [self.record(e, now) for rid, e in self.entries.items()
                if rid not in blocked and rid not in private and not self.hidden(e, now)]
        recs.sort(key=lambda r: (r["state"] != "live", -r["community"]["score"], r["name"].lower(),
                                 r["community"]["realmId"]))
        live = [r for r in recs if r["state"] == "live"]
        return {"schema": 1, "kind": "community", "updated": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now)),
                "network": {"realms": len(live),
                            "players": sum(r["community"]["lastHeartbeat"].get("players") or 0 for r in live),
                            "bots": sum(r["community"]["lastHeartbeat"].get("bots") or 0 for r in live)},
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
