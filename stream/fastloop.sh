#!/usr/bin/env bash
# WrathUnleashed: the faster start's server half. Run by "Update sign-in and warm-up.bat" (one ssh).
#  1. wu-portal: a saved Hero Key signs in by itself on /wrath, and the realm list warms the browser
#     client (hidden iframe to https://wrath.openvanilla.app/warm.html) while the player reads it.
#  2. Caddy: the browser client's own files (our code, no game data) skip the sign-in gate, so that
#     warm-up can fetch them. /data, /ws, the page and /__env.js stay behind the gate as before.
# Backups first; a Caddy that refuses the change gets its old file back. Safe to run again.
set -euo pipefail
cd "$(dirname "$0")"
. "${WU_LIB:-/srv/wrath/stream/server/stream-lib.sh}" 2>/dev/null || { WU="${WU_DIR:-/srv/wrath}"; CF="${WU_CADDYFILE:-/opt/openvanilla-classicplus/Caddyfile}"; CADDY_DIR="${WU_CADDY_DIR:-/opt/wenilla-realm}";
  MARK_BEGIN="# >>> WrathUnleashed streaming (stream-up.sh)"; MARK_END="# <<< WrathUnleashed streaming";
  caddy_reload() { (cd "$CADDY_DIR" && docker compose exec -T caddy caddy reload --config /etc/caddy/Caddyfile --adapter caddyfile); }; }
TS=$(date +%Y%m%d-%H%M%S); BK=${WU_BACKUPS:-/root/fastloop-backups}/$TS; mkdir -p "$BK"

echo "== 1/2 sign-in page (wu-portal)"
cp -p "$WU/portal/wrath_portal.py" "$BK/wrath_portal.py"
python3 -I -c 'import ast,sys;ast.parse(open(sys.argv[1]).read())' wrath_portal.py
install -m 644 wrath_portal.py "$WU/portal/wrath_portal.py"
docker restart wu-portal >/dev/null
ok=""
for _ in $(seq 1 15); do
  if docker exec wu-portal python3 -c 'import urllib.request;urllib.request.urlopen("http://127.0.0.1:8091/wrath/status.json",timeout=5)' >/dev/null 2>&1; then ok=1; break; fi
  sleep 1
done
if [ -z "$ok" ]; then
  docker logs --tail 20 wu-portal >&2 || true
  cp -p "$BK/wrath_portal.py" "$WU/portal/wrath_portal.py"; docker restart wu-portal >/dev/null
  echo "ERROR: the new sign-in page didn't start; the old one is back." >&2; exit 1
fi
echo "  wu-portal is up with the new page"

echo "== 2/2 Caddy: the client's own files skip the sign-in gate"
cp -p "$CF" "$BK/Caddyfile"
if grep -q "$MARK_BEGIN" "$CF"; then
  python3 -I - "$CF" "$MARK_BEGIN" "$MARK_END" <<'PY'
import sys
p, b, e = sys.argv[1:4]
s = open(p).read()
i = s.index(b); j = s.index(e, i)
block = s[i:j]
if "@client path" in block:
    print("  already there"); sys.exit(0)
anchor = "\thandle {\n\t\tforward_auth"
if anchor not in block: sys.exit("the streaming block has no forward_auth handle to put the client route before")
add = ("\t# the browser client's own files (no game data) skip the gate, so the realm list can warm them\n"
       "\t@client path /warm.html /boot.js /wenilla.js /wenilla_bg.wasm /wasi_stubs.js /platform.js /bridge.js /automate.js /boot-manifest.json /world-manifest.json /snippets/*\n"
       "\thandle @client {\n"
       "\t\theader Cross-Origin-Resource-Policy same-site\n"
       "\t\treverse_proxy wu-play:8090\n"
       "\t}\n")
block = block.replace(anchor, add + anchor, 1)
with open(p, "r+") as f:
    f.seek(0); f.write(s[:i] + block + s[j:]); f.truncate()
print("  added")
PY
  if ! caddy_reload; then
    cat "$BK/Caddyfile" > "$CF"; caddy_reload || true
    echo "ERROR: Caddy refused the change; the old Caddyfile is back (the sign-in page update stays)." >&2; exit 1
  fi
else
  echo "  streaming is off (no streaming block): nothing to change; stream-up.sh adds it next time"
fi

echo "== check"
sleep 2
c1=$(curl -s -o /dev/null -w '%{http_code}' -m 20 https://wrath.openvanilla.app/warm.html || true)
c2=$(curl -s -o /dev/null -w '%{http_code}' -m 20 https://wrath.openvanilla.app/data/__index || true)
c3=$(curl -s -o /dev/null -w '%{http_code}' -m 20 https://play.openvanilla.app/wrath || true)
echo "  warm.html (public): $c1   /data (must stay gated, 302/401/403): $c2   /wrath signed out (200 = saved-key page): $c3"
echo "  backups: $BK"
echo "FASTLOOP OK"
