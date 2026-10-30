-- WrathUnleashed MAIN realm: world rows for custom/lua_scripts/ov_main.lua (the level 1 / boost to 80 choice).
-- Applies to acore_world. Adds only new rows (gossip texts 61010-61013, unused in stock data); changes nothing
-- else. Safe to run again. deploy.sh applies it for WU_PROFILE=main, after main_unbrawl.sql.
-- (npc_text is cached by the game client per id: if you change a text later, give it a new id in both files.)
DELETE FROM `npc_text` WHERE `ID` BETWEEN 61010 AND 61013;
INSERT INTO `npc_text` (`ID`, `text0_0`, `text0_1`, `Probability0`) VALUES
(61010, 'Welcome to WrathUnleashed, $N.$B$BHow do you want to start this character?$B$B- From the beginning: the normal game, your race''s starting zone, levelling, trainers and professions.$B$B- Boosted to level 80: every class spell, riding with Cold Weather Flying and two mounts, dual specialization, two professions of your choice at 450, a PvE and a PvP set for your spec, four bags, and a trip to Dalaran.$B$BYou choose once per character.',
 'Welcome to WrathUnleashed, $N.$B$BHow do you want to start this character?$B$B- From the beginning: the normal game, your race''s starting zone, levelling, trainers and professions.$B$B- Boosted to level 80: every class spell, riding with Cold Weather Flying and two mounts, dual specialization, two professions of your choice at 450, a PvE and a PvP set for your spec, four bags, and a trip to Dalaran.$B$BYou choose once per character.', 1),
(61011, 'Which specialization is this character for?$B$BYou get its PvE set (Heroes'' tier 7, item level 200, with matching jewellery, trinkets and weapons) and its PvP set (Deadly Gladiator''s). Talent points are yours to spend.',
 'Which specialization is this character for?$B$BYou get its PvE set (Heroes'' tier 7, item level 200, with matching jewellery, trinkets and weapons) and its PvP set (Deadly Gladiator''s). Talent points are yours to spend.', 1),
(61012, 'Pick up to two primary professions: each comes at Grand Master (450) with every recipe a trainer teaches. Professions you already have are maxed too, and Cooking, First Aid and Fishing come with every boost.',
 'Pick up to two primary professions: each comes at Grand Master (450) with every recipe a trainer teaches. Professions you already have are maxed too, and Cooking, First Aid and Fishing come with every boost.', 1),
(61013, 'Your boost is done. Welcome to Dalaran!', 'Your boost is done. Welcome to Dalaran!', 1);
