#!/usr/bin/env bash
# WrathUnleashed: levelling rates for the main realm (3x XP, 2x rested, 2x reputation, 2x skill-ups).
# Sets the keys in the realm's profile (backup first), announces a 5-minute restart in game, then recreates
# the world server. Safe to run again (nothing happens if the running server already has them).
set -euo pipefail
cd /srv/wrath
die() { printf '\nRATES FAILED: %s\n' "$*" >&2; exit 1; }
PROFILE=$(grep -E '^OV_PROFILE=' .env 2>/dev/null | tail -1 | cut -d= -f2 | tr -d '\r"' || true)
[ "${PROFILE:-}" = main ] || die "the realm runs the '${PROFILE:-?}' profile, not 'main'"
PF=profiles/main.env
[ -f "$PF" ] || die "no $PF"
BK=/root/rates-backups/$(date +%Y%m%d-%H%M%S); mkdir -p "$BK"; cp -p "$PF" "$BK/profile.env"
sed -i 's/\r$//' "$PF"
KV="AC_RATE_XP_KILL=3 AC_RATE_XP_QUEST=3 AC_RATE_XP_QUEST_DF=3 AC_RATE_XP_EXPLORE=3 AC_RATE_REST_IN_GAME=2
AC_RATE_REST_OFFLINE_IN_TAVERN_OR_CITY=2 AC_RATE_REST_OFFLINE_IN_WILDERNESS=2 AC_RATE_REPUTATION_GAIN=2
AC_SKILL_GAIN_CRAFTING=2 AC_SKILL_GAIN_GATHERING=2 AC_SKILL_GAIN_WEAPON=2"
need=0
for kv in $KV; do
  k=${kv%%=*}; v=${kv#*=}
  if grep -qE "^$k=" "$PF"; then sed -i "s#^$k=.*#$k=$v#" "$PF"; else printf '%s=%s\n' "$k" "$v" >> "$PF"; fi
  [ "$(docker exec ov-ac-worldserver printenv "$k" 2>/dev/null || true)" = "$v" ] || need=1
  echo "  $k=$v"
done
if grep -E '^\s+AC_RATE_XP' docker-compose.prod.yml >/dev/null 2>&1; then echo "  WARNING: docker-compose.prod.yml sets AC_RATE_XP* itself, and that wins over $PF"; fi
if [ "$need" = 0 ]; then echo "  the running world server already has these rates"; echo "RATES OK"; exit 0; fi
MIN=${RATES_WARN_MIN:-5}
if [ "$MIN" -gt 0 ]; then
  echo "== announcing a restart in $MIN minute(s)"
  bash soap-cmd.sh "announce Server restart in $MIN minutes: new levelling rates (3x XP). Back in a few minutes." >/dev/null 2>&1 || true
  sleep $(( MIN * 60 - 60 )) || true
  bash soap-cmd.sh "announce Server restart in 1 minute." >/dev/null 2>&1 || true
  sleep 60
  bash soap-cmd.sh "saveall" >/dev/null 2>&1 || true
fi
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
[ "$ok" = 1 ] || die "the world server did not report ready in 20 min: docker logs --tail 80 ov-ac-worldserver. Old profile: $BK/profile.env"
echo "  world server ready: XP kill $(docker exec ov-ac-worldserver printenv AC_RATE_XP_KILL), quest $(docker exec ov-ac-worldserver printenv AC_RATE_XP_QUEST)"
echo "RATES OK"
