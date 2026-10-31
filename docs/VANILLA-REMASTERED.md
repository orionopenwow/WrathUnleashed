# Vanilla Remastered: the 1.12 realm back, as an official Leyline Beacon

Owner decision (2026-10-30 20:38): Vanilla Remastered is visible at launch as an **optional official server**.
"Stream it temporarily until someone takes over via P2P": we host and stream it for now, as before, and a community
host takes it over through the Leyline P2P network later. The GitHub package cleanup never touches the 1.12 images.

This page is the owner's runbook (the same text is in the Projects doc `claude/vanilla-remastered-revival.md`).
Nothing here runs by itself: each step is an Autopilot step that Claude queues and the owner's Control window runs.

## What it is

The old Open Vanilla 1.12 realm (CMaNGOS Classic, Classic+ "pace", client build 5875), on the same server box as the
Wrath Unleashed, under a new name. Its own database (`wenilla-realm-mariadb-1`), its own logins (the old 1.12
accounts), its own characters. Players reach it only through the Leyline relay, the way they reach the Hangout.

Why it can't simply be switched back on: when the Wrath realm was deployed (`server/deploy.sh`) it took the box's game
ports (3724 and 8085), and `wu-portal` took the name `mangosd` on the website's network (the website's account bridge
to the Wrath realm). The old `wenilla-realm-mangosd-1` / `wenilla-realm-realmd-1` containers publish those ports and
carry that name. Starting them would fail, or worse, split the website's new accounts between two servers. So the old
containers stay exactly as they are (stopped, `restart=no`), and the `ov112-on` step runs **copies** of them: the same
image ids (what was live before, never pulled again), settings, environment and volumes, as `vr-realmd` and
`vr-mangosd`, on their own internal network `vr-112`, with no published port and no route out.

## The steps, in order

| # | Step | What it does | What it touches |
|---|---|---|---|
| 1 | `ov112-realm-check` | Read-only. The old containers (present, stopped, their ports), the database, memory and disk, and a report on the 1.12 site: its Caddy routes, the browser game's address settings (names and values of address-like settings only, nothing secret), what `/`, `/play`, `/game`, `/data/`, `/ws/3724` answer, and the game data killswitch. Ends `OV112 REALM DRY`. | Nothing. |
| 2 | `ov112-on` | Backup, start, self-check, roll back on failure (details below). Ends `OV112 REALM ON`. | New: network `vr-112`, containers `vr-realmd`, `vr-mangosd`, env files `/root/vr112-env/*.env` (0600), backup `/root/vr112-on-<time>/`. Changed: `wenilla-realm-mariadb-1` joins `vr-112` (its usual names). Not touched: the old containers, Duels, the Herald proxies, the 1.12 timers, the website, Caddy, the Wrath realm. |
| 3 | `vr-beacon` | Lists it on the Leyline network as the official Beacon "Vanilla Remastered", like the Hangout: signup off, its own sign-in. Ends `VR BEACON OK`. | New: `wu-vr-agent` (64 MB, read-only), image `wu-vr-tools:1`, `/srv/wrath/vr-beacon/` (its key, made there, never copied), `/srv/wrath/portal/vr-realm.id`, `/srv/wrath/vr-realm.id`. Changed: the 1.12 realm list row's address and port (backed up first). |

Undo, in this order: `vr-beacon-off` (off Leyline; the realm list row goes back), then `ov112-realm-off` (the two game
servers stop; kept, not removed). `ov112-undo` is the full undo of tonight's `ov112-off` (Duels, Herald, the timers):
not needed for Vanilla Remastered, and not to be used for it.

### ov112-on in detail (`tools/ov112-off/start-112-realm.sh`)

1. **Checks.** Root and Docker; `wenilla-realm-realmd-1` and `wenilla-realm-mangosd-1` exist and are **stopped** (a
   running old container and a copy must never share the database: it refuses); the database is up; at least 1500 MB
   of memory available (`VR_MIN_FREE_MB`) and 3000 MB of disk for the backup; a python image for the self-check
   (`python:3.12-alpine` or `wu-hangout-tools:1`, already on the box; nothing is pulled).
2. **Backup.** `mariadb-dump --all-databases` of `wenilla-realm-mariadb-1` into `/root/vr112-on-<time>/mariadb-all.sql.gz`
   (0600, size-checked), and what existed before. The step changes no data; the dump is for a hand restore only.
3. **Start.** The internal network `vr-112`; the database joined to it under its usual names; `vr-realmd`, then
   `vr-mangosd` (`restart unless-stopped`). Run again: containers that are already up are left alone.
4. **Self-check**, any failure rolls back everything this run made:
   - the login server answers a 1.12.1 logon challenge for a made-up account (`probe112.py logon`);
   - the world server greets with `SMSG_AUTH_CHALLENGE` within 10 minutes (`VR_WORLD_WAIT`), then has not restarted;
   - the 1.12 site (`wenilla-realm-realm-1:8090`) still answers;
   - on the website's network, `mangosd` is still only `wu-portal` (the website's accounts don't split);
   - the Wrath realm's containers are still up (reported).

### vr-beacon in detail (`hosting/vanilla-remastered/vr-beacon-up.sh`)

The Hangout's script (`hosting/hangout/hangout-up.sh`) with these differences:
- `setup.py official --name "Vanilla Remastered" --auth-service vr-realmd:3724 --world-service vr-mangosd:8085`, then
  the listing record says what the realm is: core `cmangos`, build `5875`, ruleset `custom`, tag `custom`, profile
  `cmangos-1.12.1`. (`setup.py official` writes the Hangout's AzerothCore / 3.3.5a shape; the record is what the agent
  sends as is.)
- No second login server. Instead it checks the 1.12 login server's `WrongPass.MaxCount`: every relay player arrives
  from the agent's address, so a per-IP lock would lock everyone out at once. Above 0, it refuses (set it to 0, or
  `VR_ALLOW_WRONGPASS_LOCK=1`). The relay counts wrong passwords per player IP itself.
- **The realm list row** (`classicrealmd.realmlist`): after the tunnel is up, its address and port become the relay's
  IPv4 and this realm's relay world port, so a stock 1.12.1 client that logged in through the relay comes back through
  it. The row is saved first (`/srv/wrath/vr-beacon/backups/<time>/realmlist.row`) and put back on a failure and on
  `vr-beacon-off`. One row only; with several, it asks for `VR_REALM_ID`. No account is made or changed.
- Health: the tunnel; the relay sees it online; the world server answers through the agent; **a 1.12.1 logon through
  the relay's own port for this realm** answers; the listing has it. Then `vr-realm.id` for the website and the
  in-game list.
- No status URL (players and bots show as unknown on the list, as nothing reports them yet).

## How players reach it

- **Leyline launcher / realm list.** It is listed by the relay as a normal Beacon (1.12.1, CMaNGOS, "own client files").
  It shows as **Official** only once the website reads `vr-realm.id` (workstream A, see "Website changes" below);
  until then it is listed like any community realm. Players need their own 1.12.1 client.
- **A stock 1.12.1 client.** `realmlist relay.openvanilla.app:<auth port>` (the step prints it), or open its join page,
  then `realmlist relay.openvanilla.app`. Old accounts sign in with their old login. The old direct address
  (`play.openvanilla.app`) now reaches the Wrath login server and won't take a 1.12 client.
- **The 1.12 browser play page.** Not confirmed to work, and probably not reachable as it was: since the Wrath deploy,
  Caddy sends `/` to `/wrath/leyline` and `/play` to `/wrath`, and the page's game connection went to the old `realmd`
  / `mangosd` names on the website's network, which now are nobody and the Wrath bridge. The `ov112-realm-check` report
  shows the routes and the page's address settings. Making it work means pointing that page's game connection at the
  relay's bridge (`wss://relay.openvanilla.app/ws/<realm id>/auth` and `/world`) **with the client build that was live
  before** (never the private `leyline-client-112` merge). That is an open question below.
- **New players.** Signup is off and the old site's account creation went through `mangosd` (now the Wrath bridge), so
  new 1.12 accounts can't be made today. Vanilla Remastered is for returning players until that is decided.

## The game data killswitch and the 1.12 stream

The killswitch (`stream/server/gamedata-switch.sh`, steps `gamedata-off` / `gamedata-on`,
`docs/GAME-DATA-ON-OUR-SERVER.md`) covers **only the Wrath stream** (`wrath.openvanilla.app/data`, the two manifests,
the screenshots). It does **not** cover the 1.12 site: its Caddy config (`/opt/openvanilla-classicplus/Caddyfile`) is not
in this repo and the switch never edits it. Whatever the 1.12 site streamed before still streams, switch or not.
`ov112-on` warns when the switch is on; `ov112-realm-check` reports what the 1.12 site answers on `/data/`. To cover it,
the switch needs a 1.12 block too (a change for whoever owns `stream/server/`).

## Checks after launch (by hand or the read-only `check` step)

- `docker ps --filter label=leyline.vr=1` shows `vr-realmd`, `vr-mangosd` up, and `wu-vr-agent` after `vr-beacon`.
- `https://relay.openvanilla.app/r/<realm id>/status.json` says online, client 1.12.1.
- A test login with an old 1.12 account through the relay reaches the character list (never the Chumpton account).
- `free -m`: the Wrath realm keeps its headroom; `docker stats vr-mangosd` for the 1.12 world server's memory.
- The Wrath site and the Hangout still work (`/wrath`, a Hangout login): the 1.12 copies must not have changed them.

## Rollback

| What | How |
|---|---|
| A step failed | It already rolled back what it made; the last lines say why. Nothing to do. |
| Off Leyline | `vr-beacon-off`: the agent goes, `vr-realm.id` goes, the realm list row goes back. The key stays. |
| 1.12 game servers off | `ov112-realm-off` (refuses while it is on Leyline): `vr-mangosd` first (it saves players), then `vr-realmd`; kept with `restart=no`. `ov112-on` starts the same containers again. |
| Data damage | By hand only: stop both (`ov112-realm-off`), restore `/root/vr112-on-<time>/mariadb-all.sql.gz` into `wenilla-realm-mariadb-1`. Ask the owner first. |
| Remove the copies for good | `docker rm vr-mangosd vr-realmd` and `docker network rm vr-112` (the volumes are the old containers' and stay). Deleting: ask the owner first. |

## Risks

1. **Two world servers on one database.** The old containers must stay stopped while the copies run. `ov112-on`
   refuses when an old one runs, but nothing stops someone starting an old one later: never run `server/rollback.sh`,
   `start-112-jobs.sh` with the old 1.12 realm in its backup, or `docker compose up` in `/opt/wenilla-realm` while
   Vanilla Remastered is on. (`deploy.sh` uses `up --no-deps realm`, which is safe.)
2. **Memory and CPU** next to the Wrath realm and its bots. The step wants 1500 MB free; the 1.12 world server with its
   random bots may want more. Watch `free -m` after launch.
3. **Shared volumes.** The copies use the old containers' volumes. `docker compose down -v` in `/opt/wenilla-realm`
   would delete the 1.12 world.
4. **The in-game realm name** comes from the 1.12 realm list row (the step prints it and warns on brand words). Players
   see it in the client. It is left as it is (open question).
5. **Version numbers on site pages.** The relay's records carry 1.12.1; if the website shows a "1.12.1 · CMaNGOS" tag
   on the realm cards, that breaks "no client version numbers except the version chip" (a website change).
6. **The killswitch gap** above.
7. **Images.** The copies run the image ids that were live; nothing is pulled. The GitHub cleanup now refuses to delete
   `openvanilla-*`, `openwow-*`, `*mangos*` and the other 1.12 packages (`tools/github-cleanup/gh_cleanup.py`
   `PROTECTED_PACKAGE_WORDS`), and the local `PLAN.json` no longer lists them.
8. **The 1.12 site's own pages** (`wenilla-realm-realm-1`) are as they were; they were not checked for brand words here.

## A community host takes it over later (P2P)

The goal: someone in the community runs Vanilla Remastered on their own machine through the Leyline network, and the
official flag moves to them. What they need, and the order:

1. **The host kit's `cmangos-1.12.1` profile** (`hosting/kit/profiles/cmangos-1.12.1`, "Host a profile realm.bat" or
   the launcher's Host page). It builds CMaNGOS Classic from its authors' public source at a pinned commit and extracts
   the server data from **the host's own 1.12.1 client** (`extract.sh`). We never send game data. Its
   `leyline-realmd.conf` already sets `WrongPass.MaxCount = 0`.
   **Check first:** whether the `openvanilla-mangos` image was built from stock CMaNGOS or from our fork with Classic+
   code changes. If it has code changes, the profile needs that source pinned too (and as GPL code we should publish it
   anyway), or the takeover runs stock CMaNGOS with our database only.
2. **The realm database export**, made on our box at a freeze: `classicmangos` (the world, with the Classic+ content),
   `classiccharacters` (the characters), and `classicrealmd` (accounts). Handed over privately, never in a repo, a
   release or a download. The accounts table holds every player's login verifier and email: moving it to another
   person's machine needs a notice to players and their consent (or only characters move, and players claim them with
   a fresh login on the new host). Owner's call.
3. **The official flag transfer.** "Official" is ours to give, not something a host can set: the relay marks every
   Beacon `official: false`; the website marks a realm id official (`vr-realm.id` today, or the admin console's realm
   overrides). The new host's agent makes its own key, so its realm id is new. Transfer: staff verify the new realm
   (Verified host), the website's official id becomes the new one, then we run `vr-beacon-off` and, after a quiet
   period, `ov112-realm-off`. Players' join links and relay port change with the id; the realm list moves them.
   (Handing over our `realm.key` would keep the id, but the key never leaves our box by design.)
4. **Cutover order.** Announce; freeze (world server shutdown with a warning); final export; the host imports and
   links (`leyline link --core cmangos --build 5875`, or the profile's own setup); staff check a login and a character
   on it; flip the official id; `vr-beacon-off`; keep our backup until the owner says.

## Website changes this needs (not made here)

For workstream A (`stream/network.py`) and B (`stream/hub.py`):
- Read the Vanilla Remastered id like the Hangout's (`/app/vr-realm.id`, i.e. `/srv/wrath/portal/vr-realm.id`, or a
  `WU_VR_REALM` setting) and mark that relay record `official`, listed as optional (not the default realm), with a
  line like "Official, hosted by Leyline for now". Shown even while its record is missing, like the Hangout? Owner's call.
- No "1.12.1" text on the realm cards (only the version chip), and its join note should say "your own game client"
  without a version number.
- The in-game Leyline window (`realm/custom/leyline-fetch.py`) reads `/srv/wrath/hangout-realm.id` for the Hangout;
  the same for `/srv/wrath/vr-realm.id` if it should be marked there.
- The game data killswitch: a block for the 1.12 site (`stream/server/gamedata-switch.sh`).

## Files

- `tools/ov112-off/start-112-realm.sh` and its three .bat files (`Turn on the 1.12 realm - check.bat`,
  `Turn on the 1.12 realm.bat`, `Turn off the 1.12 realm.bat`)
- `hosting/vanilla-remastered/vr-beacon-up.sh`, `probe112.py`, `rules.txt`, `Put Vanilla Remastered on Leyline.bat`,
  `Take Vanilla Remastered off Leyline.bat`
- Tests: `python3 -I -m unittest discover -s hosting/vanilla-remastered/tests` (stub Docker; nothing deployed)
