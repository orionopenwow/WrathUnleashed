#!/usr/bin/env bash
# WrathUnleashed: let players log in to the 3.3.5a client with their old Open Vanilla (1.12) username and password.
#
#   bash carry-112-logins.sh            dry run: counts and names, changes nothing
#   bash carry-112-logins.sh --apply    copy the missing logins over (backs up acore_auth.account first)
#
# Both servers keep a login as SRP6 salt + verifier, never the password: the 1.12 one (cmangos) as big-endian hex
# in classicrealmd.account (s, v), AzerothCore as 32 little-endian bytes in acore_auth.account (salt, verifier).
# Same maths (verifier = g^SHA1(salt | SHA1(USER:PASS)) mod N), so a byte-order swap carries the old password over
# exactly. Only accounts that are NOT on Wrath yet are added (INSERT IGNORE: an existing Wrath account is never
# changed). Skipped: random bots, accounts without a stored login, and the ~0.3% whose 1.12 salt was stored short
# (a leading zero byte) - those players use the login the /wrath page shows.
# The website's own accounts (WR000123 style) are already on Wrath with the same password the 1.12 realm had.
set -euo pipefail
APPLY=0; [ "${1:-}" = "--apply" ] && APPLY=1
OLD=${WU_OLD_DB:-wenilla-realm-mariadb-1}
NEW=${WU_DB_CONTAINER:-ov-ac-database}
STAMP=$(date +%Y%m%d-%H%M%S)
cd /srv/wrath
docker ps --format '{{.Names}}' | grep -qx "$OLD" || { echo "The 1.12 database ($OLD) isn't running: nothing to carry over."; exit 1; }
docker ps --format '{{.Names}}' | grep -qx "$NEW" || { echo "The Wrath database ($NEW) isn't running."; exit 1; }
old_sql() { docker exec -i "$OLD" sh -c 'p="${MARIADB_ROOT_PASSWORD:-${MYSQL_ROOT_PASSWORD:-}}"; MYSQL_PWD="$p" exec mariadb -uroot -N -B classicrealmd'; }
new_sql() { docker exec -i "$NEW" sh -c 'MYSQL_PWD="$MYSQL_ROOT_PASSWORD" exec mysql -uroot -N -B acore_auth'; }

cols=$(echo "SELECT GROUP_CONCAT(LOWER(column_name)) FROM information_schema.columns WHERE table_schema='classicrealmd' AND table_name='account';" | old_sql)
echo "1.12 account columns: $cols"
sel="username"
for c in s v sha_pass_hash email; do
  case ",$cols," in *",$c,"*) sel="$sel, COALESCE($c,'')";; *) sel="$sel, ''";; esac
done
TMP=$(mktemp -d); trap 'rm -rf "$TMP"' EXIT
echo "SELECT $sel FROM account WHERE username NOT LIKE 'RNDBOT%';" | old_sql > "$TMP/old.tsv"
echo "SELECT UPPER(username) FROM account;" | new_sql > "$TMP/have.txt"

python3 -I - "$TMP/old.tsv" "$TMP/have.txt" "$TMP/insert.sql" <<'PY'
import hashlib, os, re, sys
N = int("894B645E89E1535BBDAD5B8B290650530801B18EBFBF5E8FAB3C82872A3E9BB7", 16); g = 7
old, have_f, out = sys.argv[1:4]
have = {l.strip().upper() for l in open(have_f, encoding="utf-8", errors="replace") if l.strip()}
NAME = re.compile(r"^[A-Za-z0-9]{1,20}$")
HEX = re.compile(r"^[0-9A-Fa-f]+$")
rows, already, short, nologin, badname = [], [], [], [], []
for line in open(old, encoding="utf-8", errors="replace"):
    f = line.rstrip("\n").split("\t")
    if len(f) < 5: continue
    user, s, v, sha, email = f[0].upper(), f[1].strip(), f[2].strip(), f[3].strip(), f[4].strip()
    if not NAME.match(user): badname.append(user); continue
    if user in have: already.append(user); continue
    salt = ver = None
    if s and v and HEX.match(s) and HEX.match(v) and 63 <= len(s) <= 64 and len(v) <= 64:
        s_be = bytes.fromhex(s.zfill(64))
        if s_be[0] != 0:
            salt, ver = s_be[::-1], bytes.fromhex(v.zfill(64))[::-1]
    if salt is None and sha and HEX.match(sha) and len(sha) == 40:
        # older 1.12 servers kept SHA1(USER:PASS): make a fresh salt and the verifier from it
        salt = os.urandom(32)
        x = int.from_bytes(hashlib.sha1(salt + bytes.fromhex(sha)).digest(), "little")
        ver = pow(g, x, N).to_bytes(32, "little")
    if salt is None:
        (short if s else nologin).append(user); continue
    em = email if re.match(r"^[^'\\\s]{1,255}$", email or "") else ""
    rows.append(f"('{user}', UNHEX('{salt.hex()}'), UNHEX('{ver.hex()}'), '{em}', '{em}', 2)")
with open(out, "w") as o:
    for i in range(0, len(rows), 200):
        o.write("INSERT IGNORE INTO account (username, salt, verifier, email, reg_mail, expansion) VALUES\n"
                + ",\n".join(rows[i:i + 200]) + ";\n")
print(f"to carry over:          {len(rows)}")
print(f"already on Wrath:       {len(already)}  (left as they are)")
print(f"short 1.12 salt:        {len(short)}  {' '.join(short[:20])}")
print(f"no stored login:        {len(nologin)}  {' '.join(nologin[:20])}")
if badname: print(f"unusual names skipped:  {len(badname)}  {' '.join(badname[:20])}")
if rows: print("first few:", " ".join(r.split("'")[1] for r in rows[:15]))
PY

if [ $APPLY = 0 ]; then echo; echo "Dry run: nothing changed. Run again with --apply to copy them."; exit 0; fi
[ -s "$TMP/insert.sql" ] || { echo "Nothing to copy."; exit 0; }
mkdir -p /root/wrath-backups
docker exec "$NEW" sh -c 'MYSQL_PWD="$MYSQL_ROOT_PASSWORD" exec mysqldump -uroot --single-transaction acore_auth account' \
  | gzip > "/root/wrath-backups/acore_auth-account-$STAMP.sql.gz"
[ "$(stat -c %s "/root/wrath-backups/acore_auth-account-$STAMP.sql.gz")" -gt 500 ] || { echo "The backup looks empty: stopped, nothing changed."; exit 1; }
echo "Backup: /root/wrath-backups/acore_auth-account-$STAMP.sql.gz"
new_sql < "$TMP/insert.sql"
echo "SELECT COUNT(*) FROM account WHERE username NOT LIKE 'RNDBOT%';" | new_sql | sed 's/^/Wrath accounts now (not bots): /'
echo "Done. Old 1.12 usernames and passwords now work in the 3.3.5a client (set realmlist play.openvanilla.app)."
