# Local 3.3.5a test realm (AzerothCore) for the browser client

Private, local-only (every port binds to 127.0.0.1). Needs Docker Desktop.

1. `1-extract.bat`: once. It extracts dbc + maps from your own install (`Downloads\World of Warcraft 3.3.5a`)
   into a Docker volume and takes a few minutes. vmaps/mmaps are skipped, so line-of-sight and pathing
   are off until you run `3-extract-pathing.bat` (optional, hours).
2. `2-start-realm.bat`: database + auth (3724) + world (8085). The first start imports the
   databases (several minutes).
3. `add-account.bat NAME PASSWORD`: a login with GM level 3.
4. `..\play\Play 3.3.5a in browser.bat`, then log in. The page's default realmlist is
   `localhost`, and the local host relays /ws/3724 and /ws/8085 to these ports.

`stop-realm.bat` stops it. Images: acore/ac-wotlk-* (AzerothCore, AGPL) and mysql:8.4.

## Custom realm (modules)

`Build custom realm.bat` builds AzerothCore's mod-playerbots fork with the modules below and
switches the realm to it (first run about an hour; characters and accounts are kept).
`Use stock realm.bat` goes back. Everything is pinned in `custom\sources.lock`.

| Module | What players get |
|---|---|
| mod-playerbots | Bots that fill groups, raids, battlegrounds and the world (60 by default). Quiet: no broadcasts, no world chat. |
| mod-individual-progression | Vanilla, then TBC, then Wrath, per character (progression profile) |
| mod-ale | Lua scripting; `custom\lua_scripts\ov_services.lua` adds `.ov`: free faction, race and appearance changes, and a boost to 70 on the casual profile |
| mod-transmog | Transmogrification with a collection |
| mod-autobalance | Dungeons and raids scale to the group's size |
| mod-ah-bot-plus | A stocked auction house (`set-ahbot.bat NAME` picks its character) |
| mod-aoe-loot | Loot every nearby body at once |
| mod-solo-lfg | Queue for the Dungeon Finder alone |
| mod-challenge-modes | Hardcore, semi-hardcore, self-crafted, slow-XP and other runs with rewards |
| mod-guildhouse | A guild house per guild |
| mod-dungeon-master | Random dungeon runs from an NPC |
| mod-arac | All races, all classes (client needs Patch-A.MPQ: `..\addons\install-gm-addons.bat`) |
| mod-1v1-arena | Rated 1v1 arena |
| mod-mythic-plus | Keystones with a timer, affixes and rewards |
| mod-multibot-bridge | Server side of the MultiBot addon (bot control panel) |
| mod-questie-bridge | Live server data for the Questie-335 addon |

The Dungeon Finder, raid browser, separate 10/25 lockouts and 2v2 arenas are AzerothCore's own
and stay on.

**Profiles** (`Switch profile.bat NAME`, settings in `profiles\*.env`):
- `brawl` (default): level 80 starts in Dalaran with everything unlocked (`Make it Brawl.bat`).
- `progression`: blizzlike 1x from level 1, content unlocks per character.
- `casual`: 3x XP from level 1, every expansion open, free `.ov` boost to 70.

Module settings are in `modules.env` (AzerothCore reads `AC_*` variables as overrides of the
matching `.conf` key). Edit, then `docker compose up -d ac-worldserver`.

Notes:
- The build needs internet (GitHub, lua.org) and a few GB of RAM for Docker. If the compile is
  killed, give Docker Desktop more memory (Settings > Resources) and run it again.
- Bots walk much better with pathing data: run `3-extract-pathing.bat` once.
- mod-autobalance and mod-mythic-plus both scale dungeons; keystone runs stack on top of
  autobalance's group-size scaling.
- mod-individual-progression changes world data for every profile; with it switched off
  (brawl, casual) Wrath content plays as normal.
