"""Hero Key sign-in for Beacons: the realm side (docs/HERO-KEY-SSO.md).

The website signs a short-lived assertion, "this Hero Key holder may sign in to realm <id> as <sub>", with its
own Ed25519 key (the issuer is stream/herokey_sso.py). The realm's agent checks it here and sets a one-time SRP
login on the matching local account, so the stock 3.3.5a client logs in with SRP as always. The realm never sees
the Hero Key, the site password or the player's global account id: only `sub`, a pseudonym made for this realm
alone (another realm gets a different one for the same player).

An assertion (every field is signed):

    {"v": 1, "iss": "play.openvanilla.app", "kid": "<16 hex>", "aud": "<realm id>", "sub": "<26 base32>",
     "salt": "<64 hex>", "verifier": "<64 hex>", "login_ttl": 120, "nonce": "<32 hex>", "iat": <unix>, "exp": <unix>}

    sig = Ed25519(site key, "leyline-herokey-sso-v1\\n" + canonical JSON)   (wunet/keys.sign_doc)

salt and verifier are the SRP6 values (AzerothCore's 32 little-endian bytes) of a random one-time password the
website made for this sign-in only and handed to the player's browser or launcher, never to the relay or the realm.

Off unless the site's public key is pinned: SITE_KEYS below (the owner fills it in when the flag goes on) or
WU_HEROKEY_SITE_KEYS (hex, comma separated: tests, a self-hosted network). With no key every assertion is refused
("off") and the realm keeps its join page.
"""
import hashlib
import os
import re
import time

from . import keys

CTX = "leyline-herokey-sso-v1"
VERSION = 1
# TODO(owner): the website's Hero Key sign-in public key(s), hex (GET /wrath/leyline/herokey.json shows them once
# the herokey_sso flag is on). Two entries during a key rotation. Empty: Hero Key sign-in is off on every realm.
SITE_KEYS: tuple = ()
ENV_KEYS = "WU_HEROKEY_SITE_KEYS"

SKEW = 60                 # clock difference allowed between the website and the realm, seconds
MAX_LIFETIME = 300        # exp - iat may not be longer than this
LOGIN_TTL_MAX = 900       # how long the one-time login may stay valid on the realm, at most
FIELDS = frozenset(("v", "iss", "kid", "aud", "sub", "salt", "verifier", "login_ttl", "nonce", "iat", "exp"))
SUB_RE = re.compile(r"^[a-z2-7]{26}$")
HEX64_RE = re.compile(r"^[0-9a-f]{64}$")
NONCE_RE = re.compile(r"^[0-9a-f]{32}$")
KID_RE = re.compile(r"^[0-9a-f]{16}$")
SIG_RE = re.compile(r"^[0-9a-f]{128}$")
ACCOUNT_RE = re.compile(r"^HK[A-Z2-7]{14}$")


def account_name(sub: str) -> str:
    """The realm's game account for a pseudonym: "HK" + 14 base32 characters (16, the 3.3.5a limit). Derived on
    the realm from `sub`, so the website cannot point an assertion at an account the realm made some other way."""
    return "HK" + sub[:14].upper()


def key_id(pub: bytes) -> str:
    return hashlib.sha256(pub).hexdigest()[:16]


def pinned_keys(env=None) -> dict:
    """kid -> public key bytes: SITE_KEYS plus WU_HEROKEY_SITE_KEYS. Junk entries are skipped."""
    env = os.environ if env is None else env
    out = {}
    for h in list(SITE_KEYS) + [x.strip() for x in str(env.get(ENV_KEYS, "")).split(",")]:
        try:
            b = bytes.fromhex(h)
        except ValueError:
            continue
        if len(b) == 32:
            out[key_id(b)] = b
    return out


class ReplayCache:
    """Nonces already used, each kept until its assertion expires (memory; an assertion lives 2 minutes)."""

    def __init__(self, cap=50000):
        self.seen = {}
        self.cap = cap

    def sweep(self, now):
        for n in [n for n, exp in self.seen.items() if exp + SKEW < now]:
            del self.seen[n]

    def add(self, nonce, exp, now) -> bool:
        """True the first time a nonce is seen, False on a replay (or when the cache is full: refuse, never forget)."""
        self.sweep(now)
        if nonce in self.seen or len(self.seen) >= self.cap:
            return False
        self.seen[nonce] = exp
        return True


def _int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def shape_ok(a) -> bool:
    return (isinstance(a, dict) and set(a) == FIELDS and a["v"] == VERSION and isinstance(a["iss"], str)
            and 0 < len(a["iss"]) <= 64 and isinstance(a["kid"], str) and KID_RE.match(a["kid"])
            and isinstance(a["aud"], str) and keys.REALM_ID_RE.match(a["aud"])
            and isinstance(a["sub"], str) and SUB_RE.match(a["sub"])
            and isinstance(a["salt"], str) and HEX64_RE.match(a["salt"]) and a["salt"][-2:] != "00"
            and isinstance(a["verifier"], str) and HEX64_RE.match(a["verifier"])
            and isinstance(a["nonce"], str) and NONCE_RE.match(a["nonce"])
            and _int(a["iat"]) and _int(a["exp"]) and _int(a["login_ttl"]) and 30 <= a["login_ttl"] <= LOGIN_TTL_MAX)


def check(assertion, sig, realm_id, site_keys, seen: ReplayCache, now=None):
    """(claims, None) for a good assertion for this realm, else (None, reason). The nonce is only spent once the
    signature is good, so junk can't fill the replay cache. Reasons: off, shape, kid, sig, aud, expired, early,
    lifetime, replay."""
    now = int(time.time()) if now is None else int(now)
    if not site_keys:
        return None, "off"
    if not shape_ok(assertion) or not (isinstance(sig, str) and SIG_RE.match(sig)):
        return None, "shape"
    pub = site_keys.get(assertion["kid"])
    if pub is None:
        return None, "kid"
    if not keys.verify_doc(pub, assertion, CTX, sig):
        return None, "sig"
    if assertion["aud"] != realm_id:
        return None, "aud"
    if assertion["exp"] - assertion["iat"] > MAX_LIFETIME or assertion["exp"] <= assertion["iat"]:
        return None, "lifetime"
    if assertion["iat"] > now + SKEW:
        return None, "early"
    if assertion["exp"] + SKEW < now:
        return None, "expired"
    if not seen.add(assertion["nonce"], assertion["exp"], now):
        return None, "replay"
    return dict(assertion), None
