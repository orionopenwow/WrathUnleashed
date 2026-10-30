#!/usr/bin/env bash
# The Leyline brand switch (owner 2026-10-30: "wait for the site to change on my command"). Everything players and
# visitors read says Leyline, and the main realm is "Dalaran Hangout". Run as root on the server by
# "Leyline brand.bat" (one SSH login):
#
#   bash brand.sh check     read only: prints what "on" (or "off", when it is on) would change
#   bash brand.sh on        flips it on
#   bash brand.sh off       the rollback: every name back as it was
#
# What "on" changes (backups first, in /root/brand-backups/<time>/; the old realm name in brand-state/):
#   1 custom/lua_scripts/leyline-brand.on: the realm scripts (ov_modapi.lua OVMod.Brand) see it within 30 s and say
#     "Leyline" / "Dalaran Hangout" in chat, the welcome and the in-game Leyline window; each login tells the
#     WrathUnleashedUI addon. No "reload ale" and no world server restart: nobody is kicked.
#   2 acore_auth.realmlist: the name in the game's realm list becomes "Dalaran Hangout" (the login server reads it
#     again within 20 s; players in the world stay in). With the Sample Hangout on, it is "Dalaran Hangout" too.
#   3 portal.env: LEYLINE_BRAND=1 and WU_HUB_FRONT=1 (the front page; LEYLINE_HUB_FRONT=0 keeps it hidden) (wrath_portal.py: the site is "Leyline", the main realm "Dalaran Hangout", the
#     page layer's "Back to Dalaran Hangout"); wu-portal recreated (stream visitors click Play again, as after
#     any sign-in update).
#   4 the streamed addons' addon-list names (fui-install.sh / mods-install.sh brand on: WrathUnleashedUI.toc and
#     WUModCatalog.toc Title/Notes/Author), wu-play restarted. Skipped (said so) when those scripts are older than
#     this switch: run the foreverui and mods steps first.
#   5 the Dalaran Hangout's relay listing text (hangout-beacon/state/beacon.json tagline and summary, sent with the
#     agent's next heartbeat), when the hangout runs on this box.
# "off" undoes 1-5 (the realm name from brand-state/realm-name.txt, or "Leyline Sample Hangout" while the Sample
# Hangout is on). Folder names, saved variables, chat prefixes, ids, cookies, domains and routes never change.
# Last line: BRAND OK / BRAND CHECK OK, or an error (exit 1).
set -euo pipefail
WU="${WU_DIR:-/srv/wrath}"
cd "$WU"
MODE="${1:-check}"
NAME="${LEYLINE_REALM_NAME:-Dalaran Hangout}"
SAMPLE_NAME="Leyline Sample Hangout"
STATE="$WU/brand-state"
REALM_ID="${WU_REALM_ID:-1}"
FLAG="$WU/custom/lua_scripts/leyline-brand.on"
ST="${WU_STREAM_DIR:-$WU/stream}"
HB="${WU_HANGOUT_DIR:-$WU/hangout-beacon}"
HB_IMG="${WU_HANGOUT_IMAGE:-wu-hangout-tools:1}"
die() { printf '\nBRAND FAILED: %s\n' "$*" >&2; exit 1; }
case "$MODE" in check|on|off) ;; *) die "usage: brand.sh check|on|off" ;; esac
[[ "$NAME" =~ ^[A-Za-z0-9\ _\'-]{1,32}$ ]] || die "LEYLINE_REALM_NAME: 1-32 letters, digits, spaces, _ ' or -"

dbq() { docker exec -i ov-ac-database sh -c 'MYSQL_PWD="$MYSQL_ROOT_PASSWORD" exec mysql -uroot -N -B' <<<"$1"; }
current_name() { dbq "SELECT name FROM acore_auth.realmlist WHERE id = $REALM_ID" 2>/dev/null || true; }
portal_brand() { grep -m1 -E '^LEYLINE_BRAND=' portal.env 2>/dev/null | cut -d= -f2 | tr -d '\r"' || true; }
live_env() { docker exec ov-ac-worldserver printenv "$1" 2>/dev/null || true; }
sampler_on() { grep -qxF "# <<< Leyline Sample Hangout" profiles/main.env 2>/dev/null || grep -qxF "# <<< Leyline Sample Hangout" modules.env 2>/dev/null; }
supports() { [ -f "$1" ] && grep -q '^  brand)' "$1"; }
sql_str() { printf '%s' "$1" | sed "s/'/''/g"; }

# The hangout's relay listing text, with the brand on (descriptive, not the owner's own pitch).
# TODO(owner): the Dalaran Hangout's own tagline and summary on Leyline (the same two lines are in hosting/hangout/hangout-up.sh)
HB_TAGLINE_ON="Leyline's own Dalaran: your characters, and everyone meets here."
HB_SUMMARY_ON="The Dalaran Hangout itself, reached through the Leyline relay and run by the Leyline team. Sign in with your website login (no new account), hop here from any Leyline realm, and arrive in Dalaran."

ON_NOW=0; [ "$(portal_brand)" = 1 ] && ON_NOW=1
if [ "$MODE" = off ] && sampler_on; then OFF_NAME="$SAMPLE_NAME"; else OFF_NAME=$(cat "$STATE/realm-name.txt" 2>/dev/null || echo WrathUnleashed); fi
[[ "$OFF_NAME" =~ ^[A-Za-z0-9\ _\'-]{1,32}$ ]] || OFF_NAME=WrathUnleashed

if [ "$MODE" = check ]; then
  echo "BRAND CHECK (nothing is changed)"
  if [ "$ON_NOW" = 1 ]; then echo "  the brand is ON now: these are what 'off' would put back"; want=off; else want=on; fi
  echo "== 1 realm scripts: flag $FLAG $([ -f "$FLAG" ] && echo present || echo absent) -> $([ $want = on ] && echo present || echo absent)"
  v=$(live_env OV_LEYLINE_BRAND); [ -z "$v" ] || echo "  NOTE: the world server's OV_LEYLINE_BRAND=$v wins over the flag file"
  for f in ov_modapi.lua ov_qol.lua ov_main.lua ov_reports.lua ov_leyline.lua; do
    if grep -q 'Brand' "custom/lua_scripts/$f" 2>/dev/null; then echo "  $f knows the switch"; else echo "  NOTE: $f is older than the switch: run the scripts step first"; fi
  done
  echo "== 2 realm list name: '$(current_name)' -> '$([ $want = on ] && echo "$NAME" || echo "$OFF_NAME")'"
  sampler_on && echo "  (the Sample Hangout is on: its name is '$SAMPLE_NAME' while the brand is off)"
  echo "== 3 portal.env: LEYLINE_BRAND=$(portal_brand) -> $([ $want = on ] && echo 1 || echo 0) and WU_HUB_FRONT -> $([ $want = on ] && [ "${LEYLINE_HUB_FRONT:-1}" = 1 ] && echo 1 || echo 0) (wu-portal recreated)"
  if grep -q 'LEYLINE_BRAND' portal/wrath_portal.py 2>/dev/null; then echo "  wrath_portal.py knows the switch"; else echo "  NOTE: portal/wrath_portal.py is older than the switch: run the signin step first"; fi
  echo "== 4 streamed addon list names"
  for s in fui-install.sh mods-install.sh; do
    if supports "$ST/$s"; then echo "  $s brand $want"; elif [ -f "$ST/$s" ]; then echo "  NOTE: $ST/$s is older than the switch (foreverui / mods step first)"; else echo "  $s: not on this server"; fi
  done
  for t in "$ST/overlays/foreverui/Interface/AddOns/WrathUnleashedUI/WrathUnleashedUI.toc" "$ST/overlays/mods/Interface/AddOns/WUModCatalog/WUModCatalog.toc"; do
    [ -f "$t" ] && echo "  now: $(grep -m1 '^## Title:' "$t" | tr -d '\r') ($(basename "$t"))"
  done
  echo "== 5 the hangout's relay listing text"
  if [ -f "$HB/state/host.json" ]; then
    python3 -I -c 'import json,sys;r=json.load(open(sys.argv[1])).get("record") or {};print("  now: " + (r.get("tagline") or "(none)"))' "$HB/state/host.json" 2>/dev/null || true
    echo "  -> $([ $want = on ] && echo "$HB_TAGLINE_ON" || echo "the text it had before (brand-state/beacon-before.json)")"
  else echo "  no hangout beacon on this box ($HB): nothing to change"; fi
  echo "== players online now: $(dbq "SELECT COUNT(*) FROM acore_characters.characters WHERE online = 1 AND account NOT IN (SELECT id FROM acore_auth.account WHERE username LIKE 'RNDBOT%')" 2>/dev/null || echo '?') (nobody is kicked; no restart)"
  echo "BRAND CHECK OK"
  exit 0
fi

BK=/root/brand-backups/$(date +%Y%m%d-%H%M%S); mkdir -p "$BK" "$STATE"
[ -f portal.env ] && cp -p portal.env "$BK/portal.env"
echo "BRAND $MODE (backups: $BK)"

# 1 realm scripts
if [ "$MODE" = on ]; then
  printf 'Leyline brand on (realm/brand.sh, %s). Delete this file or run brand.sh off to turn it off.\n' "$(date -u +%FT%TZ)" > "$FLAG"
  chmod 644 "$FLAG"; echo "== 1 realm scripts: $FLAG written (they see it within 30 s)"
else
  rm -f "$FLAG"; echo "== 1 realm scripts: $FLAG removed (they see it within 30 s)"
fi
v=$(live_env OV_LEYLINE_BRAND); [ -z "$v" ] || echo "  NOTE: the world server's OV_LEYLINE_BRAND=$v wins over the flag file (remove it from the profile)"

# 2 realm list name
old=$(current_name)
if [ "$MODE" = on ]; then
  # keep the name to go back to (the Sample Hangout's own name is not kept: off works that one out itself)
  if [ -n "$old" ] && [ "$old" != "$NAME" ] && [ "$old" != "$SAMPLE_NAME" ]; then printf '%s\n' "$old" > "$STATE/realm-name.txt"; fi
  NEW="$NAME"
else
  NEW="$OFF_NAME"
fi
echo "== 2 realm list name: '$old' -> '$NEW'"
dbq "UPDATE acore_auth.realmlist SET name = '$(sql_str "$NEW")' WHERE id = $REALM_ID" || echo "  NOTE: could not rename the realm (the rest goes on)"

# 3 portal
if [ -f portal.env ]; then
  B=$([ "$MODE" = on ] && echo 1 || echo 0)
  echo "== 3 portal: LEYLINE_BRAND=$B"
  if grep -q '^LEYLINE_BRAND=' portal.env; then sed -i "s#^LEYLINE_BRAND=.*#LEYLINE_BRAND=$B#" portal.env; else echo "LEYLINE_BRAND=$B" >> portal.env; fi
  # the Leyline front page at /wrath/leyline (hub.py WU_HUB_FRONT) goes live with the brand; LEYLINE_HUB_FRONT=0 keeps it hidden
  H=$([ "$MODE" = on ] && [ "${LEYLINE_HUB_FRONT:-1}" = 1 ] && echo 1 || echo 0)
  echo "     WU_HUB_FRONT=$H (the Leyline front page $([ $H = 1 ] && echo live || echo hidden))"
  if grep -q '^WU_HUB_FRONT=' portal.env; then sed -i "s#^WU_HUB_FRONT=.*#WU_HUB_FRONT=$H#" portal.env; else echo "WU_HUB_FRONT=$H" >> portal.env; fi
  grep -q 'LEYLINE_BRAND' portal/wrath_portal.py 2>/dev/null || echo "  NOTE: portal/wrath_portal.py is older than the switch: the signin step makes the pages follow it"
  if [ -f "$ST/stream-lib.sh" ]; then
    # shellcheck disable=SC1091
    ( . "$ST/stream-lib.sh"; recreate_portal ) && echo "  wu-portal recreated" \
      || echo "  NOTE: wu-portal did not come back: docker logs wu-portal (cp $BK/portal.env portal.env to undo)"
  else
    docker restart wu-portal >/dev/null 2>&1 && echo "  wu-portal restarted" || echo "  NOTE: restart wu-portal by hand to show the new names"
  fi
else
  echo "== 3 portal: no portal.env here (no sign-in pages on this box)"
fi

# 4 streamed addon list names
echo "== 4 streamed addon list names"
for s in fui-install.sh mods-install.sh; do
  if supports "$ST/$s"; then bash "$ST/$s" brand "$MODE" || echo "  NOTE: $s brand $MODE did not finish (the rest is done): bash $ST/$s brand $MODE"
  elif [ -f "$ST/$s" ]; then echo "  NOTE: $ST/$s is older than the switch: the foreverui / mods step brings it (it follows portal.env)"
  fi
done

# 5 the hangout's relay listing text
if [ -f "$HB/state/host.json" ]; then
  echo "== 5 the hangout's relay listing text"
  [ -f "$HB/state/beacon.json" ] && cp -p "$HB/state/beacon.json" "$BK/beacon.json"
  if python3 -I - "$MODE" "$HB/state" "$STATE/beacon-before.json" "$HB_TAGLINE_ON" "$HB_SUMMARY_ON" <<'PY'
import json, os, sys
mode, st, before, tag_on, sum_on = sys.argv[1:6]
bj = os.path.join(st, "beacon.json")
try:
    edits = json.load(open(bj, encoding="utf-8-sig"))
    edits = edits if isinstance(edits, dict) else {}
except (OSError, ValueError):
    edits = {}
if mode == "on":
    if not os.path.exists(before):   # beacon.json's own text before the first "on" (null: it had none)
        json.dump({k: edits.get(k) for k in ("tagline", "summary")}, open(before, "w"), indent=1)
    edits.update(tagline=tag_on, summary=sum_on)
else:
    try:
        old = json.load(open(before, encoding="utf-8"))
    except (OSError, ValueError):
        old = {}
    for k in ("tagline", "summary"):
        if isinstance(old.get(k), str):
            edits[k] = old[k]
        else:   # it had none: the setup's own text (host.json) shows again
            edits.pop(k, None)
    try:
        os.remove(before)
    except OSError:
        pass
with open(bj + ".tmp", "w", encoding="utf-8") as f:
    json.dump(edits, f, indent=1)
os.replace(bj + ".tmp", bj)
print("  tagline: " + (edits.get("tagline") or "(the setup's own)"))
PY
  then
    chown 10001:10001 "$HB/state/beacon.json" 2>/dev/null || true
    docker run --rm --user 10001:10001 --network none -v "$HB:/kit" -e WU_KIT=/kit "$HB_IMG" python -m wuhost.setup rules >/dev/null 2>&1 \
      && echo "  sent with the agent's next heartbeat" \
      || echo "  NOTE: wuhost.setup rules did not run ($HB_IMG): the hangout step (Deploy Dalaran hangout.bat) sends it"
  else
    echo "  NOTE: could not write $HB/state/beacon.json (the rest is done)"
  fi
fi
echo "BRAND OK"
