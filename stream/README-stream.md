# Play in the browser, streamed (WrathUnleashed 3.3.5a)

Signed-in players press **Play in your browser** on `https://play.openvanilla.app/wrath` and play a
small "mini" slice of the game at `https://wrath.openvanilla.app`, with no download and no game
files of their own. The game files come from the server, but only the slice: Dalaran, the two
capitals, the starter areas, and the instances of the tiers that fit in the disk budget. The full
client is never hosted. The realm keeps browser players inside the slice. To go anywhere else, they
play with their own game files: in the browser too ("Play with my own game files", below).

Three PC tools: **Size report.bat** (what every part of the game would cost on the server),
**Make mini slice.bat** (build and upload the slice) and **Upload a mini slice.bat**.

## How it works

```
play.openvanilla.app/wrath/play?mini=mini   (wu-portal: signed in? mark the account on the realm,
        |                                    12 h session, one-time 60 s code)
        v
wrath.openvanilla.app/__gate?code=...       (wu-portal: code -> HttpOnly Secure SameSite=Lax cookie wu_play)
        v
wrath.openvanilla.app/                      Caddy forward_auth -> wu-portal /__auth (cookie valid?)
   /__env.js  -> wu-portal                  window.__wenilla_env = {user, pass, host}: auto-login
   /, /data/*, /ws/3724, /ws/8085 -> wu-play   wenilla-host --only-listed: the slice and nothing else,
                                            WebSockets relayed to play.openvanilla.app:3724/8085
in game: lua/ov_slices.lua                  a marked account that leaves the slice goes home (starter area, capital or Dalaran)
```

- **Credentials** never go in a URL. The page loads `/__env.js` (same-origin only, `no-store`, only for
  the session's cookie). The client reads `window.__wenilla_env` before the query string
  (`benilla_app::webenv::page_env`). `stream-up.sh` changes the server's copy of `index.html` to load
  it and drops the dev page's `dev_query_creds`.
- **Only the slice**: `wu-play` runs `wenilla-host --patch /slice --only-listed`. Any name that is not in
  the slice folder returns 404, and `__index` lists only the slice. No MPQs are on the server.
- **The realm rule** (`lua/ov_slices.lua`, mod-ale): on login, zone change and map change, a marked
  account outside its tiers is sent back to Dalaran (resurrected if dead). It gets a whisper and a
  centre-screen message: *"This part of the world isn't streamed to the browser. To go everywhere,
  play with your own 3.3.5a game files. Need help finding or setting up your own 3.3.5a game folder?
  Join our Discord and people will help: https://discord.gg/hVeUxYwbkr"*. On Northrend (map 571),
  only zone 4395 (Dalaran, including the Underbelly and the Violet Citadel) counts as inside. Dalaran
  is always home, even at `maxTier` 0.
- **`.play`** (marked players and GMs) opens a menu: Dalaran spots, and the streamed dungeons and raids.
  These teleport to the instance's own entrance inside the map, which is the target of its
  `areatrigger_teleport` row. Raids need a raid group. Group members share the leader's instance. If
  the server refuses entry (level, heroic key), the menu says why. Arenas and battlegrounds get
  "how to queue" text, because those maps cannot be entered without a match.
- **Dungeon Finder**: a marked player can queue only for streamed dungeons, using the hook
  `PLAYER_EVENT_ON_CAN_JOIN_LFG`. Random queues are refused because the server picks the map.
  `stream-up.sh` builds the id-to-map table from the server's own `client-data/dbc/LFGDungeons.dbc`
  (`lua/lfg_ids.py` → `ov_slices_lfg.lua`). mod-ale cannot veto **battleground queues**. For those,
  the map-change check is the backstop: Warsong Gulch, Arathi Basin, Eye of the Storm and Strand are
  streamed in the battlegrounds tier, and anything else sends the player home.
- **How the gate marks the account**: it sends the SOAP console command `ovstream mark <ACCOUNT> mini
  <maxTier> 43200`. `ov_slices.lua` handles that command (mod-ale's `PLAYER_EVENT_ON_COMMAND`, which
  fires with `player = nil` for console and SOAP commands) and writes `acore_auth.ov_stream_accounts`
  through the worldserver's own auth-database connection. If the realm does not answer
  `ovstream ok`, the gate refuses streaming. An unmarked account would not be held to the slice.
  The command is not in the SOAP bridge's allow-list, so the realm service cannot send it.
  - *Why SOAP and not a database user:* wu-portal already talks SOAP to the worldserver with its GM
    account. A dedicated MySQL user would need wu-portal on `ov-wotlk_backend`, a new grant, and a
    MySQL client in Python. The `python:3.12-alpine` image has no client, PyMySQL is not allowed, and
    MySQL 8.4 defaults to `caching_sha2_password`, whose first login needs RSA or TLS. That would mean
    hand-writing that handshake. The console-command path adds no new user, no network and no
    dependency. It also keeps the realm's in-memory copy of the mark current at once, so an online
    player is checked immediately. (A mod-ale command handler is not player-only. `ALE::OnCommand`
    pushes `player = nil` for console handlers, and AzerothCore's SOAP runs commands through the CLI
    handler: `ACSoap.cpp` → `QueueCliCommand` → `ChatCommand::TryExecuteCommand` →
    `OnTryExecuteCommand`.)
- **Level-1 characters** (below `lowLevel`, 15): they live in their faction's starter area
  (Northshire Valley for every Alliance race, the Valley of Trials for every Horde race) and capital
  (Stormwind City, Orgrimmar). A new dwarf, night elf, undead... is moved to its faction's starter
  area on first login. Leaving (checked on zone, area and map change, and every 5 s for the starter
  boxes, which can be left without a zone change) sends them back with the own-files + Discord
  message. `.play` shows their starter area and capital. No Dungeon Finder.
- **From level 15**: every streamed tier. The Dungeon Finder queues for the streamed dungeons of their
  level (Specific Dungeons; the level range comes from LFGDungeons.dbc), `.play` has submenus (Dalaran,
  your capital and starting area, dungeons of Azeroth / Outland / Northrend, raids, PvP). Home (where
  "outside the slice" sends them) is their capital, Dalaran from level 68.
- **Death Knights** start in Ebon Hold (map 609, a starter tier), which stays open to them. When the
  chain sends them to Light's Hope (not streamed) they go to their capital.
- **"Boost to level 80"** (the main realm's `ov_main.lua`) is unchanged and works for streamed
  characters: it sets level 80 and teleports to Dalaran, which is always inside the slice
  (`tests/test_ov_slices.lua` runs the real `ov_main.lua` beside `ov_slices.lua` to check this).
- **"End my browser pass"** (`/wrath/play/end`) clears the mark at once. The mark is per game account,
  so while it lasts (12 h) the account is held to the slice from the desktop client too.

## The mini slice: tiers and the budget

Each tier in `slices/mini.json` has a stable `key`. The top-level **`order`** list is the priority:
a tier's number is its position there. **To reorder, move a key; to drop a tier, delete its key from
`order`.** Each tier is exported separately, and the slice grows until the budget (`budgetMB`:
3072) is reached. The realm reads the same file: `stream-up.sh` and every slice upload run
`lua/tiers_lua.py` to make `ov_slices_tiers.lua`, so nothing is listed twice.

The kit's order (the owner's priority; tier numbers are positions, so they follow any change):

| tiers | key(s) | what | maps |
|---|---|---|---|
| 0 | `base` | login, character create (all races/classes), UI, spell effects, sounds, item models (lite textures) | DBC, Interface, Character, Item, Spells... |
| 1 | `dalaran` | Dalaran, the Underbelly, the Violet Citadel | 571, tiles under zone 4395 + 1 margin |
| 2 | `arenas` | the five arenas | 559, 562, 572, 617, 618 |
| 3 | `violet-hold-toc` | Violet Hold, Trial of the Champion | 608, 650 |
| 4, 5 | `stormwind`, `orgrimmar` | Stormwind City, Orgrimmar | 0 zone 1519, 1 zone 1637 (+ 1 tile margin) |
| 6, 7 | `northshire`, `valley-of-trials` | Northshire Valley, Valley of Trials | 0 and 1, a world box each (+ 1 tile margin) |
| 8 | `ebon-hold` | Ebon Hold (Death Knight start) | 609, zone 4298 |
| 9 | `naxx-os-voa` | Naxxramas, Obsidian Sanctum, Vault of Archavon | 533, 615, 624 |
| 10 | `battlegrounds` | Warsong Gulch, Arathi Basin, Eye of the Storm, Strand of the Ancients | 489, 529, 566, 607 |
| 11 | `heroic-rotation` | Utgarde Pinnacle, Halls of Lightning/Stone, Nexus, Culling of Stratholme | 575, 602, 599, 576, 595 |
| 12–30 | `ragefire-chasm` ... `stratholme` | classic dungeons in level order, one tier each: Ragefire Chasm, Wailing Caverns, Deadmines, Shadowfang Keep, Blackfathom Deeps, Stockade, Gnomeregan, Razorfen Kraul, Scarlet Monastery (all four wings: one map), Razorfen Downs, Uldaman, Maraudon, Zul'Farrak, Sunken Temple, Blackrock Depths, Dire Maul, Blackrock Spire, Scholomance, Stratholme | 389 ... 329 |
| 31–46 | `hellfire-ramparts` ... `magisters-terrace` | TBC dungeons, level order | 543 ... 585 |
| 47–52 | `utgarde-keep` ... `oculus` | Wrath levelling dungeons not in another tier | 574, 601, 619, 600, 604, 578 |
| 53 | `icc-toc` | ICC 5-mans, Trial of the Crusader, Icecrown Citadel | 632, 658, 668, 649, 631 |

`base` and `dalaran` must stay first (tier 0 and 1); everything after can move. The realm rule and
every test look tiers up by key, never by position (`tests/test_lua.py` also runs the realm tests
under three shuffled orders).

A map entry is a whole map, a `zone` (tiles under its world-map rect), a world `box` (x min, x max,
y min, y max: for a subzone, which has no rect) or `tiles`; `marginTiles` widens what streams, the
realm rule uses the zone or box itself. `spawnBox` limits the creatures and objects `displays.py`
takes on a continent. The open world, quests outside the starter areas, Wintergrasp, Alterac Valley
and Isle of Conquest are not streamed.
`maxTier` is the highest tier the server holds. In the kit it is the last tier, so the budget
decides: "Make mini slice.bat" lowers it to what fit and uploads that copy with the slice. The gate
passes it to the realm, so players are never sent somewhere the slice does not have. Run
**Size report.bat** first to see what each tier will cost. Fill in `measuredMB` when you want a record.

**Lite textures**: item models and textures are too many to pick from (spec kits, free Armory gear),
so all of them ship with their BLP mips cut to ≤ 256 px. The `lite` setting in `mini.json` controls
this. The export report shows the MB saved and the full size per tier.

### How the file list is made

1. **Static walk, automatic** (`wenilla-host --deps`): for each tier it reads the folders in
   `prefixes`, and for each map the WDT, WDL, loading screen, minimap tiles and ADT tiles (only the
   zone's tiles for Dalaran). It then follows every ADT's textures, M2s and WMOs, every WMO's groups,
   textures, doodads and skybox, and every M2's skins, `.anim` files and textures, using the repo's
   parsers. It also adds the creatures and objects spawned on those maps (from the server's
   `creature`/`gameobject` tables, via `displays.py`, then CreatureDisplayInfo, CreatureModelData,
   baked NPC skins and GameObjectDisplayInfo).
2. **Record, the accuracy check**: "Record a capture.bat dalaran" runs the browser client locally from
   your own game files against the live realm and writes every file it actually asks for to
   `record\names-dalaran.txt`. "Make mini slice.bat" adds every `record\*.txt` at the end, so whatever
   the walk missed is included next time. Each tier in `mini.json` has a `capture` list of where to
   go, with GM `.go xyz` lines for the instances. Known gaps of the walk: sounds (zone music,
   ambience, voices), instance map art, scripted summons and NPC equipment variants.

## What you do

1. **DNS**: add an A record `wrath.openvanilla.app` pointing to the server's IP, the same IP as
   play.openvanilla.app. Caddy gets the certificate by itself once the name resolves.
2. **Client build**: copy the WotLK browser client build into `stream\www\` (the `web/dist` output
   of `scripts/web-build.sh` in benilla-wotlk: `index.html`, `wenilla.js`, `wenilla_bg.wasm` and its
   `.br`/`.gz`, `boot.js`...).
3. **Make the slice**: double-click **Make mini slice.bat**. It uses your Data folder
   `C:\Users\campw\Downloads\World of Warcraft 3.3.5a\Data`; pass another folder as the first
   argument. It uploads the kit and `www`, asks the server what is spawned, walks the data, exports
   tier by tier up to 3 GB, prints the size of each tier, and streams the slice to
   `/srv/wrath/stream/slices/mini`.
4. **Turn it on** (once, on the server): `bash /srv/wrath/stream/stream-up.sh`. You can run it again
   safely. It checks everything first and prints what to fix.
5. **Try it**: sign in at https://play.openvanilla.app/wrath and press **Play in your browser**.
6. **Better accuracy** (optional): run **Record a capture.bat** `<label>` for each place, then
   **Make mini slice.bat** again.
7. **Off switch**: `bash /srv/wrath/stream/stream-switch.sh off`. `/wrath/play` then says "Streaming
   is off right now — play with your own game files" (with the Discord help line). The stream site
   refuses the game data and the login, and every marked account is released. `... on` turns it back
   on. To remove everything: `bash /srv/wrath/stream/stream-down.sh`. It restores the old sign-in
   page and the Caddyfile and unloads the realm rule. The slice files stay; delete
   `/srv/wrath/stream/slices/mini` to free the disk.

**Keep it after a redeploy**: `deploy.sh` and its .bat upload `wrath/server/portal/wrath_portal.py`
again. Copy `stream/wrath_portal.py` over that file, or run `stream-up.sh` again after a deploy. With
`WU_STREAM=0`, the new page behaves exactly like the old one.

## What it costs

- **Disk**: the slice, at most `budgetMB` (3 GB), plus `debian:bookworm-slim` (~75 MB) and the host
  (5 MB). A re-upload unpacks next to the old slice and swaps it in. If there is not enough room for
  both, the old one is removed first and streaming is down during the upload.
- **RAM**: `wu-play` is capped at 256 MB (about 10–30 MB idle). It reads each file whole per request,
  so many players loading big files at the same moment can reach the cap, and Docker then restarts
  it. Raise `--memory` in `stream-up.sh` if that happens. wu-portal is unchanged (128 MB cap).
- **Traffic**: each new browser player downloads the client (~15 MB brotli) and the parts of the
  slice they visit. Browsers cache files, so a second visit costs little.

## Size report.bat: what every part of the game costs on the server

Run it on your PC (it reads your Data folder; nothing is exported or uploaded). It asks the server
once (one SSH connection) which creatures and objects are spawned on every instance map, then
`wenilla-host --size-report` walks the base, every tier of `mini.json` and **every instance in
Map.dbc** (all 5-mans, raids, battlegrounds, arenas: read from the DBC, not a fixed list), and writes
`size report\size-report.md` (a table sorted biggest first, lite and full MB, files, expansion) and
`size-report.json`. Every place is counted **beyond the base**: what it adds on top of the base
alone. Places share files with each other too (rocks, torches, creatures), so the report also gives
the sum of the rows and the union (everything together, each file once); the difference is the
sharing. Without the SSH answer it still runs and says creatures are not counted.

## Play with my own game files (in the browser)

The account page shows **Play with my own game files** (WU_OWNFILES=1, set by stream-up.sh). It opens
the same site, `https://wrath.openvanilla.app/?ownfiles=1`, with a session that has **no realm mark**
(the whole world; an earlier stream mark is cleared) and **no /data from the server** (`/__auth`
answers 403 for /data; the page, its scripts and `/ws` are allowed). The page (`ownfiles.js`) asks for
the player's own 3.3.5a folder and reads it locally; nothing is uploaded. It works with streaming
switched off (`stream-switch.sh off` leaves it alone); it needs the stream site, so `stream-down.sh`
turns the button off. The page must stay cross-origin isolated: wu-play sends COOP/COEP and Caddy
passes them through.

## Download this section (in the browser)

On the streamed site a **download sections** link (top right) opens a panel listing the slice's
tiers with their size. **Download** fetches a whole tier into the browser's Cache Storage (with
progress in MB and files); the game then reads those files from there, with no network. **Remove
downloaded sections** deletes them. The lists come from `/data/__tier/<n>.txt` and
`/data/__tier/index.json`, which `--export` writes into the slice (`.tiers/`) and wu-play serves
behind the same sign-in as `/data`. Why not the HTTP cache or a service worker: the client reads
with synchronous XHR, which Chromium does not send through service workers, and the HTTP cache can
be evicted at any time. `sections.js` answers those reads from the cache through a worker and a
SharedArrayBuffer (the design `ownfiles.js` uses).

## Things to know

- **One source address**: all browser players reach the authserver and worldserver from the server
  itself, because wu-play relays to `play.openvanilla.app`. An IP ban or the failed-login IP lockout
  would hit all of them together. Auto-login uses the correct password, so lockouts should not happen.
- **New characters** of the races that do not start in Northshire or the Valley of Trials are moved
  there on first login; the client may show an empty world for a moment first.
- **Caddy reloads** (any deploy that edits the Caddyfile) drop open WebSockets. Browser players
  reconnect.
- **wu-portal restarts** forget play sessions. Players press Play again.
- **Legal**: this hosts Blizzard's game files, for the slice only, to signed-in players. That is your
  decision as the owner. The files never leave the slice, are never listed beyond it, are only
  reachable with a sign-in cookie, and the off switch stops them at once. The website never links to
  or describes any download of the game client. The help line points players to the Discord.

## Files

| file | what |
|---|---|
| `bin/wenilla-host` | Linux x86_64 host (glibc ≥ 2.34; runs in debian:bookworm-slim, glibc 2.36) |
| `bin/wenilla-host.exe` | Windows host, for `--deps`, `--export` and `--record` on your PC |
| `wrath_portal.py` | the sign-in page with the gate (a copy of `wrath/server/portal/wrath_portal.py` plus streaming) |
| `lua/ov_slices.lua`, `lua/lfg_ids.py`, `lua/tiers_lua.py` | the realm rule, the Dungeon Finder id/level table maker, the tier table maker (mini.json → `ov_slices_tiers.lua`) |
| `sql/ov_stream_accounts.sql` | the mark table (acore_auth) |
| `slices/mini.json` (+ boot manifests) | the slice description, tiers, capture lists |
| `server/stream-up.sh`, `stream-down.sh`, `stream-switch.sh`, `slice-install.sh`, `patch-index.sh`, `displays.py`, `www-patch.py`, `stream-lib.sh` | server side, in `/srv/wrath/stream` |
| `www-files/` | the browser additions: `ownfiles.js` (+ worker, `mpq.js`, `chain.js`), `sections.js` (+ worker), and the edited `index.html`/`boot.js` for reference; `www-patch.py` applies the same edits to the uploaded client build. `web.patch` is the same change for the source tree (`web/` + `scripts/web-build.sh`) |
| `Size report.bat`, `Make mini slice.bat`, `Upload a mini slice.bat`, `Record a capture.bat` | your PC |
| `wenilla-host-stream.patch` | the Rust changes (`--record`, `--export`, `--only-listed`, `--deps`, lite BLP, `--size-report`, tier lists, `/data/__tier`) |
| `tests/` | `python3 -I tests/test_stream.py wrath_portal.py`, `python3 -I tests/test_realms.py wrath_portal.py` (the /wrath/realms list), `python3 -I tests/test_lua.py`, `bash tests/test_server_scripts.sh <linux host>`, `node --test tests/sections.browser.test.cjs` |

## wenilla-host switches

```
--record <file>                       append each /data name served (once, any case) while serving
--only-listed --patch <slice>         serve the slice folder only (404 otherwise; __index = the slice)
--deps <mini.json> --tiers 0-4 --displays displays.tsv --out <dir>    static walk -> <dir>/tier-N.txt
--size-report <mini.json> --displays all.tsv [--boot <manifest>]... --out <dir>
                                      measure base, tiers, every Map.dbc instance -> size-report.md/.json
--export <list>... <outdir> [--boot <manifest>]... [--slice mini.json] [--budget-mb N]
         [--lite-prefix P]... [--lite-max 256] [--dry-run]           extract, tier by tier, with a size report
                                      (and <outdir>/.tiers/<n>.txt + index.json, served as /data/__tier/...)
```
