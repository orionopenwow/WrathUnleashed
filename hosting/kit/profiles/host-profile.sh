# Host any client: the host kit's realm profiles on other server cores, Mac and Linux (profiles/<id>/, listed in
# tools/wuhost/cores.py). Sourced by host-wrath-realm.sh when WU_PROFILE names a folder here with a profile.lock
# (it uses that script's say/step/die/run/tools helpers and its `extra` setup arguments); `leyline host` and the
# launcher's Host page reach it the same way. Windows: "Host a profile realm.bat" next to this file.
#
#   1. builds three images on this PC from the core's source at the commits in profile.lock (once);
#   2. writes the realm's config (state/, .env) like every profile;
#   3. makes the server data from YOUR OWN client of that build (read-only; nothing is downloaded or shared);
#   4. starts it (profiles/<id>/docker-compose.<id>.yml): the database import, the login and world servers, the agent.
#
# Environment: WU_CLIENT_DIR (your game folder of that build; the launcher fills it in), LL_THREADS (CPU threads
# for the monster paths), LL_MMAPS=0 (skip them), LL_JOBS (compile jobs), LL_REBUILD=1 (build the images again).

profile_dir() { printf '%s' "$KIT/profiles/$1"; }

# The newest client build the kit offers (tools/wuhost/cores.py MAX_OFFERED_BUILD). Hidden by the owner on
# 2026-10-30: tcpp-4.3.4 keeps its files but is not offered. Set this back to 18414 (or LEYLINE_ALL_CLIENTS=1)
# to offer it again.
LL_MAX_OFFERED_BUILD=12340

profile_offered() {  # $1 = id: its client build is offered now (the lock's LL_BUILD), or the override is on
  case "${LEYLINE_ALL_CLIENTS:-}" in 1|true|yes|on) return 0 ;; esac
  local b
  b="$(sed 's/\r$//' "$KIT/profiles/$1/profile.lock" 2>/dev/null | grep -E '^LL_BUILD=[0-9]+$' | head -n 1 | cut -d= -f2)"
  [ -n "$b" ] && [ "$b" -le "$LL_MAX_OFFERED_BUILD" ]
}

profile_known() {  # a profile folder of this kit (letters, digits, dots and dashes only: never a path)
  [[ "$1" =~ ^[a-z0-9][a-z0-9.-]{1,31}$ ]] && [ -f "$KIT/profiles/$1/profile.lock" ]
}

profile_list() {  # the profile ids of this kit that are offered now, one per line
  local d id
  for d in "$KIT"/profiles/*/profile.lock; do
    [ -f "$d" ] || continue
    id="$(basename "$(dirname "$d")")"
    profile_offered "$id" && printf '%s\n' "$id"
  done
  return 0
}

profile_lock() {  # $1 = id: the pinned sources as LL_* shell variables (KEY=VALUE lines only; nothing in the file is run)
  local k v f
  f="$(profile_dir "$1")/profile.lock"
  [ -f "$f" ] || die "This kit has no profiles/$1/ (download the full kit again)."
  while IFS='=' read -r k v; do
    case "$k" in LL_[A-Z0-9_]*) printf -v "$k" '%s' "$v" ;; esac
  done < <(sed 's/\r$//' "$f" | grep -E '^LL_[A-Z0-9_]+=.+$')
  [ "${LL_PROFILE:-}" = "$1" ] || die "profiles/$1/profile.lock is damaged (download the full kit again)."
  profile_offered "$1" || die "The ${LL_VERSION:-$1} client is not offered yet: Leyline hosts 1.12.1, 2.4.3 and 3.3.5a realms for now. Pick another profile."
  [[ "${LL_CORE_COMMIT:-}" =~ ^[0-9a-f]{40}$ ]] || die "profiles/$1/profile.lock is damaged (download the full kit again)."
  if [ -n "${LL_DB_COMMIT:-}" ]; then
    [[ "$LL_DB_COMMIT" =~ ^[0-9a-f]{40}$ ]] || die "profiles/$1/profile.lock is damaged (download the full kit again)."
  elif ! [[ "${LL_DB_SHA256:-}" =~ ^[0-9a-f]{64}$ ]]; then
    die "The $LL_VERSION profile is not ready yet: its database file has no pinned checksum (profiles/$1/profile.lock). Pick another profile."
  fi
  LL_TAG="${LL_VERSION}-${LL_CORE_COMMIT:0:12}"
}

profile_build_args() {  # the lock's values the Dockerfile reads, as --build-arg pairs (one per line)
  local k
  for k in LL_PROFILE LL_BUILD LL_EXPANSION LL_CORE_REPO LL_CORE_COMMIT LL_DB_REPO LL_DB_COMMIT LL_DB_URL LL_DB_SHA256 \
           LL_DB_FILES; do
    [ -n "${!k:-}" ] && printf -- '--build-arg\n%s=%s\n' "$k" "${!k}"
  done
  return 0
}

profile_jobs() {  # compile jobs: one per CPU, at most one per 2 GB of the memory Docker has
  local cpus mem jobs
  cpus="$(getconf _NPROCESSORS_ONLN 2>/dev/null || sysctl -n hw.ncpu 2>/dev/null || echo 2)"
  mem="$(docker info --format '{{.MemTotal}}' 2>/dev/null || echo 4294967296)"
  [[ "$mem" =~ ^[0-9]+$ ]] || mem=4294967296
  jobs=$(( mem / 2147483648 )); (( jobs < cpus )) || jobs=$cpus; (( jobs >= 1 )) || jobs=1
  printf '%s' "${LL_JOBS:-$jobs}"
}

profile_build() {
  step "The $LL_VERSION server: building it on this PC from its authors' source"
  local t missing=() args dir
  dir="$(profile_dir "$LL_PROFILE")"
  for t in server extractors db-import; do
    if [ "${LL_REBUILD:-0}" = 1 ] || ! docker image inspect "$LL_IMAGE-$t:$LL_TAG" >/dev/null 2>&1; then missing+=("$t"); fi
  done
  if [ ${#missing[@]} -eq 0 ]; then say "  Already built ($LL_IMAGE-*:$LL_TAG)."; return 0; fi
  mapfile -t args < <(profile_build_args)
  say "  Server: $LL_CORE_REPO at ${LL_CORE_COMMIT:0:12} (credits and licences: profiles/$LL_PROFILE/NOTICE.md)."
  say "  The first build takes ${LL_BUILD_TIME:-an hour or two}, only once. Finished parts are kept."
  for t in "${missing[@]}"; do
    say "  [$t]"
    run docker build --target "$t" --build-arg "JOBS=$(profile_jobs)" "${args[@]}" \
      -f "$dir/Dockerfile" -t "$LL_IMAGE-$t:$LL_TAG" "$dir" \
      || die "The build failed (see the first 'error' above). Run this again: finished parts are kept."
  done
  say "  ${G}Built.${N}"
}

profile_is_client() {  # $1 = folder: has every file profile.lock names (either case)
  local f
  [ -n "$1" ] && [ -d "$1" ] || return 1
  for f in ${LL_CLIENT_FILES//,/ }; do
    [ -f "$1/$f" ] || [ -f "$1/${f%/*}/$(printf '%s' "${f##*/}" | tr 'A-Z' 'a-z')" ] || return 1
  done
}

profile_find_client() {
  local d
  for d in "${WU_CLIENT_DIR:-}" "$HOME/Games/$LL_VERSION" "$HOME/$LL_VERSION" "$HOME/Games/client-$LL_VERSION" \
           "$HOME/.wine/drive_c/Games/$LL_VERSION"; do
    profile_is_client "$d" && { printf '%s' "$d"; return; }
  done
  if [ -t 0 ] && [ "${LEYLINE_NONINTERACTIVE:-0}" != 1 ]; then
    read -r -p "Where is your $LL_VERSION game folder (the one with Data/ in it)? " d || true
    profile_is_client "$d" && { printf '%s' "$d"; return; }
  fi
  return 1
}

profile_volume() { printf 'leyline-%s-client-data' "${LL_IMAGE#leyline-}"; }

profile_client_data() {
  step "Server data from your own $LL_VERSION client (nothing is downloaded or shared)"
  local vol; vol="$(profile_volume)"
  run docker volume create "$vol" >/dev/null
  if docker run --rm -v "$vol:/d" alpine:3.20 test -f /d/.ready >/dev/null 2>&1; then
    say "  Already made."; return 0
  fi
  local client
  client="$(profile_find_client)" || die "No $LL_VERSION game folder found. Run again with WU_CLIENT_DIR=/path/to/your/$LL_VERSION/game/folder."
  say "  Reading $client (read-only). This takes ${LL_EXTRACT_TIME:-an hour or more} (LL_MMAPS=0 skips the monster paths)."
  run docker run --rm -v "$client:/client:ro" -v "$vol:/data" -e LL_THREADS -e LL_MMAPS -e "LL_CLIENT_FILES=$LL_CLIENT_FILES" \
    "$LL_IMAGE-extractors:$LL_TAG" || die "Making the server data failed (see above). Run this again: finished parts are kept."
}

profile_wait_ready() {  # $1 = timestamp; the world server logs LL_READY when it takes players
  local i
  for i in $(seq 1 180); do
    if docker logs --since "$1" wu-host-realm-world 2>&1 | grep -F "$LL_READY" >/dev/null; then return 0; fi
    if (( i % 6 == 0 )); then say "  still starting ($((i / 6)) min)..."; fi
    sleep 10
  done
  return 1
}

profile_compose() { printf '%s' "$(profile_dir "$LL_PROFILE")/$LL_COMPOSE"; }

profile_up() {  # $1 = the profile id
  profile_lock "$1"
  if [ "${WU_CONFIG_ONLY:-0}" = 1 ]; then
    ensure_tools
  else
    need_docker
    ensure_tools
    profile_build
  fi
  tools init --name "$WU_NAME" --profile "$LL_PROFILE" --visibility "$WU_VISIBILITY" --image "$LL_IMAGE" --tag "$LL_TAG" \
        --tools-image "$WU_TOOLS_IMAGE" --relay "$WU_RELAY" ${extra[@]+"${extra[@]}"} >/dev/null || die "Setup failed (see above)."
  if [ "${WU_CONFIG_ONLY:-0}" = 1 ]; then
    say "  Config written (state/host.json, state/rules.txt, .env). Not starting (WU_CONFIG_ONLY=1)."
    return 0
  fi
  profile_client_data
  step "Starting the $LL_VERSION realm (the first start loads the world database: 5-20 minutes)"
  local t0; t0=$(date -u +%Y-%m-%dT%H:%M:%S)
  # --remove-orphans: this kit folder's other realm containers stop if it hosted another profile before (data stays)
  run docker compose -f "$(profile_compose)" --project-directory "$KIT" up -d --remove-orphans \
    || die "The realm did not start. Run: bash host-wrath-realm.sh logs"
  [ "$DRY" = 1 ] || profile_wait_ready "$t0" || die "The world server did not get ready in 30 minutes. Run: bash host-wrath-realm.sh logs realm-world"
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
  say "Players need their own $LL_VERSION client. They open your invite link once, make an account there, then play with"
  say "  $(tools realmlist 2>/dev/null || echo "set realmlist $WU_RELAY")   (the join page says where this client keeps that line)"
  say "Check everything with: bash host-wrath-realm.sh check. Credits and licences: profiles/$LL_PROFILE/NOTICE.md"
}
