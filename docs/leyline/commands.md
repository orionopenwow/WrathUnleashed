# Commands

Every player command on Wrath. Type them in chat. Dot commands (`.wu`) run on the realm. Slash commands (`/leyline`) run in your client's UI.

Some commands depend on the realm's preset. `.qol` shows what is on for the realm you are on. Hosts can turn parts off, so a Beacon may have fewer.

## Help

| Command | What it does |
|---|---|
| `.wu` (or `.commands`) | lists the realm's commands |
| `.qol` | shows every quality-of-life feature and whether it is on; `.qol help` for help |
| `.guide` | what to do at level 80 on this realm. It shows by itself when you reach 80. |
| `.companions` | help for bots, the bots with you and the limits |
| `.build help` | the Builder's commands and limits |

## Reports and getting unstuck

| Command | What it does |
|---|---|
| `.bug <what happened>` | files a bug report with where you are (map, zone, position, level). `.report` is the same. Reports are limited per account each hour. |
| `.stuck` | hearths you home when you are stuck. Not in combat; once every 10 minutes. |

## Bots

Bots are party members for dungeons and 10-player raids. They are always labelled as bots, and they always pass on loot.

| Command | What it does |
|---|---|
| `.recruit party` | fills a 5-player group: 1 tank, 1 healer and damage, minus what your group already has |
| `.recruit raid` | fills a 10-player raid: 2 tanks, 3 healers and 5 damage, minus what your group already has |
| `.recruit tank`, `healer` or `dps` `[n]` | recruits n bots (default 1) of one role at your level. `.recruit dps mage` picks the class. |
| `.recruit alt <name>` | brings one of your own characters as a bot, with its own gear, spec and level. `.companions alts` lists them. |
| `.companions save` | remembers the alts with you. `.recruit usual` brings them back. |
| `.buddy [class]` | one levelling buddy who keeps your level and follows you. `.buddy` shows it once you have one. `.buddy off` dismisses it. |
| `.dismiss [name\|all]` | sends bots home |
| `/comp` (or `/companions`) | the Bots window: your bots, their health and status, orders, specs and roles, all without chat |
| `.summon` | brings the bots in your group to you (open world) |

Up to 4 bots in a party and 9 in a raid. Not in battlegrounds or arenas, in combat or while dead. Inside a dungeon or raid you can refill a slot between pulls. `.companions` shows the rest in game.

On a realm without the bot module, these answer "Bots are coming soon".

## Getting around

| Command | What it does |
|---|---|
| `.go` | uses the trip waiting for you from a website link (a dungeon, raid or hangout). `.wugo` is the same. |
| `.go cancel` | forgets the waiting trip |
| `.hub <place>` | goes to a hub: `dalaran`, `gurubashi`, `maul`, `circle` or `amphitheater`. On realms with hubs on. `.qol hub dalaran` is the same. |
| `.hearth` | clears your hearthstone cooldown, once an hour |

A trip from a link waits 30 minutes. It waits while you are in combat, dead, or inside an instance, a battleground or an arena. A character below the level waits too, and tries again by itself when it levels up.

## Your character

| Command | What it does |
|---|---|
| `.boost` | reopens the one-time boost to 80, only below level 10 (a Death Knight below 58) and never boosted before. On realms with the boost. |
| `.learnall` | learns every class spell your trainer teaches up to your level, now. Once a minute. |
| `.respec confirm` | resets your active spec's talents, free |
| `.xp off`, `.xp on` | freezes or resumes experience. `.xp` says which. |
| `.mounts` | at 80, learns every ground and flying mount you don't have. Once every 10 minutes. |
| `.ov` | the free services menu: change faction, race or appearance at your next login. Nothing is sold. |

## Armory

| Command | What it does |
|---|---|
| `.armory <words>` | searches item names, rare and better, best item level first |
| `.armory give <id>` | puts that item in your bags, in the areas where Armory gear is allowed. One item a second. |
| `.armory off`, `.armory on` | hides this character from the [web armory](https://play.openvanilla.app/wrath/armory), or shows it again. The site drops it within 5 minutes. |
| `.armory privacy` | says whether this character is on the web armory |
| `/armory` | opens the Armory window (the OVArmory addon) |

## Builder

Players place props in build areas. GMs can always build. Others can build once a GM runs `.build grant <name>`. The first build area is the green in front of the Goldshire inn.

| Command | What it does |
|---|---|
| `.build catalog [word]` | the props you can place |
| `.build where` | the build areas, and whether you stand in one |
| `.build spawn <id\|name>` | a prop where you stand, facing your way. It becomes your selection. |
| `.build near` | your props within 40 yards, numbered |
| `.build select <n>` | picks prop n from `.build near` |
| `.build move x\|y\|z <yards>` | moves the selection, up to 10 yards a step |
| `.build turn <degrees>` | turns the selection (+ is to the left) |
| `.build undo` | takes back your last change |
| `.build delete` | removes the selection |
| `.build clear` | removes all your props in this area |
| `.build save <name>` | saves your props here as a build |
| `.build load <name\|code>` | pastes a build where you stand |
| `.build share <name>` | prints the build's 6-character code to give to others |
| `.build saved` | your saved builds |
| `/builder` (or `/build`) | opens the Builder window, which sends the same commands |

GM only: `.build grant <name>`, `.build revoke <name>`, `.build purge <name>`.

## Discord

| Command | What it does |
|---|---|
| `.discord off`, `.discord on` | hides or shows the `[Discord]` chat lines, when the realm has the bridge |

## Windows and UI

| Command | What it does |
|---|---|
| `/leyline` (or `/realms`) | the Leyline window: every realm on the network, with a link to copy |
| `/mods` (or `/workshop`) | the Mods & Workshop panel: UI size, addons on and off, the Workshop list |
| `/collections` | your mounts and pets, with a preview (Shift-P) |
| `/wubars` | turns every action bar on and fills it |
| `/qol` | the client's quality-of-life switches (sell grays, repair, coordinates, auto loot and more) |

## Commands from mods

These come with the example mods in the [catalog](https://play.openvanilla.app/wrath/mods), when a realm runs them.

| Command | Mod | What it does |
|---|---|---|
| `/ping` | Pings | pings where you stand for your group. `/ping attack`, `danger`, `assist` (or `help`), `onmyway` (or `omw`), `look`. Alt-click the world map pings that spot. |
| `/wheel` | Emote Wheel | a ring of eight emotes at your cursor. `/wheel set 3 kiss` puts an emote in slot 3. `/wheel reset` goes back to the default. `/emotewheel` is the same. |
| `.dice [NdS]` | Dalaran Dice | rolls dice in Dalaran, for example `.dice 3d20`. Everyone within 30 yards sees it. `.dice help` for help. |
| `/dicelog` | Dalaran Dice | shows or hides the last five rolls |

## For hosts and GMs

GM commands for running a realm are on the [Hosting](hosting.md#the-gm-account) page.
