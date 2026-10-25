# WrathUnleashed GM console

One owner-only page to run the live server: realm health, players, rolling updates, streaming,
the Beacons launch checklist, speed passes, bug reports, health and logs. It runs on the server in its own small
container and listens on the server's **127.0.0.1:8099 only**. Nothing public routes to it. You
reach it through an SSH tunnel from your PC.

## What you run (put this folder in `WrathUnleashed\gmconsole\`)

| File | When |
|---|---|
| `Install GM Console.bat` | Once, and again after an update to this folder. This uses one SSH login and keeps the game running. The previous version is backed up and the login token is kept. |
| `Open GM Console.bat` | Every time you want the console. It opens one SSH connection with the tunnel, reads the login token over that same connection, and opens your browser. **Keep its window open; closing it closes the console.** |
| `Uninstall GM Console.bat` | Removes the console's container and image. The game, the website and their data are not touched. The audit log stays. |

The token lives only on the server, in `/srv/wrath/gmconsole.env` (chmod 600). The .bat never writes it to your disk and never shows it. It only puts it in the login link it hands to the browser. To log everyone out, delete that file and run `Install GM Console.bat`, which makes a new token.

## Tabs

- **Overview**:
  - realm online/offline, players vs bots, uptime and update diff (from `server info`);
  - every container's health;
  - disk (red under 3 GB), RAM and load;
  - streaming and Forever UI;
  - the live browser-client build, and whether `www.old` exists;
  - the last 10 world-server errors and Lua errors.
- **Players**:
  - real characters online: accounts named `RNDBOT*` (the playerbots' random bots) are left out;
  - per character: kick, mute, unmute, teleport to Dalaran, mail an item;
  - announce or notify everyone;
  - account search, ban (needs a reason and a confirm) and unban.
- **Updates**:
  - the release-train v0 checklist;
  - what has changed on the server but is not live yet (client, sign-in page, Lua, profile, timeout, charfix, Caddyfile, BBR);
  - the buttons: Reload realm scripts, Restart world server, Roll back browser client, Restart wu-portal, Reload Caddy;
  - Restart world server announces a 1-, 5- or 15-minute countdown first, can be cancelled, saves everyone, recreates the world server, then waits until it is ready;
  - Reload Caddy validates the Caddyfile first;
  - the history from `/srv/wrath/gmconsole-audit.log`;
  - your .bat tools, with what each one does and when to use it.
- **Streaming**:
  - streaming on/off (`stream-switch.sh`);
  - Forever UI on/off (`WU_FOREVERUI` plus a wu-portal recreate);
  - the slice size and tiers;
  - the wu-play log.
- **Beacons**:
  - the launch checklist, each item live with a Re-check button: status.json and its CORS, feed.json, the site listing and our record (including leftover `TODO(owner)` text), realms.html, DNS and health for relay.openvanilla.app;
  - previews of all three JSON files.
- **Speed**:
  - BBR / fq / slow-start;
  - HTTP/3 alt-svc;
  - Caddy `encode` lines;
  - the `.br`/`.gz` copies in www;
  - timings measured from the server: public through Caddy, and wu-play direct;
  - the speed-pass plan (P0/P1/P2) with a status you set; it is stored on the server in `gmconsole-speed.json`. Client timing reports were left out.
- **Bug reports**:
  - the reports players file in game with `.bug` (ov_reports.lua, `acore_characters.ov_bug_reports`) and the native GM tickets (`gm_ticket`, labelled "GM ticket"), newest first;
  - filter by status (new / seen / fixed / wontfix; for tickets: open-unread / open-read / closed / character deleted) and search the text or character name;
  - each one shows the character, level, class, map/zone/area (names where known, ids otherwise), position, text and time;
  - per report: set the status (the only thing the console writes: `ov_bug_reports.status`), copy the `.go xyz x y z map` teleport command, copy as markdown. Tickets are read-only here.
- **Health** (read-only): real players vs bots, world server CPU and memory and database memory (`docker stats`), world and database uptime, update diff, and the last 20 world-server error lines.
- **Logs**: worldserver, authserver, wu-portal, wu-play, caddy, database and the console itself, with a filter box and a 5-second auto-refresh.

## Safety

- **Access:**
  - every page needs the login cookie (`HttpOnly`, `SameSite=Strict`); without it you get 401;
  - every POST needs the page's CSRF token (otherwise 403) and JSON;
  - the Host must be `127.0.0.1:8099` or `localhost:8099` (no DNS rebinding);
  - there is a strict CSP: no inline or third-party scripts.
- **Confirmations:** destructive actions ask first, and the server refuses them without `confirm`.
- **No deletes:** the console never deletes a character or an account and never drops a table. There is no free-form SQL and no free-form console command.
- **Secrets:**
  - the SOAP password stays in `soap-cmd.sh`'s own file;
  - MySQL runs inside its container with that container's own password;
  - the console scrubs the token, the SOAP password and the database password from everything it shows or logs.

## Bug-report export (for a scheduled triage task)

`GET http://127.0.0.1:8099/api/export/new-reports[?since=<last id>]` returns the `new` bug reports (and unread open GM tickets) as JSON. It answers only on loopback and only with `Authorization: Bearer <GM_TOKEN>` (the token from `/srv/wrath/gmconsole.env`; a browser cookie or a `?t=` in the URL is refused). It is read-only. On the server:

```
curl -s -H "Authorization: Bearer $(sed -n 's/^GM_TOKEN=//p' /srv/wrath/gmconsole.env)" http://127.0.0.1:8099/api/export/new-reports
```

## How it is built

- `server/gmconsole.py`: Python stdlib only.
- `server/static/`: the page.
- `server/Dockerfile`: `python:3.12-alpine` plus bash, curl, the docker CLI and compose, so the server's own scripts run unchanged: `soap-cmd.sh`, `stream-switch.sh`, and `stream-lib.sh`'s `recreate_portal`.
- `server/gmconsole-install.sh` / `gmconsole-uninstall.sh`: install and remove it.

The container:
- uses the host network, so SOAP on 127.0.0.1:7878 works, but the console binds 127.0.0.1 only;
- has 192 MB of memory and `--restart unless-stopped`;
- mounts `docker.sock`, `/srv/wrath`, and `/opt/wenilla-realm` plus the Caddyfile (both read-only).

The installer refuses to finish if anything other than loopback listens on 8099.

## Tests

```
python3 -m unittest -v tests/test_gmconsole.py   # 41 tests: auth, CSRF, pages, every action's exact command, audit, secrets, bug reports, health, export
bash tests/test_install.sh                       # 22 checks: install twice, token kept, loopback only, uninstall
python3 tests/fakeenv.py 8099 &                  # the console against the fakes; prints a login link
node tests/shots.js <login link> screenshots     # every tab at 1280 and 390 wide (screenshots/)
```

The tests use fakes only, with nothing touching the live server:
- a fake `docker` CLI that records each call;
- a fake `soap-cmd.sh`;
- a temporary `/srv/wrath`;
- a local web server standing in for play.openvanilla.app, openvanilla.app, the relay and wu-play.
