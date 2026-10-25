"""The relay <-> host-agent tunnel: one WebSocket (wss://<relay>/agent, so only outbound 443 is
needed at home), many player connections multiplexed on it.

Binary messages carry stream frames:   op (u8) | stream id (u32 BE) | payload
  OPEN  0x01  relay -> agent   payload: port (u16 BE, 3724 or 8085). A new player connection.
  DATA  0x02  both ways        payload: raw TCP bytes of that connection (at most 32 KB).
  CLOSE 0x03  both ways        payload: empty, or one reason byte. The connection is gone.

Text messages carry JSON control messages:
  relay -> agent  {"challenge": "<hex 32>", "relay": "<name>", "v": 1}     first message
  agent -> relay  {"hello": {...}, "sig": "<hex>"}                          signed (keys.CTX_RELAY_LOGIN)
  relay -> agent  {"welcome": {"realm_id", "address", "auth_port", "world_port", "limits", ...}}
                  or {"error": "...", "retry": seconds}
  agent -> relay  {"ping": n}          every 20 s; relay answers {"pong": n}
  relay -> agent  {"req": n, "op": "status"} / {"req": n, "op": "create_account", ...}
  agent -> relay  {"res": n, ...}      the answer to a request
  agent -> relay  {"update": {...}}    visibility / invite hash / name changed (re-signed hello fields)

Stream ids are chosen by the relay and never reused within one tunnel. Either side may send
CLOSE first; the other side answers nothing (CLOSE for an unknown id is ignored).
Flow control is by caps, not windows: the game is a few KB/s per player, so a receiver that falls
more than MAX_BUFFER behind on one stream has that stream cut instead of stalling the tunnel.
"""
import asyncio
import struct
import time

OPEN, DATA, CLOSE = 0x01, 0x02, 0x03
HEAD = struct.Struct("!BI")
MAX_CHUNK = 32 * 1024
MAX_BUFFER = 1 << 20          # bytes queued towards one slow player/service before it is cut
PORTS = (3724, 8085)


def pack(op: int, sid: int, payload: bytes = b"") -> bytes:
    return HEAD.pack(op, sid) + payload


def unpack(msg: bytes):
    if len(msg) < HEAD.size:
        raise ValueError("short mux frame")
    op, sid = HEAD.unpack_from(msg)
    return op, sid, msg[HEAD.size:]


def open_payload(port: int) -> bytes:
    return struct.pack("!H", port)


def parse_open(payload: bytes) -> int:
    if len(payload) < 2:
        raise ValueError("short OPEN")
    return struct.unpack_from("!H", payload)[0]


class TokenBucket:
    """Bytes per second with a one-second burst. take() sleeps until the bytes are allowed, so a
    realm over its cap is slowed down (shaped), not cut."""

    def __init__(self, rate: float, burst: float | None = None, clock=time.monotonic):
        self.rate = float(rate)
        self.burst = float(burst if burst is not None else rate)
        self.tokens = self.burst
        self.clock = clock
        self.at = clock()

    def _refill(self):
        now = self.clock()
        self.tokens = min(self.burst, self.tokens + (now - self.at) * self.rate)
        self.at = now

    def delay_for(self, n: int) -> float:
        """Spend n bytes; how long the caller should wait first (0 when within the cap)."""
        if self.rate <= 0:
            return 0.0
        self._refill()
        self.tokens -= n
        if self.tokens >= 0:
            return 0.0
        return -self.tokens / self.rate

    async def take(self, n: int) -> None:
        d = self.delay_for(n)
        if d > 0:
            await asyncio.sleep(d)
