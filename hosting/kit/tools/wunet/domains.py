"""Leyline's public addresses, from leyline.env next to this file (one line: LEYLINE_DOMAIN).

The environment may override each value: LEYLINE_DOMAIN, LEYLINE_RELAY, LEYLINE_SITE, LEYLINE_JOIN.
"""
import os

FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "leyline.env")


def _read(path=FILE):
    out = {}
    try:
        with open(path, encoding="utf-8") as f:
            for ln in f:
                ln = ln.strip()
                if ln and not ln.startswith("#") and "=" in ln:
                    k, v = ln.split("=", 1)
                    out[k.strip()] = v.split("#", 1)[0].strip()
    except OSError:
        pass
    return out


def load(env=None):
    env = os.environ if env is None else env
    f = _read()
    domain = env.get("LEYLINE_DOMAIN") or f.get("LEYLINE_DOMAIN") or "openvanilla.app"
    relay = env.get("LEYLINE_RELAY") or f.get("LEYLINE_RELAY") or f"relay.{domain}"
    site = env.get("LEYLINE_SITE") or f.get("LEYLINE_SITE") or f"https://{domain}"
    join = env.get("LEYLINE_JOIN") or f.get("LEYLINE_JOIN") or f"https://{relay}"
    return {"domain": domain, "relay": relay, "site": site.rstrip("/"), "join": join.rstrip("/")}


_d = load()
DOMAIN, RELAY, SITE, JOIN = _d["domain"], _d["relay"], _d["site"], _d["join"]
