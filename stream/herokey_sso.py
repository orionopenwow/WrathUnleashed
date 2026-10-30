"""Hero Key sign-in for Beacons: the website side, the issuer (docs/HERO-KEY-SSO.md). Standard library only
(Ed25519 from `cryptography` when the image has it, else ed25519_pure.py beside this file).

Behind the `herokey_sso` flag (stream/leyline_net.py, OFF by default): wrath_portal.py only calls issue() while
the owner has it on. With it on:

  * a hop to a Beacon (/__env.js, hop_env) gets `hop_sso` {assertion, sig, redeem} and a one-time login for that
    realm instead of the framed join page and the login kept in localStorage;
  * the launcher asks POST /wrath/api/social/herokey {realm} with its Bearer token (stream/social.py);
  * GET /wrath/leyline/herokey.json publishes the public key(s), for the owner to pin in the host kit
    (hosting/kit/tools/wunet/herokey.py SITE_KEYS).

What issue() makes, for one Hero Key account and one realm:

  sub       base32(HMAC-SHA256(pepper, "leyline-sso-sub-v1\\n" + realm id + "\\n" + ACCOUNT))[:26]: the same for
            this player on this realm every time, different on every other realm, and not linkable without the
            pepper (which never leaves this server).
  password  16 random characters, made for this sign-in only. It goes to the player's browser or launcher and
            nowhere else; it is not stored here. The realm gets only its SRP6 salt and verifier, inside the signed
            assertion, so the relay in between can neither read the password nor swap in its own verifier.
  assertion signed with the site key, audience = the realm id, nonce, 2 minutes to be redeemed.

Files (in $WU_LEYLINE_DIR, default /data/leyline, made 0600 on first use; never printed or logged):
  herokey-site.key     the Ed25519 secret (hex). A second key for a rotation: herokey-site.next.key (published too).
  herokey-pepper.key   the pseudonym pepper (hex). Changing it changes every player's account on every realm.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import importlib.util
import json
import os
import re
import secrets
import time

HERE = os.path.dirname(os.path.abspath(__file__))
CTX = "leyline-herokey-sso-v1"          # the same as hosting/kit/tools/wunet/herokey.py
SUB_CTX = b"leyline-sso-sub-v1\n"
VERSION = 1
ASSERT_TTL = 120                        # seconds to redeem the assertion at the realm
LOGIN_TTL_WEB = 120                     # the one-time login, browser game (the client signs in at once)
LOGIN_TTL_LAUNCHER = 600                # the desktop client: the player types it at the login screen
REALM_ID_RE = re.compile(r"^[a-z2-7]{16}$")
ACCT_RE = re.compile(r"^[A-Za-z0-9]{1,16}$")
PASS_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"   # no 0/O, 1/I: someone may type it into the desktop client

# SRP6 as AzerothCore 3.3.5a does it (hosting/kit/tools/wunet/srp6.py; the test checks they agree)
N = int("894B645E89E1535BBDAD5B8B290650530801B18EBFBF5E8FAB3C82872A3E9BB7", 16)
G = 7


def _load_ed25519():
    for p in (os.path.join(HERE, "ed25519_pure.py"),
              os.path.join(HERE, "..", "hosting", "kit", "tools", "wunet", "ed25519_pure.py")):
        if os.path.isfile(p):
            spec = importlib.util.spec_from_file_location("wu_hk_ed25519", p)
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            return mod
    raise ImportError("ed25519_pure.py not found")


try:
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    from cryptography.hazmat.primitives import serialization
    _pure = None
except ImportError:  # pragma: no cover - the portal image has only the standard library
    Ed25519PrivateKey = None
    _pure = _load_ed25519()


def public_key(secret: bytes) -> bytes:
    if Ed25519PrivateKey is not None:
        return Ed25519PrivateKey.from_private_bytes(secret).public_key().public_bytes(
            serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    return _pure.public_key(secret)


def _sign(secret: bytes, msg: bytes) -> bytes:
    if Ed25519PrivateKey is not None:
        return Ed25519PrivateKey.from_private_bytes(secret).sign(msg)
    return _pure.sign(secret, msg)


def canonical(doc) -> bytes:
    return json.dumps(doc, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def sign_doc(secret: bytes, doc: dict) -> str:
    return _sign(secret, CTX.encode() + b"\n" + canonical(doc)).hex()


def key_id(pub: bytes) -> str:
    return hashlib.sha256(pub).hexdigest()[:16]


def pseudonym(pepper: bytes, realm_id: str, acct: str) -> str:
    """This player's id on this realm: stable, and unlinkable across realms without the pepper."""
    mac = hmac.new(pepper, SUB_CTX + realm_id.encode() + b"\n" + acct.upper().encode(), hashlib.sha256).digest()
    return base64.b32encode(mac).decode().lower()[:26]


def account_name(sub: str) -> str:
    """The same rule as wunet/herokey.account_name (the realm derives it itself)."""
    return "HK" + sub[:14].upper()


def new_salt() -> bytes:
    """32 random bytes whose most significant (last) byte is not 0 (every core here stores it at 32 bytes)."""
    while True:
        s = os.urandom(32)
        if s[-1]:
            return s


def make_verifier(user: str, password: str, salt: bytes) -> bytes:
    inner = hashlib.sha1(f"{user.upper()}:{password.upper()}".encode()).digest()
    x = int.from_bytes(hashlib.sha1(salt + inner).digest(), "little")
    return pow(G, x, N).to_bytes(32, "little")


def new_password() -> str:
    return "".join(secrets.choice(PASS_ALPHABET) for _ in range(16))


def issue(secret: bytes, pepper: bytes, acct: str, realm_id: str, iss: str, login_ttl: int = LOGIN_TTL_WEB,
          now: int | None = None) -> dict:
    """{"assertion", "sig", "login": {"user", "pass"}} for this account on this realm. The login is the player's
    alone: the caller hands it to them only (no-store), never logs it."""
    if not REALM_ID_RE.match(realm_id or "") or not ACCT_RE.match(acct or ""):
        raise ValueError("bad realm id or account")
    now = int(time.time()) if now is None else int(now)
    sub = pseudonym(pepper, realm_id, acct)
    user = account_name(sub)
    password = new_password()
    salt = new_salt()
    a = {"v": VERSION, "iss": iss[:64], "kid": key_id(public_key(secret)), "aud": realm_id, "sub": sub,
         "salt": salt.hex(), "verifier": make_verifier(user, password, salt).hex(),
         "login_ttl": int(max(30, min(login_ttl, 900))), "nonce": secrets.token_hex(16), "iat": now,
         "exp": now + ASSERT_TTL}
    return {"assertion": a, "sig": sign_doc(secret, a), "login": {"user": user, "pass": password}}


# ------------------------------------------------------------------ the key files
def _load_or_create(path: str, create: bool = True) -> bytes | None:
    try:
        with open(path, encoding="ascii") as f:
            b = bytes.fromhex(f.read().strip())
        if len(b) == 32:
            return b
        raise ValueError(f"{path} is not a 32-byte key")
    except FileNotFoundError:
        if not create:
            return None
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    b = secrets.token_bytes(32)
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:   # another thread made it first
        return _load_or_create(path, create=False)
    with os.fdopen(fd, "w", encoding="ascii") as f:
        f.write(b.hex() + "\n")
    return b


class Keys:
    """The site key (and the next one, during a rotation) and the pepper, read once from `folder`."""

    def __init__(self, folder: str):
        self.folder = folder
        self._secret = self._pepper = None
        self._next_loaded = False
        self._next = None

    def secret(self) -> bytes:
        if self._secret is None:
            self._secret = _load_or_create(os.path.join(self.folder, "herokey-site.key"))
        return self._secret

    def pepper(self) -> bytes:
        if self._pepper is None:
            self._pepper = _load_or_create(os.path.join(self.folder, "herokey-pepper.key"))
        return self._pepper

    def next_secret(self) -> bytes | None:
        if not self._next_loaded:
            self._next = _load_or_create(os.path.join(self.folder, "herokey-site.next.key"), create=False)
            self._next_loaded = True
        return self._next

    def public_doc(self) -> dict:
        """What GET /wrath/leyline/herokey.json shows: the key in use, then the next one if a rotation is staged."""
        out = []
        for s, use in ((self.secret(), "current"), (self.next_secret(), "next")):
            if s:
                pub = public_key(s)
                out.append({"kid": key_id(pub), "pub": pub.hex(), "use": use})
        return {"v": VERSION, "ctx": CTX, "keys": out}
