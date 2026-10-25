# Prints the SQL that creates an AzerothCore account (SRP6 salt + verifier) with GM level 3.
# Usage: python make_account.py USER PASS   (run by add-account.bat inside a python container)
import hashlib, os, sys
N = int("894B645E89E1535BBDAD5B8B290650530801B18EBFBF5E8FAB3C82872A3E9BB7", 16)
user, pw = sys.argv[1].upper(), sys.argv[2].upper()
if not user.isalnum() or len(user) > 16:
    sys.exit("account names are letters and digits, 16 at most")
salt = os.urandom(32)
h1 = hashlib.sha1(f"{user}:{pw}".encode()).digest()
x = int.from_bytes(hashlib.sha1(salt + h1).digest(), "little")
v = pow(7, x, N).to_bytes(32, "little")
print(f"INSERT INTO account (username, salt, verifier, expansion) VALUES ('{user}', 0x{salt.hex()}, 0x{v.hex()}, 2);")
print(f"INSERT INTO account_access (id, gmlevel, RealmID) SELECT id, 3, -1 FROM account WHERE username = '{user}';")
