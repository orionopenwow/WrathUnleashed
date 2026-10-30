#!/usr/bin/env bash
# Nightly backup of the realm databases (run by wu-backup.timer, or by hand as root).
#
#   /srv/wrath/backup.sh
#
# Writes /srv/wrath/backups/<UTC timestamp>/:
#   acore_auth.sql.gz, acore_characters.sql.gz, acore_world.sql.gz
#   acore_playerbots.sql.gz (if that database exists; bot data, can be regenerated)
#   config.tar.gz  (.env, profiles, modules.env, lua scripts, signup.env: contains secrets)
#   SHA256SUMS
# Dumps use mysqldump --single-transaction: a consistent snapshot without locking InnoDB
# tables, so the realm stays up and players notice nothing.
# Keeps 14 days locally (WU_BACKUP_KEEP_DAYS). If RESTIC_REPOSITORY is set in
# /srv/wrath/backup.env, the new folder is also pushed off-site with restic.

set -euo pipefail

WU_DIR="${WU_DIR:-/srv/wrath}"
BACKUP_ROOT="${WU_BACKUP_DIR:-${WU_DIR}/backups}"
KEEP_DAYS="${WU_BACKUP_KEEP_DAYS:-14}"
DB_CONTAINER="${WU_DB_CONTAINER:-ov-ac-database}"
DATABASES=(acore_auth acore_characters acore_world)
OPTIONAL_DATABASES=(acore_playerbots)

log() { printf '%s backup: %s\n' "$(date -u +%FT%TZ)" "$*"; }

# Optional restic settings (RESTIC_REPOSITORY, RESTIC_PASSWORD or RESTIC_PASSWORD_FILE, and
# whatever the backend needs, e.g. AWS_ACCESS_KEY_ID). File is root-only (mode 600).
if [[ -f "${WU_DIR}/backup.env" ]]; then
  set -a
  # shellcheck disable=SC1091
  . "${WU_DIR}/backup.env"
  set +a
fi

[[ $EUID -eq 0 ]] || { echo "run as root" >&2; exit 1; }
docker inspect -f '{{.State.Running}}' "$DB_CONTAINER" 2>/dev/null | grep -q true \
  || { log "database container ${DB_CONTAINER} is not running"; exit 1; }

# Runs a command inside the DB container with the root password taken from the container's
# own environment (never on this host's command line).
in_db() { docker exec -i "$DB_CONTAINER" sh -c 'MYSQL_PWD="$MYSQL_ROOT_PASSWORD"; export MYSQL_PWD; exec "$@"' sh "$@"; }

stamp="$(date -u +%Y-%m-%d_%H%M%S)"
dest="${BACKUP_ROOT}/${stamp}"
[[ ! -e "$dest" ]] || { log "${dest} already exists"; exit 1; }
tmp="${BACKUP_ROOT}/.partial-${stamp}"
umask 077
mkdir -p "$BACKUP_ROOT"
rm -rf "$tmp"
mkdir -p "$tmp"
# Leave no half-written folder behind if anything fails.
trap 'rm -rf "$tmp"' EXIT

dump() { # database
  log "dumping $1"
  # --databases adds CREATE DATABASE / USE, so restore.sh needs no database argument.
  in_db mysqldump -uroot --single-transaction --quick --routines --triggers --events \
    --hex-blob --default-character-set=utf8mb4 --set-gtid-purged=OFF --databases "$1" \
    | gzip -6 >"${tmp}/$1.sql.gz"
}

for d in "${DATABASES[@]}"; do dump "$d"; done
for d in "${OPTIONAL_DATABASES[@]}"; do
  if in_db mysql -uroot -N -e "SHOW DATABASES LIKE '$d'" | grep -qx "$d"; then dump "$d"; fi
done

log "archiving config"
tar -C "$WU_DIR" -czf "${tmp}/config.tar.gz" --ignore-failed-read \
  .env signup.env backup.env caddy.env profiles modules.env custom/lua_scripts sql 2>/dev/null || true

# Quick sanity check: every dump must decompress and end with mysqldump's completion line.
for f in "${tmp}"/*.sql.gz; do
  zcat "$f" | tail -n 1 | grep -q 'Dump completed' || { log "dump $f looks truncated"; exit 1; }
done
(cd "$tmp" && sha256sum -- * >SHA256SUMS)
mv "$tmp" "$dest"
trap - EXIT
log "wrote ${dest} ($(du -sh "$dest" | cut -f1))"

# Local retention: delete backup folders older than KEEP_DAYS days.
find "$BACKUP_ROOT" -mindepth 1 -maxdepth 1 -type d -name '20*' -mtime "+$((KEEP_DAYS - 1))" -print \
  | while read -r old; do log "removing old ${old}"; rm -rf -- "$old"; done

# Off-site copy (optional).
if [[ -n "${RESTIC_REPOSITORY:-}" ]]; then
  command -v restic >/dev/null || { log "RESTIC_REPOSITORY is set but restic is not installed"; exit 1; }
  if ! restic cat config >/dev/null 2>&1; then
    log "initialising restic repository"
    restic init
  fi
  log "restic backup ${dest}"
  restic backup --tag wrath --host wrath "$dest"
  restic forget --tag wrath --keep-daily 14 --keep-weekly 8 --keep-monthly 6 --prune
else
  log "RESTIC_REPOSITORY not set: off-site copy skipped"
fi
log "done"
