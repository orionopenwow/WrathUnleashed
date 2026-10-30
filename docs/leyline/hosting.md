# Hosting

Anyone can host a 3.3.5a realm (on AzerothCore) from their own PC. On Leyline a hosted realm is called a Beacon. The host kit and the relay are built and tested. Going live on the public relay needs the owner's deploy steps.

## What you need

- Docker: [Docker Desktop](https://www.docker.com/products/docker-desktop/) on Windows and macOS, Docker Engine on Linux. Every helper runs in containers, so you need no Python on the host.
- Your own 3.3.5a install. The kit extracts the game data a server needs (dbc and maps) from it, on your PC. Nothing is downloaded from us and nothing leaves your PC.
- No open ports. The realm talks out to the relay over one connection on port 443.
- About 10 GB of free disk (the realm images and the database), or about 25 GB if you build the images yourself (below).

## Get the host kit

1. Download the host kit: [the host kit zip](https://github.com/orionopenwow/Leyline/releases/download/host-kit/WrathUnleashed-host-kit.zip). The same link is on the site's host page, [play.openvanilla.app/wrath/host](https://play.openvanilla.app/wrath/host).
2. Unzip it anywhere you keep things. You get the host kit's folder.
3. Start Docker and wait until it says it is running.
4. Windows: double-click `Host a Wrath realm.bat` in that folder. macOS or Linux: open a terminal in it and run `bash leyline host`. Made a realm on the site's host page first? Put its file (`leyline-<id>.bat` or `.sh`) in the folder and run that instead.

The first run downloads the realm images, extracts the game data from your install, imports the databases (5 to 20 minutes) and connects to the relay. Running it again is safe: it keeps your realm, characters and links.

### If the realm images are not published yet

The kit first downloads ready-made realm images. If they are not published yet, it says so (or says your PC seems offline) and gives you two choices:

- `build`: build them on your PC with the same recipe (AzerothCore and the modules at fixed versions). It takes 1 to 2 hours and about 15 GB of disk, once. Later runs use what you built.
- `stock`: start right away with AzerothCore's own images, without the extras (bots, the boost, transmog and the rest). Run the kit again later to switch.

To answer without the question, set `WU_BUILD=1` (build) or `WU_BUILD=0` (stock).

## leyline host

On macOS or Linux, from the host kit folder:

```
bash leyline host
```

It asks a few questions the first time. Re-running it is safe; the last answers are the defaults.

1. **Realm name.**
2. **Ruleset**: one of the presets below. The default is `dalaran`.
3. **Public or private.** The default is public.
4. **A one-line tagline** for the realm list (first run only).
5. **House rules**: keep them or type new ones.
6. **Your GM account name**: 3-16 letters or digits.

It writes the config (`state/host.json`, `state/rules.txt`, `.env`), starts the realm, and the realm's agent registers with the relay. A public Beacon shows on the realm list within a minute.

On Windows, double-click `Host a Wrath realm.bat` instead.

### The other commands

| Command | What it does |
|---|---|
| `leyline status` | your invite or join link, realm list line, GM account, relay status |
| `leyline gm NAME` | give GM rights to your own account NAME |
| `leyline rules` | send new house rules after you edit `state/rules.txt` or `state/beacon.json` |
| `leyline rules --edit` | type the rules again |
| `leyline public` / `leyline private` | listed on the realm list, or friends only |
| `leyline check` | is it reachable? |
| `leyline stop` | stop the realm |
| `leyline logs [service]` | logs |
| `leyline new-invite` | a new invite link; the old one stops working |
| `leyline claim TOKEN` | link the realm to your Hero Key account (see [Hero Key](hero-key.md)) |
| `leyline signup invite`, `open` or `off` | who may make accounts on your join page |
| `leyline host --config-only` | write the config without starting anything |

Answers can come from the environment, so it can run without prompts: `LEYLINE_NAME`, `LEYLINE_RULESET`, `LEYLINE_VISIBILITY`, `LEYLINE_GM`, `LEYLINE_TAGLINE`, `LEYLINE_RULES_FILE`.

## Presets

| Preset | What it is |
|---|---|
| `dalaran` | A light hangout. Every new character picks level 1 or a one-time boost to 80, and goes to Dalaran. Free repairs, free respec, duel reset. No bots by default, 40 players at most. |
| `main` | A full game from level 1 at 3x experience, with the optional one-time boost to 80. |
| `brawl` | Everyone starts at 80 in Dalaran with their class spells, riding and reputations. |
| `progression` | 1x rates from level 1. Each character moves through the three eras of content at their own pace. No boost. |

## House rules

Your rules live in `state/rules.txt`: one rule per line, up to 10, 120 characters each. Lines that start with `#` are ignored. The `dalaran` preset starts with four hangout rules.

The tagline, summary, type (PvE, PvP, RP, RP-PvP or Fun) and Discord invite live in `state/beacon.json`. After editing either file, run `leyline rules`. The agent sends the new text with its next signed heartbeat, and the realm list shows it as "House rules".

## The GM account

`leyline` never makes accounts and never sets passwords.

1. It asks for the name of your GM account.
2. You open **your own link** (`state/host-link.txt`). It holds the invite plus a host key. Keep it to yourself.
3. You make that account on the join page with a password you choose. Your password never leaves your browser.
4. The agent gives that account GM rights by itself, within seconds. Nobody else can take the name: the relay only accepts it with the host key.

Useful GM commands in the game:

| Command | What it does |
|---|---|
| `.gm on`, `.gm off`, `.gm visible off` | GM mode, invisible |
| `.announce TEXT`, `.notify TEXT` | a message to everyone, in chat or on screen |
| `.tele dalaran` | go to Dalaran |
| `.appear NAME`, `.summon NAME` | go to a player, or bring them to you |
| `.kick NAME`, `.mute NAME MINUTES REASON`, `.unmute NAME` | moderation |
| `.ban account NAME 1d REASON`, `.unban account NAME` | bans (`30m`, `1d`, or `-1` for permanent) |
| `.account set gmlevel NAME 2 -1` | make a friend a moderator (1), GM (2) or admin (3); `0` takes it back |
| `.server info`, `.saveall`, `.server restart 300` | status, save everyone, restart in 5 minutes |

Without `leyline`, the host scripts (`Host a Wrath realm.bat`, `host-wrath-realm.sh`) make a GM login for you on first run, in `state/host-login.txt`. Only the login key goes into the database.

## Private and public

**Private** (friends only):

- Friends get `state/invite.txt`. They open it once on the PC they play from and make their own account there.
- The secret is in the part of the link after `#`, so it never reaches a web server log. The relay keeps only a hash of it.
- A stock client gets in only from an internet address that opened the invite. That lasts 24 hours. Players behind the same carrier address share it; their passwords still protect each account.
- `leyline new-invite` locks out new visits with the old link.
- Signup defaults to `invite`.

**Public** (on the realm list):

- The realm sends a signed heartbeat every 60 seconds and shows on the realm list.
- Signup defaults to `open`, so strangers from the list can make accounts.
- Warden is on for public realms (stock clients) and off for private ones, so the browser client can join.

Keep `state/` and `.env`. They are the realm's identity: its key, invite and passwords. The realm id comes from the key, so a reinstall with the same `state/` keeps the same id, ports and listing.

## The relay

The relay sits between players and hosted realms.

- **Tunnel.** The realm opens one WebSocket out to `wss://relay.../agent`. The relay sends a challenge and the realm signs it with its own Ed25519 key. The realm id is made from that key, so there are no accounts or shared tokens to register.
- **Addresses.** Each realm gets a fixed pair of ports on the relay: auth and world. A stock client uses `set realmlist relay.openvanilla.app` or the realm's own auth port. The browser client uses `wss://relay.openvanilla.app/r/<realm id>/ws/<port>`.
- **Accounts.** The join page computes the login key (SRP6 salt and verifier) in your browser and sends only that. Neither the relay nor the host sees the password.
- **Limits.** Per realm: 128 connections and 512 KB/s. Per player address: 8 connections a realm, 40 new connections a minute. 3 new realms per address an hour. A blocklist removes an abusive realm within a minute.
- **Privacy.** Hosts never see player addresses, and players never see the host's. Logs keep addresses only as a salted daily hash.
- **Self-hosting.** A realm id is not tied to one relay. The kit takes `WU_RELAY=<name>`, so a community relay works today.

The relay is Python with the standard library (plus optional `cryptography`). Its wire format is documented in `hosting/kit/tools/wunet/mux.py`.

## The realm list

[play.openvanilla.app/wrath/realms](https://play.openvanilla.app/wrath/realms) shows Wrath first, then every public Beacon from the relay's listing: name, ruleset, players and bots counted apart, house rules and a **Join** link. A slow or dead relay never slows the page.

In the game, Esc, then Mods & Workshop, then Leyline realms (or `/leyline`) shows the same list. **Copy link** gives you the realm's share link. Hopping to another realm from inside the game is planned.

The listing's rules:

- The listing builds each record itself from the host's text. Hosts can't set "official", order or badges.
- Order is live first, then by name. No paid placement, no votes.
- A record goes offline after 3 missed heartbeats and leaves the list 24 hours after the last one.
- It is readable by anyone at `/api/listing/realms.json`. The schema is in [Other servers](cross-server.md#the-realm-record-and-listing-schema).

## Discord bridge

The bridge links the realm's World chat channel with one Discord channel, both ways, and feeds `.bug` reports to a second channel. It is built but off until the owner fills in the bot's settings and turns it on. Players see `[Discord] Name: text`. `.discord off` hides those lines for you.

The daemon talks to the realm only over SOAP and to Discord over its REST API.

## More detail

The full operator guide is `hosting/INSTALL-OPERATE.md` and the design is `hosting/README.md`, both in the [Leyline repo](https://github.com/orionopenwow/Leyline/tree/main/hosting).
