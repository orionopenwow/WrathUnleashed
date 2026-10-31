"""Shared rate limits for the portal and its modules (wrath_portal.py, social.py, hub_rank.py, profiles.py, admin.py,
hub.py). One sliding-window limiter that:

  * forgets: a sweep at most every `sweep_every` seconds drops every key whose newest hit is older than its window
    (the old copies only rebuilt the table when it passed 20 000 keys and then kept any key with an old timestamp);
  * stays small: at most `max_keys` per-address keys, least recently used evicted first;
  * keeps global caps: keys named in `global_keys` (or hit through cap()) live apart, are never evicted and are never
    emptied by clear(), so a flood of fresh addresses can't reset them;
  * allows a window per key: hit(key, limit, seconds=...);
  * buckets addresses: bucket(ip) is the IPv4 address (/32) or the IPv6 /64, so one host can't dodge a per-address
    limit by walking its own /64.

Thread safe (one lock per limiter). Loaded from beside the caller (python3 -I leaves the folder off sys.path):

    import importlib.util, os, sys
    def _ratelimit():
        m = sys.modules.get("wu_ratelimit")
        if m is None:
            spec = importlib.util.spec_from_file_location(
                "wu_ratelimit", os.path.join(os.path.dirname(os.path.abspath(__file__)), "ratelimit.py"))
            m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m); sys.modules["wu_ratelimit"] = m
        return m
    limit = _ratelimit().Limiter(60)
    if not limit.hit("play:" + _ratelimit().bucket(ip), 30): ...

    python3 -I stream/tests/test_ratelimit.py stream/ratelimit.py
"""
from __future__ import annotations

import collections
import ipaddress
import threading
import time

__all__ = ["Limiter", "bucket"]


def bucket(ip: str) -> str:
    """The address a limit counts: IPv4 as is (/32; an IPv4-mapped IPv6 address counts as its IPv4), IPv6 as its /64
    ("2001:db8:1:2::/64"). Anything that isn't an address comes back trimmed to 64 characters."""
    s = (ip or "").strip()
    if s.startswith("[") and "]" in s:
        s = s[1:s.index("]")]
    s = s.split("%", 1)[0]
    try:
        a = ipaddress.ip_address(s)
    except ValueError:
        return s[:64]
    if a.version == 6:
        if a.ipv4_mapped is not None:
            return str(a.ipv4_mapped)
        return str(ipaddress.IPv6Network((int(a) >> 64 << 64, 64)))
    return str(a)


class Limiter:
    """hit(key, limit) is False once `key` had `limit` hits in its window (default `seconds`)."""

    def __init__(self, seconds: float, clock=time.monotonic, max_keys: int = 50000, sweep_every: float | None = None,
                 global_keys=()):
        self.seconds = float(seconds)
        self.clock = clock
        self.max_keys = max(1, int(max_keys))
        self.sweep_every = float(sweep_every if sweep_every is not None else min(self.seconds, 60.0))
        self.global_keys = set(global_keys)
        self.lock = threading.Lock()
        self.q: collections.OrderedDict[str, list] = collections.OrderedDict()   # key -> [deque of hits, window]
        self.g: dict[str, list] = {}   # global caps: never evicted, never cleared
        self.last_sweep = clock()
        self.evicted = 0   # keys pushed out by max_keys (a sign of a flood)

    # ------------------------------------------------------------------ hits
    def hit(self, key: str, limit: int, seconds: float | None = None) -> bool:
        if key in self.global_keys:
            return self.cap(key, limit, seconds)
        win = float(seconds) if seconds is not None else self.seconds
        now = self.clock()
        with self.lock:
            if now - self.last_sweep >= self.sweep_every:
                self._sweep(now)
            e = self.q.get(key)
            if e is None:
                e = self.q[key] = [collections.deque(), win]
            else:
                self.q.move_to_end(key)
                e[1] = win
            q = e[0]
            while q and now - q[0] > win:
                q.popleft()
            if len(q) >= limit:
                return False
            q.append(now)
            while len(self.q) > self.max_keys:
                self.q.popitem(last=False)
                self.evicted += 1
            return True

    def cap(self, name: str, limit: int, seconds: float | None = None) -> bool:
        """A global cap (say "all installs today"): kept apart from the per-address keys."""
        win = float(seconds) if seconds is not None else self.seconds
        now = self.clock()
        with self.lock:
            e = self.g.get(name)
            if e is None:
                e = self.g[name] = [collections.deque(), win]
            e[1] = win
            q = e[0]
            while q and now - q[0] > win:
                q.popleft()
            if len(q) >= limit:
                return False
            q.append(now)
            return True

    def count(self, key: str) -> int:
        now = self.clock()
        with self.lock:
            e = self.g.get(key) if key in self.g else self.q.get(key)
            if e is None:
                return 0
            return sum(1 for t in e[0] if now - t <= e[1])

    # ------------------------------------------------------------------ forgetting
    def _sweep(self, now: float) -> int:
        dead = [k for k, (q, win) in self.q.items() if not q or now - q[-1] > win]
        for k in dead:
            del self.q[k]
        self.last_sweep = now
        return len(dead)

    def sweep(self) -> int:
        """Drop every key whose newest hit is older than its window; the number dropped."""
        with self.lock:
            return self._sweep(self.clock())

    def forget(self, key: str) -> None:
        with self.lock:
            self.q.pop(key, None)

    def clear(self) -> None:
        """Forget the per-address keys (tests, staff "reset"); the global caps stay."""
        with self.lock:
            self.q.clear()

    def __len__(self) -> int:
        with self.lock:
            return len(self.q)

