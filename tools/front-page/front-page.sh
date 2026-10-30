#!/usr/bin/env bash
# The Leyline front page as the site's home (owner 2026-10-30: "fix our main page to be the one we worked on in the
# preview page area"): https://play.openvanilla.app/ goes to /wrath/leyline (the hub front page) instead of /wrath
# (the game's sign-in page). "/play" still goes to /wrath. Backup first; Caddy reload; check; put back on failure.
#   bash front-page.sh on | off | check
set -euo pipefail
MODE="${1:-check}"
CF=/opt/openvanilla-classicplus/Caddyfile
[ -f "$CF" ] || { echo "FRONT FAILED: $CF not found"; exit 1; }
OLD='	redir / /wrath 302'
NEW='	redir / /wrath/leyline 302'
now=$(grep -c "^${NEW}\$" "$CF" || true)
echo "home now: $([ "$now" -ge 1 ] && echo /wrath/leyline || echo /wrath)"
if [ "$MODE" = check ]; then echo "FRONT CHECK OK"; exit 0; fi
BK=/root/front-page-backups/$(date +%Y%m%d-%H%M%S); mkdir -p "$BK"; cp -p "$CF" "$BK/Caddyfile"
if [ "$MODE" = on ]; then FROM="$OLD"; TO="$NEW"; else FROM="$NEW"; TO="$OLD"; fi
if ! grep -q "^${FROM}\$" "$CF"; then
  grep -q "^${TO}\$" "$CF" && { echo "already $MODE"; echo "FRONT OK"; exit 0; }
  echo "FRONT FAILED: the redirect line was not found in $CF (nothing changed)"; exit 1
fi
python3 - "$CF" "$FROM" "$TO" <<'PY'
import sys
p, a, b = sys.argv[1:]
s = open(p).read().replace(a + "\n", b + "\n", 1)
with open(p, "r+") as f:      # same file: it is bind-mounted into Caddy
    f.seek(0); f.write(s); f.truncate()
PY
if ! (cd /opt/wenilla-realm && docker compose exec -T caddy caddy reload --config /etc/caddy/Caddyfile --adapter caddyfile); then
  cat "$BK/Caddyfile" > "$CF"; echo "FRONT FAILED: Caddy refused it; the old Caddyfile is back"; exit 1
fi
sleep 2
loc=$(curl -s -m 20 -o /dev/null -w '%{redirect_url}' "https://play.openvanilla.app/" || true)
echo "https://play.openvanilla.app/ -> $loc"
want=$([ "$MODE" = on ] && echo /wrath/leyline || echo /wrath)
case "$loc" in
  *"$want") echo "backup: $BK"; echo "FRONT OK";;
  *) cat "$BK/Caddyfile" > "$CF"; (cd /opt/wenilla-realm && docker compose exec -T caddy caddy reload --config /etc/caddy/Caddyfile --adapter caddyfile) || true
     echo "FRONT FAILED: the home page did not go to $want (put back)"; exit 1;;
esac
