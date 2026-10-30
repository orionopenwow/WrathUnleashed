#!/bin/sh
# The TrinityCore 4.3.4 server image's entry point (Leyline host kit, profile tcpp-4.3.4): writes the config, then
# runs the server. The config is the core's own .conf.dist, then Leyline's (leyline-*.conf: paths, network, no
# console or remote admin), then this realm's database login.
#   run-server.sh worldserver | authserver
#   run-server.sh update     (the db-import image) the world server's own updater: makes the databases from
#                            sql/base and the TDB files in this folder, applies sql/updates, then exits
set -eu
what="${1:-worldserver}"
case "$what" in worldserver|authserver|update) ;; *) exec "$@" ;; esac
ETC=/opt/tc/etc
OUT="${LL_CONF_DIR:-/tmp}"
DB_HOST="${DB_HOST:-realm-db}"
PW="${DB_ROOT_PASSWORD:-}"
case "$PW" in ""|*[!A-Za-z0-9]*) echo "DB_ROOT_PASSWORD missing or not letters and digits (run the host kit's setup)" >&2; exit 1 ;; esac

# apply OVERRIDES CONF: every "Key = Value" line of OVERRIDES replaces that key in CONF (or is added at the end).
apply() {
  awk 'function key(s) { sub(/[ \t]*=.*/, "", s); return s }
       NR == FNR { if ($0 ~ /^[A-Za-z][A-Za-z0-9_.]*[ \t]*=/) { k = key($0); v = $0; sub(/^[^=]*=[ \t]*/, "", v);
                                                             if (!(k in o)) ord[++n] = k; o[k] = v }
                   next }
       $0 ~ /^[A-Za-z][A-Za-z0-9_.]*[ \t]*=/ { k = key($0); if (k in o) { print k " = " o[k]; seen[k] = 1; next } }
       { print }
       END { for (i = 1; i <= n; i++) if (!(ord[i] in seen)) print ord[i] " = " o[ord[i]] }' "$1" "$2" > "$2.new"
  mv "$2.new" "$2"
}

bin="$what"; [ "$what" = update ] && bin=worldserver
conf="$OUT/$bin.conf"
cp "$ETC/$bin.conf.dist" "$conf"
apply "/opt/leyline/leyline-$bin.conf" "$conf"
db() { printf '"%s;3306;root;%s;%s"' "$DB_HOST" "$PW" "$1"; }
{
  echo "LoginDatabaseInfo = $(db auth)"
  if [ "$bin" = worldserver ]; then
    echo "WorldDatabaseInfo = $(db world)"
    echo "CharacterDatabaseInfo = $(db characters)"
    echo "HotfixDatabaseInfo = $(db hotfixes)"
    echo "PlayerLimit = ${WU_PLAYER_LIMIT:-100}"
  fi
  if [ "$what" = update ]; then
    echo "Updates.EnableDatabases = 15"
    echo "Updates.AutoSetup = 1"
    echo "SourceDirectory = \"/opt/tc/src\""
    echo "MySQLExecutable = \"$(command -v mariadb || command -v mysql)\""
  fi
} > "$OUT/$bin.db.conf"
apply "$OUT/$bin.db.conf" "$conf"
rm -f "$OUT/$bin.db.conf"
chmod 600 "$conf"
if [ "$what" = update ]; then
  "/opt/tc/bin/worldserver" -c "$conf" --update-databases-only
  # The realm list row for this client build (the agent points its address at the relay).
  MYSQL_PWD="$PW" mariadb -h"$DB_HOST" -uroot auth -e "INSERT INTO realmlist (id, name, gamebuild) VALUES
    (1, 'Leyline realm', 15595) ON DUPLICATE KEY UPDATE gamebuild = 15595"
  echo "databases ready"
  exit 0
fi
exec "/opt/tc/bin/$bin" -c "$conf"
