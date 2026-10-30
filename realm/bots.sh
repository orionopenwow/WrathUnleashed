#!/usr/bin/env bash
# Leyline: how many roaming bots the Dalaran Hangout runs (owner 2026-10-30: "remove the 30 bots from the Dalaran Hangout
# for now"). Usage on the server, in /srv/wrath:
#   bash bots.sh 0          no roaming bots (remembers the count it had)
#   bash bots.sh back       the count from before the last "bots.sh 0"
#   bash bots.sh <n>        any count, 0 to 200
# Sets AC_PLAYERBOTS_MIN_RANDOM_BOTS and _MAX_ in every env file the world server reads that has them (the profile,
# modules.env: modules.env is read last, so it wins; with neither, modules.env gets them), backup first, then a
# 5-minute warning in game (BOTS_WARN_MIN=0: none), saveall, the world server recreated and checked: it reports ready
# and runs with the new count. Nothing changes and nothing restarts when the server already has that count.
set -euo pipefail
cd /srv/wrath
die() { printf '\nBOTS FAILED: %s\n' "$*" >&2; exit 1; }
WANT=${1:-}
KEEP=/srv/wrath/.bots-before
live() { docker exec ov-ac-worldserver printenv "$1" 2>/dev/null || true; }
if [ "$WANT" = back ]; then
  [ -f "$KEEP" ] || die "no count saved: nothing was turned off with bots.sh 0"
  WANT=$(tr -dc 0-9 < "$KEEP")
fi
[[ "$WANT" =~ ^[0-9]+$ ]] && [ "$WANT" -le 200 ] || die "give a number of bots from 0 to 200, or 'back'"
PROFILE=$(grep -E '^OV_PROFILE=' .env 2>/dev/null | tail -1 | cut -d= -f2 | tr -d '\r"' || true)
PF=profiles/${PROFILE:-brawl}.env
MF=modules.env
[ -f "$PF" ] || die "no $PF (the realm's profile)"
NOW=$(live AC_PLAYERBOTS_MAX_RANDOM_BOTS)
echo "== roaming bots: ${NOW:-<unset>} now, $WANT wanted (profile '$PROFILE')"
if [ "$NOW" = "$WANT" ] && [ "$(live AC_PLAYERBOTS_MIN_RANDOM_BOTS)" = "$WANT" ]; then
  echo "  the world server already runs $WANT"; echo "BOTS OK"; exit 0
fi
[ "$WANT" = 0 ] && [ -n "$NOW" ] && [ "$NOW" != 0 ] && echo "$NOW" > "$KEEP"
BK=/root/bots-backups/$(date +%Y%m%d-%H%M%S); mkdir -p "$BK"
files=()
for f in "$PF" "$MF"; do
  [ -f "$f" ] || continue
  cp -p "$f" "$BK/$(basename "$f")"; sed -i 's/\r$//' "$f"
  grep -qE '^AC_PLAYERBOTS_(MIN|MAX)_RANDOM_BOTS=' "$f" && files+=("$f")
done
[ ${#files[@]} -gt 0 ] || { [ -f "$MF" ] && files=("$MF") || files=("$PF"); }
for f in "${files[@]}"; do
  for k in AC_PLAYERBOTS_MIN_RANDOM_BOTS AC_PLAYERBOTS_MAX_RANDOM_BOTS; do
    if grep -qE "^$k=" "$f"; then sed -i "s#^$k=.*#$k=$WANT#" "$f"; else printf '%s=%s\n' "$k" "$WANT" >> "$f"; fi
  done
  echo "  $f: AC_PLAYERBOTS_MIN_RANDOM_BOTS=$WANT, AC_PLAYERBOTS_MAX_RANDOM_BOTS=$WANT"
done
echo "  backup: $BK"
MIN=${BOTS_WARN_MIN:-5}
if [ "$MIN" -gt 0 ]; then
  echo "== announcing a restart in $MIN minute(s)"
  bash soap-cmd.sh "announce Server restart in $MIN minutes. Back in a few minutes." >/dev/null 2>&1 || true
  [ "$MIN" -gt 1 ] && sleep $(( MIN * 60 - 60 ))
  bash soap-cmd.sh "announce Server restart in 1 minute." >/dev/null 2>&1 || true
  sleep 60
fi
bash soap-cmd.sh "saveall" >/dev/null 2>&1 || true
echo "== recreating the world server (2-10 minutes)"
started() { docker inspect -f '{{.State.StartedAt}}' ov-ac-worldserver; }
docker compose up -d --no-deps ac-worldserver
sleep 3
ok=0
for i in $(seq 1 120); do
  if docker logs --since "$(started)" ov-ac-worldserver 2>&1 | grep -F 'ready...' >/dev/null; then ok=1; break; fi
  if (( i % 6 == 0 )); then echo "  still starting ($((i * 10 / 60)) min)..."; fi
  sleep 10
done
if [ "$ok" != 1 ]; then
  echo "  the world server did not report ready in 20 minutes: putting the old files back"
  for f in "$PF" "$MF"; do [ -f "$BK/$(basename "$f")" ] && cp -p "$BK/$(basename "$f")" "$f"; done
  docker compose up -d --no-deps ac-worldserver || true
  die "rolled back to $BK; docker logs --tail 80 ov-ac-worldserver"
fi
[ "$(live AC_PLAYERBOTS_MAX_RANDOM_BOTS)" = "$WANT" ] || die "the world server came back with $(live AC_PLAYERBOTS_MAX_RANDOM_BOTS) bots, not $WANT (another env file wins?)"
echo "  world server ready with $WANT roaming bots"
echo "BOTS OK"
