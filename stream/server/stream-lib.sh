#!/usr/bin/env bash
# Shared by stream-up.sh, stream-down.sh, stream-switch.sh and slice-install.sh (sourced).
# The paths can be moved for tests (tests/test_server_scripts.sh); on the server they are these.
WU="${WU_DIR:-/srv/wrath}"
ST="${WU_STREAM_DIR:-$WU/stream}"
CF="${WU_CADDYFILE:-/opt/openvanilla-classicplus/Caddyfile}"
CADDY_DIR="${WU_CADDY_DIR:-/opt/wenilla-realm}"
STREAM_HOST="${WU_STREAM_HOST:-wrath.openvanilla.app}"
UPSTREAM="${WU_UPSTREAM:-play.openvanilla.app}"
NET=wenilla-realm_default
MARK_BEGIN="# >>> WrathUnleashed streaming (stream-up.sh)"
MARK_END="# <<< WrathUnleashed streaming"
log() { printf '\n== %s\n' "$*"; }
die() { printf '\nERROR: %s\n' "$*" >&2; exit 1; }

# key=value in a settings file, replaced or appended
kv_set() { local f=$1 k=$2 v=$3; touch "$f"; if grep -q "^$k=" "$f"; then sed -i "s#^$k=.*#$k=$v#" "$f"; else echo "$k=$v" >> "$f"; fi; }

# wu-portal reads its settings when the container is created, so a change means a new container.
# Same command as deploy.sh step 9.
recreate_portal() {
  docker image inspect python:3.12-alpine >/dev/null 2>&1 || docker pull -q python:3.12-alpine >/dev/null
  docker rm -f wu-portal >/dev/null 2>&1 || true
  docker run -d --name wu-portal --restart unless-stopped --memory 128m \
    --network "$NET" --network-alias mangosd \
    --env-file "$WU/portal.env" -v "$WU/portal:/app:ro" \
    python:3.12-alpine python3 -I /app/wrath_portal.py >/dev/null
  docker network connect ov-wotlk_edge wu-portal
  local _
  for _ in 1 2 3 4 5 6 7 8 9 10; do
    docker exec wu-portal python3 -c 'import urllib.request;urllib.request.urlopen("http://127.0.0.1:8091/wrath/status.json",timeout=5)' >/dev/null 2>&1 && return 0
    sleep 1
  done
  docker logs --tail 20 wu-portal >&2 || true
  return 1
}

caddy_reload() { (cd "$CADDY_DIR" && docker compose exec -T caddy caddy reload --config /etc/caddy/Caddyfile --adapter caddyfile); }

# Remove our site block (between the markers) from the Caddyfile, in place (it is bind-mounted).
caddy_strip() {
  python3 -I - "$CF" "$MARK_BEGIN" "$MARK_END" <<'PY'
import sys
p, b, e = sys.argv[1:4]
s = open(p).read()
while b in s:
  i = s.index(b)
  j = s.find(e, i)
  if j < 0: sys.exit("start marker without end marker in the Caddyfile")
  j = s.find("\n", j)
  s = s[:i].rstrip("\n") + "\n" + (s[j + 1:] if j >= 0 else "")
with open(p, "r+") as f:
  f.seek(0); f.write(s); f.truncate()
PY
}

soap() { bash "$WU/soap-cmd.sh" "$@"; }

# The realm rule's tables, from the slice: ov_slices_tiers.lua (the tiers of slices/<slice>.json, by
# lua/tiers_lua.py) and ov_slices_lfg.lua (the Dungeon Finder ids and levels, from LFGDungeons.dbc).
# Returns 1 when the tiers could not be made (the slice description is broken).
realm_tables() {
  local slice_json="$1" slice_dir="$2" scripts="$WU/custom/lua_scripts"
  python3 -I "$ST/lua/tiers_lua.py" "$slice_json" > "$ST/ov_slices_tiers.lua.new" || { rm -f "$ST/ov_slices_tiers.lua.new"; return 1; }
  install -m 644 "$ST/ov_slices_tiers.lua.new" "$scripts/ov_slices_tiers.lua"; rm -f "$ST/ov_slices_tiers.lua.new"
  echo "  tiers: $(grep -c '^    \[' "$scripts/ov_slices_tiers.lua") (from $slice_json)"
  local lfg
  lfg=$(find "$WU/client-data/dbc" "$slice_dir" -maxdepth 2 -iname 'LFGDungeons.dbc' 2>/dev/null | head -1 || true)
  if [ -n "$lfg" ] && python3 -I "$ST/lua/lfg_ids.py" "$lfg" > "$ST/ov_slices_lfg.lua.new"; then
    install -m 644 "$ST/ov_slices_lfg.lua.new" "$scripts/ov_slices_lfg.lua"; rm -f "$ST/ov_slices_lfg.lua.new"
    echo "  Dungeon Finder ids: $(grep -c '\] = [0-9]*,$' "$scripts/ov_slices_lfg.lua") dungeons (from $lfg)"
  else
    rm -f "$ST/ov_slices_lfg.lua.new"
    echo "  WARNING: no LFGDungeons.dbc found: stream players cannot use the Dungeon Finder (everything else works)"
  fi
}

# The streamed client page takes the login from /__env.js (the gate), never from the URL.
patch_index() {
  local IDX="$ST/www/index.html"
  # The dev page lets ?user=&pass= links log in; the streamed page never takes credentials from the URL.
  sed -i "s/window.__wenilla_env = { dev_query_creds: '1' };/window.__wenilla_env = {};/" "$IDX"
  if ! grep -q 'src="/__env.js"' "$IDX"; then
    python3 -I - "$IDX" <<'PY'
import sys
p = sys.argv[1]; s = open(p).read()
anchor = '<script type="module">'
if anchor not in s: sys.exit("no module script in index.html")
tag = '<script src="/__env.js"></script>\n'
s = s.replace(anchor, tag + anchor, 1)
open(p, "w").write(s)
PY
  fi
  # A precompressed copy of the old page would be served instead of the edited one.
  rm -f "$IDX.br" "$IDX.gz"
  # The client (~90 MB wasm) goes out precompressed: wu-play serves .br/.gz siblings when the
  # browser accepts them (about 4x smaller), and nothing is compressed per request.
  local f
  for f in "$ST"/www/*.wasm "$ST"/www/*.js; do
    [ -f "$f" ] || continue
    if [ ! -f "$f.gz" ] || [ "$f" -nt "$f.gz" ]; then gzip -9 -k -f "$f"; fi
    if command -v brotli >/dev/null && { [ ! -f "$f.br" ] || [ "$f" -nt "$f.br" ]; }; then brotli -q 9 -k -f "$f"; fi
  done
  # "Play with my own game files" + "Download this section" (www-files, from the kit).
  if [ -d "$ST/www-files" ] && [ -f "$ST/www-patch.py" ]; then
    python3 -I "$ST/www-patch.py" "$ST/www" "$ST/www-files" \
      || echo "  WARNING: www-patch.py could not edit this client build: no own-files mode or section downloads (see above)"
  fi
}
