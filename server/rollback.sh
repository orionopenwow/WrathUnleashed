#!/usr/bin/env bash
# Undo deploy.sh: stop the Wrath realm and start the vanilla game servers again.
# Wrath's databases stay on disk (docker volume ov-wotlk_ac-database), so deploy can run again.
# Players whose web account was first made while Wrath ran have no vanilla game account yet;
# that needs an admin fix-up later (their game_accounts row points at a name vanilla doesn't have).
set -uo pipefail
cd /srv/wrath
warn() { echo "!! $*" >&2; }
# the Wrath sign-in page and SOAP bridge go first, so "mangosd" means the vanilla server again
docker rm -f wu-portal >/dev/null 2>&1 || true
if [ -f Caddyfile.before-wrath ]; then
  CF=/opt/openvanilla-classicplus/Caddyfile
  cat Caddyfile.before-wrath > "$CF"   # same file: it is bind-mounted into Caddy
  (cd /opt/wenilla-realm && docker compose exec -T caddy caddy reload --config /etc/caddy/Caddyfile --adapter caddyfile) || warn "Caddy reload failed"
  mv Caddyfile.before-wrath "Caddyfile.restored-$(date +%Y%m%d-%H%M%S)"
fi
docker compose stop || warn "stopping Wrath failed"
if [ -f realm.env.before-wrath ]; then
  cp -p realm.env.before-wrath /opt/wenilla-realm/.env && mv realm.env.before-wrath "realm.env.restored-$(date +%Y%m%d-%H%M%S)"
  (cd /opt/wenilla-realm && docker compose up -d --no-deps realm) || warn "restarting the website service failed"
fi
[ -f stopped-vanilla.txt ] || { warn "no stopped-vanilla.txt: nothing to start"; exit 1; }
while read -r line; do
  case "$line" in
    duels) (cd /opt/wenilla-duels && docker compose start) || warn "duels did not start" ;;
    realm:*) (cd /opt/wenilla-realm && docker compose start ${line#realm:}) || warn "${line#realm:} did not start" ;;
    unit:*) systemctl start "${line#unit:}" || warn "${line#unit:} did not start" ;;
    policy:*) rest=${line#policy:}; docker update --restart="${rest##*:}" "${rest%:*}" >/dev/null || warn "restart policy of ${rest%:*} not restored" ;;
  esac
done < stopped-vanilla.txt
mv stopped-vanilla.txt "stopped-vanilla.restored-$(date +%Y%m%d-%H%M%S)"
docker ps --format '{{.Names}}\t{{.Status}}'
echo "Vanilla is back."
