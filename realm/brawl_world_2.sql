-- Wrath Brawl, round two (owner decisions 2026-10-24): no gold cost, professions maxed,
-- free dual spec, starter bags, class kits, two mounts. Applies to acore_world after
-- brawl_world.sql; "Make it Brawl.bat" runs both. Safe to run again.
-- Free faction/race/appearance change is the .ov menu (custom/lua_scripts/ov_services.lua).

-- 1. No gold cost: every item a vendor sells is free, and sells for nothing (so free items
--    can't be turned into gold).
UPDATE `item_template` SET `BuyPrice` = 0, `SellPrice` = 0
WHERE `entry` IN (SELECT `item` FROM (SELECT DISTINCT `item` FROM `npc_vendor`) AS v);

-- 2. Dual talent spec costs nothing at the class trainer (gossip option type 18).
UPDATE `gossip_menu_option` SET `BoxMoney` = 0 WHERE `OptionType` = 18;

-- 3. Professions maxed: the Grand Master rank of every primary and secondary profession, plus
--    every recipe a profession trainer teaches. profiles/brawl.env raises MaxPrimaryTradeSkill so
--    all of them fit, and custom/lua_scripts/ov_brawl.lua sets each skill to 450 at first login
--    (needs the custom realm image; the stock image leaves the skills at 1/450).
DELETE FROM `playercreateinfo_skills` WHERE `comment` = 'brawl';
DELETE FROM `playercreateinfo_spell_custom` WHERE `Note` = 'brawl2';
INSERT IGNORE INTO `playercreateinfo_spell_custom` (`racemask`,`classmask`,`Spell`,`Note`) VALUES
(0,0,51304,'brawl2'),(0,0,51300,'brawl2'),(0,0,51313,'brawl2'),(0,0,51306,'brawl2'),
(0,0,50300,'brawl2'),(0,0,45363,'brawl2'),(0,0,51311,'brawl2'),(0,0,51302,'brawl2'),
(0,0,50310,'brawl2'),(0,0,51309,'brawl2'),(0,0,50305,'brawl2'),(0,0,51296,'brawl2'),
(0,0,45542,'brawl2'),(0,0,51294,'brawl2');
-- Recipes come from trainer/trainer_spell (Type 2 = tradeskill), the tables the core actually
-- loads (ObjectMgr::LoadTrainers on AzerothCore master and the pinned playerbots fork);
-- npc_trainer is legacy data the core no longer reads.
INSERT IGNORE INTO `playercreateinfo_spell_custom` (`racemask`,`classmask`,`Spell`,`Note`)
SELECT DISTINCT 0, 0, ts.`SpellId`, 'brawl2'
FROM `trainer_spell` ts JOIN `trainer` t ON t.`Id` = ts.`TrainerId`
WHERE t.`Type` = 2 AND ts.`SpellId` > 0
  AND ts.`ReqSkillLine` IN (164,165,171,182,186,197,202,333,393,755,773,185,129,356);

-- 3b. Weapon skills, so Armory weapons can be equipped. Each class gets only the weapon types it
--     can train at a 3.3.5a weapon master (classmask = 1 << (class - 1)); AlwaysMaxSkillForLevel
--     raises them to 400. 196 1H axe, 197 2H axe, 198 1H mace, 199 2H mace, 200 polearm,
--     201 1H sword, 202 2H sword, 227 staff, 264 bow, 266 gun, 1180 dagger, 2567 thrown,
--     5011 crossbow, 5009 wand, 15590 fist.
INSERT IGNORE INTO `playercreateinfo_spell_custom` (`racemask`,`classmask`,`Spell`,`Note`) VALUES
-- Warrior (1)
(0,1,196,'brawl2'),(0,1,197,'brawl2'),(0,1,198,'brawl2'),(0,1,199,'brawl2'),(0,1,200,'brawl2'),
(0,1,201,'brawl2'),(0,1,202,'brawl2'),(0,1,227,'brawl2'),(0,1,264,'brawl2'),(0,1,266,'brawl2'),
(0,1,1180,'brawl2'),(0,1,2567,'brawl2'),(0,1,5011,'brawl2'),(0,1,15590,'brawl2'),
-- Paladin (2)
(0,2,196,'brawl2'),(0,2,197,'brawl2'),(0,2,198,'brawl2'),(0,2,199,'brawl2'),(0,2,200,'brawl2'),
(0,2,201,'brawl2'),(0,2,202,'brawl2'),
-- Hunter (4)
(0,4,196,'brawl2'),(0,4,197,'brawl2'),(0,4,200,'brawl2'),(0,4,201,'brawl2'),(0,4,202,'brawl2'),
(0,4,227,'brawl2'),(0,4,264,'brawl2'),(0,4,266,'brawl2'),(0,4,1180,'brawl2'),(0,4,2567,'brawl2'),
(0,4,5011,'brawl2'),(0,4,15590,'brawl2'),
-- Rogue (8)
(0,8,196,'brawl2'),(0,8,198,'brawl2'),(0,8,201,'brawl2'),(0,8,264,'brawl2'),(0,8,266,'brawl2'),
(0,8,1180,'brawl2'),(0,8,2567,'brawl2'),(0,8,5011,'brawl2'),(0,8,15590,'brawl2'),
-- Priest (16)
(0,16,198,'brawl2'),(0,16,227,'brawl2'),(0,16,1180,'brawl2'),(0,16,5009,'brawl2'),
-- Death Knight (32), plus Death Gate (normally from the Ebon Hold quests)
(0,32,196,'brawl2'),(0,32,197,'brawl2'),(0,32,198,'brawl2'),(0,32,199,'brawl2'),(0,32,200,'brawl2'),
(0,32,201,'brawl2'),(0,32,202,'brawl2'),(0,32,50977,'brawl2'),
-- Shaman (64)
(0,64,196,'brawl2'),(0,64,197,'brawl2'),(0,64,198,'brawl2'),(0,64,199,'brawl2'),(0,64,227,'brawl2'),
(0,64,1180,'brawl2'),(0,64,15590,'brawl2'),
-- Mage (128)
(0,128,201,'brawl2'),(0,128,227,'brawl2'),(0,128,1180,'brawl2'),(0,128,5009,'brawl2'),
-- Warlock (256)
(0,256,201,'brawl2'),(0,256,227,'brawl2'),(0,256,1180,'brawl2'),(0,256,5009,'brawl2'),
-- Druid (1024)
(0,1024,198,'brawl2'),(0,1024,199,'brawl2'),(0,1024,200,'brawl2'),(0,1024,227,'brawl2'),
(0,1024,1180,'brawl2'),(0,1024,15590,'brawl2');

-- 4. Mounts: Albino Drake (flying) and Swift Zhevra (ground, for no-fly Dalaran); Death
--    Knights get Runeforging, which normally comes from their starting quests.
INSERT IGNORE INTO `playercreateinfo_spell_custom` (`racemask`,`classmask`,`Spell`,`Note`) VALUES
(0,0,60025,'brawl2'),(0,0,49322,'brawl2'),(0,32,53428,'brawl2');

-- 5. Starter bags and class kits (race 0 / class 0 = everyone).
DELETE FROM `playercreateinfo_item` WHERE `itemid` IN
(41599,5175,5176,5177,5178,21340,41165,41164,17020,17031,17032,44615,44605,21177,17030);
INSERT INTO `playercreateinfo_item` (`race`,`class`,`itemid`,`amount`) VALUES
(0,0,41599,4),                                   -- four Frostweave Bags (20 slots)
(0,7,5175,1),(0,7,5176,1),(0,7,5177,1),(0,7,5178,1), -- shaman Earth/Fire/Water/Air totems
(0,9,21340,1),                                   -- warlock Soul Pouch
(0,3,41165,1000),(0,3,41164,1000),               -- hunter arrows and bullets
(0,8,17020,20),(0,8,17031,10),(0,8,17032,10),    -- mage Arcane Powder, teleport/portal runes
(0,5,44615,20),                                  -- priest Devout Candles
(0,11,44605,20),                                 -- druid Wild Spineleaf
(0,2,21177,100),                                 -- paladin Symbols of Kings
(0,7,17030,10);                                  -- shaman Ankhs
