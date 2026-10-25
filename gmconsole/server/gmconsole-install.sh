#!/usr/bin/env bash
# WrathUnleashed GM console: install or update it on the server. Run as root with the uploaded kit:
#   bash gmconsole-install.sh <kit dir>        ("Install GM Console.bat": one SSH, tar on stdin)
# Idempotent: a second run replaces the app (the previous one is backed up) and keeps the token.
#
#   * the app goes to /srv/wrath/gmconsole (backup of the previous one in /srv/wrath/gmconsole-backups)
#   * the token: /srv/wrath/gmconsole.env (GM_TOKEN=..., chmod 600), made once, never printed
#   * the image wu-gmconsole:1 = python:3.12-alpine + bash, curl, docker CLI and compose (the server's
#     own scripts run unchanged inside it: soap-cmd.sh, stream-switch.sh, stream-lib.sh)
#   * the container wu-gmconsole: host network, listening on 127.0.0.1:8099 ONLY, 192 MB, restart
#     unless-stopped; mounts docker.sock, /srv/wrath, /opt/wenilla-realm (ro) and the Caddyfile (ro)
#   * checks: answers /healthz, and nothing listens on 8099 except 127.0.0.1 (else it is removed)
# Undo: bash /srv/wrath/gmconsole/gmconsole-uninstall.sh
# Paths can be moved for tests (tests/test_install.sh): WU_DIR, WU_CADDYFILE, WU_CADDY_DIR, WU_DOCKER_SOCK, WU_GM_PORT.
set -euo pipefail
SRC="${1:?usage: gmconsole-install.sh <kit dir>}"
WU="${WU_DIR:-/srv/wrath}"
CF="${WU_CADDYFILE:-/opt/openvanilla-classicplus/Caddyfile}"
CADDY_DIR="${WU_CADDY_DIR:-/opt/wenilla-realm}"
SOCK="${WU_DOCKER_SOCK:-/var/run/docker.sock}"
PORT="${WU_GM_PORT:-8099}"
APP="$WU/gmconsole"
ENVF="$WU/gmconsole.env"
IMG=wu-gmconsole:1
NAME=wu-gmconsole
STAMP=$(date +%Y%m%d-%H%M%S)
log() { printf '\n== %s\n' "$*"; }
die() { printf '\nGMCONSOLE FAILED: %s\n' "$*" >&2; exit 1; }

log "1/5 Checks"
command -v docker >/dev/null || die "docker not found"
for f in gmconsole.py static/app.js static/app.css gmconsole-install.sh gmconsole-uninstall.sh Dockerfile; do
  [ -f "$SRC/$f" ] || die "the kit has no $f"
done
[ -d "$WU" ] || die "$WU not found (the Wrath realm is not on this server)"
[ -f "$WU/soap-cmd.sh" ] || echo "  WARNING: $WU/soap-cmd.sh missing: the console can't send console commands"
[ -f "$CF" ] || echo "  WARNING: $CF not found: Reload Caddy and the encode check won't work"
[ -d "$CADDY_DIR" ] || echo "  WARNING: $CADDY_DIR not found"
[ -S "$SOCK" ] || [ -n "${WU_DOCKER_SOCK:-}" ] || die "$SOCK is not a socket"
python3 -I -c "import ast,sys; ast.parse(open(sys.argv[1]).read())" "$SRC/gmconsole.py" || die "gmconsole.py does not parse"
sed -i 's/\r$//' "$SRC"/*.sh

log "2/5 App files -> $APP"
if [ -d "$APP" ]; then
  mkdir -p "$WU/gmconsole-backups"
  cp -a "$APP" "$WU/gmconsole-backups/$STAMP"
  echo "  previous version backed up: $WU/gmconsole-backups/$STAMP"
  # keep the last 5 backups
  ls -1d "$WU/gmconsole-backups"/*/ 2>/dev/null | sort | head -n -5 | xargs -r rm -rf
fi
install -d -m 755 "$APP" "$APP/static"
install -m 644 "$SRC/gmconsole.py" "$APP/gmconsole.py"
install -m 644 "$SRC/static/app.js" "$SRC/static/app.css" "$APP/static/"
install -m 755 "$SRC/gmconsole-install.sh" "$SRC/gmconsole-uninstall.sh" "$APP/"
install -m 644 "$SRC/Dockerfile" "$APP/Dockerfile"

log "3/5 Token"
if grep -qE '^GM_TOKEN=[A-Za-z0-9_-]{32,}$' "$ENVF" 2>/dev/null; then
  echo "  kept (the existing $ENVF)"
else
  umask 077
  tok=$(python3 -I -c 'import secrets; print(secrets.token_urlsafe(32))')
  printf '# WrathUnleashed GM console login token (Open GM Console.bat reads it over SSH). Keep it secret.\nGM_TOKEN=%s\n' "$tok" > "$ENVF.new"
  unset tok
  mv -f "$ENVF.new" "$ENVF"
  umask 022
  echo "  new token written to $ENVF (not shown)"
fi
chmod 600 "$ENVF"

log "4/5 Image $IMG"
want=$(sha256sum "$APP/Dockerfile" | cut -c1-16)
have=$(docker image inspect -f '{{index .Config.Labels "wu.dockerfile"}}' "$IMG" 2>/dev/null || true)
if [ "$have" != "$want" ]; then
  docker image inspect python:3.12-alpine >/dev/null 2>&1 || docker pull -q python:3.12-alpine >/dev/null
  docker build -q --label "wu.dockerfile=$want" -t "$IMG" - < "$APP/Dockerfile" >/dev/null || die "docker build failed (apk needs the internet once)"
  echo "  built"
else
  echo "  up to date"
fi

log "5/5 Container $NAME on 127.0.0.1:$PORT"
start() {
  docker rm -f "$NAME" >/dev/null 2>&1 || true
  docker run -d --name "$NAME" --restart unless-stopped --memory 192m --cpus 1 --pids-limit 200 \
    --network host --security-opt no-new-privileges \
    -e GM_BIND=127.0.0.1 -e GM_PORT="$PORT" -e GM_WU_DIR="$WU" -e GM_CADDYFILE="$CF" -e GM_REALM_DIR="$CADDY_DIR" \
    -e GM_TOKEN_FILE="$ENVF" \
    -v "$SOCK:/var/run/docker.sock" -v "$WU:$WU" -v "$CADDY_DIR:$CADDY_DIR:ro" -v "$CF:$CF:ro" -v "$APP:/app:ro" \
    -w "$WU" "$IMG" python3 -I /app/gmconsole.py >/dev/null
}
healthy() {
  local _
  for _ in $(seq 1 30); do
    if curl -fsS -m 3 -H "Host: 127.0.0.1:$PORT" "http://127.0.0.1:$PORT/healthz" >/dev/null 2>&1; then return 0; fi
    sleep 1
  done
  return 1
}
start
if ! healthy; then
  docker logs --tail 30 "$NAME" >&2 || true
  if [ -d "$WU/gmconsole-backups/$STAMP" ]; then
    echo "  the new version did not start: putting the previous one back" >&2
    rm -rf "$APP" && cp -a "$WU/gmconsole-backups/$STAMP" "$APP"
    start; healthy || true
  fi
  die "the console does not answer on 127.0.0.1:$PORT (docker logs $NAME)"
fi
# never public: anything but loopback listening on the port is a hard stop
if command -v ss >/dev/null; then
  pub=$(ss -ltnH "( sport = :$PORT )" | awk '{print $4}' | grep -vE '^(127\.0\.0\.1|\[::1\]):' || true)
  if [ -n "$pub" ]; then
    docker rm -f "$NAME" >/dev/null 2>&1 || true
    die "port $PORT is listening on $pub (not only loopback): removed the console"
  fi
  echo "  listening: $(ss -ltnH "( sport = :$PORT )" | awk '{print $4}' | tr '\n' ' ')"
fi
echo "  audit log: $WU/gmconsole-audit.log"
echo
echo "The GM console is up (loopback only). On your PC: Open GM Console.bat"
echo "GMCONSOLE OK"
