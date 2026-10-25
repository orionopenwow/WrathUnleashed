#!/usr/bin/env bash
# Restores database dumps made by backup.sh.
#
#   ./restore.sh                         list the backups on this box
#   ./restore.sh <backup> [db ...]       restore all dumps in that backup, or only the named ones
#   ./restore.sh 2026-10-30_043000 acore_characters
#   ./restore.sh /path/to/acore_auth.sql.gz          restore a single dump file
#   add --yes to skip the confirmation prompt
#
# What happens:
#   1. a fresh safety backup is taken first (backup.sh), so a wrong restore can be undone
#   2. authserver and worldserver are stopped (players disconnected; online players are saved)
#   3. each dump is checked against SHA256SUMS (if present) and loaded; the dump drops and
#      recreates every table it contains
#   4. authserver and worldserver are started again
# To pull a backup from restic first: restic restore latest --target /tmp/r, then point this
# script at the folder under /tmp/r.

set -euo pipefail

WU_DIR="${WU_DIR:-/srv/wrath}"
BACKUP_ROOT="${WU_BACKUP_DIR:-${WU_DIR}/backups}"
DB_CONTAINER="${WU_DB_CONTAINER:-ov-ac-database}"

assume_yes=0
args=()
for a in "$@"; do
  if [[ "$a" == "--yes" ]]; then assume_yes=1; else args+=("$a"); fi
done
set -- "${args[@]+"${args[@]}"}"

[[ $EUID -eq 0 ]] || { echo "run as root" >&2; exit 1; }

if [[ $# -eq 0 ]]; then
  echo "Backups in ${BACKUP_ROOT} (newest last):"
  find "$BACKUP_ROOT" -mindepth 1 -maxdepth 1 -type d -name '20*' -printf '  %f\n' | sort
  echo "Usage: $0 <backup> [db ...] [--yes]"
  exit 0
fi

target="$1"; shift
files=()
if [[ -f "$target" ]]; then
  files=("$target")
else
  [[ -d "$target" ]] || target="${BACKUP_ROOT}/${target}"
  [[ -d "$target" ]] || { echo "no such backup: $target" >&2; exit 1; }
  if [[ -f "${target}/SHA256SUMS" ]]; then
    echo "[check] verifying checksums in ${target}"
    (cd "$target" && sha256sum --quiet -c SHA256SUMS)
  fi
  if [[ $# -gt 0 ]]; then
    for d in "$@"; do
      [[ -f "${target}/${d}.sql.gz" ]] || { echo "no ${d}.sql.gz in ${target}" >&2; exit 1; }
      files+=("${target}/${d}.sql.gz")
    done
  else
    for f in "${target}"/*.sql.gz; do files+=("$f"); done
  fi
fi
[[ ${#files[@]} -gt 0 ]] || { echo "nothing to restore" >&2; exit 1; }

echo "About to restore (this OVERWRITES the live data in these databases):"
for f in "${files[@]}"; do echo "  $f"; done
if [[ $assume_yes -ne 1 ]]; then
  read -r -p "Type RESTORE to continue: " answer
  [[ "$answer" == "RESTORE" ]] || { echo "aborted"; exit 1; }
fi

echo "[1/4] safety backup of the current state"
bash "${WU_DIR}/backup.sh"

echo "[2/4] stopping authserver and worldserver"
cd "$WU_DIR"
docker compose stop ac-worldserver ac-authserver

echo "[3/4] loading dumps"
for f in "${files[@]}"; do
  echo "  loading $(basename "$f")"
  gzip -t "$f"
  gunzip -c "$f" | docker exec -i "$DB_CONTAINER" sh -c 'MYSQL_PWD="$MYSQL_ROOT_PASSWORD" exec mysql -uroot'
done

echo "[4/4] starting authserver and worldserver"
docker compose up -d ac-authserver ac-worldserver
echo "Restore finished. Watch the world server come up: docker logs -f ov-ac-worldserver"
