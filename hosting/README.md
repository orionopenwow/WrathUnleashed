# WrathUnleashed hosting first (H1–H3)

Anyone can host a WrathUnleashed (3.3.5a, AzerothCore) realm from their own PC, share an invite
link, keep their home IP hidden behind our relay, and (optionally) list it in Beacons.
How to install and run it: `INSTALL-OPERATE.md`. Nothing here is deployed, pushed or published.

```
 host's PC (Docker, no open ports)                       relay.openvanilla.app                players
 ┌──────────────────────────────────────────┐            ┌──────────────────────────┐
 │ internal network (no internet)           │  one wss   │ /agent  (tunnel, 443)    │
 │  mysql ─ authserver:3724 ─ world:8085    │◀──────────▶│ :3724   shared, by knock │◀── stock 3.3.5a client
 │        ▲            ▲                    │  outbound  │ :40000  realm's auth     │◀── realmlist relay...:40000
 │        └──── wu-agent ──────────────────┼────────────│ :40001  realm's world    │◀── (from the realm list)
 │  (sets realmlist = relay:40001)         │            │ /r/<id>/ws/<port>        │◀── browser client (wss)
 └──────────────────────────────────────────┘            │ /join/<id>, /api/...     │◀── join page (knock, signup)
                                                         │ /api/listing/*           │──▶ Beacons (community records)
                                                         └──────────────────────────┘
```

## H1: the host kit (`kit/`)

`Host a Wrath realm.bat` (Windows) / `host-wrath-realm.sh` (macOS, Linux). Docker is the only
prerequisite: every helper runs in containers, so no Python on the host.

* Asks three things: realm name, profile (`main` / `brawl` / `progression` / `dalaran`: a light
  Dalaran hangout, see INSTALL-OPERATE 9.2), private or public.
  Defaults come from the last run, so re-running is the "restart/update" button.
* Images are variables: `WU_IMAGE=ghcr.io/orionopenwow/wu-ac-wotlk`, `WU_TAG=stable` (to be
  published by CI, `.github/workflows/wu-images.yml`), falling back to the PC's own
  `ov/ac-wotlk-*:custom`, then (with a warning) to AzerothCore's stock images.
* Generates: the database password, the realm's Ed25519 key (`state/realm.key`), the realm id
  (from the key), the invite secret, the host's own GM login (`state/host-login.txt`; only the
  SRP6 verifier goes into the database).
* Game data: dbc + maps only, extracted from the host's own 3.3.5a install with AzerothCore's
  `map_extractor`, into the same `ov-client-data` volume the realm tooling uses; plus mod-arac's
  DBCs from the pinned commit, exactly like `Build custom realm.bat`. Nothing is downloaded from
  Open Vanilla, nothing leaves the PC.
* Profile world SQL (`main_unbrawl`/`main_world`/`brawl_world*`/`modern_combos`) applied once per
  profile, as `Make it Main.bat` / `deploy.sh` do. `realm-files/` is filled from `realm\` by
  `Make host kit.bat` / `make-kit.sh`.
* Prints the invite link: `https://openvanilla.app/join/<realm-id>#<invite-secret>` (private) or
  `https://openvanilla.app/join/<realm-id>` (public). The secret is in the fragment, so it never
  reaches a web server log.
* `Check my realm.bat` (H4d): the self-check in plain language. `Realm tools.bat`: friend
  accounts, new invite link, public/private, claim, signup mode, logs. `Stop my realm.bat`.

Compose (`kit/docker-compose.host.yml`): the realm has **no published ports** and sits on an
`internal: true` network; only `wu-agent` (read-only root, all capabilities dropped) has a way out.
Because every player reaches the authserver from the agent's address, wrong-password bans are per
account, not per IP (the relay does per-IP limits). Warden is on for public realms (stock clients),
off for private ones (so the WrathUnleashed browser/desktop client can join).

## H2: the relay (`relay/`, `kit/tools/wunet/`)

**Why not the existing openvanilla-relay?** Its design fits and is kept: an outbound agent
WebSocket, relay-side limits, hashed IP logs, pre-upgrade refusals with real HTTP statuses. But it
is WebSocket-only for players (the 1.12 launcher runs a local bridge that rewrites the realm list).
3.3.5a players use the stock client: raw TCP, realmlist from a text file, no launcher. So the Wrath
relay adds what 1.12's couldn't: raw TCP listeners per realm, an address model the stock client
understands, and relay-side invite checks (the agent publishes sha256(secret); the 1.12 relay asked
the agent per stream).

**Why Python asyncio (not Rust)?** (1) The work is copying a few KB/s per player; one asyncio
process moves thousands of streams (the 50-player soak here: p99 ping 1.2 ms through relay + tunnel). (2) Standard
library only (plus optional `cryptography`), so the host agent, the relay, the self-check and the
test client share one protocol module (`wunet/`), and the agent runs in a 60 MB Python container on
the host's PC. (3) Testable in this sandbox and in CI without a Rust toolchain (another agent owns
cargo here). The wire protocol is small and documented (`wunet/mux.py`), so a Rust port into
`openvanilla-relay` is straightforward if traffic ever needs it.

**Tunnel**: one WebSocket `wss://relay/agent`, outbound 443 only (works behind CGNAT, campus and
hotel networks). The relay sends a challenge; the agent signs it with the realm key; the realm id
must be the key's hash: no accounts, no shared tokens, nothing central to register. Player
connections are multiplexed on it (`OPEN/DATA/CLOSE` frames, 32 KB chunks); control messages are
JSON (ping/pong, status, create_account, updates). Reconnect: exponential backoff 1→60 s with
jitter; a new tunnel replaces the old one; ports survive reconnects and relay restarts.

**Addresses**: each realm gets a fixed port pair on the relay, `auth` (even) and `world` (= auth+1),
kept in the relay's state file. The agent writes `realmlist.address/localAddress = relay IPv4`,
`port = world` (the authserver is on an internet-less network, so it gets an IP, not a name). Players:

* `set realmlist relay.openvanilla.app` (shared port 3724, routed by the player's IP to the realm
  whose join page that IP opened most recently, valid 24 h), or
* `set realmlist relay.openvanilla.app:40000` (the realm's own auth port, no knock needed for public realms).
* Browser/desktop WrathUnleashed client: `wss://relay.openvanilla.app/r/<realm-id>/ws/<port>`
  (3724/8085 or the realm's pair; `?invite=` or `/r/<id>/i/<secret>/ws/<port>` for private realms).

**Private realms**: the relay holds only sha256(secret). A raw-TCP player gets in only from an IP
that opened the invite link (the join page POSTs the secret: a "knock"); a WebSocket player with the
secret. A new invite link (`Realm tools > newinvite`) locks out new knocks with the old one. CGNAT
caveat: players behind the same carrier IP share a knock; game passwords still protect accounts.

**Accounts** (join page): the player picks a name and password; the page computes the SRP6 salt +
verifier in the browser (`crypto.subtle` SHA-1 + BigInt; tested equal to AzerothCore's math) and
sends only that; the agent inserts it. Neither the relay nor the host ever sees the password. Modes:
`invite` (default: needs the secret), `open` (public realms), `off`.

**Abuse limits** (env, `relay/deploy/relay.env.example`): per realm 128 streams, 512 KB/s token
bucket (shaping, not cutting), 20 GB/day; per player IP 8 streams per realm / 24 total, 40 new
connections a minute; stream idle 15 min, tunnel silent 90 s; a stuck player (1 MB queued) is cut,
never the tunnel; 3 new realms per IP an hour; 3 signups per IP an hour, 50 per realm a day;
a port pool (500 realms by default) with reclaim after 30 days unseen; a blocklist file (cut,
refused, delisted; re-read every minute); an optional allow-list for a closed beta.

**Privacy**: hosts never see player IPs, players never see the host's. Logs carry IPs only as a
salted daily hash; the knock table is memory-only. Caddy runs without an access log.

## H3: public listing (`relay/wurelay/listing.py`)

* Public realms' agents POST a heartbeat every 60 s, signed with the realm key
  (`wu-listing-heartbeat-v1` context, canonical JSON): realm id must match the key, clock within
  5 min, `seq` strictly increasing (replays refused), 1 per 20 s. Players and bots are separate
  numbers (bots = online characters of `RNDBOT%` accounts, from the realm's database).
* The listing rebuilds every record itself from the host's text (`state/beacon.json`: name,
  tagline, summary, type, rules, discord): Beacons schema 1 plus a `community` block
  (`site/SCHEMA-community.md`). Hosts cannot set `official`, `order` or badges; order is live
  first, then name. No paid placement, no votes.
* `GET /api/listing/realms.json` (CORS `*`) for the site, launcher and GM console; each record's
  `status` points at `https://relay/r/<id>/status.json` (format `openvanilla-status-1`).
* **Claim**: records are "unclaimed" until the host signs in on the site with a Hero Key (v2:
  Ed25519 challenge-response, so no password goes anywhere a realm can see), asks to claim realm
  `<id>`, and gets a token. `Realm tools > claim <token>` puts it in the signed heartbeat and on the
  status page; the site calls `POST /api/listing/claims` (site secret) and the listing accepts only
  if the realm's latest **signed** heartbeat carries that token. Implemented and tested on the
  listing side; the site side (Hero Key sign-in page, token issue) is the website's to build.

## The Dalaran Hangout (`hangout/`)

The owner's own realm, reachable as a Leyline Beacon through the relay on the same box ("Dalaran Hangout", listed
first): a live target to hop to and from. `hangout/Deploy Dalaran hangout.bat` (the `hangout` step;
`hangout-off` takes it off Leyline) runs `hangout-up.sh`: backup, build, `setup.py official` (public, signup
off, the realm list, accounts and GM rights never touched; the key made on the box), a second login server for
relay players (`wu-hangout-auth`: the realm's own authserver, same database, no IP auto-ban, no port; the relay
limits wrong passwords per player IP), the agent, then health checks (tunnel, realm answers, listed) with a
rollback. A hop into it keeps the player's own Wrath login and lands in Dalaran. Details:
`docs/leyline-realm-hopping.md`. Tests: `tests/test_hangout.py`, `tests/test_hangout_deploy.py`.

## Discord bridge (`discord/`)

The realm's World chat channel and one Discord channel, both ways, plus a feed of `.bug` reports to a second
channel. Game side: `realm/custom/lua_scripts/ov_discord.lua` (ships with the realm scripts; it does nothing until
the daemon pulls). Daemon: `discord/wudiscord/bridge.py` (Python stdlib only), a systemd unit on the realm box
that talks to the realm only over SOAP (`wudiscord pull` / `wudiscord say`) and to Discord over its REST API.
Players see `[Discord] Name: text`; Discord sees `[Name]: text`; `.discord off` hides the Discord lines for a player.

Install: `discord/Deploy Discord bridge.bat` (or `bash discord/deploy/discord-up.sh <src>` as root). It never turns
the bridge on. The owner fills `/opt/wu-discord/discord.env` (`DISCORD_BOT_TOKEN`, `DISCORD_CHAT_CHANNEL_ID`,
`DISCORD_BUG_CHANNEL_ID`; the SOAP login is copied from `/srv/wrath/signup.env`), turns on the bot's Message Content
intent, then `systemctl enable --now wu-discord`. `WU_DISCORD_DRY_RUN=1` logs instead of posting. Every setting is
in `discord/deploy/discord.env.example` and the docstring of `bridge.py`.
Tests (offline: fake Discord, fake SOAP, the Lua under a fake mod-ale, the install against a stub systemctl):
`python3 -I tests/test_discord_bridge.py`.

## Testing (H4)

| | What | Where it runs |
|---|---|---|
| a | 46 unit/integration tests: SRP6 vectors (wow_srp corpus, benilla-srp goldens, the owner's `make_account.py`), RC4/HMAC RFC vectors, Ed25519 both backends, WebSocket edge cases, relay multiplexing, private secret, knocks, signup, every cap, idle, slow consumer, reconnect, replacement, relay restart, bad logins, blocklist, listing + claim, setup, self-check, join-page JS | here, CI (`.github/workflows/wu-hosting.yml`) |
| b | `tests/e2e/run-e2e.sh --fake`: relay, agent and players as containers, players only on the relay's network, private then public from a fresh IP | CI (Docker) |
| b | `tests/e2e/run-e2e.sh --real`: the same against AzerothCore from images + `ov-client-data` | owner's PC, the server, a self-hosted runner |
| c | `wu-hosting.yml`: unit (py 3.10/3.12 x cryptography/pure) + e2e-fake; e2e-real by hand | GitHub Actions (not pushed) |
| d | `Check my realm.bat` / `host-wrath-realm.sh check` | host's PC |
| e | `tests/soak/soak.py` + `tests/soak/SOAK-PLAN.md` (50 clients, 1 h) | relay VM + a host |

The headless client (`wunet/wire335.py`) is written from AzerothCore 3.3.5a's packet layouts:
benilla-protocol's login code is 1.12-only (build 5875). It does SRP6, realm list, the RC4
header cipher, CMSG_AUTH_SESSION, char enum/create, player login, ping, time sync and logout.
Results: `RESULTS.md`.
