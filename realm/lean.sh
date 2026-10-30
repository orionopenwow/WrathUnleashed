#!/usr/bin/env bash
# WrathUnleashed: lean server (owner 2026-10-24: "least memory on server as possible"; Dalaran and the starter zones first).
# 60 -> 30 random bots (they roam the whole world and keep its grids loaded); idle map grids unload after 1 minute
# instead of 5; the database's unused performance monitoring off. Dalaran and the starter zones are unaffected.
# Sets the keys in the realm's profile (backup first), announces a 5-minute restart in game, then recreates
# the world server. Safe to run again (nothing happens if the running server already has them).
set -euo pipefail
cd /srv/wrath
die() { printf '\nLEAN FAILED: %s\n' "$*" >&2; exit 1; }
PROFILE=$(grep -E '^OV_PROFILE=' .env 2>/dev/null | tail -1 | cut -d= -f2 | tr -d '\r"' || true)
[ "${PROFILE:-}" = main ] || die "the realm runs the '${PROFILE:-?}' profile, not 'main'"
PF=profiles/main.env
[ -f "$PF" ] || die "no $PF"
BK=/root/lean-backups/$(date +%Y%m%d-%H%M%S); mkdir -p "$BK"; cp -p "$PF" "$BK/profile.env"
sed -i 's/\r$//' "$PF"
# Bot counts live in modules.env (read after the profile, so it wins); grid settings go in the profile.
MF=modules.env
# The Leyline Sample Hangout (realm/sampler.sh) sets its own bot count and grid settings: leave them alone.
if grep -qxF "# <<< Leyline Sample Hangout" "$PF" 2>/dev/null || grep -qxF "# <<< Leyline Sample Hangout" "$MF" 2>/dev/null; then
  echo "  the Leyline Sample Hangout is on: its settings (realm/profiles/sampler.env) are already the lean ones; nothing changed"
  echo "LEAN OK"; exit 0
fi
[ -f "$MF" ] && cp -p "$MF" "$BK/modules.env" && sed -i 's/\r$//' "$MF"
need=0
setkv() {  # file key value
  local f=$1 k=$2 v=$3
  if grep -qE "^$k=" "$f"; then sed -i "s#^$k=.*#$k=$v#" "$f"; else printf '%s=%s\n' "$k" "$v" >> "$f"; fi
  [ "$(docker exec ov-ac-worldserver printenv "$k" 2>/dev/null || true)" = "$v" ] || need=1
  echo "  $k=$v ($f)"
}
if [ -f "$MF" ]; then
  setkv "$MF" AC_PLAYERBOTS_MIN_RANDOM_BOTS 30
  setkv "$MF" AC_PLAYERBOTS_MAX_RANDOM_BOTS 30
else
  setkv "$PF" AC_PLAYERBOTS_MIN_RANDOM_BOTS 30
  setkv "$PF" AC_PLAYERBOTS_MAX_RANDOM_BOTS 30
fi
setkv "$PF" AC_GRID_UNLOAD 1
setkv "$PF" AC_GRID_CLEAN_UP_DELAY 60000
# Database: MySQL 8.4's performance_schema holds several hundred MB and nothing here reads it. PERSIST_ONLY saves the
# setting inside the database volume (mysqld-auto.cnf), so it survives restarts and container re-creates.
dbq() { docker exec -i ov-ac-database sh -c 'MYSQL_PWD="$MYSQL_ROOT_PASSWORD" exec mysql -uroot -N -B' <<<"$1"; }
echo "  database before: $(docker stats --no-stream --format '{{.MemUsage}}' ov-ac-database), performance_schema=$(dbq 'SELECT @@performance_schema'), buffer pool $(( $(dbq 'SELECT @@innodb_buffer_pool_size') / 1048576 )) MB, max_connections=$(dbq 'SELECT @@max_connections')"
dbneed=0
[ "$(dbq 'SELECT @@performance_schema')" = 1 ] && dbneed=1
if [ "$need" = 0 ] && [ "$dbneed" = 0 ]; then echo "  the server already has these settings"; echo "LEAN OK"; exit 0; fi
MIN=${LEAN_WARN_MIN:-5}
if [ "$MIN" -gt 0 ]; then
  echo "== announcing a restart in $MIN minute(s)"
  bash soap-cmd.sh "announce Server restart in $MIN minutes: a lighter, steadier server. Back in a few minutes." >/dev/null 2>&1 || true
  sleep $(( MIN * 60 - 60 )) || true
  bash soap-cmd.sh "announce Server restart in 1 minute." >/dev/null 2>&1 || true
  sleep 60
  bash soap-cmd.sh "saveall" >/dev/null 2>&1 || true
fi
if [ "$dbneed" = 1 ]; then
  echo "== database: performance_schema off (restart of the database, about 30 s)"
  dbq "SET PERSIST_ONLY performance_schema = OFF; SET PERSIST max_connections = 200;" >/dev/null
  docker stop ov-ac-worldserver >/dev/null 2>&1 || true
  docker restart ov-ac-database >/dev/null
  for i in $(seq 1 60); do
    [ "$(docker inspect -f '{{.State.Health.Status}}' ov-ac-database 2>/dev/null)" = healthy ] && break
    sleep 3
  done
  [ "$(docker inspect -f '{{.State.Health.Status}}' ov-ac-database 2>/dev/null)" = healthy ] || die "the database did not come back healthy: docker logs --tail 50 ov-ac-database"
  docker restart ov-ac-authserver >/dev/null 2>&1 || true
  echo "  database after: performance_schema=$(dbq 'SELECT @@performance_schema')"
fi
echo "== recreating the world server (2-10 minutes)"
started() { docker inspect -f '{{.State.StartedAt}}' ov-ac-worldserver; }
docker compose up -d --no-deps ac-worldserver
sleep 3
ok=0
for i in $(seq 1 120); do
  if docker logs --since "$(started)" ov-ac-worldserver 2>&1 | grep -F 'ready...' >/dev/null; then ok=1; break; fi
  if (( i % 6 == 0 )); then echo "  still starting ($((i * 10 / 60)) min)..."; fi
  sleep 10
done
[ "$ok" = 1 ] || die "the world server did not report ready in 20 min: docker logs --tail 80 ov-ac-worldserver. Old profile: $BK/profile.env"
sleep 60; echo "  world server ready:"; docker stats --no-stream --format '  {{.Name}} {{.MemUsage}}' ov-ac-worldserver ov-ac-database
echo "LEAN OK"
