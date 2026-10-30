#!/bin/sh
# The CMaNGOS server image's entry point (Leyline host kit, profiles cmangos-1.12.1 and cmangos-2.4.3: the same
# file in both): writes mangosd.conf / realmd.conf, then runs the server. The config is the core's own .conf.dist,
# then Leyline's (leyline-*.conf: paths, network, no console or remote admin), then this realm's database login.
#   run-server.sh mangosd | realmd
#   LL_DB_PREFIX   classic | tbc (the installer's database names: <prefix>realmd, <prefix>mangos, ...)
set -eu
what="${1:-mangosd}"
case "$what" in mangosd|realmd) ;; *) exec "$@" ;; esac
ETC=/opt/cmangos/etc
OUT="${LL_CONF_DIR:-/tmp}"
DB_HOST="${DB_HOST:-realm-db}"
P="${LL_DB_PREFIX:?LL_DB_PREFIX missing (the profile's compose file sets it)}"
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

conf="$OUT/$what.conf"
cp "$ETC/$what.conf.dist" "$conf"
apply "/opt/leyline/leyline-$what.conf" "$conf"
db() { printf '"%s;3306;root;%s;%s"' "$DB_HOST" "$PW" "$1"; }
{
  echo "LoginDatabaseInfo = $(db "${P}realmd")"
  if [ "$what" = mangosd ]; then
    echo "WorldDatabaseInfo = $(db "${P}mangos")"
    echo "CharacterDatabaseInfo = $(db "${P}characters")"
    echo "LogsDatabaseInfo = $(db "${P}logs")"
    echo "PlayerLimit = ${WU_PLAYER_LIMIT:-100}"
  fi
} > "$OUT/$what.db.conf"
apply "$OUT/$what.db.conf" "$conf"
rm -f "$OUT/$what.db.conf"
chmod 600 "$conf"
exec "/opt/cmangos/bin/$what" -c "$conf"
