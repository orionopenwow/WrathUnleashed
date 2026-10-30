#!/usr/bin/env bash
# WrathUnleashed: the faster start's server half. Run by "Update sign-in and warm-up.bat" (one ssh).
#  1. wu-portal: a saved Hero Key signs in by itself on /wrath, and the realm list warms the browser
#     client (hidden iframe to https://wrath.openvanilla.app/warm.html) while the player reads it.
#     Its art and theme (www-files/art: the starfield, corners, dragons, divider, Cinzel, wu-theme.css, the
#     link-preview card) go to $WU/portal/art, which wu-portal serves at /wrath/art/ (its /app is $WU/portal).
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
had_links=""
if [ -f "$WU/portal/links.py" ]; then cp -p "$WU/portal/links.py" "$BK/links.py"; had_links=1; fi
had_demo=""
if [ -f "$WU/portal/demo.py" ]; then cp -p "$WU/portal/demo.py" "$BK/demo.py"; had_demo=1; fi
had_armory=""
if [ -f "$WU/portal/armory.py" ]; then cp -p "$WU/portal/armory.py" "$BK/armory.py"; had_armory=1; fi
had_modes=""
if [ -f "$WU/portal/modes.py" ]; then cp -p "$WU/portal/modes.py" "$BK/"; [ ! -f "$WU/portal/modes_data.py" ] || cp -p "$WU/portal/modes_data.py" "$BK/"; had_modes=1; fi
had_play=""
if [ -f "$WU/portal/playmodes.py" ]; then cp -p "$WU/portal/playmodes.py" "$BK/"; [ ! -f "$WU/portal/playmodes.json" ] || cp -p "$WU/portal/playmodes.json" "$BK/"; had_play=1; fi
had_workshop=""
if [ -f "$WU/portal/workshop.py" ]; then cp -p "$WU/portal/workshop.py" "$BK/workshop.py"; had_workshop=1; fi
had_creations=""
if [ -f "$WU/portal/creations.py" ]; then cp -p "$WU/portal/creations.py" "$BK/creations.py"; had_creations=1; fi
had_docs=""
if [ -f "$WU/portal/docs.py" ]; then cp -p "$WU/portal/docs.py" "$BK/docs.py"; had_docs=1; fi
had_docdir=""
rm -rf "$BK/docs"
if [ -d "$WU/portal/docs" ]; then cp -a "$WU/portal/docs" "$BK/docs"; had_docdir=1; fi
had_host=""
if [ -f "$WU/portal/hostflow.py" ]; then cp -p "$WU/portal/hostflow.py" "$BK/"; [ ! -f "$WU/portal/ed25519_pure.py" ] || cp -p "$WU/portal/ed25519_pure.py" "$BK/"; had_host=1; fi
had_herokey=""
if [ -f "$WU/portal/herokey_sso.py" ]; then cp -p "$WU/portal/herokey_sso.py" "$BK/herokey_sso.py"; had_herokey=1; fi
had_projects=""
if [ -f "$WU/portal/projects.py" ]; then cp -p "$WU/portal/projects.py" "$BK/projects.py"; had_projects=1; fi
had_social=""
if [ -f "$WU/portal/social.py" ]; then cp -p "$WU/portal/social.py" "$BK/social.py"; had_social=1; fi
had_network=""
if [ -f "$WU/portal/network.py" ]; then cp -p "$WU/portal/network.py" "$BK/network.py"; had_network=1; fi
had_admin=""
if [ -f "$WU/portal/admin.py" ]; then cp -p "$WU/portal/admin.py" "$BK/"; [ ! -f "$WU/portal/wu-mod.py" ] || cp -p "$WU/portal/wu-mod.py" "$BK/"; had_admin=1; fi
had_hub=""
rm -rf "$BK/hub"
if [ -f "$WU/portal/hub.py" ]; then cp -p "$WU/portal/hub.py" "$BK/hub.py"; [ ! -d "$WU/portal/hub" ] || cp -a "$WU/portal/hub" "$BK/hub"; had_hub=1; fi
had_rank=""
if [ -f "$WU/portal/hub_rank.py" ]; then cp -p "$WU/portal/hub_rank.py" "$BK/hub_rank.py"; had_rank=1; fi
had_art=""
rm -rf "$BK/art"
if [ -d "$WU/portal/art" ]; then cp -a "$WU/portal/art" "$BK/art"; had_art=1; fi
put_back() {
  cp -p "$BK/wrath_portal.py" "$WU/portal/wrath_portal.py"
  if [ -n "$had_links" ]; then cp -p "$BK/links.py" "$WU/portal/links.py"; else rm -f "$WU/portal/links.py"; fi
  if [ -n "$had_demo" ]; then cp -p "$BK/demo.py" "$WU/portal/demo.py"; else rm -f "$WU/portal/demo.py"; fi
  if [ -n "$had_armory" ]; then cp -p "$BK/armory.py" "$WU/portal/armory.py"; else rm -f "$WU/portal/armory.py"; fi
  if [ -n "$had_modes" ]; then cp -p "$BK/modes.py" "$WU/portal/modes.py"; [ ! -f "$BK/modes_data.py" ] || cp -p "$BK/modes_data.py" "$WU/portal/modes_data.py"
  else rm -f "$WU/portal/modes.py" "$WU/portal/modes_data.py"; fi
  if [ -n "$had_play" ]; then cp -p "$BK/playmodes.py" "$WU/portal/playmodes.py"; [ ! -f "$BK/playmodes.json" ] || cp -p "$BK/playmodes.json" "$WU/portal/playmodes.json"
  else rm -f "$WU/portal/playmodes.py" "$WU/portal/playmodes.json"; fi
  if [ -n "$had_workshop" ]; then cp -p "$BK/workshop.py" "$WU/portal/workshop.py"; else rm -f "$WU/portal/workshop.py"; fi
  if [ -n "$had_creations" ]; then cp -p "$BK/creations.py" "$WU/portal/creations.py"; else rm -f "$WU/portal/creations.py"; fi
  if [ -n "$had_docs" ]; then cp -p "$BK/docs.py" "$WU/portal/docs.py"; else rm -f "$WU/portal/docs.py"; fi
  rm -rf "$WU/portal/docs"
  if [ -n "$had_docdir" ]; then cp -a "$BK/docs" "$WU/portal/docs"; fi
  if [ -n "$had_host" ]; then cp -p "$BK/hostflow.py" "$WU/portal/hostflow.py"; [ ! -f "$BK/ed25519_pure.py" ] || cp -p "$BK/ed25519_pure.py" "$WU/portal/"
  else rm -f "$WU/portal/hostflow.py"; fi
  if [ -n "$had_herokey" ]; then cp -p "$BK/herokey_sso.py" "$WU/portal/herokey_sso.py"; else rm -f "$WU/portal/herokey_sso.py"; fi
  if [ -n "$had_projects" ]; then cp -p "$BK/projects.py" "$WU/portal/projects.py"; else rm -f "$WU/portal/projects.py"; fi
  if [ -n "$had_social" ]; then cp -p "$BK/social.py" "$WU/portal/social.py"; else rm -f "$WU/portal/social.py"; fi
  if [ -n "$had_network" ]; then cp -p "$BK/network.py" "$WU/portal/network.py"; else rm -f "$WU/portal/network.py"; fi
  if [ -n "$had_admin" ]; then cp -p "$BK/admin.py" "$WU/portal/admin.py"; [ ! -f "$BK/wu-mod.py" ] || cp -p "$BK/wu-mod.py" "$WU/portal/"
  else rm -f "$WU/portal/admin.py" "$WU/portal/wu-mod.py"; fi
  rm -rf "$WU/portal/hub"
  if [ -n "$had_hub" ]; then cp -p "$BK/hub.py" "$WU/portal/hub.py"; [ ! -d "$BK/hub" ] || cp -a "$BK/hub" "$WU/portal/hub"
  else rm -f "$WU/portal/hub.py"; fi
  if [ -n "$had_rank" ]; then cp -p "$BK/hub_rank.py" "$WU/portal/hub_rank.py"; else rm -f "$WU/portal/hub_rank.py"; fi
  rm -rf "$WU/portal/art"
  if [ -n "$had_art" ]; then cp -a "$BK/art" "$WU/portal/art"; fi
}
python3 -I -c 'import ast,sys;ast.parse(open(sys.argv[1]).read())' wrath_portal.py
install -m 644 wrath_portal.py "$WU/portal/wrath_portal.py"
# the share links (/wrath/r/<id> and friends): optional, the portal runs without them
if [ -f links.py ]; then python3 -I -c 'import ast,sys;ast.parse(open(sys.argv[1]).read())' links.py && install -m 644 links.py "$WU/portal/links.py"; fi
# the Modes hub (/wrath/modes and the go intent): modes.py and its data, optional, always as a pair
if [ -f modes.py ] && [ -f modes_data.py ]; then
  python3 -I -c 'import ast,sys;[ast.parse(open(f).read()) for f in sys.argv[1:]]' modes.py modes_data.py \
    && install -m 644 modes.py modes_data.py "$WU/portal/"
fi
# the game modes (/wrath/modes.json, Games on /wrath/modes, ?go=mode:): playmodes.py and its catalog, optional, always as a pair
if [ -f playmodes.py ] && [ -f playmodes.json ]; then
  python3 -I -c 'import ast,sys,json;ast.parse(open(sys.argv[1]).read());json.load(open(sys.argv[2]))' playmodes.py playmodes.json \
    && python3 -I playmodes.py --check playmodes.json >/dev/null && install -m 644 playmodes.py playmodes.json "$WU/portal/"
fi
# the guest pass (demo.py): off unless portal.env has WU_GUEST_DEMO=1
if [ -f demo.py ]; then python3 -I -c 'import ast,sys;ast.parse(open(sys.argv[1]).read())' demo.py && install -m 644 demo.py "$WU/portal/demo.py"; fi
# the web armory (/wrath/armory): optional; it reads $WU/portal/armory/, which armory-export.py fills (realm/serverpass.sh)
if [ -f armory.py ]; then python3 -I -c 'import ast,sys;ast.parse(open(sys.argv[1]).read())' armory.py && install -m 644 armory.py "$WU/portal/armory.py"; fi
# the mods Workshop (/wrath/mods): optional; its data comes from the "mods" step ($WU/portal/mods)
if [ -f workshop.py ]; then python3 -I -c 'import ast,sys;ast.parse(open(sys.argv[1]).read())' workshop.py && install -m 644 workshop.py "$WU/portal/workshop.py"; fi
# the Workshop of player creations (/wrath/workshop): optional; it reads $WU/portal/workshop/, which
# workshop-export.py fills (realm/serverpass.sh step 1c)
if [ -f creations.py ]; then python3 -I -c 'import ast,sys;ast.parse(open(sys.argv[1]).read())' creations.py && install -m 644 creations.py "$WU/portal/creations.py"; fi
# the Leyline docs (/wrath/docs): docs.py and its pages (docs/leyline/*.md), optional, always as a pair
if [ -f docs.py ] && [ -f docs/leyline/index.md ]; then
  python3 -I -c 'import ast,sys;ast.parse(open(sys.argv[1]).read())' docs.py && {
    install -m 644 docs.py "$WU/portal/docs.py"
    rm -rf "$WU/portal/docs/leyline"; install -d -m 755 "$WU/portal/docs/leyline"
    install -m 644 docs/leyline/*.md "$WU/portal/docs/leyline/"
    echo "  docs: $(ls docs/leyline/*.md | wc -l) pages -> $WU/portal/docs/leyline"
  }
fi
# "+ Your server" (/wrath/host): hostflow.py and the kit's Ed25519, optional, always as a pair. Its pending
# realms live in $WU/hosted, mounted writable at /hosted: a portal made before that mount is made again once.
if [ -f hostflow.py ] && [ -f ed25519_pure.py ]; then
  python3 -I -c 'import ast,sys;[ast.parse(open(f).read()) for f in sys.argv[1:]]' hostflow.py ed25519_pure.py \
    && install -m 644 hostflow.py ed25519_pure.py "$WU/portal/"
  install -d -m 700 "$WU/hosted"
fi
# Hero Key sign-in on Beacons (herokey_sso.py, docs/HERO-KEY-SSO.md): optional, and idle until the herokey_sso flag is
# on. It signs with `cryptography` when the image has it, else the kit's ed25519_pure.py (installed above with hostflow,
# or here). Its key files are made in $WU/portal-data/leyline (/data/leyline, 0600) on first use.
if [ -f herokey_sso.py ]; then
  python3 -I -c 'import ast,sys;ast.parse(open(sys.argv[1]).read())' herokey_sso.py && install -m 644 herokey_sso.py "$WU/portal/herokey_sso.py"
  if [ -f ed25519_pure.py ] && [ ! -f "$WU/portal/ed25519_pure.py" ]; then install -m 644 ed25519_pure.py "$WU/portal/"; fi
fi
# its community links (stream/projects.py): stored in $WU/portal-data (wu-portal's /data, mounted by stream-lib.sh/deploy.sh)
if [ -f projects.py ]; then python3 -I -c 'import ast,sys;ast.parse(open(sys.argv[1]).read())' projects.py && install -m 644 projects.py "$WU/portal/projects.py"; fi
# Leyline's flags.json and the Host pack listing (stream/leyline_net.py): flags live in $WU/portal-data/leyline (/data)
if [ -f leyline_net.py ]; then python3 -I -c 'import ast,sys;ast.parse(open(sys.argv[1]).read())' leyline_net.py && install -m 644 leyline_net.py "$WU/portal/leyline_net.py"
  install -d -m 755 "$WU/portal-data/leyline"
  if [ -f hostpack.json ]; then python3 -I -c 'import json,sys;json.load(open(sys.argv[1]))' hostpack.json && install -m 644 hostpack.json "$WU/portal/hostpack.json"; fi
fi
# Leyline friends and messages (/wrath/api/social, /wrath/link): optional; its store is $WU/portal-data/social.sqlite3
if [ -f social.py ]; then python3 -I -c 'import ast,sys;ast.parse(open(sys.argv[1]).read())' social.py && install -m 644 social.py "$WU/portal/social.py"; fi
# the Leyline network (/wrath/realms in the network's order, /wrath/realms.json, realm reports): optional; its reports
# live in $WU/portal-data/network (/data/network)
if [ -f network.py ]; then python3 -I -c 'import ast,sys;ast.parse(open(sys.argv[1]).read())' network.py && install -m 644 network.py "$WU/portal/network.py"; fi
# the Leyline Admin Console (/wrath/admin, staff only): admin.py, and wu-mod.py for its "re-run the checker". Its files
# live in $WU/portal-data/admin and $WU/portal-data/leyline (wu-portal's writable /data)
if [ -f admin.py ]; then
  python3 -I -c 'import ast,sys;ast.parse(open(sys.argv[1]).read())' admin.py && install -m 644 admin.py "$WU/portal/admin.py"
  if [ -f wu-mod.py ]; then python3 -I -c 'import ast,sys;ast.parse(open(sys.argv[1]).read())' wu-mod.py && install -m 644 wu-mod.py "$WU/portal/wu-mod.py"; fi
fi
# the hidden Leyline hub (/wrath/leyline-preview, stream/hub.py) and its index (hub/*.json): optional, always as a pair.
# Its submissions queue lives in $WU/portal-data/hub (the writable /data mount).
if [ -f hub.py ] && [ -f hub/community-index.json ]; then
  python3 -I -c 'import ast,sys,json;ast.parse(open(sys.argv[1]).read());json.load(open(sys.argv[2]))' hub.py hub/community-index.json && {
    install -m 644 hub.py "$WU/portal/hub.py"
    rm -rf "$WU/portal/hub"; install -d -m 755 "$WU/portal/hub"
    install -m 644 hub/*.json "$WU/portal/hub/"
    echo "  hub: $(ls hub/*.json | wc -l) data files -> $WU/portal/hub"
  }
fi
# the hub rankings (/wrath/leyline/mods.json, /wrath/api/hub/*: stream/hub_rank.py): optional; its store is
# $WU/portal-data/hub_rank.sqlite3 (the writable /data mount)
if [ -f hub_rank.py ]; then python3 -I -c 'import ast,sys;ast.parse(open(sys.argv[1]).read())' hub_rank.py && install -m 644 hub_rank.py "$WU/portal/hub_rank.py"; fi
if [ -d www-files/art ] && [ -f www-files/art/wu-theme.css ]; then
  install -d -m 755 "$WU/portal/art"
  install -m 644 www-files/art/* "$WU/portal/art/"
  echo "  art: $(ls www-files/art | wc -l) files -> $WU/portal/art"
else
  echo "  WARNING: no www-files/art in the upload: the pages keep the art they had (or plain CSS without it)"
fi
# The host flow's pending realms live in $WU/hosted (/hosted) and the Workshop's community links in $WU/portal-data, mounted writable at /data (the only writable
# mount; /app stays read-only). A wu-portal from before that mount is recreated once, exactly as deploy.sh and
# stream-lib.sh's recreate_portal make it, plus the mount; the old container is kept, stopped, until the new
# one answers, and comes back if it doesn't.
install -d -m 755 "$WU/portal-data"; install -d -m 700 "$WU/hosted"
PORTAL_NET="${NET:-wenilla-realm_default}"
recreated=""
mounts=$(docker inspect -f '{{range .Mounts}}{{println .Destination}}{{end}}' wu-portal 2>/dev/null || true)
if printf '%s\n' "$mounts" | grep -qx /data && printf '%s\n' "$mounts" | grep -qx /hosted; then
  docker restart wu-portal >/dev/null
else
  echo "  wu-portal is missing its /data or /hosted mount: recreating it with $WU/portal-data at /data and $WU/hosted at /hosted (the old one is kept until the new one answers)"
  docker rm -f wu-portal-before-data >/dev/null 2>&1 || true
  if docker inspect wu-portal >/dev/null 2>&1; then
    docker stop wu-portal >/dev/null
    docker rename wu-portal wu-portal-before-data
    recreated=1
  else
    recreated=new
  fi
  docker image inspect python:3.12-alpine >/dev/null 2>&1 || docker pull -q python:3.12-alpine >/dev/null
  docker run -d --name wu-portal --restart unless-stopped --memory 128m \
    --network "$PORTAL_NET" --network-alias mangosd \
    --env-file "$WU/portal.env" -v "$WU/portal:/app:ro" -v "$WU/hosted:/hosted" -v "$WU/portal-data:/data" \
    python:3.12-alpine python3 -I /app/wrath_portal.py >/dev/null \
    && docker network connect ov-wotlk_edge wu-portal || true
fi
ok=""
for _ in $(seq 1 15); do
  if docker exec wu-portal python3 -c 'import urllib.request;urllib.request.urlopen("http://127.0.0.1:8091/wrath/status.json",timeout=5)' >/dev/null 2>&1; then ok=1; break; fi
  sleep 1
done
if [ -z "$ok" ]; then
  docker logs --tail 20 wu-portal >&2 || true
  put_back
  if [ "$recreated" = 1 ]; then
    docker rm -f wu-portal >/dev/null 2>&1 || true
    docker rename wu-portal-before-data wu-portal
    docker start wu-portal >/dev/null
    echo "ERROR: the new sign-in page didn't start; the old container, its page and its art are back." >&2; exit 1
  fi
  docker restart wu-portal >/dev/null
  echo "ERROR: the new sign-in page didn't start; the old one (and its art) is back." >&2; exit 1
fi
if [ -n "$recreated" ]; then
  docker rm -f wu-portal-before-data >/dev/null 2>&1 || true
  echo "  wu-portal recreated with the /data and /hosted mounts"
fi
echo "  wu-portal is up with the new page"
if [ -f "$WU/portal/art/wu-theme.css" ] && ! docker exec wu-portal python3 -c 'import urllib.request;urllib.request.urlopen("http://127.0.0.1:8091/wrath/art/wu-theme.css",timeout=5)' >/dev/null 2>&1; then
  echo "  WARNING: /wrath/art/wu-theme.css doesn't answer: the pages show their plain look until it does"
fi

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
c4=$(curl -s -o /dev/null -w '%{http_code}' -m 20 https://play.openvanilla.app/wrath/art/wu-card.webp || true)
c5=$(curl -s -o /dev/null -w '%{http_code}' -m 20 https://play.openvanilla.app/wrath/q/258 || true)
echo "  /wrath/q/258 share link (200 = links on): $c5"
c6=$(curl -s -o /dev/null -w '%{http_code}' -m 20 https://play.openvanilla.app/wrath/armory || true)
echo "  /wrath/armory (200 = the armory is on): $c6"
c7=$(curl -s -o /dev/null -w '%{http_code}' -m 20 https://play.openvanilla.app/wrath/mods || true)
echo "  /wrath/mods Workshop (200 = on): $c7"
c7m=$(curl -s -o /dev/null -w '%{http_code}' -m 20 https://play.openvanilla.app/wrath/modes.json || true)
echo "  /wrath/modes.json game modes (200 = on): $c7m"
c8=$(curl -s -o /dev/null -w '%{http_code}' -m 20 https://play.openvanilla.app/wrath/docs || true)
c8w=$(curl -s -o /dev/null -w '%{http_code}' -m 20 https://play.openvanilla.app/wrath/workshop || true)
echo "  /wrath/workshop player creations (200 = on): $c8w"
echo "  /wrath/docs Leyline docs (200 = on): $c8"
c9=$(curl -s -o /dev/null -w '%{http_code}' -m 20 https://play.openvanilla.app/wrath/host || true)
echo "  /wrath/host + Your server (302 to sign-in = on): $c9"
c10=$(curl -s -o /dev/null -w '%{http_code}' -m 20 https://play.openvanilla.app/wrath/api/social/me || true)
echo "  /wrath/api/social/me Leyline friends (401 signed out = on): $c10"
c11=$(curl -s -o /dev/null -w '%{http_code}' -m 20 https://play.openvanilla.app/wrath/admin || true)
echo "  /wrath/admin Admin Console (302 to sign-in = on): $c11"
c12=$(curl -s -o /dev/null -w '%{http_code}' -m 20 https://play.openvanilla.app/wrath/leyline-preview || true)
echo "  /wrath/leyline-preview hidden hub (200 = on): $c12"
echo "  warm.html (public): $c1   /data (must stay gated, 302/401/403): $c2   /wrath signed out (200 = saved-key page): $c3"
echo "  /wrath/art/wu-card.webp (200 = the art is served): $c4"
echo "  backups: $BK"
echo "FASTLOOP OK"
