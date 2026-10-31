#!/usr/bin/env bash
# Host a Leyline (3.3.5a) realm from this Mac or Linux PC. Needs Docker, nothing else.
# No port forwarding: the realm talks out to the relay, players connect to the relay, nobody sees
# your home IP address.
#
#   bash host-wrath-realm.sh               set up (first time: 3 questions) and start; safe to re-run
#   bash host-wrath-realm.sh check         is my realm reachable? (plain-language self-check)
#   bash host-wrath-realm.sh show          invite link, your login, relay status
#   bash host-wrath-realm.sh stop          stop the realm (characters are kept)
#   bash host-wrath-realm.sh friend NAME [PASSWORD]   make a game account for a friend
#   bash host-wrath-realm.sh new-invite    a new invite link (the old one stops working)
#   bash host-wrath-realm.sh public|private
#   bash host-wrath-realm.sh claim TOKEN   link the realm to your Hero Key account (token from the site)
#   bash host-wrath-realm.sh signup invite|open|off   who may make accounts on the join page
#   bash host-wrath-realm.sh options [--type pvp] [--xp 5 --loot 2 --rep 3] [--start level1|boost]
#                                                    the realm's own settings (state/realm.env; restart to apply)
#   bash host-wrath-realm.sh herokey on|off   Hero Key sign-in from the Leyline website (off by default)
#   bash host-wrath-realm.sh browser on|off   browser players: on = Warden off so the browser client can join (default)
#   bash host-wrath-realm.sh max-players N    the most players at once: the server's cap and the realm list's (0 = default)
#   bash host-wrath-realm.sh rules         after editing state/rules.txt or state/beacon.json (realm list text)
#   bash host-wrath-realm.sh logs [service]
#
# Answers can come from the environment (no questions): WU_NAME, WU_PROFILE (main|brawl|progression|dalaran|vanillaplus, or a
# profile for another client: profiles/<id>/, e.g. cmangos-1.12.1, cmangos-2.4.3), WU_VISIBILITY
# (private|public), WU_GAME_DIR (your 3.3.5a folder; WU_WOW_DIR still works), WU_CLIENT_DIR (your game folder for another client's profile). Images: WU_IMAGE / WU_TAG
# (prebuilt, default below), falling back to the locally built ov/ac-wotlk-*:custom. Not published yet and
# not built here: it asks "build or stock" (WU_BUILD=1 builds, WU_BUILD=0 takes AzerothCore's stock images).
set -euo pipefail

KIT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$KIT"
WU_IMAGE="${WU_IMAGE:-ghcr.io/orionopenwow/wu-ac-wotlk}"   # prebuilt realm images (published by CI, owner's OK)
WU_TAG="${WU_TAG:-stable}"
WU_LOCAL_IMAGE="${WU_LOCAL_IMAGE:-ov/ac-wotlk}"            # built by realm/"Build custom realm.bat"
WU_LOCAL_TAG="${WU_LOCAL_TAG:-custom}"
WU_TOOLS_PREBUILT="${WU_TOOLS_PREBUILT:-ghcr.io/orionopenwow/wu-host-tools:1}"
WU_TOOLS_IMAGE="${WU_TOOLS_IMAGE:-wu-host-tools:1}"
WU_EXTRACT_IMAGE="${WU_EXTRACT_IMAGE:-acore/ac-wotlk-tools:master}"
# Leyline's addresses live in one file (tools/wunet/leyline.env: LEYLINE_DOMAIN=...).
LEYLINE_DOMAIN="${LEYLINE_DOMAIN:-$(sed -n 's/^LEYLINE_DOMAIN=\([^ #]*\).*/\1/p' "$KIT/tools/wunet/leyline.env" 2>/dev/null | head -1)}"
LEYLINE_DOMAIN="${LEYLINE_DOMAIN:-openvanilla.app}"
WU_RELAY="${WU_RELAY:-${LEYLINE_RELAY:-relay.$LEYLINE_DOMAIN}}"
ARAC_REPO="https://github.com/heyitsbench/mod-arac"
ARAC_COMMIT="3f605e09c656eb3b620ef2d70c7ef61808c1cfb0"      # = realm/custom/sources.lock
COMPOSE=(docker compose -f "$KIT/docker-compose.host.yml" --project-directory "$KIT")
DRY="${WU_DRY:-0}"

if [ -t 1 ]; then B=$'\033[1m'; G=$'\033[32m'; Y=$'\033[33m'; R=$'\033[31m'; N=$'\033[0m'; else B=""; G=""; Y=""; R=""; N=""; fi
say()  { printf '%s\n' "$*"; }
step() { printf '\n%s== %s%s\n' "$B" "$*" "$N"; }
die()  { printf '%sProblem: %s%s\n' "$R" "$*" "$N" >&2; exit 1; }
run()  { if [ "$DRY" = 1 ]; then printf 'DRY: %s\n' "$*"; else "$@"; fi; }
export WU_UID="$(id -u)" WU_GID="$(id -g)"   # state/ files stay yours; the agent runs as you
tools() {
  if [ "${LEYLINE_LOCAL_TOOLS:-0}" = 1 ]; then   # this PC's python3 instead of the tools image (tests, no Docker)
    PYTHONPATH="$KIT/tools" WU_KIT="$KIT" python3 -m wuhost.setup "$@"; return
  fi
  run docker run --rm --user "$WU_UID:$WU_GID" -v "$KIT:/kit" -e WU_KIT=/kit -e WU_UID -e WU_GID "$WU_TOOLS_IMAGE" python -m wuhost.setup "$@"
}

need_docker() {
  command -v docker >/dev/null 2>&1 || die "Docker is not installed. Get Docker Desktop (Mac) or Docker Engine (Linux), then run this again."
  docker info >/dev/null 2>&1 || die "Docker is installed but not running. Start it, then run this again."
  docker compose version >/dev/null 2>&1 || die "This Docker has no 'docker compose'. Update Docker."
}

need_tools() { [ "${LEYLINE_LOCAL_TOOLS:-0}" = 1 ] || need_docker; }

ask() {  # ask VAR "question" default [choices...]
  local var="$1" q="$2" def="$3"; shift 3
  local cur="${!var:-}"
  if [ -n "$cur" ]; then return; fi
  if [ ! -t 0 ]; then printf -v "$var" '%s' "$def"; return; fi
  local a
  while true; do
    read -r -p "$q [$def]: " a || true
    a="${a:-$def}"
    if [ $# -eq 0 ]; then break; fi
    for c in "$@"; do [ "$a" = "$c" ] && break 2; done
    say "  Please type one of: $*"
  done
  printf -v "$var" '%s' "$a"
}

state_get() {  # value of a top-level key in state/host.json (no jq needed)
  [ -f "$KIT/state/host.json" ] || return 0
  sed -n "s/^ *\"$1\": *\"\{0,1\}\([^\",]*\)\"\{0,1\},\{0,1\}$/\1/p" "$KIT/state/host.json" | head -1
}

# Host any client: a profile for another client has its own folder and compose file (profiles/<id>/, its steps in
# profiles/host-profile.sh); stop, logs and check use that compose file once state/host.json names the profile.
. "$KIT/profiles/host-profile.sh" 2>/dev/null || profile_known() { return 1; }
if profile_known "$(state_get profile)"; then
  for _f in "$KIT/profiles/$(state_get profile)"/docker-compose.*.yml; do
    [ -f "$_f" ] && COMPOSE=(docker compose -f "$_f" --project-directory "$KIT") && break
  done
fi

pull_prebuilt() {  # all three realm images, or the first error (stderr) for not_published
  local part
  for part in worldserver authserver db-import; do
    run docker pull -q "$WU_IMAGE-$part:$WU_TAG" >/dev/null || return 1
  done
}

not_published() {  # $1 = docker pull's error text: the registry answered, but the image isn't there (or not public)
  grep -Eiq 'denied|unauthorized|not found|manifest unknown|does not exist|no such manifest' <<<"$1"
}

build_local() {  # AzerothCore + the modules at the kit's pinned commits, the same recipe the published images use
  local b="$KIT/cache/build" t
  [ -f "$KIT/realm-files/build/sources.lock" ] || die "This kit has no realm-files/build/ (download the full kit again)."
  say "  Building the realm images on this PC: 1-2 hours and about 15 GB of disk, only once."
  mkdir -p "$b"
  cp "$KIT/realm-files/build/sources.lock" "$KIT/realm-files/build/fetch.sh" "$b/"
  rm -rf "$b/patches" && cp -r "$KIT/realm-files/build/patches" "$b/patches"
  say "  [1/2] Sources at the pinned commits (about 1 GB)..."
  run docker run --rm --entrypoint sh -v "$b:/w" alpine/git:latest /w/fetch.sh \
    || die "Getting the sources failed (is this PC online?). Run this again: it carries on where it stopped."
  say "  [2/2] Compiling (the long part)..."
  for t in worldserver authserver db-import; do
    run docker build --target "$t" --build-arg CTOOLS_BUILD=db-only --build-arg CWITH_WARNINGS=OFF \
      --build-arg CTYPE=Release -f "$b/acore/apps/docker/Dockerfile" -t "$WU_LOCAL_IMAGE-$t:$WU_LOCAL_TAG" "$b/acore" \
      || die "The build failed (see the first 'error:' above). Run this again: finished parts are kept."
  done
  say "  ${G}Built.${N}"
}

pick_images() {
  step "Realm images"
  local err=""
  if err=$(pull_prebuilt 2>&1); then
    IMG="$WU_IMAGE"; TAG="$WU_TAG"; say "  Using the prebuilt Leyline images ($IMG-*:$TAG)."
  elif docker image inspect "$WU_LOCAL_IMAGE-worldserver:$WU_LOCAL_TAG" >/dev/null 2>&1; then
    IMG="$WU_LOCAL_IMAGE"; TAG="$WU_LOCAL_TAG"; say "  Using the images built on this PC ($IMG-*:$TAG)."
  else
    if not_published "$err"; then
      say "  ${Y}The ready-made realm images are not published yet.${N}"
    else
      say "  ${Y}Could not download the ready-made realm images (is this PC online?).${N}"
    fi
    say "    build   build them on this PC now: 1-2 hours, about 15 GB of disk, only once (bots, boost, transmog...)"
    say "    stock   start now with a plain server, without those extras (run this again later to switch)"
    local how="${WU_BUILD:-}"
    case "$how" in 1|yes|build) how=build ;; 0|no|stock) how=stock ;; *) how="" ;; esac
    if [ -z "$how" ]; then
      if [ -t 0 ]; then ask how "Build or stock" "build" build stock; else how=stock; fi
    fi
    if [ "$how" = build ]; then
      build_local
      IMG="$WU_LOCAL_IMAGE"; TAG="$WU_LOCAL_TAG"
    else
      IMG="acore/ac-wotlk"; TAG="master"
      say "  Using AzerothCore's stock images: the realm runs without Leyline's modules."
    fi
  fi
  ensure_tools
}

ensure_tools() {
  [ "${LEYLINE_LOCAL_TOOLS:-0}" = 1 ] && return 0
  if [ "$WU_TOOLS_IMAGE" = "wu-host-tools:1" ]; then
    if run docker pull -q "$WU_TOOLS_PREBUILT" >/dev/null 2>&1; then
      run docker tag "$WU_TOOLS_PREBUILT" "$WU_TOOLS_IMAGE"
    elif ! docker image inspect "$WU_TOOLS_IMAGE" >/dev/null 2>&1 || [ "${WU_REBUILD_TOOLS:-0}" = 1 ]; then
      say "  Building the small helper image (once, about a minute)..."
      run docker build -q -t "$WU_TOOLS_IMAGE" "$KIT/tools" >/dev/null || die "Building the helper image failed (is this PC online?)."
    fi
  fi
}

find_wow() {
  local d
  for d in "${WU_GAME_DIR:-${WU_WOW_DIR:-}}" "$HOME/World of Warcraft 3.3.5a" "$HOME/Games/World of Warcraft 3.3.5a" \
           "$HOME/Downloads/World of Warcraft 3.3.5a" "/Applications/World of Warcraft 3.3.5a" \
           "$HOME/.wine/drive_c/World of Warcraft 3.3.5a" "$HOME/Games/wow335"; do
    [ -n "$d" ] && [ -f "$d/Data/lichking.MPQ" -o -f "$d/Data/lichking.mpq" ] && { printf '%s' "$d"; return; }
  done
  if [ -t 0 ]; then
    read -r -p "Where is your 3.3.5a game folder (the one with Data/ in it)? " d || true
    [ -f "$d/Data/lichking.MPQ" -o -f "$d/Data/lichking.mpq" ] && { printf '%s' "$d"; return; }
  fi
  return 1
}

client_data() {
  step "Game data for the server (from your own 3.3.5a install; nothing is downloaded or shared)"
  docker volume create ov-client-data >/dev/null
  if docker run --rm -v ov-client-data:/d alpine:3.20 test -d /d/dbc -a -d /d/maps >/dev/null 2>&1; then
    say "  Already extracted."
  else
    local wow
    wow="$(find_wow)" || die "No 3.3.5a game folder found. Run again with WU_GAME_DIR=/path/to/your/3.3.5a/game/folder."
    say "  Extracting dbc + maps from $wow (a few minutes)..."
    run docker run --rm --user root -v "$wow:/wow:ro" -v ov-client-data:/out -w /out "$WU_EXTRACT_IMAGE" \
      /azerothcore/env/dist/bin/map_extractor -i /wow -o /out || die "Extracting the game data failed."
  fi
  if [ "$IMG" != "acore/ac-wotlk" ] && ! docker run --rm -v ov-client-data:/d alpine:3.20 test -d /d/dbc-stock >/dev/null 2>&1; then
    say "  All-races-all-classes data (mod-arac, pinned commit)..."
    mkdir -p "$KIT/cache"
    run docker run --rm --entrypoint sh -v "$KIT/cache:/w" alpine/git:latest -c \
      "set -e; d=/w/mod-arac; [ -d \$d/.git ] || git init -q \$d; cd \$d; git remote add origin $ARAC_REPO 2>/dev/null || true; git fetch -q --depth 1 origin $ARAC_COMMIT; git checkout -q --force FETCH_HEAD" \
      && run docker run --rm -v ov-client-data:/d -v "$KIT/cache/mod-arac/patch-contents/DBFilesContent:/s:ro" alpine:3.20 sh -c \
      'mkdir -p /d/dbc-stock && for f in /s/*.dbc; do b=$(basename $f); [ -f /d/dbc-stock/$b ] || cp /d/dbc/$b /d/dbc-stock/$b; cp $f /d/dbc/$b; done' \
      || say "  ${Y}Skipped (offline?): new characters can still use the classic race/class pairs.${N}"
  fi
}

wait_ready() {  # $1 = timestamp; waits for the worldserver's "ready..."
  local i
  for i in $(seq 1 180); do
    if docker logs --since "$1" wu-host-worldserver 2>&1 | grep -F 'ready...' >/dev/null; then return 0; fi
    if (( i % 6 == 0 )); then say "  still starting ($((i / 6)) min)..."; fi
    sleep 10
  done
  return 1
}

db_sql() {  # db_sql DATABASE < file
  docker exec -i wu-host-database sh -c "MYSQL_PWD=\"\$MYSQL_ROOT_PASSWORD\" exec mysql -uroot $1"
}

profile_sql() {
  local p="$1" files f
  [ -f "$KIT/state/applied-$p" ] && return 0
  case "$p" in
    brawl) files="brawl_world.sql brawl_world_2.sql modern_combos.sql" ;;
    main|dalaran) files="main_unbrawl.sql main_world.sql modern_combos.sql" ;;
    *)     files="modern_combos.sql" ;;
  esac
  step "World changes for the $p profile (once)"
  for f in $files; do
    if [ -f "$KIT/realm-files/sql/$f" ]; then
      run db_sql acore_world < "$KIT/realm-files/sql/$f" && say "  applied $f"
    else
      say "  $f is not in this kit, skipped"
    fi
  done
  date -u +%FT%TZ > "$KIT/state/applied-$p"
  return 1   # tells the caller a restart is needed
}

cmd_up() {
  [ "${WU_CONFIG_ONLY:-0}" = 1 ] && [ "${LEYLINE_LOCAL_TOOLS:-0}" = 1 ] || need_docker
  WU_NAME="${WU_NAME:-$(state_get name)}"
  WU_PROFILE="${WU_PROFILE:-$(state_get profile)}"
  WU_VISIBILITY="${WU_VISIBILITY:-$(state_get visibility)}"
  local others; others="$(profile_list 2>/dev/null | tr '\n' ' ' || true)"
  step "Your realm"
  ask WU_NAME "Realm name" "My Wrath Realm"
  ask WU_PROFILE "Profile: main (level 1 or boost to 80), brawl (everyone 80), progression (Vanilla->TBC->Wrath), dalaran (light hangout, no bots), vanillaplus (Vanilla+: the original world to 60, always on)${others:+, or for another client: $others}" "main" main brawl progression dalaran vanillaplus $others
  profile_known "$WU_PROFILE" \
    || [ "${WU_CONFIG_ONLY:-0}" = 1 ] || [ -f "$KIT/realm-files/profiles/main.env" ] || die "This kit has no realm-files/ (run make-kit first, or download the full kit)."
  ask WU_VISIBILITY "Private (friends with your link) or public (listed in Beacons)" "private" private public
  local extra=()
  [ -n "${WU_GM_NAME:-}" ] && extra+=(--gm-name "$WU_GM_NAME")
  [ -n "${WU_TAGLINE:-}" ] && extra+=(--tagline "$WU_TAGLINE")
  [ -n "${WU_SIGNUP:-}" ] && extra+=(--signup "$WU_SIGNUP")
  [ -n "${WU_BROWSER:-}" ] && extra+=(--browser "$WU_BROWSER")               # browser players (Warden off): on | off
  [ -n "${WU_RELAY_URL:-}" ] && extra+=(--relay-url "$WU_RELAY_URL")         # a self-hosted or test relay
  [ -n "${WU_LISTING_URL:-}" ] && extra+=(--listing-url "$WU_LISTING_URL")
  [ -n "${WU_JOIN_BASE:-}" ] && extra+=(--join-base "$WU_JOIN_BASE")
  [ -n "${WU_SEED:-}" ] && [ -f "$KIT/$WU_SEED" ] && extra+=(--seed "$WU_SEED")   # a realm made on the website (used once)
  if profile_known "$WU_PROFILE"; then   # a realm for another client: its own build and start (profiles/)
    profile_up "$WU_PROFILE"; return
  fi
  if [ "${WU_CONFIG_ONLY:-0}" = 1 ]; then
    IMG="${WU_IMAGE}"; TAG="${WU_TAG}"
    ensure_tools
  else
    pick_images
  fi
  tools init --name "$WU_NAME" --profile "$WU_PROFILE" --visibility "$WU_VISIBILITY" --image "$IMG" --tag "$TAG" \
        --tools-image "$WU_TOOLS_IMAGE" --relay "$WU_RELAY" ${extra[@]+"${extra[@]}"} >/dev/null || die "Setup failed (see above)."
  if [ "${WU_CONFIG_ONLY:-0}" = 1 ]; then
    say "  Config written (state/host.json, state/rules.txt, .env). Not starting (WU_CONFIG_ONLY=1)."
    return 0
  fi
  client_data
  step "Starting the realm (the first start imports the databases: 5-20 minutes)"
  local t0; t0=$(date -u +%Y-%m-%dT%H:%M:%S)
  run "${COMPOSE[@]}" up -d || die "The realm did not start. Run: bash host-wrath-realm.sh logs"
  [ "$DRY" = 1 ] || wait_ready "$t0" || die "The world server did not get ready in 30 minutes. Run: bash host-wrath-realm.sh logs ac-worldserver"
  if ! profile_sql "$WU_PROFILE"; then
    t0=$(date -u +%Y-%m-%dT%H:%M:%S)
    run "${COMPOSE[@]}" restart ac-worldserver
    [ "$DRY" = 1 ] || wait_ready "$t0" || die "The world server did not come back after the profile change."
  fi
  step "Connecting to the relay"
  local i
  for i in $(seq 1 24); do
    grep -q '"realmlist_ok": true' "$KIT/state/relay-state.json" 2>/dev/null && break
    [ "$DRY" = 1 ] && break
    sleep 5
  done
  grep -q '"connected": true' "$KIT/state/relay-state.json" 2>/dev/null \
    && say "  ${G}Connected.${N} Your home address stays hidden behind $WU_RELAY." \
    || say "  ${Y}Not connected yet; it keeps trying. Run: bash host-wrath-realm.sh check${N}"
  step "Done"
  tools show || true
  say ""
  say "Send your friends the invite link above. They open it once, make an account there, then play with"
  say "  $(tools realmlist 2>/dev/null || echo "set realmlist $WU_RELAY")   (the join page shows the same line)"
  say "Check everything with: bash host-wrath-realm.sh check"
  if [ -n "$(state_get gm_name)" ]; then
    say "Your realm's rules: state/rules.txt (then: bash host-wrath-realm.sh rules)."
  else
    say "Your realm's rules: state/rules.txt (then: bash host-wrath-realm.sh rules). Your GM login: state/host-login.txt"
  fi
}

cmd_check() {
  need_docker
  run "${COMPOSE[@]}" run --rm --no-deps -e WU_STATE=/state wu-agent python -m wuhost.selfcheck --state /state "$@"
}

cmd_friend() {
  need_docker
  profile_known "$(state_get profile)" && die "On this realm friends make their own account on your join page (bash host-wrath-realm.sh show)."
  [ $# -ge 1 ] || die "Usage: bash host-wrath-realm.sh friend NAME [PASSWORD]"
  docker run --rm --user "$WU_UID:$WU_GID" -v "$KIT:/kit" -e WU_KIT=/kit "$WU_TOOLS_IMAGE" python -m wuhost.setup friend "$@" | db_sql acore_auth \
    && say "Done. Your friend opens your invite link once, then logs in with that account."
}

case "${1:-up}" in
  up|start|setup) shift || true; cmd_up "$@" ;;
  check) shift; cmd_check "$@" ;;
  show) need_tools; tools show ;;
  stop) need_docker; run "${COMPOSE[@]}" stop; say "Stopped. Characters and accounts are kept; start again any time." ;;
  friend) shift; cmd_friend "$@" ;;
  new-invite) need_tools; tools new-invite ;;
  public|private) need_tools; tools visibility "$1" ;;
  browser) need_tools; [ "${2:-}" = on ] || [ "${2:-}" = off ] || die "Usage: bash host-wrath-realm.sh browser on|off"; tools browser "$2" ;;
  max-players) need_tools; [[ "${2:-}" =~ ^[0-9]{1,5}$ ]] || die "Usage: bash host-wrath-realm.sh max-players N   (0 = the ruleset's own)"; tools listing --max-players "$2" ;;
  signup) need_tools; [ $# -ge 2 ] || die "Usage: bash host-wrath-realm.sh signup invite|open|off"; tools signup "$2" ;;
  herokey) need_tools; [ "${2:-}" = on ] || [ "${2:-}" = off ] || die "Usage: bash host-wrath-realm.sh herokey on|off"; tools herokey "$2" ;;
  options) need_tools; shift; tools options "$@" ;;
  rules) need_tools; tools rules ;;
  claim) need_tools; [ $# -ge 2 ] || die "Usage: bash host-wrath-realm.sh claim TOKEN"; tools claim "$2" ;;
  logs) need_docker; shift; "${COMPOSE[@]}" logs --tail 200 "$@" ;;
  -h|--help|help) sed -n '2,20p' "$0" | sed 's/^# \{0,1\}//' ;;
  *) die "Unknown command '$1'. Try: bash host-wrath-realm.sh help" ;;
esac
