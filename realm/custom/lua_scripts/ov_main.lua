-- WrathUnleashed MAIN realm (mod-ale): every new character chooses, once, between
--   "Begin your adventure at level 1"  the normal game (normal economy, trainers, starting zone), and
--   "Boost to level 80"                level 80 with a spec kit (custom/lua_scripts/ov_kits.lua).
-- Only runs when the realm profile sets OV_MAIN=1 (profiles/main.env). Brawl, progression and casual ignore it.
--
-- How it works
--   * First login of a character (level 1, or a level-55 Death Knight): a gossip menu from the player himself
--     (Player:GossipSendMenu with the player as sender, the same mechanism as ov_services.lua's .ov menu).
--   * Boost: pick a spec (one menu per class), then up to two primary professions (fewer if the character already
--     has some), then it runs once:
--       level 80 (talent points come with it); every class spell a trainer teaches up to 80, plus the
--       spells normally learned by class quests (stances, pet spells, demons, totems, forms, class mounts);
--       weapon skills of every weapon type the class can train, at 400; Apprentice to Artisan riding and Cold
--       Weather Flying, a ground and a flying mount; dual talent specialization; the chosen primary professions
--       plus Cooking, First Aid and Fishing at 450 with every recipe a trainer teaches (the character's own
--       professions too); four 20-slot bags (put in the empty bag slots); the PvE and PvP kit for the spec
--       and class reagents in the bags, the rest by in-game mail; teleport to Dalaran, hearthstone set there.
--       The PvE set is then worn (see "Gear" below) and every spell is put on the action bars ("Bars").
--   * .boost   reopens the boost for a character that skipped or closed the menu: only while it is below level 10
--              (a Death Knight below 58) and has never been boosted.
-- Once only: each boost is recorded in characters.ov_boosts (the table ov_services.lua's boost uses) before
-- anything is granted, and the choice in characters.ov_main_choice. A character in ov_boosts can never boost
-- again, and a character is only ever changed through its own session (the menu answers only to its owner: the
-- core checks the gossip menu id and sender of every selection), so nobody can boost another character.
-- Kits are capped per account like ov_services.lua (OV_BOOST_KITS_PER_ACCOUNT, default 10): after that, a boost
-- still levels and teaches but gives no gear, bags or reagents, so deleting and re-creating characters cannot farm
-- kits. Every kit item is soulbound (ov_kits.lua takes only bind-on-pickup items), so none can be auctioned.
--
-- Gear: the PvE set is equipped, each piece in the slot its InventoryType names (both rings, both trinkets;
--   main hand first, then a one-hander in the off hand if the character can dual wield, else a shield or
--   held item; ranged, thrown or relic). The starting gear in a slot goes into the bags first. A piece that
--   can't be worn yet (a second weapon before Dual Wield / Titan's Grip, a slot whose old piece found no room)
--   stays in the bags, as does the whole PvP set; nothing is dropped, mail stays the overflow path. A hunter's
--   ammo is selected. Pieces left in the bags are tried again when the character learns a talent.
-- Bars: a layout per class and spec (BARS below: bar 1 the rotation, bottom left the cooldowns and the PvP
--   medallion, bottom right buffs, utility and the mounts, the right bars the rest, the stance / form bars for
--   warriors, druids and rogues). Layouts name rank-1 spells; the boost puts the highest rank the character
--   knows (world spell_ranks + HasSpell). How they are applied (characters.ov_boost_bars, created here, keeps
--   one row per boosted character until its bars are written):
--     1. 2 s after the boost (or after login while still pending): SaveToDB, so the core's in-memory buttons are
--        all saved (UNCHANGED) and later saves of them write nothing.
--     2. 2 s later: the rows of every button the layout covers are replaced in character_action, for both
--        talent specs (the dual spec copy the boost made too), and SMSG_ACTION_BUTTONS (0x129, uint8 1 + 144 x
--        uint32 action | type << 24, as Player::SendActionButtons) shows them at once.
--     3. 2 s later: Activate Secondary Spec (63644) and 2 s after that Activate Primary Spec (63645). Each
--        ActivateSpec saves the in-memory buttons (nothing changed) and reloads them from character_action, so
--        the server's copy matches the rows and the client (a later save or loading screen can't bring the
--        starting bar back). Mana is refilled after (a spec switch zeroes it). Skipped in combat or a
--        battleground: then the rows are still right, and the next login loads them.
--   A talent ability (Mortal Strike, Penance, ...) has its button kept free; when the character learns the
--   talent, the trainer ranks of it are taught (the boost's trainer rules), the button is written in
--   character_action for the active spec and sent to the client. The core never places buttons by itself (only
--   CMSG_SET_ACTION_BUTTON, login and spec switches do; the 3.3.5a client doesn't place learned spells), so
--   nothing fights the layout.
-- Env (read at each use): OV_MAIN=1 on; OV_BOOST_KITS_PER_ACCOUNT (10); OV_BOOST_GOLD gold given with a kit (0).
-- Tables (characters DB, created here if missing): ov_main_choice, ov_boosts (same definition as ov_services.lua).
-- Gossip texts 61010-61013 come from main_world.sql (stock text 100 if they are missing).
--
-- mod-ale API used (mod-ale 84b85cc, src/LuaEngine/methods): RegisterPlayerEvent 3 LOGIN, 2 CHARACTER_DELETE,
-- 30 FIRST_LOGIN, 42 COMMAND; RegisterPlayerGossipEvent(menu, 2 = ON_SELECT); Player:GossipClearMenu /
-- GossipMenuAddItem(icon, text, sender, intid, code, popup) / GossipSendMenu(text, player, menu) / GossipComplete;
-- Unit:SetLevel (GiveLevel + InitTalentForLevel); Player:LearnSpell, HasSpell, HasSkill, SetSkill(id, step, cur,
-- max), AdvanceSkillsToMax; Unit:CastSpell(target, spell, triggered) for dual spec (63680 + 63624, what the
-- trainer's dual spec option casts in PlayerGossip.cpp); Player:AddItem (returns the Item, anything else = no
-- room); Player:EquipItem(entry, slot) and GetEquippedItemBySlot(19-22) for bags; SendMail(subject, text,
-- receiverGuidLow, senderGuidLow, stationery, delay, money, cod, entry, amount, ...) with at most 12 items;
-- Player:Teleport, SetBindPoint, GetTeam (0 Alliance, 1 Horde), IsBot (playerbots), GetAccountName.
-- Gear: GetItemTemplate(entry):GetInventoryType(), Player:EquipItem(entry or Item, slot) (CanEquipItem with
-- swap = false, so the slot must be empty; then AutoUnequipOffhandIfNeed), GetEquippedItemBySlot, RemoveItem(item,
-- 1), GetItemByEntry, SetAmmo. Bars: CreatePacket(opcode, size) + WorldPacket:WriteUByte / WriteULong,
-- Player:SendPacket, GetActiveSpec, GetSpecsCount, InBattleground, InArena, SetPower / GetMaxPower;
-- RegisterPlayerEvent 39 LEARN_TALENTS (event, player, talentId, talentRank, spellId).

local MENU_ID = 61010
local TEXT_WELCOME, TEXT_SPEC, TEXT_PROF, TEXT_DONE = 61010, 61011, 61012, 61013
local FALLBACK_TEXT = 100

local CLASS_DK = 6
local BOOST_LEVEL = 80
local MAX_LEVEL_TO_BOOST = 10      -- .boost works below this level (normal classes)
local MAX_LEVEL_TO_BOOST_DK = 58   -- Death Knights start at 55
local BAG = 41599                  -- Frostweave Bag (20 slots), as Brawl
local BAG_SLOTS = { 19, 20, 21, 22 }
local MAIL_SUBJECT = "Your boost kit"
local MAIL_STATIONERY_GM = 61
local MAX_MAIL_ITEMS = 12

local DALARAN = { map = 571, zone = 4395, x = 5804.15, y = 624.771, z = 647.767, o = 1.64 } -- Brawl's start spot

local RIDING = { 33388, 33391, 34090, 34091, 54197 } -- Apprentice, Journeyman, Expert, Artisan, Cold Weather Flying
local MOUNTS = { 49322, 60025 }                         -- Swift Zhevra (ground), Albino Drake (flying), as Brawl

-- Weapon skill spells per class (the weapon master list, as brawl_world_2.sql 3b). 196 1H axe, 197 2H axe, 198 1H
-- mace, 199 2H mace, 200 polearm, 201 1H sword, 202 2H sword, 227 staff, 264 bow, 266 gun, 1180 dagger,
-- 2567 thrown, 5011 crossbow, 5009 wand, 15590 fist.
local WEAPON_SPELLS = {
    [1]  = { 196, 197, 198, 199, 200, 201, 202, 227, 264, 266, 1180, 2567, 5011, 15590 },
    [2]  = { 196, 197, 198, 199, 200, 201, 202 },
    [3]  = { 196, 197, 200, 201, 202, 227, 264, 266, 1180, 2567, 5011, 15590 },
    [4]  = { 196, 198, 201, 264, 266, 1180, 2567, 5011, 15590 },
    [5]  = { 198, 227, 1180, 5009 },
    [6]  = { 196, 197, 198, 199, 200, 201, 202 },
    [7]  = { 196, 197, 198, 199, 227, 1180, 15590 },
    [8]  = { 201, 227, 1180, 5009 },
    [9]  = { 201, 227, 1180, 5009 },
    [11] = { 198, 199, 200, 227, 1180, 15590 },
}

-- Class spells that come from class quests, not trainers (a trainer's next rank needs them: AzerothCore's
-- trainer_spell ReqAbility points at them). Learned before the trainer pass so the ranks chain.
local QUEST_SPELLS = {
    [1]  = { 71, 355, 7386, 2458 },             -- Defensive Stance, Taunt, Sunder Armor, Berserker Stance
    [2]  = { 7328 },                            -- Redemption
    [3]  = { 1515, 883, 2641, 6991, 982 },      -- Tame Beast, Call / Dismiss / Feed / Revive Pet
    [6]  = { 53428, 50977, 48778, 49576 },      -- Runeforging, Death Gate, Acherus Deathcharger, Death Grip
    [7]  = { 8071, 3599, 5394 },                -- Stoneskin, Searing and Healing Stream Totem (rank 1)
    [9]  = { 697, 712, 691, 1122, 18540, 5784 },-- Voidwalker, Succubus, Felhunter, Inferno, Ritual of Doom, Felsteed
    [11] = { 5487, 6807, 6795, 33943 },         -- Bear Form, Maul, Growl, Flight Form
}
-- Class mounts by faction (paladin), learned directly (the trainer's are "teacher" spells).
local FACTION_MOUNTS = { [2] = { [0] = { 13819, 23214 }, [1] = { 34769, 34767 } } }

-- Reagents and class items (the same ones Brawl hands out), with the kit.
local CLASS_ITEMS = {
    [2]  = { { 21177, 100 } },                                         -- Symbol of Kings
    [3]  = { { 41165, 1000 }, { 41164, 1000 } },                       -- arrows, bullets
    [5]  = { { 44615, 20 } },                                          -- Devout Candle
    [7]  = { { 5175, 1 }, { 5176, 1 }, { 5177, 1 }, { 5178, 1 }, { 17030, 10 } }, -- totems, Ankh
    [8]  = { { 17020, 20 }, { 17031, 10 }, { 17032, 10 } },            -- Arcane Powder, runes
    [9]  = { { 21340, 1 } },                                           -- Soul Pouch
    [11] = { { 44605, 20 } },                                          -- Wild Spineleaf
}

-- Professions: skill line -> Grand Master spell (the ranks brawl_world_2.sql teaches) and menu name.
local PRIMARY = {
    { 171, 51304, "Alchemy" }, { 164, 51300, "Blacksmithing" }, { 333, 51313, "Enchanting" },
    { 202, 51306, "Engineering" }, { 182, 50300, "Herbalism" }, { 773, 45363, "Inscription" },
    { 755, 51311, "Jewelcrafting" }, { 165, 51302, "Leatherworking" }, { 186, 50310, "Mining" },
    { 393, 50305, "Skinning" }, { 197, 51309, "Tailoring" },
}
local SECONDARY = { { 185, 51296, "Cooking" }, { 129, 45542, "First Aid" }, { 356, 51294, "Fishing" } }
local GRAND_MASTER_STEP, MAX_SKILL = 6, 450   -- as ov_brawl.lua
local MAX_PRIMARY = 2

-- Faction-only class trainer spells (as ov_qol.lua): both factions' trainers share the class requirement.
local TEAM_ALLIANCE, TEAM_HORDE = 0, 1
local FACTION_ONLY = {}
for _, id in ipairs({ 3561, 3562, 3565, 32271, 49359, 33690, 10059, 11416, 11419, 32266, 49360, 33691,
    32182, 31801, 13820, 23214 }) do FACTION_ONLY[id] = TEAM_ALLIANCE end
for _, id in ipairs({ 3563, 3566, 3567, 32272, 49358, 35715, 11418, 11420, 11417, 32267, 49361, 35717,
    2825, 53736, 34767, 34768 }) do FACTION_ONLY[id] = TEAM_HORDE end
local SPELL_EFFECT_LEARN_SPELL = 36
local KNOWN_TEACHERS = { [13820] = true, [34768] = true }

------------------------------------------------------------------------------------------------ action bar layouts
-- The 144 action buttons of 3.3.5a (Player.h MAX_ACTION_BUTTONS), 12 to a bar:
--     0-11  bar 1 (the main bar, page 1)            12-23  bar 1 page 2 (shift+2)
--    24-35  right bar                               36-47  right bar 2
--    48-59  bottom right bar ("bar 2" here)         60-71  bottom left bar
--    72-83  bonus bar 1: warrior Battle Stance, druid Cat Form, rogue Stealth (and Shadow Dance)
--    84-95  bonus bar 2: warrior Defensive Stance, druid Tree of Life
--   96-107  bonus bar 3: warrior Berserker Stance, druid Bear / Dire Bear Form
--  108-119  bonus bar 4: druid Moonkin Form
-- While a stance / form is active the client shows its bonus bar in place of bar 1 (the offsets 1-4 come from
-- SpellShapeshiftForm.dbc's BonusActionBar; AzerothCore's playercreateinfo_action confirms 72 / 84 / 96 for the
-- warrior stances and 72 / 96 for cat / bear). Shadowform and Metamorphosis get a copy of their main bar on
-- bonus bar 1 / 2 as well: if the client gives them that bar the abilities are there, if not the copy is unused.
-- The bottom and right bars are client options (Interface > ActionBars), off on a new character: the boost
-- message says how to turn them on.
--
-- Each row starts at a button and lists up to 12 entries, in order:
--   a number      a spell, written as its rank-1 id; the boost puts the highest rank the character knows there
--   { a, b, .. }  the first of these the character knows (faction or race versions of one spell)
--   0             left empty
--   RACIAL        the race's active racial;  HEARTH the Hearthstone (item);  PVP the kit's PvP medallion (item)
--   GROUND / FLY  the boost's ground / flying mount
-- A spell the character doesn't know yet (a talent) keeps its button free and is put there when it is learned.
-- Rows in a spec replace the class's row that starts at the same button.
local RACIAL, HEARTH, PVP, GROUND, FLY = "racial", "hearth", "pvp", "ground", "fly"
local SEAL_VC = { 31801, 53736 }      -- Seal of Vengeance (Alliance) / Seal of Corruption (Horde)
local HEROISM = { 32182, 2825 }       -- Heroism (Alliance) / Bloodlust (Horde)

local BARS = {}

BARS[1] = { -- Warrior
    base = {
        [72] = { 100, 772, 7384, 78, 845, 6343, 1464, 5308, 1715, 34428, 694, 20230 },  -- Battle Stance
        [84] = { 7386, 355, 6572, 2565, 72, 23922, 78, 845, 6343, 676, 23920, 871 },     -- Defensive Stance
        [96] = { 20252, 1680, 6552, 78, 845, 1464, 5308, 1715, 18499, 1719, 34428, 5246 }, -- Berserker Stance
        [48] = { 6673, 469, 1160, 5246, 1161, 3411, 676, 23920, 694, 2764, GROUND, FLY },
        [36] = { RACIAL, HEARTH, 12323, 60970 },
    },
    arms = {
        [0]  = { 12294, 772, 7384, 1464, 5308, 78, 845, 6343, 1715, 100, 34428, 12328 },
        [72] = { 12294, 772, 7384, 1464, 5308, 78, 845, 6343, 1715, 100, 34428, 12328 },
        [96] = { 12294, 1464, 5308, 78, 845, 1680, 6552, 20252, 1715, 18499, 1719, 34428 },
        [60] = { 2687, 46924, 1719, 20230, 18499, 871, 55694, 64382, 57755, 2565, 0, PVP },
    },
    fury = {
        [0]  = { 23881, 1680, 1464, 5308, 78, 845, 6552, 20252, 1715, 18499, 1719, 34428 },
        [96] = { 23881, 1680, 1464, 5308, 78, 845, 6552, 20252, 1715, 18499, 1719, 34428 },
        [72] = { 23881, 7384, 1464, 5308, 78, 845, 772, 6343, 1715, 100, 34428, 20230 },
        [60] = { 2687, 12292, 1719, 18499, 55694, 20230, 871, 64382, 57755, 2565, 0, PVP },
    },
    prot = {
        [0]  = { 23922, 6572, 20243, 6343, 78, 845, 355, 46968, 12809, 2565, 72, 23920 },
        [84] = { 23922, 6572, 20243, 6343, 78, 845, 355, 46968, 12809, 2565, 72, 23920 },
        [72] = { 100, 6343, 772, 23922, 7384, 78, 845, 5308, 1715, 694, 34428, 20230 },
        [60] = { 2687, 871, 12975, 50720, 1161, 18499, 1719, 55694, 64382, 57755, 676, PVP },
    },
}

BARS[2] = { -- Paladin
    base = {
        [60] = { 31884, 642, 498, 633, 1022, 1044, 6940, 1038, 54428, 31821, 64205, PVP },
        [48] = { 21084, SEAL_VC, 20375, 20165, 20166, 20164, 19740, 20217, 19742, 25780, GROUND, FLY },
        [24] = { 465, 7294, 19746, 32223, 19876, 19888, 19891, 25898, 25782, 25894, 25899, 20911 },
        [36] = { RACIAL, HEARTH, 7328, 10326, 20066, 5502, 19752, 853, 62124, 31789 },
    },
    holy = {
        [0] = { 635, 19750, 20473, 53563, 53601, 4987, 20271, 54428, 20216, 31842, 6940, 633 },
    },
    prot = {
        [0] = { 31935, 53595, 53600, 20925, 26573, 20271, 62124, 31789, 2812, 853, 24275, 879 },
    },
    ret = {
        [0] = { 35395, 53385, 20271, 26573, 879, 24275, 853, 2812, 4987, 19750, 62124, 1044 },
    },
}

BARS[3] = { -- Hunter
    base = {
        [60] = { 3045, 23989, 34477, 781, 5384, 19263, 53271, 19801, 19503, 1510, 2974, PVP },
        [48] = { 61846, 13165, 34074, 5118, 13159, 13813, 1499, 13809, 60192, 34600, GROUND, FLY },
        [24] = { 883, 2641, 982, 136, 6991, 1515, 13795, 20043, 3034, 3043, 1543, 20736 },
        [36] = { RACIAL, HEARTH, 2973, 1495, 19306, 1002, 6197, 1494, 19883, 1513, 1462 },
    },
    bm = {
        [0] = { 75, 56641, 3044, 2643, 1978, 53351, 34026, 1130, 19574, 19577, 136, 5116 },
    },
    mm = {
        [0] = { 75, 56641, 53209, 19434, 3044, 2643, 1978, 53351, 1130, 34490, 34026, 5116 },
    },
    sv = {
        [0] = { 75, 56641, 53301, 3674, 3044, 2643, 1978, 53351, 1130, 34026, 19386, 5116 },
    },
}

BARS[4] = { -- Rogue
    base = {
        [72] = { 8676, 703, 1833, 6770, 921, 1725, 14183, 36554, 1752, 5171, 2098, 2983 },      -- Stealth
        [60] = { 1856, 5277, 31224, 2983, 2094, 51722, 14185, 14177, 1966, 26679, 5938, PVP },
        [48] = { 1784, 8647, 1725, 1804, 1842, 921, 6770, 2764, 51723, 57934, GROUND, FLY },
        [36] = { RACIAL, HEARTH, 1776 },
    },
    assa = {
        [0]  = { 1329, 32645, 5171, 1943, 2098, 1752, 51662, 14177, 1766, 408, 51723, 57934 },
        [72] = { 8676, 703, 1833, 6770, 921, 1725, 14183, 36554, 1329, 5171, 32645, 2983 },
    },
    combat = {
        [0] = { 1752, 5171, 2098, 1943, 13877, 13750, 51690, 1766, 408, 1776, 51723, 57934 },
    },
    sub = {
        [0]  = { 16511, 53, 5171, 2098, 1943, 36554, 51713, 14185, 1766, 408, 51723, 57934 },
        [72] = { 8676, 703, 1833, 6770, 921, 1725, 14183, 36554, 16511, 5171, 2098, 2983 },
    },
}

BARS[5] = { -- Priest
    base = {
        [60] = { 34433, 64901, 64843, 586, 8122, 6346, 32375, 19236, 10060, 33206, 47585, PVP },
        [48] = { 588, 1243, 21562, 976, 27683, 14752, 27681, 15286, 2006, 1706, GROUND, FLY },
        [24] = { 605, 453, 2096, 9484, 8129, 15237, 585, 14914, 8092, 589, 32379, 5019 },
        [36] = { RACIAL, HEARTH, 527, 528, 552, 17, 139, 2061 },
    },
    disc = {
        [0] = { 17, 47540, 2061, 2060, 33076, 139, 596, 527, 552, 33206, 10060, 14751 },
    },
    holy = {
        [0] = { 2060, 2061, 139, 33076, 34861, 596, 32546, 17, 527, 552, 47788, 724 },
    },
    shadow = {
        [0]  = { 34914, 2944, 589, 8092, 15407, 32379, 48045, 15473, 47585, 15487, 64044, 5019 },
        [72] = { 34914, 2944, 589, 8092, 15407, 32379, 48045, 15473, 47585, 15487, 64044, 5019 }, -- Shadowform copy
    },
}

BARS[6] = { -- Death Knight
    base = {
        [60] = { 48792, 48707, 47568, 45529, 42650, 48743, 47528, 47476, 45524, 49576, 51052, PVP },
        [48] = { 48266, 48263, 48265, 57330, 3714, 61999, 50977, 53428, 46584, 49158, GROUND, FLY },
        [36] = { RACIAL, HEARTH, 56222, 48778 },
    },
    blood = {
        [0]  = { 55050, 49998, 45477, 45462, 45902, 50842, 48721, 43265, 56815, 56222, 47541, 49576 },
        [24] = { 55233, 48982, 49028, 49222, 49016, 49005, 0, 0, 0, 0, 0, 0 },
    },
    frost = {
        [0]  = { 45477, 45462, 49020, 49143, 49184, 45902, 50842, 43265, 47541, 51271, 49796, 57330 },
        [24] = { 49203, 49039, 51271, 49796, 56815, 49998, 0, 0, 0, 0, 0, 0 },
    },
    unholy = {
        [0]  = { 45477, 45462, 55090, 45902, 47541, 50842, 43265, 48721, 49206, 63560, 46584, 57330 },
        [24] = { 49222, 49194, 49158, 56815, 49998, 0, 0, 0, 0, 0, 0, 0 },
    },
}

BARS[7] = { -- Shaman
    base = {
        [60] = { HEROISM, 2894, 2062, 51514, 2484, 8143, 8177, 5730, 36936, 16166, 30823, PVP },
        [48] = { 66842, 66843, 66844, 8024, 8232, 51730, 8033, 2645, 2008, 556, GROUND, FLY },
        [24] = { 3599, 8190, 8227, 30706, 8075, 8071, 5394, 5675, 8170, 8512, 3738, 8181 },
        [36] = { RACIAL, HEARTH, 546, 131, 6196, 8184, 10595, 6495, 8017, 370, 57994 },
    },
    ele = {
        [0] = { 403, 421, 51505, 8050, 8042, 51490, 16166, 57994, 370, 8056, 1535, 324 },
    },
    enh = {
        [0] = { 17364, 60103, 8042, 8050, 403, 421, 1535, 57994, 8190, 30823, 51533, 324 },
    },
    resto = {
        [0] = { 61295, 1064, 331, 8004, 974, 51886, 526, 16188, 55198, 16190, 52127, 57994 },
    },
}

local MAGE_PORTS = { -- Alliance / Horde versions: teleports, then portals
    { 3561, 3567 }, { 3562, 3563 }, { 3565, 3566 }, { 32271, 32272 }, { 49359, 49358 }, { 33690, 35715 },
    { 10059, 11417 }, { 11416, 11418 }, { 11419, 11420 }, { 32266, 32267 }, { 49360, 49361 }, { 33691, 35717 },
}
BARS[8] = { -- Mage (one kit for the three trees: the main bar holds each tree's core spells)
    base = {
        [0]  = { 133, 44614, 116, 30451, 5143, 44425, 11366, 44457, 2136, 2948, 30455, 44572 },
        [60] = { 12051, 45438, 1953, 2139, 66, 12472, 12042, 11129, 12043, 11958, 55342, PVP },
        [48] = { 1459, 23028, 5019, 30482, 6117, 7302, 42955, 759, 475, 130, GROUND, FLY },
        [24] = { 118, 122, 120, 1449, 10, 2120, 30449, 543, 6143, 1463, 11426, 31661 },
        [36] = { RACIAL, HEARTH, 53140, 53142, 43987, 604, 1008, 11113, 31687, 0, 0, 0 },
        [12] = MAGE_PORTS,
    },
}

BARS[9] = { -- Warlock (one kit for the three trees)
    base = {
        [0]  = { 686, 172, 980, 348, 30108, 48181, 1120, 17962, 29722, 6353, 50796, 1454 },
        [84] = { 686, 172, 980, 348, 50589, 50581, 54785, 17962, 29722, 6353, 47241, 1454 }, -- Metamorphosis copy
        [60] = { 47241, 18708, 47193, 6229, 47897, 1122, 18540, 5484, 6789, 30283, 48020, PVP },
        [48] = { 28176, 706, 603, 702, 1714, 18223, 1490, 5782, 710, 48018, GROUND, FLY },
        [24] = { 688, 697, 712, 691, 30146, 693, 6201, 6366, 2362, 698, 29893, 5784 },
        [36] = { RACIAL, HEARTH, 1949, 5740, 27243, 755, 126, 5697, 132, 5500, 1098, 23161 },
    },
}

BARS[11] = { -- Druid: caster bar 1, Cat 72, Tree of Life 84, Bear 96, Moonkin 108 for every spec
    base = {
        [0]   = { 5185, 8936, 774, 2893, 2782, 339, 33786, 770, 29166, 20484, 1126, 467 },
        [72]  = { 1082, 1822, 1079, 22568, 52610, 5221, 5215, 1850, 5217, 9005, 6785, 62078 },  -- Cat
        [84]  = { 774, 33763, 8936, 50464, 18562, 48438, 2893, 2782, 29166, 22812, 740, 17116 }, -- Tree of Life
        [96]  = { 6807, 779, 33745, 99, 6795, 5211, 5229, 22842, 5209, 16857, 22812, 61336 },    -- Bear
        [108] = { 5176, 2912, 8921, 5570, 48505, 50516, 33831, 770, 16914, 29166, 22812, 33786 }, -- Moonkin
        [60]  = { 29166, 22812, 20484, 740, 16689, 33786, 339, 2637, 61336, 50334, 1850, PVP },
        [48]  = { 1126, 21849, 467, 50769, 783, 1066, 33943, 2908, 5225, 0, GROUND, FLY },
        [36]  = { RACIAL, HEARTH, 768, 5487, 24858, 33891 },
    },
    balance = {
        [0] = { 5176, 2912, 8921, 5570, 48505, 50516, 33831, 770, 16914, 29166, 22812, 33786 },
    },
    cat = {
        [72] = { 33876, 5221, 1822, 1079, 52610, 22568, 5217, 50334, 49376, 5215, 1850, 62078 },
        [96] = { 33878, 33745, 779, 6807, 16857, 6795, 99, 16979, 5211, 5229, 22842, 61336 },
    },
    bear = {
        [96] = { 33878, 33745, 779, 6807, 16857, 6795, 99, 16979, 5211, 5229, 22842, 61336 },
        [72] = { 33876, 5221, 1822, 1079, 52610, 22568, 5217, 50334, 49376, 5215, 1850, 62078 },
    },
    resto = {
        [0] = { 774, 33763, 8936, 50464, 5185, 18562, 48438, 17116, 2893, 2782, 740, 29166 },
    },
}

local RACIALS = { 59752, 20594, 20589, 58984, 7744, 20549, 26297, 20572, 33697, 33702, 28730, 25046, 50613,
    28880, 59542, 59543, 59544, 59545, 59547, 59548 }

local KITS = OV_KITS
if type(KITS) ~= "table" then
    local ok, mod = pcall(require, "ov_kits")
    KITS = ok and mod or OV_KITS
end

local unpack = unpack or table.unpack
local pending = {}   -- [guidLow] = { spec = key, profs = { skill, ... } }   (menu state, this session only)
local busy = {}      -- [guidLow] = true while / after a boost runs in this process

------------------------------------------------------------------------------------------------ helpers
local function on() return os.getenv("OV_MAIN") == "1" end
local function num(name, default)
    local v = tonumber(os.getenv(name) or "")
    return v and math.floor(v) or default
end
local function say(player, text) player:SendBroadcastMessage("|cff66ccff[WrathUnleashed]|r " .. text) end
local function try(obj, method, ...)
    local f = obj and obj[method]
    if type(f) ~= "function" then return nil end
    local ok, r = pcall(f, obj, ...)
    if ok then return r end
    return nil
end

local function isBot(player)
    if try(player, "IsBot") == true then return true end
    if try(player, "IsPlayerbot") == true then return true end
    local name = try(player, "GetAccountName")
    return type(name) == "string" and name:upper():find("^RNDBOT") ~= nil
end

local function queryValue(sql)
    local q = CharDBQuery(sql)
    if not q then return nil end
    return q:GetUInt32(0)
end

local function choiceOf(guid)
    local q = CharDBQuery(string.format("SELECT choice FROM ov_main_choice WHERE guid = %d", guid))
    if not q then return nil end
    return q:GetString(0)
end

local function everBoosted(guid)
    return busy[guid] == true or (queryValue(string.format("SELECT COUNT(*) AS n FROM ov_boosts WHERE char_guid = %d", guid)) or 0) > 0
end

local function setChoice(player, choice, spec)
    CharDBExecute(string.format(
        "INSERT INTO ov_main_choice (guid, account, choice, spec, created_at, decided_at) VALUES (%d, %d, '%s', '%s', %d, %d) " ..
        "ON DUPLICATE KEY UPDATE choice = VALUES(choice), spec = VALUES(spec), decided_at = VALUES(decided_at)",
        player:GetGUIDLow(), player:GetAccountId(), choice, spec or "", os.time(), choice == "pending" and 0 or os.time()))
end

local function levelOk(player)
    local limit = player:GetClass() == CLASS_DK and MAX_LEVEL_TO_BOOST_DK or MAX_LEVEL_TO_BOOST
    return player:GetLevel() < limit
end

-- Can this character boost now? (second value: why not)
local function canBoost(player)
    if not on() then return false, "off" end
    if isBot(player) then return false, "bot" end
    if not levelOk(player) then return false, "level" end
    if everBoosted(player:GetGUIDLow()) then return false, "done" end
    return true
end

local function kitFor(player, key)
    local byClass = KITS and KITS[player:GetClass()]
    return byClass and byClass[key]
end

local function sendMenu(player, text)
    player:GossipSendMenu(text or FALLBACK_TEXT, player, MENU_ID)
end

------------------------------------------------------------------------------------------------ menus
-- intids: 1 level 1, 2 boost (spec menu), 3 close, 10+n spec n, 1000+skill profession, 999 boost now
local function showChoice(player)
    if not canBoost(player) then return end
    player:GossipClearMenu()
    local dk = player:GetClass() == CLASS_DK
    player:GossipMenuAddItem(0, dk and "Begin your adventure as a Death Knight (the Ebon Hold story)"
        or "Begin your adventure at level 1", 0, 1, false,
        "Play from the start. You can still type .boost until level " ..
        (dk and MAX_LEVEL_TO_BOOST_DK or MAX_LEVEL_TO_BOOST) .. ".")
    player:GossipMenuAddItem(0, "Boost to level 80 (spec gear, professions, Dalaran)", 0, 2)
    sendMenu(player, TEXT_WELCOME)
end

local function showSpecs(player)
    local order = KITS and KITS.order and KITS.order[player:GetClass()]
    if not order then
        say(player, "No boost kit is set up for your class.")
        return player:GossipComplete()
    end
    player:GossipClearMenu()
    for n, key in ipairs(order) do
        local kit = KITS[player:GetClass()][key]
        player:GossipMenuAddItem(3, kit.name, 0, 10 + n)
    end
    player:GossipMenuAddItem(0, "Back", 0, 3)
    sendMenu(player, TEXT_SPEC)
end

local function primariesKnown(player)
    local n = 0
    for _, p in ipairs(PRIMARY) do if player:HasSkill(p[1]) then n = n + 1 end end
    return n
end

local function showProfessions(player, state)
    local have = primariesKnown(player) + #state.profs
    if have >= MAX_PRIMARY then return false end
    player:GossipClearMenu()
    for _, p in ipairs(PRIMARY) do
        local taken = player:HasSkill(p[1])
        for _, s in ipairs(state.profs) do if s == p[1] then taken = true end end
        if not taken then player:GossipMenuAddItem(4, p[3] .. " (Grand Master, 450)", 0, 1000 + p[1]) end
    end
    local kit = kitFor(player, state.spec)
    player:GossipMenuAddItem(0, (#state.profs > 0 and "No more professions: " or "No professions: ") ..
        "boost now as " .. (kit and kit.name or state.spec), 0, 999, false,
        "Boost this character to 80 now? This happens once and cannot be undone.")
    sendMenu(player, TEXT_PROF)
    return true
end

------------------------------------------------------------------------------------------------ the boost
local function learnList(player, list)
    for _, id in ipairs(list or {}) do
        if not player:HasSpell(id) then player:LearnSpell(id) end
    end
end

local teacherCache = {}
local function isTeacherSpell(id)
    if KNOWN_TEACHERS[id] then return true end
    if teacherCache[id] ~= nil then return teacherCache[id] end
    local result = false
    if type(GetSpellInfo) == "function" then
        local ok, info = pcall(GetSpellInfo, id)
        if ok and info then result = try(info, "HasEffect", SPELL_EFFECT_LEARN_SPELL) == true end
    end
    teacherCache[id] = result
    return result
end

-- Trainer spells up to `level` (class trainers: Type 0, Requirement = class; profession trainers: Type 2,
-- ReqSkillLine = skill). Same query and rules as ov_qol.lua's auto-learn: the previous rank or talent in
-- ReqAbility must be known (talent ranks are left out), a few passes so new ranks unlock the next.
local function trainerSpells(sql)
    local list = {}
    local q = WorldDBQuery(sql)
    if q then
        repeat
            list[#list + 1] = { id = q:GetUInt32(0), lvl = q:GetUInt32(1), skill = q:GetUInt32(2), rank = q:GetUInt32(3),
                r1 = q:GetUInt32(4), r2 = q:GetUInt32(5), r3 = q:GetUInt32(6) }
        until not q:NextRow()
    end
    return list
end

local function learnFromTrainer(player, list)
    local team = try(player, "GetTeam")
    local level, learned = player:GetLevel(), 0
    for _ = 1, 6 do
        local progress = false
        for _, e in ipairs(list) do
            if e.lvl <= level and not player:HasSpell(e.id) and not isTeacherSpell(e.id) then
                local side = FACTION_ONLY[e.id]
                local ok = side == nil or side == team
                for _, req in ipairs({ e.r1, e.r2, e.r3 }) do
                    if ok and req and req > 0 and not player:HasSpell(req) then ok = false end
                end
                if ok and e.skill and e.skill > 0 then
                    ok = player:HasSkill(e.skill) and (try(player, "GetSkillValue", e.skill) or 0) >= (e.rank or 0)
                end
                if ok then
                    player:LearnSpell(e.id)
                    if player:HasSpell(e.id) then learned = learned + 1; progress = true end
                end
            end
        end
        if not progress then break end
    end
    return learned
end

-- Every computed column has a name (as in ov_qol.lua / ov_services.lua).
local COLS = "ts.SpellId, MIN(ts.ReqLevel) AS lvl, MAX(ts.ReqSkillLine) AS sk, MAX(ts.ReqSkillRank) AS rk, " ..
    "MAX(ts.ReqAbility1) AS r1, MAX(ts.ReqAbility2) AS r2, MAX(ts.ReqAbility3) AS r3"

local function learnClassSpells(player)
    local cls = player:GetClass()
    learnList(player, QUEST_SPELLS[cls])
    local fm = FACTION_MOUNTS[cls]
    if fm then learnList(player, fm[try(player, "GetTeam") or 0]) end
    return learnFromTrainer(player, trainerSpells(string.format(
        "SELECT " .. COLS .. " FROM trainer t JOIN trainer_spell ts ON ts.TrainerId = t.Id " ..
        "WHERE t.Type = 0 AND t.Requirement = %d AND ts.SpellId > 0 GROUP BY ts.SpellId ORDER BY 2, 1", cls)))
end

local function maxProfession(player, skill, gmSpell)
    if not player:HasSpell(gmSpell) then player:LearnSpell(gmSpell) end
    if player:HasSkill(skill) then
        player:SetSkill(skill, GRAND_MASTER_STEP, MAX_SKILL, MAX_SKILL)   -- as ov_brawl.lua
    end
    return learnFromTrainer(player, trainerSpells(string.format(
        "SELECT " .. COLS .. " FROM trainer t JOIN trainer_spell ts ON ts.TrainerId = t.Id " ..
        "WHERE t.Type = 2 AND ts.ReqSkillLine = %d AND ts.SpellId > 0 GROUP BY ts.SpellId ORDER BY 2, 1", skill)))
end

local function addOrQueue(player, entry, count, overflow)
    local item = player:AddItem(entry, count)
    if type(item) == "userdata" then return end
    -- mod-ale's AddItem pushes nothing on a full bag (the caller gets its last argument back); stacks that
    -- only partly fit are not split here: the whole amount goes by mail.
    overflow[#overflow + 1] = { entry, count }
end

local function mailOverflow(player, overflow)
    local sent = 0
    for i = 1, #overflow, MAX_MAIL_ITEMS do
        local args = {}
        for j = i, math.min(i + MAX_MAIL_ITEMS - 1, #overflow) do
            args[#args + 1] = overflow[j][1]
            args[#args + 1] = overflow[j][2]
        end
        SendMail(MAIL_SUBJECT, "Your bags were full, so the rest of your boost kit is here.",
            player:GetGUIDLow(), 0, MAIL_STATIONERY_GM, 0, 0, 0, unpack(args))
        sent = sent + 1
    end
    return sent
end

------------------------------------------------------------------------------------------------ wearing the PvE set
-- InventoryType (ItemTemplate) -> the equipment slots it can go in (EquipmentSlots, Player::FindEquipSlot)
local INV_SLOTS = {
    [1] = { 0 }, [2] = { 1 }, [3] = { 2 }, [4] = { 3 }, [5] = { 4 }, [20] = { 4 }, [6] = { 5 }, [7] = { 6 },
    [8] = { 7 }, [9] = { 8 }, [10] = { 9 }, [11] = { 10, 11 }, [12] = { 12, 13 }, [16] = { 14 },
    [13] = { 15, 16 },                              -- one-hand: main hand, else off hand (needs Dual Wield)
    [17] = { 15 }, [21] = { 15 },                   -- two-hand, main-hand only
    [22] = { 16 }, [14] = { 16 }, [23] = { 16 },    -- off-hand weapon, shield, held in off hand
    [15] = { 17 }, [25] = { 17 }, [26] = { 17 }, [28] = { 17 }, -- bow, thrown, gun / crossbow / wand, relic
    [19] = { 18 },
}
-- Weapons in this order: what can only go in the main hand, then one-handers, then off-hand-only pieces.
local WEAPON_ORDER = { [17] = 1, [21] = 1, [13] = 2, [22] = 3, [14] = 3, [23] = 3 }
local LAST_EQUIP_SLOT = 18
local AMMO_ARROW, AMMO_BULLET, SUBCLASS_GUN = 41165, 41164, 3

local function invTypeOf(entry)
    if type(GetItemTemplate) ~= "function" then return nil end
    local ok, t = pcall(GetItemTemplate, entry)
    if not ok or not t then return nil end
    return try(t, "GetInventoryType")
end

local function wornEntries(player)
    local set = {}
    for slot = 0, LAST_EQUIP_SLOT do
        local it = try(player, "GetEquippedItemBySlot", slot)
        local e = it and try(it, "GetEntry")
        if e then set[e] = true end
    end
    return set
end

-- Moves what the character wears in `slot` (its starting gear) into the bags. True when the slot is free, and
-- the moved piece (put back on if the kit's piece then can't be worn).
local function freeSlot(player, slot)
    local old = try(player, "GetEquippedItemBySlot", slot)
    if not old then return true end
    local entry = try(old, "GetEntry")
    local copy = entry and player:AddItem(entry, 1)
    if type(copy) ~= "userdata" then return false end   -- no room: the old piece stays on
    player:RemoveItem(old, 1)
    if try(player, "GetEquippedItemBySlot", slot) then return false end
    return true, copy
end

-- Wears `ids` (the PvE set). fromBags = false: each piece is created in its slot (the boost; starting gear goes
-- to the bags first). fromBags = true: pieces already in the bags go into slots that are empty (a later retry).
-- Returns the ids not worn (the boost puts them in the bags) and how many were.
local function equipSet(player, ids, fromBags)
    local list, already = {}, fromBags and wornEntries(player) or {}
    for n, id in ipairs(ids or {}) do
        if not already[id] then list[#list + 1] = { id = id, inv = invTypeOf(id) or 0, n = n } end
    end
    table.sort(list, function(a, b)
        local oa, ob = WEAPON_ORDER[a.inv] or 0, WEAPON_ORDER[b.inv] or 0
        if oa ~= ob then return oa < ob end
        return a.n < b.n
    end)
    local taken, left, count = {}, {}, 0
    for _, e in ipairs(list) do
        local done = false
        for _, slot in ipairs(INV_SLOTS[e.inv] or {}) do
            if not done and not taken[slot] then
                local src, free, copy = e.id, false, nil
                if fromBags then
                    src = try(player, "GetItemByEntry", e.id)
                    free = src ~= nil and not try(player, "GetEquippedItemBySlot", slot)
                else
                    free, copy = freeSlot(player, slot)
                end
                if free then
                    local r = try(player, "EquipItem", src, slot)
                    if type(r) == "userdata" then
                        done, taken[slot], count = true, true, count + 1
                    elseif copy then
                        try(player, "EquipItem", copy, slot)   -- the starting piece goes back on
                    end
                end
            end
        end
        if not done then left[#left + 1] = e.id end
    end
    return left, count
end

local function selectAmmo(player)
    if player:GetClass() ~= 3 then return end
    local ranged = try(player, "GetEquippedItemBySlot", 17)
    local t = ranged and try(ranged, "GetItemTemplate")
    try(player, "SetAmmo", (t and try(t, "GetSubClass") == SUBCLASS_GUN) and AMMO_BULLET or AMMO_ARROW)
end

local function giveItems(player, kit)
    local overflow = {}
    -- bags first, into empty bag slots (more room for the kit); the rest of the four in the backpack / mail
    local bagsLeft = 4
    for _, slot in ipairs(BAG_SLOTS) do
        if bagsLeft > 0 and not try(player, "GetEquippedItemBySlot", slot) then
            local b = try(player, "EquipItem", BAG, slot)
            if type(b) == "userdata" then bagsLeft = bagsLeft - 1 end
        end
    end
    for _ = 1, bagsLeft do addOrQueue(player, BAG, 1, overflow) end
    local left, wornCount = equipSet(player, kit.pve, false)
    for _, id in ipairs(left) do addOrQueue(player, id, 1, overflow) end
    for _, id in ipairs(kit.pvp or {}) do addOrQueue(player, id, 1, overflow) end
    local med = KITS.MEDALLION
    if med then addOrQueue(player, (try(player, "GetTeam") == TEAM_HORDE) and med.horde or med.alliance, 1, overflow) end
    for _, e in ipairs(CLASS_ITEMS[player:GetClass()] or {}) do addOrQueue(player, e[1], e[2], overflow) end
    selectAmmo(player)
    return mailOverflow(player, overflow), #overflow, wornCount
end

local function step(player, what, f, ...)
    local ok, err = pcall(f, ...)
    if not ok then
        print(string.format("[ov_main] boost of %s: %s failed: %s", tostring(try(player, "GetName")), what, tostring(err)))
    end
    return ok
end

------------------------------------------------------------------------------------------------ the action bars
local SMSG_ACTION_BUTTONS = 0x129          -- Opcodes.h
local MAX_ACTION_BUTTONS = 144             -- Player.h
local ACTION_SPELL, ACTION_ITEM = 0x00, 0x80
local ACTION_TYPE_SHIFT = 16777216         -- packed = action | type << 24 (ACTION_BUTTON_PACK)
local FIRST_BONUS_BUTTON = 72              -- below this a spell is placed once; stance / form bars repeat them
local HEARTHSTONE = 6948
local SPEC_ACTIVATE = { [0] = 63645, [1] = 63644 } -- Activate Primary Spec / Activate Secondary Spec
local POWER_MANA, POWER_ENERGY = 0, 3
local BAR_STEP_MS = 2000
-- Rows are placed in this order, so a spell named twice below button 72 keeps its first (more important) place.
local ROW_ORDER = { 0, 72, 84, 96, 108, 60, 48, 24, 36, 12 }

-- [guid] = { spec = key, kit = bool, applied = bool, waiting = { [0] = { [button] = true }, [1] = ... } } for
-- boosted characters this session (characters.ov_boost_bars keeps it across sessions)
local barState = {}

local function buttonList(set)
    local list = {}
    for button in pairs(set or {}) do list[#list + 1] = button end
    table.sort(list)
    return table.concat(list, ",")
end

local function buttonSet(text)
    local set = {}
    for n in tostring(text or ""):gmatch("%d+") do set[tonumber(n)] = true end
    return set
end

local function saveBarState(guid, st)
    CharDBExecute(string.format("UPDATE ov_boost_bars SET applied_at = %d, waiting0 = '%s', waiting1 = '%s' WHERE guid = %d",
        st.applied and os.time() or 0, buttonList(st.waiting[0]), buttonList(st.waiting[1]), guid))
end

-- The class rows with the spec's rows over them: rows[firstButton] = { entries }
local function layoutRows(cls, specKey)
    local c = BARS[cls]
    if not c then return nil end
    local rows = {}
    for start, row in pairs(c.base or {}) do rows[start] = row end
    for start, row in pairs(c[specKey] or {}) do rows[start] = row end
    return rows
end

local function layoutSpellIds(rows)
    local set, list = {}, {}
    local function add(id)
        if type(id) == "number" and id > 0 and not set[id] then set[id] = true; list[#list + 1] = id end
    end
    for _, row in pairs(rows) do
        for _, e in ipairs(row) do
            if type(e) == "table" then for _, a in ipairs(e) do add(a) end else add(e) end
        end
    end
    table.sort(list)
    return list
end

-- chains[rank-1 id] = { its ranks, highest first } (world spell_ranks; spells with one rank have no rows)
local function rankChains(ids)
    local chains = {}
    if #ids == 0 then return chains end
    local q = WorldDBQuery("SELECT first_spell_id, spell_id FROM spell_ranks WHERE first_spell_id IN (" ..
        table.concat(ids, ",") .. ") ORDER BY first_spell_id, `rank` DESC")
    if q then
        repeat
            local first, id = q:GetUInt32(0), q:GetUInt32(1)
            chains[first] = chains[first] or {}
            table.insert(chains[first], id)
        until not q:NextRow()
    end
    return chains
end

local function bestRank(player, id, chains)
    for _, s in ipairs(chains[id] or {}) do
        if player:HasSpell(s) then return s end
    end
    if player:HasSpell(id) then return id end
    return nil
end

-- What the layout puts on each button now: buttons[button] = { action, type }; waiting[button] = the spell
-- entry the character doesn't know yet (a talent); covered[button] = true for every button of the layout's rows.
local function resolveLayout(player, specKey, withKit)
    local rows = layoutRows(player:GetClass(), specKey)
    if not rows then return nil end
    local chains = rankChains(layoutSpellIds(rows))
    local buttons, waiting, covered, placed = {}, {}, {}, {}
    local function spellOf(e)
        if type(e) == "number" then return bestRank(player, e, chains) end
        for _, a in ipairs(e) do
            local s = bestRank(player, a, chains)
            if s then return s end
        end
    end
    for _, start in ipairs(ROW_ORDER) do
        for i, e in ipairs(rows[start] or {}) do
            local button = start + i - 1
            if button < MAX_ACTION_BUTTONS then
                covered[button] = true
                local action, kind = nil, ACTION_SPELL
                if e == HEARTH then
                    action, kind = HEARTHSTONE, ACTION_ITEM
                elseif e == PVP then
                    local med = withKit and KITS and KITS.MEDALLION
                    if med then
                        action, kind = (try(player, "GetTeam") == TEAM_HORDE) and med.horde or med.alliance, ACTION_ITEM
                    end
                elseif e == GROUND or e == FLY then
                    local m = MOUNTS[e == GROUND and 1 or 2]
                    if player:HasSpell(m) then action = m end
                elseif e == RACIAL then
                    for _, r in ipairs(RACIALS) do
                        if player:HasSpell(r) then action = r; break end
                    end
                elseif e ~= 0 then
                    action = spellOf(e)
                    if not action then waiting[button] = e end
                end
                if action then
                    local key = kind .. ":" .. action
                    if button >= FIRST_BONUS_BUTTON or not placed[key] then
                        buttons[button] = { action, kind }
                        if button < FIRST_BONUS_BUTTON then placed[key] = true end
                    end
                end
            end
        end
    end
    return buttons, waiting, covered, chains
end

-- The character's saved buttons for a spec: rows[button] = { action, type }
local function savedButtons(guid, spec)
    local saved = {}
    local q = CharDBQuery(string.format(
        "SELECT button, action, type FROM character_action WHERE guid = %d AND spec = %d", guid, spec))
    if q then
        repeat saved[q:GetUInt32(0)] = { q:GetUInt32(1), q:GetUInt32(2) } until not q:NextRow()
    end
    return saved
end

local function packButton(b) return b[1] + b[2] * ACTION_TYPE_SHIFT end

-- SMSG_ACTION_BUTTONS as Player::SendActionButtons builds it: uint8 state (1 = here are the buttons), then
-- uint32 packed action | type << 24 for each of the 144 buttons (0 = empty).
local function buildButtonsPacket(buttons)
    if type(CreatePacket) ~= "function" then return nil end
    local pkt = CreatePacket(SMSG_ACTION_BUTTONS, 1 + MAX_ACTION_BUTTONS * 4)
    pkt:WriteUByte(1)
    for button = 0, MAX_ACTION_BUTTONS - 1 do
        local b = buttons[button]
        pkt:WriteULong(b and packButton(b) or 0)
    end
    return pkt
end

local function sendButtons(player, buttons)
    local pkt = buildButtonsPacket(buttons)
    if not pkt then return false end
    player:SendPacket(pkt)
    return true
end

-- Replaces the given buttons' rows of one spec: the covered ones are deleted, the set ones written.
local function writeButtons(guid, spec, buttons, covered)
    local del, vals = {}, {}
    for button = 0, MAX_ACTION_BUTTONS - 1 do
        if covered[button] then
            del[#del + 1] = button
            local b = buttons[button]
            if b then vals[#vals + 1] = string.format("(%d, %d, %d, %d, %d)", guid, spec, button, b[1], b[2]) end
        end
    end
    if #del > 0 then
        CharDBExecute(string.format("DELETE FROM character_action WHERE guid = %d AND spec = %d AND button IN (%s)",
            guid, spec, table.concat(del, ",")))
    end
    if #vals > 0 then
        CharDBExecute("INSERT INTO character_action (guid, spec, button, action, type) VALUES " ..
            table.concat(vals, ", ") .. " ON DUPLICATE KEY UPDATE action = VALUES(action), type = VALUES(type)")
    end
end

local function later(player, ms, what, f)
    player:RegisterEvent(function(_, _, _, p)
        if not p then return end
        local ok, err = pcall(f, p)
        if not ok then print(string.format("[ov_main] bars of %s: %s failed: %s", tostring(try(p, "GetName")), what, tostring(err))) end
    end, ms, 1)
end

local function canSwitchSpec(player)
    if (try(player, "GetSpecsCount") or 1) < 2 then return false end
    if player:IsInCombat() or try(player, "InBattleground") == true or try(player, "InArena") == true then return false end
    return true
end

-- Steps 3 and 4: switch to the second spec and back, so ActivateSpec reloads the buttons from character_action.
local function syncSpecSwitch(player)
    if (try(player, "GetActiveSpec") or 0) ~= 0 or not canSwitchSpec(player) then return end
    player:CastSpell(player, SPEC_ACTIVATE[1], true)
    later(player, BAR_STEP_MS, "spec switch back", function(p)
        if (try(p, "GetActiveSpec") or 0) == 1 then p:CastSpell(p, SPEC_ACTIVATE[0], true) end
        if (try(p, "GetActiveSpec") or 0) ~= 0 then
            print(string.format("[ov_main] bars of %s: still in the second spec after the switch back", tostring(try(p, "GetName"))))
        end
        local maxMana = try(p, "GetMaxPower", POWER_MANA) or 0
        if maxMana > 0 then try(p, "SetPower", maxMana, POWER_MANA) end   -- ActivateSpec zeroes power
        if try(p, "GetPowerType") == POWER_ENERGY then try(p, "SetPower", try(p, "GetMaxPower", POWER_ENERGY) or 100, POWER_ENERGY) end
    end)
end

-- Step 2: write the layout for both specs, show it, then sync the server's copy.
local function writeBars(player)
    local guid = player:GetGUIDLow()
    local st = barState[guid]
    if not st or st.applied then return end
    local buttons, waiting, covered = resolveLayout(player, st.spec, st.kit)
    if not buttons then st.applied = true; return end
    local active = try(player, "GetActiveSpec") or 0
    local specs = (try(player, "GetSpecsCount") or 1) >= 2 and { 0, 1 } or { active }
    -- buttons outside the layout's rows stay (anything a Death Knight set before boosting), unless they hold
    -- a spell the layout placed too
    local placed = {}
    for _, b in pairs(buttons) do placed[b[2] .. ":" .. b[1]] = true end
    local shown = {}
    for button, b in pairs(savedButtons(guid, active)) do
        if not covered[button] then
            if placed[b[2] .. ":" .. b[1]] then covered[button] = true else shown[button] = b end
        end
    end
    for button, b in pairs(buttons) do shown[button] = b end
    for _, spec in ipairs(specs) do writeButtons(guid, spec, buttons, covered) end
    sendButtons(player, shown)
    st.applied = true
    st.waiting = { [0] = {}, [1] = {} }
    for button in pairs(waiting) do st.waiting[0][button] = true; st.waiting[1][button] = true end
    saveBarState(guid, st)
    local n, w = 0, 0
    for _ in pairs(buttons) do n = n + 1 end
    for _ in pairs(waiting) do w = w + 1 end
    say(player, string.format("%d spells and items are on your action bars%s. Turn on the extra bars in Esc > " ..
        "Interface > ActionBars (bottom left, bottom right, right).", n,
        w > 0 and string.format(" (%d buttons wait for talents: learn one and it goes in its place)", w) or ""))
    later(player, BAR_STEP_MS, "spec switch", syncSpecSwitch)
end

-- Step 1 (after the boost, or at login while the bars are still pending): save, so every in-memory button is
-- in character_action and unchanged (a later save then writes none of them over the layout).
local function startBars(player, delay)
    later(player, delay or BAR_STEP_MS, "save", function(p)
        if try(p, "IsInWorld") == false then return startBars(p) end   -- still behind a loading screen
        p:SaveToDB()
        later(p, BAR_STEP_MS, "write", writeBars)
    end)
end

-- After a talent: teach its trainer ranks, wear what the new talent allows (a second weapon with Dual Wield),
-- then put the layout's spells that were waiting for a talent on their buttons (active spec), unless the player
-- has put something else there.
local talentPending = {}
local function placeWaiting(player)
    local guid = player:GetGUIDLow()
    local st = barState[guid]
    local active = try(player, "GetActiveSpec") or 0
    local waiting = st and st.waiting and st.waiting[active]
    if not waiting or next(waiting) == nil then return end
    local buttons = resolveLayout(player, st.spec, st.kit)
    if not buttons then return end
    local saved = savedButtons(guid, active)
    local onBars = {}
    for button, b in pairs(saved) do
        if b[2] == ACTION_SPELL and not player:HasSpell(b[1]) then
            saved[button] = nil                     -- a spell no longer known (talents reset): free again
        elseif button < FIRST_BONUS_BUTTON then
            onBars[b[2] .. ":" .. b[1]] = true
        end
    end
    local new, covered, changed = {}, {}, false
    for button = 0, MAX_ACTION_BUTTONS - 1 do
        local b = waiting[button] and buttons[button]
        if b then
            waiting[button], changed = nil, true
            local key = b[2] .. ":" .. b[1]
            if not saved[button] and (button >= FIRST_BONUS_BUTTON or not onBars[key]) then
                new[button], covered[button] = b, true
                if button < FIRST_BONUS_BUTTON then onBars[key] = true end
            end
        end
    end
    if changed then saveBarState(guid, st) end
    if next(new) == nil then return end
    writeButtons(guid, active, new, covered)
    for button, b in pairs(new) do saved[button] = b end
    sendButtons(player, saved)
end

local function afterTalent(player)
    local guid = player:GetGUIDLow()
    talentPending[guid] = nil
    local st = barState[guid]
    if not st then return end
    learnClassSpells(player)
    local kit = kitFor(player, st.spec)
    if kit and st.kit then equipSet(player, kit.pve, true) end
    if not st.applied then return end
    player:SaveToDB()                               -- buttons the player just moved are in the rows first
    later(player, 1000, "talent buttons", placeWaiting)
end

-- After a talent reset: the layout's talent buttons wait again (their rows go at the next login, as the core
-- drops buttons of unknown spells).
local function afterTalentReset(player)
    local guid = player:GetGUIDLow()
    local st = barState[guid]
    if not st or not st.applied then return end
    local active = try(player, "GetActiveSpec") or 0
    local _, waiting = resolveLayout(player, st.spec, st.kit)
    st.waiting[active] = waiting and (function() local w = {}; for b in pairs(waiting) do w[b] = true end; return w end)() or {}
    saveBarState(guid, st)
end

local function loadBarState(guid)
    local q = CharDBQuery(string.format(
        "SELECT spec, kit, applied_at, waiting0, waiting1 FROM ov_boost_bars WHERE guid = %d", guid))
    if not q then return nil end
    return { spec = q:GetString(0), kit = q:GetUInt32(1) == 1, applied = q:GetUInt32(2) > 0,
             waiting = { [0] = buttonSet(q:GetString(3)), [1] = buttonSet(q:GetString(4)) } }
end

local function doBoost(player, state)
    local ok, why = canBoost(player)
    if not ok then
        if why == "done" then say(player, "This character has already been boosted.") end
        return false
    end
    if player:IsInCombat() then say(player, "Not in combat."); return false end
    local kit = kitFor(player, state.spec)
    if not kit then return false end

    local guid, account = player:GetGUIDLow(), player:GetAccountId()
    local cap = num("OV_BOOST_KITS_PER_ACCOUNT", 10)
    local used = queryValue(string.format("SELECT COUNT(*) AS n FROM ov_boosts WHERE account_id = %d", account)) or 0
    local withKit = used < cap
    -- Recorded before anything is granted: a second attempt (another menu click, a relog, .boost) is refused.
    busy[guid] = true
    pending[guid] = nil
    CharDBExecute(string.format("INSERT IGNORE INTO ov_boosts (char_guid, account_id, boosted_at) VALUES (%d, %d, %d)",
        guid, account, os.time()))
    setChoice(player, "boost", state.spec)

    step(player, "level", function() player:SetLevel(BOOST_LEVEL) end)
    local spells = 0
    step(player, "class spells", function() spells = learnClassSpells(player) end)
    step(player, "weapon skills", function()
        learnList(player, WEAPON_SPELLS[player:GetClass()])
        player:AdvanceSkillsToMax()
    end)
    step(player, "riding", function() learnList(player, RIDING); learnList(player, MOUNTS) end)
    step(player, "dual spec", function()
        if (try(player, "GetSpecsCount") or 1) < 2 then
            player:CastSpell(player, 63680, true)
            player:CastSpell(player, 63624, true)
        end
    end)
    step(player, "professions", function()
        for _, s in ipairs(state.profs or {}) do
            for _, p in ipairs(PRIMARY) do if p[1] == s then maxProfession(player, p[1], p[2]) end end
        end
        for _, p in ipairs(PRIMARY) do   -- professions the character already had
            if player:HasSkill(p[1]) then maxProfession(player, p[1], p[2]) end
        end
        for _, p in ipairs(SECONDARY) do maxProfession(player, p[1], p[2]) end
    end)
    local mails, mailed, wornCount = 0, 0, 0
    if withKit then
        step(player, "kit", function() mails, mailed, wornCount = giveItems(player, kit) end)
        local gold = num("OV_BOOST_GOLD", 0)
        if gold > 0 then step(player, "gold", function() player:ModifyMoney(gold * 10000) end) end
    end
    step(player, "Dalaran", function()
        player:SetBindPoint(DALARAN.x, DALARAN.y, DALARAN.z, DALARAN.map, DALARAN.zone)
        player:Teleport(DALARAN.map, DALARAN.x, DALARAN.y, DALARAN.z, DALARAN.o)
    end)
    player:SaveToDB()
    -- the action bars: a few seconds from now, once the character is in Dalaran (see "Bars" at the top)
    step(player, "bars", function()
        barState[guid] = { spec = state.spec, kit = withKit, applied = false, waiting = { [0] = {}, [1] = {} } }
        CharDBExecute(string.format("REPLACE INTO ov_boost_bars (guid, spec, kit, applied_at, waiting0, waiting1) " ..
            "VALUES (%d, '%s', %d, 0, '', '')", guid, state.spec, withKit and 1 or 0))
        startBars(player)
    end)

    say(player, string.format("Boosted to %d as %s: %d class spells, riding, dual spec and professions learned.",
        BOOST_LEVEL, kit.name, spells))
    if withKit then
        say(player, string.format("You are wearing your PvE set (%d pieces); the PvP set and the rest are in your bags", wornCount) ..
            (mailed > 0 and string.format(" (%d item%s by mail, see the Dalaran mailbox)", mailed, mailed == 1 and "" or "s") or "") ..
            ". Spend your talent points (N), then set up your second spec at any class trainer's talent pane.")
    else
        say(player, string.format("This account has had its %d boost kits, so no gear came with this boost.", cap))
    end
    return true
end

------------------------------------------------------------------------------------------------ events
-- guid -> true once the player has touched the menu this session (any selection): the retries stop then.
local touched = {}

local function onSelect(event, player, object, sender, intid, code, menuId)
    -- mod-ale calls player-menu selects as (event, player, object, sender, intid, code): no menu id
    -- (it is the binding's key), so menuId is nil live. Only a present, different id is someone else's.
    if not on() or not player or (menuId ~= nil and menuId ~= MENU_ID) then return end
    local guid = player:GetGUIDLow()
    touched[guid] = true
    if not canBoost(player) then return player:GossipComplete() end

    if intid == 1 then
        setChoice(player, "level1", "")
        pending[guid] = nil
        say(player, "Good luck out there! Changed your mind? Type .boost while you are below level " ..
            (player:GetClass() == CLASS_DK and MAX_LEVEL_TO_BOOST_DK or MAX_LEVEL_TO_BOOST) .. ".")
        return player:GossipComplete()
    elseif intid == 2 then
        return showSpecs(player)
    elseif intid == 3 then
        pending[guid] = nil
        return showChoice(player)
    elseif intid >= 11 and intid < 100 then
        local order = KITS.order[player:GetClass()] or {}
        local key = order[intid - 10]
        if not key then return player:GossipComplete() end
        pending[guid] = { spec = key, profs = {} }
        if showProfessions(player, pending[guid]) then return end
        player:GossipComplete()
        return doBoost(player, pending[guid] or { spec = key, profs = {} })
    elseif intid > 1000 then
        local state = pending[guid]
        if not state then return player:GossipComplete() end
        local skill = intid - 1000
        local valid = false
        for _, p in ipairs(PRIMARY) do if p[1] == skill and not player:HasSkill(skill) then valid = true end end
        for _, s in ipairs(state.profs) do if s == skill then valid = false end end
        if valid and primariesKnown(player) + #state.profs < MAX_PRIMARY then state.profs[#state.profs + 1] = skill end
        if showProfessions(player, state) then return end
        player:GossipComplete()
        return doBoost(player, state)
    elseif intid == 999 then
        local state = pending[guid]
        player:GossipComplete()
        if state then return doBoost(player, state) end
        return
    end
    player:GossipComplete()
end

-- The menu is sent again a few times after login while the choice is still open and the player hasn't
-- touched it. A browser client can still be behind its loading screen when the first one arrives (and drops
-- it), and a slice rule teleport right after login closes it; a window that is already open is simply
-- replaced. Stops at the first selection, or once the choice is made.
local MENU_RETRIES_MS = { 3000, 15000, 35000, 60000, 100000, 150000 }
local function openMenuSoon(player)
    local guid = player:GetGUIDLow()
    touched[guid] = nil
    for _, ms in ipairs(MENU_RETRIES_MS) do
        player:RegisterEvent(function(_, _, _, p)
            if not p or not on() then return end
            local g = p:GetGUIDLow()
            if touched[g] or not canBoost(p) then return end
            showChoice(p)
        end, ms, 1)
    end
end

-- Every new character (not Death Knights, who get theirs in the Ebon Hold story) starts with Apprentice
-- Riding and its race's basic mount, so even level 1 can ride. Spell ids checked against AzerothCore's
-- item_template (the mount spell each race's level-20 vendor mount teaches) and trainer_spell (33388).
local APPRENTICE_RIDING = 33388
local START_MOUNT = {
    [1] = 458,    -- Human: Brown Horse
    [2] = 580,    -- Orc: Timber Wolf
    [3] = 6899,   -- Dwarf: Brown Ram
    [4] = 10793,  -- Night Elf: Striped Nightsaber
    [5] = 17464,  -- Undead: Brown Skeletal Horse
    [6] = 18990,  -- Tauren: Brown Kodo
    [7] = 10873,  -- Gnome: Red Mechanostrider
    [8] = 8395,   -- Troll: Emerald Raptor
    [10] = 34795, -- Blood Elf: Red Hawkstrider
    [11] = 34406, -- Draenei: Brown Elekk
}
local function giveStartMount(player)
    if player:GetClass() == CLASS_DK then return end
    local mount = START_MOUNT[player:GetRace()]
    if not mount then return end
    if not player:HasSpell(APPRENTICE_RIDING) then player:LearnSpell(APPRENTICE_RIDING) end
    if not player:HasSpell(mount) then player:LearnSpell(mount) end
    player:RegisterEvent(function(_, _, _, p)
        if p then say(p, "You can ride from level 1: your mount is in the spellbook (Pet/Mounts tab, |cffffff00Shift+P|r).") end
    end, 6000, 1)
end

local function onFirstLogin(event, player)
    if not on() or not player or isBot(player) then return end
    giveStartMount(player)
    if not canBoost(player) then return end
    setChoice(player, "pending", "")
    openMenuSoon(player)
end

-- The core fires ON_LOGIN before ON_FIRST_LOGIN (CharacterHandler.cpp), so on the first login there is no
-- ov_main_choice row yet and no reminder: only the menu.
local function onLogin(event, player)
    if not on() or not player or isBot(player) then return end
    local guid = player:GetGUIDLow()
    barState[guid] = loadBarState(guid)
    if barState[guid] and not barState[guid].applied then startBars(player, 5000) end   -- logged out too soon
    if choiceOf(guid) ~= "pending" then return end
    if canBoost(player) then
        say(player, "You haven't chosen yet: type |cffffff00.boost|r to boost this character to 80, or just play on.")
        openMenuSoon(player)   -- the choice window again, once the client is in the world
    end
end

local function onCommand(event, player, command)
    if not player then return end
    touched[player:GetGUIDLow()] = true
    local cmd = (command or ""):gsub("^[%.!]", ""):lower():gsub("%s+$", "")
    if cmd ~= "boost" then return end
    if not on() then return end   -- other realms: let the core answer
    local ok, why = canBoost(player)
    if ok then
        showSpecs(player)
    elseif why == "done" then
        say(player, "This character has already been boosted.")
    elseif why == "level" then
        say(player, string.format(".boost is only for new characters (below level %d, Death Knights below %d).",
            MAX_LEVEL_TO_BOOST, MAX_LEVEL_TO_BOOST_DK))
    end
    return false
end

local function onDelete(event, guid)
    if not on() then return end
    local low = type(guid) == "number" and guid or tonumber(tostring(guid)) or 0
    -- ov_boosts rows stay: they count toward the account's kit cap even after the character is gone
    if low > 0 then
        CharDBExecute(string.format("DELETE FROM ov_main_choice WHERE guid = %d", low))
        CharDBExecute(string.format("DELETE FROM ov_boost_bars WHERE guid = %d", low))
    end
end

CharDBExecute([[CREATE TABLE IF NOT EXISTS ov_main_choice (
    guid INT UNSIGNED NOT NULL PRIMARY KEY,
    account INT UNSIGNED NOT NULL,
    choice VARCHAR(8) NOT NULL,
    spec VARCHAR(16) NOT NULL DEFAULT '',
    created_at INT UNSIGNED NOT NULL,
    decided_at INT UNSIGNED NOT NULL DEFAULT 0,
    KEY account (account)
)]])
-- Same definition as ov_services.lua (whichever file loads first creates it).
CharDBExecute([[CREATE TABLE IF NOT EXISTS ov_boosts (
    char_guid INT UNSIGNED NOT NULL PRIMARY KEY,
    account_id INT UNSIGNED NOT NULL,
    boosted_at INT UNSIGNED NOT NULL,
    KEY account (account_id)
)]])

-- A boosted character's bars, until they are written, and the buttons that wait for talents.
CharDBExecute([[CREATE TABLE IF NOT EXISTS ov_boost_bars (
    guid INT UNSIGNED NOT NULL PRIMARY KEY,
    spec VARCHAR(16) NOT NULL DEFAULT '',
    kit TINYINT UNSIGNED NOT NULL DEFAULT 0,
    applied_at INT UNSIGNED NOT NULL DEFAULT 0,
    waiting0 VARCHAR(600) NOT NULL DEFAULT '',
    waiting1 VARCHAR(600) NOT NULL DEFAULT ''
)]])

-- Talents of a boosted character: a short wait so a row of talent clicks is handled once.
local function onTalent(event, player)
    if not on() or not player then return end
    local guid = player:GetGUIDLow()
    if not barState[guid] or talentPending[guid] then return end
    talentPending[guid] = true
    later(player, 1500, "talent", afterTalent)
end

local function onTalentReset(event, player)
    if not on() or not player or not barState[player:GetGUIDLow()] then return end
    later(player, 1000, "talent reset", afterTalentReset)
end

RegisterPlayerEvent(30, onFirstLogin) -- PLAYER_EVENT_ON_FIRST_LOGIN
RegisterPlayerEvent(3, onLogin)       -- PLAYER_EVENT_ON_LOGIN
RegisterPlayerEvent(42, onCommand)    -- PLAYER_EVENT_ON_COMMAND
RegisterPlayerEvent(2, onDelete)      -- PLAYER_EVENT_ON_CHARACTER_DELETE
RegisterPlayerEvent(39, onTalent)      -- PLAYER_EVENT_ON_LEARN_TALENTS
RegisterPlayerEvent(17, onTalentReset) -- PLAYER_EVENT_ON_TALENTS_RESET
RegisterPlayerGossipEvent(MENU_ID, 2, onSelect)

-- for tests/test_ov_boost.lua (read only)
OV_MAIN_TEST = { BARS = BARS, RACIALS = RACIALS, INV_SLOTS = INV_SLOTS, resolveLayout = resolveLayout,
    buildButtonsPacket = buildButtonsPacket, layoutRows = layoutRows, equipSet = equipSet, barState = barState,
    SMSG_ACTION_BUTTONS = SMSG_ACTION_BUTTONS, MAX_ACTION_BUTTONS = MAX_ACTION_BUTTONS }
