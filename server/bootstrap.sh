#!/usr/bin/env bash
# WrathUnleashed: one-time (and safe to re-run) setup of a fresh Ubuntu 24.04 box.
#
#   Run as root, from the unpacked kit folder:   sudo ./bootstrap.sh
#
# What it does, in order (every step prints what it is doing):
#    1. checks it is root on Ubuntu 24.04
#    2. base packages, timezone UTC
#    3. user "wow" (docker group, passwordless sudo), SSH keys copied from root
#    4. SSH: key-only login (refuses if no key is installed, so you cannot lock yourself out)
#    5. fail2ban for sshd
#    6. ufw: only 22, 80, 443, 3724, 8085 in
#    7. unattended-upgrades (security updates, no automatic reboot)
#    8. Docker Engine + compose plugin from Docker's apt repo, log rotation
#    9. Caddy from Caddy's apt repo
#   10. /srv/wrath layout, kit files installed, secrets generated if missing (mode 600)
#   11. systemd units: nightly backup timer, signup service, Caddy env drop-in
#
# Environment knobs (optional):
#   WU_USER=wow            name of the non-root user
#   WU_ROOT_SSH=key        "key" = root may log in with a key only; "no" = root cannot log in
#   WU_DIR=/srv/wrath      install directory
#
# No secret is written in this file. Generated secrets go to /srv/wrath/.env and
# /srv/wrath/signup.env (mode 600, root-owned) and are never printed.

set -euo pipefail

WU_USER="${WU_USER:-wow}"
WU_ROOT_SSH="${WU_ROOT_SSH:-key}"
WU_DIR="${WU_DIR:-/srv/wrath}"
KIT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
export DEBIAN_FRONTEND=noninteractive

step=0
say()  { step=$((step + 1)); printf '\n\033[1;36m[%02d] %s\033[0m\n' "$step" "$*"; }
info() { printf '     %s\n' "$*"; }
warn() { printf '\033[1;33m     WARNING: %s\033[0m\n' "$*" >&2; }
die()  { printf '\033[1;31m     ERROR: %s\033[0m\n' "$*" >&2; exit 1; }

# Random secret without characters that could break the ";"-separated AzerothCore
# DATABASE_INFO strings, compose's ${} interpolation or SQL quoting: hex only.
rand_hex() { openssl rand -hex "$1"; }
# 16 letters/digits: AzerothCore passwords are at most 16 characters (MAX_PASS_STR).
rand_pass16() { tr -dc 'A-Za-z0-9' </dev/urandom | head -c 16 || true; }

# Adds KEY=VALUE to a file only if KEY is not already there (keeps owner edits).
ensure_kv() { # file key value
  local file="$1" key="$2" value="$3"
  if ! grep -q "^${key}=" "$file" 2>/dev/null; then
    printf '%s=%s\n' "$key" "$value" >>"$file"
    info "added ${key} to ${file}"
  fi
}

# ---------------------------------------------------------------------------------------------
say "Checking the system"
[[ $EUID -eq 0 ]] || die "run as root (sudo ./bootstrap.sh)"
# shellcheck disable=SC1091
. /etc/os-release
info "OS: ${PRETTY_NAME}"
if [[ "${ID}" != "ubuntu" || "${VERSION_ID}" != "24.04" ]]; then
  warn "this kit is written for Ubuntu 24.04; continuing anyway"
fi
info "kit folder: ${KIT_DIR}"

# ---------------------------------------------------------------------------------------------
say "Installing base packages (curl, gnupg, jq, rsync, restic, python3, zstd) and setting UTC"
apt-get update -q
apt-get install -y -q ca-certificates curl gnupg openssl jq rsync restic zstd python3 \
  debian-keyring debian-archive-keyring apt-transport-https
timedatectl set-timezone UTC || warn "could not set timezone"

# ---------------------------------------------------------------------------------------------
say "Creating the non-root user '${WU_USER}'"
if id "${WU_USER}" >/dev/null 2>&1; then
  info "user ${WU_USER} already exists"
else
  adduser --disabled-password --gecos "WrathUnleashed admin" "${WU_USER}"
  info "created ${WU_USER} (no password; SSH key login only)"
fi
# Passwordless sudo: the account has no password, and it is in the docker group anyway
# (which is root-equivalent), so a sudo password would add no real protection.
SUDOERS="/etc/sudoers.d/90-${WU_USER}"
printf '%s ALL=(ALL) NOPASSWD:ALL\n' "${WU_USER}" >"${SUDOERS}.tmp"
chmod 440 "${SUDOERS}.tmp"
visudo -cf "${SUDOERS}.tmp" >/dev/null && mv "${SUDOERS}.tmp" "${SUDOERS}"
info "sudo rule: ${SUDOERS}"

# Copy root's authorized keys (Hetzner puts the key you ordered with there).
WU_HOME="$(getent passwd "${WU_USER}" | cut -d: -f6)"
install -d -m 700 -o "${WU_USER}" -g "${WU_USER}" "${WU_HOME}/.ssh"
if [[ -s /root/.ssh/authorized_keys ]]; then
  touch "${WU_HOME}/.ssh/authorized_keys"
  # Append only keys that are not there yet (idempotent).
  while IFS= read -r line; do
    [[ -z "$line" || "$line" == \#* ]] && continue
    grep -qxF "$line" "${WU_HOME}/.ssh/authorized_keys" || printf '%s\n' "$line" >>"${WU_HOME}/.ssh/authorized_keys"
  done </root/.ssh/authorized_keys
  chown "${WU_USER}:${WU_USER}" "${WU_HOME}/.ssh/authorized_keys"
  chmod 600 "${WU_HOME}/.ssh/authorized_keys"
  info "copied root's SSH keys to ${WU_HOME}/.ssh/authorized_keys"
fi

# ---------------------------------------------------------------------------------------------
say "Hardening SSH (key-only login)"
if [[ ! -s "${WU_HOME}/.ssh/authorized_keys" && ! -s /root/.ssh/authorized_keys ]]; then
  warn "no SSH public key is installed for root or ${WU_USER}."
  warn "password login stays ON so you are not locked out. Add a key, then re-run."
else
  if [[ "${WU_ROOT_SSH}" == "no" ]]; then root_login="no"; else root_login="prohibit-password"; fi
  # Ubuntu reads sshd_config.d/*.conf first and the FIRST value of a setting wins, so a
  # "10-" file beats cloud-init's "50-cloud-init.conf".
  cat >/etc/ssh/sshd_config.d/10-wrath.conf <<EOF
# Written by WrathUnleashed bootstrap.sh
PasswordAuthentication no
KbdInteractiveAuthentication no
PubkeyAuthentication yes
PermitRootLogin ${root_login}
MaxAuthTries 4
X11Forwarding no
EOF
  sshd -t || die "sshd config test failed; not reloading (see /etc/ssh/sshd_config.d/10-wrath.conf)"
  systemctl try-reload-or-restart ssh.service || true
  info "password login off, root login: ${root_login}"
  info "TEST NOW in a second terminal: ssh ${WU_USER}@<this-box>  (keep this session open)"
fi

# ---------------------------------------------------------------------------------------------
say "Installing fail2ban (sshd jail)"
apt-get install -y -q fail2ban python3-systemd
cat >/etc/fail2ban/jail.d/wrath.conf <<'EOF'
# Written by WrathUnleashed bootstrap.sh
[DEFAULT]
bantime  = 1h
findtime = 10m
maxretry = 5
backend  = systemd

[sshd]
enabled = true
EOF
systemctl enable --now fail2ban
systemctl restart fail2ban
info "fail2ban active: $(systemctl is-active fail2ban)"

# ---------------------------------------------------------------------------------------------
say "Configuring the firewall (ufw): 22, 80, 443, 3724, 8085 in; everything else dropped"
apt-get install -y -q ufw
ufw default deny incoming >/dev/null
ufw default allow outgoing >/dev/null
ufw allow 22/tcp   comment 'ssh'                 >/dev/null
ufw allow 80/tcp   comment 'http (caddy, acme)'  >/dev/null
ufw allow 443/tcp  comment 'https (caddy)'       >/dev/null
ufw allow 443/udp  comment 'http/3 (caddy)'      >/dev/null
ufw allow 3724/tcp comment 'wow authserver'      >/dev/null
ufw allow 8085/tcp comment 'wow worldserver'     >/dev/null
ufw --force enable >/dev/null
ufw status verbose | sed 's/^/     /'
info "NOTE: Docker-published ports bypass ufw. The compose file therefore binds SOAP and"
info "      every admin port to 127.0.0.1; only 3724 and 8085 are published publicly."

# ---------------------------------------------------------------------------------------------
say "Enabling unattended security upgrades (no automatic reboot)"
apt-get install -y -q unattended-upgrades
cat >/etc/apt/apt.conf.d/20auto-upgrades <<'EOF'
APT::Periodic::Update-Package-Lists "1";
APT::Periodic::Unattended-Upgrade "1";
APT::Periodic::AutocleanInterval "7";
EOF
cat >/etc/apt/apt.conf.d/52wrath-unattended <<'EOF'
// Written by WrathUnleashed bootstrap.sh. Reboots are the owner's call (players are online).
Unattended-Upgrade::Automatic-Reboot "false";
Unattended-Upgrade::Remove-Unused-Dependencies "true";
EOF
systemctl enable --now unattended-upgrades
info "Docker and Caddy come from their own repos and are NOT auto-upgraded (no surprise restarts)."

# ---------------------------------------------------------------------------------------------
say "Installing Docker Engine + compose plugin from Docker's apt repository"
install -m 0755 -d /etc/apt/keyrings
if [[ ! -s /etc/apt/keyrings/docker.asc ]]; then
  curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
  chmod a+r /etc/apt/keyrings/docker.asc
fi
cat >/etc/apt/sources.list.d/docker.sources <<EOF
Types: deb
URIs: https://download.docker.com/linux/ubuntu
Suites: ${UBUNTU_CODENAME:-$VERSION_CODENAME}
Components: stable
Architectures: $(dpkg --print-architecture)
Signed-By: /etc/apt/keyrings/docker.asc
EOF
apt-get update -q
apt-get install -y -q docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
# Log rotation for every container (the compose file also sets it per service).
if [[ ! -s /etc/docker/daemon.json ]]; then
  cat >/etc/docker/daemon.json <<'EOF'
{
  "log-driver": "json-file",
  "log-opts": { "max-size": "50m", "max-file": "5" },
  "live-restore": true
}
EOF
  info "wrote /etc/docker/daemon.json (log rotation, live-restore)"
  docker_needs_restart=1
fi
systemctl enable --now docker
# Restart only when daemon.json was just written, so a re-run never bounces a live realm.
if [[ "${docker_needs_restart:-0}" == 1 ]]; then systemctl restart docker; fi
usermod -aG docker "${WU_USER}"
info "$(docker --version)"
info "$(docker compose version)"

# ---------------------------------------------------------------------------------------------
say "Installing Caddy from Caddy's apt repository"
if [[ ! -s /usr/share/keyrings/caddy-stable-archive-keyring.gpg ]]; then
  curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' \
    | gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
  chmod o+r /usr/share/keyrings/caddy-stable-archive-keyring.gpg
fi
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' \
  >/etc/apt/sources.list.d/caddy-stable.list
chmod o+r /etc/apt/sources.list.d/caddy-stable.list
apt-get update -q
apt-get install -y -q caddy
info "$(caddy version)"

# ---------------------------------------------------------------------------------------------
say "Creating ${WU_DIR} and installing the kit files"
install -d -m 755 -o "${WU_USER}" -g "${WU_USER}" \
  "${WU_DIR}" "${WU_DIR}/profiles" "${WU_DIR}/custom" "${WU_DIR}/custom/lua_scripts" \
  "${WU_DIR}/sql" "${WU_DIR}/upload" "${WU_DIR}/site" "${WU_DIR}/signup"
# Client data (dbc/maps/vmaps/mmaps) lives here, bound into the ov-client-data volume.
# It is outside site/ and Caddy never serves it.
install -d -m 755 "${WU_DIR}/client-data"
# Backups hold DB dumps and a copy of .env: root only.
install -d -m 700 "${WU_DIR}/backups"
# AzerothCore containers run as uid 1000 ("acore"); their log dirs must be writable by it.
install -d -m 755 -o 1000 -g 1000 "${WU_DIR}/logs" "${WU_DIR}/logs/auth" "${WU_DIR}/logs/world"

# Kit files are copied when missing. Re-running keeps your edits (e.g. to the compose file or
# the Caddyfile); set WU_FORCE_KIT=1 to overwrite them with the kit's versions.
copy_kit() { # source-relative-path dest mode
  local src="${KIT_DIR}/$1" dst="$2" mode="$3"
  if [[ ! -f "$src" ]]; then warn "kit file $1 not found next to bootstrap.sh"; return 0; fi
  if [[ "$(readlink -f "$src")" == "$(readlink -f "$dst" 2>/dev/null || true)" ]]; then return 0; fi
  if [[ -e "$dst" && "${WU_FORCE_KIT:-0}" != 1 ]]; then
    cmp -s "$src" "$dst" || info "kept your ${dst} (differs from the kit; WU_FORCE_KIT=1 replaces it)"
    return 0
  fi
  install -m "$mode" "$src" "$dst"
  info "installed ${dst}"
}
for f in docker-compose.prod.yml Caddyfile; do copy_kit "$f" "${WU_DIR}/${f}" 644; done
for f in set-realm-address.sh backup.sh restore.sh soap-cmd.sh; do copy_kit "$f" "${WU_DIR}/${f}" 755; done
copy_kit signup/signup.py "${WU_DIR}/signup/signup.py" 644
# Example env files, for reference only.
for f in env.example backup.env.example signup/signup.env.example; do
  if [[ -f "${KIT_DIR}/${f}" && "${KIT_DIR}" != "${WU_DIR}" ]]; then
    install -m 644 "${KIT_DIR}/${f}" "${WU_DIR}/${f}"
  fi
done
# The placeholder site page is copied only once: after that site/ belongs to the owner.
if [[ ! -e "${WU_DIR}/site/index.html" && -f "${KIT_DIR}/site/index.html" ]]; then
  install -m 644 -o "${WU_USER}" -g "${WU_USER}" "${KIT_DIR}/site/index.html" "${WU_DIR}/site/index.html"
  info "installed placeholder ${WU_DIR}/site/index.html"
fi

# ---------------------------------------------------------------------------------------------
say "Generating secrets if missing (never printed; mode 600)"
ENV_FILE="${WU_DIR}/.env"
umask 077
touch "${ENV_FILE}"
# Owned by the admin user so a plain `docker compose` (run as wow) can read it; still 600.
chown "${WU_USER}:${WU_USER}" "${ENV_FILE}"
chmod 600 "${ENV_FILE}"
if ! grep -q '^DB_ROOT_PASSWORD=' "${ENV_FILE}"; then
  printf '# Generated by bootstrap.sh on %s. Keep this file secret.\n' "$(date -u +%F)" >>"${ENV_FILE}"
  printf 'DB_ROOT_PASSWORD=%s\n' "$(rand_hex 24)" >>"${ENV_FILE}"
  info "generated DB_ROOT_PASSWORD in ${ENV_FILE}"
else
  info "DB_ROOT_PASSWORD already set in ${ENV_FILE} (kept)"
fi
# Non-secret defaults (only added when missing, so owner edits stay).
ensure_kv "${ENV_FILE}" COMPOSE_FILE docker-compose.prod.yml
ensure_kv "${ENV_FILE}" OV_IMAGE ov/ac-wotlk
ensure_kv "${ENV_FILE}" OV_TAG custom
ensure_kv "${ENV_FILE}" OV_PROFILE brawl
ensure_kv "${ENV_FILE}" OV_PATHING 0
ensure_kv "${ENV_FILE}" DB_BUFFER_POOL_SIZE 8G

SIGNUP_ENV="${WU_DIR}/signup.env"
touch "${SIGNUP_ENV}"
chown root:root "${SIGNUP_ENV}"
chmod 600 "${SIGNUP_ENV}"
if ! grep -q '^SOAP_PASS=' "${SIGNUP_ENV}"; then
  {
    printf '# Generated by bootstrap.sh on %s. Keep this file secret.\n' "$(date -u +%F)"
    printf '# The worldserver GM account the signup service (and soap-cmd.sh) log in as.\n'
    printf '# Create it once in the worldserver console, see RUNBOOK step 8.\n'
    printf 'SOAP_USER=SOAPSVC\n'
    printf 'SOAP_PASS=%s\n' "$(rand_pass16)"
    printf 'SOAP_URL=http://127.0.0.1:7878/\n'
    printf '# Optional Cloudflare Turnstile (leave empty to disable):\n'
    printf 'TURNSTILE_SITEKEY=\n'
    printf 'TURNSTILE_SECRET=\n'
    printf 'SIGNUP_PER_IP_PER_HOUR=3\n'
  } >>"${SIGNUP_ENV}"
  info "generated SOAP_USER/SOAP_PASS in ${SIGNUP_ENV}"
else
  info "SOAP credentials already set in ${SIGNUP_ENV} (kept)"
fi

BACKUP_ENV="${WU_DIR}/backup.env"
if [[ ! -e "${BACKUP_ENV}" ]]; then
  printf '# Optional restic off-site copy; see backup.env.example. Empty = local only.\n' >"${BACKUP_ENV}"
  chmod 600 "${BACKUP_ENV}"
  info "created empty ${BACKUP_ENV}"
fi

CADDY_ENV="${WU_DIR}/caddy.env"
if [[ ! -e "${CADDY_ENV}" ]]; then
  printf '# Your domain WITHOUT "play.", e.g. DOMAIN=example.com -> https://play.example.com\nDOMAIN=example.invalid\n' >"${CADDY_ENV}"
  chmod 644 "${CADDY_ENV}"
  info "created ${CADDY_ENV}: set DOMAIN before starting Caddy"
fi
umask 022

# ---------------------------------------------------------------------------------------------
say "Installing systemd units (backup timer, signup service, Caddy settings)"
for u in wu-backup.service wu-backup.timer wu-signup.service; do
  if [[ -f "${KIT_DIR}/systemd/${u}" ]]; then
    install -m 644 "${KIT_DIR}/systemd/${u}" "/etc/systemd/system/${u}"
    info "installed /etc/systemd/system/${u}"
  else
    warn "kit file systemd/${u} not found"
  fi
done
# Caddy: read DOMAIN from caddy.env and load /srv/wrath/Caddyfile.
install -d /etc/systemd/system/caddy.service.d
cat >/etc/systemd/system/caddy.service.d/wrath.conf <<EOF
# Written by WrathUnleashed bootstrap.sh: DOMAIN for the Caddyfile's {\$DOMAIN}.
[Service]
EnvironmentFile=${CADDY_ENV}
EOF
if ! grep -q "import ${WU_DIR}/Caddyfile" /etc/caddy/Caddyfile 2>/dev/null; then
  [[ -f /etc/caddy/Caddyfile ]] && cp -n /etc/caddy/Caddyfile /etc/caddy/Caddyfile.dist || true
  printf '# Written by WrathUnleashed bootstrap.sh; edit %s/Caddyfile instead.\nimport %s/Caddyfile\n' \
    "${WU_DIR}" "${WU_DIR}" >/etc/caddy/Caddyfile
  info "/etc/caddy/Caddyfile now imports ${WU_DIR}/Caddyfile"
fi
systemctl daemon-reload
systemctl enable --now wu-backup.timer
systemctl enable wu-signup.service
if grep -q '^DOMAIN=example.invalid' "${CADDY_ENV}"; then
  info "Caddy not reloaded yet: set DOMAIN in ${CADDY_ENV}, then: systemctl restart caddy"
else
  systemctl restart caddy && info "caddy restarted"
fi
info "wu-signup enabled; start it after the SOAP account exists: systemctl start wu-signup"

# ---------------------------------------------------------------------------------------------
say "Done"
info "Next (RUNBOOK.md): upload profiles/modules.env/lua_scripts and client data,"
info "load or build the realm image, then: cd ${WU_DIR} && docker compose up -d"
info "Log out and back in as ${WU_USER} so the docker group applies."
