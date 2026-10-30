"""Soak test: many headless 3.3.5a players through the relay for a long time.

  # against a real hosted realm (accounts SOAK001.. made first, see SOAK-PLAN.md):
  python soak.py --auth relay.openvanilla.app:40000 --clients 50 --duration 3600 --accounts SOAK --password soakpass1

  # self-test of the harness, in-process (relay + agent + fake realm on this machine):
  python soak.py --rig --clients 50 --duration 60

Each player: log in, list realms, enter the world (creating a character the first time), ping every
`--ping` seconds (CMSG_PING round trip = relay + tunnel + worldserver latency), log out and back in
every `--relog` seconds. Ramps up over `--ramp` seconds. Prints a JSON summary: logins, failures by
kind, ping p50/p95/p99/max, login time, tunnel reconnects, relay metrics (in --rig mode).
"""
import argparse
import asyncio
import collections
import json
import os
import random
import statistics
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
import helpers  # noqa: E402,F401  (paths)
from wunet import wire335 as w  # noqa: E402


def pct(xs, p):
    if not xs:
        return None
    xs = sorted(xs)
    return round(xs[min(len(xs) - 1, int(len(xs) * p / 100))], 1)


class Stats:
    def __init__(self):
        self.logins = 0
        self.login_ms = []
        self.ping_ms = []
        self.errors = collections.Counter()
        self.sessions = 0
        self.active = 0
        self.peak = 0


async def player(i, a, st: Stats, end, opener=None):
    user = f"{a.accounts}{i + 1:03d}"
    await asyncio.sleep(a.ramp * i / max(1, a.clients))
    host, port = w.split_host_port(a.auth, 3724)
    while time.monotonic() < end:
        t0 = time.monotonic()
        sess = None
        try:
            K, realms = await w.logon(host, port, user, a.password, timeout=30, opener=opener)
            whost, wport = w.split_host_port(a.world or realms[0]["address"], 8085)
            sess = await w.world_session(whost, wport, user, K, realm_id=realms[0]["id"], timeout=30, opener=opener)
            chars = await w.char_enum(sess)
            if not chars:
                code = await w.char_create(sess, w.random_name("Sk"))
                if code != w.CHAR_CREATE_SUCCESS:
                    raise w.WowError(f"create {code:#x}")
                chars = await w.char_enum(sess)
            await w.enter_world(sess, chars[0]["guid"])
            st.logins += 1
            st.login_ms.append((time.monotonic() - t0) * 1000)
            st.active += 1
            st.peak = max(st.peak, st.active)
            relog_at = time.monotonic() + a.relog * (0.75 + 0.5 * random.random())
            n = 1
            try:
                while time.monotonic() < min(end, relog_at):
                    await asyncio.sleep(a.ping * (0.8 + 0.4 * random.random()))
                    p0 = time.monotonic()
                    await w.ping(sess, n)
                    st.ping_ms.append((time.monotonic() - p0) * 1000)
                    n += 1
                await w.logout(sess, within=40)
                st.sessions += 1
            finally:
                st.active -= 1
        except (w.WowError, OSError, asyncio.TimeoutError, asyncio.IncompleteReadError) as e:
            st.errors[type(e).__name__ + ": " + str(e)[:60]] += 1
            await asyncio.sleep(2 + random.random() * 3)
        finally:
            if sess:
                sess.writer.close()


async def run(a):
    st = Stats()
    rig = None
    if a.rig:
        from helpers import Rig
        rig = Rig(max_streams=4 * a.clients, max_streams_per_ip=4 * a.clients, max_streams_per_ip_total=4 * a.clients,
                  conn_rate_per_ip=100000, kbps=1 << 16, listing=False)
        await rig.__aenter__()
        rig.realm.logout_delay = 0.5
        for i in range(a.clients):
            rig.realm.add_account(f"{a.accounts}{i + 1:03d}", a.password)
        a.auth = f"127.0.0.1:{rig.ports[0]}"
        a.world = f"127.0.0.1:{rig.ports[1]}"
    end = time.monotonic() + a.duration
    t0 = time.time()
    try:
        await asyncio.gather(*[player(i, a, st, end) for i in range(a.clients)])
    finally:
        summary = {
            "clients": a.clients, "duration_s": round(time.time() - t0), "logins": st.logins,
            "completed_sessions": st.sessions, "peak_in_world": st.peak,
            "login_ms": {"p50": pct(st.login_ms, 50), "p95": pct(st.login_ms, 95), "max": pct(st.login_ms, 100)},
            "ping_ms": {"n": len(st.ping_ms), "p50": pct(st.ping_ms, 50), "p95": pct(st.ping_ms, 95),
                        "p99": pct(st.ping_ms, 99), "max": pct(st.ping_ms, 100),
                        "mean": round(statistics.mean(st.ping_ms), 1) if st.ping_ms else None},
            "errors": dict(st.errors),
        }
        if rig:
            summary["relay"] = {k: v for k, v in rig.relay.metrics.items()}
            summary["relay"]["agent_logins"] = rig.relay.metrics["agent_logins"]
            await rig.__aexit__(None, None, None)
        print(json.dumps(summary, indent=1))
    return summary


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--auth", help="relay HOST:PORT (the realm's auth port, or HOST for the shared 3724)")
    ap.add_argument("--world", help="override the world address from the realm list (tests)")
    ap.add_argument("--clients", type=int, default=50)
    ap.add_argument("--duration", type=float, default=3600)
    ap.add_argument("--ramp", type=float, default=60)
    ap.add_argument("--ping", type=float, default=25)
    ap.add_argument("--relog", type=float, default=600)
    ap.add_argument("--accounts", default="SOAK", help="account name prefix: SOAK001, SOAK002, ...")
    ap.add_argument("--password", default="soakpass1")
    ap.add_argument("--rig", action="store_true", help="in-process relay + agent + fake realm (harness self-test)")
    ap.add_argument("--max-error-rate", type=float, default=0.01, help="fail when errors/logins exceeds this")
    a = ap.parse_args()
    if not a.rig and not a.auth:
        ap.error("--auth or --rig")
    s = asyncio.run(run(a))
    errs = sum(s["errors"].values())
    return 0 if s["logins"] and errs <= a.max_error_rate * max(1, s["logins"]) else 1


if __name__ == "__main__":
    sys.exit(main())
