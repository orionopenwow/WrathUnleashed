#!/usr/bin/env bash
# WrathUnleashed: read-only report on character creation. "Diagnose character create.bat" pipes this file to
# `bash -s` over one ssh login; it changes nothing and prints no password.
cd /srv/wrath 2>/dev/null || { echo "/srv/wrath not found"; exit 1; }
q() { docker exec -i ov-ac-database sh -c 'MYSQL_PWD="$MYSQL_ROOT_PASSWORD" exec mysql -uroot --table' <<<"$1" 2>&1; }
h() { printf '\n===== %s\n' "$*"; }

h "Containers"
docker ps --format '{{.Names}}  {{.Image}}  {{.Status}}' | grep -E 'ov-ac-' || echo "no ov-ac-* containers running"

h "World server log: character-create lines (newest 200 matches of the current run's log)"
since=$(docker inspect -f '{{.State.StartedAt}}' ov-ac-worldserver 2>/dev/null)
{ docker logs --since "${since:-24h}" ov-ac-worldserver 2>&1
  tail -n 20000 logs/world/Server.log logs/world/DBErrors.log 2>/dev/null; } \
 | grep -aiE 'Create Character|invalid race/class|race/class pair|tried to Create|playercreateinfo|CharStartOutfit|charstartoutfit|skillraceclassinfo|Player Create|heroic|CHAR_CREATE|hacking' \
 | tail -n 200

h "playercreateinfo (want 83 pairs; 62 = only the stock 3.3.5a pairs, the create error)"
q "USE acore_world;
SELECT COUNT(*) AS pairs, SUM(class = 6) AS death_knights, SUM(map = 571) AS in_northrend, SUM(map = 609) AS in_acherus FROM playercreateinfo;
SELECT GROUP_CONCAT(CONCAT(r.race, '/', r.class) ORDER BY r.race, r.class SEPARATOR ' ') AS retail_pairs_without_a_row FROM (
 SELECT 1 race,3 class UNION SELECT 2,5 UNION SELECT 2,8 UNION SELECT 3,7 UNION SELECT 3,8 UNION SELECT 3,9 UNION SELECT 4,8 UNION SELECT 4,9
 UNION SELECT 5,3 UNION SELECT 6,2 UNION SELECT 6,4 UNION SELECT 6,5 UNION SELECT 6,8 UNION SELECT 6,9 UNION SELECT 7,3 UNION SELECT 7,5
 UNION SELECT 8,9 UNION SELECT 8,11 UNION SELECT 10,1 UNION SELECT 11,4 UNION SELECT 11,9) r
 WHERE NOT EXISTS (SELECT 1 FROM playercreateinfo p WHERE p.race = r.race AND p.class = r.class);
SELECT map, zone, COUNT(*) AS pairs FROM playercreateinfo GROUP BY map, zone ORDER BY map, zone;
SELECT COUNT(*) AS outfit_rows_in_db, SUM(ID BETWEEN 9001 AND 9100) AS charfix_outfits FROM charstartoutfit_dbc;
SELECT COUNT(*) AS playercreateinfo_item_rows FROM playercreateinfo_item;
SELECT COUNT(*) AS charfix_skill_rows FROM playercreateinfo_skills WHERE comment LIKE 'charfix %';"

h "mod-arac"
q "USE acore_world; SELECT name, state, timestamp FROM updates WHERE name LIKE '%arac%';" | sed 's/^/  /'
echo "  (no row above = its arac.sql never ran: mod-arac has no src/ folder, so the core's db-import skips it)"
img=$(docker inspect -f '{{.Config.Image}}' ov-ac-worldserver 2>/dev/null); dbimg=${img%-worldserver:*}-db-import:${img##*:}
if docker image inspect "$dbimg" >/dev/null 2>&1; then
  echo "  modules in $dbimg: $(docker run --rm --entrypoint sh "$dbimg" -c 'ls /azerothcore/modules 2>/dev/null | tr "\n" " "')"
fi
echo "  server dbc files vs mod-arac 3f605e0's patched ones:"
for f in CharBaseInfo:ff304f374e0371aa08fe0513c623037b CharStartOutfit:d4f99953b109426def48cfbe408aebf0 SkillRaceClassInfo:4d5a53b583843eda8815db4e24d07a60; do
  n=${f%%:*}; want=${f##*:}; p=client-data/dbc/$n.dbc
  if [ -f "$p" ]; then have=$(md5sum "$p" | cut -c1-32); [ "$have" = "$want" ] && s="mod-arac's" || s="NOT mod-arac's (stock?)"; else s="missing"; fi
  echo "    $n.dbc: $s"
done

h "Settings"
echo "  OV_PROFILE (.env): $(grep -E '^OV_PROFILE=' .env 2>/dev/null | cut -d= -f2)"
echo "  running world server environment:"
docker exec ov-ac-worldserver env 2>/dev/null | grep -E '^(AC_(CHARACTER_CREATING|HEROIC_CHARACTERS_PER_REALM|START_HEROIC_PLAYER_LEVEL|START_PLAYER_LEVEL|INDIVIDUAL_PROGRESSION_ENABLE|PLAYER_START_CUSTOM_SPELLS|CHARACTERS_PER_REALM|EXPANSION|ALLOW_TWO_SIDE_ACCOUNTS|GAME_TYPE)[A-Z_]*|OV_MAIN|OV_BRAWL)=' | sort | sed 's/^/    /'
echo "  worldserver.conf in the image (used where no AC_ variable is set):"
docker exec ov-ac-worldserver sh -c 'f=/azerothcore/env/dist/etc/worldserver.conf; [ -f $f ] || f=$f.dist; grep -E "^(CharacterCreating\.|HeroicCharactersPerRealm|StartHeroicPlayerLevel|Expansion|CharactersPerRealm|AllowTwoSide\.Accounts) *=" $f' 2>/dev/null | sed 's/^/    /'
echo "  mod-individual-progression (refuses Death Knights when enabled):"
docker exec ov-ac-worldserver sh -c 'for f in /azerothcore/env/dist/etc/modules/individualProgression.conf /azerothcore/env/dist/etc/modules/individualProgression.conf.dist; do [ -f $f ] && { grep -E "^IndividualProgression\.(Enable|DeathKnightUnlockProgression|TbcRacesUnlockProgression) *=" $f; break; }; done' 2>/dev/null | sed 's/^/    /'
echo "  Lua: $(ls custom/lua_scripts 2>/dev/null | tr '\n' ' ')"
[ -f custom/lua_scripts/ov_kits.lua ] || echo "  NOTE: custom/lua_scripts/ov_kits.lua is missing (ov_main.lua's boost kits)"

h "Accounts and characters"
q "SELECT expansion, COUNT(*) AS accounts FROM acore_auth.account GROUP BY expansion;
SELECT COUNT(*) AS characters, SUM(class = 6) AS death_knights FROM acore_characters.characters
 WHERE account NOT IN (SELECT id FROM acore_auth.account WHERE username LIKE 'RNDBOT%');"
echo
echo "Diagnose done."
