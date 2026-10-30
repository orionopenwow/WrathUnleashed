#!/usr/bin/env bash
# The Leyline Sample Hangout switch (owner 2026-10-29): turns the main realm into a temporary, lighter
# hangout to try the game, and back. Run as root on the server by "Sample hangout.bat" (one SSH login):
#
#   bash sampler.sh check <sampler.env>   read only: prints what "on" would change, and where players are
#   bash sampler.sh on    <sampler.env>   applies it: 5-minute warning in game, then the world server is recreated
#   bash sampler.sh off                   the rollback: every line back as it was, same warning and recreate
#
# What "on" changes (backups first, in /root/sampler-backups/<time>/):
#   1 profiles/main.env and modules.env: the keys of realm/profiles/sampler.env go between the markers below
#     (in modules.env when the key lives there: it is read after the profile and wins); the old lines stay as
#     "#sampler-was: KEY=value". OV_PROFILE stays main, so serverpass.sh (the realm and scripts steps) works.
#   2 acore_auth.realmlist: the name shown in the game's realm list becomes "Leyline Sample Hangout" (the old
#     name is kept in sampler-state/realm-name.txt; the login server reads it again within 20 s).
#   3 portal.env: WU_SAMPLER=1 (the play page, /wrath/realms and /wrath/leyline say "Leyline Sample Hangout,
#     temporary"), wu-portal recreated.
#   (The browser slice is separate: "Make sampler slice.bat" builds and serves slices/sampler.json; until then the
#   stream keeps serving mini and ov_slices.lua closes the capitals by itself. "off" serves mini again.)
#   4 announces a restart (SAMPLER_WARN_MIN, default 5), saves everyone, recreates the world server.
# Never touches characters: no character row is changed or deleted. Streamed players outside the new fence are
# brought home by ov_slices.lua when they log in or move (see "check").
# Last line: SAMPLER OK / SAMPLER CHECK OK, or an error (exit 1).
set -euo pipefail
WU="${WU_DIR:-/srv/wrath}"
cd "$WU"
MODE="${1:-}"; OVERLAY="${2:-}"
NAME="Leyline Sample Hangout"
BEGIN="# >>> Leyline Sample Hangout (realm/sampler.sh; 'sampler off' removes this block and restores the #sampler-was: lines)"
END="# <<< Leyline Sample Hangout"
WAS="#sampler-was: "
STATE="$WU/sampler-state"
REALM_ID="${WU_REALM_ID:-1}"
PF=profiles/main.env
MF=modules.env
die() { printf '\nSAMPLER FAILED: %s\n' "$*" >&2; exit 1; }
case "$MODE" in check|on|off) ;; *) die "usage: sampler.sh check|on <sampler.env> | off" ;; esac
PROFILE=$(grep -E '^OV_PROFILE=' .env 2>/dev/null | tail -1 | cut -d= -f2 | tr -d '\r"' || true)
[ "${PROFILE:-}" = main ] || die "the realm runs the '${PROFILE:-?}' profile, not 'main'"
[ -f "$PF" ] || die "no $PF"
[ -f "$MF" ] || die "no $MF"
sed -i 's/\r$//' "$PF" "$MF"

dbq() { docker exec -i ov-ac-database sh -c 'MYSQL_PWD="$MYSQL_ROOT_PASSWORD" exec mysql -uroot -N -B' <<<"$1"; }
live() { docker exec ov-ac-worldserver printenv "$1" 2>/dev/null || true; }
has_block() { grep -qxF "$END" "$1"; }

# The overlay's KEY=value lines, checked: keys are AC_/OV_ names, values plain (they go into sed and env files).
KV=()
if [ "$MODE" != off ]; then
  [ -f "$OVERLAY" ] || die "no overlay file ($OVERLAY): send realm/profiles/sampler.env"
  while IFS= read -r line; do
    line=${line%$'\r'}
    case "$line" in ''|'#'*) continue ;; esac
    [[ "$line" =~ ^(AC|OV)_[A-Z0-9_]+=[A-Za-z0-9.,_-]*$ ]] || die "overlay line not accepted: $line"
    KV+=("$line")
  done < "$OVERLAY"
  [ "${#KV[@]}" -gt 0 ] || die "the overlay has no settings"
  printf '%s\n' "${KV[@]}" | grep -qx 'OV_SAMPLER=1' || die "the overlay must set OV_SAMPLER=1"
fi
# Which file a key goes in: modules.env when it already sets the key (live or as a #sampler-was: line).
target() { if grep -qE "^(${WAS})?$1=" "$MF"; then echo "$MF"; else echo "$PF"; fi; }

undo_file() {  # remove our block, bring back the commented lines
  local f=$1
  python3 -I - "$f" "$BEGIN" "$END" "$WAS" <<'PY'
import sys
p, b, e, was = sys.argv[1:5]
out, skip = [], False
for line in open(p).read().splitlines():
    if line == b: skip = True; continue
    if line == e: skip = False; continue
    if skip: continue
    out.append(line[len(was):] if line.startswith(was) else line)
open(p, "w").write("\n".join(out) + "\n")
PY
}

apply_file() {  # f, then KEY=value lines for f
  local f=$1; shift
  [ "$#" -gt 0 ] || return 0
  local kv k
  for kv in "$@"; do k=${kv%%=*}; sed -i "s|^$k=|${WAS}$k=|" "$f"; done
  { echo "$BEGIN"; printf '%s\n' "$@"; echo "$END"; } >> "$f"
}

# ---------------------------------------------------------------------------------------------- check
report() {
  echo "== settings (profile '$PROFILE'; the world server reads them when it is recreated)"
  local kv k v f old now
  if [ "$MODE" = off ]; then
    for f in "$PF" "$MF"; do
      has_block "$f" || continue
      sed -n "/^# >>> Leyline Sample Hangout/,/^# <<< Leyline Sample Hangout/p" "$f" | grep -E '^(AC|OV)_' | while IFS= read -r kv; do
        k=${kv%%=*}; old=$(grep -E "^${WAS}$k=" "$f" | head -1 | sed "s#^${WAS}$k=##" || true)
        printf '  %-48s %s -> %s  (%s)\n' "$k" "${kv#*=}" "${old:-<unset: the default>}" "$f"
      done
    done
    return
  fi
  for kv in "${KV[@]}"; do
    k=${kv%%=*}; v=${kv#*=}; f=$(target "$k")
    old=$(grep -E "^($WAS)?$k=" "$f" | grep -v "^$WAS" | tail -1 | cut -d= -f2- || true)
    [ -n "$old" ] || old=$(grep -E "^${WAS}$k=" "$f" | head -1 | sed "s#^${WAS}$k=##" || true)
    now=$(live "$k")
    printf '  %-48s %s -> %s  (%s; live now: %s)\n' "$k" "${old:-<unset>}" "$v" "$f" "${now:-<unset>}"
  done
}

where_players() {
  echo "== players (characters database; bots are left out)"
  local q
  q="SELECT COUNT(*) FROM acore_characters.characters c WHERE c.online = 1
     AND c.account NOT IN (SELECT id FROM acore_auth.account WHERE username LIKE 'RNDBOT%')"
  echo "  online now: $(dbq "$q" 2>/dev/null || echo '?')"
  # Streamed accounts (the only ones fenced): where their characters stand, and what the fence does there.
  q="SELECT CASE
       WHEN c.map = 571 AND c.zone = 4395 THEN 'Dalaran: stays'
       WHEN c.map = 609 THEN 'Ebon Hold: stays (Death Knights)'
       WHEN c.map IN (0,1) AND c.level < 10 THEN 'open world, below 10: own starting area if outside it'
       WHEN c.map IN (0,1,530,571) THEN 'open world: brought to Dalaran (below 10: starting area) at login'
       ELSE 'instance, arena or battleground: stays if streamed, else Dalaran' END AS w, COUNT(*)
     FROM acore_characters.characters c JOIN acore_auth.ov_stream_accounts s ON s.account_id = c.account
     WHERE s.expires_at > UNIX_TIMESTAMP() GROUP BY w ORDER BY w"
  local rows; rows=$(dbq "$q" 2>/dev/null || true)
  if [ -n "$rows" ]; then echo "  streamed accounts' characters:"; printf '%s\n' "$rows" | sed 's/^/    /;s/\t/: /'
  else echo "  no streamed account is marked now (own-files and desktop players keep the whole world)"; fi
}

current_name() { dbq "SELECT name FROM acore_auth.realmlist WHERE id = $REALM_ID" 2>/dev/null || true; }

if [ "$MODE" = check ]; then
  echo "SAMPLER CHECK (nothing is changed)"
  for f in "$PF" "$MF"; do has_block "$f" && echo "  NOTE: $f already has the Sample Hangout block: 'on' replaces it"; done
  report
  echo "== realm list name: '$(current_name)' -> '$NAME'"
  echo "== portal.env: WU_SAMPLER=$(grep -E '^WU_SAMPLER=' portal.env 2>/dev/null | cut -d= -f2 || true) -> 1 (wu-portal recreated)"
  echo "== stream: STREAM_SLICES=$(grep -E '^STREAM_SLICES=' portal.env 2>/dev/null | cut -d= -f2 || true), wu-play serves $(docker inspect -f '{{range .Mounts}}{{if eq .Destination "/slice"}}{{.Source}}{{end}}{{end}}' wu-play 2>/dev/null || echo '(not running)')"
  where_players
  echo "== memory now"
  docker stats --no-stream --format '  {{.Name}} {{.MemUsage}} cpu {{.CPUPerc}}' ov-ac-worldserver ov-ac-database 2>/dev/null || true
  free -m | sed -n 2p | awk '{print "  host: " $3 " MB used of " $2 " MB"}'
  echo "== 'on' would announce a ${SAMPLER_WARN_MIN:-5}-minute restart and recreate the world server"
  echo "SAMPLER CHECK OK"
  exit 0
fi

# ---------------------------------------------------------------------------------------------- on / off
BK=/root/sampler-backups/$(date +%Y%m%d-%H%M%S); mkdir -p "$BK" "$STATE"
cp -p "$PF" "$BK/main.env"; cp -p "$MF" "$BK/modules.env"; [ -f portal.env ] && cp -p portal.env "$BK/portal.env"
report
undo_file "$PF"; undo_file "$MF"
if [ "$MODE" = on ]; then
  P=(); M=()
  for kv in "${KV[@]}"; do if [ "$(target "${kv%%=*}")" = "$MF" ]; then M+=("$kv"); else P+=("$kv"); fi; done
  apply_file "$PF" "${P[@]}"
  apply_file "$MF" "${M[@]+"${M[@]}"}"
  NEWNAME="$NAME"; SAMPLER=1
  old=$(current_name)
  [ -n "$old" ] && [ "$old" != "$NAME" ] && printf '%s\n' "$old" > "$STATE/realm-name.txt"
else
  NEWNAME=$(cat "$STATE/realm-name.txt" 2>/dev/null || echo WrathUnleashed); SAMPLER=0
fi
[[ "$NEWNAME" =~ ^[A-Za-z0-9\ _-]{1,32}$ ]] || NEWNAME=WrathUnleashed

MIN=${SAMPLER_WARN_MIN:-5}
WHAT=$([ "$MODE" = on ] && echo "the Leyline Sample Hangout opens" || echo "the full realm is back")
if [ "$MIN" -gt 0 ]; then
  echo "== announcing a restart in $MIN minute(s)"
  bash soap-cmd.sh "announce Server restart in $MIN minutes: $WHAT. Your characters are kept. Back in a few minutes." >/dev/null 2>&1 || true
  sleep $(( MIN * 60 - 60 )) || true
  bash soap-cmd.sh "announce Server restart in 1 minute." >/dev/null 2>&1 || true
  sleep 60
fi
bash soap-cmd.sh "saveall" >/dev/null 2>&1 || true
echo "== recreating the world server (2-10 minutes)"
started() { docker inspect -f '{{.State.StartedAt}}' ov-ac-worldserver; }
before=$(started 2>/dev/null || true)
docker compose up -d --no-deps ac-worldserver
sleep 3
[ "$(started)" != "$before" ] || docker restart ov-ac-worldserver >/dev/null
ok=0
for i in $(seq 1 120); do
  if docker logs --since "$(started)" ov-ac-worldserver 2>&1 | grep -F 'ready...' >/dev/null; then ok=1; break; fi
  if (( i % 6 == 0 )); then echo "  still starting ($((i * 10 / 60)) min)..."; fi
  sleep 10
done
[ "$ok" = 1 ] || die "the world server did not report ready in 20 min: docker logs --tail 80 ov-ac-worldserver. Old files: $BK (sampler.sh off puts the lines back)"
[ "$(live OV_SAMPLER)" = "$([ "$MODE" = on ] && echo 1 || true)" ] || die "the world server's OV_SAMPLER is '$(live OV_SAMPLER)': the compose file did not pick up the profile"
echo "  world server ready (OV_SAMPLER=$(live OV_SAMPLER))"

echo "== realm list name -> '$NEWNAME'"
dbq "UPDATE acore_auth.realmlist SET name = '$NEWNAME' WHERE id = $REALM_ID" || echo "  NOTE: could not rename the realm (the rest is done)"
if [ -f portal.env ]; then
  echo "== portal: WU_SAMPLER=$SAMPLER"
  if grep -q '^WU_SAMPLER=' portal.env; then sed -i "s#^WU_SAMPLER=.*#WU_SAMPLER=$SAMPLER#" portal.env; else echo "WU_SAMPLER=$SAMPLER" >> portal.env; fi
  if [ -f "$WU/stream/stream-lib.sh" ]; then
    # shellcheck disable=SC1091
    ( . "$WU/stream/stream-lib.sh"; recreate_portal ) && echo "  wu-portal recreated" \
      || echo "  NOTE: wu-portal did not come back: docker logs wu-portal (cp $BK/portal.env portal.env to undo)"
  else
    echo "  NOTE: no stream/stream-lib.sh: recreate wu-portal by hand to show the new labels"
  fi
fi
# Off: the browser stream goes back to the full mini slice when it serves the sampler one (slice-serve.sh).
if [ "$MODE" = off ] && grep -qxE 'STREAM_SLICES=sampler' portal.env 2>/dev/null; then
  if [ -f "$WU/stream/slice-serve.sh" ] && [ -d "$WU/stream/slices/mini" ]; then
    echo "== browser stream: back to the mini slice"
    bash "$WU/stream/slice-serve.sh" mini || echo "  NOTE: the stream still serves the sampler slice: bash $WU/stream/slice-serve.sh mini"
  else
    echo "  NOTE: the stream serves the sampler slice and slices/mini is gone: rebuild it (the slice step), then slice-serve.sh mini"
  fi
fi
sleep 60
docker stats --no-stream --format '  {{.Name}} {{.MemUsage}} cpu {{.CPUPerc}}' ov-ac-worldserver ov-ac-database 2>/dev/null || true
echo "  backups: $BK"
echo "SAMPLER OK"
