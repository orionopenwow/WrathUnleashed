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
#      AC_PLAYERBOTS_MAX_ADDED_BOTS = 4: the bot module's per-player cap, same as ov_companions.lua's.
#   1b. The web armory (play.openvanilla.app/wrath/armory, stream/armory.py), when armory-export.py rides
#      along: makes characters.ov_armory_privacy (the ".armory off" flag, ov_armory.lua), installs
#      /srv/wrath/armory-export.py, which writes /srv/wrath/portal/armory/ (wu-portal's /app/armory) from
#      cron every 5 minutes, and runs it once. Read only: fixed SELECTs in a READ ONLY session, no new
#      database login. Bots and opted-out characters are left out. Backs up the old script and cron file.
#   1c. The Workshop on the web (play.openvanilla.app/wrath/workshop, stream/creations.py), when
#      workshop-export.py rides along: makes characters.mod_workshop_items (ov_workshop.lua's table, so the export
#      works before the restart that loads the script), installs /srv/wrath/workshop-export.py, which writes
#      /srv/wrath/portal/workshop/items.json (wu-portal's /app/workshop) from cron every 5 minutes, and runs it
#      once. Read only, approved items only, no new database login.
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
n=0; changed=0; NEW=""
for f in "$T"/*.lua; do
  [ -f "$f" ] || continue
  b=$(basename "$f"); sed -i 's/\r$//' "$f"; n=$((n+1))
  if [ -f "$DST/$b" ] && cmp -s "$f" "$DST/$b"; then echo "  $b unchanged"; continue; fi
  if [ -f "$DST/$b" ]; then cp -p "$DST/$b" "$BK/$b"; else NEW="$NEW $b"; fi
  install -m 644 "$f" "$DST/$b"; echo "  $b installed"; changed=$((changed+1))
done
[ "$n" -gt 0 ] || die "no .lua files in the upload"
# A script the realm has never run is loaded by a restart (with the warning below), never by a live
# "reload ale": on 2026-10-25 a reload that added two new scripts crashed the world server (no warning
# for players). Changed scripts the realm already runs still reload live.
[ -z "$NEW" ] || echo "  new scripts:$NEW (loaded by a restart)"
# The Leyline realm list for the in-game window: leyline-fetch.py rides along in the upload; it goes to
# /srv/wrath, runs every 5 minutes from cron, and once now (a failed fetch keeps the old list).
if [ -f "$T/leyline-fetch.py" ]; then
  sed -i 's/\r$//' "$T/leyline-fetch.py"
  if python3 -I -c 'import ast,sys;ast.parse(open(sys.argv[1]).read())' "$T/leyline-fetch.py"; then
    install -m 755 "$T/leyline-fetch.py" /srv/wrath/leyline-fetch.py
    printf '*/5 * * * * root python3 -I /srv/wrath/leyline-fetch.py >/dev/null 2>&1\n' > /etc/cron.d/leyline-realms
    chmod 644 /etc/cron.d/leyline-realms
    python3 -I /srv/wrath/leyline-fetch.py >/dev/null 2>&1 && echo "  Leyline realm list fetched (cron every 5 min)" \
      || echo "  NOTE: the first Leyline realm list fetch failed; cron tries again in 5 minutes"
  else
    echo "  NOTE: leyline-fetch.py doesn't parse; skipped"
  fi
fi

# The web armory's export (see 1b above). Safe to run again: CREATE TABLE IF NOT EXISTS, install, one cron file.
if [ -f "$T/armory-export.py" ]; then
  echo "== 1b. web armory export"
  sed -i 's/\r$//' "$T/armory-export.py"
  if python3 -I -c 'import ast,sys;ast.parse(open(sys.argv[1]).read())' "$T/armory-export.py"; then
    [ -f /srv/wrath/armory-export.py ] && cp -p /srv/wrath/armory-export.py "$BK/armory-export.py"
    [ -f /etc/cron.d/wu-armory ] && cp -p /etc/cron.d/wu-armory "$BK/cron.wu-armory"
    docker exec -i ov-ac-database sh -c 'MYSQL_PWD="$MYSQL_ROOT_PASSWORD" exec mysql -uroot -N -B acore_characters' <<'SQL' || die "could not make ov_armory_privacy"
CREATE TABLE IF NOT EXISTS ov_armory_privacy (
  guid INT UNSIGNED NOT NULL PRIMARY KEY,
  hidden TINYINT UNSIGNED NOT NULL DEFAULT 0,
  changed_at INT UNSIGNED NOT NULL
);
SQL
    install -m 755 "$T/armory-export.py" /srv/wrath/armory-export.py
    install -d -m 755 /srv/wrath/portal/armory
    printf '*/5 * * * * root python3 -I /srv/wrath/armory-export.py >/dev/null 2>&1\n' > /etc/cron.d/wu-armory
    chmod 644 /etc/cron.d/wu-armory
    if out=$(python3 -I /srv/wrath/armory-export.py 2>&1); then echo "  $out (cron every 5 min)"
    else echo "  NOTE: the first armory export failed (${out:0:200}); cron tries again in 5 minutes"; fi
  else
    echo "  NOTE: armory-export.py doesn't parse; skipped"
  fi
fi

# The Workshop's export (see 1c above). Safe to run again: CREATE TABLE IF NOT EXISTS, install, one cron file.
if [ -f "$T/workshop-export.py" ]; then
  echo "== 1c. Workshop export"
  sed -i 's/\r$//' "$T/workshop-export.py"
  if python3 -I -c 'import ast,sys;ast.parse(open(sys.argv[1]).read())' "$T/workshop-export.py"; then
    [ -f /srv/wrath/workshop-export.py ] && cp -p /srv/wrath/workshop-export.py "$BK/workshop-export.py"
    [ -f /etc/cron.d/wu-workshop ] && cp -p /etc/cron.d/wu-workshop "$BK/cron.wu-workshop"
    docker exec -i ov-ac-database sh -c 'MYSQL_PWD="$MYSQL_ROOT_PASSWORD" exec mysql -uroot -N -B acore_characters' <<'SQL' || die "could not make mod_workshop_items"
CREATE TABLE IF NOT EXISTS mod_workshop_items (
  id INT UNSIGNED NOT NULL PRIMARY KEY, kind VARCHAR(8) NOT NULL, ref VARCHAR(32) NOT NULL,
  title VARCHAR(48) NOT NULL, author VARCHAR(12) NOT NULL, author_guid INT UNSIGNED NOT NULL,
  version SMALLINT UNSIGNED NOT NULL DEFAULT 1, created_at INT UNSIGNED NOT NULL, updated_at INT UNSIGNED NOT NULL,
  plays INT UNSIGNED NOT NULL DEFAULT 0, up INT UNSIGNED NOT NULL DEFAULT 0, down INT UNSIGNED NOT NULL DEFAULT 0,
  state VARCHAR(8) NOT NULL DEFAULT 'pending', descr VARCHAR(160) NOT NULL DEFAULT '',
  UNIQUE KEY kind_ref (kind, ref), KEY state (state), KEY author (author_guid)
);
SQL
    install -m 755 "$T/workshop-export.py" /srv/wrath/workshop-export.py
    install -d -m 755 /srv/wrath/portal/workshop
    printf '*/5 * * * * root python3 -I /srv/wrath/workshop-export.py >/dev/null 2>&1\n' > /etc/cron.d/wu-workshop
    chmod 644 /etc/cron.d/wu-workshop
    if out=$(python3 -I /srv/wrath/workshop-export.py 2>&1); then echo "  $out (cron every 5 min)"
    else echo "  NOTE: the first Workshop export failed (${out:0:200}); cron tries again in 5 minutes"; fi
  else
    echo "  NOTE: workshop-export.py doesn't parse; skipped"
  fi
fi

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
for kv in AC_DUNGEON_ACCESS_REQUIREMENTS_LFGLEVEL_DBCOVERRIDE=1 AC_ALLOW_TWO_SIDE_INTERACTION_GROUP=1 OV_AUTOLEARN=1 AC_PLAYERBOTS_MAX_ADDED_BOTS=4; do
  k=${kv%%=*}; v=${kv#*=}
  if grep -qE "^$k=" "$PF"; then sed -i "s#^$k=.*#$k=$v#" "$PF"; else printf '%s=%s\n' "$k" "$v" >> "$PF"; fi
  [ "$(docker exec ov-ac-worldserver printenv "$k" 2>/dev/null || true)" = "$v" ] || need=1
  echo "  $k=$v"
done

# Scripts the running world server has not loaded yet, even from an earlier pass: $DST/.ov-loaded lists
# what the last successful load (restart or reload) had; without it, anything newer than the server's start.
envchange=$need
LOADED_LIST="$DST/.ov-loaded"
start_epoch=$(date -d "$(docker inspect -f '{{.State.StartedAt}}' ov-ac-worldserver 2>/dev/null || echo now)" +%s 2>/dev/null || date +%s)
for f in "$DST"/*.lua; do
  [ -f "$f" ] || continue
  b=$(basename "$f")
  case " $NEW " in *" $b "*) continue ;; esac
  if [ -f "$LOADED_LIST" ]; then
    grep -qxF "$b" "$LOADED_LIST" || NEW="$NEW $b"
  elif [ "$(stat -c %Y "$f")" -gt "$start_epoch" ]; then
    NEW="$NEW $b"
  fi
done
[ -z "$NEW" ] || { echo "  not yet loaded by the world server:$NEW (a restart loads them)"; need=1; }
mark_loaded() { (cd "$DST" && ls -1 *.lua 2>/dev/null) > "$LOADED_LIST" || true; }
if [ "$need" = 0 ] && [ "$changed" = 0 ]; then
  echo "== 4. settings and scripts already live: nothing to reload"
  [ -f "$LOADED_LIST" ] || mark_loaded
elif [ "$need" = 0 ]; then
  echo "== 4. settings already live: reloading the changed scripts"
  out=$(bash soap-cmd.sh "reload ale" 2>&1) || {
    for b in "$BK"/*.lua; do [ -f "$b" ] && cp -p "$b" "$DST/"; done
    # the reload may have taken the world server down: wait for it (docker restarts it) before reporting
    for _ in $(seq 1 60); do bash soap-cmd.sh "server info" >/dev/null 2>&1 && break; sleep 10; done
    bash soap-cmd.sh "reload ale" >/dev/null 2>&1 || true
    die "reload ale refused ($out); the previous scripts are back"
  }
  echo "  reload ale: ${out:-ok}"
  mark_loaded
else
  MIN=${SERVERPASS_WARN_MIN:-5}
  if [ "$MIN" -gt 0 ]; then
    echo "== 4. announcing a restart in $MIN minute(s)"
    bash soap-cmd.sh "announce Server restart in $MIN minutes for an update. Back in a few minutes." >/dev/null 2>&1 || true
    sleep $(( MIN * 60 - 60 )) || true
    bash soap-cmd.sh "announce Server restart in 1 minute." >/dev/null 2>&1 || true
    sleep 60
    bash soap-cmd.sh "saveall" >/dev/null 2>&1 || true
  fi
  started() { docker inspect -f '{{.State.StartedAt}}' ov-ac-worldserver; }
  before=$(started)
  if [ "$envchange" = 1 ]; then
    echo "== recreating the world server for the new settings (2-10 minutes)"
    docker compose up -d --no-deps ac-worldserver
  fi
  # "compose up" leaves a running container alone when its settings are the same (scripts only): restart it
  if [ "$(started)" = "$before" ]; then
    echo "== restarting the world server to load the scripts (2-10 minutes)"
    docker restart ov-ac-worldserver >/dev/null
  fi
  sleep 3
  [ "$(started)" != "$before" ] || die "the world server did not restart. Backups: $BK"
  ok=0
  for i in $(seq 1 120); do
    if docker logs --since "$(started)" ov-ac-worldserver 2>&1 | grep -F 'ready...' >/dev/null; then ok=1; break; fi
    if (( i % 6 == 0 )); then echo "  still starting ($((i * 10 / 60)) min)..."; fi
    sleep 10
  done
  [ "$ok" = 1 ] || die "the world server did not report ready in 20 min: docker logs --tail 80 ov-ac-worldserver. Backups: $BK"
  echo "  world server ready"
  mark_loaded
fi
sleep 2
if docker logs --since 60s ov-ac-worldserver 2>&1 | grep -iE 'lua.*(error|failed)|ALE.*error' | tail -5 | grep . ; then
  echo "  (the lines above are Lua errors: check them)"
fi
echo "  backups: $BK"
echo "SERVERPASS OK"
