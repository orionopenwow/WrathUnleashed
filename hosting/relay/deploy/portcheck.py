"""Are the relay's game ports (40000-40999) reachable from the internet? Read-only; run from OUTSIDE the server
(the owner's PC: the relay and check steps run it after their SSH part).

    python3 portcheck.py [--relay relay.openvanilla.app] [--host play.openvanilla.app] [--range 40000-40999]

Desktop clients join a Beacon on <relay>:<auth port> and <world port>, raw TCP straight to the box (not through
Caddy). ufw is opened by relay-up.sh, but a Hetzner Cloud Firewall can only be changed in the Hetzner console and
can't be seen from the box. From outside the two look different: a port nothing listens on answers "refused" at
once when the packets reach the box, and stays silent (a timeout) when a firewall drops them.

It probes the ports of live realms from the relay's own API (/api/listing/realms.json, then /api/realms/<id>:
those should connect) and the two ends of the range (nothing listens there: refused = open, timeout = blocked).
  reachable: something connected or refused       -> "game ports 40000-40999: reachable"
  blocked:   every probe timed out                 -> "game ports 40000-40999: BLOCKED" + the Hetzner console clicks
  unknown:   the name doesn't resolve, no network  -> says so
Exit code 0 (reachable / unknown) or 4 (blocked). Standard library only.
"""
from __future__ import annotations

import argparse
import errno
import json
import socket
import sys
import urllib.request

HETZNER = """  Open the game ports in the Hetzner Cloud Firewall (the box can't change it):
    1. https://console.hetzner.cloud -> the project with the play server -> Firewalls (left menu).
       No firewall there, or none applied to the server: the block is somewhere else (ask Claude).
    2. Open the firewall applied to the server -> Rules -> Inbound -> Add rule.
    3. Protocol TCP, Port 40000-40999, Source IPs: Any IPv4 (0.0.0.0/0) and Any IPv6 (::/0) -> Add rule / Save.
    4. Run the relay step (or the server check) again: it should say "reachable"."""


def probe(host: str, port: int, timeout: float = 5.0) -> str:
    """'open', 'refused', 'timeout' or 'error: ...'."""
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return "open"
    except ConnectionRefusedError:
        return "refused"
    except socket.timeout:
        return "timeout"
    except OSError as e:
        if e.errno in (errno.ECONNREFUSED, getattr(errno, "WSAECONNREFUSED", -1), 10061):
            return "refused"
        if e.errno in (errno.ETIMEDOUT, 10060):
            return "timeout"
        return f"error: {e.strerror or e}"


def get_json(url: str, timeout: float = 8.0):
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "wu-portcheck"}),
                                    timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8"))
    except Exception:
        return None


def live_ports(relay: str, fetch=get_json, limit: int = 2) -> list[tuple[str, int]]:
    """(label, port) for up to `limit` live realms on the relay's listing."""
    doc = fetch(f"https://{relay}/api/listing/realms.json") or {}
    out = []
    for rec in doc.get("realms") or []:
        rid = ((rec.get("community") or {}).get("realmId") or rec.get("realm_id") or "")
        if rec.get("state") != "live" or not rid:
            continue
        info = fetch(f"https://{relay}/api/realms/{rid}") or {}
        if not info.get("online"):
            continue
        for k in ("auth_port", "world_port"):
            if isinstance(info.get(k), int):
                out.append((f"{info.get('name') or rid} {k.split('_')[0]}", info[k]))
        if len(out) >= 2 * limit:
            break
    return out


def check(host: str, relay: str, pmin: int, pmax: int, probe_fn=probe, fetch=get_json, timeout=5.0):
    """(verdict, lines)."""
    try:
        socket.getaddrinfo(host, None, socket.AF_INET)
    except OSError:
        return "unknown", [f"  {host} does not resolve from this PC: could not check the game ports."]
    targets = [(lbl, p) for lbl, p in live_ports(relay, fetch) if pmin <= p <= pmax]
    targets += [("range start", pmin), ("range end", pmax)]
    lines, results = [], []
    for lbl, port in targets:
        r = probe_fn(host, port, timeout)
        results.append(r)
        lines.append(f"  {host}:{port} ({lbl}): {r}")
    if any(r in ("open", "refused") for r in results):
        verdict = "reachable"
    elif results and all(r == "timeout" for r in results):
        verdict = "blocked"
    else:
        verdict = "unknown"
    return verdict, lines


def main(argv=None, probe_fn=probe, fetch=get_json) -> int:
    ap = argparse.ArgumentParser(description="Check from outside that the relay's game ports are reachable.")
    ap.add_argument("--relay", default="relay.openvanilla.app")
    ap.add_argument("--host", default="play.openvanilla.app", help="the box (the relay runs on it)")
    ap.add_argument("--range", default="40000-40999")
    ap.add_argument("--timeout", type=float, default=5.0)
    a = ap.parse_args(argv)
    pmin, pmax = (int(x) for x in a.range.split("-", 1))
    print(f"Game ports from this PC (outside the server): {a.host} {pmin}-{pmax}")
    verdict, lines = check(a.host, a.relay, pmin, pmax, probe_fn, fetch, a.timeout)
    for ln in lines:
        print(ln)
    if verdict == "reachable":
        print(f"game ports {pmin}-{pmax}: reachable")
        return 0
    if verdict == "blocked":
        print(f"game ports {pmin}-{pmax}: BLOCKED (every probe timed out: a firewall drops them)")
        print("ACTION NEEDED (owner): desktop players can't join Beacons until this is open.")
        print(HETZNER)
        return 4
    print(f"game ports {pmin}-{pmax}: could not tell (see above); the relay itself is not affected")
    return 0


if __name__ == "__main__":
    sys.exit(main())
