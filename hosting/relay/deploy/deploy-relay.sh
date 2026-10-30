#!/usr/bin/env bash
# Deploys wu-relay to a fresh Ubuntu 22.04+/Debian 12 VM. NOT RUN YET: needs the owner's OK, a VM
# and the DNS record (relay.openvanilla.app A -> the VM's IPv4, no AAAA).
#
#   bash relay/deploy/deploy-relay.sh root@203.0.113.20 [ssh-key]
#
# The owner's servers rate-limit SSH logins (about 6 per 30 s), so this uses exactly TWO connections:
# one scp of a single tarball, one ssh that runs remote-install.sh from inside it.
set -euo pipefail
TARGET="${1:?usage: deploy-relay.sh user@host [ssh-key]}"
KEY="${2:-}"
HOSTING="$(cd "$(dirname "$0")/../.." && pwd)"
SSH_OPTS=(-o ConnectTimeout=15 -o ServerAliveInterval=20)
[ -n "$KEY" ] && SSH_OPTS+=(-i "$KEY")
TAR="$(mktemp -t wu-relay-XXXX).tgz"
trap 'rm -f "$TAR"' EXIT
tar -C "$HOSTING" --exclude='__pycache__' -czf "$TAR" \
  kit/tools/wunet relay/wurelay relay/Dockerfile relay/deploy
echo "[1/2] upload ($(du -h "$TAR" | cut -f1))"
scp "${SSH_OPTS[@]}" -q "$TAR" "$TARGET:/tmp/wu-relay.tgz"
echo "[2/2] install and start"
ssh "${SSH_OPTS[@]}" "$TARGET" 'set -e; rm -rf /tmp/wu-relay-src; mkdir -p /tmp/wu-relay-src; tar -C /tmp/wu-relay-src -xzf /tmp/wu-relay.tgz; bash /tmp/wu-relay-src/relay/deploy/remote-install.sh /tmp/wu-relay-src; rm -rf /tmp/wu-relay-src /tmp/wu-relay.tgz'
