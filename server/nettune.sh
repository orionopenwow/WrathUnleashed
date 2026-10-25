#!/usr/bin/env bash
# WrathUnleashed: faster game-file downloads for far-away players (no client change).
#  1. TCP: BBR congestion control + fq, and no slow-start after idle (a 190 ms path with a little
#     packet loss is capped near 8 Mbps with the default Cubic; BBR keeps it near the line rate).
#  2. HTTP/3: Caddy already speaks it, but only if UDP 443 reaches it (firewall + Docker port).
# Backups first; Caddy is put back if the site doesn't answer afterwards. Safe to run again.
set -euo pipefail
CADDY_DIR=${WU_CADDY_DIR:-/opt/wenilla-realm}
BK=/root/nettune-backups/$(date +%Y%m%d-%H%M%S); mkdir -p "$BK"
echo "== 1/3 TCP tuning"
modprobe tcp_bbr 2>/dev/null || true
cat > /etc/sysctl.d/90-openvanilla-net.conf <<'CONF'
# WrathUnleashed / Open Vanilla: game-file streaming to far-away players
net.core.default_qdisc = fq
net.ipv4.tcp_congestion_control = bbr
net.ipv4.tcp_slow_start_after_idle = 0
CONF
echo tcp_bbr > /etc/modules-load.d/bbr.conf
sysctl -q -p /etc/sysctl.d/90-openvanilla-net.conf
echo "  congestion control: $(sysctl -n net.ipv4.tcp_congestion_control), qdisc: $(sysctl -n net.core.default_qdisc), slow start after idle: $(sysctl -n net.ipv4.tcp_slow_start_after_idle)"
[ "$(sysctl -n net.ipv4.tcp_congestion_control)" = bbr ] || { echo "NETTUNE FAILED: the kernel refused BBR" >&2; exit 1; }

echo "== 2/3 Firewall: UDP 443 for HTTP/3"
if command -v ufw >/dev/null && ufw status | grep -q '^Status: active'; then
  if ufw status | grep -qE '^443/udp\s+ALLOW'; then echo "  ufw already allows 443/udp"; else ufw allow 443/udp >/dev/null; echo "  ufw: 443/udp allowed"; fi
else
  echo "  ufw is not active on the box (nothing to open here)"
fi

echo "== 3/3 Caddy: publish UDP 443"
cd "$CADDY_DIR"
CF=""
for f in docker-compose.yml docker-compose.yaml compose.yml compose.yaml; do [ -f "$f" ] && CF=$f && break; done
[ -n "$CF" ] || { echo "NETTUNE FAILED: no compose file in $CADDY_DIR" >&2; exit 1; }
CID=$(docker compose ps -q caddy 2>/dev/null || true)
if [ -n "$CID" ] && docker port "$CID" 2>/dev/null | grep -q '^443/udp'; then
  echo "  Caddy already receives UDP 443"
else
  cp -p "$CF" "$BK/$CF"
  python3 -I - "$CF" <<'PY'
import re, sys
p = sys.argv[1]; s = open(p).read()
if re.search(r'["\']?443:443/udp["\']?', s):
    print("  compose already lists 443:443/udp"); sys.exit(0)
m = re.search(r'^(\s*-\s*)(["\']?)((?:[\d.]+:)?443:443)\2\s*$', s, re.M)
if not m: sys.exit("no '443:443' port line in the compose file: add \"443:443/udp\" under caddy's ports by hand")
line = m.group(0)
s = s.replace(line, line + "\n" + m.group(1) + '"' + m.group(3) + '/udp"', 1)
open(p, "w").write(s); print("  added 443:443/udp to " + p)
PY
  docker compose up -d caddy >/dev/null
  sleep 4
  code=$(curl -s -o /dev/null -w '%{http_code}' -m 20 https://play.openvanilla.app/ || true)
  if [ "$code" = 000 ] || [ "${code:0:1}" = 5 ]; then
    cp -p "$BK/$CF" "$CF"; docker compose up -d caddy >/dev/null
    echo "NETTUNE FAILED: the site didn't answer after the change ($code); Caddy is back as it was" >&2; exit 1
  fi
  echo "  site answers ($code) with UDP 443 published"
fi
alt=$(curl -sI -m 20 https://play.openvanilla.app/ | grep -i '^alt-svc' | tr -d '\r' || true)
echo "  Alt-Svc: ${alt:-none}"
echo "  Hetzner Cloud firewall (if you use one in the Hetzner console): allow inbound UDP 443 there too."
echo "NETTUNE OK"
