# Mod format

This is the full reference for the Leyline mod package, format 0.1. It matches `mods/SPEC.md` in the repo. The checker, `mods/wu-mod.py check`, enforces every rule on this page.

A mod can change the UI (a standard 3.3.5a addon), the realm (mod-ale Lua on the AzerothCore 3.3.5a server), or both.

## The package

A mod is a folder, or a zip of one, with a `mod.json` at the top.

```
dalaran-dice/
  mod.json            required
  ui/DalaranDice/     a 3.3.5a addon: DalaranDice.toc, .lua, .xml   (kind "ui" or "both")
  realm/*.lua         mod-ale Lua                                    (kind "realm" or "both")
  assets/             your own or licensed files, with assets/CREDITS.txt
  tests/              optional fake-ALE tests (not installed)
  README.md, LICENSE  optional
```

Other files allowed at the top: `README.txt`, `LICENSE.txt`, `LICENSE.md`, `CHANGELOG.md`, `.gitignore`.

## mod.json

| Field | Required | Rule |
|---|---|---|
| `id` | yes | 3-32 characters: lowercase letters, digits and single dashes, starting with a letter, for example `dalaran-dice` |
| `name` | yes | up to 48 characters |
| `version` | yes | semver `MAJOR.MINOR.PATCH` |
| `author` | yes | text |
| `licence` | yes | an SPDX id or expression: `MIT`, `GPL-3.0-or-later`, `MIT OR CC-BY-4.0`, `LicenseRef-...` |
| `kind` | yes | `ui`, `realm` or `both`; must match the folders present |
| `wu` | yes | the lowest Leyline version the mod works with, for example `"1.0"` |
| `description` | yes | up to 300 characters |
| `category` | no | the Workshop shelf: one id from the list below. Left out, it follows `kind`: `ui` and `both` give `addons`, `realm` gives `realm-scripts`. Anything else is an error. |
| `permissions` | no | a list from the fixed vocabulary below |
| `screenshots` | no | `.png`, `.jpg` or `.webp` paths inside the package |
| `links` | no | `https://` URLs, or `{ "label": "...", "url": "https://..." }` |

An unknown licence id gets a warning, not an error. `LicenseRef-` ids are accepted.

## Categories

The one list of categories is `mods/categories.json`. `wu-mod.py check` checks `category` against it, and the Workshop reads the same file for its category grid and its pages at `/wrath/mods/c/<id>`. To add or rename a category, change that file only.

| Id | Name | What goes there |
|---|---|---|
| `addons` | Addons and UI | interfaces, unit frames, nameplates, meters, quest helpers, bag and chat mods, UI skins |
| `graphics` | Shaders and graphics | lighting, sky, water, post effects, colour grades, graphics presets for our engines |
| `sandbox` | Sandbox and game modes | kits such as Prop Hunt, hide and seek, races, murder mystery, tower defense, jump maps |
| `maps` | Custom maps | new zones, arenas, dungeons and housing plots |
| `builds` | Builds | saved Builder creations shared as codes |
| `encounters` | Boss fights and encounters | community bosses, encounter scripts, raid replays |
| `models` | Models and props | original creatures, mounts, props and buildings |
| `realm-scripts` | Realm scripts | server-side features such as QoL, events, economies, professions and companions |
| `presets` | Server presets | ready realm recipes such as a Dalaran hangout, duels-only, raid night, RP and hardcore |
| `audio` | Sounds and music | original ambience, music packs and UI sounds |
| `tools` | Tools | developer HUD plugins, map viewers, log analysers and OBS overlays |
| `conversions` | Total conversions | whole new games built from the categories above |
| `themes` | Launcher themes | theme packs for the Leyline launcher: colours, fonts and art (CSS and images only). A theme pack is a `theme.json` package, not a `mod.json` one: see [THEMES.md](https://github.com/orionopenwow/WrathUnleashed/blob/main/docs/THEMES.md) |

A category with no mods yet says so on the Workshop and links the modders' guide. It never shows made-up entries.

## Permissions

Permissions apply to realm code only. A realm mod may only use what it declares. Undeclared use is an error. Declared but unused is a warning. Players see this list on the Workshop, so keep it short.

| Permission | Covers |
|---|---|
| `commands` | `RegisterPlayerEvent(42, ...)` (dot commands) |
| `chat` | player chat events 18-22, server event 30 (addon messages), `OVMod.Send` and `OVMod.On`, `SendWorldMessage`, `:SendAddonMessage`, `:SendUnitSay`, `:SendUnitYell`, `:SendUnitEmote`, `:SendUnitWhisper`, `:Say`, `:Yell` |
| `gossip` | `RegisterCreatureGossipEvent`, `RegisterGameObjectGossipEvent`, `RegisterItemGossipEvent`, `RegisterPlayerGossipEvent` |
| `spawns` | `PerformIngameSpawn`, `:SpawnCreature`, `:SummonGameObject` |
| `events` | every other `Register*Event` (player, server, creature, gameobject, item, group, guild, BG, map, instance, spell, ticket) |
| `db` | `CharDBExecute`, `CharDBQuery`, `CharDBQueryAsync`, `WorldDBExecute`, `WorldDBQuery`, `WorldDBQueryAsync` |
| `timers` | `CreateLuaEvent`, `:RegisterEvent` |

`:SendBroadcastMessage` to a player needs no permission. Event ids must be numbers, or a `local NAME = 42` constant, so the checker can read them.

## Realm rules

1. **Events match permissions**, as in the table above.
2. **SQL only on your own tables.** Name them `mod_<your id with _ for ->_...`, for example `mod_dalaran_dice_rolls`. They live in the realm's characters or world database and are reached through the `db` calls. The SQL must be a string literal, or `string.format` of one, so the table name is visible. Not allowed: other database names (such as `acore_auth.x`), a second statement after `;`, `GRANT`, `LOAD DATA`, `INTO OUTFILE`, `SET GLOBAL`, `CREATE DATABASE` and `DROP DATABASE`. Create tables from Lua with `CREATE TABLE IF NOT EXISTS`. `.sql` files are not run.
3. **Forbidden:** `io.*`; `os.*` except `os.time`, `os.clock`, `os.date` and `os.difftime`; `loadstring`, `load`, `loadfile`, `dofile`, `require`, `module`; `debug.*`, `package.*`; `setfenv`, `getfenv`, `_G`; `string.dump`, `collectgarbage`; `HttpRequest`, `RunCommand`; `AuthDB*`; `RegisterPacketEvent`; `ReloadALE`, `ReloadEluna`; `Ban`, `Kick`. To talk to your addon, use the realm's `OVMod` global (from `ov_modapi.lua`) without `require`, and check `if OVMod then` first.
4. **`can` hooks return true or false explicitly.** Player events 48 CAN_INIT_TRADE, 49 CAN_SEND_MAIL, 50 CAN_JOIN_LFG, 55 CAN_GROUP_INVITE, 59 CAN_RESURRECT and 60 CAN_UPDATE_SKILL run with a default of false. A handler that returns nothing, `nil` or a non-boolean counts as false and blocks the action for every player. That is how the Dungeon Finder once broke on the live realm. The checker requires the handler to end with a `return`, and every `return` to be `true`, `false`, a `not ...` or a comparison.
5. **Globals** (a warning): all realm scripts share one Lua state, so use `local`. Names that start with your id in capitals (`DALARAN_DICE`) or in camel case (`DalaranDice`) are allowed.

## UI rules

- Each addon is `ui/<Name>/<Name>.toc` with `## Interface: 30300`.
- Every file the TOC lists must exist. Names are case-sensitive in the browser client.
- XML must be well formed. `<Script file>` and `<Include file>` must point to real files.
- Lua must parse as Lua 5.1.
- The addon runs in the client's addon sandbox with the stock 3.3.5a API.

## Assets

- Only files you made or may share.
- Every file in `assets/` is listed in `assets/CREDITS.txt`: name, author, licence and source, one per line.
- Game data from the stock client is never allowed anywhere in a package. That means `.mpq`, `.blp`, `.m2`, `.wmo`, `.adt` and `.dbc`, and also `.skin`, `.anim`, `.wdt`, `.wdl`, `.db2` and `.bls`. The checker looks at the extension and at the file's first bytes, so a renamed file is caught too.
- Use `.tga` for addon textures.
- Limits: 10 MB a file, 50 MB a package, 2000 files.

## Packing and install

`wu-mod.py pack <dir>` checks the mod, then writes `<id>-<version>.zip` and `<id>-<version>.zip.sha256`. Entries are sorted under `<id>/`, with fixed timestamps and modes, so the same files always give the same bytes.

A realm installs `realm/` under its mod-ale `lua_scripts/mods/<id>/`. The client installs each `ui/<Name>/` as an addon.

## The catalog

Approved mods live in `mods/catalog/<id>/`. The folder name is the mod id.

`wu-mod.py catalog` checks every mod, packs each one into `dist/`, and writes `mods/catalog.json`. If one mod fails, nothing is written. Per mod, the JSON holds: id, name, version, author, licence, kind, category (always set, with the default filled in), wu, description, permissions, screenshots, links, `addons` (the `ui/` folder names), `realm_files`, `zip`, `sha256` and `size`. The same files always give the same JSON.

Addon folder names must be unique across the catalog. They may not be `ForeverUI`, `WrathUnleashedUI` or `WUModCatalog`. With `--lua <dir>`, the tool also writes the `WUModCatalog` addon, which the in-game Workshop tab reads.

## The commands

```
python3 wu-mod.py check <dir|zip>      check a package (exit 1 on errors)
python3 wu-mod.py new <id> [--dir D]   make a new mod from the template
python3 wu-mod.py pack <dir> [-o D]    check, then write <id>-<version>.zip and .sha256
python3 wu-mod.py catalog              check and pack every mod in catalog/, write catalog.json
```

It needs Python 3.8 or newer and nothing else. It uses `luac5.1 -p` for Lua syntax when that is installed, and a small built-in parser otherwise.

## Walkthrough: the Pings mod

Pings is one of the three example mods in `mods/catalog/`. It has a realm half and an addon that talk to each other. Alt-click the world map, Alt-click in the world, or type `/ping`, and everyone in your group on the same map sees a marker, an on-screen line such as "Friend: Attack (29, 47)", and hears a sound.

### The files

```
pings/
  mod.json
  realm/pings.lua          checks each ping and passes it to the group
  ui/WUPings/WUPings.toc   the addon's table of contents
  ui/WUPings/WUPings.lua   sends pings and draws the ones it gets
  assets/preview.png       the Workshop screenshot
  assets/CREDITS.txt       "preview.png - Leyline - MIT - drawn for this mod"
  tests/test_pings.lua     fake-ALE tests for the realm half
  tests/test_ui.lua        tests for the addon
  README.md, LICENSE
```

### mod.json

```json
{
  "id": "pings",
  "name": "Pings",
  "version": "0.1.0",
  "author": "Leyline",
  "licence": "MIT",
  "kind": "both",
  "wu": "1.0",
  "category": "addons",
  "description": "Alt-click the world map, Alt-click in the world, or type /ping: ...",
  "permissions": ["chat", "timers"],
  "screenshots": ["assets/preview.png"]
}
```

- `kind` is `both` because there is a `realm/` and a `ui/` folder.
- `category` is `addons`, so it sits on the Addons and UI shelf of the Workshop.
- `chat` covers `OVMod.On` and `OVMod.Send`.
- `timers` covers one `CreateLuaEvent`: the realm's OVMod script may load after this folder, so the mod tries again a second later.

### The messages

The addon and the realm speak over the realm's OVMOD addon channel. A message is whispered to yourself, with the prefix `OVMOD`, in this shape:

```
<mod id> TAB <name> TAB <part>/<parts> TAB <data>
```

Pings uses three messages:

| Direction | Name | Data |
|---|---|---|
| client to realm | `map` | `<kind>,<area>,<floor>,<x>,<y>` |
| realm to client | `map` | `<kind>,<area>,<floor>,<x>,<y>,<sender name>` |
| realm to client | `denied` | `rate`, `nogroup` or `bad` |

`kind` is one of `look`, `attack`, `danger`, `assist` or `onmyway`. `area` is the world map area id, `floor` its dungeon level (0 outside), and `x` and `y` run from 0 to 1 with up to 4 decimals.

### The realm half

`realm/pings.lua`, in short:

1. It registers one handler: `OVMod.On("pings", "map", onMap)`.
2. `onMap` parses the data. Anything that doesn't match the exact shape gets `denied bad`.
3. No group: `denied nogroup`. More than 5 pings in 5 seconds: `denied rate`.
4. It sends the ping to each group member on the same map and instance, never back to the sender. The addon draws its own ping when it sends one.

It uses only `OVMod.On`, `OVMod.Send`, `CreateLuaEvent`, `os.time` and player and group methods. No database, no globals, nothing forbidden.

### The addon half

`ui/WUPings/WUPings.lua`:

- `/ping` pings where you stand. With an enemy targeted it calls Attack, with a friend Help here, otherwise Look here.
- `/ping attack`, `/ping danger`, `/ping assist` (or `help`), `/ping onmyway` (or `omw`) and `/ping look` pick the call.
- Alt-click on the world map pings that spot. A plain click still zooms.
- It only accepts pings that arrive as a whisper from yourself with the `OVMOD` prefix. That is how the realm answers, and other players can't fake it.
- Alone, you see your own ping and nothing is sent.

### Check, test, pack

From `mods/`:

```
python3 wu-mod.py check catalog/pings
cd catalog/pings
lua5.1 tests/test_pings.lua realm/pings.lua
lua5.1 tests/test_ui.lua ui/WUPings/WUPings.lua
cd ../..
python3 wu-mod.py pack catalog/pings -o dist
```

The tests stub the few mod-ale functions the script calls, load it, then call its handlers with fake players.

## Make your own

1. `python3 wu-mod.py new my-mod` copies the Dalaran Dice template into `my-mod/` with your id filled in.
2. Fill in `mod.json`, and pick a `category` from the list above.
3. Write the realm part, the addon, or both.
4. List every asset in `assets/CREDITS.txt`.
5. Run `check` until it passes, then `pack`.

`mods/README-modders.md` in the repo has the same steps with code samples. Then see [Publishing](publishing.md).

## What is planned

- A `wu-mod test` command that runs your mod on a local test realm.
- Signed packages.
- A review step. The Leyline Launcher will allow all mods, with no review queue and no code signing yet. The Wrath realm itself only runs mods the team has put in `mods/catalog/`. See [Publishing](publishing.md).
- The client Open Mod API plan describes `mod.toml` and signed `.ovpack` packages with client permissions (`ui`, `packets`, `data`, `render`, `wasm`, `compat`). When its loader lands, `mod.json` should map onto `mod.toml` field by field, so there is one format, not two.
