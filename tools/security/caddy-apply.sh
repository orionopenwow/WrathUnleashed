#!/usr/bin/env bash
# DRAFT (not wired to Autopilot; the main session decides): harden the LIVE Caddyfile.
#   bash caddy-apply.sh            dry run: prints the diff it would make, changes nothing
#   bash caddy-apply.sh --apply    backs up the Caddyfile, writes it in place, validates, reloads; a Caddy that
#                                  refuses it gets the old file back
# What it adds (caddyfile_harden.py): global server timeouts (read_header 10s, read_body 30s, idle 120s; no write
# timeout, so downloads and WebSockets are never cut) and request_body /wrath* { max_size 2MB } in the play site.
# Needs Caddy 2.7 or later (it clears read deadlines on upgraded WebSocket connections); older: it stops.
# After --apply: play for 3+ minutes in the browser client (a WebSocket session) and through a relay realm.
set -euo pipefail
cd "$(dirname "$0")"
CF="${WU_CADDYFILE:-/opt/openvanilla-classicplus/Caddyfile}"
CADDY_DIR="${WU_CADDY_DIR:-/opt/wenilla-realm}"
SITE="${WU_PUBLIC_HOST:-play.openvanilla.app}"
APPLY=""; [ "${1:-}" = "--apply" ] && APPLY=1
caddy() { (cd "$CADDY_DIR" && docker compose exec -T caddy caddy "$@"); }
ver=$(caddy version 2>/dev/null | awk '{print $1}' | tr -d v || true)
echo "Caddy: ${ver:-unknown}"
case "$ver" in
  2.[7-9]*|2.[1-9][0-9]*|[3-9]*) ;;
  *) echo "Caddy ${ver:-unknown} is older than 2.7 (or unknown): read_body could cut WebSockets. Stopping."; exit 1 ;;
esac
TMP=$(mktemp); trap 'rm -f "$TMP"' EXIT
python3 -I caddyfile_harden.py "$CF" "$TMP" --site "$SITE"
if cmp -s "$CF" "$TMP"; then echo "Nothing to change."; echo "CADDY APPLY OK"; exit 0; fi
diff -u "$CF" "$TMP" | sed -n '1,80p' || true
if [ -z "$APPLY" ]; then echo; echo "Dry run: nothing changed. Run with --apply to write it."; echo "CADDY APPLY DRY"; exit 0; fi
BK=/root/caddy-backups/$(date +%Y%m%d-%H%M%S); mkdir -p "$BK"; cp -p "$CF" "$BK/Caddyfile"
cat "$TMP" > "$CF"   # in place: the file is bind-mounted into the caddy container
if ! caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile >/dev/null 2>&1 || \
   ! caddy reload --config /etc/caddy/Caddyfile --adapter caddyfile; then
  cat "$BK/Caddyfile" > "$CF"; caddy reload --config /etc/caddy/Caddyfile --adapter caddyfile || true
  echo "Caddy refused it; the old Caddyfile is back ($BK/Caddyfile)."; exit 1
fi
sleep 2
code=$(curl -s -m 20 -o /dev/null -w '%{http_code}' "https://$SITE/wrath/status.json" || true)
echo "https://$SITE/wrath/status.json -> $code"
[ "$code" = 200 ] || { cat "$BK/Caddyfile" > "$CF"; caddy reload --config /etc/caddy/Caddyfile --adapter caddyfile || true; echo "The site did not answer 200; the old Caddyfile is back."; exit 1; }
echo "Applied. Backup: $BK/Caddyfile. Undo: cat $BK/Caddyfile > $CF and reload Caddy."
echo "CADDY APPLY OK"
