#!/usr/bin/env bash
# Runs ON the relay VM (called by deploy-relay.sh over its single ssh connection). Idempotent.
set -euo pipefail
SRC="${1:?source dir}"
DIR=/opt/wu-relay
[ "$(id -u)" = 0 ] || { echo "run as root" >&2; exit 1; }
if ! command -v docker >/dev/null; then
  echo "  installing Docker"
  curl -fsSL https://get.docker.com | sh >/dev/null
fi
mkdir -p "$DIR"
install -m 644 "$SRC/relay/deploy/compose.yml" "$DIR/compose.yml"
[ -f "$DIR/Caddyfile" ] || install -m 644 "$SRC/relay/deploy/Caddyfile" "$DIR/Caddyfile"
if [ ! -f "$DIR/relay.env" ]; then
  umask 077
  sed "s/^RELAY_LISTING_SITE_SECRET=.*/RELAY_LISTING_SITE_SECRET=$(openssl rand -hex 24)/" \
    "$SRC/relay/deploy/relay.env.example" > "$DIR/relay.env"
  umask 022
  echo "  wrote $DIR/relay.env (the listing site secret is in it: give it to the website's claim service)"
fi
docker build -q -f "$SRC/relay/Dockerfile" -t wu-relay:1 "$SRC" >/dev/null
if command -v ufw >/dev/null; then
  ufw allow 22/tcp >/dev/null; ufw allow 80/tcp >/dev/null; ufw allow 443/tcp >/dev/null; ufw allow 443/udp >/dev/null
  ufw allow 3724/tcp >/dev/null; ufw allow 40000:40999/tcp >/dev/null
  ufw --force enable >/dev/null
  echo "  firewall: 22, 80, 443, 3724, 40000-40999"
fi
cd "$DIR"
docker compose up -d --remove-orphans
sleep 3
curl -fsS http://127.0.0.1:8080/healthz >/dev/null && echo "  relay is up (healthz ok)" || { echo "  relay did not answer: docker compose -f $DIR/compose.yml logs relay" >&2; exit 1; }
