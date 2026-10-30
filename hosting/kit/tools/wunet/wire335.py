"""A headless 3.3.5a (build 12340) client: SRP6 logon, realm list, world login, character list,
character create, enter the world, log out. asyncio, standard library only.

Used by the end-to-end test (through the relay, against real AzerothCore), the soak test, the
host self-check (a logon challenge round trip through the relay) and the unit tests (against
tests/fake_realm.py). Packet layouts follow AzerothCore 3.3.5a (AuthSession.cpp, WorldSocket.cpp,
CharacterHandler.cpp); the header cipher follows benilla-srp's wotlk_header.rs.

    python -m wunet.wire335 HOST[:PORT] USER PASS [--create NAME] [--enter] [--logout]
"""
import argparse
import asyncio
import hashlib
import hmac
import json
import os
import random
import struct
import sys
import zlib

from . import srp6

BUILD = 12340
# 3.3.5a world opcodes (AzerothCore Opcodes.h)
CMSG_CHAR_CREATE = 0x036
CMSG_CHAR_ENUM = 0x037
SMSG_CHAR_CREATE = 0x03A
SMSG_CHAR_ENUM = 0x03B
CMSG_PLAYER_LOGIN = 0x03D
SMSG_CHARACTER_LOGIN_FAILED = 0x041
CMSG_LOGOUT_REQUEST = 0x04B
SMSG_LOGOUT_RESPONSE = 0x04C
SMSG_LOGOUT_COMPLETE = 0x04D
CMSG_PING = 0x1DC
SMSG_PONG = 0x1DD
SMSG_AUTH_CHALLENGE = 0x1EC
CMSG_AUTH_SESSION = 0x1ED
SMSG_AUTH_RESPONSE = 0x1EE
SMSG_LOGIN_VERIFY_WORLD = 0x236
SMSG_TIME_SYNC_REQ = 0x390
CMSG_TIME_SYNC_RESP = 0x391

AUTH_OK = 0x0C
AUTH_WAIT_QUEUE = 0x1B
CHAR_CREATE_SUCCESS = 0x2F

# The two RC4 seeds (AzerothCore AuthCrypt.cpp; benilla-srp wotlk_header.rs).
CLIENT_TO_SERVER_SEED = bytes.fromhex("C2B3723CC6AED9B5343C53EE2F4367CE")
SERVER_TO_CLIENT_SEED = bytes.fromhex("CC98AE04E897EACA12DDC09342915357")

LOGON_RESULTS = {0x03: "account closed (banned)", 0x04: "unknown account or wrong password",
                 0x05: "wrong password", 0x06: "account already online", 0x08: "database busy",
                 0x09: "client version not accepted", 0x0C: "account suspended"}


class WowError(Exception):
    pass


# ---------------------------------------------------------------------------- crypto
class Arc4:
    def __init__(self, key: bytes, drop: int = 1024):
        S = list(range(256))
        j = 0
        for i in range(256):
            j = (j + S[i] + key[i % len(key)]) & 0xFF
            S[i], S[j] = S[j], S[i]
        self.S, self.i, self.j = S, 0, 0
        if drop:
            self.apply(bytes(drop))

    def apply(self, data: bytes) -> bytes:
        S, i, j = self.S, self.i, self.j
        out = bytearray(data)
        for n in range(len(out)):
            i = (i + 1) & 0xFF
            j = (j + S[i]) & 0xFF
            S[i], S[j] = S[j], S[i]
            out[n] ^= S[(S[i] + S[j]) & 0xFF]
        self.i, self.j = i, j
        return bytes(out)


def header_crypt(session_key: bytes, server: bool):
    """(encrypt, decrypt) RC4 streams for one end of a world connection."""
    c2s = Arc4(hmac.new(CLIENT_TO_SERVER_SEED, session_key, hashlib.sha1).digest())
    s2c = Arc4(hmac.new(SERVER_TO_CLIENT_SEED, session_key, hashlib.sha1).digest())
    return (s2c, c2s) if server else (c2s, s2c)


# ---------------------------------------------------------------------------- packets
VERSIONS = {12340: (3, 3, 5), 5875: (1, 12, 1)}   # build -> the version bytes a stock client of that build sends
VERSIONS.update({8606: (2, 4, 3), 15595: (4, 3, 4), 18414: (5, 4, 8)})   # the host kit's other profiles (cores.py)


def logon_challenge(user: str, build: int = BUILD) -> bytes:
    I = user.upper().encode()
    body = (b"WoW\x00" + bytes(VERSIONS.get(build, (3, 3, 5))) + struct.pack("<H", build) + b"68x\x00" + b"niW\x00"
            + b"SUne" + struct.pack("<II", 0, 0x0100007F) + bytes([len(I)]) + I)
    return bytes([0x00, 0x08]) + struct.pack("<H", len(body)) + body


def parse_realm_list(body: bytes):
    """CMD_REALM_LIST reply body (after cmd and size) -> list of realm dicts (3.3.5a layout)."""
    pos = 4
    (count,) = struct.unpack_from("<H", body, pos)
    pos += 2
    realms = []
    for _ in range(count):
        rtype, locked, flags = body[pos], body[pos + 1], body[pos + 2]
        pos += 3
        end = body.index(b"\x00", pos)
        name = body[pos:end].decode("utf-8", "replace")
        pos = end + 1
        end = body.index(b"\x00", pos)
        address = body[pos:end].decode("ascii", "replace")
        pos = end + 1
        (pop,) = struct.unpack_from("<f", body, pos)
        pos += 4
        chars, tz, rid = body[pos], body[pos + 1], body[pos + 2]
        pos += 3
        build = None
        if flags & 0x04:
            build = struct.unpack_from("<H", body, pos + 3)[0]
            pos += 5
        realms.append({"type": rtype, "locked": locked, "flags": flags, "name": name, "address": address,
                       "population": pop, "characters": chars, "timezone": tz, "id": rid, "build": build})
    return realms


def build_realm_list(realms) -> bytes:
    """Server side (fake authserver): CMD_REALM_LIST reply."""
    body = struct.pack("<IH", 0, len(realms))
    for r in realms:
        body += bytes([r.get("type", 0), 0, r.get("flags", 0)]) + r["name"].encode() + b"\x00"
        body += r["address"].encode() + b"\x00" + struct.pack("<f", r.get("population", 0.0))
        body += bytes([r.get("characters", 0), r.get("timezone", 1), r.get("id", 1)])
    body += struct.pack("<H", 0x0010)
    return bytes([0x10]) + struct.pack("<H", len(body)) + body


def split_host_port(addr: str, default: int):
    if addr.count(":") == 1:
        h, p = addr.rsplit(":", 1)
        return h, int(p)
    return addr, default


# ---------------------------------------------------------------------------- logon
async def _read(reader, n, timeout):
    return await asyncio.wait_for(reader.readexactly(n), timeout)


async def logon(host: str, port: int, user: str, password: str, timeout: float = 20, opener=None):
    """SRP6 logon + realm list. Returns (session_key, realms)."""
    opener = opener or asyncio.open_connection
    reader, writer = await asyncio.wait_for(opener(host, port), timeout)
    try:
        writer.write(logon_challenge(user))
        await writer.drain()
        head = await _read(reader, 3, timeout)
        if head[0] != 0x00:
            raise WowError(f"unexpected reply {head[0]:#x} to the logon challenge")
        if head[2] != 0x00:
            raise WowError("logon refused: " + LOGON_RESULTS.get(head[2], f"code {head[2]:#x}"))
        B = await _read(reader, 32, timeout)
        glen = (await _read(reader, 1, timeout))[0]
        g = int.from_bytes(await _read(reader, glen, timeout), "little")
        nlen = (await _read(reader, 1, timeout))[0]
        N = int.from_bytes(await _read(reader, nlen, timeout), "little")
        salt = await _read(reader, 32, timeout)
        await _read(reader, 16, timeout)  # version challenge
        sec = (await _read(reader, 1, timeout))[0]
        if sec:
            raise WowError(f"account wants extra security (flags {sec:#x}): not supported here")
        c = srp6.Client(user, password)
        A, M1 = c.process(B, salt, g, N)
        writer.write(bytes([0x01]) + A + M1 + bytes(20) + bytes([0, 0]))
        await writer.drain()
        h = await _read(reader, 2, timeout)
        if h[0] != 0x01:
            raise WowError(f"unexpected reply {h[0]:#x} to the logon proof")
        if h[1] != 0:
            raise WowError("logon refused: " + LOGON_RESULTS.get(h[1], f"code {h[1]:#x}"))
        rest = await _read(reader, 30, timeout)  # M2(20) flags(4) survey(4) loginflags(2)
        if not c.check_server(rest[:20]):
            raise WowError("server proof did not match (not the real server?)")
        writer.write(bytes([0x10, 0, 0, 0, 0]))
        await writer.drain()
        h = await _read(reader, 3, timeout)
        if h[0] != 0x10:
            raise WowError(f"unexpected reply {h[0]:#x} to the realm list request")
        size = struct.unpack_from("<H", h, 1)[0]
        body = await _read(reader, size, timeout)
        return c.K, parse_realm_list(body)
    finally:
        writer.close()


async def logon_probe(host: str, port: int, timeout: float = 10, opener=None, build: int = BUILD) -> int:
    """Send a logon challenge for a made-up account; return the result code (0x04 from a real
    authserver: 'unknown account'). Proves the whole path to the authserver works, no login needed."""
    opener = opener or asyncio.open_connection
    reader, writer = await asyncio.wait_for(opener(host, port), timeout)
    try:
        writer.write(logon_challenge("WUPROBE" + "".join(random.choice("ABCDEFGHJKLMNPQRSTUVWXYZ") for _ in range(6)),
                                     build))
        await writer.drain()
        head = await _read(reader, 3, timeout)
        if head[0] != 0x00:
            raise WowError(f"unexpected reply {head[0]:#x}")
        return head[2]
    finally:
        writer.close()


# ---------------------------------------------------------------------------- world
class World:
    def __init__(self, reader, writer, timeout=30):
        self.reader, self.writer, self.timeout = reader, writer, timeout
        self.enc = self.dec = None
        self.log = []

    def send(self, opcode: int, body: bytes = b"") -> None:
        head = struct.pack(">H", len(body) + 4) + struct.pack("<I", opcode)
        if self.enc:
            head = self.enc.apply(head)
        self.writer.write(head + body)

    async def recv(self):
        b0 = await _read(self.reader, 1, self.timeout)
        if self.dec:
            b0 = self.dec.apply(b0)
        if b0[0] & 0x80:
            rest = await _read(self.reader, 4, self.timeout)
            if self.dec:
                rest = self.dec.apply(rest)
            size = ((b0[0] & 0x7F) << 16) | (rest[0] << 8) | rest[1]
            opcode = struct.unpack_from("<H", rest, 2)[0]
        else:
            rest = await _read(self.reader, 3, self.timeout)
            if self.dec:
                rest = self.dec.apply(rest)
            size = (b0[0] << 8) | rest[0]
            opcode = struct.unpack_from("<H", rest, 1)[0]
        body = await _read(self.reader, size - 2, self.timeout) if size > 2 else b""
        self.log.append(opcode)
        return opcode, body

    async def expect(self, *opcodes, within: float | None = None):
        """Read until one of opcodes arrives (answering time sync on the way)."""
        loop = asyncio.get_running_loop()
        deadline = loop.time() + (within or self.timeout)
        while True:
            left = deadline - loop.time()
            if left <= 0:
                raise WowError(f"no {[hex(o) for o in opcodes]} within {within or self.timeout}s")
            op, body = await asyncio.wait_for(self.recv(), left)
            if op == SMSG_TIME_SYNC_REQ and len(body) >= 4:
                self.send(CMSG_TIME_SYNC_RESP, body[:4] + struct.pack("<I", int(loop.time() * 1000) & 0xFFFFFFFF))
            if op in opcodes:
                return op, body


async def world_session(host: str, port: int, user: str, session_key: bytes, realm_id: int = 1,
                        timeout: float = 30, opener=None) -> World:
    opener = opener or asyncio.open_connection
    reader, writer = await asyncio.wait_for(opener(host, port), timeout)
    w = World(reader, writer, timeout)
    op, body = await w.expect(SMSG_AUTH_CHALLENGE)
    server_seed = body[4:8]
    client_seed = os.urandom(4)
    account = user.upper().encode()
    digest = hashlib.sha1(account + bytes(4) + client_seed + server_seed + session_key).digest()
    addons = struct.pack("<II", 0, 0)  # no addons, time 0
    body = (struct.pack("<II", BUILD, 0) + account + b"\x00" + struct.pack("<I", 0) + client_seed
            + struct.pack("<III", 0, 0, realm_id) + struct.pack("<Q", 0) + digest
            + struct.pack("<I", len(addons)) + zlib.compress(addons))
    w.send(CMSG_AUTH_SESSION, body)
    await writer.drain()
    w.enc, w.dec = header_crypt(session_key, server=False)
    op, body = await w.expect(SMSG_AUTH_RESPONSE)
    if not body or body[0] not in (AUTH_OK, AUTH_WAIT_QUEUE):
        raise WowError(f"world server refused the session (code {body[0] if body else None:#x})")
    if body[0] == AUTH_WAIT_QUEUE:
        op, body = await w.expect(SMSG_AUTH_RESPONSE, within=600)
    return w


def parse_char_enum(body: bytes):
    count, pos, out = body[0], 1, []
    for _ in range(count):
        (guid,) = struct.unpack_from("<Q", body, pos)
        pos += 8
        end = body.index(b"\x00", pos)
        name = body[pos:end].decode("utf-8", "replace")
        pos = end + 1
        race, cls, gender = body[pos], body[pos + 1], body[pos + 2]
        pos += 8  # race class gender skin face hair haircolor facialhair
        level = body[pos]
        pos += 1
        zone, mapid = struct.unpack_from("<II", body, pos)
        pos += 8 + 12 + 4 + 4 + 4 + 1 + 12  # map/zone, xyz, guild, flags, custom, firstlogin, pet
        pos += 23 * 9
        out.append({"guid": guid, "name": name, "race": race, "class": cls, "level": level,
                    "zone": zone, "map": mapid})
    return out


async def char_enum(w: World):
    w.send(CMSG_CHAR_ENUM)
    await w.writer.drain()
    _, body = await w.expect(SMSG_CHAR_ENUM)
    return parse_char_enum(body)


async def char_create(w: World, name: str, race=1, cls=1, gender=0):
    w.send(CMSG_CHAR_CREATE, name.encode() + b"\x00" + bytes([race, cls, gender, 0, 0, 0, 0, 0, 0]))
    await w.writer.drain()
    _, body = await w.expect(SMSG_CHAR_CREATE)
    return body[0]


async def enter_world(w: World, guid: int):
    w.send(CMSG_PLAYER_LOGIN, struct.pack("<Q", guid))
    await w.writer.drain()
    op, body = await w.expect(SMSG_LOGIN_VERIFY_WORLD, SMSG_CHARACTER_LOGIN_FAILED, within=60)
    if op == SMSG_CHARACTER_LOGIN_FAILED:
        raise WowError(f"character login failed (code {body[0] if body else None})")
    mapid, x, y, z, o = struct.unpack_from("<Iffff", body)
    return {"map": mapid, "x": x, "y": y, "z": z}


async def ping(w: World, n: int = 1):
    w.send(CMSG_PING, struct.pack("<II", n, 50))
    await w.writer.drain()
    _, body = await w.expect(SMSG_PONG)
    return struct.unpack_from("<I", body)[0]


async def logout(w: World, within: float = 40):
    w.send(CMSG_LOGOUT_REQUEST)
    await w.writer.drain()
    op, body = await w.expect(SMSG_LOGOUT_RESPONSE)
    reason = struct.unpack_from("<I", body)[0] if len(body) >= 4 else 0
    if reason:
        raise WowError(f"logout refused (reason {reason})")
    await w.expect(SMSG_LOGOUT_COMPLETE, within=within)


def random_name(prefix="Wu") -> str:
    return (prefix + "".join(random.choice("bcdfghjklmnpqrstvwxz") for _ in range(7))).capitalize()[:12]


async def full_run(auth_host, auth_port, user, password, create=None, enter=True, do_logout=True,
                   seconds=0.0, world_override=None, opener=None, timeout=30):
    """Log in, list realms, connect to the first realm, list characters, create one when asked or
    when none exist, enter the world, ping, stay `seconds`, log out. Returns a report dict."""
    rep = {"steps": []}
    K, realms = await logon(auth_host, auth_port, user, password, timeout=timeout, opener=opener)
    rep["steps"].append("logon")
    if not realms:
        raise WowError("the realm list is empty")
    realm = realms[0]
    rep["realm"] = realm
    rep["steps"].append("realm_list")
    whost, wport = split_host_port(world_override or realm["address"], 8085)
    w = await world_session(whost, wport, user, K, realm_id=realm["id"], timeout=timeout, opener=opener)
    rep["steps"].append("world_auth")
    try:
        chars = await char_enum(w)
        rep["steps"].append("char_enum")
        if create or not chars:
            name = create or random_name()
            code = await char_create(w, name)
            if code != CHAR_CREATE_SUCCESS:
                raise WowError(f"character create failed (code {code:#x})")
            rep["steps"].append("char_create")
            chars = await char_enum(w)
            chars = [c for c in chars if c["name"].lower() == name.lower()] or chars
        rep["character"] = chars[0]
        if enter:
            rep["position"] = await enter_world(w, chars[0]["guid"])
            rep["steps"].append("enter_world")
            await ping(w)
            rep["steps"].append("ping")
            if seconds:
                end = asyncio.get_running_loop().time() + seconds
                n = 2
                while asyncio.get_running_loop().time() < end:
                    await asyncio.sleep(min(25, max(0.0, end - asyncio.get_running_loop().time())))
                    await ping(w, n)
                    n += 1
            if do_logout:
                await logout(w)
                rep["steps"].append("logout")
    finally:
        w.writer.close()
    return rep


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("auth", help="HOST or HOST:PORT of the authserver (or the relay)")
    ap.add_argument("user")
    ap.add_argument("password")
    ap.add_argument("--create", help="character name to create (default: one when the account has none)")
    ap.add_argument("--no-enter", action="store_true")
    ap.add_argument("--no-logout", action="store_true")
    ap.add_argument("--seconds", type=float, default=0)
    ap.add_argument("--world", help="override the world address from the realm list")
    a = ap.parse_args(argv)
    host, port = split_host_port(a.auth, 3724)
    try:
        rep = asyncio.run(full_run(host, port, a.user, a.password, a.create, not a.no_enter,
                                   not a.no_logout, a.seconds, a.world))
    except (WowError, OSError, asyncio.TimeoutError, asyncio.IncompleteReadError) as e:
        print(json.dumps({"ok": False, "error": f"{type(e).__name__}: {e}"}))
        return 1
    rep["ok"] = True
    print(json.dumps(rep, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
