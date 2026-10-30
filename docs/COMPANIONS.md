# Bots for dungeons and raids

No group? Bring bots. They fight, heal and follow you, and they are always labelled as bots.

## Commands

| Command | What it does |
|---|---|
| `.recruit party` | fills your group to 5: 1 tank, 1 healer and damage |
| `.recruit raid` | fills your group to 10: 2 tanks, 3 healers and 5 damage, and makes it a raid |
| `.recruit tank`, `healer` or `dps` `[n]` | adds bots of one role. `.recruit dps mage` picks the class. |
| `.recruit alt <name>` | brings one of your own characters as a bot, with its own gear, spec and level |
| `.companions alts` | lists the characters you can bring |
| `.companions save` | remembers the alts with you as your usual party |
| `.recruit usual` | brings your usual party back |
| `.buddy [class]` | a levelling buddy that keeps to your level. `.buddy off` sends it home. |
| `.dismiss [name\|all]` | sends bots home |
| `.companions` | help, the limits and who is with you |

The fills count what your group already has. Bring a friend who tanks, and `.recruit raid` adds one tank, not two.

In party chat you can tell bots: `follow`, `stay`, `attack`, `summon`.

## The Bots window

Type `/comp` (or `/companions`), or click the bots button on the minimap.

- **Your bots:** each bot's role, class, spec, item level, health and mana, and what it is doing: following,
  staying, passive or dead. Every one is marked as a bot.
- **Orders:** Follow, Stay, Attack my target, Passive (then Fight), Assist tank (damage bots focus the tank's
  skull target), Crowd control, a formation, and Prepare for raid (spells, gear and buffs).
- **Group:** Fill party, Fill raid, My usual party, Dismiss all.
- **Click a bot** to pick its spec, swap its role (tank, healer or damage), give it fresh gear, or send it home.
  Your alts keep their own talents and gear.

The window never types in your chat. "Hide bot chatter" (on by default) hides your bots' achievement lines and
their replies right after an order.

If the realm restarts while you have bots, they come back with you. The realm tells you, and `.dismiss all` or
the window sends them home.

## Rules

- Up to 4 bots in a party, 9 in a raid. Your alts count too.
- One `.recruit` every 30 seconds. Only the group leader recruits.
- Not in battlegrounds or arenas, not in combat and not while dead.
- Inside a dungeon or raid you can refill a slot between pulls, once nobody in the group is fighting.
- Bots leave when you log out.
- Only characters on your own account can be brought as alts.
- Raids are 10-player. 25-player raids are off for now.

## Loot

Bots always pass. They never roll need or greed, under group loot or need before greed, and that includes your alts. Under master loot they pass too.

One thing they still do: items below the group's loot threshold (grey and white) go round-robin, and a bot takes its turn like anyone. Want every item? Set loot to Free for All. Bots never loot then.

## Where bots know the fights

Bots get boss tactics on their own when they enter these places.

**Raids**

- Molten Core, Blackwing Lair, Onyxia's Lair, Ruins of Ahn'Qiraj
- Karazhan, Gruul's Lair, Magtheridon's Lair, Serpentshrine Cavern, Tempest Keep, Mount Hyjal, Black Temple, Zul'Aman
- Naxxramas, The Obsidian Sanctum, The Eye of Eternity, Vault of Archavon, Ulduar, Icecrown Citadel, The Ruby Sanctum

**Dungeons**

- Hellfire Ramparts, The Underbog, Auchenai Crypts, Sethekk Halls, The Mechanar, Magisters' Terrace
- Utgarde Keep, The Nexus, Azjol-Nerub, Ahn'kahet: The Old Kingdom, Drak'Tharon Keep, The Violet Hold, Gundrak, Halls of Stone, Halls of Lightning, The Oculus, Utgarde Pinnacle, The Culling of Stratholme, Trial of the Champion, The Forge of Souls, Pit of Saron

Everywhere else bots still fight, heal and follow. They just don't know special boss moves.
