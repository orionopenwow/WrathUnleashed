# Leyline

Leyline is an open-source network for community game realms. You can play on its realms, make mods for them, and host your own realm from your own PC. Everything is on GitHub under the MIT licence.

Wrath is the flagship realm. It runs the 3.3.5a game on AzerothCore, and you can play it in the browser at [play.openvanilla.app/wrath](https://play.openvanilla.app/wrath).

## The aims

- **Play without a big install.** A browser tab is enough for the parts of the world we stream. The whole world uses your own game files, which stay on your computer.
- **Anyone can host.** A realm runs on the host's own PC. Players reach it through a relay, so the host opens no ports and nobody sees the host's home address.
- **One open mod format.** A mod is a folder with a `mod.json`. One checker tool enforces every rule. Anyone can make one and anyone can read the rules.
- **Fair by design.** No shop and nothing to buy. Bots are always labelled and counted apart from players. The realm list is never ordered by money or votes.
- **Open layers.** The mod format, the realm listing schema and the relay protocol are documented, so other projects can use them without asking us.
- **No game data from us.** We never ship or upload game files. Hosts extract what a server needs from their own install, on their own PC.

## What's live and what's planned

"Live" means it runs for players today. "Built" means the code is in the repo and tested, and it works once an operator switches it on. "Planned" means it is not built yet.

| Part | Status | Where to read |
|---|---|---|
| Wrath in the browser (streamed Dalaran area, sign-in with Google or a Hero Key) | Live | [Play](play.md) |
| Wrath with your own 3.3.5a client | Live | [Play](play.md#with-your-own-client) |
| In-game commands (.wu, .bug, .stuck, .recruit, .buddy, .go, .armory and more) | Live on Wrath | [Commands](commands.md) |
| Mod format 0.1 and the `wu-mod.py` checker | Live | [Mod format](mods.md) |
| The Workshop at /wrath/mods and the in-game Workshop tab | Live | [Publishing](publishing.md) |
| Realm list at /wrath/realms and the in-game Leyline window | Live | [Hosting](hosting.md#the-realm-list) |
| Web armory, Modes hub and share links | Live | [Play](play.md#share-links) |
| These docs at /wrath/docs | Live once shipped with the sign-in step | this page |
| Host kit and the `leyline host` command | Built | [Hosting](hosting.md) |
| The relay (tunnels, join pages, listing) | Built | [Hosting](hosting.md#the-relay) |
| Discord bridge | Built, off until the owner sets it up | [Hosting](hosting.md#discord-bridge) |
| Drop your own 3.3.5a game folder on the streamed page to go anywhere | Built | [Play](play.md#use-your-own-game-folder-to-go-anywhere) |
| Play in the browser with your own game folder | Built, behind a switch | [Play](play.md#in-the-browser-with-your-own-game-folder) |
| Goldshire Inn guest pass (no sign-up) | Built, off by default | [Play](play.md#guest-pass) |
| Realm claims with a Hero Key | Listing side built; website side planned | [Hero Key](hero-key.md) |
| Leyline Launcher (desktop app): clients, mods, realms, hosting | Built (0.2), no release yet | [Launcher](launcher.md) |
| `wu-mod test` on a local test realm | Planned | [Mod format](mods.md#what-is-planned) |
| Signed mod packages | Planned | [Mod format](mods.md#what-is-planned) |
| Hopping between realms from the in-game list | Planned | [Hosting](hosting.md#the-realm-list) |
| Friends across realms | Planned | [Working together](unite.md) |
| A directory of community relays | Planned | [Other servers](cross-server.md) |
| Peer-to-peer realm list and mod sharing | Planned | [Launcher](launcher.md) |

## Where to go next

- New player: [Play](play.md), then [Commands](commands.md).
- Mod maker: [Mod format](mods.md), then [Publishing](publishing.md).
- Host: [Hosting](hosting.md).
- Running another server: [Other servers](cross-server.md) and [Working together](unite.md).
- Accounts and sign-in: [Hero Key](hero-key.md).

The source is at [github.com/orionopenwow/WrathUnleashed](https://github.com/orionopenwow/WrathUnleashed). The network parts are copied to [github.com/orionopenwow/Leyline](https://github.com/orionopenwow/Leyline).
