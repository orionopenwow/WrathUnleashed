#!/bin/bash
# The CMaNGOS databases (Leyline host kit, profiles cmangos-1.12.1 and cmangos-2.4.3: the same file in both), made
# by the project's own installer, InstallFullDB.sh of the database repo at the pinned commit, over the core's sql/
# folder at its pinned commit. Safe to run on every start:
#
#   * first run (no accounts table yet): InstallFullDB.sh -InstallAll (world, characters, realmd, logs, core updates);
#   * the pinned database commit changed: -World (the world only), then -UpdateCore;
#   * otherwise: -UpdateCore (applies only what the databases do not have yet).
#
# Accounts and characters are never dropped after the first run. The core's sample accounts (ADMINISTRATOR,
# GAMEMASTER, MODERATOR, PLAYER, whose passwords are public) are removed: players reach this realm through the relay.
# Then the realm list row is kept for this client build (the agent points its address at the relay).
set -euo pipefail
H="${DB_HOST:-realm-db}"
PW="${DB_ROOT_PASSWORD:?DB_ROOT_PASSWORD missing}"
case "$PW" in *[!A-Za-z0-9]*) echo "DB_ROOT_PASSWORD must be letters and digits (run the host kit's setup)" >&2; exit 1 ;; esac
export MYSQL_PWD="$PW"
DB=/opt/db
WANT="$(cat "$DB/.leyline-version")"
BUILD="$(cat "$DB/.leyline-build")"
EXP="$(cat "$DB/.leyline-expansion" | tr 'A-Z' 'a-z')"
REALM="${EXP}realmd"
q() { mariadb -h"$H" -uroot --max-allowed-packet=256M "$@"; }
has_table() { [ "$(q -N -B -e "SELECT COUNT(*) FROM information_schema.tables WHERE table_schema='$1' AND table_name='$2'")" -gt 0 ]; }

i=0
until q -e "SELECT 1" >/dev/null 2>&1; do
  i=$((i + 1)); [ "$i" -lt 60 ] || { echo "the database did not answer" >&2; exit 1; }; sleep 2
done

# The installer's own settings file (its variable names; the database names are its defaults).
cd "$DB"
cat > InstallFullDB.config <<EOF
MYSQL_HOST="$H"
MYSQL_PORT="3306"
MYSQL_USERNAME="mangos"
MYSQL_PASSWORD="$PW"
MYSQL_USERIP="%"
WORLD_DB_NAME="${EXP}mangos"
REALM_DB_NAME="${EXP}realmd"
CHAR_DB_NAME="${EXP}characters"
LOGS_DB_NAME="${EXP}logs"
MYSQL_PATH="$(command -v mariadb)"
MYSQL_DUMP_PATH="$(command -v mariadb-dump)"
CORE_PATH="/opt/core"
LOCALES="NO"
FORCE_WAIT="NO"
DEV_UPDATES="NO"
AHBOT="NO"
PLAYERBOTS_DB="NO"
EOF
chmod 600 InstallFullDB.config
run() { echo "== InstallFullDB.sh $1"; bash ./InstallFullDB.sh "$@" </dev/null; }

q -e "CREATE DATABASE IF NOT EXISTS leyline"
q leyline -e "CREATE TABLE IF NOT EXISTS state (k VARCHAR(32) PRIMARY KEY, v VARCHAR(128) NOT NULL)"
have="$(q -N -B leyline -e "SELECT v FROM state WHERE k='world'")"
if ! has_table "$REALM" account; then
  echo "creating the databases (the first start: 5-15 minutes)"
  run -InstallAll root "$PW" DeleteAll
elif [ "$have" != "$WANT" ]; then
  echo "loading the new world database (accounts and characters are kept)"
  run -World
  run -UpdateCore
else
  run -UpdateCore
fi
q leyline -e "REPLACE INTO state (k, v) VALUES ('world', '$WANT')"

q "$REALM" -e "DELETE FROM account WHERE username IN ('ADMINISTRATOR', 'GAMEMASTER', 'MODERATOR', 'PLAYER')
               AND joindate < '2007-01-01'"
q "$REALM" -e "INSERT INTO realmlist (id, name, address, port, icon, realmflags, timezone, allowedSecurityLevel,
               population, realmbuilds) VALUES (1, 'Leyline realm', '127.0.0.1', 8085, 1, 0, 1, 0, 0, '$BUILD')
               ON DUPLICATE KEY UPDATE realmbuilds = '$BUILD'"
echo "databases ready"
