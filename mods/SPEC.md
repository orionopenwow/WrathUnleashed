# Leyline mod package, format 0.1

A Leyline mod is a folder, or a zip of one, with a `mod.json` at the top. It can change the UI (a standard 3.3.5a addon), the realm (mod-ale Lua on the AzerothCore 3.3.5a server), or both. `wu-mod.py check` enforces every rule on this page.

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
| `wu` | yes | lowest Leyline version the mod works with: `"1.0"` |
| `description` | yes | up to 300 chars |
| `category` | no | the Workshop shelf, one id from `categories.json` (below). Default from `kind`: `ui` and `both` give `addons`, `realm` gives `realm-scripts`. Anything else is an error |
| `permissions` | no | list from the fixed vocabulary below |
| `screenshots` | no | `.png/.jpg/.webp` paths inside the package |
| `links` | no | `https://` URLs, or `{ "label": "…", "url": "https://…" }` |

## Categories

The one list is `mods/categories.json` (id, name, one line, icon name, in this order, plus `kind_defaults`).
`wu-mod.py` checks `category` against it, and `stream/workshop.py` reads the same file to draw the Workshop's
category grid and the pages `/wrath/mods/c/<id>`. To add or rename a category, change that file only.
The `mods` step sends it in the kit beside wu-mod.py and publishes it next to catalog.json in `$WU/portal/mods`
(the portal's `/app/mods`); in a checkout workshop.py falls back to `../mods/categories.json`.

| Id | Name | What goes there |
|---|---|---|
| `addons` | Addons and UI | interfaces, unit frames, nameplates, meters, quest helpers, bag and chat mods, UI skins |
| `graphics` | Shaders and graphics | lighting, sky, water, post effects, colour grades, graphics presets for our engines |
| `sandbox` | Sandbox and game modes | Garry's Mod-style kits such as Prop Hunt, hide and seek, races, murder mystery, tower defense, jump maps |
| `maps` | Custom maps | new zones, arenas, dungeons and housing plots |
| `builds` | Builds | saved Builder creations shared as codes |
| `encounters` | Boss fights and encounters | community bosses, encounter scripts, raid replays |
| `models` | Models and props | original creatures, mounts, props and buildings |
| `realm-scripts` | Realm scripts | server-side features such as QoL, events, economies, professions and companions |
| `presets` | Server presets | ready realm recipes such as a Dalaran hangout, duels-only, raid night, RP and hardcore |
| `audio` | Sounds and music | original ambience, music packs and UI sounds |
| `tools` | Tools | developer HUD plugins, map viewers, log analysers and OBS overlays |
| `conversions` | Total conversions | whole new games built from the categories above |
| `themes` | Launcher themes | Leyline launcher theme packs (`theme.json` + CSS + images, see `docs/THEMES.md`); not for `mod.json` packages |

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
version, author, licence, kind, category (always set, the default filled in), wu, description, permissions, screenshots, links, `addons` (the `ui/` folder names),
`realm_files`, `zip`, `sha256` and `size`. The same files always give the same JSON. Addon folder names must be unique
across the catalog and may not be `ForeverUI`, `WrathUnleashedUI` or `WUModCatalog`. `--lua <dir>` also writes the
`WUModCatalog` addon (`WU_MOD_CATALOG = { ... }`), which the in-game Workshop tab reads.

The `mods` step (`mods/Put mods on Wrath.bat`, Autopilot step `mods`) puts the whole catalog live in one SSH
connection (`stream/server/mods-install.sh`): realm halves into `lua_scripts/mods/<id>/` with a live `reload ale`
(rolled back on a refused reload or a Lua error from `mods/`), addon halves into the streamed client
(`stream/server/mods-overlay.py`, beside Forever UI's overlay), and catalog.json, categories.json (from the kit), zips and screenshots to the site,
where players browse them at `/wrath/mods`.

## How this fits the larger plans

- This is the MVP from the community release plan ("Leyline mod package"). Later steps there: `wu-mod test` against a local test realm, human review for anything realm-side, and signed packages once approved.
- The client Open Mod API (`claude/open-mod-api-plan.md`) describes `mod.toml` and signed `.ovpack` packages with client permissions (`ui`, `packets`, `data`, `render`, `wasm`, `compat`). Those cover the client; the permissions here cover the realm. When the M1 loader lands, `mod.json` should map onto `mod.toml` field by field rather than become a second format.
- Realm-to-addon messages use the existing OVMOD channel (`ov_modapi.lua`), the server half of `Mod.Packet`.

## Upstream addons (the addon marketplace)

Third-party addons for the 3.3.5a client that the Workshop lists and the Leyline launcher installs **straight from the
author's own repo** (all.json `source: "upstream"`, id `up:<slug>`). They are not mod packages and need no `mod.json`.
We never host them: the launcher downloads the author's release asset, or the commit archive pinned to a 40-hex commit.
A copy on our site (`install.from: "mirror"`) is allowed only when `mirror_allowed` is true: an open licence **and** no
`.blp` files. Every entry is curated by `tools/addon-curate/curate.py` and only published once a person has reviewed it.

**What is never listed** (owner, 2026-10-31): paid or cracked products; anything with native code, injection or memory
editing (`.dll`, `.asi`, `.exe`, or that needs a patched client); UIs that bundle stock game art by their own TOC
(link-out only, or left out); re-upload collections of other people's addons (never an install source). Full interface
replacements (ElvUI and the like) are allowed with `replaces_ui: true`, which the launcher shows as "Replaces your whole
interface; may conflict with the Leyline UI". Display names never carry the game's brand words; the launcher also cleans
TOC titles it shows in My Mods.

**The rules** are one file, `launcher/src-tauri/src/upstream-rules.json`, built into the launcher (`upstream.rs`) and read
by curate.py; `upstream-cases.json` beside it is run by both test suites so they cannot disagree.

| Rule | Upstream addons (curated) | Mod packages |
|---|---|---|
| Game data `.mpq .m2 .wmo .adt .dbc .skin .anim .wdt .wdl .db2 .bls`, native code `.dll .asi .exe .so .dylib`, archives `.zip .rar .7z` (by extension or first bytes), anywhere in the download | refused, whole entry | refused |
| `.blp` textures | only when the entry says `blp: "author-art"` (the author's own art, from upstream only, never mirrored; names like stock interface art are flagged for the reviewer) | refused |
| Folder names | letters, digits, `_ . + ! -`, may start with `!` or `_` (`!BugGrabber`, `xCT+`); not `Blizzard_*` or the realm's own | starts with a letter |
| `## Interface:` | holds 30300, alone or in a list (`30300, 11508`) | exactly 30300 |
| Dev files (`.pkgmeta`, `.luacheckrc`, `.editorconfig`, `.github/`, `.yml`, `README`, `LICENSE`, screenshots, scripts) | skipped, never installed | error |
| Repo layout | addon folders up to two levels deep, or the repo **is** the addon (its `.toc` at the top: the folder is named after the `.toc` for this client, `Questie-335`, `pfQuest-wotlk`) | `ui/<Name>/` |
| Size | 32 MB a file, 256 MB, 12000 files | 10 MB, 50 MB, 2000 |
| Updates | when the catalog's `install.rev` differs from the installed one (versions such as `r736` or `3x05` are not compared) | semver |

**Checks at install** (launcher, `upstream.rs`): `install.url` must be the entry's own `repo` in one of these shapes:
`https://github.com/<o>/<r>/releases/download/<tag>/<file>.zip`, `https://github.com/<o>/<r>/archive/<commit>.zip`,
`https://gitlab.com/<o>/<r>/-/archive/<commit>/<r>-<commit>.zip`, `https://codeberg.org/<o>/<r>/archive/<commit>.zip`
(or our own `/wrath/mods/` for a mirror). Redirects are followed by hand, https only, to `objects.githubusercontent.com`,
`release-assets.githubusercontent.com`, `codeload.github.com`, `gitlab.com` or `codeberg.org`. Then the zip's sha256 when
the entry has one (release assets and mirrors; GitHub's commit archives are not byte-stable), and always every file:
each installed file's sha256 against `install.files`, or the digest of the whole set (`install.files_digest`: sha256 of
the sorted `<path>\0<sha256>\n` lines). Only then is anything moved into the client, through the mod manager, as
`up:<slug>` in `Leyline/mods.json`, so Remove, turn off and on, and keeping the player's edited files work as for any mod.
An entry that is not reviewed, claims native code, or whose install block does not check out is shown as a plain link.

### The entry (`mods/upstream.json`, written by curate.py)

| Field | Meaning |
|---|---|
| `id`, `source` | `up:<slug>`, `"upstream"` |
| `name`, `display_name` | the main addon folder; the clean name we show |
| `description` | our own words, one or two sentences |
| `category`, `tags` | `addons`; sub-categories: `full-ui unit-frames raid-frames action-bars nameplates meters boss-mods raid-tools auras cooldowns combat-text quests maps minimap bags auction gear tooltips chat social class professions pvp skins libraries quality-of-life` |
| `builds` | `["3.3.5a"]` |
| `author`, `author_url`, `repo` | the repo owner and the canonical repo link (the credit and the Source link) |
| `licence`, `licence_source` | SPDX-style id from the repo's licence file (or the TOC's `X-License`), `""` when none; the file it came from |
| `mirror_allowed` | open licence and no `.blp`: only then may we host a copy |
| `version` | the main addon's TOC version (or the short commit) |
| `install` | `from` (`release-asset`, `commit-archive`, `mirror`), `url`, `mirror_url?`, `rev` (tag or 40-hex commit), `sha256?` (byte-stable downloads only), `size`, `file_count`, `strip_prefix` (the archive's top folder), `folders` (archive folder → addon folder; `""` = the repo is the addon), `skip` (what curation left out, informational), `files` (`<Addon>/<path>` → sha256), `files_digest` |
| `addons`, `toc` | the addon folders it installs, and each one's Interface, title, version, author |
| `requires`, `conflicts` | other `up:` ids it needs (from the TOCs' `## Dependencies`, plus the seed's), and ones installing the same folders |
| `replaces_ui`, `native` | a whole-interface replacement; always `false` |
| `blp`, `blp_files` | `none` or `author-art`, and which files |
| `flags`, `notes` | for the reviewer: TOC files that are missing, textures named like stock art, brand words, the seed's notes |
| `review` | `{by, at, notes}`: empty `by` is pending; only reviewed entries are published |
| `compat` | `{realm: "Wrath Unleashed", status: works/untested/broken, checked_at}` |
| `pending_update` | a newer upstream rev of an approved entry, with the file diff; the approved install stays live until it is approved |

all.json carries the reviewed entries without `files` and `skip` (the digest stands for the list); see `all-json.md`.
`failed` (with the reason) and `excluded` (with the owner's rule) list what is not in.

### Curating and reviewing

```
python3 -I tools/addon-curate/curate.py run [--only ID ...]      # resolve, download, check, hash: new entries are pending
python3 -I tools/addon-curate/curate.py list                     # id, status, licence, files, flags; and the failures
python3 -I tools/addon-curate/curate.py approve up:skada --by Owner [--notes "..."] [--works]
python3 -I tools/addon-curate/curate.py unapprove up:skada
```

`approve` (and `run`) write `stream/upstream-addons.json`, the reviewed entries in the all.json shape, which
`stream/upstream_addons.py` merges into `/wrath/mods/all.json` (checked again there). The seeds are
`tools/addon-curate/seeds-addons.json` (repo, our name and words, tags, `replaces_ui`, `requires`, or `exclude` with the
reason). For the Admin Console, curate.py has `pending_entries(path)` and `approve_entry(path, id, by, notes, works)`.
