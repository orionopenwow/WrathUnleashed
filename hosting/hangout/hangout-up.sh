#!/usr/bin/env bash
# The Dalaran Hangout: the main realm itself, reachable as a Leyline Beacon through the relay (the
# owner hosts it; nothing runs anywhere but on the realm's own box). Run as root by "Deploy Dalaran hangout.bat"
# (one SSH login: this folder and kit/tools arrive as a tarball over stdin):
#
#   bash hangout-up.sh <extracted source dir>            install or update (safe to run again)
#   bash hangout-up.sh <extracted source dir> --remove   take it off Leyline (the key is kept)
#
# What it runs: two small containers.
#   wu-hangout-agent  the host kit's own agent (wuhost/agent.py; read-only, no capabilities, 64 MB), on the site's
#                     network (the relay's web side, wu-portal's status) and the realm's edge network. It keeps one
#                     tunnel to the relay (ws://<relay web side>/agent, the same box) and signs the listing heartbeat.
#   wu-hangout-auth   a second login server for the relay's players: the realm's own authserver image and settings
#                     (copied from ov-ac-authserver), the same database, no published port, but no automatic IP bans
#                     (AC_WRONG_PASS_MAX_COUNT=0). Every relay player reaches it from the agent's address, so the
#                     realm's IP ban (10 wrong passwords) would lock everyone out at once; the relay counts wrong
#                     passwords per player IP instead (RELAY_AUTH_FAILS_PER_IP). Direct players keep ov-ac-authserver.
#                     The world server is the realm's own (ov-ac-worldserver:8085).
# What it never does: touch acore_auth.realmlist, make accounts, grant GM rights, or open a port. The realm's key
# is made here (state/realm.key, 0600, never leaves this box); signups are off (players sign in with their own
# Wrath login from the website; see docs/leyline-realm-hopping.md "The Dalaran Hangout").
#
#   1 checks   root, Docker, the relay (wu-relay + its relay.env), the realm, wu-portal, the two networks
#   2 backup   $DIR/backups/<time>/: state.tgz (host.json + the key), the id files; image -> wu-hangout-tools:rollback
#   3 image    docker build wu-hangout-tools:1 from kit/tools (the running agent keeps going if this fails)
#   4 config   setup.py official: state/host.json (public, signup off, official: realm list kept)
#   5 start    the login server for relay players, then the agent, on both networks
#   6 health   the tunnel is up (relay-state.json + the relay's /api/realms/<id>), the realm answers, and the
#              listing has it; then the id files for the play page and the in-game list. Else: roll back.
#
# Last line: "HANGOUT OK" (or "HANGOUT REMOVED"), or an error (exit 1, everything put back as it was).
# Everything can be moved for tests (hosting/tests/test_hangout_deploy.py).
set -euo pipefail
SRC="${1:?usage: hangout-up.sh <source dir> [--remove]}"
MODE="${2:-up}"
DIR="${WU_HANGOUT_DIR:-/srv/wrath/hangout-beacon}"
RELAY_DIR="${WU_RELAY_DIR:-/opt/wu-relay}"
PORTAL_DIR="${WU_PORTAL_DIR:-/srv/wrath/portal}"
WRATH_DIR="${WU_WRATH_DIR:-/srv/wrath}"
SITE_NET="${WU_SITE_NET:-wenilla-realm_default}"
EDGE_NET="${WU_EDGE_NET:-ov-wotlk_edge}"
AUTH_FROM="${WU_HANGOUT_AUTH_FROM:-ov-ac-authserver}"   # the realm's own login server: image, settings, networks
AUTH_C=wu-hangout-auth
AUTH="$AUTH_C:3724"
WORLD="${WU_HANGOUT_WORLD:-ov-ac-worldserver:8085}"
STATUS_URL="${WU_HANGOUT_STATUS_URL:-http://wu-portal:8091/wrath/status.json}"
NAME="${WU_HANGOUT_NAME:-Dalaran Hangout}"
DEFAULT_TAGLINE="WrathUnleashed's own Dalaran: your Wrath characters, and everyone meets here."
DEFAULT_SUMMARY="The WrathUnleashed realm itself, reached through the Leyline relay and run by the WrathUnleashed team. Sign in with your Wrath login (no new account), hop here from any Leyline realm, and arrive in Dalaran."
# The Leyline brand switch (realm/brand.sh, LEYLINE_BRAND=1 in portal.env): the listing text says Leyline (the same
# words brand.sh writes to state/beacon.json).
if grep -qx 'LEYLINE_BRAND=1' "${WU_WRATH_DIR:-/srv/wrath}/portal.env" 2>/dev/null; then
  DEFAULT_TAGLINE="Leyline's own Dalaran: your characters, and everyone meets here."
  DEFAULT_SUMMARY="The Dalaran Hangout itself, reached through the Leyline relay and run by the Leyline team. Sign in with your website login (no new account), hop here from any Leyline realm, and arrive in Dalaran."
fi
TAGLINE="${WU_HANGOUT_TAGLINE:-$DEFAULT_TAGLINE}"
SUMMARY="${WU_HANGOUT_SUMMARY:-$DEFAULT_SUMMARY}"
TRIES="${WU_HEALTH_TRIES:-30}"
PAUSE="${WU_HEALTH_PAUSE:-2}"
C=wu-hangout-agent
IMG=wu-hangout-tools:1
UIDGID=10001:10001        # the tools image's "wu" user
log() { printf '\n== %s\n' "$*"; }
note() { printf '  %s\n' "$*"; }
die() { printf '\nHANGOUT FAILED: %s\n' "$*" >&2; exit 1; }
envget() { sed -n "s/^$2=\([^ #]*\).*/\1/p" "$1" 2>/dev/null | tail -1; }
jget() {  # jget FILE KEY: a top-level value of a small JSON file (true/false/number/string), or nothing
  python3 -I - "$1" "$2" <<'PY' 2>/dev/null || true
import json, sys
try:
    v = json.load(open(sys.argv[1])).get(sys.argv[2])
except (OSError, ValueError, AttributeError):
    sys.exit(0)
print("" if v is None else (str(v).lower() if isinstance(v, bool) else v))
PY
}
running() { docker ps --format '{{.Names}}' | grep -x "$1" >/dev/null; }

find "$SRC" -type f \( -name '*.sh' -o -name '*.py' -o -name '*.txt' -o -name 'Dockerfile' -o -name '*.env' \) \
  -exec sed -i 's/\r$//' {} +

log "1/6 Checks"
[ "${WU_TEST:-0}" = 1 ] || [ "$(id -u)" = 0 ] || die "run as root"
command -v docker >/dev/null || die "docker not found"
for f in kit/tools/Dockerfile kit/tools/wuhost/agent.py kit/tools/wuhost/setup.py kit/tools/wunet/keys.py hangout/rules.txt; do
  [ -f "$SRC/$f" ] || die "$f is missing from the upload"
done

remove_ids() {
  rm -f "$PORTAL_DIR/hangout-realm.id" "$WRATH_DIR/hangout-realm.id"
}
start_auth() {  # the relay players' login server, from the realm's own (its env file holds the database login: 0600)
  local img wd net first=""
  img=$(docker inspect -f '{{.Config.Image}}' "$AUTH_FROM") || return 1
  wd=$(docker inspect -f '{{.Config.WorkingDir}}' "$AUTH_FROM" 2>/dev/null || true)
  ( umask 077; docker inspect -f '{{range .Config.Env}}{{println .}}{{end}}' "$AUTH_FROM" | grep -v -e '^AC_WRONG_PASS_' -e '^$' > "$DIR/auth.env" ) || return 1
  printf 'AC_WRONG_PASS_MAX_COUNT=0\nAC_WRONG_PASS_LOGGING=1\n' >> "$DIR/auth.env"
  chmod 600 "$DIR/auth.env"
  docker rm -f "$AUTH_C" >/dev/null 2>&1 || true
  for net in $(docker inspect -f '{{range $k, $v := .NetworkSettings.Networks}}{{println $k}}{{end}}' "$AUTH_FROM"); do
    if [ -z "$first" ]; then
      first=$net
      docker run -d -t --name "$AUTH_C" --restart unless-stopped --network "$net" --env-file "$DIR/auth.env" \
        ${wd:+-w "$wd"} --memory 128m --security-opt no-new-privileges \
        --log-opt max-size=10m --log-opt max-file=3 "$img" >/dev/null || return 1
    else
      docker network connect "$net" "$AUTH_C" >/dev/null 2>&1 || return 1
    fi
  done
  [ -n "$first" ] || return 1
  docker network inspect "$EDGE_NET" -f '{{range .Containers}}{{println .Name}}{{end}}' 2>/dev/null | grep -x "$AUTH_C" >/dev/null \
    || docker network connect "$EDGE_NET" "$AUTH_C" >/dev/null 2>&1 || true
  local _
  for _ in $(seq 1 "$TRIES"); do
    docker exec "$AUTH_C" bash -c 'exec 3<>/dev/tcp/127.0.0.1/3724' >/dev/null 2>&1 && return 0
    sleep "$PAUSE"
  done
  docker logs --tail 20 "$AUTH_C" >&2 2>&1 || true
  return 1
}
if [ "$MODE" = "--remove" ]; then
  log "Remove: the Dalaran Hangout leaves Leyline"
  docker rm -f "$C" "$AUTH_C" >/dev/null 2>&1 || true
  remove_ids
  note "containers gone, id files gone; the key stays in $DIR/state (running this step again brings the same realm back)"
  [ -f "$WRATH_DIR/leyline-fetch.py" ] && { python3 -I "$WRATH_DIR/leyline-fetch.py" >/dev/null 2>&1 || true; }
  echo "HANGOUT REMOVED"
  exit 0
fi

running wu-relay || die "the relay (wu-relay) is not running: run the relay step first. Nothing was changed."
[ -f "$RELAY_DIR/relay.env" ] || die "$RELAY_DIR/relay.env is missing (the relay step writes it). Nothing was changed."
BIND="$(envget "$RELAY_DIR/relay.env" RELAY_HTTP_BIND)"
RELAY_NAME="$(envget "$RELAY_DIR/relay.env" RELAY_NAME)"
RELAY_NAME="${RELAY_NAME:-relay.openvanilla.app}"
[[ "$BIND" =~ ^[0-9.]+:[0-9]+$ ]] || die "RELAY_HTTP_BIND in $RELAY_DIR/relay.env is '$BIND', not address:port. Nothing was changed."
for c in "$AUTH_FROM" ov-ac-worldserver wu-portal; do
  running "$c" || die "$c is not running: the hangout is that realm, so it must be up. Nothing was changed."
done
for n in "$SITE_NET" "$EDGE_NET"; do
  docker network inspect "$n" >/dev/null 2>&1 || die "Docker network $n not found. Nothing was changed."
done
curl -fsS -m 3 "http://$BIND/healthz" >/dev/null 2>&1 || die "the relay does not answer on http://$BIND/healthz. Nothing was changed."
note "relay $RELAY_NAME, web side $BIND; realm $WORLD on $EDGE_NET, relay players log in at $AUTH; status from $STATUS_URL"

log "2/6 Backup"
mkdir -p "$DIR/state" "$DIR/backups"
chmod 711 "$DIR"            # the agent's user reaches state/ and rules.txt, nothing else here
chmod 700 "$DIR/backups"    # backups hold the key: root only
BK="$DIR/backups/$(date +%Y%m%d-%H%M%S)"
mkdir -p "$BK"
tar -czf "$BK/state.tgz" -C "$DIR" state
for f in "$PORTAL_DIR/hangout-realm.id" "$WRATH_DIR/hangout-realm.id"; do
  [ -f "$f" ] && cp -p "$f" "$BK/$(basename "$(dirname "$f")")-hangout-realm.id"
done
HAD_IMAGE=0
if docker image inspect "$IMG" >/dev/null 2>&1; then docker tag "$IMG" wu-hangout-tools:rollback; HAD_IMAGE=1; fi
WAS_RUNNING=0
running "$C" && WAS_RUNNING=1
AUTH_WAS=0
running "$AUTH_C" && AUTH_WAS=1
note "backup: $BK (image kept as wu-hangout-tools:rollback: $HAD_IMAGE, agent was running: $WAS_RUNNING)"
ls -1d "$DIR"/backups/*/ 2>/dev/null | sort | head -n -5 | xargs -r rm -rf   # keep the last five

start_agent() {  # start_agent IMAGE
  docker rm -f "$C" >/dev/null 2>&1 || true
  docker run -d --name "$C" --restart unless-stopped --network "$SITE_NET" --memory 64m --memory-swap 64m \
    --cpus 0.5 --pids-limit 64 --read-only --tmpfs /tmp:size=8m --cap-drop ALL --security-opt no-new-privileges \
    --user "$UIDGID" -v "$DIR/state:/state" -e LOG_LEVEL=INFO --log-opt max-size=10m --log-opt max-file=3 \
    "$1" python -m wuhost.agent --state /state >/dev/null || return 1
  docker network connect "$EDGE_NET" "$C" >/dev/null 2>&1 || return 1
}
rollback() {
  echo "  rolling back to $BK" >&2
  docker rm -f "$C" >/dev/null 2>&1 || true
  if [ "$AUTH_WAS" = 0 ]; then docker rm -f "$AUTH_C" >/dev/null 2>&1 || true; fi
  rm -rf "$DIR/state.rollback"; mkdir -p "$DIR/state.rollback"
  tar -xzf "$BK/state.tgz" -C "$DIR/state.rollback" && rm -rf "$DIR/state" && mv "$DIR/state.rollback/state" "$DIR/state"
  rm -rf "$DIR/state.rollback"
  remove_ids
  for f in "$BK"/*-hangout-realm.id; do
    [ -f "$f" ] || continue
    case "$(basename "$f")" in
      "$(basename "$PORTAL_DIR")-hangout-realm.id") cp -p "$f" "$PORTAL_DIR/hangout-realm.id" ;;
      *) cp -p "$f" "$WRATH_DIR/hangout-realm.id" ;;
    esac
  done
  if [ "$HAD_IMAGE" = 1 ]; then docker tag wu-hangout-tools:rollback "$IMG"; fi
  if [ "$WAS_RUNNING" = 1 ] && [ "$HAD_IMAGE" = 1 ]; then start_agent "$IMG" || true; fi
}

log "3/6 Image $IMG"
docker build -q -t "$IMG" "$SRC/kit/tools" >/dev/null || die "building the agent image failed; nothing changed (the running agent, if any, keeps going)."
note "built"

log "4/6 Config ($DIR/state/host.json)"
install -m 644 "$SRC/hangout/rules.txt" "$DIR/rules.txt"
chown -R "$UIDGID" "$DIR/state" "$DIR/rules.txt" 2>/dev/null || true
chmod 700 "$DIR/state"
out=$(docker run --rm --user "$UIDGID" --network none -v "$DIR:/kit" -e WU_KIT=/kit "$IMG" python -m wuhost.setup official \
  --name "$NAME" --relay "$RELAY_NAME" --relay-url "ws://$BIND/agent" --listing-url "http://$BIND/api/listing/heartbeat" \
  --auth-service "$AUTH" --world-service "$WORLD" --status-url "$STATUS_URL" \
  --tagline "$TAGLINE" --summary "$SUMMARY" --rules-file /kit/rules.txt 2>&1) || { echo "$out" >&2; rollback; die "writing the config failed; rolled back."; }
RID=$(python3 -I -c 'import json,sys;print(json.loads(sys.stdin.read().strip().splitlines()[-1])["realm_id"])' <<<"$out" 2>/dev/null || true)
[[ "$RID" =~ ^[a-z2-7]{16}$ ]] || { echo "$out" >&2; rollback; die "the config did not give a realm id; rolled back."; }
[ "$(stat -c %a "$DIR/state/realm.key" 2>/dev/null || echo 600)" = 600 ] || { rollback; die "state/realm.key is not 0600; rolled back."; }
note "realm id $RID (key made on this box: $DIR/state/realm.key, never copied anywhere)"

log "5/6 Start $AUTH_C and $C"
start_auth || { rollback; die "the relay players' login server ($AUTH_C, from $AUTH_FROM) did not start; rolled back."; }
note "$AUTH_C: the realm's login server for relay players (same database, no IP bans, no published port)"
rm -f "$DIR/state/relay-state.json"
start_agent "$IMG" || { rollback; die "the agent container did not start; rolled back."; }
note "on $SITE_NET + $EDGE_NET, 64 MB, read-only"

log "6/6 Health check"
ok=""
for _ in $(seq 1 "$TRIES"); do
  if [ "$(jget "$DIR/state/relay-state.json" connected)" = true ]; then ok=1; break; fi
  sleep "$PAUSE"
done
if [ -z "$ok" ]; then
  docker logs --tail 30 "$C" >&2 2>&1 || true
  why=$(jget "$DIR/state/relay-state.json" last_error)
  rollback; die "the agent did not connect to the relay${why:+ ($why)}; rolled back."
fi
note "tunnel up"
online=$(curl -fsS -m 3 "http://$BIND/api/realms/$RID" 2>/dev/null | python3 -I -c 'import json,sys;print(json.load(sys.stdin).get("online"))' 2>/dev/null || true)
[ "$online" = True ] || { rollback; die "the relay does not see realm $RID online; rolled back."; }
st=$(curl -fsS -m 10 "http://$BIND/r/$RID/status.json" 2>/dev/null | python3 -I -c 'import json,sys;d=json.load(sys.stdin);print(d.get("online"), d.get("players"))' 2>/dev/null || true)
case "$st" in True*) note "the realm answers through the relay (status: online, players ${st#True })" ;;
  *) rollback; die "the realm's world server does not answer through the agent (status: ${st:-none}); rolled back." ;; esac
listed=""
for _ in $(seq 1 "$TRIES"); do
  if curl -fsS -m 3 "http://$BIND/api/listing/realms.json" 2>/dev/null | grep -q "\"realmId\": *\"$RID\""; then listed=1; break; fi
  sleep "$PAUSE"
done
if [ -z "$listed" ]; then
  why=$(jget "$DIR/state/relay-state.json" listing_reply)
  rollback; die "the Leyline listing does not show the hangout${why:+ (listing said: $why)}; rolled back."
fi
note "listed on Leyline"
mkdir -p "$PORTAL_DIR"
for f in "$PORTAL_DIR/hangout-realm.id" "$WRATH_DIR/hangout-realm.id"; do
  printf '%s\n' "$RID" > "$f.tmp" && chmod 644 "$f.tmp" && mv "$f.tmp" "$f"
done
note "$PORTAL_DIR/hangout-realm.id: the play page lists it first, hops to it keep the Wrath login and land in Dalaran"
note "$WRATH_DIR/hangout-realm.id: the in-game Leyline window lists it first"
if [ -f "$WRATH_DIR/leyline-fetch.py" ]; then
  python3 -I "$WRATH_DIR/leyline-fetch.py" >/dev/null 2>&1 && note "in-game realm list refreshed" || note "in-game realm list: refreshed by its own cron within 5 minutes"
fi
echo
echo "Dalaran Hangout: realm $RID on $RELAY_NAME (https://$RELAY_NAME/r/$RID/status.json)"
echo "Logs: docker logs -f $C (and $AUTH_C)    Off Leyline: the hangout-off step    Backup: $BK"
echo "HANGOUT OK"
