#!/usr/bin/env bash
# WrathUnleashed server pass (2026-10-24): Dungeon Finder from level 10, bug reports and QoL commands,
# cross-faction grouping. Reads a tar of .lua files on stdin. Everything is backed up first.
#   1. Lua: installs the uploaded scripts into custom/lua_scripts (ov_slices.lua: the finder gate at 10;
#      ov_reports.lua: .bug / .stuck / .wu).
#   2. World DB: dungeon_access_template min_level 10 for Ragefire Chasm (389), Wailing Caverns (43),
#      the Deadmines (36) and Shadowfang Keep (33), normal difficulty.
#   3. Profile: DungeonAccessRequirements.LFGLevelDBCOverride = 1 (the finder uses that table's levels
#      instead of LFGDungeons.dbc's 15), AllowTwoSide.Interaction.Group = 1 (friends on either side can group).
#      OV_AUTOLEARN = 1: ov_qol.lua's instant spell learn on level up (the profile had it at 0).
#   4. Announces a restart (SERVERPASS_WARN_MIN, default 5) and recreates the world server; if only the Lua
#      changed, a live "reload ale" instead.
# Never prints a password: MySQL runs in its container with the container's own root password.
set -euo pipefail
cd /srv/wrath
die() { printf '\nSERVERPASS FAILED: %s\n' "$*" >&2; exit 1; }
PROFILE=$(grep -E '^OV_PROFILE=' .env 2>/dev/null | tail -1 | cut -d= -f2 | tr -d '\r"' || true)
[ "${PROFILE:-}" = main ] || die "the realm runs the '${PROFILE:-?}' profile, not 'main'"
PF=profiles/main.env
[ -f "$PF" ] || die "no $PF"
BK=/root/serverpass-backups/$(date +%Y%m%d-%H%M%S); mkdir -p "$BK"
cp -p "$PF" "$BK/profile.env"
sqlq() { docker exec -i ov-ac-database sh -c 'MYSQL_PWD="$MYSQL_ROOT_PASSWORD" exec mysql -uroot -N -B acore_world' <<<"$1"; }

echo "== 1. realm scripts"
DST=custom/lua_scripts
T=$(mktemp -d); trap 'rm -rf "$T"' EXIT
tar -x -C "$T" -f -
n=0
for f in "$T"/*.lua; do
  [ -f "$f" ] || continue
  b=$(basename "$f"); sed -i 's/\r$//' "$f"
  [ -f "$DST/$b" ] && cp -p "$DST/$b" "$BK/$b"
  install -m 644 "$f" "$DST/$b"; echo "  $b installed"; n=$((n+1))
done
[ "$n" -gt 0 ] || die "no .lua files in the upload"

echo "== 2. dungeon levels (world database)"
docker exec ov-ac-database sh -c 'MYSQL_PWD="$MYSQL_ROOT_PASSWORD" exec mysqldump -uroot --single-transaction --skip-lock-tables acore_world dungeon_access_template' \
  | gzip > "$BK/dungeon_access_template.sql.gz"
gzip -dc "$BK/dungeon_access_template.sql.gz" | grep -q 'CREATE TABLE' || die "could not back up dungeon_access_template; nothing changed in the database"
MAPS="389,43,36,33"
sqlq "UPDATE dungeon_access_template SET min_level = 10 WHERE map_id IN ($MAPS) AND difficulty = 0 AND min_level > 10" >/dev/null
sqlq "SELECT map_id, min_level, max_level FROM dungeon_access_template WHERE map_id IN ($MAPS) AND difficulty = 0 ORDER BY map_id" \
  | while read -r m lo hi; do echo "  map $m: levels $lo-$hi"; done
missing=$(sqlq "SELECT COUNT(*) FROM (SELECT 389 m UNION SELECT 43 UNION SELECT 36 UNION SELECT 33) w WHERE m NOT IN (SELECT map_id FROM dungeon_access_template WHERE difficulty = 0)")
[ "${missing:-0}" = 0 ] || echo "  NOTE: $missing of the four maps have no access row; the finder keeps the DBC level for them"

echo "== 3. profile"
sed -i 's/\r$//' "$PF"
need=0
for kv in AC_DUNGEON_ACCESS_REQUIREMENTS_LFGLEVEL_DBCOVERRIDE=1 AC_ALLOW_TWO_SIDE_INTERACTION_GROUP=1 OV_AUTOLEARN=1; do
  k=${kv%%=*}; v=${kv#*=}
  if grep -qE "^$k=" "$PF"; then sed -i "s#^$k=.*#$k=$v#" "$PF"; else printf '%s=%s\n' "$k" "$v" >> "$PF"; fi
  [ "$(docker exec ov-ac-worldserver printenv "$k" 2>/dev/null || true)" = "$v" ] || need=1
  echo "  $k=$v"
done

if [ "$need" = 0 ]; then
  echo "== 4. settings already live: reloading the scripts only"
  out=$(bash soap-cmd.sh "reload ale" 2>&1) || {
    for b in "$BK"/*.lua; do [ -f "$b" ] && cp -p "$b" "$DST/"; done
    bash soap-cmd.sh "reload ale" >/dev/null 2>&1 || true
    die "reload ale refused ($out); the previous scripts are back"
  }
  echo "  reload ale: ${out:-ok}"
else
  MIN=${SERVERPASS_WARN_MIN:-5}
  if [ "$MIN" -gt 0 ]; then
    echo "== 4. announcing a restart in $MIN minute(s)"
    bash soap-cmd.sh "announce Server restart in $MIN minutes: Dungeon Finder from level 10, bug reports (.bug). Back in a few minutes." >/dev/null 2>&1 || true
    sleep $(( MIN * 60 - 60 )) || true
    bash soap-cmd.sh "announce Server restart in 1 minute." >/dev/null 2>&1 || true
    sleep 60
    bash soap-cmd.sh "saveall" >/dev/null 2>&1 || true
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
  [ "$ok" = 1 ] || die "the world server did not report ready in 20 min: docker logs --tail 80 ov-ac-worldserver. Backups: $BK"
  echo "  world server ready"
fi
sleep 2
if docker logs --since 60s ov-ac-worldserver 2>&1 | grep -iE 'lua.*(error|failed)|ALE.*error' | tail -5 | grep . ; then
  echo "  (the lines above are Lua errors: check them)"
fi
echo "  backups: $BK"
echo "SERVERPASS OK"
