#!/usr/bin/env bash
# Vanilla Remastered: start the old 1.12 realm's own game servers again (owner 2026-10-30 20:38: "stream it
# temporarily until someone takes over via P2P"). Only the realm itself: its login server and its world server.
# Duels, the Herald support proxies and the 1.12 timers stay off (stop-112-jobs.sh turned those off; they are
# not needed). Run as root by "Turn on the 1.12 realm.bat" (one SSH login; this folder, probe112.py and the
# kit's wunet arrive as a tarball over stdin):
#
#   bash start-112-realm.sh <source dir>            dry run: checks and says what it would do (read-only)
#   bash start-112-realm.sh <source dir> --go       do it: backup, start, self-check, roll back on failure
#   bash start-112-realm.sh <source dir> --off      stop them again (kept, not removed; --go starts them again)
#
# Why not just `docker start wenilla-realm-mangosd-1 wenilla-realm-realmd-1` (or start-112-jobs.sh): the Wrath
# realm took this box's game ports (ov-ac-authserver 0.0.0.0:3724, ov-ac-worldserver 0.0.0.0:8085) when it was
# deployed (server/deploy.sh), and wu-portal answers as "mangosd" on wenilla-realm_default (the website's account
# bridge to the Wrath realm). The old containers publish those ports and carry that name, so starting them would
# either fail or split the website's new accounts between two servers. So this script leaves the old containers
# exactly as they are (stopped, restart=no; inspected only) and runs two NEW containers from the very same image
# ids, settings, environment and volumes:
#   vr-realmd   the 1.12 login server  (vr-realmd:3724)
#   vr-mangosd  the 1.12 world server  (vr-mangosd:8085)
# on their own internal network vr-112 (no published port, no route out), with the 1.12 database
# (wenilla-realm-mariadb-1) joined to it under its usual names. Players reach the realm only through the Leyline
# relay ("Put Vanilla Remastered on Leyline.bat", hosting/vanilla-remastered/vr-beacon-up.sh).
#
#   1 checks   root, Docker, the old containers (present, stopped), the 1.12 database up, the Wrath realm up,
#              memory and disk; that nothing else answers as vr-realmd / vr-mangosd
#   2 backup   /root/vr112-on-<stamp>/: a dump of every database in wenilla-realm-mariadb-1 (gzip, 0600), and
#              what existed before (network, containers); nothing in it is printed
#   3 start    network vr-112, the database joined to it, vr-realmd, then vr-mangosd (restart unless-stopped)
#   4 check    the login server answers a 1.12.1 logon challenge; the world server greets (SMSG_AUTH_CHALLENGE)
#              within VR_WORLD_WAIT seconds and does not restart; the 1.12 site (wenilla-realm-realm-1) still
#              answers; the Wrath realm still answers and "mangosd" on the site network is still only wu-portal.
#              Any failure: everything this run made is taken away again (the database was not changed).
#
# Last line: "OV112 REALM ON" / "OV112 REALM OFF" / "OV112 REALM DRY", or an error (exit 1).
# It never deletes a volume, a database, an image or the old containers, never prints the environment (it holds the
# database password) and never publishes a port. Everything can be moved for tests (hosting/vanilla-remastered/tests).
set -uo pipefail
SRC="${1:?usage: start-112-realm.sh <source dir> [--go|--off]}"
MODE="${2:---check}"
OLD_LOGON="${VR_OLD_LOGON:-wenilla-realm-realmd-1}"
OLD_WORLD="${VR_OLD_WORLD:-wenilla-realm-mangosd-1}"
DB="${VR_DB:-wenilla-realm-mariadb-1}"
SITE="${VR_SITE:-wenilla-realm-realm-1}"
SITE_NET="${VR_SITE_NET:-wenilla-realm_default}"
NET="${VR_NET:-vr-112}"
LOGON=vr-realmd
WORLD=vr-mangosd
AGENT=wu-vr-agent
WRATH_AUTH="${VR_WRATH_AUTH:-ov-ac-authserver}"
WRATH_WORLD="${VR_WRATH_WORLD:-ov-ac-worldserver}"
BACKUP_ROOT="${VR_BACKUP_ROOT:-/root}"
ENV_DIR="${VR_ENV_DIR:-/root/vr112-env}"
MIN_FREE_MB="${VR_MIN_FREE_MB:-1500}"
MIN_DISK_MB="${VR_MIN_DISK_MB:-3000}"
WORLD_WAIT="${VR_WORLD_WAIT:-600}"
PAUSE="${VR_PAUSE:-10}"
log() { printf '\n== %s\n' "$*"; }
note() { printf '  %s\n' "$*"; }
die() { printf '\nOV112 REALM FAILED: %s\n' "$*" >&2; exit 1; }
BLOCKED=""
gate() {  # gate MESSAGE: stops --go; the dry run reports it and goes on
  if [ "$MODE" = --check ]; then note "WOULD STOP: $1"; BLOCKED=1; else die "$1"; fi
}
running() { docker ps --format '{{.Names}}' | grep -x "$1" >/dev/null; }
exists() { docker ps -a --format '{{.Names}}' | grep -x "$1" >/dev/null; }

case "$MODE" in --check|--go|--off) ;; *) die "usage: start-112-realm.sh <source dir> [--go|--off]";; esac
find "$SRC" -type f \( -name '*.sh' -o -name '*.py' \) -exec sed -i 's/\r$//' {} + 2>/dev/null || true
PROBE="$SRC/hosting/vanilla-remastered/probe112.py"
[ -f "$PROBE" ] || die "hosting/vanilla-remastered/probe112.py is missing from the upload"
[ -f "$SRC/hosting/kit/tools/wunet/wire335.py" ] || die "hosting/kit/tools/wunet is missing from the upload"
[ "${VR_TEST:-0}" = 1 ] || [ "$(id -u)" = 0 ] || die "run as root"
command -v docker >/dev/null || die "docker not found"

# A probe container: python on the given network, the upload's wunet and probe112.py read-only. No image is pulled:
# the box already has python:3.12-alpine (wu-portal) and wu-hangout-tools:1 (the Dalaran Hangout's agent).
PY_IMG=""
for i in python:3.12-alpine wu-hangout-tools:1; do docker image inspect "$i" >/dev/null 2>&1 && { PY_IMG=$i; break; }; done
probe() {  # probe NETWORK ARGS...
  local net="$1"; shift
  [ -n "$PY_IMG" ] || { echo "no python image on this box"; return 1; }
  docker run --rm --network "$net" --memory 64m --cap-drop ALL --security-opt no-new-privileges --read-only \
    -v "$SRC/hosting/kit/tools/wunet:/p/wunet:ro" -v "$PROBE:/p/probe112.py:ro" --entrypoint python3 "$PY_IMG" \
    -I /p/probe112.py "$@"
}

# ---------------------------------------------------------------------------------------------------- off
if [ "$MODE" = --off ]; then
  log "Off: the 1.12 realm's game servers stop (kept; --go starts them again)"
  if running "$AGENT"; then
    die "Vanilla Remastered is still on Leyline ($AGENT runs): take it off first (the vr-beacon-off step). Nothing was changed."
  fi
  for c in "$WORLD" "$LOGON"; do   # the world server first: it saves the players who are still on
    if exists "$c"; then
      docker update --restart=no "$c" >/dev/null 2>&1 || note "!! could not change $c's restart policy"
      if running "$c"; then docker stop -t 120 "$c" >/dev/null && note "stopped: $c" || note "!! could not stop $c"
      else note "already stopped: $c"; fi
    else
      note "not here: $c"
    fi
  done
  note "the network $NET and the database stay as they are; the old containers ($OLD_LOGON, $OLD_WORLD) were never touched"
  echo; echo "OV112 REALM OFF"; exit 0
fi

# ---------------------------------------------------------------------------------------------------- checks
log "1/4 Checks"
for c in "$OLD_LOGON" "$OLD_WORLD"; do
  exists "$c" || die "$c is not on this box: there is nothing to copy the 1.12 realm from. Nothing was changed."
  running "$c" && gate "$c is running: the old container and a copy must never share the database. Nothing was changed."
done
running "$DB" || die "the 1.12 database ($DB) is not running. Nothing was changed."
for c in "$WRATH_AUTH" "$WRATH_WORLD"; do running "$c" || note "note: $c (the Wrath realm) is not running"; done
for c in "$OLD_LOGON" "$OLD_WORLD"; do
  ports=$(docker inspect -f '{{range $p, $b := .HostConfig.PortBindings}}{{$p}} {{end}}' "$c" 2>/dev/null)
  nets=$(docker inspect -f '{{range $k, $v := .NetworkSettings.Networks}}{{$k}} {{end}}' "$c" 2>/dev/null)
  img=$(docker inspect -f '{{.Config.Image}}' "$c" 2>/dev/null)
  note "$c: image $img; published ports: ${ports:-none} (the copy publishes none); networks: ${nets:-none}"
done
free_mb=$(awk '/MemAvailable/ {print int($2/1024)}' /proc/meminfo 2>/dev/null || echo 0)
disk_mb=$(df -Pm "$BACKUP_ROOT" 2>/dev/null | awk 'NR==2 {print $4}')
note "memory available: ${free_mb} MB (needs $MIN_FREE_MB), disk free in $BACKUP_ROOT: ${disk_mb:-?} MB (needs $MIN_DISK_MB)"
LOGON_UP=0; WORLD_UP=0
running "$LOGON" && LOGON_UP=1
running "$WORLD" && WORLD_UP=1
if [ "$LOGON_UP$WORLD_UP" != 11 ]; then
  [ "${free_mb:-0}" -ge "$MIN_FREE_MB" ] || gate "only ${free_mb} MB of memory available; the 1.12 world server needs about $MIN_FREE_MB MB next to the Wrath realm (VR_MIN_FREE_MB). Nothing was changed."
fi
[ "${disk_mb:-0}" -ge "$MIN_DISK_MB" ] || gate "only ${disk_mb:-?} MB free in $BACKUP_ROOT for the database backup. Nothing was changed."
[ -n "$PY_IMG" ] || gate "no python image (python:3.12-alpine or wu-hangout-tools:1) for the self-check. Nothing was changed."
if [ -f /srv/wrath/portal/gamedata-off ]; then
  note "WARNING: the game data killswitch is ON for the Wrath stream. It does not cover the 1.12 site's own files"
  note "         (see docs/VANILLA-REMASTERED.md); this step does not change what the 1.12 site serves."
fi
site_report() {  # read-only: how players reach the 1.12 site and its browser game today (nothing secret is printed)
  log "The 1.12 site and its browser game (report only)"
  local cf="${VR_CADDYFILE:-/opt/openvanilla-classicplus/Caddyfile}" u
  if [ -f "$cf" ]; then
    note "routes in $cf (handle / redir / reverse_proxy / file_server / root lines):"
    grep -nE '^[[:space:]]*(handle|@|redir|reverse_proxy|file_server|root|[a-z0-9.-]+\.[a-z]+[[:space:]]*\{)' "$cf" \
      | grep -viE 'basicauth|password|secret|token|key' | sed 's/^/    /' | head -80
  else
    note "no Caddyfile at $cf"
  fi
  if exists "$SITE"; then
    note "$SITE: address settings (names and values of *_ADDR/_HOST/_PORT/_URL/_WS/REALM* only; nothing secret):"
    docker inspect -f '{{range .Config.Env}}{{println .}}{{end}}' "$SITE" 2>/dev/null \
      | grep -E '^[A-Z0-9_]*(ADDR|HOST|PORT|URL|WS|REALM|MANGOS|SOAP|STREAM|DATA)[A-Z0-9_]*=' \
      | grep -viE 'PASS|SECRET|TOKEN|KEY|SALT|COOKIE|DSN|PWD' \
      | sed -E 's#(://)[^/@[:space:]]*@#\1***@#g' | sed 's/^/    /' | head -40   # never print the user:password in a URL
  fi
  for u in ${VR_SITE_URLS:-https://play.openvanilla.app/ https://play.openvanilla.app/play https://play.openvanilla.app/game https://play.openvanilla.app/data/ https://play.openvanilla.app/ws/3724}; do
    note "$u -> $(curl -s -o /dev/null -m 10 -w '%{http_code} %{redirect_url}' "$u" 2>/dev/null || echo 'no answer')"
  done
  if [ -f /srv/wrath/portal/gamedata-off ]; then note "game data killswitch: ON (it covers the Wrath stream only)"
  else note "game data killswitch: off (it covers the Wrath stream only, not the 1.12 site)"; fi
}

if [ "$MODE" = --check ]; then
  site_report
  note "already running: $LOGON=$LOGON_UP $WORLD=$WORLD_UP"
  echo; echo "Would: back up $DB to $BACKUP_ROOT/vr112-on-<time>/, make network $NET (internal), join $DB to it,"
  echo "start $LOGON and $WORLD from the images and settings of $OLD_LOGON and $OLD_WORLD (no published ports),"
  echo "then check the login and world servers, the 1.12 site and the Wrath realm, and roll back on failure."
  [ -n "$BLOCKED" ] && echo "The --go run would stop at the WOULD STOP lines above."
  echo; echo "Dry run finished: nothing changed. Run again with --go to apply."
  echo "OV112 REALM DRY"; exit 0
fi

# ---------------------------------------------------------------------------------------------------- backup
log "2/4 Backup"
STAMP=$(date +%Y%m%d-%H%M%S)
B="$BACKUP_ROOT/vr112-on-$STAMP"
( umask 077; mkdir -p "$B" ) || die "could not make $B"
docker exec "$DB" sh -c 'p="${MARIADB_ROOT_PASSWORD:-${MYSQL_ROOT_PASSWORD:-}}"; [ -n "$p" ] || exit 9; d=$(command -v mariadb-dump || command -v mysqldump); MYSQL_PWD="$p" exec "$d" -uroot --all-databases --single-transaction --routines --events' \
  | gzip > "$B/mariadb-all.sql.gz" || die "the backup of $DB failed (no root password in its environment?). Nothing was changed."
chmod 600 "$B/mariadb-all.sql.gz"
[ "$(stat -c %s "$B/mariadb-all.sql.gz")" -gt 2000 ] || die "the backup $B/mariadb-all.sql.gz is suspiciously small. Nothing was changed."
NET_WAS=0; docker network inspect "$NET" >/dev/null 2>&1 && NET_WAS=1
DB_ON_NET=0
[ "$NET_WAS" = 1 ] && docker network inspect "$NET" -f '{{range .Containers}}{{println .Name}}{{end}}' | grep -x "$DB" >/dev/null && DB_ON_NET=1
LOGON_WAS=0; exists "$LOGON" && LOGON_WAS=1
WORLD_WAS=0; exists "$WORLD" && WORLD_WAS=1
printf 'network=%s\ndb_on_network=%s\n%s=%s running=%s\n%s=%s running=%s\n' "$NET_WAS" "$DB_ON_NET" \
  "$LOGON" "$LOGON_WAS" "$LOGON_UP" "$WORLD" "$WORLD_WAS" "$WORLD_UP" > "$B/before.txt"
note "backup: $B (mariadb-all.sql.gz $(du -h "$B/mariadb-all.sql.gz" | cut -f1); restore by hand only, this step changes no data)"

MADE=()   # what this run started or made, for the rollback
rollback() {
  echo "  rolling back (the database was not changed)" >&2
  local c
  for c in "${MADE[@]}"; do
    case "$c" in
      new:*) docker rm -f "${c#new:}" >/dev/null 2>&1 || true ;;                    # a container this run created
      started:*) docker stop -t 60 "${c#started:}" >/dev/null 2>&1 || true
                 docker update --restart=no "${c#started:}" >/dev/null 2>&1 || true ;;  # one that was there, stopped
    esac
  done
  [ "$DB_ON_NET" = 0 ] && docker network disconnect "$NET" "$DB" >/dev/null 2>&1 || true
  [ "$NET_WAS" = 0 ] && docker network rm "$NET" >/dev/null 2>&1 || true
}
fail() { rollback; die "$1; rolled back. Backup: $B"; }

# ---------------------------------------------------------------------------------------------------- start
log "3/4 Start $LOGON and $WORLD on $NET"
if [ "$NET_WAS" = 0 ]; then
  docker network create --internal --label leyline.vr=1 "$NET" >/dev/null || fail "could not make the network $NET"
  note "network $NET made (internal: no route out, no published port)"
fi
if [ "$DB_ON_NET" = 0 ]; then
  aliases=$(docker inspect -f "{{with index .NetworkSettings.Networks \"$SITE_NET\"}}{{range .Aliases}}{{println .}}{{end}}{{end}}" "$DB" 2>/dev/null)
  svc=$(docker inspect -f '{{index .Config.Labels "com.docker.compose.service"}}' "$DB" 2>/dev/null)
  args=()
  for a in $svc $aliases; do
    [[ "$a" =~ ^[A-Za-z0-9_.-]+$ ]] && [ "$a" != "$DB" ] && args+=(--alias "$a")
  done
  docker network connect "${args[@]}" "$NET" "$DB" >/dev/null || fail "could not join $DB to $NET"
  note "$DB joined to $NET (as: $DB ${svc:-} $(echo $aliases | tr '\n' ' '))"
fi

copy_run() {  # copy_run NEW OLD: a new container from OLD's image id, settings, environment and mounts
  local new="$1" old="$2" img user wd tty stdin mem ep cmd m
  img=$(docker inspect -f '{{.Image}}' "$old") || return 1
  user=$(docker inspect -f '{{.Config.User}}' "$old")
  wd=$(docker inspect -f '{{.Config.WorkingDir}}' "$old")
  tty=$(docker inspect -f '{{.Config.Tty}}' "$old")
  stdin=$(docker inspect -f '{{.Config.OpenStdin}}' "$old")
  mem=$(docker inspect -f '{{.HostConfig.Memory}}' "$old")
  ( umask 077; mkdir -p "$ENV_DIR" )
  ( umask 077; docker inspect -f '{{range .Config.Env}}{{println .}}{{end}}' "$old" | grep -v '^$' > "$ENV_DIR/$new.env" ) || return 1
  chmod 600 "$ENV_DIR/$new.env"
  local run=(docker run -d --name "$new" --restart unless-stopped --network "$NET" --env-file "$ENV_DIR/$new.env"
             --label leyline.vr=1 --label "leyline.vr.from=$old" --security-opt no-new-privileges
             --log-opt max-size=20m --log-opt max-file=3)
  [ -n "$user" ] && run+=(--user "$user")
  [ -n "$wd" ] && run+=(-w "$wd")
  [ "$tty" = true ] && run+=(-t)
  [ "$stdin" = true ] && run+=(-i)
  [ -n "$mem" ] && [ "$mem" != 0 ] && run+=(--memory "$mem")
  while IFS='|' read -r typ name srcp dst rw; do
    [ -n "$dst" ] || continue
    case "$typ" in
      volume) m="type=volume,src=$name,dst=$dst" ;;
      bind)   m="type=bind,src=$srcp,dst=$dst" ;;
      *) continue ;;
    esac
    [ "$rw" = false ] && m="$m,readonly"
    run+=(--mount "$m")
  done < <(docker inspect -f '{{range .Mounts}}{{.Type}}|{{.Name}}|{{.Source}}|{{.Destination}}|{{.RW}}{{println}}{{end}}' "$old")
  # the entry point and command, exactly (JSON arrays: no word splitting)
  mapfile -d '' ep < <(docker inspect -f '{{json .Config.Entrypoint}}' "$old" | python3 -I -c 'import json,sys;v=json.load(sys.stdin) or [];sys.stdout.write("".join(a+"\0" for a in v))')
  mapfile -d '' cmd < <(docker inspect -f '{{json .Config.Cmd}}' "$old" | python3 -I -c 'import json,sys;v=json.load(sys.stdin) or [];sys.stdout.write("".join(a+"\0" for a in v))')
  if [ "${#ep[@]}" -gt 0 ]; then
    run+=(--entrypoint "${ep[0]}" "$img" "${ep[@]:1}" "${cmd[@]}")
  else
    run+=("$img" "${cmd[@]}")
  fi
  "${run[@]}" >/dev/null
}

start_one() {  # start_one NEW OLD
  if running "$1"; then note "$1: already running"; return 0; fi
  if exists "$1"; then
    docker update --restart unless-stopped "$1" >/dev/null && docker start "$1" >/dev/null || return 1
    MADE+=("started:$1"); note "$1: started again (the container this step made before)"
  else
    copy_run "$1" "$2" || { docker rm -f "$1" >/dev/null 2>&1; return 1; }
    MADE+=("new:$1"); note "$1: made from $2 (same image id, settings and volumes; no published port)"
  fi
}
start_one "$LOGON" "$OLD_LOGON" || fail "$LOGON did not start"
start_one "$WORLD" "$OLD_WORLD" || fail "$WORLD did not start"

# ---------------------------------------------------------------------------------------------------- check
log "4/4 Self-check"
ok=""
for _ in $(seq 1 12); do
  if out=$(probe "$NET" logon "$LOGON" 3724 2>&1); then ok=1; break; fi
  running "$LOGON" || break
  sleep 5
done
[ -n "$ok" ] || { docker logs --tail 30 "$LOGON" >&2 2>&1 || true; fail "the login server ($LOGON:3724) does not answer a 1.12.1 logon (${out:-no answer})"; }
note "login server: $out"
ok=""; waited=0
while [ "$waited" -le "$WORLD_WAIT" ]; do
  if out=$(probe "$NET" world "$WORLD" 8085 2>&1); then ok=1; break; fi
  running "$WORLD" || break
  sleep "$PAUSE"; waited=$((waited + (PAUSE > 0 ? PAUSE : 1)))
done
[ -n "$ok" ] || { docker logs --tail 40 "$WORLD" >&2 2>&1 || true; fail "the world server ($WORLD:8085) did not greet within ${WORLD_WAIT}s (${out:-no answer})"; }
note "world server: $out (after about ${waited}s)"
sleep "${VR_SETTLE:-15}"
rc=$(docker inspect -f '{{.RestartCount}} {{.State.Running}}' "$WORLD" 2>/dev/null)
[ "$rc" = "0 true" ] || fail "the world server restarted or stopped right after it started (restarts, running: $rc)"
if running "$SITE"; then
  code=$(probe "$SITE_NET" http "http://$SITE:${VR_SITE_PORT:-8090}/" 2>&1) || fail "the 1.12 site ($SITE) does not answer any more ($code)"
  note "1.12 site: $code"
else
  note "note: the 1.12 site ($SITE) is not running (it was kept on by ov112-off; nothing here changes it)"
fi
held=$(for c in $(docker network inspect "$SITE_NET" -f '{{range .Containers}}{{println .Name}}{{end}}' 2>/dev/null); do
         docker inspect -f "{{with index .NetworkSettings.Networks \"$SITE_NET\"}}{{range .Aliases}}{{println .}}{{end}}{{end}}" "$c" 2>/dev/null | grep -x mangosd >/dev/null && echo "$c"
       done | sort -u | tr '\n' ' ')
case "$held" in ""|"wu-portal ") note "\"mangosd\" on $SITE_NET: ${held:-nobody} (the website's account bridge is unchanged)" ;;
  *) fail "\"mangosd\" on $SITE_NET is now held by: $held (the website's accounts would split)" ;; esac
for c in "$WRATH_AUTH" "$WRATH_WORLD"; do
  running "$c" || note "note: $c (the Wrath realm) is not running (it was not running before either, or check it)"
done

echo
echo "The 1.12 realm runs: $LOGON (login) and $WORLD (world) on $NET; nothing published, no route out."
echo "Next: the vr-beacon step lists it on Leyline as Vanilla Remastered. Off again: the ov112-realm-off step."
echo "Backup: $B"
echo "OV112 REALM ON"
