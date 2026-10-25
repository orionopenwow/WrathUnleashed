#!/usr/bin/env python3
"""Prints SQL (for acore_auth) that creates or re-passwords one AzerothCore account with GM level 3
on every realm. deploy.sh uses it for the SOAP service account, before any GM account exists.

  python3 -I soap_account_sql.py   (reads SOAP_USER and SOAP_PASS from the environment)

AzerothCore's SRP6 (src/common/Cryptography/Authentication/SRP6.cpp):
  verifier = g ^ H(salt | H(UPPER(user) ":" UPPER(pass))) mod N, g = 7, SHA-1 digests read
  little-endian, the verifier stored as 32 little-endian bytes; salt is 32 random bytes.
"""
import hashlib
import os
import re
import secrets
import sys

N = int("894B645E89E1535BBDAD5B8B290650530801B18EBFBF5E8FAB3C82872A3E9BB7", 16)
G = 7


def verifier(user: str, password: str, salt: bytes) -> bytes:
    inner = hashlib.sha1(f"{user.upper()}:{password.upper()}".encode()).digest()
    x = int.from_bytes(hashlib.sha1(salt + inner).digest(), "little")
    return pow(G, x, N).to_bytes(32, "little")


def main() -> int:
    user, password = os.environ.get("SOAP_USER", ""), os.environ.get("SOAP_PASS", "")
    if not re.fullmatch(r"[A-Za-z0-9]{3,16}", user) or not re.fullmatch(r"[A-Za-z0-9]{8,16}", password):
        print("SOAP_USER (3-16) and SOAP_PASS (8-16) must be letters and digits", file=sys.stderr)
        return 2
    salt = secrets.token_bytes(32)
    v = verifier(user, password, salt)
    u = user.upper()
    print(
        "INSERT INTO account (username, salt, verifier, expansion) "
        f"VALUES ('{u}', 0x{salt.hex()}, 0x{v.hex()}, 2) "
        "ON DUPLICATE KEY UPDATE salt = VALUES(salt), verifier = VALUES(verifier);\n"
        "REPLACE INTO account_access (id, gmlevel, RealmID, comment) "
        f"SELECT id, 3, -1, 'WrathUnleashed SOAP service' FROM account WHERE username = '{u}';"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
