#!/usr/bin/env bash
# Read-only: prints the LIVE Caddyfile and the compose files (secrets redacted by redact.py) plus what is
# listening, so they can be reviewed on the PC ("Caddy check.bat" saves this output to tools\security\live\).
# The live Caddyfile (/opt/openvanilla-classicplus/Caddyfile) is not in git. Changes nothing. Safe to run any time.
set -uo pipefail
cd "$(dirname "$0")" || exit 1
CF="${WU_CADDYFILE:-/opt/openvanilla-classicplus/Caddyfile}"
CADDY_DIR="${WU_CADDY_DIR:-/opt/wenilla-realm}"
ROOTS="${WU_COMPOSE_ROOTS:-/opt /srv/wrath}"
echo "# caddy-check $(date -u +%Y-%m-%dT%H:%M:%SZ) on $(hostname)"
echo "# secrets are replaced by <redacted>; .env files are listed by name only, never printed"
echo
echo "## Caddy version"
(cd "$CADDY_DIR" 2>/dev/null && docker compose exec -T caddy caddy version 2>/dev/null) || echo "(caddy container not reachable from $CADDY_DIR)"
echo
echo "## The live Caddyfile"
python3 -I redact.py "$CF"
echo
echo "## Compose files"
mapfile -t files < <(find $ROOTS -maxdepth 3 \( -name 'docker-compose*.yml' -o -name 'docker-compose*.yaml' -o -name 'compose*.yml' -o -name 'compose*.yaml' \) -type f 2>/dev/null | sort)
if [ "${#files[@]}" -gt 0 ]; then python3 -I redact.py "${files[@]}"; else echo "(none under $ROOTS)"; fi
echo
echo "## .env files (names only)"
find $ROOTS -maxdepth 3 -type f \( -name '*.env' -o -name '.env' \) 2>/dev/null | sort
echo
echo "## Published ports (docker)"
docker ps --format '{{.Names}}\t{{.Image}}\t{{.Ports}}' 2>/dev/null || echo "(docker not reachable)"
echo
echo "## Listening sockets"
ss -ltnup 2>/dev/null | awk '{print $1, $5, $7}' | sort -u || true
echo
echo "## Firewall (DOCKER-USER chain, ufw)"
iptables -S DOCKER-USER 2>/dev/null || echo "(no DOCKER-USER chain)"
ufw status 2>/dev/null | head -30 || true
echo
echo "## fail2ban jails"
fail2ban-client status 2>/dev/null || echo "(fail2ban not running)"
echo
echo "CADDY CHECK OK"
