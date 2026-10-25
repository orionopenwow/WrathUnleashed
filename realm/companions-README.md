# Companions (custom/lua_scripts/ov_companions.lua)

Bot party members for solo players and small groups. Players type:

| Command | What it does |
|---|---|
| `.companions` | help, the limits, who is with you |
| `.recruit tank\|healer\|dps [n]` | recruits n (default 1) into your group at your level; `.recruit dps mage` picks the class |
| `.buddy [class]` | one levelling buddy: your level, follows you, re-matched when you level up; `.buddy off` |
| `.dismiss [name\|all]` | sends companions home |

Open world only (not in combat, dead, or inside a dungeon, raid, battleground or arena), group leader only.

## How it works

The script drives mod-playerbots and has no bot AI of its own. Everything runs as the player's own chat
commands (`Player:RunCommand`) and whispers to the bot (`Player:Whisper`):

- `.playerbots bot addclass <class>`: a character from the addclass account pool (`Playerbots.AddClassAccountPoolSize`,
  50 accounts x 10 classes) of the player's faction logs in. It is levelled and geared to the player when they
  are 4+ levels apart, and it joins the player's group.
- `.playerbots bot init=auto <name>`: matches the level exactly. The buddy gets it again on each level up.
- whisper `talents spec <premade>` sets the role's spec (prot/bear/blood, holy/resto, or a damage spec), then `follow`.
- `.playerbots bot remove <name>` dismisses one.

## Limits (realm/profiles/main.env)

| Key | Default | Meaning |
|---|---|---|
| `OV_COMPANIONS` | 1 | on/off |
| `OV_COMPANIONS_PER_PLAYER` | 4 | companions per player, the buddy included |
| `OV_COMPANIONS_REALM_MAX` | 40 | companions on the realm at once |
| `OV_COMPANIONS_GROUP_MAX` | 5 | group size `.recruit` fills up to (5 = party; up to 40 for raids) |
| `OV_COMPANIONS_COOLDOWN` | 30 | seconds between two `.recruit` / `.buddy` |
| `OV_COMPANIONS_BUDDY` | 1 | `.buddy` on/off |
| `AC_PLAYERBOTS_MAX_ADDED_BOTS` | 4 | mod-playerbots' own hard cap per player (module default 40) |

The script's defaults match these values, so a live `reload ale` without the profile behaves the same. Any
change to the profile needs the world server recreated. serverpass.sh does that with a 5-minute warning.

## What the build needs

The custom image (`Build custom realm.bat`, `custom/sources.lock`) already has all of it. The stock image
(`Use stock realm.bat`) has none of it, so every command there answers "Companions are coming soon":

1. The mod-playerbots core fork (`mod-playerbots/azerothcore-wotlk`, branch Playerbot), not stock AzerothCore.
2. The `mod-playerbots` module and its `acore_playerbots` database (`AC_PLAYERBOTS_DATABASE_INFO`).
3. mod-ale built against it, so `MOD_PLAYERBOTS` is defined. That gives `Player:IsPlayerbot`, `IsAddclassBot`
   and `RunCommand`. The script checks for those methods.
4. `Playerbots.AddClassCommand = 1` (module default) so players, not only GMs, can use addclass.
5. Addclass accounts created on first start (`AddClassAccountPoolSize`, default 50). A recruit of a class
   with no free character there expires with "didn't arrive".
6. Optional: pathing data (`3-extract-pathing.bat`, `OV_PATHING=1`), so companions walk properly.

## Tests

`lua5.1 stream/tests/test_ov_companions.lua realm/custom/lua_scripts/ov_companions.lua` runs the script
against a fake mod-ale and mod-playerbots. The realm-scripts workflow runs it too.
