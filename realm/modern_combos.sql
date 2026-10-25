-- WrathUnleashed: the race and class pairs retail WoW allows today (Midnight, 2026), and no
-- others. mod-arac (custom realm image) opens every pair; this keeps only retail's 83 among
-- 3.3.5a's ten races and ten classes. Every stock 3.3.5a pair is among them. Safe to run again.
-- Races: 1 Human 2 Orc 3 Dwarf 4 Night Elf 5 Undead 6 Tauren 7 Gnome 8 Troll 10 Blood Elf 11 Draenei
-- Classes: 1 Warrior 2 Paladin 3 Hunter 4 Rogue 5 Priest 6 Death Knight 7 Shaman 8 Mage 9 Warlock 11 Druid
DELETE FROM `playercreateinfo` WHERE (`race`, `class`) NOT IN ((1,1),(1,2),(1,3),(1,4),(1,5),(1,6),(1,8),(1,9),(2,1),(2,3),(2,4),(2,5),(2,6),(2,7),(2,8),(2,9),(3,1),(3,2),(3,3),(3,4),(3,5),(3,6),(3,7),(3,8),(3,9),(4,1),(4,3),(4,4),(4,5),(4,6),(4,8),(4,9),(4,11),(5,1),(5,3),(5,4),(5,5),(5,6),(5,8),(5,9),(6,1),(6,2),(6,3),(6,4),(6,5),(6,6),(6,7),(6,8),(6,9),(6,11),(7,1),(7,3),(7,4),(7,5),(7,6),(7,8),(7,9),(8,1),(8,3),(8,4),(8,5),(8,6),(8,7),(8,8),(8,9),(8,11),(10,1),(10,2),(10,3),(10,4),(10,5),(10,6),(10,8),(10,9),(11,1),(11,2),(11,3),(11,4),(11,5),(11,6),(11,7),(11,8),(11,9));
