"""wu-agent: runs next to a home-hosted realm (a container in the host's compose) and keeps it
reachable through the relay without opening any port at home.

  * one outbound wss:// connection to the relay; proves the realm key; reconnects with backoff
  * opens a local connection to the authserver / worldserver for every player stream
  * points the realm list at the relay's per-realm address (acore_auth.realmlist), so players'
    clients come back through the relay for the world server, never to the host's IP
  * answers the relay's status and "make an account" requests (accounts arrive as SRP6 salt +
    verifier computed in the player's browser: the host never sees players' passwords)
  * public realms: a signed heartbeat to the Beacons listing every 60 s
  * a realm made on the website: its hello carries the pair hash of the website's token (wunet/keys.pair_hash),
    so the website finds this realm's id; the key itself is made here, on the host's PC
  * the operator's own realm as a Beacon (host.json "official": true, written by `setup.py official`): the realm
    list row, accounts and GM rights are never touched (that realm has its own sign-in); players and bots come
    from host.json "status_url" (the play page's /wrath/status.json) instead of the database

Config: state/host.json (written by setup.py), key: state/realm.key. It writes
state/relay-state.json for the self-check and the host's .bat.
"""
import argparse
import asyncio
import hashlib
import json
import logging
import os
import random
import socket
import sys
import time
import urllib.error
import urllib.request

from wunet import keys, mux, ws

from . import cores
from wunet.mux import CLOSE, DATA, OPEN

log = logging.getLogger("wu-agent")
VERSION = "wu-agent/1"


def read_json(path, default=None):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def write_json(path, doc):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(doc, f, indent=1, sort_keys=True)
    os.replace(tmp, path)


def resolve_ipv4(name):
    """The relay's IPv4 address for the realm list. The authserver sits on a network with no
    internet (so no outside DNS), and stock 3.3.5a clients speak IPv4 only. Falls back to the name."""
    try:
        infos = socket.getaddrinfo(name, None, socket.AF_INET, socket.SOCK_STREAM)
        return infos[0][4][0] if infos else name
    except OSError:
        return name


def split_hp(s, default_port):
    h, _, p = s.rpartition(":")
    return (h, int(p)) if h else (s, default_port)


# ------------------------------------------------------------------------------ the realm's DB
class RealmDB:
    """acore_auth / acore_characters through PyMySQL (the tools image has it). Calls block; the
    agent runs them in a thread."""

    def __init__(self, host, port, user, password, realm_db_id=1):
        self.args = dict(host=host, port=port, user=user, password=password, connect_timeout=5,
                         read_timeout=10, write_timeout=10, autocommit=True, charset="utf8mb4")
        self.realm_db_id = realm_db_id

    def _conn(self, db):
        import pymysql
        return pymysql.connect(database=db, **self.args)

    def set_realm_address(self, name, address, port):
        c = self._conn("acore_auth")
        try:
            with c.cursor() as cur:
                cur.execute("SELECT name, address, localAddress, port FROM realmlist WHERE id = %s", (self.realm_db_id,))
                row = cur.fetchone()
                if row is None:
                    return "no realmlist row yet"
                if tuple(row) == (name, address, address, port):
                    return "unchanged"
                cur.execute("UPDATE realmlist SET name = %s, address = %s, localAddress = %s, port = %s WHERE id = %s",
                            (name, address, address, port, self.realm_db_id))
                return "updated"
        finally:
            c.close()

    def create_account(self, username, salt, verifier, gmlevel=0):
        c = self._conn("acore_auth")
        try:
            with c.cursor() as cur:
                cur.execute("SELECT id FROM account WHERE username = %s", (username,))
                if cur.fetchone():
                    return "taken"
                cur.execute("INSERT INTO account (username, salt, verifier, expansion) VALUES (%s, %s, %s, 2)",
                            (username, bytes.fromhex(salt), bytes.fromhex(verifier)))
                if gmlevel:
                    cur.execute("INSERT INTO account_access (id, gmlevel, RealmID) SELECT id, %s, -1 FROM account "
                                "WHERE username = %s", (gmlevel, username))
                return "ok"
        finally:
            c.close()

    def grant_gm(self, username, gmlevel=3):
        """Give an EXISTING account GM rights on this realm. Never makes an account or touches a
        password: the operator makes their own account (join page or server console) first.
        'missing' until it exists, then 'ok' / 'unchanged'."""
        c = self._conn("acore_auth")
        try:
            with c.cursor() as cur:
                cur.execute("SELECT id FROM account WHERE username = %s", (username.upper(),))
                row = cur.fetchone()
                if not row:
                    return "missing"
                cur.execute("SELECT gmlevel FROM account_access WHERE id = %s AND RealmID = -1", (row[0],))
                have = cur.fetchone()
                if have and int(have[0]) == gmlevel:
                    return "unchanged"
                cur.execute("INSERT INTO account_access (id, gmlevel, RealmID) VALUES (%s, %s, -1) "
                            "ON DUPLICATE KEY UPDATE gmlevel = VALUES(gmlevel)", (row[0], gmlevel))
                return "ok"
        finally:
            c.close()

    def status(self):
        c = self._conn("acore_characters")
        try:
            with c.cursor() as cur:
                cur.execute("SELECT SUM(a.username NOT LIKE 'RNDBOT%%'), SUM(a.username LIKE 'RNDBOT%%') "
                            "FROM characters c JOIN acore_auth.account a ON a.id = c.account WHERE c.online = 1")
                players, bots = cur.fetchone()
                cur.execute("SELECT starttime FROM acore_auth.uptime WHERE realmid = %s ORDER BY starttime DESC LIMIT 1",
                            (self.realm_db_id,))
                row = cur.fetchone()
            return {"players": int(players or 0), "bots": int(bots or 0),
                    "uptime_s": int(time.time() - row[0]) if row else None,
                    "bots_method": "rndbot_account_prefix"}
        finally:
            c.close()


# ------------------------------------------------------------------------------ the agent
class LocalStream:
    def __init__(self, sid, port):
        self.sid, self.port = sid, port
        self.writer = None
        self.queue = []
        self.queued = 0
        self.closed = False


class Agent:
    def __init__(self, state_dir, db=None, services=None, opener=None, http_post=None, ssl_context=None):
        self.state_dir = state_dir
        self.cfg_path = os.path.join(state_dir, "host.json")
        self.cfg = read_json(self.cfg_path) or {}
        if not self.cfg.get("realm_id"):
            raise SystemExit(f"{self.cfg_path} is missing: run the host setup first")
        self.secret = keys.load_or_create(os.path.join(state_dir, "realm.key"))
        self.pub = keys.public_key(self.secret)
        if keys.realm_id(self.pub) != self.cfg["realm_id"]:
            raise SystemExit("realm.key does not belong to this realm id (state folder mixed up?)")
        self.db = db
        self.services = services or {3724: split_hp(self.cfg.get("auth_service", "ac-authserver:3724"), 3724),
                                     8085: split_hp(self.cfg.get("world_service", "ac-worldserver:8085"), 8085)}
        self.opener = opener or asyncio.open_connection
        self.http_post = http_post or self._http_post
        self.ssl_context = ssl_context
        self.ws = None
        self.streams = {}
        self.welcome = None
        self.cfg_mtime = self._mtime()
        self.stop_ev = asyncio.Event()
        self.relay_state = {"connected": False}
        self.address_done = None
        self.gm_done = None
        self.seq =int(time.time() * 1000)
        self.last_pong = time.monotonic()
        self.tick = 5          # housekeeping interval (tests shorten it)
        self.ping_every = 20
        self.heartbeat_every = int(os.environ.get("WU_HEARTBEAT_SECS", "60"))

    def _mtime(self):
        try:
            return os.stat(self.cfg_path).st_mtime
        except OSError:
            return 0

    def invite_sha(self):
        inv = self.cfg.get("invite_secret")
        return hashlib.sha256(inv.encode()).hexdigest() if inv else None

    def pair_sha(self):
        """The website's pairing (a realm made on /wrath/host): the hash of its token, never the token."""
        c = self.cfg.get("claim")
        return keys.pair_hash(c) if isinstance(c, str) and c else None

    def official(self):
        """The operator's own realm, reached through the relay: hands off its realm list, accounts and GM rights."""
        return self.cfg.get("official") is True

    def host_sha(self):
        """sha256 of the host-only secret (in the host's own join link): the relay marks signups made
        with it, and only those may take the GM account's name."""
        hs = self.cfg.get("host_secret")
        return hashlib.sha256(hs.encode()).hexdigest() if hs else None

    def save_state(self, **kw):
        self.relay_state.update(kw, updated=int(time.time()))
        try:
            write_json(os.path.join(self.state_dir, "relay-state.json"), self.relay_state)
        except OSError as e:
            log.warning("cannot write relay-state.json: %s", e)

    # -------------------------------------------------------------- relay connection
    async def run(self):
        backoff = 1
        tasks = [asyncio.ensure_future(self.housekeeping())]
        if self.cfg.get("listing_url"):   # beats only while public; a realm may switch later
            tasks.append(asyncio.ensure_future(self.heartbeat_loop(self.heartbeat_every)))
        try:
            while not self.stop_ev.is_set():
                started = time.monotonic()
                retry = None
                try:
                    retry = await self.session()
                except (OSError, ws.WSClosed, ws.HandshakeError, asyncio.TimeoutError, ValueError) as e:
                    self.save_state(connected=False, last_error=f"{type(e).__name__}: {e}")
                    log.warning("relay connection: %s", e)
                self.close_all()
                if self.stop_ev.is_set():
                    break
                if time.monotonic() - started > 60:
                    backoff = 1
                wait = retry if retry else backoff
                backoff = min(backoff * 2, 60)
                wait = wait * (0.8 + 0.4 * random.random())
                log.info("reconnecting in %.0f s", wait)
                try:
                    await asyncio.wait_for(self.stop_ev.wait(), wait)
                except asyncio.TimeoutError:
                    pass
        finally:
            for t in tasks:
                t.cancel()
            self.close_all()

    async def session(self):
        url = self.cfg["relay_url"]
        self.ws = await ws.connect(url, headers={"User-Agent": VERSION}, ssl_context=self.ssl_context,
                                   max_message=mux.MAX_CHUNK * 2)
        op, msg = await asyncio.wait_for(self.ws.recv(), 15)
        ch = json.loads(msg)
        hello = {"realm_id": self.cfg["realm_id"], "pubkey": self.pub.hex(), "challenge": ch["challenge"],
                 "relay": ch["relay"], "name": self.cfg["name"], "visibility": self.cfg["visibility"],
                 "invite_sha256": self.invite_sha(), "signup": self.cfg.get("signup", "invite"),
                 "version": VERSION, "ts": int(time.time())}
        if self.host_sha():
            hello["host_sha256"] = self.host_sha()
        if self.pair_sha():
            hello["pair_sha256"] = self.pair_sha()
        await self.ws.send(json.dumps({"hello": hello, "sig": keys.sign_doc(self.secret, hello, keys.CTX_RELAY_LOGIN)}))
        op, msg = await asyncio.wait_for(self.ws.recv(), 15)
        doc = json.loads(msg)
        if "error" in doc:
            self.save_state(connected=False, last_error="relay refused: " + str(doc["error"]))
            log.error("relay refused this realm: %s", doc["error"])
            await self.ws.close()
            return int(doc.get("retry") or 60)
        self.welcome = doc["welcome"]
        self.last_pong = time.monotonic()
        self.save_state(connected=True, since=int(time.time()), last_error=None, **{
            k: self.welcome.get(k) for k in ("address", "auth_port", "world_port", "shared_auth_port",
                                              "join_url", "status_url", "limits")})
        log.info("connected to %s: realm list address %s:%s", ch["relay"], self.welcome["address"],
                 self.welcome["world_port"])
        self.address_done = None
        pinger = asyncio.ensure_future(self.pinger())
        try:
            await self.loop()
        finally:
            pinger.cancel()
            self.save_state(connected=False)
        return None

    async def pinger(self):
        n = 0
        while True:
            await asyncio.sleep(self.ping_every)
            n += 1
            if time.monotonic() - self.last_pong > 3.25 * self.ping_every:
                log.warning("relay stopped answering pings; reconnecting")
                self.ws.abort()
                return
            self.ws.send_nowait(json.dumps({"ping": n}))

    async def loop(self):
        while True:
            op, msg = await self.ws.recv()
            if op == ws.OP_BIN:
                try:
                    kind, sid, payload = mux.unpack(msg)
                except ValueError:
                    continue
                if kind == OPEN:
                    try:
                        port = mux.parse_open(payload)
                    except ValueError:
                        continue
                    if port not in self.services:
                        self.ws.send_nowait(mux.pack(CLOSE, sid))
                        continue
                    st = LocalStream(sid, port)
                    self.streams[sid] = st
                    asyncio.ensure_future(self.local(st))
                elif kind == DATA:
                    st = self.streams.get(sid)
                    if not st or st.closed:
                        continue
                    if st.writer:
                        st.writer.write(payload)
                        if st.writer.transport.get_write_buffer_size() > mux.MAX_BUFFER:
                            self.end(st, tell=True)
                    else:
                        st.queue.append(payload)
                        st.queued += len(payload)
                        if st.queued > mux.MAX_BUFFER:
                            self.end(st, tell=True)
                elif kind == CLOSE:
                    st = self.streams.get(sid)
                    if st:
                        self.end(st, tell=False)
                continue
            try:
                doc = json.loads(msg)
            except ValueError:
                continue
            if "pong" in doc:
                self.last_pong = time.monotonic()
            elif "req" in doc:
                asyncio.ensure_future(self.answer(doc))
            elif "bye" in doc:
                log.info("relay says: %s", doc["bye"])

    async def local(self, st: LocalStream):
        host, port = self.services[st.port]
        try:
            reader, writer = await asyncio.wait_for(self.opener(host, port), 10)
        except (OSError, asyncio.TimeoutError) as e:
            log.warning("cannot reach %s:%d for a player (%s); is the realm running?", host, port, e)
            self.end(st, tell=True)
            return
        if st.closed:
            writer.close()
            return
        try:
            writer.get_extra_info("socket").setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        except (OSError, AttributeError):
            pass
        st.writer = writer
        for chunk in st.queue:
            writer.write(chunk)
        st.queue, st.queued = [], 0
        try:
            while not st.closed:
                data = await reader.read(mux.MAX_CHUNK)
                if not data:
                    break
                self.ws.send_nowait(mux.pack(DATA, st.sid, data))
                if self.ws.buffered() > mux.MAX_BUFFER:
                    await self.ws.writer.drain()
        except (ConnectionError, OSError, ws.WSClosed):
            pass
        finally:
            self.end(st, tell=True)

    def end(self, st, tell):
        if st.closed:
            return
        st.closed = True
        self.streams.pop(st.sid, None)
        if st.writer:
            try:
                st.writer.close()
            except (OSError, RuntimeError):
                pass
        if tell and self.ws and not self.ws.closed:
            try:
                self.ws.send_nowait(mux.pack(CLOSE, st.sid))
            except ws.WSClosed:
                pass

    def close_all(self):
        for st in list(self.streams.values()):
            self.end(st, tell=False)
        if self.ws:
            self.ws.abort()

    # -------------------------------------------------------------- requests from the relay
    async def answer(self, doc):
        rid = doc["req"]
        res = {"res": rid, "ok": False}
        try:
            if doc.get("op") == "status":
                res = {"res": rid, "ok": True, "status": await self.status()}
            elif doc.get("op") == "create_account":
                gm = (self.cfg.get("gm_name") or "").upper()
                if self.cfg.get("signup", "invite") == "off" or not self.db or self.official():
                    res["error"] = "off"
                elif gm and str(doc.get("username", "")).upper() == gm and doc.get("host") is not True:
                    res["error"] = "reserved"   # the GM's name: only from the host's own link
                    log.info("refused a signup for the GM account name %s (not from the host's link)", gm)
                else:
                    r = await asyncio.to_thread(self.db.create_account, doc["username"], doc["salt"], doc["verifier"])
                    res = {"res": rid, "ok": r == "ok", "error": None if r == "ok" else r}
                    log.info("account %s for a player: %s", doc["username"], r)
        except Exception as e:  # report, never crash the tunnel
            log.warning("request %s failed: %s", doc.get("op"), e)
            res["error"] = "failed"
        if self.ws and not self.ws.closed:
            self.ws.send_nowait(json.dumps(res))

    @staticmethod
    def status_from_url(url):
        """players / bots / uptime_s from a status document (format openvanilla-status-1, e.g. the play page's
        /wrath/status.json). Only plain counts are taken."""
        req = urllib.request.Request(url, headers={"Accept": "application/json", "User-Agent": VERSION})
        with urllib.request.urlopen(req, timeout=4) as r:
            doc = json.loads(r.read(65536).decode("utf-8"))
        out = {}
        for k in ("players", "bots", "uptime_s"):
            v = doc.get(k) if isinstance(doc, dict) else None
            if isinstance(v, int) and not isinstance(v, bool) and 0 <= v < 1_000_000:
                out[k] = v
        return out

    async def world_up(self):
        host, port = self.services[8085]
        try:
            _, w = await asyncio.wait_for(self.opener(host, port), 3)
            w.close()
            return True
        except (OSError, asyncio.TimeoutError):
            return False

    async def status(self):
        st = {"online": await self.world_up(), "players": None, "bots": None, "uptime_s": None,
              "profile": self.cfg.get("profile"),
              "build": cores.version((self.cfg.get("record") or {}).get("build"))}   # the client players need
        if self.db and not self.cfg.get("status_url"):
            try:
                st.update(await asyncio.to_thread(self.db.status))
            except Exception as e:
                log.debug("status from db: %s", e)
        elif self.cfg.get("status_url"):
            try:
                st.update(await asyncio.to_thread(self.status_from_url, self.cfg["status_url"]))
            except Exception as e:  # the numbers are optional; online comes from the world port above
                log.debug("status from %s: %s", self.cfg["status_url"], e)
        if self.cfg.get("claim"):
            st["claim"] = self.cfg["claim"]
        return st

    # -------------------------------------------------------------- background work
    async def housekeeping(self):
        gm_done = False
        while True:
            # host.json edited (Switch to public, new invite, claim token): tell the relay
            m = self._mtime()
            if m != self.cfg_mtime:
                self.cfg_mtime = m
                new = read_json(self.cfg_path) or self.cfg
                changed = {k for k in ("name", "visibility", "invite_secret", "signup", "host_secret", "claim")
                           if new.get(k) != self.cfg.get(k)}
                self.cfg = new
                if changed and self.ws and not self.ws.closed:
                    upd = {"name": new["name"], "visibility": new["visibility"], "invite_sha256": self.invite_sha(),
                           "signup": new.get("signup", "invite")}
                    if self.host_sha():
                        upd["host_sha256"] = self.host_sha()
                    if self.pair_sha():
                        upd["pair_sha256"] = self.pair_sha()
                    self.ws.send_nowait(json.dumps({"update": upd}))
                    log.info("told the relay: %s changed", ", ".join(sorted(changed)))
                if "name" in changed:
                    self.address_done = None
            if self.db and self.welcome and self.address_done is None and not self.official():
                try:
                    addr = await asyncio.to_thread(resolve_ipv4, self.welcome["address"])
                    r = await asyncio.to_thread(self.db.set_realm_address, self.cfg["name"], addr,
                                                int(self.welcome["world_port"]))
                    if r in ("updated", "unchanged"):
                        self.address_done = time.time()
                        log.info("realm list address: %s:%s (%s)", addr, self.welcome["world_port"], r)
                        self.save_state(realmlist_ok=True, realmlist_address=addr)
                except Exception as e:
                    self.save_state(realmlist_ok=False, realmlist_error=str(e)[:200])
                    log.info("realm list not set yet (database starting?): %s", e)
            if self.db and not gm_done and self.cfg.get("gm") and not self.official():
                try:
                    g = self.cfg["gm"]
                    r = await asyncio.to_thread(self.db.create_account, g["username"], g["salt"], g["verifier"], 3)
                    gm_done = r in ("ok", "taken")
                    if r == "ok":
                        log.info("host account %s created (GM)", g["username"])
                except Exception as e:
                    log.debug("host account later: %s", e)
            gm_name = self.cfg.get("gm_name")
            if self.db and gm_name and self.gm_done != gm_name and not self.official():
                try:
                    r = await asyncio.to_thread(self.db.grant_gm, gm_name, 3)
                    if r in ("ok", "unchanged"):
                        self.gm_done = gm_name
                        log.info("%s is the GM of this realm (%s)", gm_name.upper(), r)
                    self.save_state(gm_account=gm_name.upper(), gm_ok=r in ("ok", "unchanged"))
                except Exception as e:
                    log.debug("GM rights later: %s", e)
            if self.address_done and time.time() - self.address_done > 300:
                self.address_done = None   # re-check every 5 minutes (someone may have reset it)
            await asyncio.sleep(self.tick)

    def _http_post(self, url, body):
        req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json",
                                                              "User-Agent": VERSION}, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=15) as r:
                return r.status, r.read()
        except urllib.error.HTTPError as e:
            return e.code, e.read()

    def beat(self, status):
        self.seq = max(self.seq + 1, int(time.time() * 1000))
        beat = {"v": 1, "realm_id": self.cfg["realm_id"], "pubkey": self.pub.hex(), "seq": self.seq,
                "ts": int(time.time()), "relay": (self.welcome or {}).get("address"),
                "record": self.cfg.get("record") or {"name": self.cfg["name"]},
                "status": {k: status.get(k) for k in ("online", "players", "bots", "uptime_s")}}
        if self.cfg.get("claim"):
            beat["claim"] = self.cfg["claim"]
        return {"beat": beat, "sig": keys.sign_doc(self.secret, beat, keys.CTX_HEARTBEAT)}

    async def heartbeat_loop(self, every=60):
        while True:
            beat_now = self.cfg.get("visibility") == "public" and self.welcome and self.ws and not self.ws.closed
            if beat_now:
                try:
                    body = json.dumps(self.beat(await self.status())).encode()
                    code, reply = await asyncio.to_thread(self.http_post, self.cfg["listing_url"], body)
                    self.save_state(listing_status=code, listing_reply=reply[:300].decode("utf-8", "replace"))
                    if code != 200:
                        log.warning("listing answered %s: %s", code, reply[:200])
                except Exception as e:
                    self.save_state(listing_status=None, listing_reply=str(e)[:200])
                    log.info("heartbeat failed: %s", e)
            # not connected yet: look again soon, so a new realm is listed seconds after it connects, not a minute
            await asyncio.sleep(every if beat_now else min(every, 2))


def main(argv=None):
    ap = argparse.ArgumentParser(description="Leyline host agent (relay tunnel)")
    ap.add_argument("--state", default=os.environ.get("WU_STATE", "/state"))
    a = ap.parse_args(argv)
    logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"), format="%(asctime)s %(levelname)s %(message)s")
    from .coredb import open_db   # WU_CORE: the profile's core (cores.py); AzerothCore's RealmDB when unset
    db = open_db()
    agent = Agent(a.state, db=db)
    try:
        asyncio.run(agent.run())
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
