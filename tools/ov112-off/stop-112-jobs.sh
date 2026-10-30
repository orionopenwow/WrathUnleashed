#!/usr/bin/env bash
# Turn off the 1.12 Open Vanilla realm's jobs on the server (play.openvanilla.app), and nothing else.
#
#   bash stop-112-jobs.sh          dry run: say what it would change, change nothing
#   bash stop-112-jobs.sh --go     do it
#
# What it turns off (all of it can be turned back on with start-112-jobs.sh):
#   * root's crontab lines that run 1.12 jobs (backup_cron.sh, armory/streams crons, anything naming
#     openvanilla / openwow / wenilla / hetzner scripts / Herald / Warfront / Duels / Boss Fights)
#   * the 1.12 systemd units (openvanilla-* / openwow-*: armory, streams, digest, telemetry, Herald,
#     Herald Autopilot, Warfront/Duels/Boss Fights live and self-tests, the old backend/studio units):
#     systemctl disable --now. The unit files stay where they are.
#   * the 1.12 containers: Warfront, Duels, staging, the old openvanilla compose stack, the Herald
#     support proxies, and only mangosd/realmd of the wenilla-realm stack: restart policy set to "no",
#     then stopped. Nothing is removed.
# What it never touches: anything naming wu-, leyline, hangout, relay, portal, stream, wrath or caddy
# (Leyline and the Dalaran Hangout run on the same server), the wenilla-realm stack's realm, caddy and
# mariadb containers (the website front and the proxy everything goes through), Docker itself, and
# /etc/cron.d (only reported).
# Before changing anything it saves root's crontab, the unit files and their state, and each
# container's restart policy and state in /root/ov112-off-<stamp>/ (start-112-jobs.sh reads that).
#
# For the tests: --classify-cron (stdin: a crontab; prints "OFF <line>" or "KEEP <line>"),
# --classify-unit NAME, --classify-container NAME PROJECT SERVICE (print OFF or KEEP).
set -u

# Names that are Leyline / WrathUnleashed / shared infrastructure: never touched.
PROTECT='wu-|wu_|leyline|hangout|relay|portal|stream|wrath|caddy|/srv/|/opt/cmangos|/opt/tc|/opt/leyline'
# Names that mark a 1.12 job.
OV='openvanilla|openwow|open-vanilla|wenilla|classicplus|hetzner/|herald|owbot|botlab|warfront|duels|bossfights|armory_cron|backup_cron'
# 1.12 jobs whose own names contain a protected word (the 1.12 site's streams fetcher).
OV_EXACT='streams_cron\.sh|streams_fetch\.py|openvanilla-streams'

classify_cron_line() {   # $1 = one crontab line -> OFF or KEEP
  local l="$1" low
  low=$(printf '%s' "$l" | tr 'A-Z' 'a-z')
  case "$low" in ''|'#'*) echo KEEP; return;; esac
  # VAR=value lines (SHELL=, PATH=, MAILTO=) are settings, not jobs
  if printf '%s' "$low" | grep -qE '^[[:space:]]*[a-z_][a-z0-9_]*[[:space:]]*='; then echo KEEP; return; fi
  if printf '%s' "$low" | grep -qE "$OV_EXACT" && ! printf '%s' "$low" | grep -qE 'wu-|wu_|leyline|hangout|wrath|/srv/'; then
    echo OFF; return
  fi
  if printf '%s' "$low" | grep -qE "$PROTECT"; then echo KEEP; return; fi
  if printf '%s' "$low" | grep -qE "$OV"; then echo OFF; return; fi
  echo KEEP
}

classify_unit() {   # $1 = unit name -> OFF or KEEP
  local u
  u=$(printf '%s' "$1" | tr 'A-Z' 'a-z')
  case "$u" in openvanilla-binfmt.service) echo KEEP; return;; esac   # x86 emulation other containers may use
  case "$u" in openvanilla-streams.service|openvanilla-streams.timer) echo OFF; return;; esac
  case "$u" in openvanilla-*.service|openvanilla-*.timer|openwow-*.service|openwow-*.timer) ;; *) echo KEEP; return;; esac
  if printf '%s' "$u" | grep -qE "$PROTECT"; then echo KEEP; return; fi
  echo OFF
}

classify_container() {   # $1 name, $2 compose project, $3 compose service -> OFF or KEEP
  local n p s all
  n=$(printf '%s' "$1" | tr 'A-Z' 'a-z'); p=$(printf '%s' "${2:-}" | tr 'A-Z' 'a-z'); s=$(printf '%s' "${3:-}" | tr 'A-Z' 'a-z')
  all="$n $p $s"
  if printf '%s' "$all" | grep -qE "$PROTECT"; then echo KEEP; return; fi
  case "$p" in
    wenilla-realm) case "$s" in mangosd|realmd) echo OFF;; *) echo KEEP;; esac; return;;   # realm (website) + mariadb stay
    owduels|wenilla-duels|wenilla-warfront|owwarfront|wenilla-staging|wenilla-bossfights|openvanilla|openwow) echo OFF; return;;
  esac
  case "$n" in openvanilla-support-*|openvanilla_*|openwow_*|openwow-*) echo OFF; return;; esac
  echo KEEP
}

case "${1:-}" in
  --classify-cron) while IFS= read -r line || [ -n "$line" ]; do echo "$(classify_cron_line "$line") $line"; done; exit 0;;
  --classify-unit) classify_unit "${2:-}"; exit 0;;
  --classify-container) classify_container "${2:-}" "${3:-}" "${4:-}"; exit 0;;
  --go) GO=1;;
  ''|--dry-run) GO=0;;
  *) echo "usage: $0 [--go]"; exit 2;;
esac

[ "$(id -u)" = 0 ] || { echo "Run this as root (it reads root's crontab and systemd)."; exit 1; }
STAMP=$(date +%Y%m%d-%H%M%S)
B=${OV112_BACKUP_ROOT:-/root}/ov112-off-$STAMP   # OV112_BACKUP_ROOT: for the tests
if [ "$GO" = 1 ]; then mkdir -p "$B/units"; echo "Backup folder: $B"; else echo "DRY RUN (nothing changes; add --go to apply)"; fi
changed=0

echo; echo "== root's crontab"
if crontab -l >/tmp/ov112-cron.$$ 2>/dev/null; then
  : > /tmp/ov112-keep.$$; : > /tmp/ov112-off.$$
  while IFS= read -r line || [ -n "$line" ]; do
    if [ "$(classify_cron_line "$line")" = OFF ]; then printf '%s\n' "$line" >> /tmp/ov112-off.$$; else printf '%s\n' "$line" >> /tmp/ov112-keep.$$; fi
  done < /tmp/ov112-cron.$$
  if [ -s /tmp/ov112-off.$$ ]; then
    sed 's/^/  off: /' /tmp/ov112-off.$$
    if [ "$GO" = 1 ]; then
      cp /tmp/ov112-cron.$$ "$B/crontab.before"; cp /tmp/ov112-off.$$ "$B/crontab.removed"
      crontab /tmp/ov112-keep.$$ && echo "  crontab updated ($(wc -l < /tmp/ov112-off.$$) lines removed)" && changed=1
    fi
  else
    echo "  no 1.12 lines"
  fi
  rm -f /tmp/ov112-cron.$$ /tmp/ov112-keep.$$ /tmp/ov112-off.$$
else
  echo "  root has no crontab"
fi
for f in /etc/cron.d/*; do
  [ -f "$f" ] || continue
  if grep -qiE "$OV" "$f" && ! grep -qiE 'wu-|leyline|hangout|wrath' "$f"; then echo "  note: $f mentions a 1.12 job (left as is; remove it by hand if it is one)"; fi
done

echo; echo "== systemd units"
if command -v systemctl >/dev/null 2>&1; then
  units=$(systemctl list-unit-files --no-legend --type=service,timer 2>/dev/null | awk '{print $1}' | grep -iE '^(openvanilla|openwow)-' || true)
  : > /tmp/ov112-units.$$
  for u in $units; do
    if [ "$(classify_unit "$u")" != OFF ]; then echo "  keep: $u"; continue; fi
    en=$(systemctl is-enabled "$u" 2>/dev/null || true); ac=$(systemctl is-active "$u" 2>/dev/null || true)
    case "$en:$ac" in disabled:inactive|masked:*|static:inactive|:inactive|:) echo "  already off: $u ($en, $ac)"; continue;; esac
    echo "  off: $u (was $en, $ac)"
    printf '%s %s %s\n' "$u" "${en:-unknown}" "${ac:-unknown}" >> /tmp/ov112-units.$$
  done
  # timers first, so a timer can't start its service again
  for u in $(grep '\.timer ' /tmp/ov112-units.$$ | cut -d' ' -f1) $(grep '\.service ' /tmp/ov112-units.$$ | cut -d' ' -f1); do
    if [ "$GO" = 1 ]; then
      p=$(systemctl show -p FragmentPath --value "$u" 2>/dev/null); [ -n "$p" ] && [ -f "$p" ] && cp -p "$p" "$B/units/"
      systemctl disable --now "$u" >/dev/null 2>&1 && changed=1 || echo "  !! could not disable $u"
    fi
  done
  [ "$GO" = 1 ] && cp /tmp/ov112-units.$$ "$B/units.state"
  [ -s /tmp/ov112-units.$$ ] || echo "  nothing to turn off"
  rm -f /tmp/ov112-units.$$
else
  echo "  no systemctl here"
fi

echo; echo "== containers"
if command -v docker >/dev/null 2>&1; then
  : > /tmp/ov112-ct.$$
  docker ps -a --format '{{.Names}}|{{.Label "com.docker.compose.project"}}|{{.Label "com.docker.compose.service"}}' 2>/dev/null |
  while IFS='|' read -r n p s; do
    [ -n "$n" ] || continue
    if [ "$(classify_container "$n" "$p" "$s")" != OFF ]; then echo "  keep: $n${p:+ ($p/$s)}"; continue; fi
    pol=$(docker inspect -f '{{.HostConfig.RestartPolicy.Name}}' "$n" 2>/dev/null); run=$(docker inspect -f '{{.State.Running}}' "$n" 2>/dev/null)
    if [ "$pol" = no ] && [ "$run" != true ]; then echo "  already off: $n"; continue; fi
    echo "  off: $n${p:+ ($p/$s)} (restart=$pol, running=$run)"
    printf '%s %s %s\n' "$n" "${pol:-no}" "${run:-false}" >> /tmp/ov112-ct.$$
  done
  if [ "$GO" = 1 ]; then
    cp /tmp/ov112-ct.$$ "$B/containers.state"
    while read -r n pol run; do
      docker update --restart=no "$n" >/dev/null && changed=1 || echo "  !! could not change $n's restart policy"
      [ "$run" = true ] && { docker stop -t 30 "$n" >/dev/null || echo "  !! could not stop $n"; }
    done < /tmp/ov112-ct.$$
  fi
  [ -s /tmp/ov112-ct.$$ ] || echo "  nothing to turn off"
  rm -f /tmp/ov112-ct.$$
else
  echo "  no docker here"
fi

echo
if [ "$GO" = 1 ]; then
  echo "Done. Saved in $B. Undo: bash start-112-jobs.sh --go $B"
  echo "OV112 OFF"
else
  echo "Dry run finished: nothing changed. Run again with --go to apply."
  echo "OV112 DRY"
fi
