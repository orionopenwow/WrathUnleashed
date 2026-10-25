# Other servers

Many community servers run 3.3.5a and 1.12 realms. This page says how they and their players fit with Leyline. It sticks to what the code does today.

## What we never do

- We never touch other servers' clients. Leyline ships no patch, launcher or file that changes another server's client.
- We never read, copy or import other servers' data: no accounts, characters, databases or files.
- We never ship game data. Hosts extract what they need from their own install, on their own PC.
- The realm list never ranks by money or votes, and hosts can't buy a better place.

## Players from other servers

- Your own 3.3.5a client works on Wrath and on hosted Beacons. You only change the realm list line. See [Play](play.md#with-your-own-client).
- Your client folder stays yours. Change the realm list line back to play elsewhere.
- Accounts on Leyline realms are separate from accounts on other servers. Nothing moves between them.
- Addons you made for the stock 3.3.5a client can become Leyline mods. A UI-only mod is a normal addon in `ui/<Name>/` plus a `mod.json`. See [Mod format](mods.md).

## The open layers

Three parts are documented so anyone can adopt them, with or without Leyline. All of it is MIT licensed.

### The mod format

A folder with a `mod.json`, an addon in `ui/`, mod-ale Lua in `realm/`, or both. The rules are in [Mod format](mods.md). The checker, `mods/wu-mod.py`, uses only the Python standard library, so any server can run it on its own mods. Realm halves run on any AzerothCore 3.3.5a realm with mod-ale. Mods that talk to their addon also need the realm's `ov_modapi.lua` (the OVMOD channel).

### The realm record and listing schema

The relay serves its list at `GET /api/listing/realms.json`, readable from any site:

```
{ "schema": 1, "kind": "community", "updated": "...", "realms": [ <record>, ... ] }
```

Each record is a Beacons schema 1 record plus a `community` block:

| Field | Value |
|---|---|
| `slug` | `c-<realm id>` (16 base32 characters made from the realm's Ed25519 key) |
| `official` | always `false` |
| `state` | `live` while heartbeats arrive, `offline` after 3 missed ones; gone after 24 hours |
| `order` | always `1000`; then live first, then by name |
| `profile` | `game` (`wrath-3.3.5a`), `version`, `build`, `ruleset`, `address`, `port` |
| `connect` | `{"kind": "web-signin", "url": ".../join/<id>", "label": "Join this realm"}` |
| `status` | `{"url": ".../r/<id>/status.json", "format": "openvanilla-status-1"}` |
| `community` | `realmId`, `relay`, `signed`, `claimed`, `claimedBy`, `firstSeen`, `lastSeen`, `lastHeartbeat` |

Text from the host has fixed limits: name up to 32 characters, tagline 80, summary 400, up to 10 rules of 120, and a Discord link only as `https://discord.gg/...`. Readers should show it as text, never as HTML. Players and bots are separate numbers; bots are never added to players.

A realm's own status uses the same `openvanilla-status-1` idea. Wrath's is at [play.openvanilla.app/wrath/status.json](https://play.openvanilla.app/wrath/status.json): realm, online, players, bots, queue, uptime and build.

The full schema is `hosting/site/SCHEMA-community.md` in the repo.

### The relay protocol

The tunnel between a realm and the relay is one WebSocket with small binary frames:

```
op (1 byte) | stream id (4 bytes, big endian) | payload
OPEN  0x01  relay to agent   payload: the port (3724 or 8085). A new player connection.
DATA  0x02  both ways        raw TCP bytes of that connection, at most 32 KB
CLOSE 0x03  both ways        the connection is gone
```

Control messages are JSON: a challenge, a signed hello, a welcome with the realm's ports, pings, and requests such as status and account creation. Heartbeats to the listing are signed with the realm key, carry a growing sequence number, and must be within 5 minutes of the listing's clock.

The protocol is written down in `hosting/kit/tools/wunet/mux.py`, and the listing rules in `hosting/relay/wurelay/listing.py`.

## How another server can list on Leyline

Today the listing only shows realms that keep a live tunnel to the relay. There are two ways to do that.

**Run your realm through the host kit.** If your realm is AzerothCore 3.3.5a, the kit's agent can connect it to the relay:

1. Set up the host kit (see [Hosting](hosting.md)).
2. Make it public: `leyline public`.
3. Fill in `state/beacon.json` and `state/rules.txt` with your name, tagline, type, rules and Discord link, then run `leyline rules`.
4. Your realm shows on the realm list within a minute. Players join through the relay with their own clients.
5. When the website side is built, claim the record with a [Hero Key](hero-key.md).

**Run your own relay.** The relay is open source. A realm id comes from the realm's own key, not from our relay, and the kit takes `WU_RELAY=<name>`, so a community relay works today. A directory of relays, so lists can be shared between relays, is planned.

To confirm:

- Listing a server that keeps its own login server and doesn't use the relay. The listing has no way to do this yet.
- Listing a 1.12 server. The listing's records say `wrath-3.3.5a` today.
- Adding an official record to the website's realm files (the Beacons `www/realms/` folder). That is in the website repo, not here.

## Working together

How communities could go further together is a separate proposal: [Working together](unite.md).
