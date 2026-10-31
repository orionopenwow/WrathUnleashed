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
#      Companions (ov_companions.lua, dungeons and 10-player raids): AC_PLAYERBOTS_MAX_ADDED_BOTS = 9 (the bot
#      module's per-player cap: you + 9 = a 10-player raid), OV_COMPANIONS_PER_PLAYER_RAID = 9,
#      OV_COMPANIONS_GROUP_MAX = 10, OV_COMPANIONS_REALM_MAX = 60, OV_COMPANIONS_RAID25 = 0 (25-player off).
#      Bots always pass on loot: AC_PLAYERBOTS_LOOT_NEED_ROLL_LEVEL = 0 and _LOOT_GREED_ROLL_LEVEL = 0 turn
#      need and greed votes into pass, _LOOT_ROLL_DISENCHANT = 0, _LOOT_ROLL_RECIPE = 0, _FREE_METHOD_LOOT = 0
#      (no looting under free-for-all). AC_PLAYERBOTS_ALLOW_GUILD_BOTS = 0: own-account alts only.
#      Chat anti-spam (docs/SECURITY-HARDENING.md): ChatFlood 6 messages / 1 s -> 30 s mute, ChatLevelReq Say 1,
#      Channel 5, Whisper 5, ChatStrictLinkChecking Severity 1 / Kick 0. A first run with them restarts the realm.
#   3b. Bot talent specs: mod-playerbots' premade specs (realm/playerbots-specs.env, 256 AC_PLAYERBOTS_PREMADE_SPEC_*
#      lines) go into the profile, so ".recruit" can give each bot its role's talents.
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
for kv in AC_DUNGEON_ACCESS_REQUIREMENTS_LFGLEVEL_DBCOVERRIDE=1 AC_ALLOW_TWO_SIDE_INTERACTION_GROUP=1 OV_AUTOLEARN=1 \
    AC_PLAYERBOTS_MAX_ADDED_BOTS=9 OV_COMPANIONS_PER_PLAYER_RAID=9 OV_COMPANIONS_GROUP_MAX=10 \
    OV_COMPANIONS_REALM_MAX=60 OV_COMPANIONS_RAID25=0 \
    AC_PLAYERBOTS_LOOT_NEED_ROLL_LEVEL=0 AC_PLAYERBOTS_LOOT_GREED_ROLL_LEVEL=0 AC_PLAYERBOTS_LOOT_ROLL_DISENCHANT=0 \
    AC_PLAYERBOTS_LOOT_ROLL_RECIPE=0 AC_PLAYERBOTS_FREE_METHOD_LOOT=0 AC_PLAYERBOTS_ALLOW_GUILD_BOTS=0 \
    AC_CHAT_FLOOD_MESSAGE_COUNT=6 AC_CHAT_FLOOD_MESSAGE_DELAY=1 AC_CHAT_FLOOD_MUTE_TIME=30 \
    AC_CHAT_LEVEL_REQ_SAY=1 AC_CHAT_LEVEL_REQ_CHANNEL=5 AC_CHAT_LEVEL_REQ_WHISPER=5 \
    AC_CHAT_STRICT_LINK_CHECKING_SEVERITY=1 AC_CHAT_STRICT_LINK_CHECKING_KICK=0; do
  k=${kv%%=*}; v=${kv#*=}
  if grep -qE "^$k=" "$PF"; then sed -i "s#^$k=.*#$k=$v#" "$PF"; else printf '%s=%s\n' "$k" "$v" >> "$PF"; fi
  [ "$(docker exec ov-ac-worldserver printenv "$k" 2>/dev/null || true)" = "$v" ] || need=1
  echo "  $k=$v"
done

# 3b. mod-playerbots' premade talent specs. The realm runs on env settings only and never installs the
# module's playerbots.conf, so every bot answered "talents spec list" with "Total 0 specs found" and Companions
# couldn't give bots their role's talents (seen live 2026-10-26). These lines are realm/playerbots-specs.env,
# made from the pinned module's playerbots.conf.dist by tools/playerbots-specs/make_specs_env.py; the test
# stream/tests/test_serverpass_specs.py keeps this copy equal to that file. Replaces any older copy.
echo "== 3b. bot talent specs"
SPECS_TMP=$(mktemp)
cat > "$SPECS_TMP" <<'OV_SPECS_EOF'
AC_PLAYERBOTS_PREMADE_SPEC_NAME_1__0=arms pve
AC_PLAYERBOTS_PREMADE_SPEC_GLYPH_1__0=43418,43395,43423,43399,43397,43421
AC_PLAYERBOTS_PREMADE_SPEC_LINK_1__0__60=3022032023335100002012211231241
AC_PLAYERBOTS_PREMADE_SPEC_LINK_1__0__80=3022032023335100102012213231251-305-2033
AC_PLAYERBOTS_PREMADE_SPEC_NAME_1__1=fury pve
AC_PLAYERBOTS_PREMADE_SPEC_GLYPH_1__1=43418,43395,43414,43396,49084,43432
AC_PLAYERBOTS_PREMADE_SPEC_LINK_1__1__60=-305053000500310053120501351
AC_PLAYERBOTS_PREMADE_SPEC_LINK_1__1__80=32002300233-305053000500310153120511351
AC_PLAYERBOTS_PREMADE_SPEC_NAME_1__2=prot pve
AC_PLAYERBOTS_PREMADE_SPEC_GLYPH_1__2=43429,43397,43425,43399,49084,45797
AC_PLAYERBOTS_PREMADE_SPEC_LINK_1__2__60=--053351225000210521030113321
AC_PLAYERBOTS_PREMADE_SPEC_LINK_1__2__80=3500030023-301-053351225000210521030113321
AC_PLAYERBOTS_PREMADE_SPEC_NAME_1__3=arms pvp
AC_PLAYERBOTS_PREMADE_SPEC_GLYPH_1__3=43417,43397,43423,43396,49084,43421
AC_PLAYERBOTS_PREMADE_SPEC_LINK_1__3__60=0320232023331100032212012221251
AC_PLAYERBOTS_PREMADE_SPEC_LINK_1__3__80=0320332023335100232212013231251-3250001
AC_PLAYERBOTS_PREMADE_SPEC_NAME_1__4=fury pvp
AC_PLAYERBOTS_PREMADE_SPEC_GLYPH_1__4=43432,43397,43417,43395,43396,43418
AC_PLAYERBOTS_PREMADE_SPEC_LINK_1__4__60=-325000131500212250120511351
AC_PLAYERBOTS_PREMADE_SPEC_LINK_1__4__80=03220300233-325000131500212250122511351
AC_PLAYERBOTS_PREMADE_SPEC_NAME_1__5=prot pvp
AC_PLAYERBOTS_PREMADE_SPEC_GLYPH_1__5=43425,43397,43415,43396,49084,45792
AC_PLAYERBOTS_PREMADE_SPEC_LINK_1__5__60=--250031220223012520332113321
AC_PLAYERBOTS_PREMADE_SPEC_LINK_1__5__80=0502300123-3-250031220223012521332113321
AC_PLAYERBOTS_PREMADE_SPEC_NAME_2__0=holy pve
AC_PLAYERBOTS_PREMADE_SPEC_GLYPH_2__0=41106,43367,45741,43368,43365,41109
AC_PLAYERBOTS_PREMADE_SPEC_LINK_2__0__60=50350151020013053100515221
AC_PLAYERBOTS_PREMADE_SPEC_LINK_2__0__80=50350152100013053100515221-50320104203
AC_PLAYERBOTS_PREMADE_SPEC_NAME_2__1=prot pve
AC_PLAYERBOTS_PREMADE_SPEC_GLYPH_2__1=41100,43367,43869,43368,43369,45745
AC_PLAYERBOTS_PREMADE_SPEC_LINK_2__1__60=-05005135203102311333112321
AC_PLAYERBOTS_PREMADE_SPEC_LINK_2__1__80=-05005135203102311333312321-502302012003
AC_PLAYERBOTS_PREMADE_SPEC_NAME_2__2=ret pve
AC_PLAYERBOTS_PREMADE_SPEC_GLYPH_2__2=41092,43367,41099,43368,43340,43869
AC_PLAYERBOTS_PREMADE_SPEC_LINK_2__2__60=--05230051203331302133231131
AC_PLAYERBOTS_PREMADE_SPEC_LINK_2__2__65=-05-05230051203331302133231131
AC_PLAYERBOTS_PREMADE_SPEC_LINK_2__2__80=050501-05-05232051203331302133231331
AC_PLAYERBOTS_PREMADE_SPEC_NAME_2__3=holy pvp
AC_PLAYERBOTS_PREMADE_SPEC_GLYPH_2__3=41110,43367,45746,43369,43365,45747
AC_PLAYERBOTS_PREMADE_SPEC_LINK_2__3__60=50332150300013050133215221
AC_PLAYERBOTS_PREMADE_SPEC_LINK_2__3__80=50332150300013050133315221-5032013122
AC_PLAYERBOTS_PREMADE_SPEC_NAME_2__4=prot pvp
AC_PLAYERBOTS_PREMADE_SPEC_GLYPH_2__4=41092,43367,41101,43369,43365,45745
AC_PLAYERBOTS_PREMADE_SPEC_LINK_2__4__60=-15320130223122311323311321
AC_PLAYERBOTS_PREMADE_SPEC_LINK_2__4__80=-15320130223122321333312321-052300502
AC_PLAYERBOTS_PREMADE_SPEC_NAME_2__5=ret pvp
AC_PLAYERBOTS_PREMADE_SPEC_GLYPH_2__5=41095,43367,41102,43369,43365,45747
AC_PLAYERBOTS_PREMADE_SPEC_LINK_2__5__60=--05230250203331222133201321
AC_PLAYERBOTS_PREMADE_SPEC_LINK_2__5__80=-1532013022-05230250203331322133201321
AC_PLAYERBOTS_PREMADE_SPEC_NAME_3__0=bm pve
AC_PLAYERBOTS_PREMADE_SPEC_GLYPH_3__0=42912,43350,42902,43351,43338,42914
AC_PLAYERBOTS_PREMADE_SPEC_LINK_3__0__40=512002015051122301
AC_PLAYERBOTS_PREMADE_SPEC_LINK_3__0__60=51200201505112233110531151
AC_PLAYERBOTS_PREMADE_SPEC_LINK_3__0__80=51200201505112233111531351-0323031-5
AC_PLAYERBOTS_PREMADE_SPEC_NAME_3__1=mm pve
AC_PLAYERBOTS_PREMADE_SPEC_GLYPH_3__1=42912,43350,45625,43351,43338,42914
AC_PLAYERBOTS_PREMADE_SPEC_LINK_3__1__60=-035305101030013233115031151
AC_PLAYERBOTS_PREMADE_SPEC_LINK_3__1__80=502-035305101230013233135031351-5000002
AC_PLAYERBOTS_PREMADE_SPEC_NAME_3__2=surv pve
AC_PLAYERBOTS_PREMADE_SPEC_GLYPH_3__2=45733,43350,45731,43351,43338,45732
AC_PLAYERBOTS_PREMADE_SPEC_LINK_3__2__60=--5000032500033330502135201311
AC_PLAYERBOTS_PREMADE_SPEC_LINK_3__2__80=-005305101-5000032500033330532135301321
AC_PLAYERBOTS_PREMADE_SPEC_NAME_3__3=bm pvp
AC_PLAYERBOTS_PREMADE_SPEC_GLYPH_3__3=42897,42900,42902,43356,43338,42900
AC_PLAYERBOTS_PREMADE_SPEC_LINK_3__3__60=05203201505012233100531151
AC_PLAYERBOTS_PREMADE_SPEC_LINK_3__3__80=05203201505012233100531351-005305101-03
AC_PLAYERBOTS_PREMADE_SPEC_NAME_3__4=mm pvp
AC_PLAYERBOTS_PREMADE_SPEC_GLYPH_3__4=42912,43351,42897,43338,43356,42904
AC_PLAYERBOTS_PREMADE_SPEC_LINK_3__4__60=-034305101030213231135031051
AC_PLAYERBOTS_PREMADE_SPEC_LINK_3__4__80=-035305101030213233135031051-53013020102
AC_PLAYERBOTS_PREMADE_SPEC_NAME_3__5=surv pvp
AC_PLAYERBOTS_PREMADE_SPEC_GLYPH_3__5=42912,43350,42904,43356,43338,45731
AC_PLAYERBOTS_PREMADE_SPEC_LINK_3__5__60=--2300302410233030533135001031
AC_PLAYERBOTS_PREMADE_SPEC_LINK_3__5__80=-005305201-2300302510233330533135001031
AC_PLAYERBOTS_PREMADE_SPEC_NAME_4__0=as pve
AC_PLAYERBOTS_PREMADE_SPEC_GLYPH_4__0=45768,43379,45761,43380,43378,45766
AC_PLAYERBOTS_PREMADE_SPEC_LINK_4__0__60=005303104352100520103331051
AC_PLAYERBOTS_PREMADE_SPEC_LINK_4__0__80=005303005352100520103331051-005005003-502
AC_PLAYERBOTS_PREMADE_SPEC_NAME_4__1=combat pve
AC_PLAYERBOTS_PREMADE_SPEC_GLYPH_4__1=42962,43379,45762,43380,43378,42969
AC_PLAYERBOTS_PREMADE_SPEC_LINK_4__1__60=-0252051000035015223100501251
AC_PLAYERBOTS_PREMADE_SPEC_LINK_4__1__80=00532000523-0252051000035015223100501251
AC_PLAYERBOTS_PREMADE_SPEC_NAME_4__2=subtlety pve
AC_PLAYERBOTS_PREMADE_SPEC_GLYPH_4__2=42967,43379,45764,43380,43378,45767
AC_PLAYERBOTS_PREMADE_SPEC_LINK_4__2__60=--5022012030321121350115031151
AC_PLAYERBOTS_PREMADE_SPEC_LINK_4__2__80=30532010114--5022012030321121350115031151
AC_PLAYERBOTS_PREMADE_SPEC_NAME_4__3=as pvp
AC_PLAYERBOTS_PREMADE_SPEC_GLYPH_4__3=42974,43380,45768,43379,43376,42971
AC_PLAYERBOTS_PREMADE_SPEC_LINK_4__3__60=005303103342102522103031--50002
AC_PLAYERBOTS_PREMADE_SPEC_LINK_4__3__80=005303103342102522103031-004-532023203000012
AC_PLAYERBOTS_PREMADE_SPEC_NAME_4__4=combat pvp
AC_PLAYERBOTS_PREMADE_SPEC_GLYPH_4__4=42972,43380,45762,43376,43378,42971
AC_PLAYERBOTS_PREMADE_SPEC_LINK_4__4__60=-3250002050225010223102321251
AC_PLAYERBOTS_PREMADE_SPEC_LINK_4__4__80=305120105-3250002050235010223102521251
AC_PLAYERBOTS_PREMADE_SPEC_NAME_4__5=subtlety pvp
AC_PLAYERBOTS_PREMADE_SPEC_GLYPH_4__5=42968,43376,45764,43380,43379,42971
AC_PLAYERBOTS_PREMADE_SPEC_LINK_4__5__60=--5120212030320121330133221251
AC_PLAYERBOTS_PREMADE_SPEC_LINK_4__5__80=3023031-3-5120212030320121350135231251
AC_PLAYERBOTS_PREMADE_SPEC_NAME_5__0=disc pve
AC_PLAYERBOTS_PREMADE_SPEC_GLYPH_5__0=42408,43371,42400,43374,43342,45756
AC_PLAYERBOTS_PREMADE_SPEC_LINK_5__0__60=0503203130300512301323131051
AC_PLAYERBOTS_PREMADE_SPEC_LINK_5__0__80=0503203130300512331323231251-03520103
AC_PLAYERBOTS_PREMADE_SPEC_NAME_5__1=holy pve
AC_PLAYERBOTS_PREMADE_SPEC_GLYPH_5__1=42408,43371,42400,43374,43342,42396
AC_PLAYERBOTS_PREMADE_SPEC_LINK_5__1__60=-035050031301152530000331331
AC_PLAYERBOTS_PREMADE_SPEC_LINK_5__1__80=05032031-235050032302152530000331351
AC_PLAYERBOTS_PREMADE_SPEC_NAME_5__2=shadow pve
AC_PLAYERBOTS_PREMADE_SPEC_GLYPH_5__2=45753,43371,42407,43374,43370,42415
AC_PLAYERBOTS_PREMADE_SPEC_LINK_5__2__60=--325003041203010323150301351
AC_PLAYERBOTS_PREMADE_SPEC_LINK_5__2__80=0503203--325023051223010323152301351
AC_PLAYERBOTS_PREMADE_SPEC_NAME_5__3=disc pvp
AC_PLAYERBOTS_PREMADE_SPEC_GLYPH_5__3=42408,43371,45760,43370,43374,45756
AC_PLAYERBOTS_PREMADE_SPEC_LINK_5__3__60=5003203130320512201323031051
AC_PLAYERBOTS_PREMADE_SPEC_LINK_5__3__80=5003203130322512331013231151-23050113
AC_PLAYERBOTS_PREMADE_SPEC_NAME_5__4=holy pvp
AC_PLAYERBOTS_PREMADE_SPEC_GLYPH_5__4=42411,43371,42408,43370,43374,45755
AC_PLAYERBOTS_PREMADE_SPEC_LINK_5__4__60=-235501031000152430320031151
AC_PLAYERBOTS_PREMADE_SPEC_LINK_5__4__80=500320313-235501031000152530320031351
AC_PLAYERBOTS_PREMADE_SPEC_NAME_5__5=shadow pvp
AC_PLAYERBOTS_PREMADE_SPEC_GLYPH_5__5=42407,43371,45753,43370,43374,42408
AC_PLAYERBOTS_PREMADE_SPEC_LINK_5__5__60=--005323241223112003102311351
AC_PLAYERBOTS_PREMADE_SPEC_LINK_5__5__80=50332031003--005323241223112003102311351
AC_PLAYERBOTS_PREMADE_SPEC_NAME_6__0=blood pve
AC_PLAYERBOTS_PREMADE_SPEC_GLYPH_6__0=45805,43673,43538,43544,43672,43542
AC_PLAYERBOTS_PREMADE_SPEC_LINK_6__0__60=035502150300331320102013111-005
AC_PLAYERBOTS_PREMADE_SPEC_LINK_6__0__80=0055021533303310201020131-305020510002-00522
AC_PLAYERBOTS_PREMADE_SPEC_NAME_6__1=frost pve
AC_PLAYERBOTS_PREMADE_SPEC_GLYPH_6__1=45805,43673,43547,43544,43672,43543
AC_PLAYERBOTS_PREMADE_SPEC_LINK_6__1__60=-32003350332203012300023101351
AC_PLAYERBOTS_PREMADE_SPEC_LINK_6__1__80=-32002350352203012300033101351-230200305003
AC_PLAYERBOTS_PREMADE_SPEC_NAME_6__2=unholy pve
AC_PLAYERBOTS_PREMADE_SPEC_GLYPH_6__2=43542,43673,43546,43535,43672,43549
AC_PLAYERBOTS_PREMADE_SPEC_LINK_6__2__60=--2301303050032151000150013131151
AC_PLAYERBOTS_PREMADE_SPEC_LINK_6__2__80=23050202--2302303350032152000150003133151
AC_PLAYERBOTS_PREMADE_SPEC_NAME_6__3=double aura blood pve
AC_PLAYERBOTS_PREMADE_SPEC_GLYPH_6__3=45805,43673,43538,43544,43672,43554
AC_PLAYERBOTS_PREMADE_SPEC_LINK_6__3__60=005512153330030320102013-305
AC_PLAYERBOTS_PREMADE_SPEC_LINK_6__3__80=005512153330030320102013-3050505002023001-002
AC_PLAYERBOTS_PREMADE_SPEC_NAME_6__4=blood pvp
AC_PLAYERBOTS_PREMADE_SPEC_GLYPH_6__4=43534,43535,45799,43673,43672,45805
AC_PLAYERBOTS_PREMADE_SPEC_LINK_6__4__60=2305021503003313201222101351
AC_PLAYERBOTS_PREMADE_SPEC_LINK_6__4__80=2305021503003313201222101351--032232300023
AC_PLAYERBOTS_PREMADE_SPEC_NAME_6__5=frost pvp
AC_PLAYERBOTS_PREMADE_SPEC_GLYPH_6__5=43543,43539,45800,43673,43672,45806
AC_PLAYERBOTS_PREMADE_SPEC_LINK_6__5__60=-32015351022203012001233101251
AC_PLAYERBOTS_PREMADE_SPEC_LINK_6__5__80=0055-32015351052203012001233131351-03
AC_PLAYERBOTS_PREMADE_SPEC_NAME_6__6=unholy pvp
AC_PLAYERBOTS_PREMADE_SPEC_GLYPH_6__6=45804,43539,43549,43673,43672,45805
AC_PLAYERBOTS_PREMADE_SPEC_LINK_6__6__60=--2301323301002152230101203103151
AC_PLAYERBOTS_PREMADE_SPEC_LINK_6__6__80=-320050410002-2301323301002152230101203133151
AC_PLAYERBOTS_PREMADE_SPEC_NAME_7__0=ele pve
AC_PLAYERBOTS_PREMADE_SPEC_GLYPH_7__0=41536,43385,41532,43386,44923,45776
AC_PLAYERBOTS_PREMADE_SPEC_LINK_7__0__60=4530001520213351102301351
AC_PLAYERBOTS_PREMADE_SPEC_LINK_7__0__80=4530001523213351302301351-00525003
AC_PLAYERBOTS_PREMADE_SPEC_NAME_7__1=enh pve
AC_PLAYERBOTS_PREMADE_SPEC_GLYPH_7__1=41542,43385,41539,43386,43725,45771
AC_PLAYERBOTS_PREMADE_SPEC_LINK_7__1__60=-30305003105021333031121131051
AC_PLAYERBOTS_PREMADE_SPEC_LINK_7__1__80=053030152-30305003105021333031131131051
AC_PLAYERBOTS_PREMADE_SPEC_NAME_7__2=resto pve
AC_PLAYERBOTS_PREMADE_SPEC_GLYPH_7__2=41527,43385,41517,43386,43725,45775
AC_PLAYERBOTS_PREMADE_SPEC_LINK_7__2__60=--50005301235310501102321251
AC_PLAYERBOTS_PREMADE_SPEC_LINK_7__2__80=-00502033-50005331335310501122331251
AC_PLAYERBOTS_PREMADE_SPEC_NAME_7__3=ele pvp
AC_PLAYERBOTS_PREMADE_SPEC_GLYPH_7__3=45778,43388,45770,43725,43386,41524
AC_PLAYERBOTS_PREMADE_SPEC_LINK_7__3__60=0533001503213051322301341
AC_PLAYERBOTS_PREMADE_SPEC_LINK_7__3__80=0533051503213051322331351-023212001
AC_PLAYERBOTS_PREMADE_SPEC_NAME_7__4=enh pvp
AC_PLAYERBOTS_PREMADE_SPEC_GLYPH_7__4=45778,43388,41526,43725,43344,45771
AC_PLAYERBOTS_PREMADE_SPEC_LINK_7__4__60=-02305203105001333201131131151
AC_PLAYERBOTS_PREMADE_SPEC_LINK_7__4__80=0503351-02305203105001333211131231251
AC_PLAYERBOTS_PREMADE_SPEC_NAME_7__5=resto pvp
AC_PLAYERBOTS_PREMADE_SPEC_GLYPH_7__5=45778,43388,45775,43725,43344,41535
AC_PLAYERBOTS_PREMADE_SPEC_LINK_7__5__60=--05032331331013501120321251
AC_PLAYERBOTS_PREMADE_SPEC_LINK_7__5__80=-023222301004-05032331331013501120331251
AC_PLAYERBOTS_PREMADE_SPEC_NAME_8__0=arcane pve
AC_PLAYERBOTS_PREMADE_SPEC_GLYPH_8__0=42735,43339,44955,43364,43361,42751
AC_PLAYERBOTS_PREMADE_SPEC_LINK_8__0__60=230005231100330150323102500321
AC_PLAYERBOTS_PREMADE_SPEC_LINK_8__0__80=230005231100330150323102505321-03-203303001
AC_PLAYERBOTS_PREMADE_SPEC_NAME_8__1=fire pve
AC_PLAYERBOTS_PREMADE_SPEC_GLYPH_8__1=42739,43339,45737,43364,44920,42751
AC_PLAYERBOTS_PREMADE_SPEC_LINK_8__1__60=-0055030011302231053120321341
AC_PLAYERBOTS_PREMADE_SPEC_LINK_8__1__80=23000503110003-0055032012303330053120300351
AC_PLAYERBOTS_PREMADE_SPEC_NAME_8__2=frost pve
AC_PLAYERBOTS_PREMADE_SPEC_GLYPH_8__2=42742,43339,50045,43364,43361,42751
AC_PLAYERBOTS_PREMADE_SPEC_LINK_8__2__60=--0533030313203100030152231151
AC_PLAYERBOTS_PREMADE_SPEC_LINK_8__2__80=23002303110003--0533030313203100030152231351
AC_PLAYERBOTS_PREMADE_SPEC_NAME_8__3=frostfire pve
AC_PLAYERBOTS_PREMADE_SPEC_GLYPH_8__3=44684,44920,42751,43339,43364,45737
AC_PLAYERBOTS_PREMADE_SPEC_LINK_8__3__60=-2305032012303331053120300051
AC_PLAYERBOTS_PREMADE_SPEC_LINK_8__3__80=-2305032012303331053120321351-023302031
AC_PLAYERBOTS_PREMADE_SPEC_NAME_8__4=arcane pvp
AC_PLAYERBOTS_PREMADE_SPEC_GLYPH_8__4=42735,43364,42738,43360,43357,42752
AC_PLAYERBOTS_PREMADE_SPEC_LINK_8__4__60=205323200122032103303102015221
AC_PLAYERBOTS_PREMADE_SPEC_LINK_8__4__80=205323200122032103303102015321-23002-303020301
AC_PLAYERBOTS_PREMADE_SPEC_NAME_8__5=fire pvp
AC_PLAYERBOTS_PREMADE_SPEC_GLYPH_8__5=42738,43364,42752,43360,43357,45737
AC_PLAYERBOTS_PREMADE_SPEC_LINK_8__5__60=-2305202312020031223122301351
AC_PLAYERBOTS_PREMADE_SPEC_LINK_8__5__80=230321030122-2305212312020031223122301351
AC_PLAYERBOTS_PREMADE_SPEC_NAME_8__6=frost pvp
AC_PLAYERBOTS_PREMADE_SPEC_GLYPH_8__6=42738,43364,45740,43357,43360,42752
AC_PLAYERBOTS_PREMADE_SPEC_LINK_8__6__60=--3533203210203100232102231151
AC_PLAYERBOTS_PREMADE_SPEC_LINK_8__6__80=23032103010203--3533203210203100232102231151
AC_PLAYERBOTS_PREMADE_SPEC_NAME_9__0=affli pve
AC_PLAYERBOTS_PREMADE_SPEC_GLYPH_9__0=45785,43390,50077,43394,43393,45779
AC_PLAYERBOTS_PREMADE_SPEC_LINK_9__0__60=2350022001113510053500131151
AC_PLAYERBOTS_PREMADE_SPEC_LINK_9__0__70=2350022001113510053500131151--55
AC_PLAYERBOTS_PREMADE_SPEC_LINK_9__0__80=2350022001123510253500331151--55000005
AC_PLAYERBOTS_PREMADE_SPEC_NAME_9__1=demo pve
AC_PLAYERBOTS_PREMADE_SPEC_GLYPH_9__1=45785,43390,50077,43394,43393,42459
AC_PLAYERBOTS_PREMADE_SPEC_LINK_9__1__60=-003203301135112530135201051
AC_PLAYERBOTS_PREMADE_SPEC_LINK_9__1__70=-003203301135112530135201051-55
AC_PLAYERBOTS_PREMADE_SPEC_LINK_9__1__80=-003203301135112530135221351-55000005
AC_PLAYERBOTS_PREMADE_SPEC_NAME_9__2=destro pve
AC_PLAYERBOTS_PREMADE_SPEC_GLYPH_9__2=45785,43390,42454,43394,43393,42453
AC_PLAYERBOTS_PREMADE_SPEC_LINK_9__2__60=--05203215200231051305031151
AC_PLAYERBOTS_PREMADE_SPEC_LINK_9__2__80=23-0302-05203215220331051335231351
AC_PLAYERBOTS_PREMADE_SPEC_NAME_9__3=affli pvp
AC_PLAYERBOTS_PREMADE_SPEC_GLYPH_9__3=50077,43392,42455,43390,43389,45783
AC_PLAYERBOTS_PREMADE_SPEC_LINK_9__3__60=0350002231223011053502301151
AC_PLAYERBOTS_PREMADE_SPEC_LINK_9__3__80=2350002231223111053502301151-2032003011302
AC_PLAYERBOTS_PREMADE_SPEC_NAME_9__4=demo pvp
AC_PLAYERBOTS_PREMADE_SPEC_GLYPH_9__4=42459,43392,45780,43390,43389,45783
AC_PLAYERBOTS_PREMADE_SPEC_LINK_9__4__60=-003203301135202530135001251
AC_PLAYERBOTS_PREMADE_SPEC_LINK_9__4__80=-003203301135202530135011351-052300152
AC_PLAYERBOTS_PREMADE_SPEC_NAME_9__5=destro pvp
AC_PLAYERBOTS_PREMADE_SPEC_GLYPH_9__5=42471,43392,42454,43390,43389,45783
AC_PLAYERBOTS_PREMADE_SPEC_LINK_9__5__60=--05230015220331351005031051
AC_PLAYERBOTS_PREMADE_SPEC_LINK_9__5__80=-2032003311302-05230015220331351005031051
AC_PLAYERBOTS_PREMADE_SPEC_NAME_11__0=balance pve
AC_PLAYERBOTS_PREMADE_SPEC_GLYPH_11__0=40916,43331,40921,43335,44922,40919
AC_PLAYERBOTS_PREMADE_SPEC_LINK_11__0__60=5032003125031003213304301231
AC_PLAYERBOTS_PREMADE_SPEC_LINK_11__0__80=5032003125331303213305301231--205003012
AC_PLAYERBOTS_PREMADE_SPEC_NAME_11__1=bear pve
AC_PLAYERBOTS_PREMADE_SPEC_GLYPH_11__1=40897,43331,46372,43335,43332,40899
AC_PLAYERBOTS_PREMADE_SPEC_LINK_11__1__60=-503232132322010303120300013501
AC_PLAYERBOTS_PREMADE_SPEC_LINK_11__1__80=-503232132322010353120303013511-20350001
AC_PLAYERBOTS_PREMADE_SPEC_NAME_11__2=resto pve
AC_PLAYERBOTS_PREMADE_SPEC_GLYPH_11__2=40906,43331,45602,43335,43674,45603
AC_PLAYERBOTS_PREMADE_SPEC_LINK_11__2__60=--230033312031502331050313031
AC_PLAYERBOTS_PREMADE_SPEC_LINK_11__2__80=05320031--230033312031502431053313051
AC_PLAYERBOTS_PREMADE_SPEC_NAME_11__3=cat pve
AC_PLAYERBOTS_PREMADE_SPEC_GLYPH_11__3=40902,43331,40901,43674,43335,45604
AC_PLAYERBOTS_PREMADE_SPEC_LINK_11__3__60=-552202032322010053100030310501
AC_PLAYERBOTS_PREMADE_SPEC_LINK_11__3__80=-553202032322010053120030310511-203503012
AC_PLAYERBOTS_PREMADE_SPEC_NAME_11__4=balance pvp
AC_PLAYERBOTS_PREMADE_SPEC_GLYPH_11__4=40921,43331,45622,43674,43335,45623
AC_PLAYERBOTS_PREMADE_SPEC_LINK_11__4__60=5012203115331002213032311231
AC_PLAYERBOTS_PREMADE_SPEC_LINK_11__4__80=5022203125331003213035311231--230033012
AC_PLAYERBOTS_PREMADE_SPEC_NAME_11__5=cat pvp
AC_PLAYERBOTS_PREMADE_SPEC_GLYPH_11__5=40902,43331,45601,43674,43335,40901
AC_PLAYERBOTS_PREMADE_SPEC_LINK_11__5__60=-513202032322010053103030310501
AC_PLAYERBOTS_PREMADE_SPEC_LINK_11__5__80=-523202032322010053103030310511-205503012
AC_PLAYERBOTS_PREMADE_SPEC_NAME_11__6=resto pvp
AC_PLAYERBOTS_PREMADE_SPEC_GLYPH_11__6=40913,43331,40906,43335,43674,45623
AC_PLAYERBOTS_PREMADE_SPEC_LINK_11__6__60=--230033312031500511350013051
AC_PLAYERBOTS_PREMADE_SPEC_LINK_11__6__80=05320021--230033312031500531353013251
OV_SPECS_EOF
before_md5=$(md5sum < "$PF")
grep -v '^AC_PLAYERBOTS_PREMADE_SPEC_' "$PF" > "$PF.new" || true
cat "$SPECS_TMP" >> "$PF.new"
cat "$PF.new" > "$PF"; rm -f "$PF.new" "$SPECS_TMP"
[ "$(md5sum < "$PF")" = "$before_md5" ] || echo "  profile updated"
echo "  $(grep -c '^AC_PLAYERBOTS_PREMADE_SPEC_NAME_' "$PF") talent specs in the profile"
[ "$(docker exec ov-ac-worldserver printenv AC_PLAYERBOTS_PREMADE_SPEC_NAME_1__0 2>/dev/null || true)" = "arms pve" ] || need=1

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
