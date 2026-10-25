#!/usr/bin/env bash
# WrathUnleashed server check (read-only): memory, containers, realm settings that matter, the Dungeon Finder's
# live state, players and bots, and recent errors. Changes nothing. Prints no passwords or tokens.
cd /srv/wrath 2>/dev/null || { echo "no /srv/wrath"; exit 1; }
soap() { bash soap-cmd.sh "$1" 2>&1 | head -40; }
echo "== host"
uptime; free -m; df -h / | tail -1
echo; echo "== containers (memory, CPU)"
docker stats --no-stream --format '{{.Name}}\t{{.MemUsage}}\t{{.CPUPerc}}' 2>/dev/null | sort
echo; echo "== world server settings (selected)"
docker exec ov-ac-worldserver env 2>/dev/null | grep -E '^AC_(DUNGEON_FINDER|DUNGEON_ACCESS|SOLO_LFG|PLAYERBOTS_(RANDOM_BOT_(AUTOLOGIN|JOIN_LFG|MIN|MAX)|MIN_RANDOM|MAX_RANDOM|ENABLED)|AI_PLAYERBOT_(MIN|MAX)_RANDOM|ALLOW_TWO_SIDE|GRID|MAP_UPDATE|PRELOAD|VISIBILITY|INSTANCE_MAP_LOAD|MAX_PLAYER_LEVEL|RATE_XP_KILL)' | sort
echo; echo "== live: server info / LFG"
soap "server info"
soap "lfg options"
soap "lfg queue"
echo; echo "== Lua scripts loaded"
ls -1 custom/lua_scripts/ | tr '\n' ' '; echo
echo; echo "== world server: started at / restarts / state"
docker inspect -f '{{.State.StartedAt}} restarts={{.RestartCount}} status={{.State.Status}} exit={{.State.ExitCode}} oom={{.State.OOMKilled}}' ov-ac-worldserver 2>&1
echo; echo "== recent world server errors (last 90 min, deduplicated)"
docker logs --since 90m ov-ac-worldserver 2>&1 | grep -iE 'error|lua|ale|lfg|crash|assert|exception' | sed -E 's/[0-9]{4}-[0-9]{2}-[0-9]{2}[ T][0-9:.]+//' | sort | uniq -c | sort -rn | head -40
echo; echo "== world server: last 25 lines"
docker logs --tail 25 ov-ac-worldserver 2>&1 | cut -c1-220
echo; echo "DIAG OK"
