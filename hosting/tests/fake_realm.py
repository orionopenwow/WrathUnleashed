"""A fake AzerothCore 3.3.5a realm for tests: authserver (SRP6 server side, realm list) and a
worldserver (auth challenge, session digest check, RC4 header cipher, character list/create,
player login, ping, logout). Strict about sizes and proofs, so a client bug fails here the way it
would against the real core. Accounts come from (salt, verifier) pairs, as in acore_auth.account.
"""
import asyncio
import hashlib
import os
import struct
import zlib

from wunet import srp6, wire335 as w


class FakeRealm:
    def __init__(self, realm_name="Fake Realm", world_address="127.0.0.1:8085", realm_id=1, logout_delay=0.2):
        self.accounts = {}          # USER -> (salt, verifier)
        self.sessions = {}          # USER -> K (set by a successful logon)
        self.chars = {}             # USER -> list of dicts
        self.realm_name, self.world_address, self.realm_id = realm_name, world_address, realm_id
        self.logout_delay = logout_delay
        self.events = []
        self.auth_server = self.world_server = None
        self.next_guid = 1

    def add_account(self, user, password):
        self.accounts[user.upper()] = srp6.make_verifier(user, password)

    def add_account_raw(self, user, salt: bytes, verifier: bytes):
        self.accounts[user.upper()] = (salt, verifier)

    async def start(self, host="127.0.0.1"):
        self.auth_server = await asyncio.start_server(self.on_auth, host, 0)
        self.world_server = await asyncio.start_server(self.on_world, host, 0)
        return self

    @property
    def auth_port(self):
        return self.auth_server.sockets[0].getsockname()[1]

    @property
    def world_port(self):
        return self.world_server.sockets[0].getsockname()[1]

    async def stop(self):
        for s in (self.auth_server, self.world_server):
            if s:
                s.close()

    # ------------------------------------------------------------------ authserver
    async def on_auth(self, reader, writer):
        try:
            await self._auth(reader, writer)
        except (asyncio.IncompleteReadError, ConnectionError, ValueError) as e:
            self.events.append(("auth_error", str(e)))
        finally:
            writer.close()

    async def _auth(self, reader, writer):
        head = await reader.readexactly(4)
        if head[0] != 0x00:
            raise ValueError("expected a logon challenge")
        size = struct.unpack_from("<H", head, 2)[0]
        body = await reader.readexactly(size)
        if body[:4] != b"WoW\x00" or struct.unpack_from("<H", body, 7)[0] != w.BUILD:
            writer.write(bytes([0, 0, 0x09]))
            return
        ilen = body[29]
        if size != 30 + ilen:
            raise ValueError("challenge size field wrong")
        user = body[30:30 + ilen].decode()
        acct = self.accounts.get(user)
        if not acct:
            writer.write(bytes([0, 0, 0x04]))
            self.events.append(("unknown_account", user))
            return
        srv = srp6.Server(user, *acct)
        writer.write(bytes([0, 0, 0]) + srv.B + bytes([1, srp6.G, 32]) + srp6.N_BYTES + acct[0] + os.urandom(16) + b"\x00")
        proof = await reader.readexactly(75)
        if proof[0] != 0x01:
            raise ValueError("expected a logon proof")
        A, M1 = proof[1:33], proof[33:53]
        res = srv.verify(A, M1)
        if not res:
            writer.write(bytes([1, 0x04, 3, 0]))
            self.events.append(("bad_proof", user))
            return
        K, M2 = res
        self.sessions[user] = K
        writer.write(bytes([1, 0]) + M2 + struct.pack("<IIH", 0x00800000, 0, 0))
        self.events.append(("logon", user))
        while True:
            req = await reader.readexactly(5)
            if req[0] != 0x10:
                raise ValueError("expected a realm list request")
            writer.write(w.build_realm_list([{"name": self.realm_name, "address": self.world_address,
                                              "id": self.realm_id, "flags": 0}]))
            await writer.drain()

    # ------------------------------------------------------------------ worldserver
    async def on_world(self, reader, writer):
        try:
            await self._world(reader, writer)
        except (asyncio.IncompleteReadError, ConnectionError, ValueError) as e:
            self.events.append(("world_error", str(e)))
        finally:
            writer.close()

    async def _world(self, reader, writer):
        seed = os.urandom(4)
        body = struct.pack("<I", 1) + seed + os.urandom(32)
        writer.write(struct.pack(">H", len(body) + 2) + struct.pack("<H", w.SMSG_AUTH_CHALLENGE) + body)
        await writer.drain()
        enc = dec = None

        async def recv():
            h = await reader.readexactly(6)
            if dec:
                h = dec.apply(h)
            size = struct.unpack_from(">H", h)[0]
            op = struct.unpack_from("<I", h, 2)[0]
            if size < 4 or size > 10240:
                raise ValueError(f"bad client packet size {size}")
            return op, await reader.readexactly(size - 4)

        def send(op, b=b""):
            hh = struct.pack(">H", len(b) + 2) + struct.pack("<H", op)
            writer.write((enc.apply(hh) if enc else hh) + b)

        op, b = await recv()
        if op != w.CMSG_AUTH_SESSION:
            raise ValueError("expected CMSG_AUTH_SESSION")
        build, _ls = struct.unpack_from("<II", b)
        end = b.index(b"\x00", 8)
        user = b[8:end].decode()
        p = end + 1
        _lst, client_seed, _reg, _bg, realm = struct.unpack_from("<I4sIII", b, p)
        p += 20 + 8
        digest = b[p:p + 20]
        p += 20
        (asize,) = struct.unpack_from("<I", b, p)
        addons = zlib.decompress(b[p + 4:])
        if len(addons) != asize or build != w.BUILD or realm != self.realm_id:
            raise ValueError("bad auth session fields")
        K = self.sessions.get(user)
        if not K or hashlib.sha1(user.encode() + bytes(4) + client_seed + seed + K).digest() != digest:
            raise ValueError("session digest mismatch")
        enc, dec = w.header_crypt(K, server=True)
        send(w.SMSG_AUTH_RESPONSE, bytes([w.AUTH_OK]) + struct.pack("<IBIB", 0, 0, 0, 2))
        send(0x2EF, b"\x00" * 4)  # noise: something the client must skip (SMSG_ADDON_INFO-like)
        await writer.drain()
        self.events.append(("world_auth", user))
        chars = self.chars.setdefault(user, [])
        while True:
            op, b = await recv()
            if op == w.CMSG_CHAR_ENUM:
                out = bytes([len(chars)])
                for c in chars:
                    out += struct.pack("<Q", c["guid"]) + c["name"].encode() + b"\x00"
                    out += bytes([c["race"], c["class"], 0, 0, 0, 0, 0, 0, c["level"]])
                    out += struct.pack("<II", 12, 0) + struct.pack("<fff", -8949.95, -132.493, 83.5312)
                    out += struct.pack("<IIIB", 0, 0, 0, 1) + struct.pack("<III", 0, 0, 0) + bytes(23 * 9)
                send(w.SMSG_CHAR_ENUM, out)
            elif op == w.CMSG_CHAR_CREATE:
                end = b.index(b"\x00")
                name = b[:end].decode()
                if len(b) != end + 1 + 9:
                    raise ValueError("char create size")
                if not name.isalpha() or any(c["name"].lower() == name.lower() for v in self.chars.values() for c in v):
                    send(w.SMSG_CHAR_CREATE, bytes([0x32]))  # name in use
                else:
                    chars.append({"guid": self.next_guid, "name": name.capitalize(), "race": b[end + 1],
                                  "class": b[end + 2], "level": 1})
                    self.next_guid += 1
                    send(w.SMSG_CHAR_CREATE, bytes([w.CHAR_CREATE_SUCCESS]))
                    self.events.append(("char_create", name))
            elif op == w.CMSG_PLAYER_LOGIN:
                (guid,) = struct.unpack_from("<Q", b)
                if not any(c["guid"] == guid for c in chars):
                    send(w.SMSG_CHARACTER_LOGIN_FAILED, b"\x01")
                else:
                    send(w.SMSG_TIME_SYNC_REQ, struct.pack("<I", 0))
                    big = os.urandom(40000)  # a large packet: 5-byte server header
                    hh = struct.pack(">I", (len(big) + 2) | 0x800000)[1:] + struct.pack("<H", 0x0A9)
                    writer.write(enc.apply(bytes([hh[0] | 0x80]) + hh[1:]) + big)
                    send(w.SMSG_LOGIN_VERIFY_WORLD, struct.pack("<Iffff", 0, -8949.95, -132.493, 83.5312, 0.0))
                    self.events.append(("enter_world", guid))
            elif op == w.CMSG_PING:
                send(w.SMSG_PONG, b[:4])
            elif op == w.CMSG_TIME_SYNC_RESP:
                self.events.append(("time_sync", user))
            elif op == w.CMSG_LOGOUT_REQUEST:
                send(w.SMSG_LOGOUT_RESPONSE, struct.pack("<IB", 0, 0))
                await writer.drain()
                await asyncio.sleep(self.logout_delay)
                send(w.SMSG_LOGOUT_COMPLETE)
                self.events.append(("logout", user))
            await writer.drain()


# ---------------------------------------------------------------------- container mode (e2e --fake)
async def _serve(a):
    import json as _json
    r = FakeRealm(realm_name=a.name)
    for spec in a.account:
        u, p = spec.split(":", 1)
        r.add_account(u, p)
    r.auth_server = await asyncio.start_server(r.on_auth, "0.0.0.0", a.auth_port)
    r.world_server = await asyncio.start_server(r.on_world, "0.0.0.0", a.world_port)
    print(f"fake realm on {a.auth_port}/{a.world_port}", flush=True)
    while True:  # advertise what the agent was told by the relay (it writes relay-state.json)
        try:
            st = _json.load(open(a.advertise_from))
            if st.get("connected"):
                addr = st.get("realmlist_address") or st.get("address")
                import socket as _s
                try:
                    addr = _s.gethostbyname(st.get("address"))
                except OSError:
                    pass
                r.world_address = f"{addr}:{st['world_port']}"
        except (OSError, ValueError, KeyError):
            pass
        await asyncio.sleep(1)


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description="fake 3.3.5a realm for the docker e2e (no game data needed)")
    ap.add_argument("--auth-port", type=int, default=3724)
    ap.add_argument("--world-port", type=int, default=8085)
    ap.add_argument("--name", default="E2E Fake Realm")
    ap.add_argument("--account", action="append", default=[], help="USER:PASS")
    ap.add_argument("--advertise-from", default="/state/relay-state.json")
    asyncio.run(_serve(ap.parse_args()))
