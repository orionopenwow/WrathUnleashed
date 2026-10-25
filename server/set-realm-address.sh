#!/usr/bin/env bash
# Points the realm list at this box: updates acore_auth.realmlist (address, localAddress, name).
#
#   ./set-realm-address.sh <public-host> [realm-name]
#   ./set-realm-address.sh play.example.com "WrathUnleashed"
#   ./set-realm-address.sh 203.0.113.10
#
# <public-host> is what players' clients connect to after login: a DNS name (must already
# resolve, the authserver looks it up) or the box's public IPv4. Both address and
# localAddress get it: players are never on the box's LAN, and the Docker bridge would
# otherwise hand containers' 172.x addresses to nobody useful.
#
# Env: WU_REALM_ID (default 1, must match the worldserver's RealmID),
#      WU_REALM_NAME (default "WrathUnleashed", used when no second argument is given),
#      WU_DB_CONTAINER (default ov-ac-database).
#
# The authserver re-reads the realm list every 20 s (RealmsStateUpdateDelay); no restart needed.

set -euo pipefail

host="${1:-}"
name="${2:-${WU_REALM_NAME:-WrathUnleashed}}"
realm_id="${WU_REALM_ID:-1}"
db="${WU_DB_CONTAINER:-ov-ac-database}"

usage() { sed -n '2,8p' "$0" | sed 's/^# \{0,1\}//'; exit 2; }
[[ -n "$host" ]] || usage

# Strict input checks: these values go into SQL, so only allow characters that need no quoting.
if [[ ! "$host" =~ ^[A-Za-z0-9.-]{1,253}$ ]]; then
  echo "error: host must be a DNS name or IPv4 address (letters, digits, dots, hyphens)" >&2; exit 2
fi
if [[ ! "$name" =~ ^[A-Za-z0-9\ _-]{1,32}$ ]]; then
  echo "error: realm name: 1-32 letters, digits, spaces, '_' or '-'" >&2; exit 2
fi
if [[ ! "$realm_id" =~ ^[0-9]+$ ]]; then
  echo "error: WU_REALM_ID must be a number" >&2; exit 2
fi

# A DNS name that does not resolve leaves players stuck at "connecting" after the realm list.
if [[ ! "$host" =~ ^[0-9.]+$ ]] && ! getent ahostsv4 "$host" >/dev/null; then
  echo "warning: '$host' does not resolve from this box yet; players cannot connect until it does" >&2
fi

echo "[1/2] Setting realm ${realm_id}: name='${name}' address='${host}' localAddress='${host}'"
# The password is read inside the container from its own environment, so it never appears
# on this host's command line or in this script.
docker exec -i "$db" sh -c 'MYSQL_PWD="$MYSQL_ROOT_PASSWORD" exec mysql -uroot acore_auth' <<SQL
UPDATE realmlist
   SET name = '${name}', address = '${host}', localAddress = '${host}', port = 8085
 WHERE id = ${realm_id};
SELECT ROW_COUNT() AS rows_changed;
SQL

echo "[2/2] Realm list now:"
docker exec -i "$db" sh -c 'MYSQL_PWD="$MYSQL_ROOT_PASSWORD" exec mysql -uroot -t acore_auth' <<'SQL'
SELECT id, name, address, localAddress, port, gamebuild FROM realmlist;
SQL
echo "Done. Players use:  set realmlist ${host}   (authserver picks this up within ~20 s)"
