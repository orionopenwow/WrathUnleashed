#!/usr/bin/env bash
# End-to-end test of home hosting: relay + host kit + headless 3.3.5a players, all in Docker.
#
#   bash tests/e2e/run-e2e.sh --fake     no game data needed (GitHub Actions): the realm is
#                                        tests/fake_realm.py, everything else is the real thing
#   bash tests/e2e/run-e2e.sh --real     real AzerothCore from images + the ov-client-data volume
#                                        (dbc+maps from your own 3.3.5a install): the owner's PC, the
#                                        server, or a self-hosted runner. Images: WU_IMAGE / WU_TAG
#                                        (default: the local ov/ac-wotlk-*:custom, else acore stock)
#
# Players run in containers on the relay's network only (never the realm's), private mode first,
# then the realm switches to public and a FRESH container (a new IP) plays without an invite.
# Leaves nothing behind (--keep to keep it for a look). Exit 0 = pass.
set -euo pipefail
MODE="${1:---fake}"
KEEP=0; [ "${2:-}" = "--keep" ] && KEEP=1
HOSTING="$(cd "$(dirname "$0")/../.." && pwd)"
WORK="$(mktemp -d -t wu-e2e-XXXX)"
NET=wu-e2e-net
P=wu-e2e
TOOLS=wu-host-tools:e2e
RELAY_IMG=wu-relay:e2e
log() { printf '\n== %s\n' "$*"; }

cleanup() {
  [ "$KEEP" = 1 ] && { echo "kept: $WORK (docker: $P*)"; return; }
  docker rm -f wu-e2e-relay wu-e2e-fake wu-e2e-agent >/dev/null 2>&1 || true
  if [ -f "$WORK/kit/docker-compose.host.yml" ]; then
    docker compose -p "$P" -f "$WORK/kit/docker-compose.host.yml" -f "$WORK/override.yml" --project-directory "$WORK/kit" down -v >/dev/null 2>&1 || true
  fi
  docker network rm "$NET" wu-e2e-realm >/dev/null 2>&1 || true
  rm -rf "$WORK"
}
trap cleanup EXIT

log "build images"
docker build -q -t "$TOOLS" "$HOSTING/kit/tools" >/dev/null
docker build -q -f "$HOSTING/relay/Dockerfile" -t "$RELAY_IMG" "$HOSTING" >/dev/null
docker network create "$NET" >/dev/null

log "relay"
docker run -d --name wu-e2e-relay --network "$NET" --network-alias relay.e2e \
  -e RELAY_NAME=relay.e2e -e RELAY_HTTP_BIND=0.0.0.0:8080 -e RELAY_TRUST_PROXY=0 \
  -e RELAY_PORT_MIN=40000 -e RELAY_PORT_MAX=40019 -e RELAY_LISTING_SITE_SECRET=e2e \
  -e RELAY_SITE_ORIGINS=https://openvanilla.app "$RELAY_IMG" >/dev/null
for i in $(seq 1 30); do docker exec wu-e2e-relay python -c "import urllib.request;urllib.request.urlopen('http://127.0.0.1:8080/healthz')" 2>/dev/null && break; sleep 1; done

log "host kit setup (private)"
cp -r "$HOSTING/kit" "$WORK/kit"
rm -rf "$WORK/kit/state" "$WORK/kit/.env"
if [ "$MODE" = --real ]; then
  if [ -n "${WU_IMAGE:-}" ]; then IMG="$WU_IMAGE"; TAG="${WU_TAG:-stable}"
  elif docker image inspect ov/ac-wotlk-worldserver:custom >/dev/null 2>&1; then IMG=ov/ac-wotlk; TAG=custom
  else IMG=acore/ac-wotlk; TAG=master; fi
else IMG=none; TAG=none; fi
docker run --rm -v "$WORK/kit:/kit" -e WU_KIT=/kit "$TOOLS" python -m wuhost.setup init --name "E2E Realm" \
  --profile main --visibility private --image "$IMG" --tag "$TAG" --tools-image "$TOOLS" --relay relay.e2e \
  --relay-url ws://relay.e2e:8080/agent --listing-url http://relay.e2e:8080/api/listing/heartbeat \
  --site http://relay.e2e:8080 --bots 0
chmod -R a+rwX "$WORK/kit/state"

wait_connected() {
  for i in $(seq 1 "${1:-120}"); do
    grep -q '"connected": true' "$WORK/kit/state/relay-state.json" 2>/dev/null && \
      { [ "$MODE" = --fake ] || grep -q '"realmlist_ok": true' "$WORK/kit/state/relay-state.json"; } && return 0
    sleep 2
  done
  echo "agent never connected:"; cat "$WORK/kit/state/relay-state.json" 2>/dev/null || true; return 1
}

ACCOUNT_ARGS=()
if [ "$MODE" = --fake ]; then
  log "fake realm + agent (no game data)"
  docker network create --internal wu-e2e-realm >/dev/null
  docker run -d --name wu-e2e-fake --network wu-e2e-realm --network-alias ac-authserver --network-alias ac-worldserver \
    -v "$WORK/kit/state:/state:ro" -v "$HOSTING:/hosting:ro" -e PYTHONPATH=/app:/hosting/tests "$TOOLS" \
    python /hosting/tests/fake_realm.py --account E2EUSER:E2EPASS1 >/dev/null
  docker run -d --name wu-e2e-agent --network wu-e2e-realm -v "$WORK/kit/state:/state" -e WU_HEARTBEAT_SECS=5 \
    "$TOOLS" python -m wuhost.agent --state /state >/dev/null
  docker network connect "$NET" wu-e2e-agent
  ACCOUNT_ARGS=(--account E2EUSER:E2EPASS1)
  wait_connected 60
  sleep 2   # the fake realm picks up the relay address
else
  log "real realm from images: $IMG-*:$TAG"
  docker volume inspect ov-client-data >/dev/null 2>&1 || { echo "no ov-client-data volume (dbc+maps): run the kit's extraction first"; exit 2; }
  [ -f "$WORK/kit/realm-files/profiles/main.env" ] || {
    [ -n "${WU_REALM_DIR:-}" ] && bash "$WORK/kit/make-kit.sh" "$WU_REALM_DIR" >/dev/null || {
      echo "kit has no realm-files/: set WU_REALM_DIR=/path/to/WrathUnleashed/realm"; exit 2; }; }
  cat > "$WORK/override.yml" <<EOF
networks:
  egress:
    external: true
    name: $NET
services:
  ac-database: { container_name: wu-e2e-database }
  ac-authserver: { container_name: wu-e2e-authserver }
  ac-worldserver: { container_name: wu-e2e-worldserver }
  wu-agent:
    container_name: wu-e2e-agent
    environment: { WU_HEARTBEAT_SECS: "5" }
EOF
  T0=$(date -u +%Y-%m-%dT%H:%M:%S)
  docker compose -p "$P" -f "$WORK/kit/docker-compose.host.yml" -f "$WORK/override.yml" --project-directory "$WORK/kit" up -d
  for i in $(seq 1 180); do
    docker logs --since "$T0" wu-e2e-worldserver 2>&1 | grep -F 'ready...' >/dev/null && break
    [ "$i" = 180 ] && { docker logs --tail 60 wu-e2e-worldserver; exit 1; }
    sleep 10
  done
  wait_connected 120
fi

player() {  # player NAME args...
  local name="$1"; shift
  docker run --rm --name "$name" --network "$NET" -v "$WORK/kit/state:/state:ro" -v "$HOSTING:/hosting:ro" \
    -v "$WORK:/work" "$TOOLS" python /hosting/tests/e2e/e2e_client.py "$@"
}

log "players: private realm"
player wu-e2e-p1 private --save-account /work/account.txt "${ACCOUNT_ARGS[@]}"
ACC="$(cat "$WORK/account.txt")"

log "switch to public"
docker run --rm -v "$WORK/kit:/kit" -e WU_KIT=/kit "$TOOLS" python -m wuhost.setup visibility public
chmod -R a+rwX "$WORK/kit/state"

log "players: public realm, fresh IP"
player wu-e2e-p2 public --account "$ACC"

log "self-check on the host"
if [ "$MODE" = --real ]; then
  docker compose -p "$P" -f "$WORK/kit/docker-compose.host.yml" -f "$WORK/override.yml" --project-directory "$WORK/kit" \
    run --rm --no-deps wu-agent python -c "import asyncio,sys; from wuhost import selfcheck; r=asyncio.run(selfcheck.run('/state', relay_http='http://relay.e2e:8080')); sys.exit(1 if r.bad else 0)"
else
  docker run --rm --network "$NET" -v "$WORK/kit/state:/state:ro" "$TOOLS" python -c "import asyncio,sys; from wuhost import selfcheck; r=asyncio.run(selfcheck.run('/state', login=False, relay_http='http://relay.e2e:8080', local_auth=('relay.e2e',1), local_world=('relay.e2e',1))); print('(local checks fail by design in --fake: the fake realm is not on this network)')" || true
fi
echo
echo "E2E PASSED ($MODE)"
