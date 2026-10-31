#!/usr/bin/env bash
# Connection-flood limits for the ports Docker publishes (Docker's port rules skip ufw: they sit in the FORWARD
# chain, and DOCKER-USER is the one place Docker leaves for our own rules), and a fail2ban jail for the
# authserver's wrong-password log line.
#
#   bash firewall.sh            dry run (the default): prints every command, changes nothing
#   bash firewall.sh --apply    applies it, installs itself as /usr/local/sbin/wu-firewall.sh with a systemd unit
#                               (wu-firewall.service) that puts the rules back after a reboot or a Docker restart,
#                               and writes the fail2ban jail + filter
#   bash firewall.sh --remove   takes the rules, the unit and the jail out again
# Idempotent: our rules live in their own chain (WU-LIMIT), which is emptied and refilled on every run; DOCKER-USER
# gets exactly one jump to it.
#
# Per source address (IPv4 /32, IPv6 /64), new connections only (established players are never touched):
#   3724 (login), 8085 (world)    at most 10 open connections, 30 new a minute (burst 20)
#   40000:40999 (relay)           at most 20 open, 120 new a minute (burst 60)
#   80, 443 (web)                 at most 200 open, 600 new a minute (burst 300); WU_FW_WEB=0 leaves them alone:
#                                 set that once Cloudflare proxies the sites (every visitor then comes from a
#                                 Cloudflare address, and Cloudflare's own rate rules do this job)
# Over the limit: a TCP reset (the client sees "connection refused", nothing hangs).
set -euo pipefail
MODE=dry
case "${1:-}" in --apply) MODE=apply ;; --remove) MODE=remove ;; ""|--dry-run) MODE=dry ;; *) echo "usage: $0 [--apply|--remove]"; exit 2 ;; esac
CHAIN=WU-LIMIT
WEB=${WU_FW_WEB:-1}
AUTH_LOG=${WU_AUTH_LOG:-/srv/wrath/logs/auth/Auth.log}
EXT=${WU_FW_IF:-$(ip -o route get 1.1.1.1 2>/dev/null | sed -n 's/.* dev \([^ ]*\).*/\1/p')}
[ -n "$EXT" ] || { echo "Can't tell the outside network interface (set WU_FW_IF)."; exit 1; }

run() { if [ "$MODE" = dry ]; then printf '  %s\n' "$*"; else "$@"; fi; }
have6() { command -v ip6tables >/dev/null 2>&1 && ip6tables -S DOCKER-USER >/dev/null 2>&1; }

# port spec, connlimit, rate per minute, burst
RULES=("3724 10 30 20" "8085 10 30 20" "40000:40999 20 120 60")
[ "$WEB" = 0 ] || RULES+=("80 200 600 300" "443 200 600 300")

fill() {   # $1 iptables|ip6tables, $2 mask
  local T=$1 M=$2 r p c rate burst name
  $T -n -L DOCKER-USER >/dev/null 2>&1 || { echo "  ($T: no DOCKER-USER chain: is Docker running?)"; return 0; }
  if ! $T -n -L "$CHAIN" >/dev/null 2>&1; then run "$T" -N "$CHAIN"; fi
  run "$T" -F "$CHAIN"
  for r in "${RULES[@]}"; do
    read -r p c rate burst <<<"$r"
    name="wu${p//:/-}${M}"
    run "$T" -A "$CHAIN" -i "$EXT" -p tcp -m conntrack --ctstate NEW --ctorigdstport "$p" \
      -m connlimit --connlimit-above "$c" --connlimit-mask "$M" -j REJECT --reject-with tcp-reset
    run "$T" -A "$CHAIN" -i "$EXT" -p tcp --syn -m conntrack --ctstate NEW --ctorigdstport "$p" \
      -m hashlimit --hashlimit-name "$name" --hashlimit-mode srcip --hashlimit-srcmask "$M" \
      --hashlimit-above "$rate/minute" --hashlimit-burst "$burst" -j REJECT --reject-with tcp-reset
  done
  run "$T" -A "$CHAIN" -j RETURN
  if ! $T -C DOCKER-USER -j "$CHAIN" >/dev/null 2>&1; then run "$T" -I DOCKER-USER 1 -j "$CHAIN"; fi
}

unfill() {
  local T=$1
  while $T -C DOCKER-USER -j "$CHAIN" >/dev/null 2>&1; do run "$T" -D DOCKER-USER -j "$CHAIN"; [ "$MODE" = dry ] && break; done
  if $T -n -L "$CHAIN" >/dev/null 2>&1; then run "$T" -F "$CHAIN"; run "$T" -X "$CHAIN"; fi
}

JAIL=/etc/fail2ban/jail.d/wrath-auth.conf
FILTER=/etc/fail2ban/filter.d/wrath-auth.conf
FILTER_BODY="# Written by tools/security/firewall.sh: the authserver's line for a wrong password (WrongPass.Logging)
[Definition]
failregex = ^'<HOST>:\d+' \[AuthChallenge\] account \S+ tried to login with invalid password!\$
ignoreregex =
# Auth.log lines carry no time (Appender.Auth flags 0): fail2ban stamps them as it reads them
datepattern = {NONE}"
JAIL_BODY="# Written by tools/security/firewall.sh. The authserver already bans an address for 10 minutes after 10 wrong
# passwords (AC_WRONG_PASS_*); this bans one that keeps at it (20 in 10 minutes) for a day, in DOCKER-USER
# (fail2ban's default INPUT chain never sees Docker's forwarded game ports).
[wrath-auth]
enabled  = true
filter   = wrath-auth
logpath  = $AUTH_LOG
backend  = polling
findtime = 10m
maxretry = 20
bantime  = 1d
action   = iptables-multiport[name=wrath-auth, port=\"3724,8085\", protocol=tcp, chain=DOCKER-USER]"

UNIT=/etc/systemd/system/wu-firewall.service
UNIT_BODY="[Unit]
Description=WrathUnleashed connection limits in DOCKER-USER (tools/security/firewall.sh)
After=docker.service
PartOf=docker.service

[Service]
Type=oneshot
ExecStartPre=/bin/sleep 5
ExecStart=/usr/local/sbin/wu-firewall.sh --apply --no-install
RemainAfterExit=yes

[Install]
WantedBy=multi-user.target docker.service"

echo "== firewall ($MODE) on $EXT; web limits: $([ "$WEB" = 0 ] && echo off || echo on)"
if [ "$MODE" = remove ]; then
  unfill iptables; have6 && unfill ip6tables
  [ -f "$UNIT" ] && { run systemctl disable --now wu-firewall.service; run rm -f "$UNIT" /usr/local/sbin/wu-firewall.sh; }
  [ -f "$JAIL" ] && { run rm -f "$JAIL" "$FILTER"; run systemctl reload fail2ban; }
  echo "FIREWALL REMOVED"; exit 0
fi
fill iptables 32
if have6; then fill ip6tables 64; else echo "  (no IPv6 DOCKER-USER chain: IPv4 only)"; fi

[ "${2:-}" = "--no-install" ] && { echo "FIREWALL OK"; exit 0; }

echo "== fail2ban jail for wrong passwords ($AUTH_LOG)"
if [ "$MODE" = dry ]; then
  printf '  would write %s:\n%s\n  would write %s:\n%s\n' "$FILTER" "$FILTER_BODY" "$JAIL" "$JAIL_BODY" | sed 's/^/    /'
  [ -f "$AUTH_LOG" ] || echo "  NOTE: $AUTH_LOG isn't there yet (the jail waits for it)"
else
  if command -v fail2ban-client >/dev/null 2>&1; then
    printf '%s\n' "$FILTER_BODY" > "$FILTER"; printf '%s\n' "$JAIL_BODY" > "$JAIL"
    touch "$AUTH_LOG" 2>/dev/null || true
    fail2ban-client -t >/dev/null || { rm -f "$JAIL" "$FILTER"; echo "fail2ban refused the jail; removed it again"; exit 1; }
    systemctl reload fail2ban || systemctl restart fail2ban
    echo "  fail2ban: $(fail2ban-client status wrath-auth 2>/dev/null | grep -c 'Currently banned' || true) jail(s) up"
  else
    echo "  fail2ban isn't installed (server/bootstrap.sh installs it): jail skipped"
  fi
fi

echo "== kept after a reboot (wu-firewall.service)"
if [ "$MODE" = dry ]; then
  echo "  would install /usr/local/sbin/wu-firewall.sh and $UNIT"
else
  install -m 755 "$0" /usr/local/sbin/wu-firewall.sh
  printf '%s\n' "$UNIT_BODY" > "$UNIT"
  systemctl daemon-reload
  systemctl enable wu-firewall.service >/dev/null 2>&1 || true
  echo "  installed"
fi
[ "$MODE" = dry ] && { echo; echo "Dry run: nothing changed. bash $0 --apply to do it."; echo "FIREWALL DRY"; exit 0; }
echo "FIREWALL OK"
