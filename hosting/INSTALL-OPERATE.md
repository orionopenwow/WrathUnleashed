# Hosting first: install and operate

For the owner. What each piece is, how to try it on your PC today, what going live takes (and
which steps need your OK), and how to run it afterwards. Design: `README.md`.

## 1. What goes where

| Folder | Goes to | What |
|---|---|---|
| `kit/` | `Desktop\WrathUnleashed\host\` (and, zipped, to players) | the host kit: `Host a Wrath realm.bat`, `Check my realm.bat`, `Realm tools.bat`, `Stop my realm.bat`, `host-wrath-realm.sh`, the compose file, the agent/tools image |
| `relay/` + `kit/tools/wunet/` | the relay VM (`/opt/wu-relay`) | the relay server, its Docker/systemd/Caddy setup, the join page |
| `site/` | the website repo (`www/`) | `join/index.html`, a snippet for `404.html`, the community-record schema for the Beacons page |
| `server/set-realm-address.sh` | `WrathUnleashed\server\` (replaces the old one) | same as before, plus a world port and `--relay STATE_DIR` |
| `.github/workflows/` | the repo that carries `hosting/` | tests (`wu-hosting.yml`) and the image build (`wu-images.yml`: publishes on a push to main, see 9.4) |
| `tests/` | with the code | unit tests, docker end-to-end, soak |

After copying `kit\` to `WrathUnleashed\host\`, run `Make host kit.bat` there once: it fills
`realm-files\` from `..\realm\` (profiles, `modules.env`, Lua, the profile SQL) and builds
`WrathUnleashed-host-kit.zip` for players. Run it again whenever those realm files change.

## 2. Try it on your PC (nothing public, nothing deployed)

The kit talks to `relay.openvanilla.app`, which doesn't exist yet. To see the whole thing work on
your PC now, run the end-to-end test: it starts a private relay in Docker, the host kit against
your real AzerothCore images and your extracted game data, and headless players that make an
account on the join API, create a character, enter the world and log out, first private, then
public from a fresh "IP":

```
# WSL (Ubuntu) with Docker Desktop's WSL integration on, from the folder that holds hosting/
WU_REALM_DIR=/c/Users/campw/Desktop/WrathUnleashed/realm bash hosting/tests/e2e/run-e2e.sh --real
```

It uses the `ov-client-data` volume you already have and the `ov/ac-wotlk-*:custom` images
(`WU_IMAGE`/`WU_TAG` to pick others). Its containers are named `wu-e2e-*` and it removes
everything when done (`--keep` to look around). `--fake` runs the same without AzerothCore.
This is also the first real-client check of the one thing the sandbox could not test: see 7.1.

## 3. Going live: steps that need your OK

1. **A relay VM** (recommended: its own small box, e.g. Hetzner CX22 ~€4-5/month, ~20 TB
   traffic in EU; verify prices). It can share a box with a realm only if that box's 3724 is free
   or `RELAY_SHARED_AUTH_PORT=0` (then players need `realmlist relay...:<port>`, see 7.1).
   Traffic: ~5-10 KB/s per player counted twice ≈ 36-72 MB/hour per player.
2. **DNS**: `relay.openvanilla.app` **A** record → the VM's IPv4 (Squarespace DNS). **No AAAA
   record**: the stock 3.3.5a client is IPv4-only, and a browser that knocks over IPv6 would
   open the wrong address.
3. **Deploy the relay**: `bash hosting/relay/deploy/deploy-relay.sh root@<vm-ip> ~/.ssh/<key>`.
   Exactly two connections (one scp of a single tarball, one ssh), so the SSH rate limit is never
   hit. It installs Docker if needed, writes `/opt/wu-relay/relay.env` with a fresh listing site
   secret, builds the image, opens 22/80/443/3724/40000-40999 in ufw, starts relay + Caddy (TLS
   for `https://` and `wss://` is automatic once DNS points there).
4. **Publish the images** the kit pulls: `wu-images.yml` (on a push to main, or by hand; see 9.4) →
   `ghcr.io/orionopenwow/wu-ac-wotlk-{db-import,authserver,worldserver}:stable`,
   `wu-host-tools:1`, `wu-relay:1`. They contain AzerothCore + the pinned modules (AGPL: sources
   stay public, `sources.lock` + patches), no Blizzard data. Until then the kit builds the small
   tools image itself and uses the PC's own realm images (players without them get stock
   AzerothCore and a warning).
5. **Website**: put `site/join/index.html` at `www/join/index.html`, add `site/404-join.js` to
   `www/404.html` (so `openvanilla.app/join/<id>#secret` opens the page; the relay also serves
   `https://relay.openvanilla.app/join/<id>` itself), and teach the Beacons page to read
   `https://relay.openvanilla.app/api/listing/realms.json` (`site/SCHEMA-community.md`).
6. **Claims** (when you want them): the site needs "Claim a realm" behind Hero Key sign-in: make a
   random 24-char token for (account, realm id), show it, then `POST /api/listing/claims` with
   `Authorization: Bearer <RELAY_LISTING_SITE_SECRET>` and `{realm_id, token, claimed_by}`.
   The listing side is done and tested.
7. **Open or closed beta**: by default anyone may host. For a closed start, put realm ids (one per
   line) in a file and set `RELAY_ALLOW_FILE` to it.

## 4a. One command on Linux/macOS: `leyline host`

```
bash leyline host            # name, ruleset (dalaran by default), public/private, house rules, your GM account NAME
```

It writes the config (`state/host.json`, `state/rules.txt`, `.env`), starts the realm through
`host-wrath-realm.sh`, and the agent registers the Beacon with the relay (public: on the Leyline
realm list within a minute). It **never makes accounts or sets passwords**: it asks for the name of
your GM account, then you open **your own link** (`state/host-link.txt`, the invite plus a host key:
keep it to yourself) and make that account on the join page with your own password. The agent gives
it GM rights by itself. Nobody else can take that name: the relay only accepts it from the host key.
Friends get `state/invite.txt`. Public Beacons default to signup `open` (strangers from the list can
make accounts); private ones to `invite`.

`leyline status`, `leyline gm NAME`, `leyline rules` (`--edit` to retype them), `leyline public|private`,
`leyline check|stop|logs|new-invite|claim TOKEN|signup MODE`. Answers can come from the environment
(`LEYLINE_NAME`, `LEYLINE_RULESET`, `LEYLINE_VISIBILITY`, `LEYLINE_GM`, `LEYLINE_TAGLINE`,
`LEYLINE_RULES_FILE`); `--config-only` writes the config without starting anything.

Addresses live in one line: `kit/tools/wunet/leyline.env` (`LEYLINE_DOMAIN`). Join links are the
relay's own page (`https://relay.<domain>/join/<id>`), so they work without the website.
Tested end to end without game data: `tests/test_leyline_e2e.py`.

## 4b. From the website: "+ Your server" (`/wrath/host`)

The realm list, the Leyline page and the account page have a **+ Your server** button. It signs the
player in (Google or Hero Key), asks for the realm name, preset (Dalaran hangout by default, or main,
brawl, progression), house rules, public or private, their GM account name and a tagline, and **Start
server** makes a pending realm for that account (`stream/hostflow.py`): a realm key and id, invite and
host secrets made exactly as `setup.py` makes them, and a claim token. The realm's page
(`/wrath/host/<id>`, owner only) shows the share link (`/wrath/r/<id>`), a per-realm download
(`leyline-<id>.bat` for Windows, `leyline-<id>.sh` for Mac/Linux) and live status ("Waiting for your PC"
-> "Online, listed"). The realm runs on the player's own PC through the relay; nothing runs on our server.

The download goes in the unzipped host kit folder. It writes `state/seed.b64` (this realm's key, links,
claim token and answers, nothing else) and runs `setup.py init --seed` (then `leyline host`, or
`Host a Wrath realm.bat`); the seed is used once and deleted, and a kit that already hosts another realm
refuses it. The website forgets the realm key the first time the realm connects. No accounts, no
passwords: the host makes the GM account on their own join link. With `WU_LISTING_SITE_SECRET` (= the
relay's `RELAY_LISTING_SITE_SECRET`) in `portal.env`, a listed public realm is claimed for its account.
Pending realms live in `/srv/wrath/hosted` (mounted at `/hosted`). `WU_HOST_KIT_URL` points the page
at the host kit zip. Tests: `stream/tests/test_hostflow.py`.

## 4. Hosting (what players do)

Windows: unzip the kit, double-click `Host a Wrath realm.bat`. macOS/Linux: `bash host-wrath-realm.sh`.
Questions: realm name, profile (main / brawl / progression / dalaran), private or public. First start: game
data extraction (minutes), database import (5-20 min). It ends with the invite link and the host's
own GM login (`state\host-login.txt`).

Friends open the link once on the PC they play from, make an account on that page, and set
`set realmlist relay.openvanilla.app` in `Data\enUS\realmlist.wtf`.

| Do | Windows | macOS/Linux |
|---|---|---|
| start / restart / change profile | `Host a Wrath realm.bat` | `bash host-wrath-realm.sh` |
| is it reachable? | `Check my realm.bat` | `... check` |
| stop | `Stop my realm.bat` | `... stop` |
| account for a friend | `Realm tools.bat friend NAME [PASS]` | `... friend NAME [PASS]` |
| new invite link (old stops working) | `Realm tools.bat newinvite` | `... new-invite` |
| list it / unlist it | `Realm tools.bat public` / `private` | `... public` / `private` |
| claim it (token from the site) | `Realm tools.bat claim TOKEN` | `... claim TOKEN` |
| join-page signups | `Realm tools.bat signup invite\|open\|off` | `... signup invite\|open\|off` |
| logs | `Realm tools.bat logs` | `... logs [service]` |

Keep `state\` and `.env`: they are the realm's identity (key, invite, passwords). Back up
`state\` plus the `wu-host_wu-database` Docker volume. The realm id follows the key, so a host
who reinstalls with the same `state\` keeps the same id, ports and listing.

## 5. Operating the relay

* Logs: `docker compose -f /opt/wu-relay/compose.yml logs -f relay` (JSON lines; IPs only as
  salted daily hashes).
* Metrics: `curl -s 127.0.0.1:8080/metrics` on the box (`wu_relay_realms_online`,
  `..._streams_open`, `..._bytes_total`, `..._refused_<status>_total`, `..._agent_logins_total`,
  `..._accounts_created_total`). Caddy refuses `/metrics` from outside.
* Limits: `/opt/wu-relay/relay.env`, then `docker compose up -d`. Realms reconnect by themselves in
  seconds; their ports are kept (`/var/lib/wu-relay/state.json` in the `relay-state` volume:
  back it up, it is the port book).
* Remove an abusive realm: add its id to `/var/lib/wu-relay/blocked.txt` (inside the volume:
  `docker compose exec relay sh -c 'echo <id> >> /var/lib/wu-relay/blocked.txt'`). Within a minute
  it is cut off, refused and gone from the listing.
* Update: run `deploy-relay.sh` again (keeps `relay.env`, `Caddyfile`, state).
* Without Docker: `relay/deploy/wu-relay.service` runs it with the box's Python.

## 6. Troubleshooting

| Symptom | Cause / fix |
|---|---|
| Check says "not connected to the relay" | PC offline, or outgoing 443 blocked; the agent retries every ≤ 60 s. `docker logs wu-host-agent` |
| "relay refused: too many new realms from this address" | 3 new realm ids per IP an hour; wait, or don't delete `state\` between tries |
| Players stuck at "Connecting" after the realm list | realm list not pointing at the relay yet: check says so; it fixes itself once the database is up |
| Private realm: players can't connect | they must open the invite link on the PC (and internet connection) they play from; links last 24 h per IP; a new invite link locks out old ones |
| "realm is full" / "too many connections" | per-realm 128 streams (≈ 64 players) / per-IP limits in `relay.env` |
| A whole realm is slow | its 512 KB/s cap (≈ 50 players) shapes it; raise `RELAY_KBPS` for that relay |
| Stock-image warning in the kit | no WrathUnleashed images: publish them (3.4) or build locally |

## 7. Known limits and open questions

1. **`set realmlist host:port` on the stock 3.3.5a client** is used for the per-realm auth port.
   The shared port 3724 (`set realmlist relay.openvanilla.app`) avoids depending on it and is what
   the join page shows first. The world connection always uses the realm list's `ip:port`, which
   every 3.3.5a client supports. Verify once with a real client on your PC (section 2, then a
   manual login with the printed realmlist lines).
2. **wenilla-host** (`crates/wenilla-host`) only proxies `/ws/3724` and `/ws/8085` to a fixed
   upstream, so it can't follow the realm's relay ports. The browser client needs no wenilla-host
   for relayed realms: point its WebSocket base at `wss://relay.openvanilla.app/r/<realm-id>`
   (private: `/r/<id>/i/<secret>`), and the relay maps both the standard and the realm's own
   ports. If a desktop flow must go through wenilla-host, it needs an `--allow-port` flag (one line
   in `ws.rs`'s allowlist); not changed here (read-only tree).
3. **Hero Key v2 claims**: listing side done; the site's sign-in + token page is not built.
4. **Federated / self-hosted relays**: realm ids come from the host's key, not from our relay, and
   the kit takes `WU_RELAY=<name>`, so a community relay works today; a relay directory and a
   second region are later work.
5. **CGNAT**: players behind one carrier IP share a knock for 24 h. Game passwords still protect
   every account; hosts who want more can set signup to `off` and make accounts themselves.
6. The relay keeps daily traffic counters in its state file (saved every minute), so a relay
   restart loses at most a minute of counting.

## 8. Needs your OK (nothing here was done)

- Buying/choosing the relay VM, and its monthly cost.
- DNS: `relay.openvanilla.app` A record (no AAAA).
- Deploying the relay (`deploy-relay.sh`, 2 SSH connections) and the listing site secret's
  hand-off to the website.
- Publishing images to ghcr.io (`wu-images.yml`, see 9.4).
- Pushing the workflows and the code; website changes (join page, 404 snippet, Beacons community list).
- Opening hosting to everyone vs a closed beta (`RELAY_ALLOW_FILE`), and the default limits.
- Running the 1-hour soak on the relay VM (`tests/soak/SOAK-PLAN.md`).

## 9. Beacons beta (relay on the existing box, Dalaran hangouts, realm list)

### 9.1 The relay on play.openvanilla.app: the "relay" step

`hosting/relay/Deploy relay.bat` (control panel step `relay`) puts the relay on the existing Hetzner
box instead of a separate VM. One SSH login; the relay's source goes over stdin; `relay/deploy/relay-up.sh`
runs on the box:

* **TLS**: no second Caddy (80/443 belong to the site's `wenilla-realm-caddy-1`). The relay's web side
  listens on the `wenilla-realm_default` bridge gateway (`172.x.0.1:8099`), and a marked site block for
  `relay.openvanilla.app` is added to the site's Caddyfile (backup first, restored if Caddy refuses).
  `RELAY_TRUSTED_PROXIES` lets the relay read `X-Forwarded-For` from that bridge only.
* **Ports**: game ports 40000-40999 on the host network. 3724 is the realm's own authserver here, so the
  shared port is off (`RELAY_SHARED_AUTH_PORT=0`): players use `set realmlist relay.openvanilla.app:<port>`
  (the join page shows it), which needs the 7.1 check with a real client. ufw is opened if active; a
  Hetzner Cloud Firewall, if any, needs TCP 40000-40999 by hand.
* **Memory**: the container is capped at 192 MB (`WU_RELAY_MEM` in `/opt/wu-relay/.env`), 1 CPU, 128 pids.
* **Backup, health, rollback**: `/opt/wu-relay/backups/<time>/` (compose, relay.env, state/, Caddyfile; the
  last five kept) and the old image as `wu-relay:rollback`. `/healthz` must answer from the box and from
  inside Caddy, the memory limit must be set and `/api/listing/realms.json` must answer; otherwise it
  rolls back. Re-running it is the update.
* **DNS**: if `relay.openvanilla.app` has no A record (or points elsewhere), the relay is still installed
  and healthy, Caddy is left alone, and the step ends with `ACTION NEEDED` and the exact record:
  **A `relay` -> the box's IPv4, no AAAA**. The step exits 3 (shown as failed in the control panel);
  run it again once the record exists.
* `relay.env` (chmod 600) gets a new listing site secret on first install; it is never printed.

### 9.2 The "dalaran" hosting preset

`Host a Wrath realm.bat` now offers `dalaran`: `realm/profiles/dalaran.env` (copied into `realm-files\` by
`Make host kit.bat`). A light hangout for a host's PC:

* every new character picks level 1 or the one-time **boost to 80** (`ov_main.lua`: spec kit, professions,
  teleported to Dalaran with the hearthstone set there); `.qol hub dalaran` (and the other hubs), free
  repairs, free respec, duel reset;
* **no bots** by default (`WU_BOTS=0`; `--bots N` to add some), database buffer 256 MB, 40 players max,
  idle map areas unload after a minute;
* the same world SQL as `main` (`main_unbrawl`, `main_world`, `modern_combos`).

**The host's GM login** is made on first run for every profile: `state\host-login.txt` (account and
password; only the SRP6 verifier goes into the database) at GM level 3 (administrator) on this realm.
Useful commands in game (type them in chat):

| Command | What it does |
|---|---|
| `.gm on` / `.gm off`, `.gm visible off` | GM mode (untargetable, no aggro), invisible |
| `.announce TEXT`, `.notify TEXT` | message to everyone (chat / on screen) |
| `.tele dalaran`, `.qol hub dalaran` | go to Dalaran |
| `.appear NAME`, `.summon NAME` | go to a player / bring them to you |
| `.kick NAME`, `.mute NAME MINUTES REASON`, `.unmute NAME` | moderation |
| `.ban account NAME 1d REASON`, `.unban account NAME` | bans (durations like `30m`, `1d`, `-1` = permanent) |
| `.account set gmlevel NAME 1 -1` | make a friend a moderator (1), GM (2) or admin (3); `0` takes it back |
| `.account set password NAME NEW NEW` | reset a friend's password |
| `.character level NAME 80`, `.revive` | level a character, revive the selected one |
| `.server info`, `.saveall`, `.server restart 300` | status, save everyone, restart in 5 minutes |

Without the game: `docker attach wu-host-worldserver` opens the server console (same commands without
the dot; leave with Ctrl+P then Ctrl+Q). Friends' accounts: `Realm tools.bat friend NAME`.

**The rules text** lives in `state\rules.txt` (one rule per line, up to 10, 120 characters each; the
dalaran preset starts it with four hangout rules). Tagline, summary, type (PvE, PvP, RP, RP-PvP, Fun) and
Discord invite live in `state\beacon.json`; the name comes from setup. After editing either file run
`Realm tools.bat rules` (`bash host-wrath-realm.sh rules`): the agent sends the new text with its next
signed heartbeat, and the realm list shows it as "House rules".

### 9.3 The realm list on the play page

`https://play.openvanilla.app/wrath/realms` (linked from the play and sign-in pages): WrathUnleashed first
(its own status), then the public community realms from the relay's `/api/listing/realms.json` with name,
ruleset, players (and bots), house rules and a **Join** link (`https://relay.openvanilla.app/join/<id>`).
The list is fetched in the background and cached (60 s; 30 s after a failure); a page waits at most 2.5 s,
and only before the very first fetch, so a slow or dead relay never slows the play page. The relay step
writes the relay's address on the Docker network to `/srv/wrath/portal/relay-listing.url`, so the list
works before DNS. Deployed with the `signin` step (it installs the new `wrath_portal.py`).

### 9.4 Publishing the images

`.github/workflows/wu-images.yml`: a push to main that touches `realm/custom/sources.lock`, its patches,
`fetch.sh`, `hosting/kit/tools/` or `hosting/relay/` (or Actions > wu-images > Run workflow) builds and
publishes `ghcr.io/orionopenwow/wu-ac-wotlk-{db-import,authserver,worldserver}:stable` (the names the kit
pulls with `WU_IMAGE=ghcr.io/orionopenwow/wu-ac-wotlk`, `WU_TAG=stable`), `wu-host-tools:1` and
`wu-relay:1`, each also as `:sha-<commit>`. AzerothCore + modules from source, mod-arac's client DBCs
removed from the build context, no game data. Only the built-in `GITHUB_TOKEN`; no secrets in files.
The owner, once:

1. Push the workflow file: the git credential needs the `workflow` scope (`gh auth refresh -s workflow`).
2. Organization orionopenwow > Settings > Actions > General: allow Actions; Workflow permissions may stay
   "Read" (the file asks for `packages: write` itself) unless the org blocks that, then pick "Read and write".
3. Organization > Settings > Packages: allow public packages. After the first run, open each package
   (wu-ac-wotlk-db-import, -authserver, -worldserver, wu-host-tools, wu-relay) > Package settings >
   Change visibility > **Public** (hosts pull without logging in), and check "Manage Actions access"
   lists WrathUnleashed with **Write** (only needed if a package was created outside this repo).
4. The first realm build takes 1-2 hours on GitHub's runners.
