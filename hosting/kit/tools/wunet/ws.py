"""A small RFC 6455 WebSocket for asyncio streams (server upgrade and client connect), standard
library only. Enough for the relay: binary/text messages, fragmentation, ping/pong, close, a size
cap. No extensions (no compression: the game bytes don't compress and it would cost CPU).

Every frame is written with a single transport.write(), so tasks can share one socket without a
lock: asyncio never interleaves two write() calls.
"""
import asyncio
import base64
import hashlib
import os
import ssl as _ssl
import struct
import urllib.parse

GUID = b"258EAFA5-E914-47DA-95CA-C5AB0DC85B11"
OP_CONT, OP_TEXT, OP_BIN, OP_CLOSE, OP_PING, OP_PONG = 0x0, 0x1, 0x2, 0x8, 0x9, 0xA
MAX_HEADER = 16384


class WSClosed(Exception):
    def __init__(self, code=1006, reason=""):
        super().__init__(f"websocket closed ({code}) {reason}".strip())
        self.code, self.reason = code, reason


class HandshakeError(OSError):
    def __init__(self, status, msg=""):
        super().__init__(f"HTTP {status} {msg}".strip())
        self.status = status


def accept_key(key: str) -> str:
    return base64.b64encode(hashlib.sha1(key.encode() + GUID).digest()).decode()


class WebSocket:
    def __init__(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter, client: bool,
                 max_message: int = 1 << 20):
        self.reader, self.writer, self.client = reader, writer, client
        self.max_message = max_message
        self.closed = False
        self.close_code = None

    # ------------------------------------------------------------------ sending
    def _frame(self, op: int, data: bytes) -> bytes:
        n = len(data)
        b0 = 0x80 | op
        mask_bit = 0x80 if self.client else 0
        if n < 126:
            head = struct.pack("!BB", b0, mask_bit | n)
        elif n < 65536:
            head = struct.pack("!BBH", b0, mask_bit | 126, n)
        else:
            head = struct.pack("!BBQ", b0, mask_bit | 127, n)
        if self.client:  # clients must mask (RFC 6455 5.3)
            mk = os.urandom(4)
            return head + mk + _unmask(data, mk)
        return head + data

    def send_nowait(self, data, op: int | None = None) -> None:
        if self.closed:
            raise WSClosed(self.close_code or 1006)
        if op is None:
            op = OP_TEXT if isinstance(data, str) else OP_BIN
        if isinstance(data, str):
            data = data.encode("utf-8")
        self.writer.write(self._frame(op, bytes(data)))

    async def send(self, data, op: int | None = None) -> None:
        self.send_nowait(data, op)
        await self.writer.drain()

    def buffered(self) -> int:
        t = self.writer.transport
        return t.get_write_buffer_size() if t else 0

    async def close(self, code: int = 1000, reason: str = "") -> None:
        if not self.closed:
            try:
                self.writer.write(self._frame(OP_CLOSE, struct.pack("!H", code) + reason.encode()[:120]))
                await asyncio.wait_for(self.writer.drain(), 2)
            except (OSError, asyncio.TimeoutError, RuntimeError):
                pass
            self.closed, self.close_code = True, code
        self.abort()

    def abort(self) -> None:
        self.closed = True
        try:
            self.writer.close()
        except (OSError, RuntimeError):
            pass

    # ------------------------------------------------------------------ receiving
    async def _read_frame(self):
        h = await self.reader.readexactly(2)
        fin, op = h[0] & 0x80, h[0] & 0x0F
        if h[0] & 0x70:
            raise WSClosed(1002, "reserved bits")
        masked, n = h[1] & 0x80, h[1] & 0x7F
        if n == 126:
            n = struct.unpack("!H", await self.reader.readexactly(2))[0]
        elif n == 127:
            n = struct.unpack("!Q", await self.reader.readexactly(8))[0]
        if n > self.max_message:
            raise WSClosed(1009, "message too big")
        if masked != (0 if self.client else 0x80):
            raise WSClosed(1002, "bad masking")
        mk = await self.reader.readexactly(4) if masked else None
        data = await self.reader.readexactly(n) if n else b""
        if mk:
            data = _unmask(data, mk)
        return fin, op, data

    async def recv(self):
        """(opcode, payload) of the next text/binary message. Raises WSClosed at the end."""
        parts, first_op, total = [], None, 0
        try:
            while True:
                fin, op, data = await self._read_frame()
                if op >= 0x8:  # control frames, may sit between fragments
                    if op == OP_PING:
                        self.send_nowait(data, OP_PONG)
                    elif op == OP_CLOSE:
                        code = struct.unpack("!H", data[:2])[0] if len(data) >= 2 else 1005
                        if not self.closed:
                            try:
                                self.writer.write(self._frame(OP_CLOSE, data[:2]))
                            except (OSError, RuntimeError):
                                pass
                        self.closed, self.close_code = True, code
                        self.abort()
                        raise WSClosed(code, data[2:].decode("utf-8", "replace"))
                    continue
                if op == OP_CONT:
                    if first_op is None:
                        raise WSClosed(1002, "stray continuation")
                else:
                    if first_op is not None:
                        raise WSClosed(1002, "interleaved message")
                    first_op = op
                parts.append(data)
                total += len(data)
                if total > self.max_message:
                    raise WSClosed(1009, "message too big")
                if fin:
                    payload = b"".join(parts)
                    if first_op == OP_TEXT:
                        return OP_TEXT, payload.decode("utf-8")
                    return first_op, payload
        except (asyncio.IncompleteReadError, ConnectionError, OSError) as e:
            self.closed = True
            raise WSClosed(1006, type(e).__name__) from None


def _unmask(data: bytes, mk: bytes) -> bytes:
    n = len(data)
    if not n:
        return data
    key = (mk * (n // 4 + 1))[:n]
    return (int.from_bytes(data, "big") ^ int.from_bytes(key, "big")).to_bytes(n, "big")


# ---------------------------------------------------------------------- server side
async def server_upgrade(req, reader, writer, max_message=1 << 20, extra_headers=None) -> WebSocket:
    """Answer an already-parsed upgrade request (req.headers: lower-case dict) with 101."""
    key = req.headers.get("sec-websocket-key", "")
    if (req.headers.get("upgrade", "").lower() != "websocket" or not key
            or req.headers.get("sec-websocket-version") != "13"):
        raise HandshakeError(400, "not a websocket upgrade")
    lines = ["HTTP/1.1 101 Switching Protocols", "Upgrade: websocket", "Connection: Upgrade",
             f"Sec-WebSocket-Accept: {accept_key(key)}"]
    for k, v in (extra_headers or {}).items():
        lines.append(f"{k}: {v}")
    writer.write(("\r\n".join(lines) + "\r\n\r\n").encode())
    await writer.drain()
    return WebSocket(reader, writer, client=False, max_message=max_message)


# ---------------------------------------------------------------------- client side
async def connect(url: str, headers: dict | None = None, timeout: float = 15,
                  ssl_context: _ssl.SSLContext | None = None, max_message=1 << 20) -> WebSocket:
    u = urllib.parse.urlsplit(url)
    if u.scheme not in ("ws", "wss"):
        raise ValueError(f"not a websocket url: {url}")
    port = u.port or (443 if u.scheme == "wss" else 80)
    ctx = None
    if u.scheme == "wss":
        ctx = ssl_context or _ssl.create_default_context()
    reader, writer = await asyncio.wait_for(
        asyncio.open_connection(u.hostname, port, ssl=ctx, server_hostname=u.hostname if ctx else None,
                                limit=1 << 20), timeout)
    key = base64.b64encode(os.urandom(16)).decode()
    path = (u.path or "/") + (("?" + u.query) if u.query else "")
    host = u.hostname + (f":{u.port}" if u.port else "")
    lines = [f"GET {path} HTTP/1.1", f"Host: {host}", "Upgrade: websocket", "Connection: Upgrade",
             f"Sec-WebSocket-Key: {key}", "Sec-WebSocket-Version: 13"]
    for k, v in (headers or {}).items():
        lines.append(f"{k}: {v}")
    writer.write(("\r\n".join(lines) + "\r\n\r\n").encode())
    try:
        head = await asyncio.wait_for(reader.readuntil(b"\r\n\r\n"), timeout)
    except (asyncio.IncompleteReadError, asyncio.LimitOverrunError, asyncio.TimeoutError) as e:
        writer.close()
        raise HandshakeError(0, f"no handshake reply ({type(e).__name__})") from None
    status_line, *hdrs = head.decode("latin-1").split("\r\n")
    parts = status_line.split(" ", 2)
    status = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else 0
    hd = {}
    for h in hdrs:
        if ":" in h:
            k, v = h.split(":", 1)
            hd[k.strip().lower()] = v.strip()
    if status != 101:
        writer.close()
        raise HandshakeError(status, parts[2] if len(parts) > 2 else "")
    if hd.get("sec-websocket-accept") != accept_key(key):
        writer.close()
        raise HandshakeError(status, "bad accept key")
    return WebSocket(reader, writer, client=True, max_message=max_message)
