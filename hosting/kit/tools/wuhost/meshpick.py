"""Host side of the Leyline mesh (docs/LEYLINE-MESH.md): pick a relay for this realm, and the community relay
profile ("Help the network: relay for others"). Standard library only; every record is verified (wunet.mesh).
"""
from __future__ import annotations

import json
import re
import time
import urllib.request

from wunet import mesh

UA = "wu-host-mesh/1"


def _get(url, timeout=8):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read(8 << 20).decode("utf-8"))


def fetch_relays(bootstrap: str, get=_get, now=None) -> list:
    """Verified relay records (node dicts) from the first bootstrap node that answers."""
    now = time.time() if now is None else now
    for base in [u.strip().rstrip("/") for u in bootstrap.split(",") if u.strip()]:
        try:
            doc = get(base + "/api/mesh/peers")
        except (OSError, ValueError):
            continue
        st = mesh.Store()
        for r in (doc or {}).get("relays") or []:
            st.offer(r, now)
        if st.relays():
            return [r["node"] for r in st.relays()]
    return []


def pick_relay(nodes: list, *, volunteers: bool, seeds: set) -> str | None:
    """The relay host to dial: room for one more realm, lowest load. Seeds only unless `volunteers`."""
    best = None
    for n in nodes:
        h = n.get("host")
        if not mesh.host_ok(h) or (not volunteers and h not in seeds):
            continue
        caps, load = n.get("caps") or {}, n.get("load") or {}
        if caps.get("realms") and (load.get("realms") or 0) >= caps["realms"]:
            continue
        frac = (load.get("realms") or 0) / caps["realms"] if caps.get("realms") else 0.5
        key = (round(frac, 3), 0 if h in seeds else 1, h)
        if best is None or key < best[0]:
            best = (key, h)
    return best[1] if best else None


def volunteer_env(host: str, *, region="", max_realms=25, kbps=256, daily_gb=5, bootstrap="") -> str:
    """The env file for docker-compose.volunteer-relay.yml."""
    if not mesh.host_ok((host or "").lower()):
        raise SystemExit("--host must be this PC's public DNS name, like relay.example.org")
    if region and region not in mesh.REGIONS:
        raise SystemExit("unknown region")
    boot = ",".join(u for u in (bootstrap or "").split(",") if re.match(r"^https://[a-z0-9.-]+(:[0-9]+)?$", u.strip()))
    lines = [
        "# Leyline community relay (setup.py volunteer-relay). Relays other people's realms through this PC:",
        "# only while docker-compose.volunteer-relay.yml runs. Players' game traffic passes through it.",
        f"RELAY_NAME={host.lower()}",
        "RELAY_VOLUNTEER=1",
        "RELAY_MESH=1",
        f"RELAY_MESH_BOOTSTRAP={boot}",
        f"RELAY_REGION={region}",
        f"RELAY_MAX_REALMS={max(1, min(int(max_realms), 200))}",
        f"RELAY_KBPS={max(32, min(int(kbps), 4096))}",
        f"RELAY_DAILY_GB={max(1, min(int(daily_gb), 100))}",
        "RELAY_PORT_MIN=41000",
        f"RELAY_PORT_MAX={41000 + 2 * max(1, min(int(max_realms), 200)) + 1}",
        "RELAY_SHARED_AUTH_PORT=0",
        "RELAY_LISTING=1",
    ]
    return "\n".join(lines) + "\n"
