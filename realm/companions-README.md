# Companions (custom/lua_scripts/ov_companions.lua)

Bot party members for dungeons and 10-player raids. Players always see them called bots. The player guide is
`docs/COMPANIONS.md`. Players type:

| Command | What it does |
|---|---|
| `.companions` | help, the limits, who is with you |
| `.companions alts` | the other characters on the player's account (offline, not the current one) |
| `.companions save` | stores the alts with the player as the account's usual party (`mod_companions_usual`) |
| `.recruit party` | fills a 5-player group: 1 tank, 1 healer, damage, minus the roles already there |
| `.recruit raid` | fills a 10-player raid: 2 tanks, 3 healers, 5 damage, minus the roles already there; converts the party |
| `.recruit tank\|healer\|dps [n]` | recruits n (default 1) into your group at your level; `.recruit dps mage` picks the class |
| `.recruit alt <name>` | one of the player's own characters, with its own gear, spec and level |
| `.recruit usual` | re-adds the saved alts |
| `.buddy [class]` | one levelling buddy: your level, follows you, re-matched when you level up; `.buddy off` |
| `.dismiss [name\|all]` | sends bots home (alts too) |

Owner decisions (final): 10-player raids only (25 behind `OV_COMPANIONS_RAID25`, off); bots always pass on
loot, the player's own alts included.

## Where

Not in battlegrounds or arenas, not in combat, not while dead; group leader only. Inside a dungeon or raid
instance only while nobody in the group is in combat, so a dead or missing slot can be refilled between pulls.
`.recruit raid` is refused inside a 5-player dungeon (a raid group can't stay there) and in a Dungeon Finder
group.

Bringing a bot over: in the open world a bot on another map or more than 40 yards away is teleported to the
player. Inside an instance only a bot on the same map **and** instance id is moved; any other gets the
whisper `summon` (mod-playerbots' own SummonAction with its own checks).

## Roles

What a group already covers: our own bots by the role they were recruited for; everyone else (real players,
alts) by spec through mod-playerbots' `Player:IsTank(true)` / `IsHealer(true)` (talent tree, works for real
players), else damage. Tanks are filled first, then healers, then damage; spare slots go to damage.

## How it works

The script drives mod-playerbots and has no bot AI of its own. Everything runs as the player's own chat
commands (`Player:RunCommand`) and whispers to the bot (`Player:Whisper`):

- `.playerbots bot addclass <class>`: a character from the addclass account pool (`Playerbots.AddClassAccountPoolSize`,
  50 accounts x 10 classes) of the player's faction logs in. It is levelled and geared to the player when they
  are 4+ levels apart, and it joins the player's group. A 6th member makes the module convert a party to a
  raid by itself; `.recruit raid` converts first anyway (`Group:ConvertToRaid`).
- `.playerbots bot add <name>`: an alt (`Playerbots.AllowAccountBots = 1`). The script checks first, in the
  characters table by the player's account id, that the name is the player's own, offline, not the current
  character. Names are letters only, so they are safe in the command and the SQL.
- `.playerbots bot init=auto <name>`: matches the level exactly (addclass bots only).
- whispers to addclass bots: `talents spec <premade>` (prot/bear/blood, holy/resto, or a damage spec),
  `maintenance`, `autogear` (capped by `AutoGearQualityLimit = 3`). Alts get none of these.
- whispers to every bot: `ll normal`, then `follow` (and `summon` when needed, see above).
- `.playerbots bot remove <name>` dismisses one. mod-playerbots logs a player's bots out when the player logs out.

## Loot: bots always pass

The vote is made in mod-playerbots' `LootRollAction.cpp` (pinned e88cc40) and controlled by global keys, so
they cover every bot on the realm (companions, alts, and the Dungeon Finder's bots). Set in the profile:

| Key | Value | Effect |
|---|---|---|
| `AC_PLAYERBOTS_LOOT_NEED_ROLL_LEVEL` | 0 | every NEED vote becomes PASS |
| `AC_PLAYERBOTS_LOOT_GREED_ROLL_LEVEL` | 0 | every GREED vote becomes PASS |
| `AC_PLAYERBOTS_LOOT_ROLL_DISENCHANT` | 0 | no disenchant votes (they would be greed, then pass) |
| `AC_PLAYERBOTS_LOOT_ROLL_RECIPE` | 0 | recipes: pass |
| `AC_PLAYERBOTS_FREE_METHOD_LOOT` | 0 | under free-for-all bots don't loot at all (`LootAction::isUseful`) |

Under master loot and free-for-all the bots vote PASS on any roll regardless. Per bot, the script also
whispers `ll normal` on arrival: the bot's own loot list setting, which an alt may carry as `all` from an
earlier session. There is no per-bot "always pass" command in the pinned source: the keys above decide.

What can't be prevented: items below the group's loot threshold (grey and white by default) are not rolled;
they go round-robin and a bot loots its turn like any member. Free-for-all avoids it (bots never loot). Removing
the bot's `loot` strategy would only leave those items locked to the bot's turn, and the module refuses that
change on addclass bots for non-GM players anyway.

## Limits (realm/profiles/main.env)

| Key | Default | Meaning |
|---|---|---|
| `OV_COMPANIONS` | 1 | on/off |
| `OV_COMPANIONS_PER_PLAYER` | 4 | bots per player in a party (buddy and alts included; at most 4) |
| `OV_COMPANIONS_PER_PLAYER_RAID` | 9 | bots per player in a raid group |
| `OV_COMPANIONS_REALM_MAX` | 60 | bots on the realm at once |
| `OV_COMPANIONS_GROUP_MAX` | 10 | the largest group `.recruit` fills (5 = no raids; up to 25 only with RAID25) |
| `OV_COMPANIONS_RAID25` | 0 | 1 lets `.recruit raid 25` fill 25 (also needs GROUP_MAX 25, PER_PLAYER_RAID 24, MAX_ADDED_BOTS 24) |
| `OV_COMPANIONS_COOLDOWN` | 30 | seconds between two `.recruit` / `.buddy` (a whole fill counts once) |
| `OV_COMPANIONS_BUDDY` | 1 | `.buddy` on/off |
| `AC_PLAYERBOTS_MAX_ADDED_BOTS` | 9 | mod-playerbots' own hard cap per player (module default 40): you + 9 = 10 |
| `AC_PLAYERBOTS_ALLOW_GUILD_BOTS` | 0 | the raw `.playerbots bot add` can't take a guildmate's offline character |

The script's defaults match these values, so a live `reload ale` without the profile behaves the same. Any
change to the profile needs the world server recreated. serverpass.sh does that with a 5-minute warning.

## Database

`mod_companions_usual` in the characters database (`account, slot, guid, name, saved_at`, primary key
`account, slot`), made by the script with `CREATE TABLE IF NOT EXISTS`. `.recruit usual` joins it to
`characters` on guid **and** account, so a character moved to another account drops out.

## What the build needs

The custom image (`Build custom realm.bat`, `custom/sources.lock`) already has all of it. The stock image
(`Use stock realm.bat`) has none of it, so every command there answers "Bots are coming soon":

1. The mod-playerbots core fork (`mod-playerbots/azerothcore-wotlk`, branch Playerbot), not stock AzerothCore.
2. The `mod-playerbots` module and its `acore_playerbots` database (`AC_PLAYERBOTS_DATABASE_INFO`).
3. mod-ale built against it, so `MOD_PLAYERBOTS` is defined. That gives `Player:IsPlayerbot`, `IsAddclassBot`,
   `IsTank`, `IsHealer` and `RunCommand`. The script checks for those methods.
4. `Playerbots.AddClassCommand = 1` (module default) so players, not only GMs, can use addclass, and
   `Playerbots.AllowAccountBots = 1` (module default) for alts.
5. Addclass accounts created on first start (`AddClassAccountPoolSize`, default 50). A recruit of a class
   with no free character there expires with "didn't arrive".
6. `Playerbots.ApplyInstanceStrategies = 1` (module default): raid and dungeon tactics switch on by themselves
   inside the instances listed in `docs/COMPANIONS.md` (`src/Ai/Raid`, `src/Ai/Dungeon`).
7. Optional: pathing data (`3-extract-pathing.bat`, `OV_PATHING=1`), so bots walk properly.

## Tests

`lua5.1 stream/tests/test_ov_companions.lua realm/custom/lua_scripts/ov_companions.lua` (from the repo root)
runs the script against a fake mod-ale, mod-playerbots and characters database: composition math, caps,
cooldown, the instance rules, alts (own account only), save/usual, the loot keys in the profile and
serverpass, and that players never see a brand name or the word "companion".
