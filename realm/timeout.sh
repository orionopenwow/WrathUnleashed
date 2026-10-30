#!/usr/bin/env bash
# WrathUnleashed: a slow browser load must not get the player kicked. AzerothCore drops an in-world
# session that sends nothing for SocketTimeOutTimeActive (default 60 s); the browser client's first
# world load can take longer than that until the faster client ships. This raises it to 10 minutes in
# the realm's profile and recreates the world server. Players online are disconnected for the restart.
# Safe to run again. Backup of the profile in /root/timeout-backups/<time>.
set -euo pipefail
cd /srv/wrath
die() { printf '\nTIMEOUT FAILED: %s\n' "$*" >&2; exit 1; }
PROFILE=$(grep -E '^OV_PROFILE=' .env 2>/dev/null | tail -1 | cut -d= -f2 | tr -d '\r"' || true)
PROFILE=${PROFILE:-brawl}
PF=profiles/$PROFILE.env
[ -f "$PF" ] || die "no $PF"
BK=/root/timeout-backups/$(date +%Y%m%d-%H%M%S); mkdir -p "$BK"; cp -p "$PF" "$BK/profile.env"
sed -i 's/\r$//' "$PF"
K=AC_SOCKET_TIME_OUT_TIME_ACTIVE V=600000
if grep -qE "^$K=$V\$" "$PF"; then echo "  $K=$V (already)"; changed=0
else
  if grep -qE "^$K=" "$PF"; then sed -i "s#^$K=.*#$K=$V#" "$PF"; else printf '%s=%s\n' "$K" "$V" >> "$PF"; fi
  echo "  $K=$V (set in $PF)"; changed=1
fi
running=$(docker exec ov-ac-worldserver printenv $K 2>/dev/null || true)
if [ "$running" = "$V" ]; then echo "  the running world server already has it"; echo "TIMEOUT OK"; exit 0; fi
echo "== recreating the world server (players online are disconnected; 2-10 minutes)"
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
echo "  world server ready; it runs with $K=$(docker exec ov-ac-worldserver printenv $K)"
docker logs --since "$(started)" ov-ac-worldserver 2>&1 | grep -F 'SocketTimeOutTimeActive' | tail -1 || true
echo "TIMEOUT OK"
