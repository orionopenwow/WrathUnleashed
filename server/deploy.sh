#!/usr/bin/env bash
# WrathUnleashed: replace the vanilla game servers on this box with the Wrath (3.3.5a) realm.
# Run as root from /srv/wrath after "Deploy Wrath to my server.bat" uploaded everything.
#   bash deploy.sh            back up vanilla, stop it, start Wrath: the main realm (level 1 or boost to 80), Warden off
#   WU_PROFILE=brawl bash deploy.sh   the same with Brawl (everyone instant 80)
# The vanilla databases are dumped to /root/vanilla-backups first; rollback.sh undoes the swap.
# The website (wenilla-realm caddy + realm portal + its MariaDB) is left running, and sign-in moves
# to it: players sign in at https://play.openvanilla.app/wrath with Google or their Hero Key and
# get their Wrath login there (portal/wrath_portal.py). No hand-made tester accounts.
set -euo pipefail
cd /srv/wrath
STAMP=$(date +%Y%m%d-%H%M%S)
log() { printf '\n== %s\n' "$*"; }
die() { printf '\nERROR: %s\n' "$*" >&2; exit 1; }
trap 'echo "!! deploy stopped at line $LINENO. Vanilla may be stopped: bash /srv/wrath/rollback.sh brings it back." >&2' ERR
# record a stop for rollback.sh, once
note() { touch stopped-vanilla.txt; grep -qxF "$1" stopped-vanilla.txt || echo "$1" >> stopped-vanilla.txt; }
REALM_HOST="${WU_REALM_HOST:-play.openvanilla.app}"
PROFILE="${WU_PROFILE:-main}"
[ -f "profiles/$PROFILE.env" ] || die "no profile profiles/$PROFILE.env (brawl, main, progression or casual)"

log "1/10 Back up the vanilla databases"
mkdir -p /root/vanilla-backups
docker ps --format '{{.Names}}' | grep -qx wenilla-realm-mariadb-1 \
  || die "the website database (wenilla-realm-mariadb-1) is not running, so it can't be backed up. Nothing was stopped."
for c in wenilla-realm-mariadb-1 owduels-mariadb-1; do
  docker ps --format '{{.Names}}' | grep -qx "$c" || { echo "  $c not running, skipped"; continue; }
  out="/root/vanilla-backups/$c-$STAMP.sql.gz"
  docker exec "$c" sh -c 'p="${MARIADB_ROOT_PASSWORD:-${MYSQL_ROOT_PASSWORD:-}}"; [ -n "$p" ] || exit 9; exec mariadb-dump -uroot -p"$p" --all-databases --single-transaction --routines' | gzip > "$out" \
    || die "backup of $c failed (no root password in its environment?). Nothing was stopped."
  [ "$(stat -c %s "$out")" -gt 2000 ] || die "backup $out is suspiciously small; nothing was stopped"
  echo "  $out  ($(du -h "$out" | cut -f1))"
done

log "2/10 Stop the vanilla game servers (website stays up)"
if [ -d /opt/wenilla-duels ]; then (cd /opt/wenilla-duels && docker compose stop) && note "duels"; fi
if [ -d /opt/wenilla-realm ]; then
  # keep them down across reboots too (a second "mangosd" would take half the new accounts)
  for id in $(cd /opt/wenilla-realm && docker compose ps -aq mangosd realmd); do
    pol=$(docker inspect -f '{{.HostConfig.RestartPolicy.Name}}' "$id")
    note "policy:$(docker inspect -f '{{.Name}}' "$id" | tr -d /):$pol"
    docker update --restart=no "$id" >/dev/null
  done
  (cd /opt/wenilla-realm && docker compose stop mangosd realmd) && note "realm:mangosd realmd"
fi
for u in $( { systemctl list-units --type=service --state=running --no-legend --plain; systemctl list-units --type=timer --state=active --no-legend --plain; } | awk '{print $1}' | grep -i herald || true); do
  systemctl stop "$u" && note "unit:$u" && echo "  stopped $u"
done
if ss -ltnH | grep -E '(:3724|:8085|127\.0\.0\.1:7878)[[:space:]]' >/dev/null && ! docker ps --format '{{.Names}}' | grep -qx ov-ac-worldserver; then
  ss -ltnp | grep -E ':3724|:8085|:7878' || true
  die "a game port (3724, 8085 or 7878) is still in use. Run: bash /srv/wrath/rollback.sh"
fi
free -h | sed -n 1,2p

log "3/10 Realm images"
# load the images only when the upload is newer than the last load (a re-run skips minutes of work)
if [ -f upload/wu-images.tar.gz ] && { [ ! -f upload/.images-loaded ] || [ upload/wu-images.tar.gz -nt upload/.images-loaded ]; }; then
  docker load -i upload/wu-images.tar.gz && touch upload/.images-loaded
fi
[ -d modules-sql/mod-playerbots/playerbots/base ] || die "modules-sql/mod-playerbots is missing (the bots' database files); run the deploy .bat again"
docker image inspect "${OV_IMAGE_CHECK:-ov/ac-wotlk-worldserver:custom}" >/dev/null 2>&1 || die "custom images not loaded"

log "4/10 Game data (extracted from the owner's own install; served to nobody)"
mkdir -p client-data
docker volume inspect ov-client-data >/dev/null 2>&1 || \
  docker volume create --driver local --opt type=none --opt o=bind --opt device=/srv/wrath/client-data ov-client-data >/dev/null
if [ -f upload/client-data.tgz ]; then tar -C client-data -xzf upload/client-data.tgz && rm -f upload/client-data.tgz; fi
[ -d client-data/dbc ] && [ -d client-data/maps ] || die "client-data has no dbc/maps"

log "5/10 Settings (.env)"
touch .env; chmod 600 .env
kv() { grep -q "^$1=" .env && sed -i "s#^$1=.*#$1=$2#" .env || echo "$1=$2" >> .env; }
grep -q '^DB_ROOT_PASSWORD=' .env || echo "DB_ROOT_PASSWORD=$(openssl rand -hex 24)" >> .env
kv COMPOSE_FILE docker-compose.prod.yml
kv OV_IMAGE ov/ac-wotlk
kv OV_TAG custom
kv OV_PROFILE "$PROFILE"
kv OV_PATHING 0
kv WU_WARDEN "${WU_WARDEN:-0}"
kv DB_BUFFER_POOL_SIZE 1G
kv WU_PLAYER_LIMIT 100
install -d -m 755 -o 1000 -g 1000 logs logs/auth logs/world
REALM_NAME="${WU_REALM_NAME:-WrathUnleashed}"
# The SOAP service account (made in step 6): signup.env for soap-cmd.sh, portal.env for the sign-in page.
if [ ! -f portal.env ]; then
  SP=$(openssl rand -hex 8 | tr 'a-f' 'A-F')
  umask 077
  printf 'SOAP_USER=WUSOAP\nSOAP_PASS=%s\nAC_SOAP_URL=http://ov-ac-worldserver:7878/\nPORTAL_URL=http://ovlive-realm:8090\nPUBLIC_HOST=%s\n' "$SP" "$REALM_HOST" > portal.env
  printf 'SOAP_USER=WUSOAP\nSOAP_PASS=%s\nSOAP_URL=http://127.0.0.1:7878/\n' "$SP" > signup.env
  umask 022
fi
grep -q '^REALM_NAME=' portal.env && sed -i "s#^REALM_NAME=.*#REALM_NAME=$REALM_NAME#" portal.env || echo "REALM_NAME=$REALM_NAME" >> portal.env
sed -i 's/\r$//' ./*.sh profiles/*.env modules.env 2>/dev/null || true

log "6/10 Start the realm (first start imports the databases and makes the bots: 5-20 min)"
wait_ready() {   # $1 = the time just before the (re)start; only logs after it count
  local i
  for i in $(seq 1 180); do
    # plain grep reads everything, so "docker logs" never dies on a closed pipe
    if docker logs --since "$1" ov-ac-worldserver 2>&1 | grep -F 'ready...' >/dev/null; then return 0; fi
    if (( i % 6 == 0 )); then echo "  still starting ($((i*10/60)) min)..."; fi
    sleep 10
  done
  return 1
}
docker compose up -d
# only log lines from the world server's current start count (also right when it was already up)
started() { docker inspect -f '{{.State.StartedAt}}' ov-ac-worldserver; }
wait_ready "$(started)" || die "the world server did not report ready in 30 min: docker logs --tail 80 ov-ac-worldserver"
( set -a; . ./portal.env; set +a; python3 -I portal/soap_account_sql.py ) \
  | docker exec -i ov-ac-database sh -c 'MYSQL_PWD="$MYSQL_ROOT_PASSWORD" exec mysql -uroot acore_auth' \
  || die "could not write the SOAP service account"
echo "  SOAP service account WUSOAP ready"

log "7/10 World changes for the $PROFILE profile"
# brawl: level 80 starts, free vendors, everything unlocked. main: puts back the stock rows Brawl changed (a no-op
# on a database that never ran Brawl), adds the boost menu's texts. Every profile keeps the modern race/class pairs.
case "$PROFILE" in
  brawl) WORLD_SQL="sql/brawl_world.sql sql/brawl_world_2.sql sql/modern_combos.sql" ;;
  main)  WORLD_SQL="sql/main_unbrawl.sql sql/main_world.sql sql/modern_combos.sql sql/charfix_world.sql" ;;
  *)     WORLD_SQL="sql/modern_combos.sql" ;;
esac
for f in $WORLD_SQL; do
  [ -f "$f" ] || { echo "  $f missing, skipped"; continue; }
  docker exec -i ov-ac-database sh -c 'MYSQL_PWD="$MYSQL_ROOT_PASSWORD" exec mysql -uroot acore_world' < "$f"
  echo "  applied $f"
done

log "8/10 Realm address and restart"
# The Leyline brand switch (realm/brand.sh): while it is on, the realm list keeps "Wrath Unleashed" (brand.sh NAME).
LIST_NAME="$REALM_NAME"
grep -qx 'LEYLINE_BRAND=1' portal.env 2>/dev/null && LIST_NAME="${LEYLINE_REALM_NAME:-Wrath Unleashed}"
bash set-realm-address.sh "$REALM_HOST" "$LIST_NAME"
docker compose restart ac-worldserver
sleep 2
wait_ready "$(started)" || die "the world server did not come back after the restart"
if command -v ufw >/dev/null && ufw status | grep -q "Status: active"; then
  ufw allow 3724/tcp >/dev/null; ufw allow 8085/tcp >/dev/null; echo "  ufw: 3724 and 8085 open"
fi

log "9/10 Sign-in: Google and Hero Keys on the website"
for i in 1 2 3 4 5 6; do bash soap-cmd.sh "server info" >/dev/null 2>&1 && break; sleep 10; done
bash soap-cmd.sh "server info" >/dev/null || die "SOAP does not accept WUSOAP (soap-cmd.sh \"server info\" to see why)"
# The website's login queue (on for vanilla) would hold back /api/play, which the Wrath page reads.
RE=/opt/wenilla-realm/.env
[ -f realm.env.before-wrath ] || cp -p "$RE" realm.env.before-wrath
if grep -q '^QUEUE_ENABLED=' "$RE"; then sed -i 's/^QUEUE_ENABLED=.*/QUEUE_ENABLED=0/' "$RE"; else echo QUEUE_ENABLED=0 >> "$RE"; fi
(cd /opt/wenilla-realm && docker compose up -d --no-deps realm)   # --no-deps: never starts mangosd again
docker network inspect wenilla-realm_default >/dev/null 2>&1 || die "network wenilla-realm_default not found (is the website stack running?)"
docker image inspect python:3.12-alpine >/dev/null 2>&1 || docker pull -q python:3.12-alpine >/dev/null
docker rm -f wu-portal >/dev/null 2>&1 || true
mkdir -p /srv/wrath/hosted && chmod 700 /srv/wrath/hosted   # /wrath/host's pending realms (stream/hostflow.py)
mkdir -p /srv/wrath/portal-data   # the Workshop's community links (stream/projects.py): the only writable mount
# On the website's network as "wu-portal" (Caddy) and "mangosd" (the realm service's SOAP, now a
# bridge to AzerothCore while the vanilla mangosd is stopped); on ov-wotlk_edge to reach the worldserver.
docker run -d --name wu-portal --restart unless-stopped --memory 128m \
  --network wenilla-realm_default --network-alias mangosd \
  --env-file /srv/wrath/portal.env -v /srv/wrath/portal:/app:ro -v /srv/wrath/hosted:/hosted -v /srv/wrath/portal-data:/data \
  python:3.12-alpine python3 -I /app/wrath_portal.py >/dev/null
docker network connect ov-wotlk_edge wu-portal
CF=/opt/openvanilla-classicplus/Caddyfile
[ -f "$CF" ] || die "$CF not found"
[ -f Caddyfile.before-wrath ] || cp -p "$CF" Caddyfile.before-wrath
python3 -I - "$CF" <<'PY2'
import sys
p = sys.argv[1]; s = open(p).read()
mark = "# WrathUnleashed (deploy.sh)"
anchor = "\thandle {\n\t\treverse_proxy ovlive-realm:8090"
if mark not in s:
    if anchor not in s: sys.exit("anchor not found in Caddyfile")
    block = ("\t" + mark + ": the Wrath sign-in page; the old play page sends players there.\n"
             "\tredir / /wrath/leyline 302\n\tredir /play /wrath 302\n"
             "\thandle /wrath* {\n\t\treverse_proxy wu-portal:8091 {\n"
             "\t\t\theader_up X-Real-IP {remote_host}\n\t\t\theader_up X-Forwarded-For {remote_host}\n\t\t}\n\t}\n\n")
    s = s.replace(anchor, block + anchor, 1)
    with open(p, "r+") as f:   # same file (it is bind-mounted into Caddy)
        f.seek(0); f.write(s); f.truncate()
PY2
if ! (cd /opt/wenilla-realm && docker compose exec -T caddy caddy reload --config /etc/caddy/Caddyfile --adapter caddyfile); then
  cat Caddyfile.before-wrath > "$CF"
  die "Caddy refused the new Caddyfile; the old one is back. The realm itself is up."
fi
sleep 3
code=$(curl -s -m 25 -o /dev/null -w '%{http_code}' "https://$REALM_HOST/wrath/healthz" || true)
echo "  https://$REALM_HOST/wrath/healthz -> $code (200 = sign-in page and SOAP bridge working)"

n=$(docker exec wu-portal python3 -c 'import socket; print(len(socket.gethostbyname_ex("mangosd")[2]))' 2>/dev/null || echo "?")
echo "  \"mangosd\" answers with $n address(es) on the website network (1 = only the bridge)"

log "10/10 Status"
docker compose ps
free -h | sed -n 1,2p
echo
echo "$REALM_NAME is up. Players sign in at https://${REALM_HOST}/wrath (Google or Hero Key) to see their login."
echo "Check from your PC: Test-NetConnection ${REALM_HOST} -Port 3724   (and -Port 8085)"
echo "If those fail, open TCP 3724 and 8085 in the Hetzner Cloud Firewall (console) too."
echo "Undo: bash /srv/wrath/rollback.sh"
