# Prints SQL creating AzerothCore accounts (SRP6, GM level 0) for every name in a list, with a
# random password each, and writes the name,password pairs to accounts.csv for you to hand out.
# Usage (inside a python container): python make_accounts.py testers.txt accounts.csv
import hashlib, os, secrets, string, sys
N = int("894B645E89E1535BBDAD5B8B290650530801B18EBFBF5E8FAB3C82872A3E9BB7", 16)
names_file, csv_file = sys.argv[1], sys.argv[2]
alphabet = string.ascii_uppercase + string.digits
rows = []
for line in open(names_file, encoding="utf-8-sig"):
    user = line.strip().upper()
    if not user or user.startswith("#"):
        continue
    if not user.isalnum() or not 3 <= len(user) <= 16 or user.startswith("RNDBOT"):
        sys.exit(f"bad account name {user!r}: letters and digits, 3-16, not rndbot...")
    pw = "".join(secrets.choice(alphabet) for _ in range(10))
    salt = os.urandom(32)
    x = int.from_bytes(hashlib.sha1(salt + hashlib.sha1(f"{user}:{pw}".encode()).digest()).digest(), "little")
    v = pow(7, x, N).to_bytes(32, "little")
    print(f"INSERT INTO account (username, salt, verifier, expansion) VALUES ('{user}', 0x{salt.hex()}, 0x{v.hex()}, 2) ON DUPLICATE KEY UPDATE salt = VALUES(salt), verifier = VALUES(verifier);")
    rows.append((user, pw))
with open(csv_file, "w", encoding="utf-8") as f:
    f.write("account,password\n")
    for u, p in rows:
        f.write(f"{u},{p}\n")
print(f"-- {len(rows)} accounts", file=sys.stderr)
