#!/usr/bin/env bash
# WrathUnleashed GM console: remove the container and the image. The game, the website and all
# their data are untouched. Kept: the audit log (/srv/wrath/gmconsole-audit.log), the speed-plan
# ticks (gmconsole-speed.json) and the app backups. The token file is retired (renamed), so an
# old login link stops working even if the console is installed again.
set -euo pipefail
WU="${WU_DIR:-/srv/wrath}"
docker rm -f wu-gmconsole >/dev/null 2>&1 && echo "  container wu-gmconsole removed" || echo "  no wu-gmconsole container"
docker image rm wu-gmconsole:1 >/dev/null 2>&1 && echo "  image removed" || true
if [ -f "$WU/gmconsole.env" ]; then
  mv -f "$WU/gmconsole.env" "$WU/gmconsole.env.retired-$(date +%Y%m%d-%H%M%S)"
  chmod 600 "$WU"/gmconsole.env.retired-* 2>/dev/null || true
  echo "  token retired"
fi
if [ -d "$WU/gmconsole" ]; then
  mkdir -p "$WU/gmconsole-backups"
  mv "$WU/gmconsole" "$WU/gmconsole-backups/uninstalled-$(date +%Y%m%d-%H%M%S)"
  echo "  app files moved to $WU/gmconsole-backups"
fi
echo "GMCONSOLE REMOVED"
