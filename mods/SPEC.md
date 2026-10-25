# WU mod package, format 0.1

A WrathUnleashed (WU) mod is a folder, or a zip of one, with a `mod.json` at the top. It can change the UI (a standard 3.3.5a addon), the realm (mod-ale Lua on the AzerothCore 3.3.5a server), or both. `wu-mod.py check` enforces every rule on this page.

```
dalaran-dice/
  mod.json            required
  ui/DalaranDice/     a 3.3.5a addon: DalaranDice.toc, .lua, .xml   (kind "ui" or "both")
  realm/*.lua         mod-ale Lua                                    (kind "realm" or "both")
  assets/             your own or licensed files, with assets/CREDITS.txt
  tests/              optional fake-ALE tests (not installed)
  README.md, LICENSE  optional
```

## mod.json

| Field | Required | Rule |
|---|---|---|
| `id` | yes | 3-32 chars, lowercase letters, digits and single dashes, starts with a letter: `dalaran-dice` |
| `name` | yes | up to 48 chars |
| `version` | yes | semver `MAJOR.MINOR.PATCH` |
| `author` | yes | text |
| `licence` | yes | SPDX id or expression: `MIT`, `GPL-3.0-or-later`, `MIT OR CC-BY-4.0`, `LicenseRef-…` |
| `kind` | yes | `ui`, `realm` or `both`; must match the folders present |
| `wu` | yes | lowest WU version the mod works with: `"1.0"` |
| `description` | yes | up to 300 chars |
| `permissions` | no | list from the fixed vocabulary below |
| `screenshots` | no | `.png/.jpg/.webp` paths inside the package |
| `links` | no | `https://` URLs, or `{ "label": "…", "url": "https://…" }` |

## Permissions (realm only)

A realm mod may only use what it declares. Undeclared use is an error; declared but unused is a warning.

| Permission | Covers |
|---|---|
| `commands` | `RegisterPlayerEvent(42, …)` (dot commands) |
| `chat` | player chat events 18-22, server event 30 (addon messages), `OVMod.Send/On`, `SendWorldMessage`, `:SendAddonMessage`, `:SendUnitSay/Yell/Emote/Whisper`, `:Say/:Yell` |
| `gossip` | `Register{Creature,GameObject,Item,Player}GossipEvent` |
| `spawns` | `PerformIngameSpawn`, `:SpawnCreature`, `:SummonGameObject` |
| `events` | every other `Register*Event` (player, server, creature, gameobject, item, group, guild, BG, map, instance, spell, ticket) |
| `db` | `CharDBExecute/Query/QueryAsync`, `WorldDBExecute/Query/QueryAsync` |
| `timers` | `CreateLuaEvent`, `:RegisterEvent` |

`:SendBroadcastMessage` to a player needs no permission. Event ids must be numbers (or a `local NAME = 42` constant) so the checker can read them.

## Realm rules

1. **Events match permissions** (table above).
2. **SQL only on your own tables**, named `mod_<id with _ for ->_*` (`mod_dalaran_dice_rolls`), in the realm's characters or world database, through the `db` calls. The SQL must be a string literal (or `string.format` of one) so the table is visible. No other database names (`acore_auth.x`), no second statement after `;`, no `GRANT`, `LOAD DATA`, `INTO OUTFILE`, `SET GLOBAL`, `CREATE/DROP DATABASE`. Create tables from Lua with `CREATE TABLE IF NOT EXISTS`; `.sql` files are not run.
3. **Forbidden:** `io.*`, `os.*` other than `os.time/clock/date/difftime`, `loadstring`, `load`, `loadfile`, `dofile`, `require`, `module`, `debug.*`, `package.*`, `setfenv/getfenv`, `_G`, `string.dump`, `collectgarbage`, `HttpRequest`, `RunCommand`, `AuthDB*`, `RegisterPacketEvent`, `ReloadALE/ReloadEluna`, `Ban`, `Kick`. To talk to your addon use the realm's `OVMod` global (from `ov_modapi.lua`) without `require`, and check `if OVMod then`.
4. **`can` hooks return true or false explicitly.** Player events 48 CAN_INIT_TRADE, 49 CAN_SEND_MAIL, 50 CAN_JOIN_LFG, 55 CAN_GROUP_INVITE, 59 CAN_RESURRECT and 60 CAN_UPDATE_SKILL run through mod-ale's `CallAllFunctionsBool` with a default of false. A handler that returns nothing, `nil` or a non-boolean counts as **false and blocks the action for every player**. That is how the Dungeon Finder broke on our live realm. The checker requires the handler to end with a `return`, and every `return` to be `true`, `false`, a `not …` or a comparison.
5. **Globals** (warning): all realm scripts share one Lua state, so use `local`. Names starting with `DALARAN_DICE`/`DalaranDice` (your id) are allowed.

## UI rules

- Each addon is `ui/<Name>/<Name>.toc` with `## Interface: 30300`. Every file the TOC lists must exist (names are case-sensitive in the browser client). XML must be well formed, and `<Script file>`/`<Include file>` must point to real files. Lua must parse as Lua 5.1.
- The addon runs in the client's addon sandbox with the stock 3.3.5a API.

## Assets

Only files you made or may redistribute. Every file in `assets/` is listed in `assets/CREDITS.txt` (name, author, licence, source). Blizzard game data is never allowed anywhere in a package: `.mpq .blp .m2 .wmo .adt .dbc` (and `.skin .anim .wdt .wdl .db2 .bls`), by extension or by file signature. Use `.tga` for addon textures. Limits: 10 MB a file, 50 MB a package, 2000 files.

## Packing and install

`wu-mod.py pack <dir>` checks the mod, then writes `<id>-<version>.zip` (sorted entries under `<id>/`, fixed timestamps and modes, so the same files always give the same bytes) and `<id>-<version>.zip.sha256`. A realm installs `realm/` under its mod-ale `lua_scripts/mods/<id>/`, and the client installs each `ui/<Name>/` as an addon.

## The catalog

Approved mods live in `mods/catalog/<id>/` (the folder name is the mod id). `wu-mod.py catalog` checks every one
(one failure and nothing is written), packs each into `dist/`, and writes `mods/catalog.json`: per mod its id, name,
version, author, licence, kind, wu, description, permissions, screenshots, links, `addons` (the `ui/` folder names),
`realm_files`, `zip`, `sha256` and `size`. The same files always give the same JSON. Addon folder names must be unique
across the catalog and may not be `ForeverUI`, `WrathUnleashedUI` or `WUModCatalog`. `--lua <dir>` also writes the
`WUModCatalog` addon (`WU_MOD_CATALOG = { ... }`), which the in-game Workshop tab reads.

The `mods` step (`mods/Put mods on Wrath.bat`, Autopilot step `mods`) puts the whole catalog live in one SSH
connection (`stream/server/mods-install.sh`): realm halves into `lua_scripts/mods/<id>/` with a live `reload ale`
(rolled back on a refused reload or a Lua error from `mods/`), addon halves into the streamed client
(`stream/server/mods-overlay.py`, beside Forever UI's overlay), and catalog.json, zips and screenshots to the site,
where players browse them at `/wrath/mods`.

## How this fits the larger plans

- This is the MVP from the community release plan ("WU mod package"). Later steps there: `wu-mod test` against a local test realm, human review for anything realm-side, and signed packages once approved.
- The client Open Mod API (`claude/open-mod-api-plan.md`) describes `mod.toml` and signed `.ovpack` packages with client permissions (`ui`, `packets`, `data`, `render`, `wasm`, `compat`). Those cover the client; the permissions here cover the realm. When the M1 loader lands, `mod.json` should map onto `mod.toml` field by field rather than become a second format.
- Realm-to-addon messages use the existing OVMOD channel (`ov_modapi.lua`), the server half of `Mod.Packet`.
