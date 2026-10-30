#!/usr/bin/env bash
# Points the realm list at the address players' clients must use for the world server: updates
# acore_auth.realmlist (name, address, localAddress, port). Drop-in for server/set-realm-address.sh,
# plus a world port and a relay mode.
#
#   ./set-realm-address.sh <public-host> [realm-name] [world-port]
#   ./set-realm-address.sh play.example.com "WrathUnleashed"            port 8085 (direct, as before)
#   ./set-realm-address.sh relay.openvanilla.app "Frost Haven" 40001    behind the relay
#   ./set-realm-address.sh --relay STATE_DIR [realm-name]                read host/port from the agent's
#                                                                        STATE_DIR/relay-state.json
#
# Behind the relay the address is the relay's and the port is the realm's own relay world port
# (auth port + 1), so clients reconnect through the relay and never learn the host's IP. Home
# hosts don't need this script: the wu-agent sets the same row itself on every (re)connect.
#
# Env: WU_REALM_ID (default 1), WU_REALM_NAME (default "WrathUnleashed"), WU_DB_CONTAINER
# (default ov-ac-database; the home kit's is wu-host-database).
# The authserver re-reads the realm list every 20 s (RealmsStateUpdateDelay); no restart needed.
set -euo pipefail

if [[ "${1:-}" == "--relay" ]]; then
  st="${2:?usage: --relay STATE_DIR [realm-name]}/relay-state.json"
  [[ -f "$st" ]] || { echo "error: $st not found (is the agent connected?)" >&2; exit 2; }
  host=$(sed -n 's/^ *"address": *"\([^"]*\)".*/\1/p' "$st" | head -1)
  port=$(sed -n 's/^ *"world_port": *\([0-9]*\).*/\1/p' "$st" | head -1)
  name="${3:-${WU_REALM_NAME:-WrathUnleashed}}"
else
  host="${1:-}"
  name="${2:-${WU_REALM_NAME:-WrathUnleashed}}"
  port="${3:-8085}"
fi
realm_id="${WU_REALM_ID:-1}"
db="${WU_DB_CONTAINER:-ov-ac-database}"

usage() { sed -n '2,10p' "$0" | sed 's/^# \{0,1\}//'; exit 2; }
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
if [[ ! "$port" =~ ^[0-9]{1,5}$ ]] || (( port < 1 || port > 65535 )); then
  echo "error: world port must be 1-65535" >&2; exit 2
fi

# A DNS name that does not resolve leaves players stuck at "connecting" after the realm list.
if [[ ! "$host" =~ ^[0-9.]+$ ]] && ! getent ahostsv4 "$host" >/dev/null; then
  echo "warning: '$host' does not resolve from this box yet; players cannot connect until it does" >&2
fi

echo "[1/2] Setting realm ${realm_id}: name='${name}' address='${host}' localAddress='${host}' port=${port}"
docker exec -i "$db" sh -c 'MYSQL_PWD="$MYSQL_ROOT_PASSWORD" exec mysql -uroot acore_auth' <<SQL
UPDATE realmlist
   SET name = '${name}', address = '${host}', localAddress = '${host}', port = ${port}
 WHERE id = ${realm_id};
SELECT ROW_COUNT() AS rows_changed;
SQL

echo "[2/2] Realm list now:"
docker exec -i "$db" sh -c 'MYSQL_PWD="$MYSQL_ROOT_PASSWORD" exec mysql -uroot -t acore_auth' <<'SQL'
SELECT id, name, address, localAddress, port, gamebuild FROM realmlist;
SQL
echo "Done. Players use:  set realmlist ${host}   (authserver picks this up within ~20 s)"
