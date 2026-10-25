# WrathUnleashed quality-of-life Lua

Two parts for the WrathUnleashed 3.3.5a (build 12340) AzerothCore realm:

| File | Runs in | What it is |
|---|---|---|
| `server/ov_qol.lua` | worldserver, mod-ale (Eluna-compatible) | Login welcome, `.qol` help, auto-learn class spells, duel reset, free repair command, Brawl hub teleports, bot help text |
| `addon/OVQoL/OVQoL.toc` | client (3.3.5a and the browser client) | `## Interface: 30300`, `## SavedVariables: OVQoLDB` |
| `addon/OVQoL/OVQoL.lua` | client | Sell grays, auto-repair (guild bank first), coordinates under the minimap, auto-loot toggle, quest auto-accept/turn-in, hide gryphons, `/qol` |

## Install

- **Server:** copy `server/ov_qol.lua` to `realm\custom\lua_scripts\`, beside `ov_services.lua`, `ov_brawl.lua` and `ov_armory.lua`. Then restart the worldserver, or use mod-ale's reload command if your build has one.
- **Addon:** copy the `addon/OVQoL` folder to `<WoW install>\Interface\AddOns\OVQoL\`. For the browser client, put it wherever that client loads `Interface\AddOns` from.

## Server script: `ov_qol.lua`

Chat commands:

| Command | Does |
|---|---|
| `.qol` | Lists which features are on for this realm, plus the commands |
| `.qol learn` | Learns every class spell you qualify for now. Only when auto-learn is on |
| `.qol repair` | Repairs all gear for free, anywhere, out of combat (5 s cooldown). Only when free repair is on |
| `.qol hub <place>`, `.hub <place>` | Teleports you to `dalaran`, `gurubashi`, `maul`, `circle` or `amphitheater` |
| `.tele <place>` | Same as `.hub`, for **non-GM players only** and only for those five names. A GM's `.tele` is never intercepted |
| `.qol bots` | Short mod-playerbots how-to: `.playerbots bot add/addclass/remove/list`, plus the whisper commands follow, stay, attack, summon, release, revive and autogear |

Events:

| Event | Behaviour |
|---|---|
| Login (3) | Welcome message naming the realm, `.ov`, `.armory` and `.qol` |
| Level change (13) | Auto-learn class spells |
| First login (30) | Auto-learn class spells. This covers characters that start at 80 in Dalaran, which never fire a level change |
| Duel end (11) | Both players get full health and mana/energy, rage and runic power go back to 0, and `ResetAllCooldowns()` runs |
| Command (42) | Handles `.qol`, `.hub` and the player `.tele` shortcuts. Returns `false` to consume the command, the same as `ov_services.lua` |

No gossip menu is used, so there's no clash with menu 61000 in `ov_services.lua`. The script doesn't use the `OVARM` addon prefix either.

### Env-var gates

`1` turns a feature on, `0` turns it off, and unset gives the default. The vars are read at use time.

| Var | Default | Gates |
|---|---|---|
| `OV_REALM_NAME` | `WrathUnleashed` | Name in the welcome message |
| `OV_QOL_WELCOME` | on | Login welcome |
| `OV_AUTOLEARN` | on if `OV_BRAWL=1`, else off | Auto-learn on level up, first login and `.qol learn` |
| `OV_DUEL_RESET` | on | Duel-end restore |
| `OV_QOL_HUB` | on if `OV_BRAWL=1`, else off | `.qol hub`, `.hub`, player `.tele` |
| `OV_FREE_REPAIR` | on if `OV_BRAWL=1`, else off | `.qol repair` |
| `OV_QOL_BOTHELP` | on | `.qol bots` text |
| `OV_BRAWL` | (set by the brawl profile) | Flips the Brawl defaults above |

### How auto-learn works

1. On first use, it checks `information_schema` to find which trainer schema the world DB has:
   - **New (AzerothCore master):** `trainer` with `Type = 0` (class trainer) and `Requirement = <class id>`, joined to `trainer_spell`. This path is used whenever those tables exist.
   - **Legacy:** `npc_trainer` on creatures with `creature_template.trainer_type = 0 AND trainer_class = <class>`, plus one level of negative-`SpellID` template references. `ReqSpell` is used if the column exists.
   - **Neither:** auto-learn is disabled and the worldserver log says so (`[ov_qol] auto-learn trainer schema: none`).
2. Results are cached per class in Lua memory, roughly 100 to 300 rows per class.
3. A spell is taught only if:
   - `ReqLevel` is at or below the player's level;
   - the player already knows every `ReqAbility1..3` spell;
   - any `ReqSkillLine`/`ReqSkillRank` requirement is met;
   - it isn't on the other faction's list.

   Requiring the `ReqAbility` spells is what keeps talent-dependent ranks out: rank 2 of Mortal Strike needs the talent itself. It is also why ranks are learned in order. Up to 4 passes run, so a rank learned in one pass can unlock the next.
4. Faction-only spells are filtered with a fixed list checked against the AzerothCore `trainer_spell` data: mage city teleports and portals, Heroism/Bloodlust, Seal of Vengeance/Corruption, and the paladin mounts. AzerothCore's real trainer filters these with `IsSpellFitByClassAndRace`, which Lua can't reach.
5. "Teacher" entries are skipped and left to the trainer. These are spells with a `LEARN_SPELL` effect, such as class mounts, which a real trainer *casts* rather than learns. They're detected with mod-ale's `GetSpellInfo(id):HasEffect(36)`, with two known paladin ids hard-coded in case that is missing. The player is told how many were skipped.
6. All SQL values are integers forced through `%d`, or names from fixed lists that are also stripped and quote-escaped.

### Hub teleports

The script looks up each name in `game_tele` at runtime and caches the result: `Dalaran`, `GurubashiArena`, `TheMaul`, `CircleOfBloodArena`, `AmphitheaterOfAnguish`. If a row is missing, it falls back to the same coordinates copied from AzerothCore master `game_tele.sql`. A teleport is refused if the player is:

- in combat;
- dead;
- in a battleground or arena;
- in a dungeon or raid;
- within 10 seconds of their last hub teleport.

All five places are open-world. Instanced arena maps (Nagrand, Blade's Edge, Lordaeron, Dalaran Sewers) were left out on purpose, because teleporting into them outside a queue doesn't work.

### Left to worldserver.conf (not doable safely from Lua)

| Want | Setting |
|---|---|
| Free repairs at vendors | `Rate.RepairCost = 0`. Eluna has no hook on the vendor repair. `.qol repair` is the Lua alternative |
| Instant mail | `MailDeliveryDelay = 0`. There's no Eluna hook for the mail delay |
| An exact duel reset | `ResetDuelCooldowns = 1` and `ResetDuelHealthMana = 1`. These restore the pre-duel state. If you enable them, set `OV_DUEL_RESET=0` |

## Addon: OVQoL

`/qol` shows the status. `/qol <name>` toggles one feature, and `/qol reset` restores the defaults. Settings are saved per account in `OVQoLDB`.

| Name | Default | Behaviour |
|---|---|---|
| `sell` | on | When a merchant opens, sells every quality-0 item that has a vendor price (from `GetItemInfo`: quality is the 3rd return, sell price the 11th). One item every 0.2 s. It stops the moment the merchant closes, so `UseContainerItem` never runs without a merchant open |
| `repair` | on | `CanMerchantRepair()` → `GetRepairAllCost()` → `RepairAllItems()` |
| `guild` | on | Tries `RepairAllItems(1)` first when `IsInGuild()` and `CanGuildBankRepair()` are true and the withdraw limit and bank balance look sufficient. If no `UPDATE_INVENTORY_DURABILITY` arrives within 1.5 s and the bill is unchanged, it pays with your own gold |
| `coords` | on | `x, y` from `GetPlayerMapPosition("player")`, shown under the minimap at 5 updates a second. Shows `--, --` in instances. Calls `SetMapToCurrentZone()` on zone change, but only while the world map is closed |
| `loot` | off | Sets the `autoLootDefault` CVar to 1 or 0. It only touches the CVar when you toggle it |
| `quests` | off | Accepts quests on `QUEST_DETAIL`. Completes them on `QUEST_PROGRESS` when `IsQuestCompletable()`. Takes the reward on `QUEST_COMPLETE` when there are 0 or 1 choices; with more than one, you pick. On gossip it hands in completed quests first, then opens the first available quest. **Hold Shift** to do it all manually |
| `gryphons` | off | Hides `MainMenuBarLeftEndCap` and `MainMenuBarRightEndCap`. In combat it waits for `PLAYER_REGEN_ENABLED` |

Safety:

- No Blizzard function is hooked or replaced, and no protected action is called.
- Every API is checked before use (`if FunctionName then`).
- Every event handler runs in `pcall`. A feature that errors turns itself off for the session and prints one message.
- The "Release Spirit" popup is not touched on purpose. Hiding it can leave a player with no release button, and auto-releasing wastes soulstones, Reincarnation and battle resurrections.

## Known limitations

- **Auto-learn only teaches what class trainers teach:**
  - Quest-taught spells aren't granted: shaman totems, warlock demons, druid forms and the like. Neither are later ranks that depend on them, until the player has the base spell.
  - Teacher spells (class mounts) still need a trainer visit.
  - The faction filter is a hand-made list, not the core's race/class mask check. If your DB adds custom race-locked class spells, add them to `FACTION_ONLY`.
- **Legacy `npc_trainer` path:** this follows only one level of negative `SpellID` references, and needs `creature_template.trainer_class`.
- **Duel reset and cooldowns:** `ResetAllCooldowns()` clears **all** cooldowns, including item cooldowns like the Hearthstone and long ones like Bloodlust/Heroism. The Exhaustion/Sated debuff stays. The core settings above avoid this.
- **Lingering effects after a duel:** DoTs that tick after the duel ends aren't undone.
- **`.tele` interception:** this relies on mod-ale's command hook firing before the core's permission check, which is how `.ov` already works. GM rank 0 players are the only ones intercepted.
- **Quest turn-in from gossip:** this depends on 3.3's `GetGossipActiveQuests()` returning 4 values per quest (title, level, trivial, complete). If the count isn't a multiple of 4, turn-ins from gossip are skipped. On the old-style greeting frame, an active quest is opened only when it's the only one.
- **Coordinates:** these read 0,0 inside instances and on maps with no zone coordinates.
