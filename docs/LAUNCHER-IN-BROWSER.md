# The launcher in the browser: parity

The owner, 2026-10-30: "we want one click on site server joins, all features in the launcher in the browser as well".
This page lists every page of the Leyline launcher (launcher/ui/index.html, social.js, modes.js) next to what the
website and the browser game offer today, the gap, and how to close it. The new hub pages are still hidden: they live
under `/wrath/leyline-preview` (stream/hub.py) until `WU_HUB_FRONT=1` makes the hub the front door at `/wrath/leyline`.

Status: **done** = the browser has it now. **closed** = closed by the hub work in this change (hidden preview).
**open** = still a gap; the "Later" list below says what it takes.

| Launcher page | What it does in the launcher | The website / browser game today | Gap | Status |
|---|---|---|---|---|
| Home | Pick a game client and a realm, PLAY (writes the realmlist, starts the client) or BROWSER mode; realm status; news teaser | `/wrath` plays the official realm in the browser; the hub front page has Platform Status and the realm list with Play in browser on every live 3.3.5a realm | A desktop client can't be started from a web page. The browser game is the web's PLAY; only 3.3.5a realms play in it | done (by design: the browser plays 3.3.5a; desktop clients stay in the launcher) |
| My Mods | Installed mods per client: turn off/on, update, remove, add a zip | Nothing: a website can't see or change files in a game folder | Managing a desktop client's AddOns folder; mods for the browser game itself | open (Later 3) |
| Discover | The catalog (Workshop + community index + themes), Hot/Rising/Top, ratings, INSTALL | `/wrath/leyline-preview/catalog` with the same sorts and rankings (hub_rank), item pages with ratings and **Install with Leyline** (`leyline://install/<id>`, which deeplink.rs accepts) | Install needs the launcher on this PC; nothing installs into the browser game | done for desktop (one click hands over to the launcher); browser-game installs: open (Later 3) |
| Realms | The network: featured, the official realm, Beacons by the fair score, filters (build, rules, region, language, has players), Add a realm, invite links for private realms | `/wrath/realms` (old look) and now the hub's realm list: under the hero on the front page and the full list at `/wrath/leyline-preview/realms`, with the same order and filters, one-click **Play in browser** (`/wrath?go=r:<id>`, ours plain `/wrath`), the desktop address with a Copy button, live player counts | **Open in launcher** for a realm: deeplink.rs only understands `install/<id>` today. Private-realm invite links open on the relay (`/join/<id>`) in the browser already | closed (list, filters, one-click browser join, address); Open in launcher: open (Later 1) |
| Modes | Every game mode from `/wrath/modes.json`, PLAY signs in and starts the mode | `/wrath/modes` (old look, duels and boss fights first) and now `/wrath/leyline-preview/modes`: every mode in stream/playmodes.json, one click (`/wrath?go=mode:<id>`), Host it for realm types, Coming soon shown | Offline modes that need the player's own game folder (Azeroth Survivors) are "coming" on both | closed |
| Host | Host pack, profiles, house rules, realm list details (tags, region, language, limit), start/stop the realm in Docker on this PC | `/wrath/host`: the one-click host form makes the realm and a setup script for the host's PC (stream/hostflow.py); the hub's Host a Beacon page and the Host your own panel | The server itself has to run on a PC or a server; a web page can't start Docker. Start/stop and logs of a running realm are launcher-only | done for setup; running it: open (Later 4) |
| Friends | Device sign-in, friends, requests, presence, messages (stream/social.py over `/wrath/api/social`) | The API takes the website's own sign-in already (cookie, CSRF); `/wrath/link` approves launchers; the in-game window has friends on the realm | No friends page on the website | open (Later 2) |
| Community Hub | Links: Discord, the Leyline page, the Workshop, GitHub | The hub's footer and header (Discord, GitHub), Community Spotlight, the Community hub product card (`/wrath/workshop`), Creators | Nothing missing | done |
| News | The launcher's built-in posts, "More on the website" | The admin console publishes `/wrath/leyline/news.json`; now `/wrath/leyline-preview/news` shows those posts | The launcher still shows its built-in NEWS list in app.js rather than news.json | closed on the web; the launcher reading news.json: open (Later 5) |
| Settings | Wine for macOS/Linux, update channel, privacy, your data, native code, themes | Not needed in the browser (no Wine, the page updates itself, no telemetry) | Themes: the browser has the one Dark look | done (nothing to carry over); a Light look on the hub: Later 6 |

## Closed in this change (all hidden with the preview)

- **Realm list under the hero** on the front page and the full list at `/wrath/leyline-preview/realms`: our realm
  first, then the network's order (stream/network.py `order()`, the launcher's realms.rs order), offline last, builds
  above 3.3.5a left out (`MAX_OFFERED_BUILD`). One-click Play in browser, the desktop address (Copy), live counts.
- **Modes page** `/wrath/leyline-preview/modes`: every game mode, one click.
- **News page** `/wrath/leyline-preview/news`: the admin console's posts.

## Later (the bigger gaps)

1. **Open in launcher for realms.** Add `leyline://realm/<realm id>` to launcher/src-tauri/src/deeplink.rs (a
   16-character base32 id, like `REALM_ID_RE`), have app.js open Realms with that realm chosen (never PLAY by itself:
   the click in the launcher is the consent, as with install), then set `REALM_DEEPLINK = "leyline://realm/{id}"` in
   stream/hub.py and the rows get the button. Needs a launcher release, so a Tauri build.
2. **Friends on the website.** A `/wrath/friends` page on the existing `/wrath/api/social` API (cookie sign-in, the
   CSRF it already hands out, the `events` long poll). Mostly a page and a small script; no new storage.
3. **Mods for the browser game.** Installing a Workshop UI mod into the browser client (it would be a layer the game
   page loads, per account), and a My Mods page to turn them off and on. Needs the browser client's addon loading
   and the Workshop's permissions review to cover it. Desktop clients stay with the launcher.
4. **A running realm from the web.** Status, start/stop and logs of a hosted realm from `/wrath/host/<id>`, through
   the Beacon agent on the host's PC. Needs a control channel the agent doesn't have today.
5. **One news source.** The launcher reads `/wrath/leyline/news.json` (cached) instead of its built-in list, so the
   website and the launcher say the same.
6. **Light look on the hub.** The launcher has Dark and Light; the hub is Dark only.
7. **Other builds in the browser.** Play in browser is 3.3.5a only (the browser client). 1.12.1 and 2.4.3 realms show
   "Needs a 1.12.1 client" and their address.
