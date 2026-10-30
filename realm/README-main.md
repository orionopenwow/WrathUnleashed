# WrathUnleashed MAIN realm profile

A normal Wrath game from level 1 (1x XP, gold costs, vendors, trainers, professions, the races' starting zones),
and on its first login every new character chooses once:

* **Begin your adventure at level 1** (a Death Knight: carry on with the Ebon Hold story at 55), or
* **Boost to level 80**: pick a spec, then up to two primary professions, and the character gets level 80, every
  class spell a trainer teaches up to 80 plus the class-quest spells, all its weapon skills at 400, riding up to
  Artisan with Cold Weather Flying, Swift Zhevra and Albino Drake, dual spec, the chosen professions (and any it
  already had) plus Cooking, First Aid and Fishing at 450 with every trainer recipe, four Frostweave Bags equipped,
  the spec's **PvE kit** (Heroes' T7 10-man set + ilvl ~200 off-pieces) and **PvP kit** (Deadly Gladiator's), class
  reagents, and a teleport to Dalaran with the hearthstone set there. What doesn't fit in the bags comes by mail.

Missed or closed the menu? `.boost` works while the character is below level 10 (a Death Knight below 58) and has
never been boosted. Modern race/class pairs (modern_combos.sql) stay, and Death Knights are open from the first
character. None of Brawl's world changes apply on main.

## Files (same layout as `realm\`)

| File | What it is | Copy to |
|---|---|---|
| `profiles/main.env` | the profile; every key documented; `OV_MAIN=1` | `realm\profiles\` |
| `custom/lua_scripts/ov_main.lua` | the choice menu, the boost, `.boost` | `realm\custom\lua_scripts\` |
| `custom/lua_scripts/ov_kits.lua` | generated kit data, `OV_KITS[class][spec] = {name, role, pve, pvp}` | `realm\custom\lua_scripts\` |
| `main_world.sql` | the menu texts (npc_text 61010-61013, new rows only) | `realm\` |
| `main_unbrawl.sql` | puts back every stock row Brawl changed; no-op on a database that never ran Brawl | `realm\` |
| `Make it Main.bat` | local test realm: applies both SQL files + modern_combos.sql, switches to `main`, restarts | `realm\` |
| `kits.md` | every kit, by spec, with item names, ids, item level and stats | wherever you like |
| `patches/*.diff` | the changes existing files need (below) | apply by hand |
| `tools/` | generators (`gen_kits.py`, `gen_unbrawl.py`, `mk_itemdb.py`), `validate_kits.py`, `test/harness.lua` | not needed on the server |

The scripts only act when `OV_MAIN=1`, so copying them into `realm\custom\lua_scripts\` is harmless for Brawl.

## Changes existing files need

1. **`server\deploy.sh`** (`patches/deploy.sh-main.diff`): one `PROFILE` variable from `WU_PROFILE` (default
   `brawl`, checked against `profiles/`), and step 7 applies the SQL for that profile:
   * `brawl`: `brawl_world.sql brawl_world_2.sql modern_combos.sql` (as today)
   * `main`: `main_unbrawl.sql main_world.sql modern_combos.sql`
   * anything else: `modern_combos.sql`
   Warden is untouched (`WU_WARDEN`, as the deploy sets it).
2. **`server\Deploy Wrath to my server.bat`** (`patches/deploy-bat-main.diff`): takes the profile as its argument
   (`"Deploy Wrath to my server.bat" main`, no argument = brawl), uploads `main_unbrawl.sql` and `main_world.sql`
   with the other SQL files, and starts the server side with `WU_PROFILE=<profile> bash deploy.sh`.
3. **`realm\custom\lua_scripts\ov_armory.lua`** (`patches/ov_armory-main-level80.diff`, against the other agent's
   fixed copy in `/mnt/user-data/outputs/realm-lua/`): with `OV_MAIN=1` the Armory only works at level 80
   (`.armory give` says "On this realm the Armory opens at level 80."; searching still works). No change on Brawl.
4. Nothing else. `ov_services.lua` (its boost to 70 is off: `OV_BOOST_TO_70=0`), `ov_qol.lua` (main.env sets its
   gates explicitly) and `ov_brawl.lua` (`OV_BRAWL=0`) need no change. ov_main.lua shares `characters.ov_boosts`
   with ov_services.lua (same `CREATE TABLE IF NOT EXISTS`), so a character boosted by either can't boost again and
   both count toward one per-account kit cap.

Optional: add `main` to the profile list in the comments of `realm\Switch profile.bat` (it already works with any
`profiles\*.env`, but on its own it doesn't apply the SQL: use `Make it Main.bat` locally).

## Deploying main

1. Copy the files above into `realm\` and apply the three diffs.
2. `server\Deploy Wrath to my server.bat main` (type YES). Step 7 of the log shows
   `applied sql/main_unbrawl.sql`, `applied sql/main_world.sql`, `applied sql/modern_combos.sql`.
3. Already deployed as Brawl and only want to switch? On the server:
   `cd /srv/wrath && WU_PROFILE=main bash deploy.sh` does the whole flow again; the short way is to upload
   `profiles/main.env`, the two Lua files and the two SQL files, then
   ```
   cd /srv/wrath
   for f in sql/main_unbrawl.sql sql/main_world.sql sql/modern_combos.sql; do
     docker exec -i ov-ac-database sh -c 'MYSQL_PWD="$MYSQL_ROOT_PASSWORD" exec mysql -uroot acore_world' < "$f"; done
   sed -i 's/^OV_PROFILE=.*/OV_PROFILE=main/' .env && docker compose up -d ac-worldserver
   ```
   Characters made under Brawl keep everything they have (level, gear, gold). Main is meant for a fresh character
   database: if the Brawl test characters should not carry over, wipe `acore_characters` before opening.

## Test steps (local realm first, then live)

1. `Make it Main.bat`, then make a **Human Warrior**. Within ~3 s of entering the world: the menu with two choices.
   Close it, log out and back in: no menu, a chat line "type .boost".
2. `.boost` -> Protection -> Mining -> Blacksmithing. Check: level 80 in Dalaran, hearthstone says Dalaran, four
   20-slot bags, the PvE and PvP items of `kits.md` (Warrior / Protection) and the Medallion of the Alliance in the
   bags; spellbook full up to level 80 ranks (talent spells such as Vigilance come once the talent is taken);
   Defensive and Berserker Stance; weapon skills 400/400 (character pane -> Skills); Artisan Riding and Cold
   Weather Flying, Albino Drake and Swift Zhevra in the mount tab (Dalaran itself is no-fly: use the zhevra);
   Talents pane shows 71 points and a second spec; Mining, Blacksmithing, Cooking, First Aid, Fishing at 450/450.
3. Type `.boost` again: "This character has already been boosted." Relog: no menu, no reminder.
4. New **Orc Death Knight**: the menu (55), Boost -> Blood -> "No professions": Medallion of the Horde, Runeforging
   and Death Gate in the spellbook.
5. New **Gnome Mage**: "Begin your adventure at level 1": normal start in Dun Morogh, class trainer costs gold,
   vendors charge, dual spec costs 1000 g at a trainer (stock), `.armory give 40000` says the Armory opens at 80.
6. Overflow: on a fresh level 1, fill the backpack (buy/loot junk) and equip four small bags full of junk, then
   `.boost`: what doesn't fit arrives as mails "Your boost kit" (12 items each) at the Dalaran mailbox.
7. Live, after the deploy: `docker logs ov-ac-worldserver 2>&1 | grep -i -E "ov_main|ov_kits|lua"` shows the
   scripts loaded with no errors; then repeat steps 1-3 with a real account.

## Decisions (mine, easy to change)

* **Professions**: the player picks up to two primary professions in the boost (fewer if the character already has
  some); those, any it already had, and Cooking / First Aid / Fishing go to 450 with every trainer recipe
  (specialization recipes need the specialization quest first). A brand-new character has none to "max", so the
  pick-two route is the useful one.
* **Kit cap**: 10 kits per account (`OV_BOOST_KITS_PER_ACCOUNT`), the same table and number as ov_services.lua.
  Past the cap a boost still levels and teaches, without items. Kit gear is soulbound only (no Darkmoon Cards or
  other bind-on-equip items), so it can't be auctioned; the Frostweave Bags (as asked) are bind-on-equip and
  tradeable, and kit items still sell to vendors: that's the farm the cap limits.
* **No gold** with a boost (`OV_BOOST_GOLD=0`); set it to e.g. 200 if boosted characters should be able to repair
  and buy talent ranks straight away.
* **Talent-gated ranks** (e.g. Mortal Strike ranks 2+) are not taught (the talent isn't there yet); the player buys
  them at the trainer after taking the talent, as normal. Class mounts that are "teacher" spells (warlock
  Dreadsteed at the trainer) follow the trainer rules; paladin Warhorse/Charger and Felsteed are taught directly.
* **Fury** gets two one-handers (works before Titan's Grip); DK Frost dual-wields, Unholy and Blood two-handers.
  **Mage** and **Warlock** have one shared caster kit. Tanks have no PvP tier set, so their PvP kit is the plate /
  cat damage kit.
* **mod-individual-progression is off** on main (it would lock a boosted 80 out of Northrend).
* Arena points auto-distribute weekly (on, as Brawl).
* The menu opens 2.5 s after the first login (`Player:RegisterEvent`), from the player himself, like `.ov`.

## How the data was made

`tools/gen_kits.py` reads the realm core's own world data (mod-playerbots/azerothcore-wotlk 3f2969dd,
`data/sql/base/db_world`: item_template plus the loot, vendor and quest tables to keep only obtainable items)
loaded into a local MariaDB, and writes `ov_kits.lua`, `kits.md` and `tools/test/kits.json`. Selection: class
(AllowableClass), the class's best armor type, weapon types the class trains, all races, soulbound, no profession
/ reputation / honor requirement, item level 195-205 for PvE (Heroes' set excluded from off-slots) and 200-213 with
resilience for PvP, scored per spec profile (stat weights and forbidden stats per role: str, agi, hunter, enh,
tank, DK tank, bear, caster, healer, holy paladin). Spell power on many Wrath items is an equip spell, which the
world database doesn't describe; the generator labels each equip spell by the items carrying it (only caster items
-> spell power; only physical -> attack power). Relics are picked by name (marked *hand* in kits.md).
`tools/validate_kits.py` re-checks every item against the database: 324 distinct items, 0 problems.

`tools/gen_unbrawl.py` writes `main_unbrawl.sql` from the same stock data. Tested on a stock world database:
running it on stock changes nothing (CHECKSUM TABLE identical), and stock -> brawl_world.sql -> brawl_world_2.sql
-> main_unbrawl.sql gives back byte-identical item_template, npc_vendor, playercreateinfo, playercreateinfo_item,
playercreateinfo_spell_custom and gossip_menu_option; a second run changes nothing.

## Stub harness

`lua5.1 tools/test/harness.lua` (from this folder) fakes the mod-ale API and runs: bots and `OV_MAIN=0` get
nothing; the menu once and a reminder (not the menu) on relog; `.boost` -> spec -> professions -> boost; every
grant checked (rank chains, no talent ranks, own-faction spells, weapon skills 400, riding, dual spec, 450
professions, bags equipped, every kit item in the bags, faction medallion, Dalaran + hearth); a second boost and
stale menu clicks do nothing; another player's session can't touch the character (options not in your own menu and
wrong menu ids are dropped, as the core does); level-1 choice then `.boost` at 5, refused at 10; DK at 55 yes, 58 no;
full bags -> mail, at most 12 items a mail, bags + mail = the whole kit; the per-account cap; all 27 class/spec
kits boosted, every item checked for AllowableClass, AllowableRace, armor type, weapon type, shield/relic, soulbound.
Result: 2902 checks, 0 failed. `luac5.1 -p` is clean on both Lua files.
