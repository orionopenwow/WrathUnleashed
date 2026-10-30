#!/usr/bin/env bash
# Undo stop-112-jobs.sh: turn the 1.12 Open Vanilla realm's jobs back on, exactly as they were.
#
#   bash start-112-jobs.sh                       dry run, from the newest /root/ov112-off-* folder
#   bash start-112-jobs.sh --go [/root/ov112-off-<stamp>]   do it (that folder, or the newest)
#
# From the backup folder it: puts the removed crontab lines back (only those that are missing now),
# enables again the units that were enabled and starts the ones that were running, and gives each
# container its old restart policy and starts the ones that were running. Nothing else changes.
set -u
GO=0; B=""
for a in "$@"; do
  case "$a" in --go) GO=1;; --dry-run) GO=0;; /*) B="$a";; *) echo "usage: $0 [--go] [/root/ov112-off-<stamp>]"; exit 2;; esac
done
[ "$(id -u)" = 0 ] || { echo "Run this as root."; exit 1; }
[ -n "$B" ] || B=$(ls -d "${OV112_BACKUP_ROOT:-/root}"/ov112-off-* 2>/dev/null | sort | tail -1)
[ -n "$B" ] && [ -d "$B" ] || { echo "No /root/ov112-off-* folder: nothing to undo."; exit 1; }
echo "From: $B"; [ "$GO" = 1 ] || echo "DRY RUN (nothing changes; add --go to apply)"

echo; echo "== root's crontab"
if [ -s "$B/crontab.removed" ]; then
  crontab -l > /tmp/ov112-now.$$ 2>/dev/null || : > /tmp/ov112-now.$$
  cp /tmp/ov112-now.$$ /tmp/ov112-new.$$; add=0
  while IFS= read -r line || [ -n "$line" ]; do
    if grep -qxF -- "$line" /tmp/ov112-now.$$; then echo "  already there: $line"; else echo "  back: $line"; printf '%s\n' "$line" >> /tmp/ov112-new.$$; add=1; fi
  done < "$B/crontab.removed"
  [ "$GO" = 1 ] && [ "$add" = 1 ] && crontab /tmp/ov112-new.$$ && echo "  crontab updated"
  rm -f /tmp/ov112-now.$$ /tmp/ov112-new.$$
else
  echo "  no lines were removed"
fi

echo; echo "== systemd units"
if [ -s "$B/units.state" ]; then
  # services first, then timers (a timer starting would run its service early)
  for kind in service timer; do
    while read -r u en ac; do
      case "$u" in *."$kind") ;; *) continue;; esac
      echo "  $u: back to $en, $ac"
      if [ "$GO" = 1 ]; then
        [ -f "/etc/systemd/system/$u" ] || { [ -f "$B/units/$u" ] && cp -p "$B/units/$u" /etc/systemd/system/ && systemctl daemon-reload; }
        [ "$en" = enabled ] && systemctl enable "$u" >/dev/null 2>&1
        [ "$ac" = active ] && systemctl start "$u" >/dev/null 2>&1
      fi
    done < "$B/units.state"
  done
else
  echo "  no units were turned off"
fi

echo; echo "== containers"
if [ -s "$B/containers.state" ]; then
  while read -r n pol run; do
    echo "  $n: restart=$pol${run:+, running=$run}"
    if [ "$GO" = 1 ]; then
      docker update --restart="$pol" "$n" >/dev/null || echo "  !! could not set $n's restart policy"
      [ "$run" = true ] && { docker start "$n" >/dev/null || echo "  !! could not start $n"; }
    fi
  done < "$B/containers.state"
else
  echo "  no containers were turned off"
fi

echo
if [ "$GO" = 1 ]; then echo "Done."; echo "OV112 ON"; else echo "Dry run finished: nothing changed."; echo "OV112 DRY"; fi
