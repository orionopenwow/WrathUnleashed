"""Realm keys, realm ids and signed JSON.

Every hosted realm has one Ed25519 key, made at setup on the host's PC (state/realm.key, never
leaves it). Everything public about the realm hangs off that key:

  realm id   = base32(sha256(public key))[:16], lower case      e.g. "k3x9q2m4p7w8r5t2"
  relay      : the agent proves the key by signing the relay's challenge (no account, no token)
  listing    : heartbeats are signed with it, so nobody else can update or fake the realm's entry
  claim      : the site binds a Hero Key account to the realm id once the realm shows the claim
               token on its status page (see docs in INSTALL-OPERATE.md)

A realm id is not tied to a relay: the same key works on a self-hosted or federated relay.
"""
import base64
import hashlib
import json
import os
import re

try:  # fast path: the tools and relay images install it
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey
    from cryptography.exceptions import InvalidSignature
    HAVE_CRYPTOGRAPHY = True
except ImportError:  # pragma: no cover - exercised by tests through FORCE_PURE
    HAVE_CRYPTOGRAPHY = False

from . import ed25519_pure

REALM_ID_RE = re.compile(r"^[a-z2-7]{16}$")
FORCE_PURE = os.environ.get("WU_PURE_ED25519") == "1"


def _fast():
    return HAVE_CRYPTOGRAPHY and not FORCE_PURE


def new_secret() -> bytes:
    return os.urandom(32)


def public_key(secret: bytes) -> bytes:
    if _fast():
        from cryptography.hazmat.primitives import serialization
        k = Ed25519PrivateKey.from_private_bytes(secret).public_key()
        return k.public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    return ed25519_pure.public_key(secret)


def sign(secret: bytes, msg: bytes) -> bytes:
    if _fast():
        return Ed25519PrivateKey.from_private_bytes(secret).sign(msg)
    return ed25519_pure.sign(secret, msg)


def verify(public: bytes, msg: bytes, sig: bytes) -> bool:
    if len(public) != 32 or len(sig) != 64:
        return False
    if _fast():
        try:
            Ed25519PublicKey.from_public_bytes(public).verify(sig, msg)
            return True
        except (InvalidSignature, ValueError):
            return False
    return ed25519_pure.verify(public, msg, sig)


def realm_id(public: bytes) -> str:
    return base64.b32encode(hashlib.sha256(public).digest()).decode().lower()[:16]


def canonical(doc) -> bytes:
    """The bytes a signature covers: sorted keys, no spaces, UTF-8."""
    return json.dumps(doc, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def sign_doc(secret: bytes, doc: dict, context: str) -> str:
    """Hex signature of `context` + "\\n" + canonical(doc). The context string keeps a heartbeat
    signature from ever being accepted as a relay login and vice versa."""
    return sign(secret, context.encode() + b"\n" + canonical(doc)).hex()


def verify_doc(public: bytes, doc: dict, context: str, sig_hex: str) -> bool:
    try:
        sig = bytes.fromhex(sig_hex)
    except (ValueError, TypeError):
        return False
    return verify(public, context.encode() + b"\n" + canonical(doc), sig)


def load_or_create(path: str) -> bytes:
    """The realm's secret key file (32 raw bytes, hex in the file). Created 0600 on first use."""
    if os.path.exists(path):
        with open(path, "r", encoding="ascii") as f:
            s = bytes.fromhex(f.read().strip())
        if len(s) != 32:
            raise ValueError(f"{path} is not a realm key")
        return s
    s = new_secret()
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w", encoding="ascii") as f:
        f.write(s.hex() + "\n")
    return s


# Context strings (versioned): what a signature is for.
CTX_RELAY_LOGIN = "wu-relay-login-v1"
CTX_HEARTBEAT = "wu-listing-heartbeat-v1"
