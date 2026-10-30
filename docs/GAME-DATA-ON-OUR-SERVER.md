# Game data on our server, and the killswitch

The owner's direction (2026-10-29): **no game data served from our Hetzner server.** The slim streamed
sampler keeps running until the community realms carry players. Then the owner switches it off with one action:
the **game data killswitch**.

This page lists every route and file on the server that serves game-derived data, and what the killswitch does
to each one. Uncertain items are marked **(uncertain)**. After the switch, the browser client works only with
the player's own 3.3.5a game folder. That is the existing own-files flow: drag and drop, `/?ownfiles=1`,
`stream/www-files/ownfiles*.js`, `chain.js` and `mpq.js`. The folder is read in the browser tab and never
uploaded.

**Not in scope:** torrent or P2P hosting of game data. It is not allowed and nothing here builds it. The
standing rule is "No torrents and no whole-client downloads". The launcher's torrent and P2P plumbing carries
only our own open content (docs/P2P-AND-TORRENT.md).

## Inventory

Sizes are estimates. The switch's own report (`gamedata-switch.sh status`) prints the real numbers on the server.

### Served to players over HTTP: the killswitch closes these

| Route (public) | Comes from (server) | Size (est.) | What it is for | Killswitch |
|---|---|---|---|---|
| `wrath.openvanilla.app/data/<name>` | wu-play (`wenilla-host --patch /slice`) → `/srv/wrath/stream/slices/mini/` | Up to `budgetMB` in `stream/slices/mini.json` (7,424 MB today; the owner calls it "slim" **(uncertain: check `status`)**). Tens of thousands of files. | The streamed slice: models, textures, terrain, sounds, DBCs and the stock interface for the tiers that fit | **410 Gone** (Caddy, and again at `/__auth`). `--park` moves the folder. |
| `wrath.openvanilla.app/data/__index` | wu-play, made from the slice | about 1–3 MB of JSON | Every file name in the slice (game archive paths) | **410** |
| `wrath.openvanilla.app/data/__tier/index.json`, `/data/__tier/<n>.txt` | wu-play, made from the slice | about 1–3 MB in total | Per-tier file lists for "Download this section" (`sections.js`) | **410** |
| `wrath.openvanilla.app/data/Interface/ForeverUI/*`, `.../AddOns/ForeverUI/*`, `.../GlueXML/ForeverUI*` | `/srv/wrath/stream/overlays/foreverui/`, hard-linked into each slice (`fui-install.sh`) | about 20–60 MB **(uncertain)** | Forever UI (GPL code by Adrestie). Its **art comes from the modern game client**. It makes the menus and character select look like that client. | **410** (it is under `/data`). `--park` moves the overlay. `fui-install.sh install` refuses while the switch is on. |
| `wrath.openvanilla.app/data/Interface/GlueXML/*`, `.../Glues/*`, `.../LoadingScreens/*` | the slice | included above | The character-select and loading-screen art and code from the game files | **410** (under `/data`) |
| `wrath.openvanilla.app/boot-manifest.json` | `/srv/wrath/stream/www/boot-manifest.json` (copied from `stream/slices/boot-manifest.json`; Forever UI and the mods add their text files) | about 25 KB, about 520 names | The boot read-set: **game file paths** that boot.js prefetches. Names only, no file bytes. | **410** (Caddy). `--park` moves the file. |
| `wrath.openvanilla.app/world-manifest.json` | `/srv/wrath/stream/www/world-manifest.json` | about 55 KB, about 1,060 names | The world read-set, the same kind of list | **410**. `--park` moves the file. |
| `wrath.openvanilla.app/data/Interface/AddOns/<catalog mod>/*`, `.../WrathUnleashedUI/*`, `.../WUModCatalog/*` | `overlays/mods` and the Forever UI kit, laid into the slice | small | **Our own** open addons (Lua, XML, an OFL/Bitstream-licensed font). Not game data, but they live under `/data`. | Also 410, because all of `/data` goes. Own-files players never got these from `/data` anyway (`/__auth` already refused `/data` to them). |
| `play.openvanilla.app/wrath/art/leyline-shot-{dalaran,start,city,durotar}.webp` | `/srv/wrath/portal/art/` (from `stream/www-files/art/`) | about 470 KB | Screenshots of the running game on `/wrath/leyline` and `/wrath/modes`. Rendered from the game's files. **(uncertain: screenshots, not files; closed to be safe)** | **410** (portal). The pages fall back to a painted panel. |

### Served to players, not game data: stays as it is

| Route | What it is | Why it stays |
|---|---|---|
| `wrath.openvanilla.app/`, `/index.html`, `/wenilla.js`, `/wenilla_bg.wasm`, `/boot.js`, `/ownfiles*.js`, `/chain.js`, `/mpq.js`, `/sections*.js`, `/wrath-*.js`, `/wu-*.js`, `/snippets/*`, `/warm.html`, `/art/*` | The browser client and the page layer. **Our code**, built from our sources. | Own-files play needs it. |
| `wrath.openvanilla.app/__gate`, `/__env.js`, `/__auth`, `/ws/3724`, `/ws/8085` | Sign-in, the session's login, and the realm connection | Own-files play needs it. |
| `play.openvanilla.app/wrath/art/wu-*.webp`, `leyline-{bg,emblem,corner-*,divider}.webp`, the fonts and `wu-theme.css` | The site's look. The loading background and the Orion art are our own. | Our art and open fonts (Cinzel and Big Shoulders, SIL OFL). **(uncertain: `wu-dragon-l/r.webp` and `wu-corner-*.webp` came with the 1.12 boot screen in commit 370d80c; their source isn't recorded. They look like UI frame art. Ask the owner before relying on them; the killswitch leaves them.)** |
| `play.openvanilla.app/wrath/mods/*` (zips, screenshots, `catalog.json`) | Mod packages | Only open formats. `wu-mod.py` rejects MPQ/M2/BLP/ADT/WMO/WDT magic bytes. Mod screenshots are pictures of mods in play, like the Leyline shots **(uncertain; not closed)**. |
| `play.openvanilla.app/wrath/armory/*`, `/wrath/workshop/*`, `/wrath/status.json`, `/wrath/leyline/*.json`, `/wrath/realms`, docs and the hub | Text and JSON from our database and our files | No game files. |
| `relay.openvanilla.app` | The Beacons relay: listings and join pages | No game files. |

### On the server, never served over HTTP

| Path | What it is | Killswitch |
|---|---|---|
| `/srv/wrath/client-data/` (`dbc/`, `maps/`, `vmaps/`, `mmaps/`) | Extracted for AzerothCore. The realm itself needs it to run. | Not touched: it is not served to players. **(uncertain: this is the owner's call if the rule is ever read as "no game data on the box at all")** |
| `/srv/wrath/stream/slices/*.json` (`mini.json`) | Tier descriptions: zone keys, map ids, budgets. No file bytes. | Stays (the realm rule and the portal read it). |
| `/srv/wrath/stream/overlays/backup/` | Earlier copies of our scripts | Stays (not game data). |
| `/srv/wrath/offline-gamedata/<time>/` | Created by `--park` | Not served. Never deleted by the switch. |

### Elsewhere, not on our server (for the record)

- The repository has `stream/slices/boot-manifest.json` and `world-manifest.json`. These are lists of game
  file paths, names only. The `leyline` step copies the repo to GitHub. **(uncertain: whether file names count;
  no bytes)**
- `play.openvanilla.app` may also run the 1.12 Open Vanilla site (`/opt/wenilla-realm`). Its Caddy config is not
  in this repo. **(uncertain: check whether it serves any 1.12 `/data`)** The switch's report lists only the
  WrathUnleashed routes. Run `grep -n '/data\|file_server' /opt/openvanilla-classicplus/Caddyfile` on the
  server to see the rest.

## The killswitch

`stream/server/gamedata-switch.sh off [--park] | on | status` runs on the server and is logged. It does the
following:

1. **The flag file** `/srv/wrath/portal/gamedata-off` (JSON: since, by). wu-portal sees it at `/app/gamedata-off`
   on every request, with no restart. While it exists:
   - streaming is off, whatever `WU_STREAM` says;
   - `/wrath/play?mini=…` goes to "Play with my own game files" (`?mode=own`);
   - `/__auth` answers **410 Gone** (JSON) for `/data…` and the two manifests, for every session;
   - `/__env.js` adds `window.WU_GAMEDATA_OFF = true`;
   - the game screenshots answer 410;
   - `/wrath/status.json` adds `"gamedata_streaming": false, "gamedata_since": "<time>"`.
2. **Caddy.** `gamedata-caddy.py add` puts a block first inside the stream site. The block answers 410 for
   `/data`, `/data/*`, `/boot-manifest.json` and `/world-manifest.json`, so the gate and wu-play are never asked.
   A Caddy that refuses the change gets its previous file back. The flag stays, so `/__auth` still closes `/data`.
3. **The realm.** Every stream account is released, so no one stays held to the slice.
4. **`--park` (optional).** The slices, the Forever UI overlay and the manifests move into
   `/srv/wrath/offline-gamedata/<time>/` and are never deleted. wu-play restarts on empty placeholders and must
   still serve the page, or everything moves back.
5. **Check and log.** `/data/__tier/index.json`, a slice file (`/data/DBFilesClient%5CMap.dbc`) and
   `/boot-manifest.json` must answer **410**. The script prints what was served before and after, appends
   one line to `/srv/wrath/gamedata-switch.log` and writes `/srv/wrath/portal/gamedata-last.json` (the console's
   "since"). It ends with `GAMEDATA OFF OK`.

`on` reverses each step in order: it moves parked files back, takes the Caddy block out, removes the flag, and
checks that `/data` is behind the sign-in gate again (302/401/403). It ends with `GAMEDATA ON OK`.

While the switch is on:
- `slice-install.sh` refuses uploads (nothing new goes onto the server);
- `fui-install.sh install` refuses uploads;
- `stream-up.sh` (the `client` step) keeps the 410 block.

### The owner's steps

- **Turn game data OFF:** run `stream\Game data killswitch ON.bat`. Add `park` to also move the files off the
  served folders. Or ask Claude to queue the Autopilot step `gamedata-off`.
- **Turn it back ON:** run `stream\Game data killswitch OFF.bat`, or use the Autopilot step `gamedata-on`.
- **Look without changing anything:** `ssh root@play.openvanilla.app "bash /srv/wrath/stream/gamedata-switch.sh status"`.

The admin console shows a read-only line on its Dashboard and Health pages: "Game data streaming: on/off since …".
The switch is not a web button.

### What players see when it is off

- **Website** (`/wrath`). The Dalaran card's button reads "Play with my game folder", with one line: "This realm
  needs your own game folder…". The button opens the game page with the folder card. An old "Play now" link
  (`/wrath/play?mini=mini`) goes to the same place.
- **Game page.** The card "Use my own game files" says "This realm needs your own game folder: drop your 3.3.5a
  game folder below." There is no "Stream a mini version" button and no request to `/data`. After the folder
  is checked (build 12340), the game starts on the same account and characters.
- **A page that was already streaming.** Its next `/data` read gets 410. That read is not retried. One note
  appears: "This realm needs your own game folder" with a **Use my game folder** button, which leads to the
  folder card. There are no endless retries and no black screen.
- **Leyline launcher.** In BROWSER mode, with the official realm chosen, the bar reads "BROWSER PLAY · NEEDS
  YOUR GAME FOLDER". PLAY with the player's own desktop client is unchanged.
- **Desktop players** (their own client and realmlist) see no change.
